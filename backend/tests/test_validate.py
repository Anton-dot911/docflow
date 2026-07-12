"""Exhaustive unit tests for services/validate.py (T6, generalized in T10).

Pure logic, no mocks needed (CLAUDE.md testing conventions). Covers arithmetic
tolerance edges, date sanity, ЄДРПОУ/ІПН checksum vectors, confidence zeroing,
and an "e2e-lite" run of the full pipeline (all checks together) against the
T5 clean fixture's expected values — see docs comment on
`test_clean_t5_fixture_produces_zero_issues` for why that must stay at zero.
This whole invoice suite is unchanged from T6: it still calls `validate_invoice`
exactly as before, which now forwards to the generalized `validate_document`
(see `services/validate.py`). A parallel suite near the bottom of this file
exercises `validate_document` directly against `ActData`, proving the same
checks generalize correctly rather than being forked into a second module.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.models.domain import (
    ActData,
    FieldConfidence,
    InvoiceData,
    LineItem,
    Party,
    ValidationIssue,
)
from app.services.validate import validate_document, validate_invoice, zero_out_confidences

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _item(
    *,
    quantity: str | None,
    unit_price: str | None,
    amount: str | None,
    name: str | None = "item",
) -> LineItem:
    return LineItem(
        name=name,
        quantity=Decimal(quantity) if quantity is not None else None,
        unit_price=Decimal(unit_price) if unit_price is not None else None,
        amount=Decimal(amount) if amount is not None else None,
    )


def _party(tax_id: str | None, *, name: str | None = "party") -> Party:
    return Party(name=name, tax_id=tax_id, address="addr")


def _invoice(
    *,
    items: list[LineItem] | None = None,
    subtotal: str | None = "100.00",
    vat_amount: str | None = "20.00",
    total: str | None = "120.00",
    invoice_date: date | None = None,
    supplier_tax_id: str | None = None,
    buyer_tax_id: str | None = None,
) -> InvoiceData:
    return InvoiceData(
        supplier=_party(supplier_tax_id, name="supplier"),
        buyer=_party(buyer_tax_id, name="buyer"),
        invoice_number="INV-1",
        invoice_date=invoice_date,
        items=items
        if items is not None
        else [_item(quantity="1", unit_price="100.00", amount="100.00")],
        subtotal=Decimal(subtotal) if subtotal is not None else None,
        vat_amount=Decimal(vat_amount) if vat_amount is not None else None,
        total=Decimal(total) if total is not None else None,
    )


# --- line arithmetic ---------------------------------------------------------


def test_line_arithmetic_exact_match_no_issue() -> None:
    inv = _invoice(items=[_item(quantity="3", unit_price="10.00", amount="30.00")])
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "line_arithmetic_mismatch"] == []


def test_line_arithmetic_within_tolerance_no_issue() -> None:
    # 3 * 10.00 = 30.00, stated amount off by 0.009 -> within the 0.01 tolerance.
    inv = _invoice(items=[_item(quantity="3", unit_price="10.00", amount="30.009")])
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "line_arithmetic_mismatch"] == []


def test_line_arithmetic_just_outside_tolerance_flags() -> None:
    # off by 0.011 -> outside the 0.01 tolerance.
    inv = _invoice(items=[_item(quantity="3", unit_price="10.00", amount="30.011")])
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "line_arithmetic_mismatch"]
    assert len(matches) == 1
    assert matches[0].path == "items[0].amount"
    assert "30.01" in matches[0].message  # concrete numbers in the message


def test_line_arithmetic_multiple_bad_lines() -> None:
    inv = _invoice(
        items=[
            _item(quantity="2", unit_price="10.00", amount="25.00"),  # expected 20.00
            _item(quantity="1", unit_price="5.00", amount="5.00"),  # ok
            _item(quantity="4", unit_price="3.00", amount="20.00"),  # expected 12.00
        ]
    )
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    bad = [i for i in issues if i.code == "line_arithmetic_mismatch"]
    assert {i.path for i in bad} == {"items[0].amount", "items[2].amount"}


def test_line_arithmetic_null_amount_skipped() -> None:
    inv = _invoice(items=[_item(quantity="3", unit_price="10.00", amount=None)])
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "line_arithmetic_mismatch"] == []


def test_line_arithmetic_null_quantity_or_price_skipped() -> None:
    inv = _invoice(
        items=[
            _item(quantity=None, unit_price="10.00", amount="999.00"),
            _item(quantity="3", unit_price=None, amount="999.00"),
        ]
    )
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "line_arithmetic_mismatch"] == []


# --- subtotal / total ---------------------------------------------------------


def test_subtotal_matches_no_issue() -> None:
    inv = _invoice(
        items=[
            _item(quantity="1", unit_price="60.00", amount="60.00"),
            _item(quantity="1", unit_price="40.00", amount="40.00"),
        ],
        subtotal="100.00",
        vat_amount="20.00",
        total="120.00",
    )
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "subtotal_mismatch"] == []


def test_subtotal_mismatch_flags_with_concrete_numbers() -> None:
    inv = _invoice(
        items=[_item(quantity="1", unit_price="80.00", amount="80.00")],
        subtotal="100.00",
        vat_amount="20.00",
        total="120.00",
    )
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "subtotal_mismatch"]
    assert len(matches) == 1
    assert matches[0].path == "subtotal"
    assert matches[0].message == "positions total 80.00, document says 100.00"


def test_subtotal_check_skipped_when_any_item_amount_null() -> None:
    inv = _invoice(
        items=[
            _item(quantity="1", unit_price="80.00", amount="80.00"),
            _item(quantity="1", unit_price="80.00", amount=None),
        ],
        subtotal="100.00",
    )
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "subtotal_mismatch"] == []


def test_subtotal_check_skipped_when_subtotal_null() -> None:
    inv = _invoice(
        items=[_item(quantity="1", unit_price="80.00", amount="80.00")],
        subtotal=None,
    )
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "subtotal_mismatch"] == []


def test_total_matches_no_issue() -> None:
    inv = _invoice(subtotal="100.00", vat_amount="20.00", total="120.00")
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "total_mismatch"] == []


def test_total_mismatch_flags_with_concrete_numbers() -> None:
    inv = _invoice(subtotal="100.00", vat_amount="20.00", total="130.00")
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "total_mismatch"]
    assert len(matches) == 1
    assert matches[0].path == "total"
    assert matches[0].message == "subtotal 100.00 + vat 20.00 = 120.00, document says 130.00"


def test_total_check_skipped_when_vat_null() -> None:
    inv = _invoice(subtotal="100.00", vat_amount=None, total="999.00")
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "total_mismatch"] == []


# --- dates ---------------------------------------------------------------


def test_date_valid_no_issue() -> None:
    inv = _invoice(invoice_date=date(2024, 6, 1))
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if "date" in i.code] == []


def test_date_today_allowed() -> None:
    inv = _invoice(invoice_date=date(2025, 1, 1))
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if "date" in i.code] == []


def test_date_future_flags() -> None:
    inv = _invoice(invoice_date=date(2025, 1, 2))
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "future_date"]
    assert len(matches) == 1
    assert matches[0].path == "invoice_date"


def test_date_exactly_ten_years_old_allowed() -> None:
    # "not older than 10 years" -> exactly 10 years is the boundary, allowed.
    inv = _invoice(invoice_date=date(2015, 1, 1))
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "stale_date"] == []


def test_date_eleven_years_old_flags_stale() -> None:
    inv = _invoice(invoice_date=date(2014, 1, 1))
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "stale_date"]
    assert len(matches) == 1
    assert matches[0].path == "invoice_date"


def test_date_null_skipped() -> None:
    inv = _invoice(invoice_date=None)
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if "date" in i.code] == []


def test_garbage_date_string_rejected_by_pydantic_upstream() -> None:
    """A garbage date string can never reach validate_invoice: InvoiceData's
    `invoice_date: date | None` rejects it at construction time."""
    with pytest.raises(Exception):  # noqa: B017  # pydantic.ValidationError
        InvoiceData(
            supplier=_party(None),
            buyer=_party(None),
            invoice_number="INV-1",
            invoice_date="not-a-date",
            items=[],
            subtotal=None,
            vat_amount=None,
            total=None,
        )


def test_bad_date_defensive_branch_for_bypassed_validation() -> None:
    """bad_date only fires if a caller bypasses Pydantic validation entirely
    (e.g. `model_construct`); it can't happen via normal InvoiceData construction."""
    inv = InvoiceData.model_construct(
        supplier=_party(None),
        buyer=_party(None),
        invoice_number="INV-1",
        invoice_date="not-a-date",  # type: ignore[arg-type]
        items=[],
        subtotal=None,
        vat_amount=None,
        total=None,
    )
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "bad_date"]
    assert len(matches) == 1
    assert matches[0].path == "invoice_date"


