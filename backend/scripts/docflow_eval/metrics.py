"""Metric aggregation for the T11 eval (pure).

Turns per-document field evaluations into the four T11 metrics — field
accuracy, schema validity rate, review-flag rate and false-confidence rate —
overall and grouped by normalised category tag. No I/O; unit-tested alongside
the scoring logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from docflow_eval.scoring import FieldEval

ALL_CATEGORY = "ALL"


@dataclass
class DocEval:
    """One document's fully-scored eval record."""

    id: str
    raw_tags: list[str]
    categories: list[str]  # normalised tags (>=1; UNTAGGED if none)
    doc_type: str
    extracted: bool
    schema_valid: bool
    field_evals: list[FieldEval]
    total_payload_fields: int
    flagged_payload_fields: int


@dataclass
class CategoryMetrics:
    """Aggregated metrics for one category (or ALL)."""

    category: str
    n_docs: int
    n_comparable_fields: int
    n_correct: int
    field_accuracy: float | None
    n_extracted: int
    schema_validity_rate: float | None
    n_payload_fields: int
    n_flagged_fields: int
    review_flag_rate: float | None
    n_false_confidence: int
    false_confidence_rate: float | None
    false_confidence_fields: list[str] = field(default_factory=list)


def _ratio(numerator: int, denominator: int) -> float | None:
    return (numerator / denominator) if denominator else None


def aggregate(docs: list[DocEval], category: str) -> CategoryMetrics:
    """Aggregate the T11 metrics over `docs` under the label `category`."""
    comparable = [fe for d in docs for fe in d.field_evals if fe.comparable]
    n_comparable = len(comparable)
    n_correct = sum(1 for fe in comparable if fe.matched)
    n_false_conf = sum(1 for fe in comparable if fe.false_confidence)
    fc_fields = [f"{d.id}:{fe.field}" for d in docs for fe in d.field_evals if fe.false_confidence]

    extracted = [d for d in docs if d.extracted]
    n_extracted = len(extracted)
    n_schema_valid = sum(1 for d in extracted if d.schema_valid)

    n_payload_fields = sum(d.total_payload_fields for d in extracted)
    n_flagged = sum(d.flagged_payload_fields for d in extracted)

    return CategoryMetrics(
        category=category,
        n_docs=len(docs),
        n_comparable_fields=n_comparable,
        n_correct=n_correct,
        field_accuracy=_ratio(n_correct, n_comparable),
        n_extracted=n_extracted,
        schema_validity_rate=_ratio(n_schema_valid, n_extracted),
        n_payload_fields=n_payload_fields,
        n_flagged_fields=n_flagged,
        review_flag_rate=_ratio(n_flagged, n_payload_fields),
        n_false_confidence=n_false_conf,
        false_confidence_rate=_ratio(n_false_conf, n_comparable),
        false_confidence_fields=fc_fields,
    )


def by_category(docs: list[DocEval]) -> dict[str, CategoryMetrics]:
    """Return metrics for ALL plus each category, categories sorted by name."""
    result: dict[str, CategoryMetrics] = {ALL_CATEGORY: aggregate(docs, ALL_CATEGORY)}
    categories = sorted({c for d in docs for c in d.categories})
    for category in categories:
        members = [d for d in docs if category in d.categories]
        result[category] = aggregate(members, category)
    return result
