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

## Review UI (T7)

### PATCH clears the matching T6 issue, not just the confidence
`PATCH /api/extractions/{id}` (`app/routes/extractions.py`) sets the edited
field's confidence to 1.0 **and** drops any `validation_issues` entry at that
same path, in addition to updating `payload`. The PLAN.md contract only says
"updates payload, sets confidence to 1.0" — clearing the issue isn't stated
explicitly, but without it a fixed field would still render red forever
(UI_SPEC: red = validation issue present, independent of confidence), so the
review flow could never reach all-green. `services/validate.py` guarantees a
1:1 correspondence between T6 issues and zeroed confidences at extraction
time; PATCH restores that invariant after an edit. "Прийняти як є" (accept
red as-is) and an actual correction are the same request shape — `new_value`
equal to vs. different from the current value — so both go through one code
path with no special-cased "accept" endpoint.

### Confirm's 409 gate is confidence-0 only; the UI's gate is stricter
`POST /api/documents/{id}/confirm` (`app/routes/documents.py`) 409s only when
a field's confidence is exactly 0 — i.e. an unresolved T6 issue — per the
PLAN.md route contract. Amber (low-confidence, no issue) fields do **not**
block the backend. The frontend's `canConfirm` (`state/confirmGate.ts`) is
stricter: it requires every field to be green (UI_SPEC §3.6, "all-green
state"), so the Confirm button stays disabled until amber fields are also
resolved even though the backend would accept a confirm with amber fields
still outstanding. This is intentional headroom, not a bug — the backend
enforces the correctness-critical case (a known-wrong value), the frontend
UX additionally asks the operator to at least glance at every low-confidence
field before shipping.

### Dot-path get/set duplicated (not shared) between backend and frontend
`app/services/field_path.py` (backend) and `src/state/fieldPath.ts`
(frontend) implement the same `"items[2].amount"` navigation independently —
the backend uses it to apply a PATCH server-side and validate the result
against `InvoiceData`; the frontend uses it for the reducer's optimistic
update and to read a field's current raw value for "Прийняти як є". No
shared package exists between the two runtimes (see the T7 Scaffolder-era
decision above about `shared/` being dropped), and the logic is ~30 lines of
pure functions on both sides, so duplication was chosen over adding a build
step to share it.

### `GET /api/documents/{id}` exposes `mode`/`pages` beyond the stated contract
The PLAN.md contract lists the response as "document + latest extraction
(payload, field_confidences, validation_issues)"; `DocumentDetailResponse`
additionally carries `mode` (`"text"|"vision"|null`, from T3 preprocessing)
and `pages`. The Review UI needs `mode` to decide whether in-document
text-layer search is even possible (see the next decision) — this was already
a column on `documents` (migration 002), just not yet surfaced over HTTP.

### Text-layer search / snippet-drawer fallback (UI_SPEC §3.2's "for scans/images")
Clicking a flagged field searches the pdf.js text layer for its
`source_snippet` (`state/textSearch.ts`'s `findSnippetItemIndices`, driven by
`DocumentPane`) and highlights the match in the document pane. This only
works when the original file has a real extractable text layer, i.e.
`mode === "text"` and the file isn't an image upload (`ReviewPage`'s
`documentSearchable`). For everything else — scans/photos in vision mode, or
a text-mode search that doesn't find a match — the field's own inline
"Фрагмент документа" drawer is shown instead, per the task instructions to
document this limitation. On mobile the drawer always shows (there's no
adjacent document pane to scroll to), matching the mockup exactly.

