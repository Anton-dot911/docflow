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

### Batch semantics: partial success
A batch accepts the valid files and rejects the invalid ones **individually**,
rather than all-or-nothing. `POST /api/documents` returns `200` with one entry
per input file, in order:
`[{filename, status, document_id?, reason?}]`

- **accepted** → `status:"queued"` + `document_id` (file stored, row created,
  status stub scheduled).
- **rejected** → `status:"rejected"` + machine-readable `reason`
  (`too_large` | `bad_type`); the file is not stored and has no row.

The request only **hard-fails** with `400` when the request itself is
malformed — zero files (`reason:"no_files"`) or more than 10
(`reason:"too_many_files"`); body is `{message, reason}`. A `400` means nothing
was processed.

This extends the `docs/PLAN.md` shape (`[{document_id, status}]`) with
`filename`/`reason` and a response-only `rejected` status. It was chosen
deliberately over all-or-nothing so one bad file in a batch of ten does not
discard the nine good ones. `rejected` is **not** added to the SQL `doc_status`
enum — it exists only in the API response, since rejected files are never
persisted. (`no_files` is enforced in the service; via HTTP an empty multipart
body is also caught earlier by FastAPI's own `422`.)

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

## Preprocessing (T3)

### Text-vs-vision decision by text-coverage ratio (threshold 0.3)
For PDFs, `services/preprocess.py` extracts the text layer per page with
pypdfium2 and computes a **text-coverage ratio** — the fraction of processed
pages whose stripped text reaches `MIN_CHARS_PER_PAGE` (10) chars. At/above
`TEXT_MODE_THRESHOLD` (0.3) the document is handled as **text** (return the
extracted text, skip vision — cheaper and exact); **below** 0.3 it falls back to
**vision** (rasterize pages). The boundary is inclusive on the text side: exactly
0.3 → text, 0.2 → vision. `text_coverage_ratio()` / `page_has_text()` are pure
functions, unit-tested around the boundary without any PDF I/O. JPG/PNG uploads
skip the decision and go straight to vision.

### Page cap: 20 pages processed in T3
Both text extraction and rasterization stop after `MAX_PAGES` (**20**) pages, so
a pathological 200-page upload can't blow up latency/cost. `PreprocessedDoc.pages`
is the number of pages **actually processed** (`min(total, 20)`), so for normal
small documents it equals the true page count and for oversized ones it is 20.
The coverage ratio is likewise computed over the processed pages only.

### 1568px long-side cap for vision images
Rasterized PDF pages and normalized JPG/PNG uploads are constrained to
`MAX_LONG_SIDE_PX` (1568) on the long edge — a sensible resolution for Claude
vision that bounds image tokens/cost. PDF pages are rendered straight to the
target long side (scale = 1568 / long-side-in-points, never upscaling beyond it),
then a post-render resize guards rounding. Images are only ever **downscaled**,
never enlarged. All vision output is re-encoded as PNG (RGB).

### `PreprocessedDoc` location + invariants
The contract model lives in `app/models/preprocess.py` (verbatim shape:
`{mode, text?, images?, pages}`). A post-init validator enforces the obvious
invariant — text mode has non-empty `text`, vision mode has ≥1 image — which
catches wiring mistakes without changing the contract's field shape.

### Background worker runs preprocessing in-process (no Storage re-fetch)
The T2 status stub (`_run_status_stub`) is replaced by `_run_preprocess`:
`queued -> processing -> preprocess -> review`, persisting `mode`/`pages` in the
same update that advances to `review` (`DocumentsRepo.mark_reviewable`). Any
preprocessing error moves the row to `failed` with the message
(`mark_failed`) instead of stranding it in `processing`. FastAPI BackgroundTasks
run in-process right after the response, so the already-read upload bytes are
handed to the worker directly rather than re-downloaded from Storage; the
`INGESTION_STUB_DELAY_SECONDS` knob is gone (preprocessing is fast and real).

### Migration 002 adds `mode` + `pages` (nullable)
`supabase/migrations/002_preprocess.sql` adds `documents.mode text`
(`check in ('text','vision')`) and `documents.pages int` (`check >= 0`). Both are
nullable because a row is `queued`/`processing`/`failed` before preprocessing
completes; they are written only when the worker reaches `review`.

### New dependencies: pypdfium2 + Pillow
`pypdfium2` (PDFium bindings — no system poppler, permissive licence) does PDF
text extraction and page rasterization; `Pillow` does the resize + PNG encode and
normalizes image uploads. Neither ships a `py.typed` marker relevant to us —
`pypdfium2.*` is marked `ignore_missing_imports` for mypy strict (Pillow ships
its own types).

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
