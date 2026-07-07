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
    DocStatus,
    DocumentCreated,
    DocumentListItem,
    DocumentListResponse,
    RejectionDetail,
)
from app.repos.documents import DocumentsRepo
from app.repos.storage import StorageRepo
from app.services.ingestion import (
    BatchSizeError,
    FilesRejectedError,
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
    status_code=status.HTTP_201_CREATED,
    response_model=list[DocumentCreated],
    responses={422: {"model": RejectionDetail}},
)
async def upload_documents(
    background_tasks: BackgroundTasks,
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
    files: Annotated[list[UploadFile], File(description="1..10 files (pdf/jpg/png, <=10MB)")],
) -> list[DocumentCreated]:
    payloads = [
        UploadFilePayload(filename=f.filename or "file", content=await f.read()) for f in files
    ]
    try:
        return service.ingest(payloads, background_tasks)
    except BatchSizeError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except FilesRejectedError as error:
        detail = RejectionDetail(message=str(error), results=error.results)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail.model_dump()
        ) from error


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
