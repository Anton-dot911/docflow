import type { FieldFlag } from "./flags.ts";

// Guided review order (UI_SPEC §3.3): "Next field" / Tab jump only across
// unresolved flagged fields (amber warn + red err), in list order, wrapping
// around. Green (ok) fields are never part of the guided sequence.

export function unresolvedOrder(flags: FieldFlag[]): string[] {
  return flags.filter((f) => f.severity !== "ok").map((f) => f.path);
}

export function nextUnresolvedPath(flags: FieldFlag[], currentPath: string | null): string | null {
  const order = unresolvedOrder(flags);
  if (order.length === 0) return null;
  const first = order[0] as string;
  if (currentPath === null) return first;
  const index = order.indexOf(currentPath);
  if (index === -1) return first;
  return order[(index + 1) % order.length] as string;
}
