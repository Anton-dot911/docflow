"""Real-Supabase integration test for ingestion (T2).

Marked `supabase` and excluded from the default run (which stays hermetic). Run
explicitly with real credentials in the env:

    uv run pytest -m supabase -s

It creates the bucket if missing, uploads a real file, inserts a documents row,
runs the background preprocess worker, verifies the row + Storage object exist,
prints them as evidence, then cleans everything up.
"""

from __future__ import annotations

import io
import os
import uuid
from typing import Any, cast

import pytest
from fastapi import BackgroundTasks
from PIL import Image

from app.config import PLACEHOLDER_USER_ID, STORAGE_BUCKET
from app.repos.documents import DocumentsRepo
from app.repos.storage import StorageRepo
from app.repos.supabase_client import get_supabase
from app.services.ingestion import IngestionService, UploadFilePayload

pytestmark = pytest.mark.supabase


def _tiny_png() -> bytes:
    """A genuinely decodable PNG (T3 preprocessing actually opens the image)."""
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 40)).save(buf, format="PNG")
    return buf.getvalue()


PNG_SAMPLE = _tiny_png()


@pytest.mark.skipif(
    not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")),
    reason="requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY",
)
def test_ingest_creates_row_and_storage_object() -> None:
    client = get_supabase()
    service = IngestionService(storage=StorageRepo(), documents=DocumentsRepo())
    background = BackgroundTasks()

    filename = f"integration-{uuid.uuid4().hex[:8]}.png"
    created = service.ingest([UploadFilePayload(filename=filename, content=PNG_SAMPLE)], background)
    assert len(created) == 1
    assert created[0].status.value == "queued"
    document_id = created[0].document_id
    assert document_id is not None

    # Run the queued->processing->review preprocess worker the endpoint runs in bg.
    for task in background.tasks:
        task.func(*task.args, **task.kwargs)

    try:
        # DB row present, storage_path follows the convention, status reached review.
        row = cast(
            dict[str, Any],
            client.table("documents")
            .select("*")
            .eq("id", str(document_id))
            .single()
            .execute()
            .data,
        )
        expected_path = f"{PLACEHOLDER_USER_ID}/{document_id}/{filename}"
        assert row["storage_path"] == expected_path
        assert row["status"] == "review"
        assert row["user_id"] == str(PLACEHOLDER_USER_ID)
        # T3: preprocessing persisted mode + pages (a PNG upload -> vision, 1 page).
        assert row["mode"] == "vision"
        assert row["pages"] == 1

        # Storage object present under the document's folder.
        objects = client.storage.from_(STORAGE_BUCKET).list(f"{PLACEHOLDER_USER_ID}/{document_id}")
        names = [o["name"] for o in objects]
        assert filename in names

        print("\n=== INTEGRATION EVIDENCE ===")
        print("documents row:", row)
        print("storage object:", f"{STORAGE_BUCKET}/{expected_path}")
        print("storage listing:", objects)
        print("=== END EVIDENCE ===")
    finally:
        client.storage.from_(STORAGE_BUCKET).remove(
            [f"{PLACEHOLDER_USER_ID}/{document_id}/{filename}"]
        )
        client.table("documents").delete().eq("id", str(document_id)).execute()
