"""Resolve the running commit SHA for the /health endpoint.

Deploys (Railway/Fly, Docker) inject the SHA via an env var since the .git
directory is not shipped; local dev falls back to `git rev-parse`.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

# Checked in order; the first non-empty value wins.
_ENV_VARS = ("GIT_COMMIT", "COMMIT_SHA", "SOURCE_COMMIT", "RAILWAY_GIT_COMMIT_SHA")
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def get_commit_sha() -> str:
    """Return the current commit SHA, or "unknown" if it cannot be resolved."""
    import os

    for name in _ENV_VARS:
        value = os.environ.get(name)
        if value:
            return value.strip()

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return "unknown"

    return result.stdout.strip() or "unknown"
