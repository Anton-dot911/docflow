"""Dot-path read/write for extraction payloads (T7 review edits).

`FieldConfidence.path` / `ValidationIssue.path` use the dot-path shape from
docs/PLAN.md (e.g. ``"items[2].amount"``, ``"supplier.tax_id"``, ``"total"``).
The Review UI PATCHes one field at a time by that same path; these pure
functions translate it into dict/list navigation over the JSON-native
payload dict (as stored in `extractions.payload`). Malformed paths or an
out-of-range index raise `FieldPathError` so the route layer can turn them
into a 422 rather than a 500.
"""

from __future__ import annotations

import copy
import re
from typing import Any

_SEGMENT_RE = re.compile(r"^([^.\[\]]+)(\[(\d+)\])?$")


class FieldPathError(ValueError):
    """`field_path` does not resolve against the given payload."""


def _tokenize(path: str) -> list[tuple[str, int | None]]:
    if not path:
        raise FieldPathError("field_path must not be empty")
    tokens: list[tuple[str, int | None]] = []
    for part in path.split("."):
        match = _SEGMENT_RE.match(part)
        if match is None:
            raise FieldPathError(f"malformed field_path segment: {part!r}")
        index = int(match.group(3)) if match.group(3) is not None else None
        tokens.append((match.group(1), index))
    return tokens


def get_field_value(payload: dict[str, Any], path: str) -> Any:
    """Return the value at `path` within `payload`."""
    node: Any = payload
    for name, index in _tokenize(path):
        if not isinstance(node, dict) or name not in node:
            raise FieldPathError(f"field_path {path!r} does not resolve: missing {name!r}")
        node = node[name]
        if index is not None:
            if not isinstance(node, list) or index >= len(node):
                raise FieldPathError(
                    f"field_path {path!r} does not resolve: index {index} out of range"
                )
            node = node[index]
    return node


def set_field_value(payload: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """Return a copy of `payload` with `value` written at `path`.

    Pure: `payload` is never mutated.
    """
    result = copy.deepcopy(payload)
    tokens = _tokenize(path)
    node: Any = result
    for i, (name, index) in enumerate(tokens):
        is_last = i == len(tokens) - 1
        if not isinstance(node, dict) or name not in node:
            raise FieldPathError(f"field_path {path!r} does not resolve: missing {name!r}")
        if index is not None:
            container = node[name]
            if not isinstance(container, list) or index >= len(container):
                raise FieldPathError(
                    f"field_path {path!r} does not resolve: index {index} out of range"
                )
            if is_last:
                container[index] = value
            else:
                node = container[index]
        else:
            if is_last:
                node[name] = value
            else:
                node = node[name]
    return result
