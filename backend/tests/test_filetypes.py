"""Magic-byte sniffing — pure, no mocks (CLAUDE.md testing conventions)."""

from __future__ import annotations

import pytest

from app.services.filetypes import content_type_for, sniff_type

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 32
# A renamed executable: PE/DOS "MZ" header, regardless of a .pdf extension.
EXE = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 32


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PDF, "pdf"),
        (JPEG, "jpg"),
        (PNG, "png"),
    ],
)
def test_sniff_type_accepts_known_signatures(data: bytes, expected: str) -> None:
    assert sniff_type(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        EXE,
        b"",
        b"not a real file at all",
        b"GIF89a",  # a valid image, but not an accepted type
        b"PK\x03\x04",  # zip/office doc
        b"%PDF"[:3],  # truncated pdf signature must not match
    ],
)
def test_sniff_type_rejects_unknown(data: bytes) -> None:
    assert sniff_type(data) is None


def test_content_type_mapping() -> None:
    assert content_type_for("pdf") == "application/pdf"
    assert content_type_for("jpg") == "image/jpeg"
    assert content_type_for("png") == "image/png"
