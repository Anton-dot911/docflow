"""Deterministic validation for extracted invoice/act data (T6, generalized T10).

Pure functions only: no I/O, no LLM calls, no DB access (CLAUDE.md rule 1/3 and
the T6 task spec). Operates on the `InvoiceData`/`ActData` / `FieldConfidence`
contracts from `app.models.domain` and produces `ValidationIssue`s that the
caller (`services/extract.py`) persists and uses to zero out matching field
confidences so the Review UI flags them.

T10 adds `ActData` alongside `InvoiceData`. Rather than forking a parallel
`validate_act.py`, the checks below are generalized over a small
`_DocumentView` adapter that reads either payload's line items, its own-date
field and its two parties under their type-specific names/paths
(`items`/`invoice_date`/`supplier`+`buyer` vs `services`/`act_date`/
`contractor`+`customer`) — `subtotal`/`vat_amount`/`total` are named
identically on both models, so those checks need no adapting at all.
`validate_invoice` is kept as a thin, name-preserving wrapper around the
generalized `validate_document` so existing callers/tests are unaffected.

A `None` field is never itself a validation error — it is already a
low-confidence signal from extraction. Every check below only fires when all
the values it needs are present.

Codes (fixed enum, verbatim from the task spec):
  line_arithmetic_mismatch, subtotal_mismatch, total_mismatch,
  bad_date, future_date, stale_date, bad_tax_id
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.config import MAX_INVOICE_AGE_YEARS, VALIDATION_AMOUNT_TOLERANCE
from app.models.domain import (
    ActData,
    FieldConfidence,
    InvoiceData,
    LineItem,
    Party,
    ValidationIssue,
)

_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class _DocumentView:
    """Adapts an `InvoiceData`/`ActData` payload to the shape every check
    below needs, translating each type's own field names into the checks'
    generic terms and the dot-paths its type actually uses."""

    payload: InvoiceData | ActData
    items: list[LineItem]
    items_path: str
    own_date: date | None
    date_path: str
    parties: tuple[tuple[Party, str], ...]


def _view(payload: InvoiceData | ActData) -> _DocumentView:
    if isinstance(payload, InvoiceData):
        return _DocumentView(
            payload=payload,
            items=payload.items,
            items_path="items",
            own_date=payload.invoice_date,
            date_path="invoice_date",
            parties=((payload.supplier, "supplier.tax_id"), (payload.buyer, "buyer.tax_id")),
        )
    return _DocumentView(
        payload=payload,
        items=payload.services,
        items_path="services",
        own_date=payload.act_date,
        date_path="act_date",
        parties=((payload.contractor, "contractor.tax_id"), (payload.customer, "customer.tax_id")),
    )


def _money(value: Decimal) -> str:
    """Render a Decimal the way messages quote it: 2 decimal places."""
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= VALIDATION_AMOUNT_TOLERANCE


def _check_line_arithmetic(items: list[LineItem], *, path_prefix: str) -> list[ValidationIssue]:
    """qty * unit_price == amount per line. Skips a line if any value is null."""
    issues: list[ValidationIssue] = []
    for i, item in enumerate(items):
        if item.quantity is None or item.unit_price is None or item.amount is None:
            continue
        expected = item.quantity * item.unit_price
        if not _close(expected, item.amount):
            issues.append(
                ValidationIssue(
                    path=f"{path_prefix}[{i}].amount",
                    code="line_arithmetic_mismatch",
                    message=(
                        f"line {i + 1}: {item.quantity} * {item.unit_price} = "
                        f"{_money(expected)}, document says {_money(item.amount)}"
                    ),
                )
            )
    return issues


def _check_subtotal(view: _DocumentView) -> list[ValidationIssue]:
    """sum(line amounts) == subtotal. Skipped unless subtotal and every line
    amount are present — an incomplete line means the sum is not meaningful,
    and that line's own null is already a low-confidence signal on its own."""
    payload = view.payload
    if payload.subtotal is None or not view.items:
        return []
    amounts = [item.amount for item in view.items]
    if any(amount is None for amount in amounts):
        return []
    total = sum((amount for amount in amounts if amount is not None), Decimal("0"))
    if _close(total, payload.subtotal):
        return []
    return [
        ValidationIssue(
            path="subtotal",
            code="subtotal_mismatch",
            message=f"positions total {_money(total)}, document says {_money(payload.subtotal)}",
        )
    ]


def _check_total(payload: InvoiceData | ActData) -> list[ValidationIssue]:
    """subtotal + vat_amount == total. Skipped unless all three are present.

    `subtotal`/`vat_amount`/`total` are named identically on `InvoiceData` and
    `ActData`, so this check needs no `_DocumentView` indirection."""
    if payload.subtotal is None or payload.vat_amount is None or payload.total is None:
        return []
    expected = payload.subtotal + payload.vat_amount
    if _close(expected, payload.total):
        return []
    return [
        ValidationIssue(
            path="total",
            code="total_mismatch",
            message=(
                f"subtotal {_money(payload.subtotal)} + vat {_money(payload.vat_amount)} = "
                f"{_money(expected)}, document says {_money(payload.total)}"
            ),
        )
    ]


