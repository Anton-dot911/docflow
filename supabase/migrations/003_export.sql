-- 003_export.sql — T8 export & history: record when a document was confirmed.
-- Nullable because rows are not `confirmed` for most of their life; written by
-- the same update that sets status='confirmed' (see DocumentsRepo.mark_confirmed).
-- Export's JSON `meta.confirmed_at` (docs/PLAN.md export route) and the history
-- list both read it.

alter table documents
  add column confirmed_at timestamptz;
