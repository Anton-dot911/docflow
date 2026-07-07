"""Ingestion pipeline entrypoint (T2).

Validates an upload batch (count, magic-byte type, size), stores accepted files
in Supabase Storage, creates queued `documents` rows, and schedules a background
stub that walks each document queued -> processing -> review so the status flow
is exercised end-to-end before real processing (T3+) replaces the stub.

Batch semantics: all-or-nothing. If any file fails validation the whole request
is rejected with a 4xx carrying per-file results and nothing is stored; this
keeps the documented success response verbatim `[{document_id, status}]`
(docs/PLAN.md) rather than mixing accepted/rejected entries into it. See
docs/decisions.md.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import BackgroundTasks

from app.config import (
    MAX_FILE_SIZE_BYTES,
    MAX_FILES_PER_REQUEST,
    MIN_FILES_PER_REQUEST,
    PLACEHOLDER_USER_ID,
    STATUS_STUB_DELAY_SECONDS,
)
from app.models.document import DocStatus, DocumentCreated, FileResult
from app.repos.documents import DocumentsRepo
from app.repos.storage import StorageRepo, build_storage_path
from app.services.filetypes import content_type_for, sniff_type


class BatchSizeError(Exception):
    """The number of files is outside the allowed 1..10 range."""


class FilesRejectedError(Exception):
    """One or more files failed per-file validation; nothing was stored."""

    def __init__(self, results: list[FileResult]) -> None:
        self.results = results
        super().__init__("one or more files were rejected")


@dataclass(frozen=True)
class UploadFilePayload:
    """A single uploaded file's name and raw bytes, read by the route."""

    filename: str
    content: bytes


def _safe_filename(raw: str | None) -> str:
    """Reduce a client filename to a single safe path segment."""
    candidate = (raw or "").replace("\\", "/").split("/")[-1].strip()
    return candidate or "file"


def _validate(payload: UploadFilePayload) -> tuple[FileResult, str | None]:
    """Validate one file. Returns (result, sniffed_type). type is None if rejected."""
    filename = _safe_filename(payload.filename)
    size = len(payload.content)
    if size == 0:
        return FileResult(filename=filename, accepted=False, error="file is empty"), None
    if size > MAX_FILE_SIZE_BYTES:
        return (
            FileResult(
                filename=filename,
                accepted=False,
                error=f"file exceeds the {MAX_FILE_SIZE_BYTES} byte limit ({size} bytes)",
            ),
            None,
        )
    file_type = sniff_type(payload.content)
    if file_type is None:
        return (
            FileResult(
                filename=filename,
                accepted=False,
                error="unsupported file type; only pdf, jpg, png are allowed",
            ),
            None,
        )
    return FileResult(filename=filename, accepted=True), file_type


def _run_status_stub(documents: DocumentsRepo, document_id: UUID, delay: float) -> None:
    """Placeholder worker: queued -> processing -> (delay) -> review.

    Replaced by the real preprocess/classify/extract pipeline in T3+.
    """
    documents.set_status(document_id=document_id, status=DocStatus.processing.value)
    if delay > 0:
        time.sleep(delay)
    documents.set_status(document_id=document_id, status=DocStatus.review.value)


class IngestionService:
    def __init__(self, storage: StorageRepo, documents: DocumentsRepo) -> None:
        self._storage = storage
        self._documents = documents

    def ingest(
        self,
        payloads: list[UploadFilePayload],
        background_tasks: BackgroundTasks,
        *,
        user_id: UUID = PLACEHOLDER_USER_ID,
    ) -> list[DocumentCreated]:
        if not (MIN_FILES_PER_REQUEST <= len(payloads) <= MAX_FILES_PER_REQUEST):
            raise BatchSizeError(
                f"expected {MIN_FILES_PER_REQUEST}..{MAX_FILES_PER_REQUEST} files, "
                f"got {len(payloads)}"
            )

        validations = [_validate(p) for p in payloads]
        if any(not result.accepted for result, _ in validations):
            raise FilesRejectedError([result for result, _ in validations])

        # All valid: make sure the private bucket exists, then store each file
        # and create its queued row.
        self._storage.ensure_bucket()
        created: list[DocumentCreated] = []
        for payload, (result, file_type) in zip(payloads, validations, strict=True):
            assert file_type is not None  # guaranteed by the all-accepted check above
            document_id = uuid4()
            storage_path = build_storage_path(
                user_id=user_id, document_id=document_id, filename=result.filename
            )
            self._storage.upload(
                path=storage_path,
                data=payload.content,
                content_type=content_type_for(file_type),
            )
            row = self._documents.create(
                document_id=document_id,
                user_id=user_id,
                filename=result.filename,
                storage_path=storage_path,
            )
            background_tasks.add_task(
                _run_status_stub,
                self._documents,
                document_id,
                STATUS_STUB_DELAY_SECONDS,
            )
            created.append(
                DocumentCreated(document_id=document_id, status=DocStatus(row["status"]))
            )
        return created
