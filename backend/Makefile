# DocFlow backend developer tasks.
#
# `make eval` runs the T11 evaluation harness (docs/PLAN.md T11): it fetches the
# Goldsmith golden dataset, runs the real pipeline (T3 preprocess -> T10 classify
# -> T5/T10 extract -> T6 validate) over every example, prints a metrics table by
# category and writes eval_runs/<timestamp>.json.
#
# Requires (already set in the Claude Code session env):
#   GOLDSMITH_EXPORT_URL / GOLDSMITH_EXPORT_TOKEN  — dataset export
#   SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY       — golden file download
#   ANTHROPIC_API_KEY                              — real extraction/classification
#
# scripts/ is added to PYTHONPATH so the `docflow_eval` package resolves without
# being installed (mirrors how tests import scripts/seed_demo.py).

.PHONY: eval test lint

eval:
	PYTHONPATH=scripts uv run python -m docflow_eval.run --fetch

test:
	uv run pytest

lint:
	uv run ruff check . && uv run mypy
