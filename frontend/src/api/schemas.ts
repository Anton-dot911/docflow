import { z } from "zod";

// Wire-contract schemas for responses crossing the HTTP boundary from the
// FastAPI backend. Inlined here (the scaffolder's ts-fullstack template kept
// these in a shared workspace package shared with a Fastify service; DocFlow's
// backend is Python, so the web app owns its own copy of the contract).

export const healthResponseSchema = z.object({
  status: z.literal("ok"),
  commit: z.string(),
});

export type HealthResponse = z.infer<typeof healthResponseSchema>;

// --- T7 Review UI ------------------------------------------------------------
// Mirrors backend/app/models/domain.py + backend/app/models/review.py. Money
// fields are Decimal server-side, serialized as numeric strings (CLAUDE.md
// rule 7) — kept as `z.string()` here rather than coerced to `number`, so no
// float precision is ever introduced client-side; formatting/parsing for
// display and edits happens explicitly where needed.

export const partySchema = z.object({
  name: z.string().nullable(),
  tax_id: z.string().nullable(),
  address: z.string().nullable(),
});
export type Party = z.infer<typeof partySchema>;

export const lineItemSchema = z.object({
  name: z.string().nullable(),
  quantity: z.string().nullable(),
  unit_price: z.string().nullable(),
  amount: z.string().nullable(),
});
export type LineItem = z.infer<typeof lineItemSchema>;

export const invoiceDataSchema = z.object({
  supplier: partySchema,
  buyer: partySchema,
  invoice_number: z.string().nullable(),
  invoice_date: z.string().nullable(),
  items: z.array(lineItemSchema),
  subtotal: z.string().nullable(),
  vat_amount: z.string().nullable(),
  total: z.string().nullable(),
});
export type InvoiceData = z.infer<typeof invoiceDataSchema>;

// --- T10 Classifier + act type ------------------------------------------------
// Mirrors backend/app/models/domain.py's ActData: same shape as InvoiceData,
// with contractor/customer (виконавець/замовник) in place of supplier/buyer,
// act_number/act_date in place of invoice_number/invoice_date, and services in
// place of items (still lineItemSchema entries).

export const actDataSchema = z.object({
  contractor: partySchema,
  customer: partySchema,
  act_number: z.string().nullable(),
  act_date: z.string().nullable(),
  services: z.array(lineItemSchema),
  subtotal: z.string().nullable(),
  vat_amount: z.string().nullable(),
  total: z.string().nullable(),
});
export type ActData = z.infer<typeof actDataSchema>;

// A payload is either shape; the two are structurally distinct (items vs
// services, supplier/buyer vs contractor/customer) so zod's union picks the
// right one deterministically, mirroring the backend's `InvoiceData | ActData`
// smart-union validation (app/models/domain.py's ExtractionResult.payload).
export const extractionPayloadSchema = z.union([invoiceDataSchema, actDataSchema]);
export type ExtractionPayload = z.infer<typeof extractionPayloadSchema>;

export function isInvoicePayload(payload: ExtractionPayload): payload is InvoiceData {
  return "items" in payload;
}

export const fieldConfidenceSchema = z.object({
  path: z.string(),
  confidence: z.number().min(0).max(1),
  source_snippet: z.string().nullable(),
});
export type FieldConfidence = z.infer<typeof fieldConfidenceSchema>;

export const validationIssueSchema = z.object({
  path: z.string(),
  code: z.string(),
  message: z.string(),
});
export type ValidationIssue = z.infer<typeof validationIssueSchema>;

export const extractionDetailSchema = z.object({
  id: z.string(),
  document_id: z.string(),
  payload: extractionPayloadSchema,
  field_confidences: z.array(fieldConfidenceSchema),
  validation_issues: z.array(validationIssueSchema),
});
export type ExtractionDetail = z.infer<typeof extractionDetailSchema>;

export const docStatusSchema = z.enum(["queued", "processing", "review", "confirmed", "failed"]);
export type DocStatus = z.infer<typeof docStatusSchema>;

export const documentDetailSchema = z.object({
  id: z.string(),
  filename: z.string(),
  status: docStatusSchema,
  doc_type: z.string().nullable(),
  mode: z.enum(["text", "vision"]).nullable(),
  pages: z.number().nullable(),
  created_at: z.string(),
  extraction: extractionDetailSchema.nullable(),
});
export type DocumentDetail = z.infer<typeof documentDetailSchema>;

export const fileUrlResponseSchema = z.object({
  url: z.string(),
  expires_in: z.number(),
});
export type FileUrlResponse = z.infer<typeof fileUrlResponseSchema>;

export const confirmConflictSchema = z.object({
  message: z.string(),
  unresolved_fields: z.array(z.string()),
});
export type ConfirmConflict = z.infer<typeof confirmConflictSchema>;

// --- T8 History page ----------------------------------------------------------
// Mirrors backend/app/models/document.py's DocumentListItem/DocumentListResponse
// (GET /api/documents, extended by T8 with `total`/`flags_count` from each
// document's latest extraction).

export const documentListItemSchema = z.object({
  id: z.string(),
  filename: z.string(),
  status: docStatusSchema,
  doc_type: z.string().nullable(),
  created_at: z.string(),
  total: z.string().nullable(),
  flags_count: z.number().nullable(),
});
export type DocumentListItem = z.infer<typeof documentListItemSchema>;

export const documentListResponseSchema = z.object({
  items: z.array(documentListItemSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});
export type DocumentListResponse = z.infer<typeof documentListResponseSchema>;

// --- T9 Demo mode -------------------------------------------------------------
// Mirrors backend/app/models/demo.py's DemoSampleItem (GET /api/demo/samples).

export const demoSampleSchema = z.object({
  id: z.string(),
  key: z.string(),
  filename: z.string(),
  difficulty: z.string(),
  title: z.string(),
  description: z.string(),
  status: docStatusSchema,
  doc_type: z.string().nullable(),
});
export type DemoSample = z.infer<typeof demoSampleSchema>;
