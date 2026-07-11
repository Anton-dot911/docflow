import { describe, expect, it } from "vitest";
import { nextUnresolvedPath, unresolvedOrder } from "../src/state/guidedNav.ts";
import type { FieldFlag } from "../src/state/flags.ts";

const FLAGS: FieldFlag[] = [
  { path: "supplier.name", severity: "ok", confidence: 0.99, issue: null, sourceSnippet: null },
  { path: "items[0].amount", severity: "warn", confidence: 0.62, issue: null, sourceSnippet: null },
  { path: "total", severity: "err", confidence: 0, issue: null, sourceSnippet: null },
];

describe("unresolvedOrder", () => {
  it("excludes ok fields and keeps warn/err in list order", () => {
    expect(unresolvedOrder(FLAGS)).toEqual(["items[0].amount", "total"]);
  });

  it("is empty when everything is ok (all-green state)", () => {
    const allOk = FLAGS.map((f) => ({ ...f, severity: "ok" as const }));
    expect(unresolvedOrder(allOk)).toEqual([]);
  });
});

describe("nextUnresolvedPath", () => {
  it("starts at the first unresolved field when nothing is focused", () => {
    expect(nextUnresolvedPath(FLAGS, null)).toBe("items[0].amount");
  });

  it("advances to the next unresolved field", () => {
    expect(nextUnresolvedPath(FLAGS, "items[0].amount")).toBe("total");
  });

  it("wraps around after the last unresolved field", () => {
    expect(nextUnresolvedPath(FLAGS, "total")).toBe("items[0].amount");
  });

  it("returns null once every field is resolved", () => {
    const allOk = FLAGS.map((f) => ({ ...f, severity: "ok" as const }));
    expect(nextUnresolvedPath(allOk, null)).toBeNull();
  });

  it("falls back to the first unresolved field if current is no longer in the list", () => {
    expect(nextUnresolvedPath(FLAGS, "some-resolved-path")).toBe("items[0].amount");
  });
});
