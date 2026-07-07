-- 001_init.sql — DocFlow core schema (documents, extractions, review_log + RLS)
-- Table DDL is verbatim from the contract in docs/PLAN.md. Does NOT touch the
-- shared `llm_calls` table (owned by Meter).

create type doc_status as enum ('queued','processing','review','confirmed','failed');

create table documents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  filename text not null,
  storage_path text not null,
  doc_type text,
  status doc_status not null default 'queued',
  error text,
  created_at timestamptz not null default now()
);

create table extractions (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references documents(id) on delete cascade,
  schema_version int not null default 1,
  payload jsonb not null,
  field_confidences jsonb not null,
  validation_issues jsonb not null default '[]',
  model text not null,
  tokens_in int, tokens_out int,
  cost_usd numeric(10,5), latency_ms int,
  created_at timestamptz not null default now()
);

create table review_log (
  id bigint generated always as identity primary key,
  extraction_id uuid not null references extractions(id) on delete cascade,
  field_path text not null,
  old_value jsonb, new_value jsonb,
  created_at timestamptz not null default now()
);

-- RLS: enable on all tables, policy user_id = auth.uid() (documents),
-- via join for children.
alter table documents enable row level security;
alter table extractions enable row level security;
alter table review_log enable row level security;

-- Indexes supporting the RLS join predicates below.
create index extractions_document_id_idx on extractions (document_id);
create index review_log_extraction_id_idx on review_log (extraction_id);

-- documents: a row belongs to the authenticated user directly.
create policy documents_owner on documents
  for all
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- extractions: ownership derived by join to the parent document.
create policy extractions_via_document on extractions
  for all
  using (
    exists (
      select 1 from documents d
      where d.id = extractions.document_id and d.user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from documents d
      where d.id = extractions.document_id and d.user_id = auth.uid()
    )
  );

-- review_log: ownership derived by join through extractions to documents.
create policy review_log_via_extraction on review_log
  for all
  using (
    exists (
      select 1
      from extractions e
      join documents d on d.id = e.document_id
      where e.id = review_log.extraction_id and d.user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1
      from extractions e
      join documents d on d.id = e.document_id
      where e.id = review_log.extraction_id and d.user_id = auth.uid()
    )
  );