### Document pane: renderer picked by file extension, not by T3 `mode`
`.pdf` always renders via pdf.js (even a scanned/vision-mode PDF is a valid
PDF — pdf.js just won't find a text layer in it); `.jpg`/`.png` always render
as a plain `<img>`. `mode` only affects the text-search fallback above, not
which renderer runs. pdf.js pages are re-rendered at a scale computed from the
pane's actual container width (rather than a fixed scale + CSS resize) so the
text layer's pdf.js-computed absolute positions land pixel-for-pixel on the
canvas.

### Source chip is a mode label, not real provenance
The mockup's chip reads "Фото · Viber" — a specific channel DocFlow doesn't
capture. The Review UI's chip instead reads "Скан / Фото" (`mode ===
"vision"` or an image upload) or "PDF" — the one distinction the pipeline
actually knows. Revisit if/when T2 ingestion starts recording a source
channel.

### `pdfjs-dist` pinned to latest (6.1.200), no version workaround needed
`pdfjs-dist` was added as the one new frontend dependency the task
anticipated. During manual E2E verification in this sandbox, `page.render()`
threw `TypeError: ...getOrInsertComputed is not a function` — a very recent
`Map.prototype` builtin pdf.js now uses internally, missing from this
sandbox's headless Chromium (v141). Downgrading to 5.7.284 hit the same
error (the builtin is used there too), confirming it's a browser-version
floor rather than a bad version pick, so the pin stayed on latest. Any
current auto-updating desktop browser has this builtin; see
`docs/e2e-review-checklist.md` for the full root-cause trace.

### Manual E2E: seeded first (no credit), then re-run through the real pipeline
The Anthropic key initially had no credit balance, so the first manual E2E
pass substituted only the T5 call — writing the fixtures' known-correct
`InvoiceData` straight to `extractions` and running the **real, unmodified**
`services/validate.py` over it. Once credit was available the checklist was
re-run fully through the actual `POST /api/documents` → T3 → T5 → T6 pipeline
(model `claude-sonnet-4-5`): the real extraction reproduced the broken
fixture's wrong `total=121560.00`, real T6 flagged the `total_mismatch`, and
the 409 gate → edit / accept-as-is → 200 confirm flow ran on genuine
extractions (the persisted row carries a real metered call:
`cost_usd=0.03531`, `latency_ms=13301`). Full detail — including the real-run
table and the accept-as-is demonstration — in `docs/e2e-review-checklist.md`.

### Review page reached via `?id=`, not a route
No router or Upload/History page exists yet (T2's upload endpoint has no
frontend; those are T8+ scope). `App.tsx` reads `id` from the query string
and renders `ReviewPage` when present, falling back to the existing T1
health-check skeleton otherwise. Revisit once an Upload/History page exists
to link into Review properly.

## Export & history (T8)

### Migration 003 adds `documents.confirmed_at` (nullable)
The export JSON's `meta.confirmed_at` (task spec) needs a real confirm
timestamp, which no existing column carries. `supabase/migrations/003_export.sql`
adds `documents.confirmed_at timestamptz` (nullable, same pattern as
migration 002's `mode`/`pages` — additive, not a PLAN.md contract change).
`DocumentsRepo.mark_confirmed` now stamps it (`datetime.now(UTC)`) in the same
update that sets `status='confirmed'`. The history list also surfaces it
implicitly through `status`, but doesn't display the timestamp itself.

### `settings.REVIEW_THRESHOLD` finally implemented server-side
docs/PLAN.md's contract names `settings.REVIEW_THRESHOLD = 0.85`, but until T8
only the frontend had it (hardcoded in `state/flags.ts`). T8's history list
needs a server-side flags_count per document, so `REVIEW_THRESHOLD = 0.85` was
added to `app/config.py` and consumed by the new `services/flags.py::count_flags`
— a field counts as "needing review" if it has a T6 validation issue at its
path, or confidence is below the threshold (issue always wins), mirroring
`state/flags.ts`'s `severityFor` (duplicated, not shared, per the same
reasoning as `field_path.py`/`fieldPath.ts` in the T7 entry above).

### `GET /api/documents` (T2) enriched with `total`/`flags_count`, not a new endpoint
The task asked the history page to reuse T2's list endpoint for paging, so
`DocumentListItem` gained two optional fields sourced from each document's
*latest* extraction (`None` until one exists): `total` (`Decimal`, the
payload's `total` field) and `flags_count` (int, via `count_flags`).
`ExtractionsRepo.get_latest_for_documents` batches this in one query (`in_`
over the page's document ids, newest-first, first-seen-per-id wins) instead of
N+1 look-ups per row.

### CSV shape: column names, quoting, filenames
The task spec (not docs/PLAN.md, which only names the two formats) fixed the
row/repeat/BOM/CRLF/delimiter rules; the following were judgment calls filling
gaps in that spec:
- **Column names** follow the `InvoiceData`/`Party` field names directly
  (`supplier_name`, `item_unit_price`, ...) rather than inventing a separate
  vocabulary — self-documenting against the domain model.
- **Quoting** uses Python csv's `QUOTE_MINIMAL` (quote only fields containing
  the delimiter, quote char, or a line terminator), not `QUOTE_ALL` — this is
  what Excel/Sheets expect and is exercised by the golden tests on both a
  comma-containing name (`"Кабель HDMI, 2 м"`, from the T5 clean fixture) and a
  synthetic name with an embedded `"` character.
- **Filenames**: `{invoice_number or document_id}.{ext}` per the task, but
  invoice numbers can contain filesystem-unsafe characters (the clean
  fixture's `РФ-2024/0317` has a `/`) — `export_filename_stem` replaces
  `\/:*?"<>|` with `_` rather than dropping them, keeping the number legible.
  `Content-Disposition` carries both an ASCII fallback (`?` for
  non-representable chars) and the real UTF-8 name via `filename*=UTF-8''...`
  (RFC 6266/5987), since invoice numbers/documents are routinely Cyrillic.
- **JSON shape**: `InvoiceExport` subclasses `InvoiceData` and adds one
  trailing `meta` field, rather than nesting the payload under a `payload` key
  — matches the task's "the InvoiceData shape ... plus a small meta block"
  wording literally, and keeps a downloaded file's top level identical to the
  Review UI's `payload` shape.

### 409 gate checks `status == "confirmed"` only, no extraction existence check first
`GET /api/documents/{id}/export` 409s whenever the document isn't `confirmed`
(task spec: "confirmed documents only — 409 for non-confirmed"). A confirmed
document with no extraction row is a data-integrity impossibility in practice
(nothing sets `status='confirmed'` without one), so that path 404s instead
("document has no extraction to export") rather than getting its own status
code — defensive, not a designed API state.

### History polling: two independent effects, no shared `load` helper
The first implementation used one `useCallback`-memoized `load` function
invoked from both a mount/filter/offset effect and a polling `setInterval`.
`eslint-plugin-react-hooks`'s `set-state-in-effect` rule flags any function
that (transitively) calls `setState` when it's invoked directly at an effect
body's top level, even if the actual state update happens asynchronously after
an `await` — it does not flag the same call sitting inside a nested callback
(e.g. `setInterval`'s callback). Rather than suppress the rule, the fetch was
inlined per effect (mirroring `ReviewPage`'s existing `.then/.catch` mount
effect): one effect fetches on mount and on `filter`/`offset` change; a second,
independent effect starts a 5s `setInterval` only while
`hasInFlightDocuments` is true on the current page, and its cleanup
(`clearInterval`) is what "stops polling" once everything settles — not a
runtime check inside the interval callback. The `loading` spinner now only
ever covers the very first fetch (its `useState(true)` initial value); later
fetches (filter changes, pagination, polling) swap the list in place with no
flash back to "Завантаження…".

### Manual E2E: DB layer stubbed, live Supabase migration not applied in this session
This session had no interactive user to approve the Supabase MCP server's
`apply_migration`/`execute_sql` tools (both require an explicit approval this
non-interactive session cannot grant), and the environment does not expose a
direct Postgres connection string (only the REST/service-role key) for a
manual `psql` alternative. **Migration 003 has *not* been applied to the live
Supabase project** — confirmed by querying `documents` columns directly
(`mode`, `pages` present; no `confirmed_at`). Running the real
upload→T3→T5→T6→confirm→export pipeline against that project would 500 on
`mark_confirmed`.

The manual DoD pass instead ran the real FastAPI app (`uv run`) and the real
Vite dev server, with `DocumentsRepo`/`ExtractionsRepo`/`StorageRepo`
dependency-overridden to in-memory fakes seeded with the T5 clean fixture plus
one document per status (queued/processing/review/confirmed/failed) — the same
override technique the pytest suite already uses, just scripted as a
throwaway (uncommitted) server instead of a test. This proves the real T8 HTTP
surface end-to-end (export byte content, headers, history list, browser
download, row-click navigation) without writing to the shared live database.
**Before this ships against the real project, `supabase/migrations/003_export.sql`
still needs to be applied** (Supabase SQL editor, or `apply_migration` once
approved).

## Demo mode (T9)

### Precondition: T8 was not merged; a minimal export endpoint was added, then dropped once T8 landed
The task brief for T9 stated "main must contain merged T8" as a precondition,
and asked to stop and ask if a contract looked wrong. At the start of the T9
session `main` was actually at T7 (376fd3b) — T8 ("Export & history", PLAN.md)
had not been started anywhere (checked all local/remote branches). T9's own
guardrail list requires "export allowed" for the demo user, which presumes an
export endpoint exists. Raised this as a blocking question; the user's
follow-up reiterated "Implement task T9 ONLY," which was read as: proceed on
top of current `main`, and implement only the slice of T8 that T9's contract
actually depends on — a minimal `GET /api/documents/{id}/export?format=json|csv`
wired into `app/routes/documents.py` — rather than the full T8 scope (history
list page, golden-file CSV regression tests, etc.).

**Follow-up**, once the real T8 PR merged to `main` (full contract: `meta`
block with `confirmed_at`/`schema_version`, BOM+CRLF CSV, 409-unless-confirmed
gating, migration 003, history list page): this branch was rebased onto it,
T8's `app/services/export.py` / `app/routes/export.py` / `tests/test_export.py`
were kept verbatim, and T9's own minimal export slice (the version described
immediately above) was deleted outright rather than reconciled — T8 is now the
one and only export implementation. What carried over: the demo rate-limit
guardrail was re-applied to T8's `export_document` route (`request` param +
`enforce_demo_document_rate_limit` call, same pattern as the other
demo-touching routes), and the `/demo` page's cards gained JSON/CSV download
links for confirmed documents, reusing T8's `exportUrl()` helper exactly like
the History page does. `docs/PLAN.md`'s T8 row is now marked done (T8's own
PR), and T9's row no longer references the superseded minimal-export note.