# --- ЄДРПОУ / ІПН checksum ----------------------------------------------------

EDRPOU_VALID = ["38492069", "29141773", "76317064"]  # 3 known-valid vectors
IPN_VALID = "3012415678"


@pytest.mark.parametrize("tax_id", EDRPOU_VALID)
def test_edrpou_valid_vectors_no_issue(tax_id: str) -> None:
    inv = _invoice(supplier_tax_id=tax_id)
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "bad_tax_id"] == []


def test_edrpou_checksum_broken_flags() -> None:
    # Valid vector "29141773" with its control digit corrupted.
    inv = _invoice(supplier_tax_id="29141770")
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "bad_tax_id"]
    assert len(matches) == 1
    assert matches[0].path == "supplier.tax_id"


def test_edrpou_wrong_length_seven_digits_flags() -> None:
    inv = _invoice(supplier_tax_id="1234567")
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i.code for i in issues if i.path == "supplier.tax_id"] == ["bad_tax_id"]


def test_ipn_valid_ten_digit_no_issue() -> None:
    inv = _invoice(buyer_tax_id=IPN_VALID)
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "bad_tax_id"] == []


def test_ipn_checksum_broken_flags() -> None:
    inv = _invoice(buyer_tax_id="3012415670")  # last digit corrupted (was 8)
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "bad_tax_id"]
    assert len(matches) == 1
    assert matches[0].path == "buyer.tax_id"