def _check_date(view: _DocumentView, *, today: date) -> list[ValidationIssue]:
    """The document's own date is a real date, not in the future (today
    allowed), not older than MAX_INVOICE_AGE_YEARS. `bad_date` is defensive:
    Pydantic already guarantees a real `date` for any validated payload, so it
    only fires if a caller bypassed validation (e.g. `model_construct`)."""
    own_date, path = view.own_date, view.date_path
    if own_date is None:
        return []
    if not isinstance(own_date, date):
        return [
            ValidationIssue(
                path=path,
                code="bad_date",
                message=f"{path} is not a valid date: {own_date!r}",
            )
        ]
    if own_date > today:
        return [
            ValidationIssue(
                path=path,
                code="future_date",
                message=(
                    f"{path} {own_date.isoformat()} is in the future (today is {today.isoformat()})"
                ),
            )
        ]
    cutoff = today.replace(year=today.year - MAX_INVOICE_AGE_YEARS)
    if own_date < cutoff:
        return [
            ValidationIssue(
                path=path,
                code="stale_date",
                message=(
                    f"{path} {own_date.isoformat()} is more than "
                    f"{MAX_INVOICE_AGE_YEARS} years old (cutoff {cutoff.isoformat()})"
                ),
            )
        ]
    return []


def _edrpou_checksum_ok(digits: list[int]) -> bool:
    """8-digit ЄДРПОУ control-digit algorithm: weighted sum of the first 7
    digits mod 11 against two weight sets, falling back to 0 if both hit the
    mod-11 == 10 edge case."""
    weights_primary = (1, 2, 3, 4, 5, 6, 7)
    weights_fallback = (3, 4, 5, 6, 7, 8, 9)
    check = sum(d * w for d, w in zip(digits[:7], weights_primary, strict=True)) % 11
    if check == 10:
        check = sum(d * w for d, w in zip(digits[:7], weights_fallback, strict=True)) % 11
        if check == 10:
            check = 0
    return check == digits[7]


def _ipn_checksum_ok(digits: list[int]) -> bool:
    """10-digit ІПН (РНОКПП) control-digit algorithm: weighted sum of the
    first 9 digits, mod 11, mod 10, compared to the 10th digit."""
    weights = (-1, 5, 7, 9, 4, 6, 10, 5, 7)
    total = sum(d * w for d, w in zip(digits[:9], weights, strict=True))
    check = (total % 11) % 10
    return check == digits[9]


def _check_tax_id(party: Party, *, path: str) -> list[ValidationIssue]:
    tax_id = party.tax_id
    if tax_id is None:
        return []
    issue = ValidationIssue(
        path=path,
        code="bad_tax_id",
        message=f"{path} '{tax_id}' failed the ЄДРПОУ/ІПН checksum",
    )
    if not tax_id.isdigit():
        return [issue]
    digits = [int(c) for c in tax_id]
    if len(digits) == 8:
        return [] if _edrpou_checksum_ok(digits) else [issue]
    if len(digits) == 10:
        return [] if _ipn_checksum_ok(digits) else [issue]
    return [issue]


def validate_document(
    payload: InvoiceData | ActData, *, today: date | None = None
) -> list[ValidationIssue]:
    """Run every deterministic check and return the combined issue list.

    Works for either `InvoiceData` or `ActData` — see `_DocumentView`/`_view`
    above for how the two payload shapes are read generically. `today` is
    injectable for tests; real callers leave it as `None` and get
    `date.today()`.
    """
    resolved_today = today if today is not None else date.today()
    view = _view(payload)
    issues: list[ValidationIssue] = []
    issues += _check_line_arithmetic(view.items, path_prefix=view.items_path)
    issues += _check_subtotal(view)
    issues += _check_total(payload)
    issues += _check_date(view, today=resolved_today)
    for party, path in view.parties:
        issues += _check_tax_id(party, path=path)
    return issues


def validate_invoice(payload: InvoiceData, *, today: date | None = None) -> list[ValidationIssue]:
    """`validate_document`, kept under its original T6 name for existing
    callers/tests — `InvoiceData` was the only payload type before T10."""
    return validate_document(payload, today=today)


def zero_out_confidences(
    confidences: list[FieldConfidence], issues: list[ValidationIssue]
) -> list[FieldConfidence]:
    """Return a new confidence list with every issue's path set to confidence 0.

    Paths with no issue are returned unchanged (same object); this is a pure
    transform, the input list is never mutated.
    """
    bad_paths = {issue.path for issue in issues}
    return [
        c.model_copy(update={"confidence": 0.0}) if c.path in bad_paths else c for c in confidences
    ]
