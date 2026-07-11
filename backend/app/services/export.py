"""Export builders for confirmed documents (T8).

Pure functions over an already-validated `InvoiceData` payload — no I/O, no
FastAPI — so the golden-file tests exercise them directly (same testing
convention as `services/validate.py`). The route (`app/routes/export.py`)
resolves the document/extraction rows and calls these to build the response
body.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from urllib.parse import quote
from uuid import UUID

from app.models.domain import InvoiceData
from app.models.export import ExportMeta, InvoiceExport

# One row per line item; header-level fields repeated on every row (task spec,
# not the docs/PLAN.md contract block, which only names the two export
# formats). Column names follow the InvoiceData/Party field names.
CSV_HEADER = [
    "supplier_name",
    "supplier_tax_id",
    "supplier_address",
    "buyer_name",
    "buyer_tax_id",
    "buyer_address",
    "invoice_number",
    "invoice_date",
    "item_name",
    "item_quantity",
    "item_unit_price",
    "item_amount",
    "subtotal",
    "vat_amount",
    "total",
]

_BOM = "\ufeff"
_FILENAME_UNSAFE_RE = re.compile(r'[\\/:*?"<>|]')


def build_json_export(
    payload: InvoiceData,
    *,
    document_id: UUID,
    confirmed_at: datetime,
    schema_version: int,
) -> InvoiceExport:
    """The confirmed payload plus a `meta` block, per the export contract."""
    meta = ExportMeta(
        document_id=document_id, confirmed_at=confirmed_at, schema_version=schema_version
    )
    return InvoiceExport(**payload.model_dump(), meta=meta)


def _cell(value: object) -> str:
    """Empty string for a null field; Decimal/date/str otherwise render as-is
    (Decimal's own `str()` is already dot-separated with no thousands grouping,
    satisfying the numbers rule below)."""
    return "" if value is None else str(value)


def build_csv_bytes(payload: InvoiceData) -> bytes:
    """UTF-8 (with BOM) CSV, comma-delimited, CRLF line endings, one row per
    line item with header-level fields repeated on every row."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=",", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)

    header_fields = [
        _cell(payload.supplier.name),
        _cell(payload.supplier.tax_id),
        _cell(payload.supplier.address),
        _cell(payload.buyer.name),
        _cell(payload.buyer.tax_id),
        _cell(payload.buyer.address),
        _cell(payload.invoice_number),
        _cell(payload.invoice_date.isoformat() if payload.invoice_date else None),
    ]
    trailer_fields = [_cell(payload.subtotal), _cell(payload.vat_amount), _cell(payload.total)]

    for item in payload.items:
        item_fields = [
            _cell(item.name),
            _cell(item.quantity),
            _cell(item.unit_price),
            _cell(item.amount),
        ]
        writer.writerow([*header_fields, *item_fields, *trailer_fields])

    return (_BOM + buf.getvalue()).encode("utf-8")


def export_filename_stem(invoice_number: str | None, document_id: UUID) -> str:
    """`invoice_number` when present (sanitized for filesystem/header safety),
    else the document id. Invoice numbers can contain characters that are
    invalid in filenames (e.g. "РФ-2024/0317"), so unsafe characters are
    replaced with "_" rather than dropped, to keep the number legible."""
    if invoice_number:
        stem = _FILENAME_UNSAFE_RE.sub("_", invoice_number).strip()
        if stem:
            return stem
    return str(document_id)


def content_disposition(filename: str) -> str:
    """`attachment` header with a Cyrillic-safe filename.

    RFC 6266/5987: an ASCII `filename` fallback for clients that ignore
    `filename*`, plus the real UTF-8 name via `filename*`.
    """
    ascii_fallback = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quote(filename)}'