def test_tax_id_with_letters_flags_bad_tax_id() -> None:
    inv = _invoice(supplier_tax_id="1234567A")
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i.code for i in issues if i.path == "supplier.tax_id"] == ["bad_tax_id"]


def test_tax_id_null_skipped() -> None:
    inv = _invoice(supplier_tax_id=None, buyer_tax_id=None)
    issues = validate_invoice(inv, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "bad_tax_id"] == []


# --- confidence zeroing -------------------------------------------------------


def test_zero_out_confidences_only_touches_matching_paths() -> None:
    confidences = [
        FieldConfidence(path="supplier.name", confidence=0.95, source_snippet=None),
        FieldConfidence(path="total", confidence=0.9, source_snippet=None),
        FieldConfidence(path="items[0].amount", confidence=0.8, source_snippet=None),
    ]
    issues = [ValidationIssue(path="total", code="total_mismatch", message="x")]

    result = zero_out_confidences(confidences, issues)

    by_path = {c.path: c.confidence for c in result}
    assert by_path["total"] == 0.0
    assert by_path["supplier.name"] == 0.95
    assert by_path["items[0].amount"] == 0.8
    # Original list is untouched (pure function).
    assert confidences[1].confidence == 0.9


def test_zero_out_confidences_multiple_issues_multiple_paths() -> None:
    confidences = [
        FieldConfidence(path="subtotal", confidence=0.9, source_snippet=None),
        FieldConfidence(path="items[0].amount", confidence=0.8, source_snippet=None),
        FieldConfidence(path="items[1].amount", confidence=0.7, source_snippet=None),
    ]
    issues = [
        ValidationIssue(path="items[0].amount", code="line_arithmetic_mismatch", message="a"),
        ValidationIssue(path="items[1].amount", code="line_arithmetic_mismatch", message="b"),
    ]

    result = zero_out_confidences(confidences, issues)

    by_path = {c.path: c.confidence for c in result}
    assert by_path["subtotal"] == 0.9
    assert by_path["items[0].amount"] == 0.0
    assert by_path["items[1].amount"] == 0.0


