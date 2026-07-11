"""Tests for T8 export: golden-file CSV/JSON shape, filename/Content-Disposition
handling, and the route's 404/409 gating.

The builder-level tests (`services/export.py`) are pure and use the T5 clean
fixture payload (`EXPECTED_INVOICE_TEXT`) — same convention as
`services/validate.py`'s exhaustive unit tests: no mocks needed. The route
tests mock DocumentsRepo/ExtractionsRepo the same way `test_review_routes.py`
does.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.domain import InvoiceData
from app.routes import export as export_routes
from app.services.export import (
    build_csv_bytes,
    build_json_export,
    content_disposition,
    export_filename_stem,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
if FIXTURES not in sys.path:
    sys.path.insert(0, FIXTURES)
from generate_invoice_fixtures import EXPECTED_INVOICE_TEXT  # noqa: E402

DOCUMENT_ID = UUID("33333333-3333-3333-3333-333333333333")
CONFIRMED_AT = datetime(2026, 7, 10, 12, 30, 0, tzinfo=UTC)

CLEAN_PAYLOAD = InvoiceData.model_validate(EXPECTED_INVOICE_TEXT)

# --- Golden-file: JSON export -------------------------------------------------

EXPECTED_JSON = """{
  "supplier": {
    "name": "ТОВ «Технопостач»",
    "tax_id": "38492069",
    "address": "м. Київ, вул. Промислова, 15, оф. 204"
  },
  "buyer": {
    "name": "ФОП Коваленко Олена Петрівна",
    "tax_id": "3012415678",
    "address": "м. Харків, просп. Науки, 47, кв. 12"
  },
  "invoice_number": "РФ-2024/0317",
  "invoice_date": "2024-04-17",
  "items": [
    {
      "name": "Ноутбук Lenovo ThinkPad",
      "quantity": "3",
      "unit_price": "32500.00",
      "amount": "97500.00"
    },
    {
      "name": "Миша бездротова Logitech",
      "quantity": "3",
      "unit_price": "850.00",
      "amount": "2550.00"
    },
    {
      "name": "Кабель HDMI, 2 м",
      "quantity": "5",
      "unit_price": "220.00",
      "amount": "1100.00"
    }
  ],
  "subtotal": "101150.00",
  "vat_amount": "20230.00",
  "total": "121380.00",
  "meta": {
    "document_id": "33333333-3333-3333-3333-333333333333",
    "confirmed_at": "2026-07-10T12:30:00Z",
    "schema_version": 1
  }
}"""


def test_json_export_golden_bytes() -> None:
    export = build_json_export(
        CLEAN_PAYLOAD, document_id=DOCUMENT_ID, confirmed_at=CONFIRMED_AT, schema_version=1
    )
    content = json.dumps(export.model_dump(mode="json"), ensure_ascii=False, indent=2)
    assert content == EXPECTED_JSON


def test_json_export_never_fabricates_missing_fields() -> None:
    """A null field stays null in the export (CLAUDE.md rule 5), not omitted
    or coerced to some placeholder."""
    payload = InvoiceData.model_validate({**EXPECTED_INVOICE_TEXT, "invoice_number": None})
    export = build_json_export(
        payload, document_id=DOCUMENT_ID, confirmed_at=CONFIRMED_AT, schema_version=1
    )
    assert export.invoice_number is None
    assert export.model_dump(mode="json")["invoice_number"] is None


# --- Golden-file: CSV export ---------------------------------------------------

EXPECTED_CSV_ROWS = [
    "supplier_name,supplier_tax_id,supplier_address,buyer_name,buyer_tax_id,buyer_address,"
    "invoice_number,invoice_date,item_name,item_quantity,item_unit_price,item_amount,"
    "subtotal,vat_amount,total",
    'ТОВ «Технопостач»,38492069,"м. Київ, вул. Промислова, 15, оф. 204",'
    "ФОП Коваленко Олена Петрівна,3012415678,"
    '"м. Харків, просп. Науки, 47, кв. 12",РФ-2024/0317,2024-04-17,'
    "Ноутбук Lenovo ThinkPad,3,32500.00,97500.00,101150.00,20230.00,121380.00",
    'ТОВ «Технопостач»,38492069,"м. Київ, вул. Промислова, 15, оф. 204",'
    "ФОП Коваленко Олена Петрівна,3012415678,"
    '"м. Харків, просп. Науки, 47, кв. 12",РФ-2024/0317,2024-04-17,'
    "Миша бездротова Logitech,3,850.00,2550.00,101150.00,20230.00,121380.00",
    'ТОВ «Технопостач»,38492069,"м. Київ, вул. Промислова, 15, оф. 204",'
    "ФОП Коваленко Олена Петрівна,3012415678,"
    '"м. Харків, просп. Науки, 47, кв. 12",РФ-2024/0317,2024-04-17,'
    '"Кабель HDMI, 2 м",5,220.00,1100.00,101150.00,20230.00,121380.00',
]
EXPECTED_CSV_BYTES = ("\ufeff" + "\r\n".join(EXPECTED_CSV_ROWS) + "\r\n").encode("utf-8")


def test_csv_export_golden_bytes() -> None:
    assert build_csv_bytes(CLEAN_PAYLOAD) == EXPECTED_CSV_BYTES


def test_csv_export_has_utf8_bom() -> None:
    content = build_csv_bytes(CLEAN_PAYLOAD)
    assert content.startswith(b"\xef\xbb\xbf")


def test_csv_export_uses_crlf_line_endings() -> None:
    content = build_csv_bytes(CLEAN_PAYLOAD).decode("utf-8-sig")
    assert "\r\n" in content
    assert "\n" not in content.replace("\r\n", "")


def test_csv_export_one_row_per_line_item_with_header_fields_repeated() -> None:
    content = build_csv_bytes(CLEAN_PAYLOAD).decode("utf-8-sig")
    rows = content.strip("\r\n").split("\r\n")
    assert len(rows) == 1 + len(CLEAN_PAYLOAD.items)  # header + one row per item
    header_prefix = "ТОВ «Технопостач»,38492069"
    for row in rows[1:]:
        assert row.startswith(header_prefix)


def test_csv_export_quotes_field_with_embedded_quote_character() -> None:
    """A name containing a literal `"` is escaped by doubling it, per RFC 4180
    (the T5 clean fixture only exercises comma-quoting; this covers the other
    half of "quoting of names with commas/quotes")."""
    payload = InvoiceData.model_validate(
        {
            **EXPECTED_INVOICE_TEXT,
            "items": [
                {
                    "name": 'Кабель 6" USB',
                    "quantity": "1",
                    "unit_price": "10.00",
                    "amount": "10.00",
                }
            ],
        }
    )
    content = build_csv_bytes(payload).decode("utf-8-sig")
    assert '"Кабель 6"" USB"' in content


def test_csv_export_null_fields_render_as_empty_cell() -> None:
    payload = InvoiceData.model_validate(
        {
            **EXPECTED_INVOICE_TEXT,
            "invoice_number": None,
            "items": [{"name": None, "quantity": None, "unit_price": None, "amount": None}],
        }
    )
    content = build_csv_bytes(payload).decode("utf-8-sig")
    rows = list(csv.reader(content.strip("\r\n").split("\r\n")))
    header, data_row = rows[0], rows[1]
    assert data_row[header.index("invoice_number")] == ""
    for column in ("item_name", "item_quantity", "item_unit_price", "item_amount"):
        assert data_row[header.index(column)] == ""


# --- Filename / Content-Disposition -------------------------------------------


def test_export_filename_stem_uses_invoice_number() -> None:
    assert export_filename_stem("РФ-2024/0317", DOCUMENT_ID) == "РФ-2024_0317"


def test_export_filename_stem_falls_back_to_document_id() -> None:
    assert export_filename_stem(None, DOCUMENT_ID) == str(DOCUMENT_ID)
    assert export_filename_stem("", DOCUMENT_ID) == str(DOCUMENT_ID)


def test_content_disposition_carries_ascii_fallback_and_utf8_name() -> None:
    header = content_disposition("РФ-2024_0317.csv")
    assert header.startswith('attachment; filename="')
    assert "filename*=UTF-8''" in header
    assert "%D0%A0%D0%A4" in header  # percent-encoded Cyrillic Р Ф


# --- Route: GET /api/documents/{id}/export ------------------------------------


def _document_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": str(DOCUMENT_ID),
        "filename": "invoice.pdf",
        "status": "confirmed",
        "doc_type": "invoice",
        "confirmed_at": CONFIRMED_AT.isoformat(),
        "created_at": "2026-07-10T09:00:00+00:00",
    }
    row.update(overrides)
    return row


def _extraction_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": "44444444-4444-4444-4444-444444444444",
        "document_id": str(DOCUMENT_ID),
        "payload": EXPECTED_INVOICE_TEXT,
        "field_confidences": [],
        "validation_issues": [],
        "schema_version": 1,
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
def client(documents: MagicMock, extractions: MagicMock):  # type: ignore[no-untyped-def]
    app.dependency_overrides[export_routes.get_documents_repo] = lambda: documents
    app.dependency_overrides[export_routes.get_extractions_repo] = lambda: extractions
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_export_json_returns_body_and_headers(
    client: TestClient, documents: MagicMock, extractions: MagicMock
) -> None:
    documents.get_by_id.return_value = _document_row()
    extractions.get_latest_by_document.return_value = _extraction_row()

    response = client.get(f"/api/documents/{DOCUMENT_ID}/export", params={"format": "json"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    disposition = response.headers["content-disposition"]
    assert "РФ-2024_0317.json" in disposition or "filename*=UTF-8''" in disposition
    body = response.json()
    assert body["invoice_number"] == "РФ-2024/0317"
    assert body["meta"]["document_id"] == str(DOCUMENT_ID)
    assert body["meta"]["schema_version"] == 1


def test_export_csv_returns_bom_and_content_type(
    client: TestClient, documents: MagicMock, extractions: MagicMock
) -> None:
    documents.get_by_id.return_value = _document_row()
    extractions.get_latest_by_document.return_value = _extraction_row()

    response = client.get(f"/api/documents/{DOCUMENT_ID}/export", params={"format": "csv"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.content == EXPECTED_CSV_BYTES


def test_export_defaults_to_json_format(
    client: TestClient, documents: MagicMock, extractions: MagicMock
) -> None:
    documents.get_by_id.return_value = _document_row()
    extractions.get_latest_by_document.return_value = _extraction_row()

    response = client.get(f"/api/documents/{DOCUMENT_ID}/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_export_409_when_not_confirmed(
    client: TestClient, documents: MagicMock, extractions: MagicMock
) -> None:
    documents.get_by_id.return_value = _document_row(status="review")

    response = client.get(f"/api/documents/{DOCUMENT_ID}/export", params={"format": "json"})

    assert response.status_code == 409
    extractions.get_latest_by_document.assert_not_called()


def test_export_404_when_document_missing(client: TestClient, documents: MagicMock) -> None:
    documents.get_by_id.return_value = None

    response = client.get(f"/api/documents/{DOCUMENT_ID}/export")

    assert response.status_code == 404


def test_export_404_when_no_extraction(
    client: TestClient, documents: MagicMock, extractions: MagicMock
) -> None:
    documents.get_by_id.return_value = _document_row()
    extractions.get_latest_by_document.return_value = None

    response = client.get(f"/api/documents/{DOCUMENT_ID}/export")

    assert response.status_code == 404
