import { describe, expect, it } from "vitest";
import { STATUS_FILTERS, statusQueryParam } from "../src/state/historyFilter.ts";

describe("statusQueryParam", () => {
  it("maps 'all' to no query param (undefined)", () => {
    expect(statusQueryParam("all")).toBeUndefined();
  });

  it.each(["queued", "processing", "review", "confirmed", "failed"] as const)(
    "maps %s straight through to the backend status value",
    (status) => {
      expect(statusQueryParam(status)).toBe(status);
    },
  );
});

describe("STATUS_FILTERS", () => {
  it("starts with the 'all' chip and covers every DocStatus once", () => {
    expect(STATUS_FILTERS[0]?.value).toBe("all");
    const values = STATUS_FILTERS.map((f) => f.value);
    expect(new Set(values).size).toBe(values.length);
    expect(values).toEqual(
      expect.arrayContaining(["all", "queued", "processing", "review", "confirmed", "failed"]),
    );
  });
});
