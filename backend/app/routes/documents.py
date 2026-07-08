"""HTTP layer for document ingestion and listing (T2).

Thin: parse/validate the request, delegate to IngestionService / repos, map
domain errors to status codes. Repos and the service are provided via FastAPI
dependencies so unit tests can override them with fakes.
"""

from __future__ import annotations

from typing import Annotated

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

from app.config import PLACEHOLDER_USER_ID
from app.models.document import (
    BatchError,
    DocStatus,
    DocumentListItem,
    DocumentListResponse,
    UploadItemResult,
)
from app.repos.documents import DocumentsRepo
from app.repos.storage import StorageRepo
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
    return DocumentListResponse(
        items=[DocumentListItem.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
