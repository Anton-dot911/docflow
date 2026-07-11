import type { FieldFlag } from "./flags.ts";

// Confirm-gating logic (UI_SPEC §3.6): the Confirm button only becomes
// enabled/primary once every field is green (all-green state). This is
// stricter than the backend's 409 gate (which only blocks confidence-0
// fields) — the UI also waits out unresolved amber fields before allowing a
// one-click confirm, matching the mockup's `nextField`/`confirm` behavior.

export function canConfirm(flags: FieldFlag[]): boolean {
  return flags.every((f) => f.severity === "ok");
}
