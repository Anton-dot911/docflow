# T7 Review UI — Manual E2E Checklist

Run against the real backend (`uv run fastapi run app/main.py`, real Supabase)
and the real frontend (`pnpm dev`). Fixtures: `backend/tests/fixtures/
invoice_broken_total.pdf` (T6 arithmetic issue on `total`, plus a low-confidence
`items[0].amount`) and `backend/tests/fixtures/invoice_text.pdf` (the clean T5
fixture — internally consistent, zero T6 issues).

## Known blocker hit during this run: no Anthropic API credit

The `ANTHROPIC_API_KEY` available in this session
(`$METER_ANTHROPIC_API_KEY`) has **no credit balance** — every real T5
extraction call fails immediately with `400 invalid_request_error: Your
credit balance is too low`. This blocks running the actual T5 LLM call, so
step 2 below substitutes it: the exact `InvoiceData` payload each fixture was
designed to produce (from `generate_invoice_fixtures.py`'s
`EXPECTED_INVOICE_TEXT` / `BROKEN_TOTAL_INVOICE`) is written directly to the
`extractions` table, then the **real** `services/validate.py` (`validate_invoice`
/ `zero_out_confidences`, unmodified, no mocking) computes the issues and
confidences, and the **real** repos persist it against the **real** Supabase
project. Every step from T6 onward, and all of T7 (routes + UI), runs for
real and unmodified. This is documented here rather than silently worked
around — a real key with credit would let step 2 run through the actual
`POST /api/documents` → T3 preprocess → T5 extract pipeline instead.

## Steps

1. **Upload both fixtures.**
   `POST /api/documents` with `invoice_broken_total.pdf` and
   `invoice_text.pdf` → both return `{status: "queued", document_id}`.
   **Result: PASS.**
   ```
   [{"filename":"invoice_broken_total.pdf","status":"queued","document_id":"...","reason":null},
    {"filename":"invoice_text.pdf","status":"queued","document_id":"...","reason":null}]
   ```

2. **Reach `review` with a real T6-validated extraction.**
   Because of the credit blocker above, extraction was seeded (payload exact,
   validator real) instead of waiting on the real LLM call. `GET
   /api/documents/{id}` for the broken-total doc:
   **Result: PASS** — `status: "review"`, `mode: "text"`, one T6 issue:
   ```
   {"path":"total","code":"total_mismatch",
    "message":"subtotal 101150.00 + vat 20230.00 = 121380.00, document says 121560.00"}
   ```
   The clean fixture's `GET` shows `validation_issues: []` and every field
   confidence ≥ 0.85.

3. **Open the red field in the UI — issue message shown verbatim.**
   Desktop (1280×900), light theme: clicking "До сплати" (total) expands the
   field. The reason text rendered in `.rv-field__reason` is:
   `subtotal 101150.00 + vat 20230.00 = 121380.00, document says 121560.00`
   — byte-for-byte the API's message, no re-wording. The pre-filled input
   shows the current (wrong) value `121560.00`, ready to correct.
   **Result: PASS** (see `Screenshot: red field open` below).

4. **Confirm is blocked while unresolved fields remain.**
   With the document freshly loaded, `.rv-header__actions`'s "Підтвердити
   документ" button is disabled and clicking it (or `POST
   /api/documents/{id}/confirm` directly) returns `409`:
   ```
   {"detail":{"message":"document has unresolved fields with confidence 0",
               "unresolved_fields":["total"]}}
   ```
   **Result: PASS.**

5. **Edit the red field → saved, issue clears, confidence → 1.0.**
   Typing `121380.00` and clicking "Зберегти виправлення" PATCHes
   `/api/extractions/{id}` with `{field_path:"total", new_value:"121380.00"}`.
   Response: `payload.total = "121380.00"`, `total` confidence `1.0`,
   `validation_issues` no longer contains `total`. The field turns green in
   the UI immediately (optimistic) and stays green after the real round-trip.
   **Result: PASS.**

6. **Accept-as-is an amber field.**
   `items[0].amount` (confidence 0.62, no T6 issue) is opened and
   "Підтвердити ₴ 97 500,00" is clicked — PATCH with the *same* value
   (`97500.00` → `97500.00`). Confidence goes to `1.0`; this is the
   "Прийняти як є" mechanic exercised on an amber field via its one-button
   form. **Result: PASS.**

7. **All-green → Confirm becomes enabled → succeeds.**
   Once every field is green, the counter strip switches to "Усі поля
   підтверджено — документ готовий ✓", both Confirm buttons (desktop header
   + mobile bottom bar) become enabled, and clicking Confirm calls `POST
   /confirm` → `200 {"status":"confirmed"}`. The badge switches to
   "підтверджено" and a toast ("Документ підтверджено ✓") appears.
   **Result: PASS** (confirmed via API in this run; see the toast/badge
   screenshots from an earlier equivalent run in the session transcript —
   badge/strip text captured live: `badge: "підтверджено"`, `strip: "Усі поля
   підтверджено — документ готовий ✓"`).

