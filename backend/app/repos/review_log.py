"""Repository for the `review_log` table.

Append-only audit trail of operator edits (CLAUDE.md rule 8: no raw SQL in
route handlers). One row per PATCH /api/extractions/{id} call (T7); the DDL's
`old_value`/`new_value` columns are jsonb, so both are stored as whatever
JSON-native value the caller passes.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from app.repos.supabase_client import get_supabase

_TABLE = "review_log"


class ReviewLogRepo:
    """Insert-only access to review_log rows written by the Review UI (T7)."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client if client is not None else get_supabase()

    def create(
        self,
        *,
        extraction_id: UUID,
        field_path: str,
        old_value: Any,
        new_value: Any,
    ) -> dict[str, Any]:
        row = {
            "extraction_id": str(extraction_id),
            "field_path": field_path,
            "old_value": old_value,
            "new_value": new_value,
        }
        result = self._client.table(_TABLE).insert(row).execute()
        return cast(dict[str, Any], result.data[0])
