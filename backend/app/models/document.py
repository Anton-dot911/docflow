"""API-layer Pydantic models for the ingestion endpoints (T2).

These are wire contracts for POST/GET /api/documents. Domain extraction models
(InvoiceData etc., see docs/PLAN.md) arrive with later tasks.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
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


class UploadItemStatus(StrEnum):
    """Per-file outcome status in the POST /api/documents response.

    `queued` mirrors the stored `documents.status`; `rejected` is response-only
    (a rejected file is never stored, so it has no DB row).
    """

    queued = "queued"
    rejected = "rejected"


class UploadReason(StrEnum):
    """Machine-readable reason a file (or the whole request) was rejected."""

    too_large = "too_large"
    bad_type = "bad_type"
    too_many_files = "too_many_files"
    no_files = "no_files"


class UploadItemResult(BaseModel):
    """One entry of the POST /api/documents response (partial success).

    Accepted files carry `document_id` + status `queued`; rejected files carry
    status `rejected` + a `reason`.
    """

    filename: str
    status: UploadItemStatus
    document_id: UUID | None = None
    reason: UploadReason | None = None


class BatchError(BaseModel):
    """Body of the 400 returned when the request itself is malformed."""

    message: str
    reason: UploadReason


class DocumentListItem(BaseModel):
    """One row of the GET /api/documents listing.

    `total` and `flags_count` (T8 history page) come from the document's
    latest extraction, if any, and are `None` until extraction has run.
    `flags_count` is the number of fields still needing review (T6 issue or
    confidence below `settings.REVIEW_THRESHOLD` — see `services/flags.py`).
    """

    id: UUID
    filename: str
    status: DocStatus
    doc_type: str | None = None
    created_at: datetime
    total: Decimal | None = None
    flags_count: int | None = None


class DocumentListResponse(BaseModel):
    """Paged listing for GET /api/documents."""

    items: list[DocumentListItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
