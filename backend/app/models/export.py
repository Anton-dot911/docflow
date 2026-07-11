"""API-layer Pydantic models for GET /api/documents/{id}/export (T8).

`InvoiceExport` is the JSON export body: the `InvoiceData` shape verbatim
(Decimals/dates already serialize as strings/ISO via CLAUDE.md rule 7) plus a
`meta` block naming the document, when it was confirmed, and the extraction
schema version — so a downloaded file is self-describing without the API.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.domain import InvoiceData


class ExportMeta(BaseModel):
    document_id: UUID
    confirmed_at: datetime
    schema_version: int


class InvoiceExport(InvoiceData):
    meta: ExportMeta


class ExportConflict(BaseModel):
    """Body of the 409 raised when exporting a document that isn't confirmed."""

    message: str
