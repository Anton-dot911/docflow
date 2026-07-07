import { describe, expect, it } from "vitest";
import { parseHealth } from "../src/api/client.ts";

describe("parseHealth", () => {
  it("accepts a valid backend response", () => {
    const payload = { status: "ok", commit: "0123456789abcdef" };
    expect(parseHealth(payload)).toEqual(payload);
  });

  it("rejects a malformed response", () => {
    expect(() => parseHealth({ status: "nope" })).toThrow();
  });
});
