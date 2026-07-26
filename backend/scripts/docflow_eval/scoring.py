"""Pure scoring logic for the T11 eval (no I/O, no LLM, no DB).

Compares one pipeline extraction against a Goldsmith label and classifies every
comparable field as matched / missed / false-confidence. Kept free of Pydantic
and network so it is exhaustively unit-testable with plain dicts
(`tests/test_evals_scoring.py`).

Matching rules (from the docs/PLAN.md T11 contract):
  * numbers / dates  -> exact match
  * names / strings  -> fuzzy ratio >= 0.9 (rapidfuzz)

Two Goldsmith conventions the rules above have to account for, both grounded in
the actual dataset (see docs/decisions.md):
  * **empty sentinels** — a blank invoice form or a non-invoice letter is
    labelled `total_amount: 0` / `invoice_number: "0"`, meaning "no value is
    present". The correct pipeline behaviour is to return `null` (rule 5 in
    CLAUDE.md: never fabricate), so for a sentinel the match is a pipeline
    `None`; a fabricated concrete value is the *wrong*, dangerous answer.
  * **`currency`** — present in some labels but absent from the DocFlow
    `InvoiceData`/`ActData` contract, so it is recorded but not scorable
    (`comparable=False`) rather than silently counted as a miss.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from rapidfuzz import fuzz

# docs/PLAN.md / docs/UI_SPEC.md contract: confidence >= this is "confident".
FALSE_CONFIDENCE_THRESHOLD = 0.85
# docs/PLAN.md contract: fuzzy match for names/strings.
FUZZY_MATCH_THRESHOLD = 0.9

# Goldsmith "no value present" sentinels (see module docstring).
_EMPTY_NUMBER_SENTINEL = Decimal("0")
_EMPTY_STRING_SENTINEL = "0"

# Golden label field -> DocFlow payload attribute for each doc_type. `total_amount`
# maps to the identically-named `total` on both InvoiceData and ActData.
_NUMBER_FIELDS = {"total_amount": ("total", "total")}
_DATE_FIELDS = {"issue_date": ("invoice_date", "act_date")}
_STRING_FIELDS = {"invoice_number": ("invoice_number", "act_number")}
# Present in some labels, but no corresponding field in the extraction contract.
_UNMODELED_FIELDS = {"currency"}


@dataclass(frozen=True)
class FieldEval:
    """The scored outcome for one golden field on one document."""

    field: str
    expected: Any
    actual: Any
    comparable: bool  # False => not part of the extraction contract (e.g. currency)
    matched: bool
    sentinel_empty: bool  # the label meant "no value present"
    confidence: float | None
    false_confidence: bool  # confident (>= threshold) but wrong — the dangerous case


# --- tag normalisation ------------------------------------------------------

# The raw Goldsmith tags are inconsistent (case, spelling, synonyms). This
# explicit, visible map folds them onto the canonical categories the ToR names
# (docs/TZ.md §8) so the by-category table is meaningful; the raw tags are kept
# verbatim in the per-example JSON so nothing is hidden. Any tag not listed
# falls through to its whitespace/'_'-normalised form.
_TAG_NORMALIZATION = {
    "clean": "clean",
    "clean pdf": "clean",
    "scan": "scan",
    "scan good": "scan",
    "scangood": "scan",
    "scan bad": "scan",
    "scanbad": "scan",
    "multipage": "multipage",
    "nonstandard": "nonstandard_layout",
    "nonstandard layout": "nonstandard_layout",
    "photo": "photo",
    "foto": "photo",
    "without data": "without_data",
    "other letter": "other",
    "other": "other",
}

UNTAGGED = "untagged"


def normalize_tag(tag: str) -> str:
    """Fold one raw Goldsmith tag onto a canonical category label."""
    collapsed = re.sub(r"\s+", " ", tag.strip().lower())
    return _TAG_NORMALIZATION.get(collapsed, collapsed.replace(" ", "_"))


def normalize_tags(tags: list[str]) -> list[str]:
    """Normalise an example's tags; empty -> `[UNTAGGED]`. De-duped, order kept."""
    out: list[str] = []
    for tag in tags:
        norm = normalize_tag(tag)
        if norm and norm not in out:
            out.append(norm)
    return out or [UNTAGGED]


# --- value coercion ---------------------------------------------------------


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


