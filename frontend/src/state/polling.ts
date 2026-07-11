import type { DocStatus } from "../api/schemas.ts";

// Auto-refresh gate for the T8 history list: poll only while at least one
// document is still in flight (queued/processing); a page of only
// review/confirmed/failed rows should not keep polling forever.

const IN_FLIGHT_STATUSES: ReadonlySet<DocStatus> = new Set(["queued", "processing"]);

export function hasInFlightDocuments(statuses: readonly DocStatus[]): boolean {
  return statuses.some((status) => IN_FLIGHT_STATUSES.has(status));
}
