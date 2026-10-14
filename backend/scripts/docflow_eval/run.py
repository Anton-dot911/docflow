"""T11 eval entry point (`make eval`).

Loads the Goldsmith golden dataset, runs the real DocFlow pipeline over every
example, computes the four T11 metrics grouped by category, writes
`eval_runs/<timestamp>.json`, prints a metrics table, and compares against the
most recent prior run (exit 1 on a field-accuracy regression > 2pp, per the
docs/PLAN.md contract).

Environment (all already present in the session):
  GOLDSMITH_EXPORT_URL / GOLDSMITH_EXPORT_TOKEN  — dataset export
  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY       — golden file download
  ANTHROPIC_API_KEY                              — real extraction/classification

Usage:
  uv run python -m docflow_eval.run [--fetch] [--dataset SLUG] [--version N]
  (`make eval` runs it with --fetch.)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.flags import count_flags
from docflow_eval.golden import (
    GoldenExample,
    fetch_dataset,
    load_golden,
    resolve_file,
    save_dataset,
)
from docflow_eval.metrics import ALL_CATEGORY, CategoryMetrics, DocEval, by_category
from docflow_eval.pipeline import PipelineResult, run_pipeline
from docflow_eval.scoring import (
    FALSE_CONFIDENCE_THRESHOLD,
    actual_for_field,
    confidence_for_field,
    evaluate_field,
    normalize_tags,
)

# scripts/docflow_eval/run.py -> backend/
BACKEND_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = BACKEND_ROOT / "data" / "golden" / "invoices.jsonl"
FILES_CACHE = BACKEND_ROOT / "data" / "golden" / "files"
EVAL_RUNS_DIR = BACKEND_ROOT / "eval_runs"

DATASET = "docflow-invoices"
VERSION = 1
# Field-accuracy (ALL) regression beyond this fails the run (docs/PLAN.md).
REGRESSION_THRESHOLD_PP = 0.02


def _pct(value: float | None) -> str:
    return "   n/a" if value is None else f"{value * 100:5.1f}%"


def _score_example(example: GoldenExample, result: PipelineResult) -> DocEval:
    """Score one pipeline result against its golden label."""
    field_evals = []
    for field, expected in example.expected.items():
        actual = actual_for_field(field, result.payload, result.doc_type)
        confidence = confidence_for_field(field, result.confidences, result.doc_type)
        field_evals.append(evaluate_field(field, expected, actual, confidence))
    return DocEval(
        id=example.id,
        raw_tags=example.tags,
        categories=normalize_tags(example.tags),
        doc_type=result.doc_type,
        extracted=result.extracted,
        schema_valid=result.schema_valid,
        field_evals=field_evals,
        total_payload_fields=len(result.field_confidences_raw),
        flagged_payload_fields=count_flags(
            result.field_confidences_raw, result.validation_issues_raw
        ),
    )


def _print_table(metrics: dict[str, CategoryMetrics], n_examples: int) -> None:
    header = (
        f"{'category':<20}{'docs':>5}{'fields':>7}{'acc':>8}"
        f"{'schema':>8}{'review':>8}{'false-conf':>12}"
    )
    print(header)
    print("-" * len(header))
    # ALL first, then categories alphabetically.
    ordered = [ALL_CATEGORY, *sorted(k for k in metrics if k != ALL_CATEGORY)]
    for name in ordered:
        m = metrics[name]
        fc = f"{_pct(m.false_confidence_rate)} ({m.n_false_confidence})"
        print(
            f"{name:<20}{m.n_docs:>5}{m.n_comparable_fields:>7}"
            f"{_pct(m.field_accuracy):>8}{_pct(m.schema_validity_rate):>8}"
            f"{_pct(m.review_flag_rate):>8}{fc:>12}"
        )
    print("-" * len(header))
    print(f"N = {n_examples} examples (see summary for sample-size caveat)")


def _print_findings(doc_evals: list[DocEval]) -> None:
    print(
        "\n=== FALSE-CONFIDENCE FINDINGS (confidence >= "
        f"{FALSE_CONFIDENCE_THRESHOLD:.2f} but value wrong) ==="
    )
    any_found = False
    for d in doc_evals:
        for fe in d.field_evals:
            if fe.false_confidence:
                any_found = True
                print(
                    f"  {d.id}  field={fe.field}  expected={fe.expected!r}  "
                    f"got={fe.actual!r}  confidence={fe.confidence}"
                )
    if not any_found:
        print("  none — no field was confidently wrong.")


def _print_per_doc(doc_evals: list[DocEval], results: dict[str, PipelineResult]) -> None:
    print("\n=== PER-DOCUMENT DETAIL ===")
    for d in doc_evals:
        r = results[d.id]
        cost = f"${r.cost_usd}" if r.cost_usd is not None else "n/a"
        print(
            f"\n{d.id}  tags={d.raw_tags} -> {d.categories}  "
            f"class={d.doc_type}@{r.classify_confidence:.2f}  mode={r.mode}  "
            f"extracted={d.extracted}  schema_valid={d.schema_valid}  "
            f"cost={cost}  latency={r.latency_ms}ms"
        )
        if r.error:
            print(f"    ERROR: {r.error}")
        for fe in d.field_evals:
            if not fe.comparable:
                print(f"    {fe.field:<16} [not in contract — excluded]  expected={fe.expected!r}")
                continue
            mark = "OK " if fe.matched else "XX "
            flags = []
            if fe.sentinel_empty:
                flags.append("sentinel-empty")
            if fe.false_confidence:
                flags.append("FALSE-CONFIDENCE")
            suffix = f"  [{', '.join(flags)}]" if flags else ""
            conf = "n/a" if fe.confidence is None else f"{fe.confidence:.2f}"
            print(
                f"    {mark}{fe.field:<16} expected={fe.expected!r}  "
                f"got={fe.actual!r}  conf={conf}{suffix}"
            )


def _previous_run(current_path: Path) -> Path | None:
    prior = sorted(p for p in EVAL_RUNS_DIR.glob("*.json") if p != current_path)
    return prior[-1] if prior else None


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"not JSON serialisable: {type(value)!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the DocFlow T11 eval.")
    parser.add_argument("--fetch", action="store_true", help="re-download the dataset JSONL first")
    parser.add_argument("--dataset", default=DATASET)
    parser.add_argument("--version", type=int, default=VERSION)
    args = parser.parse_args(argv)

    if args.fetch:
        token = os.environ["GOLDSMITH_EXPORT_TOKEN"]
        url = os.environ["GOLDSMITH_EXPORT_URL"]
        print(f"Fetching dataset {args.dataset}@{args.version} ...")
        text = fetch_dataset(url=url, token=token, dataset=args.dataset, version=args.version)
        save_dataset(text, GOLDEN_PATH)
        print(f"Saved -> {GOLDEN_PATH}")

    if not GOLDEN_PATH.is_file():
        print(f"ERROR: {GOLDEN_PATH} not found. Run with --fetch first.", file=sys.stderr)
        return 2

    examples = load_golden(GOLDEN_PATH)
    n = len(examples)
    print(f"Loaded {n} examples from {GOLDEN_PATH}\n")

    doc_evals: list[DocEval] = []
    results: dict[str, PipelineResult] = {}
    for i, example in enumerate(examples, start=1):
        print(f"[{i}/{n}] {example.id}  tags={example.tags} ...", flush=True)
        content = resolve_file(example.file_ref, cache_dir=FILES_CACHE)
        result = run_pipeline(content)
        results[example.id] = result
        doc_evals.append(_score_example(example, result))

    metrics = by_category(doc_evals)
    models = sorted({r.model for r in results.values() if r.model})
    total_cost = sum((r.cost_usd for r in results.values() if r.cost_usd is not None), Decimal("0"))

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = EVAL_RUNS_DIR / f"{timestamp}.json"
    EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)

    previous = _previous_run(out_path)
    prev_all_accuracy: float | None = None
    if previous is not None:
        prev_data = json.loads(previous.read_text(encoding="utf-8"))
        prev_all_accuracy = prev_data.get("metrics", {}).get(ALL_CATEGORY, {}).get("field_accuracy")

    # Print the human-readable report before persisting, so a write hiccup never
    # costs the run its (expensive, already-billed) results.
    print(f"\n=== METRICS BY CATEGORY (N={n}) ===")
    _print_table(metrics, n)
    _print_findings(doc_evals)
    _print_per_doc(doc_evals, results)

    run_record: dict[str, Any] = {
        "timestamp": timestamp,
        "dataset": args.dataset,
        "dataset_version": args.version,
        "n_examples": n,
        "models": models,
        "extraction_model": os.environ.get("LLM_MODEL"),
        "total_cost_usd": str(total_cost),
        "false_confidence_threshold": FALSE_CONFIDENCE_THRESHOLD,
        "metrics": {name: asdict(m) for name, m in metrics.items()},
        "documents": [
            {
                "id": d.id,
                "raw_tags": d.raw_tags,
                "categories": d.categories,
                "doc_type": d.doc_type,
                "extracted": d.extracted,
                "schema_valid": d.schema_valid,
                "classify_confidence": results[d.id].classify_confidence,
                "mode": results[d.id].mode,
                "cost_usd": (
                    str(results[d.id].cost_usd) if results[d.id].cost_usd is not None else None
                ),
                "latency_ms": results[d.id].latency_ms,
                "error": results[d.id].error,
                "fields": [asdict(fe) for fe in d.field_evals],
            }
            for d in doc_evals
        ],
        "previous_run": previous.name if previous else None,
    }
    out_path.write_text(json.dumps(run_record, indent=2, default=_json_default, ensure_ascii=False))

    print(f"\nModels used: {models}")
    print(f"Total extraction cost: ${total_cost}")
    print(f"Run written -> {out_path.relative_to(BACKEND_ROOT)}")

    all_metrics = metrics[ALL_CATEGORY]
    print("\n=== COMPARISON ===")
    if previous is None or prev_all_accuracy is None:
        print("Baseline run — no prior run to compare against.")
        exit_code = 0
    else:
        current = all_metrics.field_accuracy or 0.0
        delta = current - prev_all_accuracy
        print(
            f"Previous ({previous.name}) field accuracy: {_pct(prev_all_accuracy)}; "
            f"current: {_pct(current)}; delta: {delta * 100:+.1f}pp"
        )
        if -delta > REGRESSION_THRESHOLD_PP:
            print(f"REGRESSION > {REGRESSION_THRESHOLD_PP * 100:.0f}pp — failing.")
            exit_code = 1
        else:
            print("No regression beyond threshold.")
            exit_code = 0

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