8. **Clean fixture: one-click confirm, no edits.**
   `GET` shows zero issues and all confidences ≥ 0.85 → the UI's counter
   strip already reads "Усі поля підтверджено" and Confirm is enabled on
   first load. Clicking it once → `200 {"status":"confirmed"}`, no PATCH
   calls needed. **Result: PASS.**

9. **Mobile layout (390×844) and dark theme.**
   At the mobile breakpoint the header's inline actions hide and the sticky
   bottom bar (`Наступне поле` / `Підтвердити документ`) appears instead,
   vertically stacked above document → fields, matching UI_SPEC §2.
   Switching the theme pill to "Темна" swaps every token (surface, ink,
   accent gradient, amber/red/green backgrounds) while the document pane
   stays light "scan paper" in both themes. **Result: PASS** (visually
   confirmed via screenshots taken during this session).

10. **`review_log` rows are written for both PATCHes.**
    Queried directly from Supabase after the run above (`extraction_id
    4244d791-fd86-4f33-896c-6a7d7150006c`):
    ```json
    [
      {
        "id": 8,
        "extraction_id": "4244d791-fd86-4f33-896c-6a7d7150006c",
        "field_path": "total",
        "old_value": "121560.00",
        "new_value": "121380.00",
        "created_at": "2026-07-11T00:00:17.485145+00:00"
      },
      {
        "id": 9,
        "extraction_id": "4244d791-fd86-4f33-896c-6a7d7150006c",
        "field_path": "items[0].amount",
        "old_value": "97500.00",
        "new_value": "97500.00",
        "created_at": "2026-07-11T00:00:24.702304+00:00"
      }
    ]
    ```
    Row 8 is the edit (old ≠ new); row 9 is the accept-as-is (old == new) —
    both mechanisms write a row, as designed. **Result: PASS.**

## Known limitation surfaced by this run (not an app bug)

The document pane's pdf.js rendering could not be **visually** confirmed in
this sandbox's headless Chromium (bundled with Playwright, version 141):
`page.render()` throws `TypeError: this[#methodPromises]
.getOrInsertComputed is not a function`. `Map.prototype.getOrInsertComputed`
is a very recent V8 builtin that pdf.js 5.x/6.x now uses internally
(confirmed present in both the previous pin and latest); Chromium 141 predates
it. This was root-caused, not just observed:

- The signed URL, fetch, `GlobalWorkerOptions.workerSrc`, and the whole
  effect/lifecycle wiring in `DocumentPane` are correct — traced with
  temporary instrumentation down to the exact `page.render()` call throwing.
- Downgrading `pdfjs-dist` to 5.7.284 did not help (same builtin required),
  confirming this is a browser-version floor, not a bad dependency pin —
  reverted to latest (6.1.200).
- The component's own error path works correctly: on this failure it shows
  `role="alert"` text with the real error message (confirmed present in the
  DOM), it's just scrolled below the (empty) canvas within the pane's
  internal `max-height: 70vh` scroll area, so it wasn't visible in a
  full-page screenshot without scrolling that inner region.
- `findSnippetItemIndices` (the text-layer search matching logic) is unit
  tested directly (`tests/textSearch.test.ts`) independent of pdf.js/canvas.

Any current desktop browser (Chrome/Edge/Firefox, auto-updated) will have
this V8 feature and should render normally — this is a testing-sandbox
ceiling, not a shipped defect. Flagging it here rather than silently
smoothing it over.

