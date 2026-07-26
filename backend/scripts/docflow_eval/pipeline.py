"""Runs the real DocFlow pipeline over one document's bytes, for the eval.

Mirrors `app/services/ingestion.py::_run_pipeline` exactly — T3 preprocess ->
T10 classify -> route by doc_type/confidence -> T5/T10 extract -> T6 validate —
using the same production services and the real Anthropic API. Keep this in sync
with `_run_pipeline` if the ingestion routing changes.

The one difference from ingestion is that persistence is stubbed: a capturing
fake `ExtractionsRepo` is injected so the eval never writes rows to the shared
Supabase `documents`/`extractions` tables. Everything that determines extraction
quality (preprocess mode, classification, the extraction LLM call, deterministic
validation and confidence zeroing) runs for real. See docs/decisions.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from app.config import CLASSIFY_REVIEW_CONFIDENCE_THRESHOLD
from app.llm import LlmError
from app.models.domain import DocType, ExtractionResult
from app.repos.extractions import ExtractionsRepo
from app.services.classify import classify_document
from app.services.extract import ExtractionService
from app.services.preprocess import preprocess


class _CapturingExtractionsRepo:
    """Stand-in for `ExtractionsRepo` that captures the row instead of writing it.

    Same `create(...)` signature the real repo exposes; returns a minimal row so
    `ExtractionService.extract` completes unchanged, but touches no database.
    """

    def __init__(self) -> None:
        self.row: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self.row = kwargs
        return {"id": str(uuid4()), **kwargs}


@dataclass
class PipelineResult:
    """Everything the scorer needs from one pipeline run over one document."""

    doc_type: str  # classifier's decision (invoice/act/other)
    classify_confidence: float
    mode: str  # T3 preprocess mode: text | vision
    pages: int
    extracted: bool  # did extraction run (vs. routed straight to review)?
    schema_valid: bool  # did extraction return a Pydantic-valid ExtractionResult?
    payload: dict[str, Any] | None  # JSON-dumped InvoiceData/ActData, or None
    confidences: dict[str, float] = field(default_factory=dict)  # path -> confidence
    field_confidences_raw: list[dict[str, Any]] = field(default_factory=list)
    validation_issues_raw: list[dict[str, Any]] = field(default_factory=list)
    model: str | None = None  # id the extraction call resolved to
    cost_usd: Decimal | None = None
    latency_ms: int | None = None
    error: str | None = None


def run_pipeline(content: bytes, *, document_id: UUID | None = None) -> PipelineResult:
    """Run preprocess -> classify -> (extract -> validate) over `content`.

    Never raises for a normal extraction failure: a model that can't produce a
    schema-valid result is recorded as `schema_valid=False` (mirroring how
    ingestion would mark the document `failed`), so one bad document does not
    abort the whole eval run.
    """
    doc_id = document_id or uuid4()
    pre = preprocess(content)
    classification = classify_document(pre)
    doc_type = classification.doc_type

    routed_to_review = (
        doc_type == DocType.other
        or classification.confidence < CLASSIFY_REVIEW_CONFIDENCE_THRESHOLD
    )
    if routed_to_review:
        return PipelineResult(
            doc_type=doc_type.value,
            classify_confidence=classification.confidence,
            mode=pre.mode,
            pages=pre.pages,
            extracted=False,
            schema_valid=True,  # correctly abstaining is valid behaviour, not a schema failure
            payload=None,
        )

    repo = _CapturingExtractionsRepo()
    # The capturing repo is structurally compatible with ExtractionsRepo.create;
    # cast so ExtractionService type-checks without a live Supabase client.
    service = ExtractionService(extractions=cast(ExtractionsRepo, repo))
    try:
        result: ExtractionResult = service.extract(document_id=doc_id, doc=pre, doc_type=doc_type)
    except LlmError as error:
        return PipelineResult(
            doc_type=doc_type.value,
            classify_confidence=classification.confidence,
            mode=pre.mode,
            pages=pre.pages,
            extracted=True,
            schema_valid=False,
            payload=None,
            error=f"{type(error).__name__}: {error}",
        )

    confidences = {c.path: c.confidence for c in result.confidences}
    captured = repo.row or {}
    return PipelineResult(
        doc_type=result.doc_type.value,
        classify_confidence=classification.confidence,
        mode=pre.mode,
        pages=pre.pages,
        extracted=True,
        schema_valid=True,
        payload=result.payload.model_dump(mode="json"),
        confidences=confidences,
        field_confidences_raw=[c.model_dump(mode="json") for c in result.confidences],
        validation_issues_raw=list(captured.get("validation_issues", [])),
        model=captured.get("model"),
        cost_usd=captured.get("cost_usd"),
        latency_ms=captured.get("latency_ms"),
    )
