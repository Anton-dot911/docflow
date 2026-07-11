"""HTTP layer for GET /api/documents/{id}/export (T8).

Thin: resolve the document + its latest extraction, gate on `status ==
confirmed` (409 otherwise), and hand the validated payload to
`services/export.py` for the actual JSON/CSV rendering. Repos are provided via
FastAPI dependencies so unit tests can override them with fakes.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.models.domain import InvoiceData
from app.models.export import ExportConflict
from app.repos.documents import DocumentsRepo
from app.repos.extractions import ExtractionsRepo
from app.services.export import (
    build_csv_bytes,
    build_json_export,
    content_disposition,
    export_filename_stem,
)

router = APIRouter(prefix="/api/documents", tags=["export"])


def get_documents_repo() -> DocumentsRepo:
    return DocumentsRepo()


def get_extractions_repo() -> ExtractionsRepo:
    return ExtractionsRepo()


@router.get("/{document_id}/export", responses={409: {"model": ExportConflict}})
def export_document(
    document_id: UUID,
    documents: Annotated[DocumentsRepo, Depends(get_documents_repo)],
    extractions: Annotated[ExtractionsRepo, Depends(get_extractions_repo)],
    format: Annotated[Literal["json", "csv"], Query()] = "json",
) -> Response:
    document = documents.get_by_id(document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    if document["status"] != "confirmed":
        conflict = ExportConflict(message="document is not confirmed")
        raise HTTPException(status.HTTP_409_CONFLICT, detail=conflict.model_dump())

    extraction = extractions.get_latest_by_document(document_id)
    if extraction is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="document has no extraction to export"
        )

    payload = InvoiceData.model_validate(extraction["payload"])
    stem = export_filename_stem(payload.invoice_number, document_id)

    if format == "json":
        export = build_json_export(
            payload,
            document_id=document_id,
            confirmed_at=document["confirmed_at"],
            schema_version=extraction["schema_version"],
        )
        content = json.dumps(export.model_dump(mode="json"), ensure_ascii=False, indent=2).encode(
            "utf-8"
        )
        media_type = "application/json"
        filename = f"{stem}.json"
    else:
        content = build_csv_bytes(payload)
        media_type = "text/csv; charset=utf-8"
        filename = f"{stem}.csv"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": content_disposition(filename)},
    )
