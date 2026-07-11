import type { FieldConfidence, ValidationIssue } from "../api/schemas.ts";

// Flag-detection logic (UI_SPEC §3.1): confidence threshold + issue mapping.
// A validation issue always wins over a low confidence — a field with a T6
// issue is red even if its confidence happens to be >= the threshold.

export const REVIEW_THRESHOLD = 0.85;

export type FlagSeverity = "ok" | "warn" | "err";

export function issueForPath(path: string, issues: ValidationIssue[]): ValidationIssue | null {
  return issues.find((issue) => issue.path === path) ?? null;
}

export function severityFor(
  confidence: number,
  path: string,
  issues: ValidationIssue[],
): FlagSeverity {
  if (issueForPath(path, issues) !== null) return "err";
  if (confidence < REVIEW_THRESHOLD) return "warn";
  return "ok";
}

export interface FieldFlag {
  path: string;
  severity: FlagSeverity;
  confidence: number;
  issue: ValidationIssue | null;
  sourceSnippet: string | null;
}

export function flagsFor(confidences: FieldConfidence[], issues: ValidationIssue[]): FieldFlag[] {
  return confidences.map((c) => ({
    path: c.path,
    severity: severityFor(c.confidence, c.path, issues),
    confidence: c.confidence,
    issue: issueForPath(c.path, issues),
    sourceSnippet: c.source_snippet,
  }));
}
