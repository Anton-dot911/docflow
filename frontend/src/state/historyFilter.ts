import type { DocStatus } from "../api/schemas.ts";

// Status filter chips for the T8 history list. "all" is frontend-only (it
// means "no status filter"); every other value maps 1:1 to the backend's
// `status` query param.

export type StatusFilter = "all" | DocStatus;

export const STATUS_FILTERS: readonly { value: StatusFilter; label: string }[] = [
  { value: "all", label: "Усі" },
  { value: "queued", label: "У черзі" },
  { value: "processing", label: "Обробляється" },
  { value: "review", label: "На перевірці" },
  { value: "confirmed", label: "Підтверджено" },
  { value: "failed", label: "Помилка" },
];

export function statusQueryParam(filter: StatusFilter): DocStatus | undefined {
  return filter === "all" ? undefined : filter;
}
