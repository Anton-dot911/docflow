"""Unit tests for services/classify.py (T10), SDK mocked via mock_llm.

Covers the classifier's request shape (page 1 only — text mode sends just
`first_page_text`, vision mode sends a text block plus `images[0]` only, even
when the document has multiple pages), temperature 0, and model resolution
(default `claude-haiku-4-5`, overridable via `CLASSIFIER_MODEL`). No network or
real Anthropic/Supabase access.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

import pytest
from anthropic.types import ToolUseBlock
from conftest import MockLlm

from app.llm import client as llm_client
from app.models.domain import Classification, DocType
from app.models.preprocess import PreprocessedDoc
from app.services.classify import DEFAULT_CLASSIFIER_MODEL, ClassificationService


def _response(payload: dict[str, Any], *, model: str = DEFAULT_CLASSIFIER_MODEL) -> SimpleNamespace:
    block = ToolUseBlock(type="tool_use", id="toolu_1", name=llm_client.TOOL_NAME, input=payload)
    return SimpleNamespace(content=[block], stop_reason="tool_use", model=model, usage=None)


def _service(mock_llm: MockLlm) -> ClassificationService:
    return ClassificationService(llm=mock_llm.make(component="classify"))


def test_text_mode_sends_first_page_text_only(mock_llm: MockLlm) -> None:
    mock_llm.create.return_value = _response({"doc_type": "invoice", "confidence": 0.95})
    doc = PreprocessedDoc(
        mode="text",
        text="--- page 1 ---\nheader\n\n--- page 2 ---\ntotals",
        first_page_text="page 1 only text",
        pages=2,
    )

    result = _service(mock_llm).classify(doc)

    assert isinstance(result, Classification)
    kwargs = mock_llm.create.call_args.kwargs
    assert kwargs["messages"][0]["content"] == "page 1 only text"
    assert kwargs["temperature"] == 0.0
    assert kwargs["model"] == DEFAULT_CLASSIFIER_MODEL


def test_text_mode_falls_back_to_full_text_when_first_page_text_missing(
    mock_llm: MockLlm,
) -> None:
    mock_llm.create.return_value = _response({"doc_type": "other", "confidence": 0.8})
    doc = PreprocessedDoc(mode="text", text="whole document text", pages=1)

    _service(mock_llm).classify(doc)

    content = mock_llm.create.call_args.kwargs["messages"][0]["content"]
    assert content == "whole document text"


def test_vision_mode_sends_only_page_one_image(mock_llm: MockLlm) -> None:
    mock_llm.create.return_value = _response({"doc_type": "act", "confidence": 0.9})
    doc = PreprocessedDoc(
        mode="vision", images=[b"\x89PNG-page-1", b"\x89PNG-page-2", b"\x89PNG-page-3"], pages=3
    )

    _service(mock_llm).classify(doc)

    content = mock_llm.create.call_args.kwargs["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    images = [block for block in content if block["type"] == "image"]
    # Only page 1's image is sent, even though the document has 3 pages.
    assert len(images) == 1
    assert images[0]["source"]["type"] == "base64"
    assert images[0]["source"]["media_type"] == "image/png"
    assert base64.standard_b64decode(images[0]["source"]["data"]) == b"\x89PNG-page-1"


def test_result_parses_into_classification(mock_llm: MockLlm) -> None:
    mock_llm.create.return_value = _response({"doc_type": "act", "confidence": 0.87})
    doc = PreprocessedDoc(mode="text", text="act text", first_page_text="act text", pages=1)

    result = _service(mock_llm).classify(doc)

    assert result.doc_type == DocType.act
    assert result.confidence == 0.87


def test_default_model_is_haiku(mock_llm: MockLlm) -> None:
    mock_llm.create.return_value = _response({"doc_type": "invoice", "confidence": 0.9})
    doc = PreprocessedDoc(mode="text", text="x", first_page_text="x", pages=1)

    _service(mock_llm).classify(doc)

    assert mock_llm.create.call_args.kwargs["model"] == "claude-haiku-4-5"


def test_classifier_model_env_var_overrides_default(
    mock_llm: MockLlm, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLASSIFIER_MODEL", "claude-sonnet-5")
    mock_llm.create.return_value = _response(
        {"doc_type": "invoice", "confidence": 0.9}, model="claude-sonnet-5"
    )
    doc = PreprocessedDoc(mode="text", text="x", first_page_text="x", pages=1)

    _service(mock_llm).classify(doc)

    assert mock_llm.create.call_args.kwargs["model"] == "claude-sonnet-5"
