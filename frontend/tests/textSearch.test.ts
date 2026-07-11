import { describe, expect, it } from "vitest";
import { findSnippetItemIndices } from "../src/state/textSearch.ts";

describe("findSnippetItemIndices", () => {
  it("finds a snippet contained in a single text item", () => {
    const items = ["Борошно пшен. в/г 25кг", "× 18 =", "450,00"];
    expect(findSnippetItemIndices(items, "450,00")).toEqual([2]);
  });

  it("finds a snippet spanning multiple adjacent text items", () => {
    const items = ["ДО СПЛАТИ:", "14 640,00"];
    expect(findSnippetItemIndices(items, "ДО СПЛАТИ: 14 640,00")).toEqual([0, 1]);
  });

  it("is case- and whitespace-insensitive", () => {
    const items = ["Всього:   14640.00  "];
    expect(findSnippetItemIndices(items, "всього: 14640.00")).toEqual([0]);
  });

  it("returns null when the snippet is not present", () => {
    const items = ["Борошно житнє", "25 кг", "400,00"];
    expect(findSnippetItemIndices(items, "не існує")).toBeNull();
  });

  it("returns null for an empty snippet", () => {
    expect(findSnippetItemIndices(["a", "b"], "")).toBeNull();
  });
});
