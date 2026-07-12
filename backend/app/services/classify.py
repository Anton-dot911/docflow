"""Document classification (T10).

Runs before extraction: a cheap, page-1-only call that decides `doc_type` and
routes the document to the matching extractor (or straight to review, unrouted,
when the type can't be recognized confidently). Always temperature 0
(CLAUDE.md rule 4) and metered under the "classify" Meter component so its
cost is visible separately from extraction (see app/llm/client.py).

Deliberately its own Meter component and its own (cheaper) default model —
classification is a one-line-of-output task, not a full-document extraction,
and directly serves the T12 per-document cost target.
"""

from __future__ import annotations

import base64
import os
from typing import Any

from app.llm import Llm, create_docflow_llm
from app.models.domain import Classification
from app.models.preprocess import PreprocessedDoc

PROMPT_FILE = "prompts/classify.v1.md"

# Fallback chain mirrors the LLM_MODEL convention in app/llm/client.py, but
# with its own env var and its own (cheap) default: classification never needs
# a large model, so it must not silently inherit LLM_MODEL's (possibly
# expensive) extraction model.
CLASSIFIER_MODEL_ENV_VAR = "CLASSIFIER_MODEL"
DEFAULT_CLASSIFIER_MODEL = "claude-haiku-4-5"

# T3 always encodes vision pages as PNG (see services/preprocess.py).
_IMAGE_MEDIA_TYPE = "image/png"
_VISION_INSTRUCTION = "Classify page 1 of the following document."


def _resolve_model() -> str:
    return os.environ.get(CLASSIFIER_MODEL_ENV_VAR) or DEFAULT_CLASSIFIER_MODEL


def _page1_content(doc: PreprocessedDoc) -> str | list[dict[str, Any]]:
    """Shape the user message from just page 1 of `doc`, per the task spec.

    text mode -> `first_page_text` (falling back to the full text in the rare
    case a text-mode document's own first page carried no text of its own);
    vision mode -> a text block plus the first page's base64 PNG image (T3
    guarantees `images` is non-empty in vision mode, so `images[0]` is safe).
    """
    if doc.mode == "text":
        return doc.first_page_text or doc.text or ""
    image = doc.images[0] if doc.images else b""
    return [
        {"type": "text", "text": _VISION_INSTRUCTION},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": _IMAGE_MEDIA_TYPE,
                "data": base64.standard_b64encode(image).decode("ascii"),
            },
        },
    ]


class ClassificationService:
    """Classifies one document's first page into a `Classification`."""

    def __init__(self, llm: Llm | None = None) -> None:
        self._llm = llm or create_docflow_llm(component="classify")

    def classify(self, doc: PreprocessedDoc) -> Classification:
        content = _page1_content(doc)
        return self._llm.call_structured(_resolve_model(), PROMPT_FILE, content, Classification)


def classify_document(doc: PreprocessedDoc) -> Classification:
    """Module-level seam used by the ingestion background worker.

    Mirrors `services/extract.py`'s `extract_document` seam: builds a default
    `ClassificationService` (real LLM) and runs it; unit tests of the worker
    monkeypatch this symbol, and the service itself is unit-tested directly
    with an injected mock LLM.
    """
    return ClassificationService().classify(doc)
