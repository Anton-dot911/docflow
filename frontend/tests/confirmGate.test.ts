import { describe, expect, it } from "vitest";
import { canConfirm } from "../src/state/confirmGate.ts";
import type { FieldFlag } from "../src/state/flags.ts";

describe("canConfirm", () => {
  it("blocks confirm while a red (err) field is unresolved", () => {
    const flags: FieldFlag[] = [
      { path: "supplier.name", severity: "ok", confidence: 0.99, issue: null, sourceSnippet: null },
      { path: "total", severity: "err", confidence: 0, issue: null, sourceSnippet: null },
    ];
    expect(canConfirm(flags)).toBe(false);
  });

  it("blocks confirm while an amber (warn) field is unresolved", () => {
    const flags: FieldFlag[] = [
      {
        path: "items[0].amount",
        severity: "warn",
        confidence: 0.62,
        issue: null,
        sourceSnippet: null,
      },
    ];
    expect(canConfirm(flags)).toBe(false);
  });

  it("allows confirm once every field is ok (all-green state)", () => {
    const flags: FieldFlag[] = [
      { path: "supplier.name", severity: "ok", confidence: 0.99, issue: null, sourceSnippet: null },
      { path: "total", severity: "ok", confidence: 1, issue: null, sourceSnippet: null },
    ];
    expect(canConfirm(flags)).toBe(true);
  });

  it("allows confirm on an empty field list", () => {
    expect(canConfirm([])).toBe(true);
  });
});
