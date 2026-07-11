"""API-layer Pydantic models for the T9 demo mode endpoints.

Wire contracts for GET /api/demo/samples and the always-409
POST /api/demo/documents. See `app/demo_data.py` for the underlying static
metadata these are built from.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.models.document import DocStatus


class DemoSampleItem(BaseModel):
    """One card on the /demo entry page: static metadata + live status."""

    id: UUID
    key: str
    filename: str
    difficulty: str
    title: str
    description: str
    status: DocStatus
    doc_type: str | None = None


class DemoUploadBlocked(BaseModel):
    """Body of the 409 always returned by POST /api/demo/documents."""

    message: str
