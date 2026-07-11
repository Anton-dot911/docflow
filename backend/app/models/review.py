"""API-layer Pydantic models for the T7 Review UI endpoints.

Wire contracts for GET /api/documents/{id}, PATCH /api/extractions/{id},
POST /api/documents/{id}/confirm and GET /api/documents/{id}/file. Reuses the
domain contracts from `app.models.domain` verbatim (InvoiceData,
FieldConfidence, ValidationIssue) rather than re-declaring them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.document import DocStatus
from app.models.domain import FieldConfidence, InvoiceData, ValidationIssue


class ExtractionDetail(BaseModel):
    """The latest extraction for a document, as returned to the Review UI."""

    id: UUID
    document_id: UUID
    payload: InvoiceData
    field_confidences: list[FieldConfidence]
    validation_issues: list[ValidationIssue]


class DocumentDetailResponse(BaseModel):
    """Body of GET /api/documents/{id}."""

    id: UUID
    filename: str
    status: DocStatus
    doc_type: str | None = None
    mode: str | None = None
    pages: int | None = None
    created_at: datetime
    extraction: ExtractionDetail | None = None


class PatchExtractionRequest(BaseModel):
    """Body of PATCH /api/extractions/{id}."""

    field_path: str
    new_value: Any = None


class ConfirmResponse(BaseModel):
    """Body of POST /api/documents/{id}/confirm on success."""

    status: DocStatus


class ConfirmConflict(BaseModel):
    """Body of the 409 raised when unresolved (confidence-0) fields remain."""

    message: str
    unresolved_fields: list[str]


class FileUrlResponse(BaseModel):
    """Body of GET /api/documents/{id}/file."""

    url: str
    expires_in: int
