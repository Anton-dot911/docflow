import { describe, expect, it } from "vitest";
import { flagsFor, REVIEW_THRESHOLD, severityFor } from "../src/state/flags.ts";
import type { ValidationIssue } from "../src/api/schemas.ts";

const ISSUES: ValidationIssue[] = [
  {
    path: "total",
    code: "total_mismatch",
    message: "positions total 14460.00, document says 14640.00",
  },
];

describe("severityFor", () => {
  it("is ok at or above the threshold with no issue", () => {
    expect(severityFor(0.85, "supplier.name", [])).toBe("ok");
    expect(severityFor(0.99, "supplier.name", [])).toBe("ok");
  });

  it("is warn just below the threshold", () => {
    expect(severityFor(REVIEW_THRESHOLD - 0.01, "items[0].amount", [])).toBe("warn");
  });

  it("is err when a validation issue matches the path, regardless of confidence", () => {
    expect(severityFor(0.99, "total", ISSUES)).toBe("err");
  });

  it("err takes priority over warn for the same low-confidence field", () => {
    expect(severityFor(0.1, "total", ISSUES)).toBe("err");
  });
});

describe("flagsFor", () => {
  it("maps each confidence entry to a flag with severity and issue", () => {
    const flags = flagsFor(
      [
        { path: "supplier.name", confidence: 0.99, source_snippet: null },
        { path: "items[0].amount", confidence: 0.62, source_snippet: "450,00" },
        { path: "total", confidence: 0, source_snippet: "14 640,00" },
      ],
      ISSUES,
    );
    expect(flags.map((f) => f.severity)).toEqual(["ok", "warn", "err"]);
    expect(flags[2]?.issue?.code).toBe("total_mismatch");
    expect(flags[0]?.issue).toBeNull();
  });
});
