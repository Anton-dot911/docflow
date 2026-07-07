# PLAN.md — DocFlow Implementation Plan

Each task = one coding-agent session (2–4h scope). Give the agent ONE task, with its DoD. Do not proceed while the previous task's DoD is red.

---

## Contracts (source of truth — implement verbatim)

### Domain models (backend/app/models/)

```python
from decimal import Decimal
from datetime import date
from enum import Enum
from pydantic import BaseModel, Field

class DocType(str, Enum):
    invoice = "invoice"
    act = "act"
    other = "other"

class Classification(BaseModel):
    doc_type: DocType
    confidence: float = Field(ge=0, le=1)

class LineItem(BaseModel):
    name: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None

class Party(BaseModel):
    name: str | None
    tax_id: str | None          # ЄДРПОУ/ІПН
    address: str | None

class InvoiceData(BaseModel):
    supplier: Party
    buyer: Party
    invoice_number: str | None
    invoice_date: date | None
    items: list[LineItem]
    subtotal: Decimal | None
    vat_amount: Decimal | None
    total: Decimal | None

class FieldConfidence(BaseModel):
    path: str                    # dot-path, e.g. "items[2].amount"
    confidence: float = Field(ge=0, le=1)
    source_snippet: str | None   # short quote from document

class ExtractionResult(BaseModel):
    doc_type: DocType
    payload: InvoiceData         # union with ActData when added (T10)
    confidences: list[FieldConfidence]

class ValidationIssue(BaseModel):
    path: str
    code: str                    # "arithmetic_mismatch" | "bad_date" | "bad_tax_id" | ...
    message: str
```

### DDL (supabase/migrations/001_init.sql)

```sql
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
-- RLS: enable on all tables, policy user_id = auth.uid() (documents), via join for children.
```

### API (FastAPI routes)

```
POST /api/documents            multipart upload (1..10 files) -> [{document_id, status}]
GET  /api/documents            list for user (status, paging)
GET  /api/documents/{id}       document + latest extraction + issues
PATCH /api/extractions/{id}    body: {field_path, new_value} -> updates payload, writes review_log
POST /api/documents/{id}/confirm  -> status=confirmed
GET  /api/documents/{id}/export?format=json|csv
GET  /api/demo/samples         list of 5 preloaded demo docs (no auth)
```

Confidence threshold for review highlight: `settings.REVIEW_THRESHOLD = 0.85`.

---

## Tasks

**T1. Scaffold & skeleton.**
Run `antlab-create` (py-service + frontend), wire Supabase project, apply migration 001, health endpoint, CI green.
DoD: `pytest`, `ruff`, `mypy`, `pnpm test` all pass in CI; `/health` returns commit SHA.

**T2. Ingestion.**
Upload endpoint: validate type/size (pdf/jpg/png, ≤10MB, ≤10 files), store to Supabase Storage, create `documents` rows, background task stub sets status processing→review.
DoD: tests for size/type rejection, happy path; files visible in Storage.

**T3. Preprocessing.**
`services/preprocess.py`: for PDF extract text via pypdfium2; compute text-coverage ratio; below 0.3 → rasterize pages to PNG (max 1568px long side). Output: `PreprocessedDoc {mode: "text"|"vision", text?: str, images?: list[bytes], pages: int}`.
DoD: unit tests on 3 fixture files (text PDF, scanned PDF, JPG).

**T4. LLM layer.**
`app/llm/client.py`: metered Anthropic wrapper (Meter integration), `call_structured(model, prompt_file, input, output_model: type[BaseModel])` implementing tool-use schema from Pydantic, validation, single retry with error feedback, timeout, backoff on 429/529.
DoD: unit tests with mocked SDK: happy path, invalid-then-valid retry, retry exhausted raises.

**T5. Extraction (invoice).**
`prompts/extract_invoice.v1.md` (2 few-shot cases; null-not-fabricate instruction), `services/extract.py` producing `ExtractionResult`, persisted to `extractions` with cost/latency.
DoD: `@pytest.mark.llm` test extracts fixture invoice with ≥80% correct fields (smoke, not eval).

**T6. Validation.**
`services/validate.py` pure functions: line arithmetic (qty*price=amount, sum=subtotal, subtotal+vat=total, tolerance 0.01), date sanity, EDRPOU checksum. Issues zero-out matching field confidences.
DoD: exhaustive unit tests incl. tolerance edges and checksum vectors.

**T7. Review UI.**
Two-pane page: left document render (pdf.js / image), right schema-driven form; fields with confidence < 0.85 or validation issue highlighted; field click ⇄ snippet highlight; PATCH per edit; Confirm button.
DoD: vitest component tests for highlight logic; manual e2e checklist in PR.

**T8. Export & history.**
JSON/CSV export (CSV: one row per line item, header fields repeated), history list page with statuses.
DoD: golden-file tests for CSV shape.

**T9. Demo mode.**
Seed script uploads 5 curated docs under demo user; `/demo` page, no auth; rate-limited.
DoD: fresh deploy + seed = working demo in ≤ 2 commands.

**T10. Classifier + Act type.**
`prompts/classify.v1.md`, `Classification` call on page 1; `ActData` model + `extract_act.v1.md`; router by doc_type.
DoD: llm smoke tests for both types; unknown docs → `other` + status review.

**T11. Evals.**
`make eval`: loads Goldsmith JSONL from `data/golden/`, runs pipeline, computes field accuracy (exact for numbers/dates, fuzzy≥0.9 for names), schema validity rate, review-flag rate, false-confidence rate; prints table by tag; writes `eval_runs/<ts>.json`; compares to previous run, exit 1 on regression > 2pp.
DoD: runs on 40-doc dataset; metrics table generated.

**T12. Hardening & release.**
Prompt iteration to targets (accuracy ≥95%, validity ≥99%); README(EN) with metrics + architecture diagram + design decisions; deploy backend (Railway/Fly) + frontend (Netlify); demo video.
DoD: ТЗ §10 checklist fully green.

---

## Session prompt template
> Read CLAUDE.md and docs/PLAN.md. Implement task T<N> only. Follow the contracts verbatim. Stop and ask if a contract seems wrong rather than changing it silently. Finish with: tests passing, short summary of decisions made.
