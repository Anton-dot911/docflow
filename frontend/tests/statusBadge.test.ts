import { describe, expect, it } from "vitest";
import { statusBadge } from "../src/state/statusBadge.ts";

describe("statusBadge", () => {
  it.each([
    ["queued", "У черзі", "neutral"],
    ["processing", "Обробляється", "active"],
    ["review", "На перевірці", "warn"],
    ["confirmed", "Підтверджено", "success"],
    ["failed", "Помилка", "error"],
  ] as const)("maps %s -> label %s, tone %s", (status, label, tone) => {
    expect(statusBadge(status)).toEqual({ label, tone });
  });
});
