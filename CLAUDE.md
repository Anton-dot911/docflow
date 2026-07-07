# CLAUDE.md — DocFlow (Document Intelligence Pipeline)

## What this project is
Service that turns unstructured business documents (invoices, acts — PDF/scans/photos) into validated structured data with a human-in-the-loop review UI. Full spec: `docs/TZ.md`. Current work plan: `docs/PLAN.md` — work on ONE task at a time, in order, unless told otherwise.

## Stack
- Backend: Python 3.12, FastAPI, Pydantic v2, `anthropic` SDK, Supabase (Postgres + Storage)
- Frontend: React 18 + Vite + TypeScript (strict) + Tailwind
- Tests: pytest (backend), vitest (frontend)
- Package managers: `uv` (backend), `pnpm` (frontend)

## Commands
- Backend dev: `cd backend && uv run fastapi dev app/main.py`
- Backend tests: `cd backend && uv run pytest`
- Lint: `uv run ruff check . && uv run mypy app`
- Frontend dev: `cd frontend && pnpm dev`
- Frontend tests: `cd frontend && pnpm test`
- Evals: `cd backend && make eval` (requires `data/golden/` dataset)

## Hard rules
1. NEVER parse LLM free-text output with regex/string matching. All structured LLM outputs go through tool use with Pydantic-generated schemas, validated by the same Pydantic model. On validation failure: exactly one retry with the validation error appended.
2. Prompts live in `backend/prompts/<name>.v<N>.md` as files. Never inline prompt text in Python code. Bumping prompt content = new version file, old one stays.
3. Every Claude API call goes through `app/llm/client.py` (metered wrapper). Never instantiate `anthropic.Anthropic()` elsewhere.
4. Temperature 0 for all extraction/classification calls.
5. Extraction must return `null` for missing fields — never fabricate values. This is asserted in evals.
6. API keys only server-side. Frontend never calls Anthropic directly.
7. All money/quantity fields: `Decimal`, never float. Dates: ISO 8601 strings in JSON, `date` in Python.
8. DB access via the repository layer `app/repos/`. No raw SQL in route handlers.
9. Do not add new dependencies without a comment in the PR/commit body explaining why.
10. Do not create documentation files unless asked. Update existing ones.

## Structure
```
backend/
  app/
    main.py          # FastAPI app, routers only
    routes/          # HTTP layer, thin
    services/        # ingestion, classify, extract, validate pipelines
    llm/             # client wrapper, schema helpers
    repos/           # DB access
    models/          # Pydantic domain models (contracts — see docs/CONTRACTS in PLAN.md)
  prompts/
  tests/
  data/golden/       # eval dataset (JSONL from Goldsmith)
frontend/
  src/
    pages/           # Upload, Review, History, Demo
    components/
    api/             # typed client
```

## Definition of done for any task
- Lint + typecheck + tests pass
- New logic has tests; AI components have eval coverage
- No TODOs left in touched code without an issue reference

## Testing conventions
- Unit tests mock the LLM layer (fixture `mock_llm` in `tests/conftest.py`); never call the real API in unit tests.
- Integration tests hitting real API are marked `@pytest.mark.llm` and excluded by default.
- Validation logic (arithmetic, EDRPOU checksum, dates) is pure functions in `services/validate.py` — test exhaustively, no mocks needed.
