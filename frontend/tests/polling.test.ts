import { describe, expect, it } from "vitest";
import { hasInFlightDocuments } from "../src/state/polling.ts";

describe("hasInFlightDocuments", () => {
  it("is false for an empty list", () => {
    expect(hasInFlightDocuments([])).toBe(false);
  });

  it("is true when at least one document is queued", () => {
    expect(hasInFlightDocuments(["confirmed", "queued", "failed"])).toBe(true);
  });

  it("is true when at least one document is processing", () => {
    expect(hasInFlightDocuments(["review", "processing"])).toBe(true);
  });

  it("is false once everything has settled (review/confirmed/failed)", () => {
    expect(hasInFlightDocuments(["review", "confirmed", "failed"])).toBe(false);
  });
});
