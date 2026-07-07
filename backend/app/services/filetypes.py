"""Magic-byte file type detection.

Extensions and client-supplied MIME headers are trivially spoofable (a renamed
`.exe -> .pdf` still claims `application/pdf`), so accepted types are decided by
inspecting the leading bytes of the content. Pure functions — no I/O, exhaustively
unit-tested without mocks.
"""

from __future__ import annotations

# (label, content-type, signature) — order does not matter, signatures are
# mutually exclusive. Labels match app.config.ALLOWED_TYPES.
_SIGNATURES: tuple[tuple[str, str, bytes], ...] = (
    ("pdf", "application/pdf", b"%PDF-"),
    ("jpg", "image/jpeg", b"\xff\xd8\xff"),
    ("png", "image/png", b"\x89PNG\r\n\x1a\n"),
)

_CONTENT_TYPES: dict[str, str] = {label: ct for label, ct, _ in _SIGNATURES}


def sniff_type(data: bytes) -> str | None:
    """Return the logical type ("pdf"/"jpg"/"png") from magic bytes, or None.

    None means the content matches no accepted signature and must be rejected.
    """
    for label, _content_type, signature in _SIGNATURES:
        if data.startswith(signature):
            return label
    return None


def content_type_for(file_type: str) -> str:
    """Map a sniffed logical type to the MIME type used for Storage upload."""
    return _CONTENT_TYPES[file_type]
