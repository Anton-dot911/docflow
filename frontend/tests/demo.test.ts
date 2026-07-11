import { describe, expect, it } from "vitest";
import { parseDemoSamples } from "../src/api/demo.ts";

const VALID_SAMPLE = {
  id: "00000000-0000-0000-0000-0000000000d1",
  key: "clean_text",
  filename: "rahunok_chystyi.pdf",
  difficulty: "легкий",
  title: "Чистий текстовий PDF",
  description: "Born-digital рахунок з реальним текстовим шаром.",
  status: "review",
  doc_type: "invoice",
};

describe("parseDemoSamples", () => {
  it("accepts a valid backend response", () => {
    expect(parseDemoSamples([VALID_SAMPLE])).toEqual([VALID_SAMPLE]);
  });

  it("accepts a null doc_type (not yet seeded)", () => {
    const sample = { ...VALID_SAMPLE, status: "queued", doc_type: null };
    expect(parseDemoSamples([sample])).toEqual([sample]);
  });

  it("rejects a malformed status", () => {
    expect(() => parseDemoSamples([{ ...VALID_SAMPLE, status: "nope" }])).toThrow();
  });

  it("rejects a missing required field", () => {
    const { difficulty: _difficulty, ...missingDifficulty } = VALID_SAMPLE;
    expect(() => parseDemoSamples([missingDifficulty])).toThrow();
  });
});