# --- fuzzy matching ---------------------------------------------------------


def fuzzy_ratio(a: str, b: str) -> float:
    """Normalised similarity in [0, 1] (rapidfuzz token-insensitive ratio)."""
    return fuzz.ratio(a.strip(), b.strip()) / 100.0


def strings_match(
    expected: str, actual: str | None, *, threshold: float = FUZZY_MATCH_THRESHOLD
) -> bool:
    """True if `actual` is present and within `threshold` fuzzy distance."""
    if actual is None:
        return False
    return fuzzy_ratio(expected, actual) >= threshold


# --- payload mapping (JSON-dumped payload -> comparable actual value) --------


def _doc_index(doc_type: str) -> int:
    """0 for invoice-shaped payloads, 1 for act-shaped ones."""
    return 1 if doc_type == "act" else 0


def actual_for_field(field: str, payload: dict[str, Any] | None, doc_type: str) -> Any:
    """Return the pipeline's value for a golden `field`, or None if absent.

    Reads a JSON-dumped payload (Decimals as strings, dates as ISO strings) and
    returns a typed value: `Decimal` for numbers, `date` for dates, `str` for
    strings. A missing payload (no extraction ran) yields None for every field.
    """
    if payload is None:
        return None
    idx = _doc_index(doc_type)
    if field in _NUMBER_FIELDS:
        return _to_decimal(payload.get(_NUMBER_FIELDS[field][idx]))
    if field in _DATE_FIELDS:
        return _to_date(payload.get(_DATE_FIELDS[field][idx]))
    if field in _STRING_FIELDS:
        raw = payload.get(_STRING_FIELDS[field][idx])
        return None if raw is None else str(raw)
    return None


def confidence_for_field(field: str, confidences: dict[str, float], doc_type: str) -> float | None:
    """Look up the pipeline's confidence for a golden `field`'s payload path."""
    idx = _doc_index(doc_type)
    if field in _NUMBER_FIELDS:
        return confidences.get(_NUMBER_FIELDS[field][idx])
    if field in _DATE_FIELDS:
        return confidences.get(_DATE_FIELDS[field][idx])
    if field in _STRING_FIELDS:
        return confidences.get(_STRING_FIELDS[field][idx])
    return None


# --- field comparison -------------------------------------------------------


def _compare(field: str, expected: Any, actual: Any) -> tuple[bool, bool]:
    """Return (matched, sentinel_empty) for one comparable field."""
    if field in _NUMBER_FIELDS:
        exp = _to_decimal(expected)
        act = _to_decimal(actual) if not isinstance(actual, Decimal) else actual
        if exp is not None and exp == _EMPTY_NUMBER_SENTINEL:
            return (act is None or act == 0, True)
        return (act is not None and exp is not None and act == exp, False)
    if field in _DATE_FIELDS:
        exp_date = _to_date(expected)
        act_date = actual if isinstance(actual, date) else _to_date(actual)
        return (act_date is not None and act_date == exp_date, False)
    # string field
    exp_str = "" if expected is None else str(expected).strip()
    if exp_str == _EMPTY_STRING_SENTINEL:
        return (actual is None, True)
    act_str = actual if (actual is None or isinstance(actual, str)) else str(actual)
    return (strings_match(exp_str, act_str), False)


def is_false_confidence(
    matched: bool, confidence: float | None, *, threshold: float = FALSE_CONFIDENCE_THRESHOLD
) -> bool:
    """The dangerous case: the model was confident (>= threshold) yet wrong."""
    return confidence is not None and confidence >= threshold and not matched


def evaluate_field(field: str, expected: Any, actual: Any, confidence: float | None) -> FieldEval:
    """Score one golden field against the pipeline's value + its confidence."""
    if field in _UNMODELED_FIELDS:
        return FieldEval(
            field=field,
            expected=expected,
            actual=actual,
            comparable=False,
            matched=False,
            sentinel_empty=False,
            confidence=confidence,
            false_confidence=False,
        )
    matched, sentinel = _compare(field, expected, actual)
    return FieldEval(
        field=field,
        expected=expected,
        actual=actual,
        comparable=True,
        matched=matched,
        sentinel_empty=sentinel,
        confidence=confidence,
        false_confidence=is_false_confidence(matched, confidence),
    )
