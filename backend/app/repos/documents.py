"""Repository for the `documents` table.

All DB access for documents goes through here (CLAUDE.md rule 8: no raw SQL in
route handlers). Uses the service-role Supabase client, so RLS is bypassed and
the caller is responsible for scoping by user_id.
"""

from __future__ import annotations

from datetime import UTC, datetime
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
        """Transition a document to a new status."""
        self._client.table(_TABLE).update({"status": status}).eq("id", str(document_id)).execute()

    def mark_reviewable(
        self, *, document_id: UUID, mode: str, pages: int, doc_type: str | None = None
    ) -> None:
        """Persist preprocessing outputs and advance the document to `review`.

        Writes `mode`/`pages` and `status='review'` in one update (T3). T10
        additionally writes `doc_type` (the classifier's decision) when given;
        it stays optional so pre-T10 callers are unaffected. A `review` row
        with `doc_type` set but no `extractions` row is how the Review UI
        recognizes an "unrecognized document type" (or low-confidence) result
        that skipped extraction entirely — see `services/ingestion.py`.
        """
        update: dict[str, Any] = {"mode": mode, "pages": pages, "status": "review"}
        if doc_type is not None:
            update["doc_type"] = doc_type
        self._client.table(_TABLE).update(update).eq("id", str(document_id)).execute()

    def mark_failed(self, *, document_id: UUID, error: str) -> None:
        """Record a processing failure: `status='failed'` with an error message."""
        self._client.table(_TABLE).update({"status": "failed", "error": error}).eq(
            "id", str(document_id)
        ).execute()

    def mark_confirmed(self, *, document_id: UUID) -> None:
        """Transition a document to `confirmed` (T7 Confirm action).

        Also stamps `confirmed_at` (migration 003), which T8's export `meta`
        block and history list surface.
        """
        confirmed_at = datetime.now(UTC).isoformat()
        self._client.table(_TABLE).update({"status": "confirmed", "confirmed_at": confirmed_at}).eq(
            "id", str(document_id)
        ).execute()

    def get_by_id(self, document_id: UUID) -> dict[str, Any] | None:
        """Return the document row, or None if it does not exist (T7)."""
        result = self._client.table(_TABLE).select("*").eq("id", str(document_id)).execute()
        rows = cast(list[dict[str, Any]], result.data)
        return rows[0] if rows else None

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
        result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        rows = cast(list[dict[str, Any]], result.data)
        total = result.count if result.count is not None else len(rows)
        return rows, total