## Environment notes for reproducing this run

- Backend: `ANTHROPIC_API_KEY=$METER_ANTHROPIC_API_KEY LLM_MODEL=claude-sonnet-5
  uv run fastapi run app/main.py --port 8000` (real Supabase creds already in env).
- Frontend: `pnpm dev --port 5173` (proxies `/api` to the backend).
- All documents/storage objects created during this checklist run were
  deleted afterward (`documents`, extraction rows cascade, storage objects) —
  the JSON/screenshots above are the durable record.

## Finishing pass (2026-07-11) — two mobile fixes + re-run

Two issues from a manual review pass were fixed and the checklist re-run
against the real backend.

**Fix 1 — dark-theme filename invisible on the scan card.** The generic
`.rv-app h2` colour rule (specificity 0,1,1) was overriding
`.rv-paper__title` (0,1,0), forcing the filename to the theme `--ink`
(near-white in dark) on the always-white scan paper. The scan-paper inner
text selectors are now compound (`.rv-paper .rv-paper__title` etc., 0,2,0) so
the scan-paper ink/text tokens win. Verified in dark mode: title computed
colour `rgb(17, 24, 39)` (= scan-paper ink #111827), kicker/source
`rgb(51, 65, 85)` (= scan-paper text #334155) — all visible on white paper;
light mode unchanged (`rgb(17, 24, 39)`).

**Fix 2 — mobile action bar overlapping field cards.** The bottom bar was
`position: sticky` with only 48px of content bottom-padding, so cards
scrolled under it. It is now `position: fixed` (centred, safe-area padded,
gradient scrim) with a mobile-only `padding-bottom: 128px` reserve on the
content (bar is `display:none` ≥880px, so desktop keeps its 48px and the
two-pane header actions). Verified at 390px scrolled fully down:
`lastCardClearsBar: true`, `cardsCoveredByBar: 0`, bar pinned at
viewport bottom (752–844) below the last content (bottom 706). Desktop
regression check: bar `display:none`, wrap `padding-bottom: 48px`, header
actions `flex`.

**Re-run results (all against the real backend + Supabase, extraction seeded
per the no-credit note above):**

| Step | Result |
|---|---|
| 1. upload broken + clean | both `queued` with document_ids |
| 2. GET broken → review | `status: review`, `mode: text`, `pages: 1`; one issue: `total_mismatch — subtotal 101150.00 + vat 20230.00 = 121380.00, document says 121560.00`; `total` confidence `0.0` |
| 3. GET file | `expires_in: 3600`, signed URL on `*.supabase.co` with `token=` |
| 4. confirm before fix | **409** `{"detail":{"message":"document has unresolved fields with confidence 0","unresolved_fields":["total"]}}` |
| 5. PATCH `total` → `121380.00` | payload `total: "121380.00"`, confidence `1.0`, `validation_issues: []` |
| 6. PATCH `items[0].amount` (accept as-is) | confidence `1.0`; no fields `< 0.85` remain |
| 7. confirm after resolve | **200** `{"status":"confirmed"}`; final row `status: confirmed`, `payload.total: 121380.00` |
| 8. clean fixture one-click | zero issues, all confidences ≥ 0.85 → confirm **200** → `confirmed` (its transient `failed` before confirm was the background worker's `mark_failed` racing the seed — the no-credit seeding artifact, not the confirm gate) |
| 10. review_log rows | two rows written — see below |

```json
[
  {"id": 10, "extraction_id": "87b42549-f243-4ce2-8a8f-944160636f89",
   "field_path": "total", "old_value": "121560.00", "new_value": "121380.00",
   "created_at": "2026-07-11T05:23:12.176267+00:00"},
  {"id": 11, "extraction_id": "87b42549-f243-4ce2-8a8f-944160636f89",
   "field_path": "items[0].amount", "old_value": "97500.00", "new_value": "97500.00",
   "created_at": "2026-07-11T05:23:12.876435+00:00"}
]
```

Row 10 is the edit (old ≠ new); row 11 is the accept-as-is (old == new) —
both write a row. Test docs deleted after the run.
