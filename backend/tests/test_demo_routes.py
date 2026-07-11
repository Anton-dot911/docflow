"""Unit tests for T9 demo mode: GET /api/demo/samples, POST /api/demo/documents
(always-blocked upload), and the per-IP rate limit applied to demo endpoints
and to any request touching a demo document. Repos are MagicMocks injected
through FastAPI dependency overrides, mirroring tests/test_review_routes.py —
no network or real Supabase is touched.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import DEMO_RATE_LIMIT_MAX_REQUESTS
from app.demo_data import DEMO_DOCUMENTS
from app.main import app
from app.routes import demo as demo_routes
from app.routes import documents as documents_routes
from app.routes import extractions as extractions_routes
from app.services.rate_limit import reset_rate_limits

DEMO_DOC_ID = str(DEMO_DOCUMENTS[0].document_id)
NON_DEMO_DOC_ID = "99999999-9999-9999-9999-999999999999"
EXTRACTION_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def _clean_rate_limiter() -> Iterator[None]:
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture
def documents() -> MagicMock:
    return MagicMock(name="DocumentsRepo")


@pytest.fixture
def extractions() -> MagicMock:
    return MagicMock(name="ExtractionsRepo")


@pytest.fixture
def storage() -> MagicMock:
    return MagicMock(name="StorageRepo")


@pytest.fixture
def review_log() -> MagicMock:
    repo = MagicMock(name="ReviewLogRepo")
    repo.create.side_effect = lambda **kw: {**kw, "id": 1}
    return repo


@pytest.fixture
def client(
    documents: MagicMock, extractions: MagicMock, storage: MagicMock, review_log: MagicMock
) -> Iterator[TestClient]:
    app.dependency_overrides[demo_routes.get_documents_repo] = lambda: documents
    app.dependency_overrides[documents_routes.get_documents_repo] = lambda: documents
    app.dependency_overrides[documents_routes.get_extractions_repo] = lambda: extractions
    app.dependency_overrides[documents_routes.get_storage_repo] = lambda: storage
    app.dependency_overrides[extractions_routes.get_extractions_repo] = lambda: extractions
    app.dependency_overrides[extractions_routes.get_review_log_repo] = lambda: review_log
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- GET /api/demo/samples ---------------------------------------------------


def test_list_demo_samples_returns_all_five_with_metadata(
    client: TestClient, documents: MagicMock
) -> None:
    documents.get_by_id.return_value = {"status": "review", "doc_type": "invoice"}

    response = client.get("/api/demo/samples")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(DEMO_DOCUMENTS)
    keys = {item["key"] for item in body}
    assert keys == {spec.key for spec in DEMO_DOCUMENTS}
    assert all(item["status"] == "review" for item in body)
    assert all(item["difficulty"] for item in body)


def test_list_demo_samples_defaults_to_queued_when_not_seeded_yet(
    client: TestClient, documents: MagicMock
) -> None:
    documents.get_by_id.return_value = None

    response = client.get("/api/demo/samples")

    assert response.status_code == 200
    body = response.json()
    assert all(item["status"] == "queued" for item in body)
    assert all(item["doc_type"] is None for item in body)


# --- POST /api/demo/documents (always blocked) -------------------------------


def test_demo_upload_always_409s_with_friendly_message(client: TestClient) -> None:
    response = client.post("/api/demo/documents")

    assert response.status_code == 409
    assert "демо-режим" in response.json()["detail"]["message"]


# --- Rate limiting ------------------------------------------------------------


def test_demo_samples_rate_limit_fires_after_max_requests(
    client: TestClient, documents: MagicMock
) -> None:
    documents.get_by_id.return_value = None

    for _ in range(DEMO_RATE_LIMIT_MAX_REQUESTS):
        response = client.get("/api/demo/samples")
        assert response.status_code == 200

    response = client.get("/api/demo/samples")
    assert response.status_code == 429


def test_non_demo_document_is_never_rate_limited(
    client: TestClient, documents: MagicMock, extractions: MagicMock
) -> None:
    documents.get_by_id.return_value = {
        "id": NON_DEMO_DOC_ID,
        "filename": "a.pdf",
        "status": "review",
        "created_at": "2026-07-10T09:00:00+00:00",
    }
    extractions.get_latest_by_document.return_value = None

    for _ in range(DEMO_RATE_LIMIT_MAX_REQUESTS + 5):
        response = client.get(f"/api/documents/{NON_DEMO_DOC_ID}")
        assert response.status_code == 200


def test_demo_document_get_is_rate_limited(
    client: TestClient, documents: MagicMock, extractions: MagicMock
) -> None:
    documents.get_by_id.return_value = {
        "id": DEMO_DOC_ID,
        "filename": "demo.pdf",
        "status": "review",
        "created_at": "2026-07-10T09:00:00+00:00",
    }
    extractions.get_latest_by_document.return_value = None

    for _ in range(DEMO_RATE_LIMIT_MAX_REQUESTS):
        response = client.get(f"/api/documents/{DEMO_DOC_ID}")
        assert response.status_code == 200

    response = client.get(f"/api/documents/{DEMO_DOC_ID}")
    assert response.status_code == 429


# --- PATCH on a demo extraction excludes review_log --------------------------


def _extraction_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": EXTRACTION_ID,
        "document_id": DEMO_DOC_ID,
        "payload": {
            "supplier": {"name": "Постачальник", "tax_id": None, "address": None},
            "buyer": {"name": None, "tax_id": None, "address": None},
            "invoice_number": "1",
            "invoice_date": None,
            "items": [],
            "subtotal": None,
            "vat_amount": None,
            "total": "100.00",
        },
        "field_confidences": [
            {"path": "total", "confidence": 0.5, "source_snippet": None},
        ],
        "validation_issues": [],
    }
    row.update(overrides)
    return row


def test_patch_on_demo_document_does_not_write_review_log(
    client: TestClient, extractions: MagicMock, review_log: MagicMock
) -> None:
    row = _extraction_row()
    extractions.get_by_id.return_value = row
    extractions.update_after_edit.side_effect = lambda _id, **kw: {**row, **kw}

    response = client.patch(
        f"/api/extractions/{EXTRACTION_ID}",
        json={"field_path": "total", "new_value": "150.00"},
    )

    assert response.status_code == 200, response.text
    review_log.create.assert_not_called()


def test_patch_on_non_demo_document_still_writes_review_log(
    client: TestClient, extractions: MagicMock, review_log: MagicMock
) -> None:
    row = _extraction_row(document_id=NON_DEMO_DOC_ID)
    extractions.get_by_id.return_value = row
    extractions.update_after_edit.side_effect = lambda _id, **kw: {**row, **kw}

    response = client.patch(
        f"/api/extractions/{EXTRACTION_ID}",
        json={"field_path": "total", "new_value": "150.00"},
    )

    assert response.status_code == 200, response.text
    review_log.create.assert_called_once()
