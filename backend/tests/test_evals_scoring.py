"""Unit tests for the T11 eval scoring/metrics logic (mocked inputs, no API).

Covers the two pieces of judgment the eval turns on — fuzzy string matching and
false-confidence detection — plus the Goldsmith conventions the scorer has to
respect (empty sentinels, the unmodeled `currency` field, invoice-vs-act field
mapping) and the metric aggregation. Never touches the network, the LLM, or the
DB (CLAUDE.md testing conventions); the live end-to-end run is the integration
test.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from docflow_eval.metrics import ALL_CATEGORY, DocEval, aggregate, by_category
from docflow_eval.scoring import (
    FUZZY_MATCH_THRESHOLD,
    actual_for_field,
    confidence_for_field,
    evaluate_field,
    fuzzy_ratio,
    is_false_confidence,
    normalize_tag,
    normalize_tags,
    strings_match,
)

# --- fuzzy matching ---------------------------------------------------------


def test_fuzzy_ratio_identical_is_one() -> None:
    assert fuzzy_ratio("РФ-2026/100", "РФ-2026/100") == 1.0


def test_fuzzy_ratio_is_normalised_to_unit_interval() -> None:
    ratio = fuzzy_ratio("РФ-2026/100", "РФ-2026/108")
    assert 0.0 <= ratio <= 1.0


def test_strings_match_ignores_surrounding_whitespace() -> None:
    assert strings_match("РФ-2026/100", "  РФ-2026/100 ")


def test_strings_match_none_actual_is_miss() -> None:
    assert not strings_match("РФ-2026/100", None)


def test_strings_match_close_enough_passes_threshold() -> None:
    # One transposed digit in an 11-char string stays >= 0.9.
    assert strings_match("РФ-2026/100", "РФ-2026/108")


def test_strings_match_far_string_fails() -> None:
    assert not strings_match("РФ-2026/100", "АКТ-2026/50")


def test_threshold_is_the_contract_value() -> None:
    assert FUZZY_MATCH_THRESHOLD == 0.9


# --- false-confidence detection ---------------------------------------------


def test_false_confidence_confident_and_wrong() -> None:
    assert is_false_confidence(matched=False, confidence=0.95)


def test_false_confidence_confident_and_right_is_safe() -> None:
    assert not is_false_confidence(matched=True, confidence=0.99)


def test_false_confidence_wrong_but_unconfident_is_not_dangerous() -> None:
    assert not is_false_confidence(matched=False, confidence=0.4)


def test_false_confidence_threshold_is_inclusive() -> None:
    assert is_false_confidence(matched=False, confidence=0.85)


def test_false_confidence_missing_confidence_is_not_flagged() -> None:
    # No extraction / no confidence entry -> cannot be "confidently" wrong.
    assert not is_false_confidence(matched=False, confidence=None)


# --- number field (exact) ---------------------------------------------------


def test_number_exact_match() -> None:
    fe = evaluate_field("total_amount", 20121.55, Decimal("20121.55"), 0.9)
    assert fe.matched and fe.comparable and not fe.sentinel_empty


def test_number_mismatch_is_miss() -> None:
    fe = evaluate_field("total_amount", 20121.55, Decimal("20121.56"), 0.9)
    assert not fe.matched


def test_number_confident_mismatch_is_false_confidence() -> None:
    fe = evaluate_field("total_amount", 20121.55, Decimal("99999.00"), 0.97)
    assert not fe.matched and fe.false_confidence


def test_number_sentinel_zero_matches_null() -> None:
    fe = evaluate_field("total_amount", 0, None, None)
    assert fe.matched and fe.sentinel_empty and not fe.false_confidence


def test_number_sentinel_zero_fabricated_value_is_false_confidence() -> None:
    fe = evaluate_field("total_amount", 0, Decimal("4868.85"), 0.9)
    assert not fe.matched and fe.sentinel_empty and fe.false_confidence


# --- date field (exact) -----------------------------------------------------


def test_date_exact_match() -> None:
    fe = evaluate_field("issue_date", "2026-04-02", "2026-04-02", 0.9)
    assert fe.matched


def test_date_mismatch_is_miss() -> None:
    fe = evaluate_field("issue_date", "2026-04-02", "2026-04-03", 0.9)
    assert not fe.matched


def test_date_null_actual_is_miss() -> None:
    fe = evaluate_field("issue_date", "2026-04-02", None, None)
    assert not fe.matched


# --- string field (fuzzy) ---------------------------------------------------


def test_string_fuzzy_match() -> None:
    fe = evaluate_field("invoice_number", "РФ-2026/100", "РФ-2026/100", 0.9)
    assert fe.matched


def test_string_sentinel_matches_null() -> None:
    fe = evaluate_field("invoice_number", "0", None, None)
    assert fe.matched and fe.sentinel_empty


def test_string_sentinel_fabricated_is_wrong() -> None:
    fe = evaluate_field("invoice_number", "0", "РФ-2026/100", 0.95)
    assert not fe.matched and fe.sentinel_empty and fe.false_confidence


# --- unmodeled field --------------------------------------------------------


def test_currency_is_not_comparable() -> None:
    fe = evaluate_field("currency", "UAH", None, None)
    assert not fe.comparable and not fe.false_confidence


# --- payload / confidence mapping (invoice vs act) --------------------------


def test_actual_for_field_invoice_payload() -> None:
    payload = {"invoice_number": "РФ-2026/100", "invoice_date": "2026-04-02", "total": "20121.55"}
    assert actual_for_field("invoice_number", payload, "invoice") == "РФ-2026/100"
    assert str(actual_for_field("issue_date", payload, "invoice")) == "2026-04-02"
    assert actual_for_field("total_amount", payload, "invoice") == Decimal("20121.55")


def test_actual_for_field_act_payload_uses_act_names() -> None:
    payload = {"act_number": "АКТ-2026/50", "act_date": "2026-02-24", "total": "15432.05"}
    assert actual_for_field("invoice_number", payload, "act") == "АКТ-2026/50"
    assert str(actual_for_field("issue_date", payload, "act")) == "2026-02-24"


def test_actual_for_field_missing_payload_is_none() -> None:
    assert actual_for_field("total_amount", None, "invoice") is None


def test_confidence_for_field_maps_to_payload_path() -> None:
    confidences = {"invoice_number": 0.9, "invoice_date": 0.8, "total": 0.95}
    assert confidence_for_field("total_amount", confidences, "invoice") == 0.95
    assert confidence_for_field("issue_date", confidences, "invoice") == 0.8


def test_confidence_for_field_act_path() -> None:
    confidences = {"act_number": 0.7, "total": 0.6}
    assert confidence_for_field("invoice_number", confidences, "act") == 0.7


# --- tag normalisation ------------------------------------------------------


def test_normalize_tag_synonyms() -> None:
    assert normalize_tag("Clean pdf") == "clean"
    assert normalize_tag("foto") == "photo"
    assert normalize_tag("scangood") == "scan"
    assert normalize_tag("scan bad") == "scan"
    assert normalize_tag("nonstandard") == "nonstandard_layout"
    assert normalize_tag("other letter") == "other"
    assert normalize_tag("without data") == "without_data"


def test_normalize_tag_unknown_falls_through_snake_cased() -> None:
    assert normalize_tag("Brand New") == "brand_new"


def test_normalize_tags_empty_becomes_untagged() -> None:
    assert normalize_tags([]) == ["untagged"]


def test_normalize_tags_dedupes() -> None:
    assert normalize_tags(["scan", "scangood"]) == ["scan"]


# --- metric aggregation -----------------------------------------------------


def _doc(
    id: str, categories: list[str], evals: list[tuple[str, bool, float | None, bool]]
) -> DocEval:
    field_evals = [
        evaluate_field(name, "x", "x" if matched else "y", conf) for name, matched, conf, _ in evals
    ]
    # Override matched/false_confidence deterministically for aggregation tests.
    from dataclasses import replace

    field_evals = [
        replace(fe, matched=m, false_confidence=fc, comparable=True)
        for fe, (_, m, _c, fc) in zip(field_evals, evals, strict=True)
    ]
    return DocEval(
        id=id,
        raw_tags=categories,
        categories=categories,
        doc_type="invoice",
        extracted=True,
        schema_valid=True,
        field_evals=field_evals,
        total_payload_fields=10,
        flagged_payload_fields=3,
    )


def test_aggregate_field_accuracy_and_false_confidence() -> None:
    docs = [
        _doc(
            "a", ["clean"], [("total_amount", True, 0.9, False), ("issue_date", True, 0.9, False)]
        ),
        _doc(
            "b", ["scan"], [("total_amount", False, 0.95, True), ("issue_date", True, 0.9, False)]
        ),
    ]
    m = aggregate(docs, ALL_CATEGORY)
    assert m.n_docs == 2
    assert m.n_comparable_fields == 4
    assert m.n_correct == 3
    assert m.field_accuracy == 0.75
    assert m.n_false_confidence == 1
    assert m.false_confidence_rate == 0.25
    # 3 flagged of 10 payload fields per doc -> 6/20.
    assert m.review_flag_rate == 0.3
    assert m.schema_validity_rate == 1.0


def test_by_category_splits_and_includes_all() -> None:
    docs = [
        _doc("a", ["clean"], [("total_amount", True, 0.9, False)]),
        _doc("b", ["scan"], [("total_amount", False, 0.95, True)]),
    ]
    result = by_category(docs)
    assert set(result) == {ALL_CATEGORY, "clean", "scan"}
    assert result["clean"].field_accuracy == 1.0
    assert result["scan"].field_accuracy == 0.0
    assert result["scan"].n_false_confidence == 1


def test_aggregate_empty_metrics_are_none_not_zero_division() -> None:
    m = aggregate([], "empty")
    assert m.field_accuracy is None
    assert m.schema_validity_rate is None
    assert m.review_flag_rate is None
    assert m.false_confidence_rate is None