# --- e2e-lite: full pipeline against the T5 clean fixture ---------------------


def _load_expected_invoice_text() -> dict[str, Any]:
    if FIXTURES not in sys.path:
        sys.path.insert(0, FIXTURES)
    from generate_invoice_fixtures import EXPECTED_INVOICE_TEXT

    return dict(EXPECTED_INVOICE_TEXT)


def test_clean_t5_fixture_produces_zero_issues() -> None:
    """Runs every T6 check together against the T5 "clean" invoice fixture's
    known-correct field values (the same dict that generates invoice_text.pdf
    and that test_extract_smoke.py scores extraction against).

    This must produce zero issues: it's the DoD contract for a clean document.
    If it doesn't, the fixture's data or a validator has a bug — investigate,
    don't loosen the tolerance (see docs/PLAN.md T6 DoD).
    """
    exp = _load_expected_invoice_text()
    payload = InvoiceData(
        supplier=Party(**exp["supplier"]),
        buyer=Party(**exp["buyer"]),
        invoice_number=exp["invoice_number"],
        invoice_date=date.fromisoformat(exp["invoice_date"]),
        items=[
            LineItem(
                name=item["name"],
                quantity=Decimal(item["quantity"]),
                unit_price=Decimal(item["unit_price"]),
                amount=Decimal(item["amount"]),
            )
            for item in exp["items"]
        ],
        subtotal=Decimal(exp["subtotal"]),
        vat_amount=Decimal(exp["vat_amount"]),
        total=Decimal(exp["total"]),
    )

    # invoice_date (2024-04-17) is safely within [today-10y, today] for any
    # plausible "today" this suite runs on.
    issues = validate_invoice(payload)

    assert issues == [], f"clean fixture produced issues: {issues}"


# --- T10: validate_document generalized over ActData --------------------------
# Mirrors a slice of the invoice suite above against ActData's own field names
# (services/act_date/contractor/customer instead of items/invoice_date/
# supplier/buyer), proving the checks generalize rather than being forked.


def _act(
    *,
    services: list[LineItem] | None = None,
    subtotal: str | None = "100.00",
    vat_amount: str | None = "20.00",
    total: str | None = "120.00",
    act_date: date | None = None,
    contractor_tax_id: str | None = None,
    customer_tax_id: str | None = None,
) -> ActData:
    return ActData(
        contractor=_party(contractor_tax_id, name="contractor"),
        customer=_party(customer_tax_id, name="customer"),
        act_number="ACT-1",
        act_date=act_date,
        services=services
        if services is not None
        else [_item(quantity="1", unit_price="100.00", amount="100.00")],
        subtotal=Decimal(subtotal) if subtotal is not None else None,
        vat_amount=Decimal(vat_amount) if vat_amount is not None else None,
        total=Decimal(total) if total is not None else None,
    )


def test_act_line_arithmetic_uses_services_path() -> None:
    act = _act(services=[_item(quantity="3", unit_price="10.00", amount="30.011")])
    issues = validate_document(act, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "line_arithmetic_mismatch"]
    assert len(matches) == 1
    assert matches[0].path == "services[0].amount"


