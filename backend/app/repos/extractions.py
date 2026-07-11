"""Repository for the `extractions` table.

All DB access for extractions goes through here (CLAUDE.md rule 8: no raw SQL in
route handlers). Uses the service-role Supabase client, so RLS is bypassed and
the caller scopes by the parent document. T5 writes one row per successful
extraction with the payload, per-field confidences and the call's cost/latency;
T6 adds the deterministic `validation_issues` produced by `services/validate.py`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from app.repos.supabase_client import get_supabase

_TABLE = "extractions"


class ExtractionsRepo:
    """Insert extraction rows produced by the extraction pipeline (T5)."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client if client is not None else get_supabase()

    def create(
        self,
        *,
        document_id: UUID,
        payload: dict[str, Any],
        field_confidences: list[dict[str, Any]],
        validation_issues: list[dict[str, Any]],
        model: str,
        tokens_in: int | None,
        tokens_out: int | None,
        cost_usd: Decimal | None,
        latency_ms: int | None,
    ) -> dict[str, Any]:
        """Insert one extraction row and return it.

        `payload`, `field_confidences` and `validation_issues` are already
        JSON-native (see `services/extract.py`, which dumps the Pydantic
        models in JSON mode so Decimals become numeric strings and dates ISO
        8601). `cost_usd` is a `Decimal` (CLAUDE.md rule 7) serialized as a
        string to preserve its 5-decimal precision into the `numeric(10,5)`
        column. `schema_version` keeps its DDL default (1).
        """
        row = {
            "document_id": str(document_id),
            "payload": payload,
            "field_confidences": field_confidences,
            "validation_issues": validation_issues,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": str(cost_usd) if cost_usd is not None else None,
            "latency_ms": latency_ms,
        }
        result = self._client.table(_TABLE).insert(row).execute()
        return cast(dict[str, Any], result.data[0])

    def get_by_id(self, extraction_id: UUID) -> dict[str, Any] | None:
        """Return one extraction row by id, or None (T7 PATCH target lookup)."""
        result = self._client.table(_TABLE).select("*").eq("id", str(extraction_id)).execute()
        rows = cast(list[dict[str, Any]], result.data)
        return rows[0] if rows else None

    def get_latest_by_document(self, document_id: UUID) -> dict[str, Any] | None:
        """Return the most recent extraction for a document, or None (T7 GET)."""
        result = (
            self._client.table(_TABLE)
            .select("*")
            .eq("document_id", str(document_id))
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = cast(list[dict[str, Any]], result.data)
        return rows[0] if rows else None

    def get_latest_for_documents(self, document_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Return the latest extraction row per document_id, keyed by document_id.

        One batched query instead of N+1 (T8 history list needs each row's
        total/flags_count). Rows come back newest-first, so the first row seen
        per document_id is the latest and later duplicates are ignored.
        """
        if not document_ids:
            return {}
        result = (
            self._client.table(_TABLE)
            .select("*")
            .in_("document_id", document_ids)
            .order("created_at", desc=True)
            .execute()
        )
        rows = cast(list[dict[str, Any]], result.data)
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest.setdefault(row["document_id"], row)
        return latest

    def update_after_edit(
        self,
        extraction_id: UUID,
        *,
        payload: dict[str, Any],
        field_confidences: list[dict[str, Any]],
        validation_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Persist a T7 review edit: new payload/confidences/issues for one row."""
        result = (
            self._client.table(_TABLE)
            .update(
                {
                    "payload": payload,
                    "field_confidences": field_confidences,
                    "validation_issues": validation_issues,
                }
            )
            .eq("id", str(extraction_id))
            .execute()
        )
        return cast(dict[str, Any], result.data[0])
