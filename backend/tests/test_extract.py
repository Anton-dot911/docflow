"""Unit tests for services/extract.py (SDK mocked via mock_llm).

Cover the two request shapes (text vs vision content blocks), persistence of
payload/confidences/metrics, the forced invoice doc_type, and the background
worker's failure path (extraction error -> document status failed). No network
or real Anthropic/Supabase access.
"""

from __future__ import annotations

import base64
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from anthropic.types import ToolUseBlock
from conftest import MockLlm

import app.services.ingestion as ingestion
from app.llm import client as llm_client
from app.llm.client import LlmError
from app.models.domain import Classification, DocType, ExtractionResult
from app.models.preprocess import PreprocessedDoc
from app.services.extract import ExtractionService

# A schema-valid ExtractionResult the mocked tool call returns.
VALID_PAYLOAD: dict[str, Any] = {
    "doc_type": "invoice",
    "payload": {
        "supplier": {
            "name": "ТОВ «Технопостач»",
            "tax_id": "38492069",
            "address": "м. Київ, вул. Промислова, 15",
        },
        "buyer": {
            "name": "ФОП Коваленко Олена Петрівна",
            "tax_id": "3012415678",
            "address": "м. Харків, просп. Науки, 47",
        },
        "invoice_number": "РФ-2024/0317",
        "invoice_date": "2024-04-17",
        "items": [
            {
                "name": "Ноутбук Lenovo",
                "quantity": "3",
                "unit_price": "32500.00",
                "amount": "97500.00",
            },
        ],
        "subtotal": "97500.00",
        "vat_amount": "19500.00",
        "total": "117000.00",
    },
    "confidences": [
        {"path": "supplier.name", "confidence": 0.95, "source_snippet": "ТОВ «Технопостач»"},
        {"path": "total", "confidence": 0.9, "source_snippet": "Всього: 117000.00"},
    ],
}


class FakeExtractionsRepo:
    """Captures the kwargs passed to create() for assertions."""

    def __init__(self) -> None:
        self.created: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self.created = kwargs
        return {"id": str(uuid4()), **kwargs}


def _response(
    payload: dict[str, Any],
    *,
    model: str = "claude-haiku-4-5",
    tokens_in: int = 1500,
    tokens_out: int = 420,
) -> SimpleNamespace:
    """A Message-shaped stand-in carrying a tool call plus usage/model."""
    block = ToolUseBlock(type="tool_use", id="toolu_1", name=llm_client.TOOL_NAME, input=payload)
    usage = SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out)
    return SimpleNamespace(content=[block], stop_reason="tool_use", model=model, usage=usage)


def _service(mock_llm: MockLlm, repo: FakeExtractionsRepo) -> ExtractionService:
    return ExtractionService(llm=mock_llm.make(component="extract"), extractions=repo)  # type: ignore[arg-type]


def test_text_mode_sends_extracted_text_verbatim(mock_llm: MockLlm) -> None:
    mock_llm.create.return_value = _response(VALID_PAYLOAD)
    service = _service(mock_llm, FakeExtractionsRepo())
    doc = PreprocessedDoc(mode="text", text="Рахунок № РФ-2024/0317 ...", pages=1)

    result = service.extract(document_id=uuid4(), doc=doc)

    assert isinstance(result, ExtractionResult)
    kwargs = mock_llm.create.call_args.kwargs
    # Text mode: the extracted text is the user message content, used verbatim.
    assert kwargs["messages"][0]["content"] == "Рахунок № РФ-2024/0317 ..."
    # Structured tool-use call at temperature 0 (CLAUDE.md rule 4).
    assert kwargs["tools"][0]["name"] == llm_client.TOOL_NAME
    assert kwargs["tool_choice"] == {"type": "tool", "name": llm_client.TOOL_NAME}
    assert kwargs["temperature"] == 0.0


def test_vision_mode_sends_text_then_base64_image_blocks(mock_llm: MockLlm) -> None:
    mock_llm.create.return_value = _response(VALID_PAYLOAD)
    service = _service(mock_llm, FakeExtractionsRepo())
    doc = PreprocessedDoc(mode="vision", images=[b"\x89PNG-page-1", b"\x89PNG-page-2"], pages=2)

    service.extract(document_id=uuid4(), doc=doc)

    content = mock_llm.create.call_args.kwargs["messages"][0]["content"]
    assert isinstance(content, list)
    # Leading text block, then one image block per page.
    assert content[0]["type"] == "text"
    images = [block for block in content if block["type"] == "image"]
    assert len(images) == 2
    assert images[0]["source"]["type"] == "base64"
    assert images[0]["source"]["media_type"] == "image/png"
    # The bytes round-trip through base64 unchanged.
    assert base64.standard_b64decode(images[0]["source"]["data"]) == b"\x89PNG-page-1"
    assert base64.standard_b64decode(images[1]["source"]["data"]) == b"\x89PNG-page-2"