def test_act_line_arithmetic_exact_match_no_issue() -> None:
    act = _act(services=[_item(quantity="3", unit_price="10.00", amount="30.00")])
    issues = validate_document(act, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "line_arithmetic_mismatch"] == []


def test_act_subtotal_mismatch_flags() -> None:
    act = _act(
        services=[_item(quantity="1", unit_price="80.00", amount="80.00")],
        subtotal="100.00",
    )
    issues = validate_document(act, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "subtotal_mismatch"]
    assert len(matches) == 1
    assert matches[0].path == "subtotal"


def test_act_total_mismatch_flags() -> None:
    act = _act(subtotal="100.00", vat_amount="20.00", total="130.00")
    issues = validate_document(act, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "total_mismatch"]
    assert len(matches) == 1
    assert matches[0].path == "total"


def test_act_date_uses_act_date_path() -> None:
    act = _act(act_date=date(2025, 1, 2))
    issues = validate_document(act, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "future_date"]
    assert len(matches) == 1
    assert matches[0].path == "act_date"


def test_act_date_stale_flags() -> None:
    act = _act(act_date=date(2014, 1, 1))
    issues = validate_document(act, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "stale_date"]
    assert len(matches) == 1
    assert matches[0].path == "act_date"


def test_act_date_null_skipped() -> None:
    act = _act(act_date=None)
    issues = validate_document(act, today=date(2025, 1, 1))
    assert [i for i in issues if "date" in i.code] == []


@pytest.mark.parametrize("tax_id", EDRPOU_VALID)
def test_act_contractor_edrpou_valid_no_issue(tax_id: str) -> None:
    act = _act(contractor_tax_id=tax_id)
    issues = validate_document(act, today=date(2025, 1, 1))
    assert [i for i in issues if i.code == "bad_tax_id"] == []


def test_act_contractor_edrpou_broken_flags_contractor_path() -> None:
    act = _act(contractor_tax_id="29141770")  # corrupted control digit
    issues = validate_document(act, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "bad_tax_id"]
    assert len(matches) == 1
    assert matches[0].path == "contractor.tax_id"


def test_act_customer_ipn_broken_flags_customer_path() -> None:
    act = _act(customer_tax_id="3012415670")  # corrupted control digit
    issues = validate_document(act, today=date(2025, 1, 1))
    matches = [i for i in issues if i.code == "bad_tax_id"]
    assert len(matches) == 1
    assert matches[0].path == "customer.tax_id"


def _load_expected_act_text() -> dict[str, Any]:
    if FIXTURES not in sys.path:
        sys.path.insert(0, FIXTURES)
    from generate_act_fixtures import EXPECTED_ACT_TEXT

    return dict(EXPECTED_ACT_TEXT)


def test_clean_act_fixture_produces_zero_issues() -> None:
    """Runs every check together against the T10 "clean" act fixture's
    known-correct field values (the same dict that generates act_text.pdf).
    Must produce zero issues, mirroring `test_clean_t5_fixture_produces_zero_issues`
    above for the invoice case."""
    exp = _load_expected_act_text()
    payload = ActData(
        contractor=Party(**exp["contractor"]),
        customer=Party(**exp["customer"]),
        act_number=exp["act_number"],
        act_date=date.fromisoformat(exp["act_date"]),
        services=[
            LineItem(
                name=item["name"],
                quantity=Decimal(item["quantity"]),
                unit_price=Decimal(item["unit_price"]),
                amount=Decimal(item["amount"]),
            )
            for item in exp["services"]
        ],
        subtotal=Decimal(exp["subtotal"]),
        vat_amount=Decimal(exp["vat_amount"]),
        total=Decimal(exp["total"]),
    )

    issues = validate_document(payload)

    assert issues == [], f"clean act fixture produced issues: {issues}"