### Demo documents are ordinary rows, scoped by a second fixed user id
Auth doesn't exist yet (see the T2 "Placeholder user_id" decision above) — the
whole app already runs under one fixed `PLACEHOLDER_USER_ID`. Demo documents
live in the exact same `documents`/`extractions`/Storage bucket, just under a
second fixed constant, `app.config.DEMO_USER_ID`
(`00000000-0000-0000-0000-0000000000de`), so they are trivially distinguishable
from "real" placeholder-user documents without any schema change. The 5 demo
documents themselves additionally get fixed, hardcoded ids
(`app/demo_data.py`, `...d1`..`...d5`) so seeding can recognize "already
seeded" by primary key rather than by any fuzzier matching.

### No DB migration needed for T9
Every piece of T9 fits the existing `documents`/`extractions`/`review_log`
schema: `DEMO_USER_ID` is just another `uuid` value for the existing
`user_id` column, and the 5 demo documents' card metadata (filename,
difficulty label, title, description) is static application data
(`app/demo_data.py`), not something that needs its own table. No SQL is
included in this change; no migration to pause for.

### Upload guardrail: a dedicated always-409 endpoint, not a check inside POST /api/documents
There is no session/auth concept yet, so a request to the real
`POST /api/documents` has no way to identify itself as "the demo user" — every
upload is already the one `PLACEHOLDER_USER_ID`. Rather than inventing a fake
identity signal, "demo user cannot upload" is implemented as a separate
`POST /api/demo/documents` (`app/routes/demo.py`) that always returns `409`
with a friendly Ukrainian message. The `/demo` page itself has no upload
dropzone at all; this endpoint exists so a direct API call against the demo
namespace gets a clear, on-brand rejection instead of a bare 404, and so the
guardrail is something a test can actually assert against.

