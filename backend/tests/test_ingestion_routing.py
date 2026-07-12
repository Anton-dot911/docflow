"""Unit tests for T10 classify-then-route wiring in services/ingestion.py.

`_run_pipeline` is queued -> processing -> preprocess -> classify -> extract ->
review (or straight to review with no extraction for an unrecognized/
low-confidence result). These tests monkeypatch `classify_document` and
`extract_document` directly (both are plain module-level seams, same
convention as the rest of the ingestion suite) so no LLM/Supabase access is
needed — `services/classify.py`'s own request-shape behaviour is covered by
`test_classify.py`, and `services/extract.py`'s by `test_extract.py`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import app.services.ingestion as ingestion
from app.models.domain import Classification, DocType
from app.models.preprocess import PreprocessedDoc

PREPROCESSED = PreprocessedDoc(mode="text", text="some document text", pages=1)


def _stub_preprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingestion, "preprocess", lambda content: PREPROCESSED)


def test_invoice_routes_to_extraction_with_doc_type(monkeypatch: pytest.MonkeyPatch) -> None:
    documents = MagicMock(name="DocumentsRepo")
    _stub_preprocess(monkeypatch)
    monkeypatch.setattr(
        ingestion,
        "classify_document",
        lambda doc: Classification(doc_type=DocType.invoice, confidence=0.97),
    )
    extract_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        ingestion, "extract_document", lambda **kwargs: extract_calls.append(kwargs)
    )

    ingestion._run_pipeline(documents, uuid4(), b"bytes")

    assert len(extract_calls) == 1
    assert extract_calls[0]["doc_type"] == DocType.invoice
    documents.mark_failed.assert_not_called()
    documents.mark_reviewable.assert_called_once()
    assert documents.mark_reviewable.call_args.kwargs["doc_type"] == "invoice"


def test_act_routes_to_extraction_with_doc_type(monkeypatch: pytest.MonkeyPatch) -> None:
    documents = MagicMock(name="DocumentsRepo")
    _stub_preprocess(monkeypatch)
    monkeypatch.setattr(
        ingestion,
        "classify_document",
        lambda doc: Classification(doc_type=DocType.act, confidence=0.93),
    )
    extract_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        ingestion, "extract_document", lambda **kwargs: extract_calls.append(kwargs)
    )

    ingestion._run_pipeline(documents, uuid4(), b"bytes")

    assert len(extract_calls) == 1
    assert extract_calls[0]["doc_type"] == DocType.act
    documents.mark_failed.assert_not_called()
    documents.mark_reviewable.assert_called_once()
    assert documents.mark_reviewable.call_args.kwargs["doc_type"] == "act"


def test_other_doc_type_skips_extraction_and_reaches_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = MagicMock(name="DocumentsRepo")
    _stub_preprocess(monkeypatch)
    monkeypatch.setattr(
        ingestion,
        "classify_document",
        lambda doc: Classification(doc_type=DocType.other, confidence=0.95),
    )
    extract_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        ingestion, "extract_document", lambda **kwargs: extract_calls.append(kwargs)
    )

    ingestion._run_pipeline(documents, uuid4(), b"bytes")

    assert extract_calls == []  # no extraction attempted
    documents.mark_failed.assert_not_called()
    documents.mark_reviewable.assert_called_once()
    kwargs = documents.mark_reviewable.call_args.kwargs
    assert kwargs["doc_type"] == "other"
    assert kwargs["mode"] == "text"
    assert kwargs["pages"] == 1


def test_low_confidence_skips_extraction_even_for_a_recognized_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = MagicMock(name="DocumentsRepo")
    _stub_preprocess(monkeypatch)
    monkeypatch.setattr(
        ingestion,
        "classify_document",
        # A plausible doc_type, but below CLASSIFY_REVIEW_CONFIDENCE_THRESHOLD (0.6).
        lambda doc: Classification(doc_type=DocType.invoice, confidence=0.4),
    )
    extract_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        ingestion, "extract_document", lambda **kwargs: extract_calls.append(kwargs)
    )

    ingestion._run_pipeline(documents, uuid4(), b"bytes")

    assert extract_calls == []  # low confidence -> no extraction, regardless of doc_type
    documents.mark_failed.assert_not_called()
    documents.mark_reviewable.assert_called_once()
    assert documents.mark_reviewable.call_args.kwargs["doc_type"] == "invoice"


def test_confidence_at_threshold_boundary_still_extracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = MagicMock(name="DocumentsRepo")
    _stub_preprocess(monkeypatch)
    monkeypatch.setattr(
        ingestion,
        "classify_document",
        lambda doc: Classification(doc_type=DocType.invoice, confidence=0.6),
    )
    extract_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        ingestion, "extract_document", lambda **kwargs: extract_calls.append(kwargs)
    )

    ingestion._run_pipeline(documents, uuid4(), b"bytes")

    assert len(extract_calls) == 1  # 0.6 is not < 0.6 -> extraction proceeds


def test_classification_failure_marks_document_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    documents = MagicMock(name="DocumentsRepo")
    _stub_preprocess(monkeypatch)

    def _boom(doc: PreprocessedDoc) -> Classification:
        raise RuntimeError("model returned no structured_output tool call")

    monkeypatch.setattr(ingestion, "classify_document", _boom)
    extract_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        ingestion, "extract_document", lambda **kwargs: extract_calls.append(kwargs)
    )

    ingestion._run_pipeline(documents, uuid4(), b"bytes")

    assert extract_calls == []
    documents.mark_reviewable.assert_not_called()
    documents.mark_failed.assert_called_once()
    assert "classification failed" in documents.mark_failed.call_args.kwargs["error"]
