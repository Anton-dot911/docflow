"""HTTP layer for T9 demo mode: public, no-auth sample listing plus a
friendly, always-blocked upload endpoint.

Demo documents are ordinary rows in the same `documents`/`extractions` tables
(no separate schema) — scoped by the fixed `DEMO_USER_ID` and the 5 fixed ids
in `app/demo_data.py`, seeded by `scripts/seed_demo.py`. See docs/decisions.md
for why upload is a dedicated blocked endpoint rather than reusing
POST /api/documents, and why every demo endpoint is per-IP rate-limited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.demo_data import DEMO_DOCUMENTS
from app.models.demo import DemoSampleItem, DemoUploadBlocked
from app.repos.documents import DocumentsRepo
from app.services.demo_guard import enforce_demo_namespace_rate_limit

router = APIRouter(prefix="/api/demo", tags=["demo"])

_UPLOAD_BLOCKED_MESSAGE = (
    "Це демо-режим лише для перегляду — завантаження файлів вимкнено. "
    "Оберіть один із 5 готових прикладів нижче."
)


def get_documents_repo() -> DocumentsRepo:
    return DocumentsRepo()


@router.get("/samples", response_model=list[DemoSampleItem])
def list_demo_samples(
    request: Request,
    documents: Annotated[DocumentsRepo, Depends(get_documents_repo)],
) -> list[DemoSampleItem]:
    """The 5 curated demo documents: static card metadata + live doc status.

    A spec whose row hasn't been seeded yet (fresh environment, seed script
    not run) still renders with status `queued` rather than 404ing, so the
    entry page can show all 5 cards even mid-seed.
    """
    enforce_demo_namespace_rate_limit(request)
    items: list[DemoSampleItem] = []
    for spec in DEMO_DOCUMENTS:
        row = documents.get_by_id(spec.document_id)
        items.append(
            DemoSampleItem(
                id=spec.document_id,
                key=spec.key,
                filename=spec.filename,
                difficulty=spec.difficulty,
                title=spec.title,
                description=spec.description,
                status=row["status"] if row else "queued",
                doc_type=row.get("doc_type") if row else None,
            )
        )
    return items


@router.post("/documents", responses={409: {"model": DemoUploadBlocked}})
def demo_upload_blocked(request: Request) -> None:
    """The demo user cannot upload — always 409s with a friendly message.

    The 5 demo documents are curated and seeded once; the /demo page has no
    dropzone, but this endpoint exists so a direct API call gets a clear,
    on-brand rejection instead of a bare 404 (guardrail from the task spec).
    """
    enforce_demo_namespace_rate_limit(request)
    detail = DemoUploadBlocked(message=_UPLOAD_BLOCKED_MESSAGE)
    raise HTTPException(status.HTTP_409_CONFLICT, detail=detail.model_dump())
