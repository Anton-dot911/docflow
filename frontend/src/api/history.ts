import {
  documentListResponseSchema,
  type DocStatus,
  type DocumentListResponse,
} from "./schemas.ts";
import { ApiError } from "./review.ts";

// Client for the T8 History page's list endpoint (GET /api/documents, T2's
// paged listing extended with total/flags_count) and export downloads.

export interface ListDocumentsParams {
  status?: DocStatus;
  limit: number;
  offset: number;
}

export async function fetchDocuments(params: ListDocumentsParams): Promise<DocumentListResponse> {
  const search = new URLSearchParams();
  if (params.status) search.set("status", params.status);
  search.set("limit", String(params.limit));
  search.set("offset", String(params.offset));
  const response = await fetch(`/api/documents?${search.toString()}`);
  if (!response.ok) {
    throw new ApiError(`GET documents failed with status ${response.status}`, response.status);
  }
  return documentListResponseSchema.parse(await response.json());
}

// Confirmed rows link straight to this URL (an <a download> anchor); the
// backend sets Content-Disposition, so no fetch/blob dance is needed here.
export function exportUrl(documentId: string, format: "json" | "csv"): string {
  return `/api/documents/${documentId}/export?format=${format}`;
}
