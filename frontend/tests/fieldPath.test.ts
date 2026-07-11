import { describe, expect, it } from "vitest";
import { FieldPathError, setFieldValue } from "../src/state/fieldPath.ts";

const PAYLOAD = {
  supplier: { name: "ТОВ Х", tax_id: "38412907", address: null },
  buyer: { name: null, tax_id: null, address: null },
  invoice_number: "1",
  invoice_date: "2026-01-01",
  items: [
    { name: "a", quantity: "1", unit_price: "2.00", amount: "2.00" },
    { name: "b", quantity: "3", unit_price: "4.00", amount: "12.00" },
  ],
  subtotal: "14.00",
  vat_amount: "0.00",
  total: "14.00",
};

describe("setFieldValue", () => {
  it("sets a top-level scalar without mutating the input", () => {
    const result = setFieldValue(PAYLOAD, "total", "99.00");
    expect(result.total).toBe("99.00");
    expect(PAYLOAD.total).toBe("14.00");
  });

  it("sets a nested object field, leaving siblings untouched", () => {
    const result = setFieldValue(PAYLOAD, "supplier.tax_id", "12345678") as typeof PAYLOAD;
    expect(result.supplier.tax_id).toBe("12345678");
    expect(result.supplier.name).toBe("ТОВ Х");
  });

  it("sets an indexed line-item field, leaving other items untouched", () => {
    const result = setFieldValue(PAYLOAD, "items[0].amount", "3.00") as typeof PAYLOAD;
    expect(result.items[0]?.amount).toBe("3.00");
    expect(result.items[1]?.amount).toBe("12.00");
  });

  it("throws FieldPathError for an out-of-range index", () => {
    expect(() => setFieldValue(PAYLOAD, "items[9].amount", "1.00")).toThrow(FieldPathError);
  });

  it("throws FieldPathError for an unknown top-level key", () => {
    expect(() => setFieldValue(PAYLOAD, "nope", "1.00")).toThrow(FieldPathError);
  });

  it("throws FieldPathError for a malformed segment", () => {
    expect(() => setFieldValue(PAYLOAD, "items[abc].amount", "1.00")).toThrow(FieldPathError);
  });
});
