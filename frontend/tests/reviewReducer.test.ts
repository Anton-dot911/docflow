import { describe, expect, it } from "vitest";
import { initReviewState, reviewReducer } from "../src/state/reviewReducer.ts";
import type { ExtractionDetail } from "../src/api/schemas.ts";

function extraction(): ExtractionDetail {
  return {
    id: "22222222-2222-2222-2222-222222222222",
    document_id: "11111111-1111-1111-1111-111111111111",
    payload: {
      supplier: { name: "ТОВ Х", tax_id: "38412907", address: null },
      buyer: { name: null, tax_id: null, address: null },
      invoice_number: "2847",
      invoice_date: "2026-07-04",
      items: [{ name: "Борошно", quantity: "25", unit_price: "18.00", amount: "450.00" }],
      subtotal: "12200.00",
      vat_amount: "2440.00",
      total: "14640.00",
    },
    field_confidences: [
      { path: "items[0].amount", confidence: 0.62, source_snippet: "450,00" },
      { path: "total", confidence: 0, source_snippet: "14 640,00" },
    ],
    validation_issues: [
      {
        path: "total",
        code: "total_mismatch",
        message: "positions total 14460.00, document says 14640.00",
      },
    ],
  };
}

describe("reviewReducer", () => {
  it("edit/start optimistically applies the value, bumps confidence, clears the issue", () => {
    const initial = initReviewState(extraction());
    const next = reviewReducer(initial, { type: "edit/start", path: "total", value: "14460.00" });

    expect(next.extraction.payload.total).toBe("14460.00");
    expect(next.extraction.field_confidences.find((c) => c.path === "total")?.confidence).toBe(1);
    expect(next.extraction.validation_issues).toEqual([]);
    expect(next.pendingPath).toBe("total");
    expect(next.snapshot).toEqual(initial.extraction);
  });

  it("edit/success replaces the extraction with the server response and clears the snapshot", () => {
    const initial = initReviewState(extraction());
    const started = reviewReducer(initial, {
      type: "edit/start",
      path: "total",
      value: "14460.00",
    });
    const serverExtraction: ExtractionDetail = {
      ...started.extraction,
      field_confidences: started.extraction.field_confidences,
    };

    const done = reviewReducer(started, { type: "edit/success", extraction: serverExtraction });

    expect(done.extraction).toEqual(serverExtraction);
    expect(done.snapshot).toBeNull();
    expect(done.pendingPath).toBeNull();
    expect(done.error).toBeNull();
  });

  it("edit/failure rolls back to the pre-edit snapshot and records the error", () => {
    const initial = initReviewState(extraction());
    const started = reviewReducer(initial, {
      type: "edit/start",
      path: "total",
      value: "14460.00",
    });

    const rolledBack = reviewReducer(started, { type: "edit/failure", message: "network error" });

    expect(rolledBack.extraction).toEqual(initial.extraction);
    expect(rolledBack.extraction.payload.total).toBe("14640.00");
    expect(rolledBack.snapshot).toBeNull();
    expect(rolledBack.pendingPath).toBeNull();
    expect(rolledBack.error).toBe("network error");
  });

  it("accept-as-is (same value) still bumps confidence and clears the issue", () => {
    const initial = initReviewState(extraction());
    const next = reviewReducer(initial, { type: "edit/start", path: "total", value: "14640.00" });

    expect(next.extraction.payload.total).toBe("14640.00");
    expect(next.extraction.field_confidences.find((c) => c.path === "total")?.confidence).toBe(1);
    expect(next.extraction.validation_issues).toEqual([]);
  });
});
