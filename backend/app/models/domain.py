"""Domain models — the extraction/validation contracts (source of truth).

These are implemented verbatim from the Contracts block in docs/PLAN.md and are
the single source of truth for the pipeline's structured data. T5 uses
`InvoiceData`, `Party`, `LineItem`, `FieldConfidence` and `ExtractionResult`;
`Classification` and `ValidationIssue` are defined here too so the contract lives
in one place, and are exercised by their own tasks (T10 classifier, T6
validation). Money/quantity are `Decimal` and dates are `date` per CLAUDE.md
rule 7; JSON serialization renders them as numeric strings / ISO 8601.

T10 adds `ActData` (акт виконаних робіт), mirroring `InvoiceData` field-for-
field: `contractor`/`customer` in place of `supplier`/`buyer` (виконавець /
замовник, the natural Ukrainian terms for who performs vs. who receives the
work), `act_number`/`act_date` in place of `invoice_number`/`invoice_date`,
`services` in place of `items` (still a list of the same `LineItem` shape).
`ExtractionResult.payload` becomes the `InvoiceData | ActData` union the
docstring below anticipated; Pydantic's smart-union validation picks the right
one from the required field sets (`items` vs `services`, `supplier`/`buyer` vs
`contractor`/`customer`), so no extra discriminator field is needed.
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


class ActData(BaseModel):
    """Акт виконаних робіт (act of completed works/services) — T10."""

    contractor: Party  # виконавець — mirrors InvoiceData.supplier
    customer: Party  # замовник — mirrors InvoiceData.buyer
    act_number: str | None
    act_date: date | None
    services: list[LineItem]
    subtotal: Decimal | None
    vat_amount: Decimal | None
    total: Decimal | None


class FieldConfidence(BaseModel):
    path: str  # dot-path, e.g. "items[2].amount"
    confidence: float = Field(ge=0, le=1)
    source_snippet: str | None  # short quote from document


class ExtractionResult(BaseModel):
    doc_type: DocType
    payload: InvoiceData | ActData
    confidences: list[FieldConfidence]


class ValidationIssue(BaseModel):
    path: str
    code: str  # "arithmetic_mismatch" | "bad_date" | "bad_tax_id" | ...
    message: str