def test_persists_payload_confidences_and_metrics(mock_llm: MockLlm) -> None:
    mock_llm.create.return_value = _response(
        VALID_PAYLOAD, model="claude-haiku-4-5", tokens_in=1500, tokens_out=420
    )
    repo = FakeExtractionsRepo()
    document_id = uuid4()
    _service(mock_llm, repo).extract(
        document_id=document_id,
        doc=PreprocessedDoc(mode="text", text="invoice text", pages=1),
    )

    assert repo.created is not None
    row = repo.created
    assert row["document_id"] == document_id
    # Metrics from the (mocked) response usage + meter pricing.
    assert row["model"] == "claude-haiku-4-5"
    assert row["tokens_in"] == 1500
    assert row["tokens_out"] == 420
    assert isinstance(row["cost_usd"], Decimal)
    assert row["cost_usd"] > Decimal("0")
    assert isinstance(row["latency_ms"], int)
    assert row["latency_ms"] >= 0
    # payload is JSON-native: Decimals -> numeric strings, dates -> ISO 8601.
    assert row["payload"]["subtotal"] == "97500.00"
    assert row["payload"]["invoice_date"] == "2024-04-17"
    assert row["payload"]["items"][0]["amount"] == "97500.00"
    # Per-field confidences persisted as a list of dicts.
    assert row["field_confidences"][0]["path"] == "supplier.name"
    assert row["field_confidences"][0]["confidence"] == 0.95
    # T6: VALID_PAYLOAD is internally consistent (arithmetic + checksums), so
    # validation runs clean and nothing gets zeroed.
    assert row["validation_issues"] == []


def test_doc_type_is_forced_to_invoice(mock_llm: MockLlm) -> None:
    # Even if the model echoes a different type, T5 pins it to invoice (T10 owns
    # real classification).
    payload = {**VALID_PAYLOAD, "doc_type": "other"}
    mock_llm.create.return_value = _response(payload)
    result = _service(mock_llm, FakeExtractionsRepo()).extract(
        document_id=uuid4(),
        doc=PreprocessedDoc(mode="text", text="invoice text", pages=1),
    )
    assert result.doc_type == DocType.invoice


def test_pipeline_marks_failed_when_extraction_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    documents = MagicMock(name="DocumentsRepo")
    monkeypatch.setattr(
        ingestion,
        "preprocess",
        lambda content: PreprocessedDoc(mode="text", text="some invoice text", pages=1),
    )
    monkeypatch.setattr(
        ingestion,
        "classify_document",
        lambda doc: Classification(doc_type=DocType.invoice, confidence=0.99),
    )

    def _boom(**kwargs: Any) -> None:
        raise LlmError("model returned no structured_output tool call")

    monkeypatch.setattr(ingestion, "extract_document", _boom)

    ingestion._run_pipeline(documents, uuid4(), b"bytes")

    # Marked processing, then failed with the error stored; never advanced to review.
    assert [c.kwargs["status"] for c in documents.set_status.call_args_list] == ["processing"]
    documents.mark_failed.assert_called_once()
    assert "extraction failed" in documents.mark_failed.call_args.kwargs["error"]
    documents.mark_reviewable.assert_not_called()


# --- T6: validation integration ---------------------------------------------
# A payload identical to VALID_PAYLOAD except the stated total (121450.00)
# doesn't match subtotal + vat (97500.00 + 19500.00 = 117000.00).
BROKEN_TOTAL_PAYLOAD: dict[str, Any] = {
    **VALID_PAYLOAD,
    "payload": {**VALID_PAYLOAD["payload"], "total": "121450.00"},
}


def test_validation_issue_zeroes_confidence_and_persists(mock_llm: MockLlm) -> None:
    mock_llm.create.return_value = _response(BROKEN_TOTAL_PAYLOAD)
    repo = FakeExtractionsRepo()
    result = _service(mock_llm, repo).extract(
        document_id=uuid4(),
        doc=PreprocessedDoc(mode="text", text="invoice text", pages=1),
    )

    assert repo.created is not None
    issues = repo.created["validation_issues"]
    assert [i["code"] for i in issues] == ["total_mismatch"]
    assert issues[0]["path"] == "total"
    assert issues[0]["message"] == (
        "subtotal 97500.00 + vat 19500.00 = 117000.00, document says 121450.00"
    )
    # VALID_PAYLOAD's "total" confidence (0.9) is zeroed; "supplier.name" is untouched.
    conf_by_path = {c.path: c.confidence for c in result.confidences}
    assert conf_by_path["total"] == 0.0
    assert conf_by_path["supplier.name"] == 0.95
    expected_confidences = [c.model_dump(mode="json") for c in result.confidences]
    assert repo.created["field_confidences"] == expected_confidences


def test_pipeline_reaches_review_despite_validation_issues(
    mock_llm: MockLlm, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A validation issue is a confidence signal, not a pipeline failure: the
    document still advances to review, with the issue persisted for the UI."""
    documents = MagicMock(name="DocumentsRepo")
    repo = FakeExtractionsRepo()
    monkeypatch.setattr(
        ingestion,
        "preprocess",
        lambda content: PreprocessedDoc(mode="text", text="some invoice text", pages=1),
    )
    monkeypatch.setattr(
        ingestion,
        "classify_document",
        lambda doc: Classification(doc_type=DocType.invoice, confidence=0.99),
    )
    mock_llm.create.return_value = _response(BROKEN_TOTAL_PAYLOAD)
    service = _service(mock_llm, repo)
    monkeypatch.setattr(
        ingestion,
        "extract_document",
        lambda *, document_id, doc, doc_type=DocType.invoice: service.extract(
            document_id=document_id, doc=doc, doc_type=doc_type
        ),
    )

    document_id = uuid4()
    ingestion._run_pipeline(documents, document_id, b"bytes")

    documents.mark_failed.assert_not_called()
    documents.mark_reviewable.assert_called_once()
    assert repo.created is not None
    assert repo.created["validation_issues"] == [
        {
            "path": "total",
            "code": "total_mismatch",
            "message": "subtotal 97500.00 + vat 19500.00 = 117000.00, document says 121450.00",
        }
    ]
