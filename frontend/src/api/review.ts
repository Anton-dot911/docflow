import {
  confirmConflictSchema,
  documentDetailSchema,
  extractionDetailSchema,
  fileUrlResponseSchema,
  type ConfirmConflict,
  type DocumentDetail,
  type ExtractionDetail,
  type FileUrlResponse,
} from "./schemas.ts";

// Client for the T7 Review UI endpoints (see docs/PLAN.md API contract). The
// Vite dev server proxies /api to the FastAPI backend (see vite.config.ts).

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// Thrown specifically for POST /confirm's 409 so callers can show which
// fields are still unresolved without re-parsing the response body.
export class ConfirmConflictError extends ApiError {
  conflict: ConfirmConflict;

  constructor(conflict: ConfirmConflict) {
    super(conflict.message, 409);
    this.name = "ConfirmConflictError";
    this.conflict = conflict;
  }
}

export async function fetchDocument(documentId: string): Promise<DocumentDetail> {
  const response = await fetch(`/api/documents/${documentId}`);
  if (!response.ok) {
    throw new ApiError(`GET document failed with status ${response.status}`, response.status);
  }
  return documentDetailSchema.parse(await response.json());
}

export async function fetchDocumentFileUrl(documentId: string): Promise<FileUrlResponse> {
  const response = await fetch(`/api/documents/${documentId}/file`);
  if (!response.ok) {
    throw new ApiError(`GET file url failed with status ${response.status}`, response.status);
  }
  return fileUrlResponseSchema.parse(await response.json());
}

export async function patchExtraction(
  extractionId: string,
  fieldPath: string,
  newValue: unknown,
): Promise<ExtractionDetail> {
  const response = await fetch(`/api/extractions/${extractionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ field_path: fieldPath, new_value: newValue }),
  });
  if (!response.ok) {
    throw new ApiError(`PATCH extraction failed with status ${response.status}`, response.status);
  }
  return extractionDetailSchema.parse(await response.json());
}

export async function confirmDocument(documentId: string): Promise<void> {
  const response = await fetch(`/api/documents/${documentId}/confirm`, { method: "POST" });
  if (response.status === 409) {
    const body = await response.json();
    throw new ConfirmConflictError(confirmConflictSchema.parse(body.detail));
  }
  if (!response.ok) {
    throw new ApiError(`confirm failed with status ${response.status}`, response.status);
  }
}
