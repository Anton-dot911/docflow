"""Repository for the `extractions` table.

All DB access for extractions goes through here (CLAUDE.md rule 8: no raw SQL in
route handlers). Uses the service-role Supabase client, so RLS is bypassed and
the caller scopes by the parent document. T5 writes one row per successful
extraction with the payload, per-field confidences and the call's cost/latency.
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
        model: str,
        tokens_in: int | None,
        tokens_out: int | None,
        cost_usd: Decimal | None,
        latency_ms: int | None,
    ) -> dict[str, Any]:
        """Insert one extraction row and return it.

        `payload` and `field_confidences` are already JSON-native (see
        `services/extract.py`, which dumps the Pydantic models in JSON mode so
        Decimals become numeric strings and dates ISO 8601). `cost_usd` is a
        `Decimal` (CLAUDE.md rule 7) serialized as a string to preserve its
        5-decimal precision into the `numeric(10,5)` column. `schema_version`
        and `validation_issues` keep their DDL defaults (1 and `[]`); validation
        (T6) fills the latter later.
        """
        row = {
            "document_id": str(document_id),
            "payload": payload,
            "field_confidences": field_confidences,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": str(cost_usd) if cost_usd is not None else None,
            "latency_ms": latency_ms,
        }
        result = self._client.table(_TABLE).insert(row).execute()
        return cast(dict[str, Any], result.data[0])
