"""Real-pipeline smoke test for T5 extraction, excluded from default runs.

Uploads the two committed invoice fixtures through the real stack — T2 endpoint
(POST /api/documents) -> T3 preprocess -> T5 extract — hitting the real Anthropic
API and real Supabase. Asserts both documents reach status ``review`` and that
the clean text fixture clears the DoD bar of >=80% correct fields, printing a
field-by-field table plus the persisted extraction row (incl. cost_usd) and the
recent ``llm_calls`` entries as evidence.

Run with real credentials (Supabase creds in the env, Anthropic key exported;
pick a current model):

    ANTHROPIC_API_KEY=$METER_ANTHROPIC_API_KEY LLM_MODEL=claude-sonnet-5 \
        uv run pytest -m llm tests/test_extract_smoke.py -s

Marked ``llm`` so it is excluded from the hermetic default suite.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.config import PLACEHOLDER_USER_ID, STORAGE_BUCKET
from app.main import app
from app.repos.supabase_client import get_supabase

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        "ANTHROPIC_API_KEY" not in os.environ,
        reason="needs ANTHROPIC_API_KEY",
    ),
    pytest.mark.skipif(
        not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")),
        reason="needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY",
    ),
]

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
_NUMERIC_PATHS = {"quantity", "unit_price", "amount", "subtotal", "vat_amount", "total"}


def _read(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return fh.read()


def _norm(text: str) -> str:
    """Loose text normalization for names/addresses: fold quotes and spaces."""
    for ch in "«»\"'“”„":
        text = text.replace(ch, "")
    return " ".join(text.lower().split())


def _values_match(path_leaf: str, expected: Any, actual: Any) -> bool:
    if expected is None:
        return actual is None
    if actual is None:
        return False
    if path_leaf in _NUMERIC_PATHS:
        try:
            return Decimal(str(actual)) == Decimal(str(expected))
        except Exception:
            return False
    if path_leaf == "invoice_date":
        return str(actual) == str(expected)
    return _norm(str(actual)) == _norm(str(expected))


def _flatten_expected() -> list[tuple[str, str, Any]]:
    """(dot_path, leaf, expected_value) for every scalar field we score."""
    if FIXTURES not in sys.path:
        sys.path.insert(0, FIXTURES)
    from generate_invoice_fixtures import EXPECTED_INVOICE_TEXT

    exp = EXPECTED_INVOICE_TEXT
    rows: list[tuple[str, str, Any]] = []
    for party in ("supplier", "buyer"):
        for leaf in ("name", "tax_id", "address"):
            rows.append((f"{party}.{leaf}", leaf, exp[party][leaf]))
    rows.append(("invoice_number", "invoice_number", exp["invoice_number"]))
    rows.append(("invoice_date", "invoice_date", exp["invoice_date"]))
    for i, item in enumerate(exp["items"]):
        for leaf in ("name", "quantity", "unit_price", "amount"):
            rows.append((f"items[{i}].{leaf}", leaf, item[leaf]))
    for leaf in ("subtotal", "vat_amount", "total"):
        rows.append((leaf, leaf, exp[leaf]))
    return rows


def _get_by_path(payload: dict[str, Any], dot_path: str) -> Any:
    node: Any = payload
    for part in dot_path.split("."):
        if "[" in part:
            key, idx = part[: part.index("[")], int(part[part.index("[") + 1 : part.index("]")])
            node = node.get(key) or []
            node = node[idx] if idx < len(node) else None
        else:
            node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            return None
    return node


def _upload(client: TestClient, name: str, content_type: str) -> str:
    resp = client.post("/api/documents", files=[("files", (name, _read(name), content_type))])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body[0]["status"] == "queued"
    return cast(str, body[0]["document_id"])


def test_both_fixtures_flow_to_review_and_clean_hits_80pct() -> None:
    supabase = get_supabase()
    created_ids: list[str] = []
    try:
        # BackgroundTasks run synchronously once TestClient's post() returns, so
        # the full T2->T3->T5 pipeline has finished by the time we read the rows.
        with TestClient(app) as client:
            text_id = _upload(client, "invoice_text.pdf", "application/pdf")
            scan_id = _upload(client, "invoice_scan.jpg", "image/jpeg")
        created_ids = [text_id, scan_id]

        # Both documents reached review.
        for doc_id, label in ((text_id, "text"), (scan_id, "scan")):
            row = cast(
                dict[str, Any],
                supabase.table("documents").select("*").eq("id", doc_id).single().execute().data,
            )
            print(f"\n[{label}] status={row['status']} mode={row['mode']} error={row.get('error')}")
            assert row["status"] == "review", f"{label} did not reach review: {row}"

        # Pull the clean-fixture extraction row.
        extraction = cast(
            dict[str, Any],
            supabase.table("extractions")
            .select("*")
            .eq("document_id", text_id)
            .single()
            .execute()
            .data,
        )
        payload = extraction["payload"]
        conf_by_path = {c["path"]: c["confidence"] for c in extraction["field_confidences"]}

        # Field-by-field scoring against the known clean invoice.
        rows = _flatten_expected()
        correct = 0
        print("\n=== FIELD-BY-FIELD (clean text fixture) ===")
        print(f"{'field':<22} {'expected':<34} {'extracted':<34} {'conf':>5}  ok")
        for dot_path, leaf, expected in rows:
            actual = _get_by_path(payload, dot_path)
            ok = _values_match(leaf, expected, actual)
            correct += int(ok)
            conf = conf_by_path.get(dot_path)
            conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else "  - "
            print(
                f"{dot_path:<22} {expected!s:<34.34} {actual!s:<34.34} {conf_s:>5}  "
                f"{'Y' if ok else 'N'}"
            )
        accuracy = correct / len(rows)
        print(f"\nfields correct: {correct}/{len(rows)} = {accuracy:.0%}")

        print("\n=== EXTRACTION ROW ===")
        for key in (
            "id",
            "document_id",
            "model",
            "tokens_in",
            "tokens_out",
            "cost_usd",
            "latency_ms",
            "schema_version",
        ):
            print(f"  {key}: {extraction.get(key)}")
        print("  payload:", payload)

        # Recent llm_calls evidence (append-only meter records for this project).
        calls = (
            supabase.table("llm_calls")
            .select("ts,project,component,model,tokens_in,tokens_out,cost_usd,latency_ms,status")
            .eq("project", "docflow")
            .order("ts", desc=True)
            .limit(4)
            .execute()
            .data
        )
        print("\n=== RECENT llm_calls (project=docflow) ===")
        for call in calls:
            print(" ", call)

        assert accuracy >= 0.80, f"clean-fixture accuracy {accuracy:.0%} below 80% DoD"
    finally:
        for doc_id in created_ids:
            objects = supabase.storage.from_(STORAGE_BUCKET).list(f"{PLACEHOLDER_USER_ID}/{doc_id}")
            if objects:
                supabase.storage.from_(STORAGE_BUCKET).remove(
                    [f"{PLACEHOLDER_USER_ID}/{doc_id}/{o['name']}" for o in objects]
                )
            supabase.table("documents").delete().eq("id", doc_id).execute()
