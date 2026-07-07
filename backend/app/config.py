"""Runtime configuration constants for DocFlow backend.

Values that are not secrets live here as plain constants; secrets come from the
environment (see backend/.env.example). Ingestion (T2) limits and conventions
are defined here so routes, services, and tests share a single source of truth.
"""

from __future__ import annotations

import os
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

# --- Auth placeholder -------------------------------------------------------
# Auth is out of T2 scope (see docs/decisions.md). Until it lands, every
# document is owned by this fixed user_id so the documents.user_id NOT NULL /
# uuid column is satisfied and the RLS predicate has something to key on.
PLACEHOLDER_USER_ID = UUID("00000000-0000-0000-0000-000000000000")

# --- Background status stub (T2) --------------------------------------------
# The stub worker moves a document queued -> processing -> review with this
# delay in between so the status flow is exercised end-to-end before real
# processing (T3+) exists. Overridable via env; tests set it to 0 for speed.
STATUS_STUB_DELAY_SECONDS = float(os.environ.get("INGESTION_STUB_DELAY_SECONDS", "1.0"))
