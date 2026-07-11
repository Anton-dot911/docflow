"""Runtime configuration constants for DocFlow backend.

Values that are not secrets live here as plain constants; secrets come from the
environment (see backend/.env.example). Ingestion (T2) limits and conventions
are defined here so routes, services, and tests share a single source of truth.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

# --- Upload validation (T2) -------------------------------------------------
MIN_FILES_PER_REQUEST = 1
MAX_FILES_PER_REQUEST = 10
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB per file

# Logical file types we accept, keyed by the label sniff_type() returns.
ALLOWED_TYPES: frozenset[str] = frozenset({"pdf", "jpg", "png"})

# --- Supabase Storage -------------------------------------------------------
# Private bucket that holds every uploaded document. Created programmatically
# with the service-role key if it does not already exist.
STORAGE_BUCKET = "documents"

# --- Validation (T6) ---------------------------------------------------------
# Absolute tolerance for line/subtotal/total arithmetic checks (Decimal, per
# CLAUDE.md rule 7 — money is never float).
VALIDATION_AMOUNT_TOLERANCE = Decimal("0.01")

# invoice_date sanity: older than this many years -> "stale_date".
MAX_INVOICE_AGE_YEARS = 10

# --- Review UI (T7) ---------------------------------------------------------
# GET /api/documents/{id}/file mints a short-lived signed URL to the private
# Storage object rather than exposing a public one.
SIGNED_URL_EXPIRES_SECONDS = 3600

# Confidence threshold for review highlight (docs/PLAN.md contract). The T7
# frontend already hardcodes this value (src/state/flags.ts); T8 is the first
# backend consumer (history list's per-document flags_count).
REVIEW_THRESHOLD = 0.85

# --- Auth placeholder -------------------------------------------------------
# Auth is out of T2 scope (see docs/decisions.md). Until it lands, every
# document is owned by this fixed user_id so the documents.user_id NOT NULL /
# uuid column is satisfied and the RLS predicate has something to key on.
PLACEHOLDER_USER_ID = UUID("00000000-0000-0000-0000-000000000000")
