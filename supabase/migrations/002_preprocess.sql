-- 002_preprocess.sql — T3 preprocessing: persist how a document was preprocessed.
-- Adds two nullable columns to `documents`, written when the background worker
-- finishes preprocessing (mode + page count) and advances the row to `review`.
-- Nullable because rows are `queued`/`processing`/`failed` before preprocessing
-- completes. See docs/PLAN.md T3 and docs/decisions.md.

alter table documents
  add column mode text check (mode in ('text', 'vision')),
  add column pages int check (pages >= 0);