### Confirm/PATCH: shared global state + snapshot-based reset, not per-session copies
The task allowed either "per-session copy" or "reset" as the simplest safe
option. Per-session copies would need a session concept (cookies, forked rows
per visitor) that doesn't exist anywhere else in the app; building one just
for the demo would be the more complex option for comparatively little
benefit on a portfolio demo. Instead, demo documents are shared, global state
(any visitor's edits are visible to the next visitor until a reset), and
`scripts/seed_demo.py --reset` restores every seeded demo document to its
pristine, just-extracted state:

- The first real seed run persists a snapshot of the freshly-extracted
  `extractions` row (`payload`, `field_confidences`, `validation_issues`) to
  `scripts/demo_snapshots/<key>.json`, committed to the repo.
- `--reset` reads that snapshot and writes it back via the extraction's
  existing id (`ExtractionsRepo.update_after_edit`) plus
  `DocumentsRepo.set_status(..., "review")` (undoing any demo `confirm`). No
  Storage or Anthropic call happens on reset — it's two small Postgres
  updates per document, cheap enough to run nightly via cron ("nightly-safe
  idempotency").
- This deliberately never re-bills the LLM after the first seed. The task
  brief's "extraction cost is acceptable" reads as a one-time cost to
  authorize, not a recurring one; a reset that re-ran the real pipeline every
  night would turn a one-off decision into an open-ended recurring spend.

### review_log: demo edits are excluded, not flagged `is_demo`
The task offered a choice: flag demo review_log rows with `is_demo`, or
exclude them. Excluding was chosen — `review_log` is described in `docs/TZ.md`
§6 as "джерело даних для майбутнього поліпшення промптів" (training/analysis
signal for future prompt work); public, unauthenticated demo edits are noise
against that purpose and don't need to be retained at all, and excluding them
needs zero schema change (an `is_demo` flag would need a migration on
`review_log`, which T9 doesn't otherwise require — see above). PATCH still
applies the edit itself exactly as for a real document (payload update,
confidence bump to 1.0, matching validation issue cleared) — only the
`review_log.create` call is skipped when the extraction's `document_id` is
one of the 5 fixed demo ids (`app/routes/extractions.py`).

### Rate limiting: in-memory per-IP sliding window, scoped to demo traffic only
`app/services/rate_limit.py` is a pure, dependency-free sliding-window counter
(no Redis/new infra for a portfolio demo); `app/services/demo_guard.py` wires
it into routes. It is applied to: every `/api/demo/*` endpoint, and — via an
explicit `is_demo_document_id` check inside `routes/documents.py` /
`routes/extractions.py` / T8's `routes/export.py` — any
`GET`/`PATCH`/`POST confirm`/`export` request whose target is one of the 5
fixed demo documents. Real (non-demo) traffic
through the exact same route handlers is never rate-limited; the check is a
no-op for any other document id. The limit (30 requests/60s per IP,
`app.config.DEMO_RATE_LIMIT_*`) is conservative on purpose and resets on
process restart — acceptable for a demo, called out here in case it causes
confusion after a deploy.

### Fixture generation extends, rather than imports, the T3/T5 generators
`scripts/seed_demo.py` reuses `tests/_pdfgen.build_image_pdf` (T3's
dependency-free PDF wrapper, for the image-PDF "good scan" fixture) and the
fpdf2 + DejaVuSans Cyrillic-rendering approach from
`tests/fixtures/generate_invoice_fixtures.py` (for the two born-digital PDFs
and, extended to a raw `PIL.Image` before JPEG-encoding, for the scan/photo
renders) — but the invoice content itself (5 distinct fictional companies,
line items, totals) is new to this script, not the literal T3/T5 fixtures,
since the demo needs 5 *different* curated documents rather than reusing the
tests' 2. `_build_invoice()` computes line/subtotal/VAT/total arithmetic from
`Decimal` inputs so every non-broken document is internally consistent
end-to-end (T6 raises zero validation issues on it); the `arithmetic_error`
document uses the same builder with an explicit `total_override` to trip only
`total_mismatch`, mirroring T5's `BROKEN_TOTAL_INVOICE` fixture. Tax ids used
are checksum-valid ЄДРПОУ/ІПН numbers (verified against
`services/validate.py`'s actual checksum algorithms before picking them) so
the 4 non-broken documents don't spuriously flag `bad_tax_id`.

### `seed()` takes injectable repos so idempotency is unit-testable without real credentials
`scripts/seed_demo.py`'s `seed(*, reset, documents=None, extractions=None,
storage=None)` builds the real Supabase-backed repos only when a repo isn't
passed in. `tests/test_seed_demo.py` injects `MagicMock`s (plus a fake
`ExtractionService`/`preprocess`) to exercise the actual decision logic — skip
an already-seeded document, seed a missing one exactly once, restore from a
snapshot on `--reset` — without ever touching the real Anthropic API or
Supabase (per CLAUDE.md's testing conventions). Real runs (`uv run python
scripts/seed_demo.py`) get the default real-client repos exactly as before.

### `mypy_path = ["scripts"]`
`tests/test_seed_demo.py` imports `scripts/seed_demo.py` directly (mirroring
how `tests/fixtures/generate_fixtures.py` imports `tests/_pdfgen.py`).
`[tool.mypy] files` only covers `app`/`tests`, so mypy couldn't resolve the
`import seed_demo` without also being told where to look; `mypy_path =
["scripts"]` adds it as a search path (not as a file to type-check on its
own), and `scripts/seed_demo.py` happens to already pass strict mode as a
result of being resolved.
