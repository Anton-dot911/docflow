# Design decisions

## Ingestion (T2)

### Placeholder user_id (auth out of scope)
Auth is not part of T2. `documents.user_id` is `uuid NOT NULL`, so ingestion
writes every row under a fixed placeholder UUID
`00000000-0000-0000-0000-000000000000` (`app.config.PLACEHOLDER_USER_ID`), also
used as the first Storage path segment. When real auth lands, this constant is
replaced by the authenticated user's id and the RLS `user_id = auth.uid()`
policy (already defined in migration 001) starts doing real work. The service
role key used by the repos layer bypasses RLS, which is why inserts succeed
today.

### Batch semantics: all-or-nothing (keeps the response contract verbatim)
The API contract in `docs/PLAN.md` is `POST /api/documents -> [{document_id,
status}]`. The task also requires "clear 4xx errors and per-file results" on
invalid input. To honour the success contract exactly while still reporting
per-file detail, a batch is **all-or-nothing**: every file is validated first;
if any file fails, the whole request is rejected with `422` and a body
`{message, results:[{filename, accepted, error}]}` and **nothing is stored** —
so the `2xx` body is always the documented `[{document_id, status}]` with no
rejected/`null` entries mixed in. A wrong number of files (outside 1..10) is a
request-level error → `400`. This interpretation does not change the contract;
if partial-success (per-file `207`-style) is wanted later, that is a contract
change to be raised explicitly.

### File-type validation by magic bytes
Accepted types (pdf/jpg/png) are decided from leading-byte signatures
(`app/services/filetypes.py`), not the extension or the client-supplied MIME
header, so a renamed `.exe -> .pdf` (PE `MZ` header) is rejected. Size limit is
10 MB/file, enforced on the read content length.

### Private Storage bucket, created programmatically
The `documents` bucket is created on demand via the service-role key with
`public=False` (`StorageRepo.ensure_bucket`, idempotent). Files live at
`{user_id}/{document_id}/{filename}`.

### Background status stub
`documents.status` walks `queued -> processing -> review` via a FastAPI
background task (`_run_status_stub`) with a configurable delay
(`INGESTION_STUB_DELAY_SECONDS`, default 1s; tests use 0). This exercises the
status flow end-to-end; T3+ replaces the stub with real preprocessing.

### supabase declared as a direct dependency
`supabase` was already resolved transitively through `meter`; T2 declares it
explicitly in `pyproject.toml` so the repos layer does not rely on a transitive
pin. Its sub-packages ship incomplete type stubs, so `supabase.*`, `storage3.*`,
and `postgrest.*` are marked `ignore_missing_imports` for mypy strict.

## Scaffolder friction (T7)

Generated with `npx github:Anton-dot911/Project-Scaffolder` (`antlab-create`):
`py-service` → `backend/`, and the **web** part of `ts-fullstack` → `frontend/`.
Every manual fix the generated output needed is logged here (this doubles as
Scaffolder's T7 acceptance).

### Frontend — extracting only the web app from `ts-fullstack`
- `ts-fullstack` generates a **3-package pnpm workspace** (`web/` + `service/` +
  `shared/`). DocFlow's backend is the separate Python `py-service`, not the
  template's Fastify `service/`, so only `web/` was taken. Dropped
  `pnpm-workspace.yaml`, the root workspace `package.json`, `service/`, and
  `shared/`.
- `web/` imported the health wire-schema from the workspace package
  `@docflow-frontend/shared`. With `shared/` dropped, that zod schema was
  **inlined** into `frontend/src/api/schemas.ts`.
- Built a standalone `frontend/package.json` by merging `web/`'s deps with the
  root's tooling devDeps (eslint, prettier, typescript-eslint,
  eslint-plugin-react-hooks) and adding `zod` (previously a `shared/` dep).
- Moved the workspace-root tooling configs into `frontend/`:
  `tsconfig.base.json`, `eslint.config.js`, `.prettierrc.json`,
  `.prettierignore`, `.gitignore`.
- `eslint.config.js` scoped the react-hooks rules to `web/src/**`; retargeted to
  `src/**` after flattening `web/` up into `frontend/`.
- Reorganized `web/src/lib/api.ts` into `frontend/src/api/{client,schemas}.ts`
  to match the `src/api/` layout in the root CLAUDE.md.
- `web/vite.config.ts` proxied `/health` to the Fastify service on
  `localhost:3000`; repointed to the FastAPI backend on `localhost:8000` and
  added an `/api` proxy.

### Backend
- `pyproject.toml` hardcodes `readme = "README.md"`; the editable install fails
  (`OSError: Readme file does not exist: README.md`) when the file is absent. We
  dropped the template's TODO-only README stub (project rule 10 forbids adding
  doc files; DoD forbids leftover TODOs), so removed the `readme` field.
- `Dockerfile` base image was `python3.13`; the project targets 3.12
  (CLAUDE.md / `requires-python`). Changed to `python3.12` and switched both
  `uv sync` steps to `--frozen` now that `uv.lock` is committed.

### Both templates
- Each template ships per-package `CLAUDE.md`, `README.md`, and `LICENSE` full
  of TODO placeholders. Dropped them: the repo-root `CLAUDE.md` governs, rule 10
  forbids creating doc files, and the DoD forbids stray TODOs.
- Each template ships its own single-package `.github/workflows/ci.yml`. In the
  merged monorepo these were replaced by one root `.github/workflows/ci.yml`
  with separate `backend` and `frontend` jobs (each with a `working-directory`).
- Backend template CI pinned `python-version: "3.13"`; switched to `3.12`.

### Health contract
- The template `/health` returned a static `{status: "ok"}` (and the frontend
  schema expected `{status, service}`). T1 requires `/health` to return the
  commit SHA. Backend now returns `{status, commit}` via `app/version.py`, which
  resolves the SHA from an env var (`GIT_COMMIT`/`COMMIT_SHA`/…) first, then
  `git rev-parse HEAD`, else `"unknown"` — deploys don't ship `.git` (see
  `.dockerignore`), so the SHA must be injected via env at deploy time. The
  frontend schema, `App.tsx`, and `tests/api.test.ts` were updated to `commit`.

### Notes (not blockers, deferred)
- The scaffolded `app/llm/client.py` defaults to model `claude-sonnet-4-6` as a
  placeholder. T1 makes no live LLM calls; model selection is revisited in
  T4/T5. Meter wiring is already present via `metered_client`; pinned to the
  `docflow` project through `create_docflow_llm` in `app/llm/__init__.py`.
