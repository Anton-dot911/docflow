"""Unit tests for scripts/seed_demo.py's idempotency and reset orchestration.

The real pipeline (Anthropic + Supabase Storage) is stubbed out — these tests
exercise only `seed()`'s decisions: does a fresh run seed every curated
document (5 invoices + 1 act, T10) exactly once, does re-running with rows
already present skip every one of them (no duplicates, no repeat LLM/Storage
calls — the DoD's "run twice -> same documents" requirement), and does
`--reset` restore a committed snapshot without touching Storage or the LLM at
all. Never calls the real Anthropic API or Supabase (CLAUDE.md testing
conventions).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import seed_demo as sd

from app.demo_data import DEMO_DOCUMENTS
from app.models.preprocess import PreprocessedDoc


class _FakeExtractionService:
    """Stands in for the real ExtractionService: no LLM call, no persistence.

    `seed()` reads the persisted row back via `extractions.get_latest_by_document`
    afterwards, so tests set that mock's return value directly rather than
    depending on this class to write anything.
    """

    def __init__(self, llm: Any = None, extractions: Any = None) -> None:
        del llm, extractions

    def extract(self, *, document_id: Any, doc: Any, doc_type: Any = None) -> None:
        del document_id, doc, doc_type
        return None


def _fake_extraction_row() -> dict[str, Any]:
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "payload": {
            "supplier": {"name": "Test", "tax_id": None, "address": None},
            "buyer": {"name": None, "tax_id": None, "address": None},
            "invoice_number": None,
            "invoice_date": None,
            "items": [],
            "subtotal": None,
            "vat_amount": None,
            "total": None,
        },
        "field_confidences": [],
        "validation_issues": [],
        "model": "fake-model",
        "cost_usd": "0.00100",
    }


@pytest.fixture
def repos(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, MagicMock]:
    documents = MagicMock(name="DocumentsRepo")
    extractions = MagicMock(name="ExtractionsRepo")
    storage = MagicMock(name="StorageRepo")
    extractions.get_latest_by_document.return_value = _fake_extraction_row()

    monkeypatch.setattr(sd, "SNAPSHOT_DIR", tmp_path)
    monkeypatch.setattr(
        sd, "preprocess", lambda content: PreprocessedDoc(mode="text", text="x", pages=1)
    )
    monkeypatch.setattr(sd, "ExtractionService", _FakeExtractionService)
    monkeypatch.setattr(sd, "create_docflow_llm", lambda component: object())

    return {"documents": documents, "extractions": extractions, "storage": storage}


def test_fresh_run_seeds_all_five_documents_exactly_once(repos: dict[str, MagicMock]) -> None:
    repos["documents"].get_by_id.return_value = None  # nothing seeded yet

    sd.seed(
        reset=False,
        documents=repos["documents"],
        extractions=repos["extractions"],
        storage=repos["storage"],
    )

    assert repos["documents"].create.call_count == len(DEMO_DOCUMENTS)
    assert repos["storage"].upload.call_count == len(DEMO_DOCUMENTS)
    assert repos["documents"].mark_reviewable.call_count == len(DEMO_DOCUMENTS)
    # A snapshot was written for every document (used later by --reset).
    written = {p.stem for p in sd.SNAPSHOT_DIR.glob("*.json")}
    assert written == {spec.key for spec in DEMO_DOCUMENTS}


def test_second_run_is_idempotent_no_duplicates(repos: dict[str, MagicMock]) -> None:
    repos["documents"].get_by_id.return_value = {"status": "review"}  # already seeded

    sd.seed(
        reset=False,
        documents=repos["documents"],
        extractions=repos["extractions"],
        storage=repos["storage"],
    )

    repos["documents"].create.assert_not_called()
    repos["storage"].upload.assert_not_called()
    repos["documents"].mark_reviewable.assert_not_called()
    repos["storage"].ensure_bucket.assert_called_once()  # still idempotent/cheap to call


def test_reset_restores_snapshot_without_touching_storage_or_llm(
    repos: dict[str, MagicMock],
) -> None:
    spec = DEMO_DOCUMENTS[0]
    snapshot = {
        "payload": {"invoice_number": "PRISTINE-1"},
        "field_confidences": [],
        "validation_issues": [],
    }
    (sd.SNAPSHOT_DIR).mkdir(parents=True, exist_ok=True)
    (sd.SNAPSHOT_DIR / f"{spec.key}.json").write_text(json.dumps(snapshot), encoding="utf-8")
    repos["extractions"].get_latest_by_document.return_value = {"id": "ext-1"}

    sd.seed(
        reset=True,
        documents=repos["documents"],
        extractions=repos["extractions"],
        storage=repos["storage"],
    )

    repos["storage"].upload.assert_not_called()
    repos["storage"].ensure_bucket.assert_not_called()
    update_kwargs = repos["extractions"].update_after_edit.call_args_list[0].kwargs
    assert update_kwargs["payload"] == snapshot["payload"]
    repos["documents"].set_status.assert_any_call(document_id=spec.document_id, status="review")


def test_reset_skips_documents_never_seeded(repos: dict[str, MagicMock]) -> None:
    # No snapshot files written at all -> every reset is a no-op skip.
    sd.seed(
        reset=True,
        documents=repos["documents"],
        extractions=repos["extractions"],
        storage=repos["storage"],
    )

    repos["extractions"].update_after_edit.assert_not_called()
    repos["documents"].set_status.assert_not_called()
