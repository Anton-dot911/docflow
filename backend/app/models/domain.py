"""Domain models — the extraction/validation contracts (source of truth).

These are implemented verbatim from the Contracts block in docs/PLAN.md and are
the single source of truth for the pipeline's structured data. T5 uses
`InvoiceData`, `Party`, `LineItem`, `FieldConfidence` and `ExtractionResult`;
`Classification` and `ValidationIssue` are defined here too so the contract lives
in one place, and are exercised by their own tasks (T10 classifier, T6
validation). Money/quantity are `Decimal` and dates are `date` per CLAUDE.md
rule 7; JSON serialization renders them as numeric strings / ISO 8601.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class DocType(str, Enum):  # noqa: UP042  # verbatim from docs/PLAN.md contract
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
    tax_id: str | None  # ЄДРПОУ/ІПН
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
    path: str  # dot-path, e.g. "items[2].amount"
    confidence: float = Field(ge=0, le=1)
    source_snippet: str | None  # short quote from document


class ExtractionResult(BaseModel):
    doc_type: DocType
    payload: InvoiceData  # union with ActData when added (T10)
    confidences: list[FieldConfidence]


class ValidationIssue(BaseModel):
    path: str
    code: str  # "arithmetic_mismatch" | "bad_date" | "bad_tax_id" | ...
    message: str
