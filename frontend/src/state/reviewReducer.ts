import type { ExtractionDetail, ExtractionPayload } from "../api/schemas.ts";
import { setFieldValue } from "./fieldPath.ts";

// Optimistic PATCH + rollback for the Review page. An edit (or an "Прийняти
// як є" accept-as-is, which PATCHes the same value) is applied to local state
// immediately; if the request fails, state rolls back to the pre-edit
// snapshot. Mirrors the backend's PATCH behavior (services/field_path.py +
// routes/extractions.py) so the optimistic view matches what the server will
// actually return: confidence -> 1.0, matching validation issue cleared.

export interface ReviewState {
  extraction: ExtractionDetail;
  snapshot: ExtractionDetail | null;
  pendingPath: string | null;
  error: string | null;
}

export type ReviewAction =
  | { type: "edit/start"; path: string; value: unknown }
  | { type: "edit/success"; extraction: ExtractionDetail }
  | { type: "edit/failure"; message: string }
  | { type: "extraction/replace"; extraction: ExtractionDetail };

export function initReviewState(extraction: ExtractionDetail): ReviewState {
  return { extraction, snapshot: null, pendingPath: null, error: null };
}

function applyOptimisticEdit(
  extraction: ExtractionDetail,
  path: string,
  value: unknown,
): ExtractionDetail {
  const payload = setFieldValue(
    extraction.payload as unknown as Record<string, unknown>,
    path,
    value,
  ) as unknown as ExtractionPayload;
  const fieldConfidences = extraction.field_confidences.map((c) =>
    c.path === path ? { ...c, confidence: 1 } : c,
  );
  const validationIssues = extraction.validation_issues.filter((issue) => issue.path !== path);
  return {
    ...extraction,
    payload,
    field_confidences: fieldConfidences,
    validation_issues: validationIssues,
  };
}

export function reviewReducer(state: ReviewState, action: ReviewAction): ReviewState {
  switch (action.type) {
    case "edit/start":
      return {
        ...state,
        snapshot: state.extraction,
        extraction: applyOptimisticEdit(state.extraction, action.path, action.value),
        pendingPath: action.path,
        error: null,
      };
    case "edit/success":
      return {
        ...state,
        extraction: action.extraction,
        snapshot: null,
        pendingPath: null,
        error: null,
      };
    case "edit/failure":
      return {
        ...state,
        extraction: state.snapshot ?? state.extraction,
        snapshot: null,
        pendingPath: null,
        error: action.message,
      };
    case "extraction/replace":
      return { ...state, extraction: action.extraction, snapshot: null, pendingPath: null };
    default:
      return state;
  }
}
