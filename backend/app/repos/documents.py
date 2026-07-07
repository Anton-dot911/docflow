"""Repository for the `documents` table.

All DB access for documents goes through here (CLAUDE.md rule 8: no raw SQL in
route handlers). Uses the service-role Supabase client, so RLS is bypassed and
the caller is responsible for scoping by user_id.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from postgrest.types import CountMethod

from app.repos.supabase_client import get_supabase

_TABLE = "documents"


class DocumentsRepo:
    """CRUD for documents rows needed by ingestion (T2)."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client if client is not None else get_supabase()

    def create(
        self,
        *,
        document_id: UUID,
        user_id: UUID,
        filename: str,
        storage_path: str,
    ) -> dict[str, Any]:
        """Insert a queued document row and return it (including status)."""
        row = {
            "id": str(document_id),
            "user_id": str(user_id),
            "filename": filename,
            "storage_path": storage_path,
            "status": "queued",
        }
        result = self._client.table(_TABLE).insert(row).execute()
        return cast(dict[str, Any], result.data[0])

    def set_status(self, *, document_id: UUID, status: str) -> None:
        """Transition a document to a new status (used by the stub worker)."""
        self._client.table(_TABLE).update({"status": status}).eq(
            "id", str(document_id)
        ).execute()

    def list_for_user(
        self,
        *,
        user_id: UUID,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (rows, total) for a user, newest first, optionally filtered."""
        query = (
            self._client.table(_TABLE)
            .select("*", count=CountMethod.exact)
            .eq("user_id", str(user_id))
        )
        if status is not None:
            query = query.eq("status", status)
        result = (
            query.order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        rows = cast(list[dict[str, Any]], result.data)
        total = result.count if result.count is not None else len(rows)
        return rows, total
