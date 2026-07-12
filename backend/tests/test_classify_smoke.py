"""Real-pipeline smoke test for T10 classification + act extraction.

Two parts, both hitting the real Anthropic API:

1. ``test_classify_all_fixtures`` — classifies every committed fixture (T5's
   invoices, T10's acts, and a garbage "other" letter) directly through
   `ClassificationService` and asserts each lands on the expected `doc_type`
   with confidence >= `CLASSIFY_REVIEW_CONFIDENCE_THRESHOLD`. Prints a table
   plus the classifier's own `llm_calls` rows (component="classify") as
   evidence of the Haiku model/cost.
2. ``test_act_flows_to_review_end_to_end`` — uploads the clean act fixture
   through the real stack (POST /api/documents -> preprocess -> classify ->
   route -> extract -> validate), same shape as T5's
   `test_extract_smoke.py::test_both_fixtures_flow_to_review_and_clean_hits_80pct`,
   scoring the extracted payload against `EXPECTED_ACT_TEXT`.

Run with real credentials (Supabase creds in the env, Anthropic key exported):

    ANTHROPIC_API_KEY=$METER_ANTHROPIC_API_KEY LLM_MODEL=claude-sonnet-5 \
        uv run pytest -m llm tests/test_classify_smoke.py -s

Marked ``llm`` so it is excluded from the hermetic default suite.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.config import CLASSIFY_REVIEW_CONFIDENCE_THRESHOLD, PLACEHOLDER_USER_ID, STORAGE_BUCKET
from app.main import app
from app.models.domain import DocType
from app.repos.supabase_client import get_supabase
from app.services.classify import ClassificationService
from app.services.preprocess import preprocess

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

# (filename, expected doc_type)
_CLASSIFY_FIXTURES: list[tuple[str, DocType]] = [
    ("invoice_text.pdf", DocType.invoice),
    ("invoice_scan.jpg", DocType.invoice),
    ("invoice_broken_total.pdf", DocType.invoice),
    ("act_text.pdf", DocType.act),
    ("act_scan.jpg", DocType.act),
    ("other_letter.pdf", DocType.other),
]


def _read(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return fh.read()


def _norm(text: str) -> str:
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
    if path_leaf == "act_date":
        return str(actual) == str(expected)
    return _norm(str(actual)) == _norm(str(expected))


def _flatten_expected_act() -> list[tuple[str, str, Any]]:
    if FIXTURES not in sys.path:
        sys.path.insert(0, FIXTURES)
    from generate_act_fixtures import EXPECTED_ACT_TEXT

    exp = EXPECTED_ACT_TEXT
    rows: list[tuple[str, str, Any]] = []
    for party in ("contractor", "customer"):
        for leaf in ("name", "tax_id", "address"):
            rows.append((f"{party}.{leaf}", leaf, exp[party][leaf]))
    rows.append(("act_number", "act_number", exp["act_number"]))
    rows.append(("act_date", "act_date", exp["act_date"]))
    for i, svc in enumerate(exp["services"]):
        for leaf in ("name", "quantity", "unit_price", "amount"):
            rows.append((f"services[{i}].{leaf}", leaf, svc[leaf]))
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


def test_classify_all_fixtures() -> None:
    service = ClassificationService()
    results: list[tuple[str, DocType, DocType, float]] = []
    print("\n=== CLASSIFY ALL FIXTURES ===")
    print(f"{'fixture':<26} {'expected':<10} {'actual':<10} {'confidence':>10}")
    for filename, expected in _CLASSIFY_FIXTURES:
        doc = preprocess(_read(filename))
        result = service.classify(doc)
        results.append((filename, expected, result.doc_type, result.confidence))
        print(
            f"{filename:<26} {expected.value:<10} {result.doc_type.value:<10} "
            f"{result.confidence:>10.2f}"
        )

    supabase = get_supabase()
    calls = (
        supabase.table("llm_calls")
        .select("ts,project,component,model,tokens_in,tokens_out,cost_usd,latency_ms,status")
        .eq("project", "docflow")
        .eq("component", "classify")
        .order("ts", desc=True)
        .limit(len(_CLASSIFY_FIXTURES))
        .execute()
        .data
    )
    print("\n=== RECENT llm_calls (project=docflow, component=classify) ===")
    for call in calls:
        print(" ", call)

    for filename, expected, actual, confidence in results:
        assert actual == expected, (
            f"{filename}: expected {expected}, got {actual} ({confidence:.2f})"
        )
        if expected != DocType.other:
            assert confidence >= CLASSIFY_REVIEW_CONFIDENCE_THRESHOLD, (
                f"{filename}: confidence {confidence:.2f} below review threshold"
            )


def _upload(client: TestClient, name: str, content_type: str) -> str:
    resp = client.post("/api/documents", files=[("files", (name, _read(name), content_type))])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body[0]["status"] == "queued"
    return cast(str, body[0]["document_id"])


def test_act_flows_to_review_end_to_end() -> None:
    supabase = get_supabase()
    created_ids: list[str] = []
    try:
        with TestClient(app) as client:
            act_id = _upload(client, "act_text.pdf", "application/pdf")
        created_ids = [act_id]

        row = cast(
            dict[str, Any],
            supabase.table("documents").select("*").eq("id", act_id).single().execute().data,
        )
        print(
            f"\n[act] status={row['status']} doc_type={row['doc_type']} "
            f"mode={row['mode']} error={row.get('error')}"
        )
        assert row["status"] == "review", f"act did not reach review: {row}"
        assert row["doc_type"] == "act", f"act classified as {row['doc_type']!r}"

        extraction = cast(
            dict[str, Any],
            supabase.table("extractions")
            .select("*")
            .eq("document_id", act_id)
            .single()
            .execute()
            .data,
        )
        payload = extraction["payload"]
        conf_by_path = {c["path"]: c["confidence"] for c in extraction["field_confidences"]}

        rows = _flatten_expected_act()
        correct = 0
        print("\n=== FIELD-BY-FIELD (clean act fixture) ===")
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
        print("validation_issues:", extraction["validation_issues"])

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

        calls = (
            supabase.table("llm_calls")
            .select("ts,project,component,model,tokens_in,tokens_out,cost_usd,latency_ms,status")
            .eq("project", "docflow")
            .order("ts", desc=True)
            .limit(6)
            .execute()
            .data
        )
        print("\n=== RECENT llm_calls (project=docflow) ===")
        for call in calls:
            print(" ", call)

        assert accuracy >= 0.80, f"clean act accuracy {accuracy:.0%} below 80% DoD"
        assert extraction["validation_issues"] == [], (
            f"clean act fixture produced validation issues: {extraction['validation_issues']}"
        )
    finally:
        for doc_id in created_ids:
            objects = supabase.storage.from_(STORAGE_BUCKET).list(f"{PLACEHOLDER_USER_ID}/{doc_id}")
            if objects:
                supabase.storage.from_(STORAGE_BUCKET).remove(
                    [f"{PLACEHOLDER_USER_ID}/{doc_id}/{o['name']}" for o in objects]
                )
            supabase.table("documents").delete().eq("id", doc_id).execute()
