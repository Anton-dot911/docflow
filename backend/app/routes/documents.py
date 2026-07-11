"""HTTP layer for document ingestion and listing (T2).

Thin: parse/validate the request, delegate to IngestionService / repos, map
domain errors to status codes. Repos and the service are provided via FastAPI
dependencies so unit tests can override them with fakes.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from app.config import PLACEHOLDER_USER_ID, SIGNED_URL_EXPIRES_SECONDS
from app.models.document import (
    BatchError,
    DocStatus,
    DocumentListItem,
    DocumentListResponse,
    UploadItemResult,
)
from app.models.review import (
    ConfirmConflict,
    ConfirmResponse,
    DocumentDetailResponse,
    ExtractionDetail,
    FileUrlResponse,
)
from app.repos.documents import DocumentsRepo
from app.repos.extractions import ExtractionsRepo
from app.repos.storage import StorageRepo
from app.services.flags import count_flags
from app.services.ingestion import (
    BatchSizeError,
    IngestionService,
    UploadFilePayload,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])


def get_documents_repo() -> DocumentsRepo:
    return DocumentsRepo()


def get_storage_repo() -> StorageRepo:
    return StorageRepo()


def get_extractions_repo() -> ExtractionsRepo:
    return ExtractionsRepo()


def get_ingestion_service(
    storage: Annotated[StorageRepo, Depends(get_storage_repo)],
    documents: Annotated[DocumentsRepo, Depends(get_documents_repo)],
) -> IngestionService:
    return IngestionService(storage=storage, documents=documents)


@router.post(
    "",
    response_model=list[UploadItemResult],
    responses={400: {"model": BatchError}},
)
async def upload_documents(
    background_tasks: BackgroundTasks,
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
    files: Annotated[list[UploadFile], File(description="1..10 files (pdf/jpg/png, <=10MB)")],
) -> list[UploadItemResult]:
    """Accept valid files, reject invalid ones individually (partial success).

    Returns one result per input file. The request only hard-fails (400) when
    it is itself malformed: zero files or more than 10.
    """
    payloads = [
        UploadFilePayload(filename=f.filename or "file", content=await f.read()) for f in files
    ]
    try:
        return service.ingest(payloads, background_tasks)
    except BatchSizeError as error:
        detail = BatchError(message=str(error), reason=error.reason)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=detail.model_dump()) from error


@router.get("", response_model=DocumentListResponse)
def list_documents(
    documents: Annotated[DocumentsRepo, Depends(get_documents_repo)],
    extractions: Annotated[ExtractionsRepo, Depends(get_extractions_repo)],
    status_filter: Annotated[DocStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    rows, total = documents.list_for_user(
        user_id=PLACEHOLDER_USER_ID,
        status=status_filter.value if status_filter else None,
        limit=limit,
        offset=offset,
    )
    extraction_by_doc = extractions.get_latest_for_documents([row["id"] for row in rows])
    items = []
    for row in rows:
        item = DocumentListItem.model_validate(row)
        extraction = extraction_by_doc.get(row["id"])
        if extraction is not None:
            raw_total = extraction["payload"].get("total")
            item = item.model_copy(
                update={
                    "total": Decimal(raw_total) if raw_total is not None else None,
                    "flags_count": count_flags(
                        extraction["field_confidences"], extraction["validation_issues"]
                    ),
                }
            )
        items.append(item)
    return DocumentListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=DocumentDetailResponse)
def get_document(
    document_id: UUID,
    documents: Annotated[DocumentsRepo, Depends(get_documents_repo)],
    extractions: Annotated[ExtractionsRepo, Depends(get_extractions_repo)],
) -> DocumentDetailResponse:
    """Document + its latest extraction (payload, confidences, issues), if any."""
    document = documents.get_by_id(document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    extraction_row = extractions.get_latest_by_document(document_id)
    extraction = ExtractionDetail.model_validate(extraction_row) if extraction_row else None
    return DocumentDetailResponse(
        id=document["id"],
        filename=document["filename"],
        status=document["status"],
        doc_type=document.get("doc_type"),
        mode=document.get("mode"),
        pages=document.get("pages"),
        created_at=document["created_at"],
        extraction=extraction,
    )


@router.get("/{document_id}/file", response_model=FileUrlResponse)
def get_document_file(
    document_id: UUID,
    documents: Annotated[DocumentsRepo, Depends(get_documents_repo)],
    storage: Annotated[StorageRepo, Depends(get_storage_repo)],
) -> FileUrlResponse:
    """Short-lived signed URL to the stored file (private bucket)."""
    document = documents.get_by_id(document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    url = storage.create_signed_url(
        path=document["storage_path"], expires_in=SIGNED_URL_EXPIRES_SECONDS
    )
    return FileUrlResponse(url=url, expires_in=SIGNED_URL_EXPIRES_SECONDS)


@router.post(
    "/{document_id}/confirm",
    response_model=ConfirmResponse,
    responses={409: {"model": ConfirmConflict}},
)
def confirm_document(
    document_id: UUID,
    documents: Annotated[DocumentsRepo, Depends(get_documents_repo)],
    extractions: Annotated[ExtractionsRepo, Depends(get_extractions_repo)],
) -> ConfirmResponse:
    """Confirm a document, rejecting with 409 while any field is unresolved.

    "Unresolved" means confidence 0 (a T6 validation issue that was never
    explicitly accepted): PATCH /api/extractions/{id} always sets confidence to
    1.0, so accepting a red field as-is (same value) or editing it both clear
    this gate. A document is never confirmed while unresolved fields remain.
    """
    document = documents.get_by_id(document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    extraction = extractions.get_latest_by_document(document_id)
    if extraction is not None:
        unresolved = [c["path"] for c in extraction["field_confidences"] if c["confidence"] == 0]
        if unresolved:
            conflict = ConfirmConflict(
                message="document has unresolved fields with confidence 0",
                unresolved_fields=unresolved,
            )
            raise HTTPException(status.HTTP_409_CONFLICT, detail=conflict.model_dump())
    documents.mark_confirmed(document_id=document_id)
    return ConfirmResponse(status=DocStatus.confirmed)
