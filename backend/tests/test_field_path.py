"""Unit tests for the T7 dot-path get/set helpers (app/services/field_path.py).

Pure functions, no I/O — exercised directly against InvoiceData-shaped dicts.
"""

from __future__ import annotations

import copy

import pytest

from app.services.field_path import FieldPathError, get_field_value, set_field_value

PAYLOAD = {
    "supplier": {"name": "ТОВ Х", "tax_id": "38412907", "address": None},
    "buyer": {"name": None, "tax_id": None, "address": None},
    "invoice_number": "1",
    "invoice_date": "2026-01-01",
    "items": [
        {"name": "a", "quantity": "1", "unit_price": "2.00", "amount": "2.00"},
        {"name": "b", "quantity": "3", "unit_price": "4.00", "amount": "12.00"},
    ],
    "subtotal": "14.00",
    "vat_amount": "0.00",
    "total": "14.00",
}


def test_get_top_level_scalar() -> None:
    assert get_field_value(PAYLOAD, "total") == "14.00"


def test_get_nested_object_field() -> None:
    assert get_field_value(PAYLOAD, "supplier.tax_id") == "38412907"


def test_get_indexed_list_field() -> None:
    assert get_field_value(PAYLOAD, "items[1].amount") == "12.00"


def test_set_does_not_mutate_input() -> None:
    original = copy.deepcopy(PAYLOAD)
    set_field_value(PAYLOAD, "total", "99.00")
    assert original == PAYLOAD


def test_set_top_level_scalar() -> None:
    result = set_field_value(PAYLOAD, "total", "99.00")
    assert result["total"] == "99.00"
    assert PAYLOAD["total"] == "14.00"


def test_set_nested_object_field() -> None:
    result = set_field_value(PAYLOAD, "supplier.tax_id", "12345678")
    assert result["supplier"]["tax_id"] == "12345678"
    assert result["supplier"]["name"] == "ТОВ Х"  # sibling untouched


def test_set_indexed_list_field() -> None:
    result = set_field_value(PAYLOAD, "items[0].amount", "3.00")
    assert result["items"][0]["amount"] == "3.00"
    assert result["items"][1]["amount"] == "12.00"  # sibling item untouched


def test_get_missing_key_raises() -> None:
    with pytest.raises(FieldPathError):
        get_field_value(PAYLOAD, "nope")


def test_get_out_of_range_index_raises() -> None:
    with pytest.raises(FieldPathError):
        get_field_value(PAYLOAD, "items[9].amount")


def test_set_out_of_range_index_raises() -> None:
    with pytest.raises(FieldPathError):
        set_field_value(PAYLOAD, "items[9].amount", "1.00")


def test_malformed_segment_raises() -> None:
    with pytest.raises(FieldPathError):
        get_field_value(PAYLOAD, "items[abc].amount")


def test_empty_path_raises() -> None:
    with pytest.raises(FieldPathError):
        get_field_value(PAYLOAD, "")
