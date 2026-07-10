"""Invoice extraction pipeline (T5).

Turns a `PreprocessedDoc` (T3) into a validated `ExtractionResult` and persists
it to the `extractions` table with the call's cost/latency. Both preprocessing
modes are supported:

- **text** — the extracted text layer is sent verbatim as the user message.
- **vision** — each page image is sent as a base64 PNG image block, preceded by
  a short text block.

The structured call goes through the T4 `call_structured_metered` wrapper with
`ExtractionResult` as the output model (tool-use schema + validate + single
retry). `doc_type` is fixed to `"invoice"` for now — classification is T10.

After extraction, T6's `services/validate.py` runs deterministic checks
(arithmetic, date sanity, tax-id checksum) against the payload; every issue
zeroes that field's confidence before persistence so the Review UI flags it.
"""

from __future__ import annotations

import base64
from typing import Any
from uuid import UUID

from app.llm import Llm, create_docflow_llm
from app.models.domain import DocType, ExtractionResult
from app.models.preprocess import PreprocessedDoc
from app.repos.extractions import ExtractionsRepo
from app.services.validate import validate_invoice, zero_out_confidences

PROMPT_FILE = "prompts/extract_invoice.v1.md"

# T3 always encodes vision pages as PNG (see services/preprocess.py).
_IMAGE_MEDIA_TYPE = "image/png"
_VISION_INSTRUCTION = "Extract the invoice data from the following document page image(s)."


def _build_content(doc: PreprocessedDoc) -> str | list[dict[str, Any]]:
    """Shape the user message for the extraction call from a PreprocessedDoc.

    text mode -> the extracted text string; vision mode -> a text block followed
    by one base64 PNG image block per page.
    """
    if doc.mode == "text":
        # The model validator guarantees non-empty text in text mode.
        return doc.text or ""
    blocks: list[dict[str, Any]] = [{"type": "text", "text": _VISION_INSTRUCTION}]
    for image in doc.images or []:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": _IMAGE_MEDIA_TYPE,
                    "data": base64.standard_b64encode(image).decode("ascii"),
                },
            }
        )
    return blocks


class ExtractionService:
    """Runs invoice extraction for one document and persists the result."""

    def __init__(self, llm: Llm | None = None, extractions: ExtractionsRepo | None = None) -> None:
        # Defaults are built lazily so unit tests can inject a mocked Llm and a
        # fake repo, and so no API key / Supabase client is needed at import.
        self._llm = llm or create_docflow_llm(component="extract")
        self._extractions = extractions or ExtractionsRepo()

    def extract(self, *, document_id: UUID, doc: PreprocessedDoc) -> ExtractionResult:
        """Extract invoice fields from `doc`, persist the row, return the result.

        Raises whatever the LLM layer raises (e.g. `LlmError`) or the repo raises
        on a failed insert; the caller (background worker) turns that into a
        `failed` document status rather than dropping it silently.
        """
        content = _build_content(doc)
        result, metrics = self._llm.call_structured_metered(
            None, PROMPT_FILE, content, ExtractionResult
        )
        # Classification is T10; force the type for now so the persisted row is
        # unambiguous regardless of what the model echoed back.
        result = result.model_copy(update={"doc_type": DocType.invoice})

        # T6: deterministic validation. Every issue zeroes its field's
        # confidence so the Review UI flags it alongside low-confidence fields.
        issues = validate_invoice(result.payload)
        confidences = zero_out_confidences(result.confidences, issues)
        result = result.model_copy(update={"confidences": confidences})

        self._extractions.create(
            document_id=document_id,
            payload=result.payload.model_dump(mode="json"),
            field_confidences=[c.model_dump(mode="json") for c in result.confidences],
            validation_issues=[i.model_dump(mode="json") for i in issues],
            model=metrics.model,
            tokens_in=metrics.tokens_in,
            tokens_out=metrics.tokens_out,
            cost_usd=metrics.cost_usd,
            latency_ms=metrics.latency_ms,
        )
        return result


def extract_document(*, document_id: UUID, doc: PreprocessedDoc) -> ExtractionResult:
    """Module-level seam used by the ingestion background worker.

    Builds a default `ExtractionService` (real LLM + repo) and runs it. Unit
    tests of the worker monkeypatch this symbol; the service itself is unit-
    tested directly with injected fakes.
    """
    return ExtractionService().extract(document_id=document_id, doc=doc)
