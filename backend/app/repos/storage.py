"""Supabase Storage access for uploaded documents.

Path convention (see docs/decisions.md): {user_id}/{document_id}/{filename}.
The bucket is private; files are only ever reached through the service-role
backend, never via a public URL.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.config import STORAGE_BUCKET
from app.repos.supabase_client import get_supabase


class StorageRepo:
    """Thin wrapper over the Supabase Storage API for the documents bucket."""

    def __init__(self, client: Any | None = None, bucket: str = STORAGE_BUCKET) -> None:
        self._client = client if client is not None else get_supabase()
        self._bucket = bucket

    def ensure_bucket(self) -> None:
        """Create the private documents bucket if it does not already exist.

        Idempotent: safe to call on every request. A concurrent create that
        loses the race raises a "already exists" error, which we swallow.
        """
        existing = {
            getattr(b, "id", None) or getattr(b, "name", None) for b in self._list_buckets()
        }
        if self._bucket in existing:
            return
        try:
            self._client.storage.create_bucket(self._bucket, options={"public": False})
        except Exception as error:  # normalise a lost "already exists" race to a no-op
            if "exist" not in str(error).lower():
                raise

    def upload(self, *, path: str, data: bytes, content_type: str) -> None:
        """Upload bytes to `path`. upsert=false so a repeat path is a conflict."""
        self._client.storage.from_(self._bucket).upload(
            path,
            data,
            {"content-type": content_type, "upsert": "false"},
        )

    def _list_buckets(self) -> list[Any]:
        return list(self._client.storage.list_buckets())


def build_storage_path(*, user_id: UUID, document_id: UUID, filename: str) -> str:
    """Assemble the canonical storage key for a document."""
    return f"{user_id}/{document_id}/{filename}"
