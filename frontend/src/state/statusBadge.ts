import type { DocStatus } from "../api/schemas.ts";

// Status -> badge presentation for the T8 history list. `tone` picks a CSS
// modifier class (`hp-badge--<tone>`, see history.css); labels are Ukrainian
// to match the rest of the product copy (ReviewPage's "підтверджено" etc).

export type StatusTone = "neutral" | "active" | "warn" | "success" | "error";

export interface StatusBadgeInfo {
  label: string;
  tone: StatusTone;
}

const BADGES: Record<DocStatus, StatusBadgeInfo> = {
  queued: { label: "У черзі", tone: "neutral" },
  processing: { label: "Обробляється", tone: "active" },
  review: { label: "На перевірці", tone: "warn" },
  confirmed: { label: "Підтверджено", tone: "success" },
  failed: { label: "Помилка", tone: "error" },
};

export function statusBadge(status: DocStatus): StatusBadgeInfo {
  return BADGES[status];
}
