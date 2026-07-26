"""Golden dataset reader and file resolver (T11).

`load_golden` is the reference reader for the Goldsmith export saved at
`data/golden/invoices.jsonl`: one JSON object per line, parsed into a typed
`GoldenExample`. `fetch_dataset` pulls that JSONL from the Goldsmith export
function; `resolve_file` turns an example's `storage://goldsmith-inputs/...`
reference into the actual document bytes by downloading from the shared
Supabase Storage bucket (Goldsmith owns `goldsmith-inputs`; DocFlow only reads
it here — see LESSONS §9), caching each file under `data/golden/files/` so a
re-run does not re-download.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The Goldsmith file references all live under this one Storage bucket.
_STORAGE_PREFIX = "storage://goldsmith-inputs/"
_STORAGE_BUCKET = "goldsmith-inputs"


@dataclass(frozen=True)
class GoldenExample:
    """One labelled example from the Goldsmith `docflow-invoices` dataset.

    `expected` is the human-verified label object (its keys are a minimal
    subset — `invoice_number`, `issue_date`, `total_amount`, optionally
    `currency` — not the full `InvoiceData` shape; the scorer maps them onto
    the pipeline's payload). `tags` are the raw category labels as exported.
    """

    id: str
    file_ref: str
    expected: dict[str, Any]
    tags: list[str] = field(default_factory=list)


def fetch_dataset(*, url: str, token: str, dataset: str, version: int) -> str:
    """Fetch the raw JSONL export for `dataset`@`version` from Goldsmith."""
    full_url = f"{url}?dataset={dataset}&version={version}"
    request = urllib.request.Request(full_url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        body: str = response.read().decode("utf-8")
    return body


def save_dataset(text: str, path: Path) -> None:
    """Write the raw JSONL export to `path`, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_golden(path: Path) -> list[GoldenExample]:
    """Reference reader: parse `data/golden/invoices.jsonl` into examples.

    Blank lines are skipped; every non-blank line must be a JSON object with an
    `id` and an `input.file_ref`.
    """
    examples: list[GoldenExample] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        obj = json.loads(line)
        examples.append(
            GoldenExample(
                id=obj["id"],
                file_ref=obj["input"]["file_ref"],
                expected=obj.get("expected", {}),
                tags=list(obj.get("tags", [])),
            )
        )
    return examples


def _storage_path(file_ref: str) -> str:
    if not file_ref.startswith(_STORAGE_PREFIX):
        raise ValueError(f"unsupported file_ref scheme: {file_ref!r}")
    return file_ref[len(_STORAGE_PREFIX) :]


def resolve_file(file_ref: str, *, cache_dir: Path) -> bytes:
    """Return the document bytes for `file_ref`, caching under `cache_dir`.

    Downloads from the `goldsmith-inputs` Supabase Storage bucket using the
    service-role key (`SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`), keyed by
    the object's basename so repeat runs read the local copy.
    """
    object_path = _storage_path(file_ref)
    cache_file = cache_dir / object_path.split("/")[-1]
    if cache_file.is_file():
        return cache_file.read_bytes()

    supabase_url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    download_url = f"{supabase_url}/storage/v1/object/{_STORAGE_BUCKET}/{object_path}"
    request = urllib.request.Request(
        download_url, headers={"Authorization": f"Bearer {key}", "apikey": key}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data: bytes = response.read()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(data)
    return data
