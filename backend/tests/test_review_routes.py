"""Unit tests for the T7 Review UI routes, with repos mocked.

Covers: GET /api/documents/{id} (document + latest extraction, 404), PATCH
/api/extractions/{id} (payload/confidence update, review_log write, bad
field_path -> 422), POST /api/documents/{id}/confirm (409 gate on confidence-0
fields, success clears it), and GET /api/documents/{id}/file (signed URL).
Storage/DB repos are MagicMocks injected through FastAPI dependency overrides
so no network or real Supabase is touched.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import documents as documents_routes
from app.routes import extractions as extractions_routes

DOCUMENT_ID = "11111111-1111-1111-1111-111111111111"
EXTRACTION_ID = "22222222-2222-2222-2222-222222222222"

PAYLOAD: dict[str, Any] = {
    "supplier": {"name": "ТОВ «Млин-Агро»", "tax_id": "38412907", "address": "м. Київ"},
    "buyer": {"name": "ФОП Іванов", "tax_id": None, "address": None},
    "invoice_number": "2847",
    "invoice_date": "2026-07-04",
    "items": [
        {"name": "Борошно пшен.", "quantity": "25", "unit_price": "18.00", "amount": "450.00"}
    ],
    "subtotal": "12200.00",
    "vat_amount": "2440.00",
    "total": "14640.00",
}

FIELD_CONFIDENCES: list[dict[str, Any]] = [
    {"path": "supplier.name", "confidence": 0.99, "source_snippet": None},
    {"path": "items[0].amount", "confidence": 0.62, "source_snippet": "450,00"},
    {"path": "total", "confidence": 0.0, "source_snippet": "14 640,00"},
]

VALIDATION_ISSUES: list[dict[str, Any]] = [
    {
        "path": "total",
        "code": "total_mismatch",
        "message": "positions total 14460.00, document says 14640.00",
    }
]


def _extraction_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": EXTRACTION_ID,
        "document_id": DOCUMENT_ID,
        "payload": copy.deepcopy(PAYLOAD),
        "field_confidences": copy.deepcopy(FIELD_CONFIDENCES),
        "validation_issues": copy.deepcopy(VALIDATION_ISSUES),
        "model": "claude-sonnet-5",
        "created_at": "2026-07-10T10:00:00+00:00",
    }
    row.update(overrides)
    return row


def _document_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": DOCUMENT_ID,
        "filename": "накладна.pdf",
        "status": "review",
        "doc_type": "invoice",
        "mode": "text",
        "pages": 1,
        "storage_path": f"00000000-0000-0000-0000-000000000000/{DOCUMENT_ID}/накладна.pdf",
        "created_at": "2026-07-10T09:00:00+00:00",
    }
    row.update(overrides)
    return row


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
    app.dependency_overrides[documents_routes.get_documents_repo] = lambda: documents
    app.dependency_overrides[documents_routes.get_extractions_repo] = lambda: extractions
    app.dependency_overrides[documents_routes.get_storage_repo] = lambda: storage
    app.dependency_overrides[extractions_routes.get_extractions_repo] = lambda: extractions
    app.dependency_overrides[extractions_routes.get_review_log_repo] = lambda: review_log
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- GET /api/documents/{id} -------------------------------------------------


def test_get_document_returns_document_and_latest_extraction(
    client: TestClient, documents: MagicMock, extractions: MagicMock
) -> None:
    documents.get_by_id.return_value = _document_row()
    extractions.get_latest_by_document.return_value = _extraction_row()

    response = client.get(f"/api/documents/{DOCUMENT_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "накладна.pdf"
    assert body["mode"] == "text"
    assert body["extraction"]["payload"]["total"] == "14640.00"
    assert body["extraction"]["field_confidences"][2]["path"] == "total"
    assert body["extraction"]["validation_issues"][0]["code"] == "total_mismatch"
    extractions.get_latest_by_document.assert_called_once()


def test_get_document_404_when_missing(client: TestClient, documents: MagicMock) -> None:
    documents.get_by_id.return_value = None
    response = client.get(f"/api/documents/{DOCUMENT_ID}")
    assert response.status_code == 404


def test_get_document_extraction_null_when_none_yet(
    client: TestClient, documents: MagicMock, extractions: MagicMock
) -> None:
    documents.get_by_id.return_value = _document_row(status="processing", mode=None, pages=None)
    extractions.get_latest_by_document.return_value = None
    response = client.get(f"/api/documents/{DOCUMENT_ID}")
    assert response.status_code == 200
    assert response.json()["extraction"] is None


# --- GET /api/documents/{id}/file --------------------------------------------


def test_get_document_file_returns_signed_url(
    client: TestClient, documents: MagicMock, storage: MagicMock
) -> None:
    documents.get_by_id.return_value = _document_row()
    storage.create_signed_url.return_value = "https://example.supabase.co/signed/xyz"

    response = client.get(f"/api/documents/{DOCUMENT_ID}/file")

    assert response.status_code == 200
    body = response.json()
    assert body["url"] == "https://example.supabase.co/signed/xyz"
    assert body["expires_in"] == 3600
    storage.create_signed_url.assert_called_once_with(
        path=_document_row()["storage_path"], expires_in=3600
    )


def test_get_document_file_404_when_missing(client: TestClient, documents: MagicMock) -> None:
    documents.get_by_id.return_value = None
    response = client.get(f"/api/documents/{DOCUMENT_ID}/file")
    assert response.status_code == 404


# --- PATCH /api/extractions/{id} ---------------------------------------------


def test_patch_extraction_updates_payload_confidence_and_logs(
    client: TestClient, extractions: MagicMock, review_log: MagicMock
) -> None:
    row = _extraction_row()
    extractions.get_by_id.return_value = row
    extractions.update_after_edit.side_effect = lambda _id, **kw: {**row, **kw}

    response = client.patch(
        f"/api/extractions/{EXTRACTION_ID}",
        json={"field_path": "total", "new_value": "14460.00"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["payload"]["total"] == "14460.00"
    confidences = {c["path"]: c["confidence"] for c in body["field_confidences"]}
    assert confidences["total"] == 1.0
    # The T6 issue at "total" is cleared once the operator has acted on it.
    assert all(issue["path"] != "total" for issue in body["validation_issues"])

    update_kwargs = extractions.update_after_edit.call_args.kwargs
    assert update_kwargs["payload"]["total"] == "14460.00"

    review_log.create.assert_called_once()
    log_kwargs = review_log.create.call_args.kwargs
    assert log_kwargs["field_path"] == "total"
    assert log_kwargs["old_value"] == "14640.00"
    assert log_kwargs["new_value"] == "14460.00"


def test_patch_extraction_accept_as_is_same_value_still_resolves(
    client: TestClient, extractions: MagicMock, review_log: MagicMock
) -> None:
    row = _extraction_row()
    extractions.get_by_id.return_value = row
    extractions.update_after_edit.side_effect = lambda _id, **kw: {**row, **kw}

    response = client.patch(
        f"/api/extractions/{EXTRACTION_ID}",
        json={"field_path": "total", "new_value": "14640.00"},  # same value = "Прийняти як є"
    )

    assert response.status_code == 200
    body = response.json()
    confidences = {c["path"]: c["confidence"] for c in body["field_confidences"]}
    assert confidences["total"] == 1.0
    assert all(issue["path"] != "total" for issue in body["validation_issues"])


def test_patch_extraction_line_item_field_path(
    client: TestClient, extractions: MagicMock, review_log: MagicMock
) -> None:
    row = _extraction_row()
    extractions.get_by_id.return_value = row
    extractions.update_after_edit.side_effect = lambda _id, **kw: {**row, **kw}

    response = client.patch(
        f"/api/extractions/{EXTRACTION_ID}",
        json={"field_path": "items[0].amount", "new_value": "460.00"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["payload"]["items"][0]["amount"] == "460.00"
    confidences = {c["path"]: c["confidence"] for c in body["field_confidences"]}
    assert confidences["items[0].amount"] == 1.0


def test_patch_extraction_bad_field_path_422(client: TestClient, extractions: MagicMock) -> None:
    extractions.get_by_id.return_value = _extraction_row()
    response = client.patch(
        f"/api/extractions/{EXTRACTION_ID}",
        json={"field_path": "items[9].amount", "new_value": "1.00"},
    )
    assert response.status_code == 422
    extractions.update_after_edit.assert_not_called()


def test_patch_extraction_404_when_missing(client: TestClient, extractions: MagicMock) -> None:
    extractions.get_by_id.return_value = None
    response = client.patch(
        f"/api/extractions/{EXTRACTION_ID}",
        json={"field_path": "total", "new_value": "1.00"},
    )
    assert response.status_code == 404


# --- POST /api/documents/{id}/confirm ----------------------------------------


def test_confirm_rejects_409_when_unresolved_zero_confidence_field(
    client: TestClient, documents: MagicMock, extractions: MagicMock
) -> None:
    documents.get_by_id.return_value = _document_row()
    extractions.get_latest_by_document.return_value = _extraction_row()  # "total" is still 0

    response = client.post(f"/api/documents/{DOCUMENT_ID}/confirm")

    assert response.status_code == 409
    assert response.json()["detail"]["unresolved_fields"] == ["total"]
    documents.mark_confirmed.assert_not_called()


def test_confirm_succeeds_once_zero_confidence_fields_are_resolved(
    client: TestClient, documents: MagicMock, extractions: MagicMock
) -> None:
    documents.get_by_id.return_value = _document_row()
    resolved = _extraction_row(
        field_confidences=[
            {"path": "supplier.name", "confidence": 0.99, "source_snippet": None},
            {"path": "items[0].amount", "confidence": 0.62, "source_snippet": "450,00"},
            {"path": "total", "confidence": 1.0, "source_snippet": "14 640,00"},
        ],
        validation_issues=[],
    )
    extractions.get_latest_by_document.return_value = resolved

    response = client.post(f"/api/documents/{DOCUMENT_ID}/confirm")

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    documents.mark_confirmed.assert_called_once()
    assert str(documents.mark_confirmed.call_args.kwargs["document_id"]) == DOCUMENT_ID


def test_confirm_succeeds_with_no_extraction_at_all(
    client: TestClient, documents: MagicMock, extractions: MagicMock
) -> None:
    documents.get_by_id.return_value = _document_row(status="review", mode=None, pages=None)
    extractions.get_latest_by_document.return_value = None

    response = client.post(f"/api/documents/{DOCUMENT_ID}/confirm")

    assert response.status_code == 200
    documents.mark_confirmed.assert_called_once()


def test_confirm_404_when_document_missing(client: TestClient, documents: MagicMock) -> None:
    documents.get_by_id.return_value = None
    response = client.post(f"/api/documents/{DOCUMENT_ID}/confirm")
    assert response.status_code == 404
