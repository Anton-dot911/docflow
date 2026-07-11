"""Field-flag counting for the T8 history list.

Mirrors the frontend's `state/flags.ts` severity rule (duplicated, not shared,
per the same reasoning as `field_path.py` — see docs/decisions.md): a field
needs review if it has a T6 validation issue at its path, or its confidence is
below `REVIEW_THRESHOLD` — a validation issue always wins even when the
confidence happens to be high. Pure function; no I/O.
"""

from __future__ import annotations

from typing import Any

from app.config import REVIEW_THRESHOLD


def count_flags(
    field_confidences: list[dict[str, Any]], validation_issues: list[dict[str, Any]]
) -> int:
    issue_paths = {issue["path"] for issue in validation_issues}
    return sum(
        1
        for c in field_confidences
        if c["path"] in issue_paths or c["confidence"] < REVIEW_THRESHOLD
    )
