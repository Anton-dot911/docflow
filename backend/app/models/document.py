"""API-layer Pydantic models for the ingestion endpoints (T2).

These are wire contracts for POST/GET /api/documents. Domain extraction models
(InvoiceData etc., see docs/PLAN.md) arrive with later tasks.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class DocStatus(StrEnum):
    """Mirror of the SQL `doc_status` enum (supabase/migrations/001_init.sql)."""

    queued = "queued"
    processing = "processing"
    review = "review"
    confirmed = "confirmed"
    failed = "failed"


class DocumentCreated(BaseModel):
    """One entry of the POST /api/documents success response."""

    document_id: UUID
    status: DocStatus


class FileResult(BaseModel):
    """Per-file outcome, returned in the 4xx body when a batch is rejected."""

    filename: str
    accepted: bool
    error: str | None = None


class RejectionDetail(BaseModel):
    """Body of the 422 returned when one or more files fail validation."""

    message: str
    results: list[FileResult]


class DocumentListItem(BaseModel):
    """One row of the GET /api/documents listing."""

    id: UUID
    filename: str
    status: DocStatus
    doc_type: str | None = None
    created_at: datetime


class DocumentListResponse(BaseModel):
    """Paged listing for GET /api/documents."""

    items: list[DocumentListItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
