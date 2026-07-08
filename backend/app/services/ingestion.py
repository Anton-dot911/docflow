"""Ingestion pipeline entrypoint (T2).

Validates an upload batch (count, magic-byte type, size), stores accepted files
in Supabase Storage, creates queued `documents` rows, and schedules a background
stub that walks each document queued -> processing -> review so the status flow
is exercised end-to-end before real processing (T3+) replaces the stub.

Batch semantics: partial success. Valid files are accepted (stored + queued);
invalid files are rejected individually with a machine-readable reason, and the
response reports one entry per input file in order. The whole request only
hard-fails (raising BatchSizeError -> 400) when the request itself is malformed:
zero files, or more than the 1..10 allowed. See docs/decisions.md.
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
from app.models.document import (
    DocStatus,
    UploadItemResult,
    UploadItemStatus,
    UploadReason,
)
from app.repos.documents import DocumentsRepo
from app.repos.storage import StorageRepo, build_storage_path
from app.services.filetypes import content_type_for, sniff_type


class BatchSizeError(Exception):
    """The request is malformed: the file count is outside the allowed range."""

    def __init__(self, reason: UploadReason, message: str) -> None:
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True)
class UploadFilePayload:
    """A single uploaded file's name and raw bytes, read by the route."""

    filename: str
    content: bytes


@dataclass(frozen=True)
class _Validated:
    """Outcome of validating one file. `file_type` is None iff rejected."""

    filename: str
    file_type: str | None
    reason: UploadReason | None


def _safe_filename(raw: str | None) -> str:
    """Reduce a client filename to a single safe path segment."""
    candidate = (raw or "").replace("\\", "/").split("/")[-1].strip()
    return candidate or "file"


def _validate(payload: UploadFilePayload) -> _Validated:
    """Validate one file by size then magic bytes."""
    filename = _safe_filename(payload.filename)
    if len(payload.content) > MAX_FILE_SIZE_BYTES:
        return _Validated(filename, None, UploadReason.too_large)
    file_type = sniff_type(payload.content)
    if file_type is None:
        # Covers unknown signatures and empty files (nothing to sniff).
        return _Validated(filename, None, UploadReason.bad_type)
    return _Validated(filename, file_type, None)


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
    ) -> list[UploadItemResult]:
        count = len(payloads)
        if count < MIN_FILES_PER_REQUEST:
            raise BatchSizeError(UploadReason.no_files, "no files were uploaded")
        if count > MAX_FILES_PER_REQUEST:
            raise BatchSizeError(
                UploadReason.too_many_files,
                f"too many files: {count} (max {MAX_FILES_PER_REQUEST})",
            )

        results: list[UploadItemResult] = []
        bucket_ready = False
        for payload in payloads:
            validated = _validate(payload)
            if validated.file_type is None:
                results.append(
                    UploadItemResult(
                        filename=validated.filename,
                        status=UploadItemStatus.rejected,
                        reason=validated.reason,
                    )
                )
                continue

            # Create the bucket lazily, only once we have a file to store.
            if not bucket_ready:
                self._storage.ensure_bucket()
                bucket_ready = True

            document_id = uuid4()
            storage_path = build_storage_path(
                user_id=user_id, document_id=document_id, filename=validated.filename
            )
            self._storage.upload(
                path=storage_path,
                data=payload.content,
                content_type=content_type_for(validated.file_type),
            )
            row = self._documents.create(
                document_id=document_id,
                user_id=user_id,
                filename=validated.filename,
                storage_path=storage_path,
            )
            background_tasks.add_task(
                _run_status_stub,
                self._documents,
                document_id,
                STATUS_STUB_DELAY_SECONDS,
            )
            results.append(
                UploadItemResult(
                    filename=validated.filename,
                    status=UploadItemStatus(row["status"]),
                    document_id=document_id,
                )
            )
        return results
