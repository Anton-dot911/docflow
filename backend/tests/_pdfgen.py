"""Dependency-free builders for tiny, deterministic PDF fixtures (T3 tests).

Hand-rolls minimal but valid PDFs so tests never fetch anything from the network
(and don't need a heavyweight PDF writer). Two shapes are enough for T3:

- `build_text_pdf` — pages with a real Helvetica text layer (born-digital PDF).
- `build_image_pdf` — a page whose only content is an embedded JPEG image and
  which therefore has *no* extractable text (a stand-in for a scanned page).

Shared by `tests/fixtures/generate_fixtures.py` (which writes the committed
fixture files) and by `tests/test_preprocess.py` (which builds an oversized
many-page PDF in memory for the page-cap test).
"""

from __future__ import annotations


def _escape(text: str) -> bytes:
    """Escape a string for a PDF literal-string operand."""
    out = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return out.encode("latin-1", "replace")


def _serialize(objects: dict[int, bytes]) -> bytes:
    """Serialize a {number: object-body} map into a PDF with a valid xref table.

    Object numbers must be contiguous starting at 1; object 1 must be the
    catalog (the trailer points /Root at ``1 0 R``).
    """
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + objects[num] + b"\nendobj\n"

    xref_pos = len(out)
    count = max(objects) + 1  # entries 0..max
    out += b"xref\n0 %d\n" % count
    out += b"0000000000 65535 f \n"
    for num in range(1, count):
        out += b"%010d 00000 n \n" % offsets[num]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (count, xref_pos)
    return bytes(out)


def build_text_pdf(pages_text: list[str]) -> bytes:
    """Build a PDF where each string in ``pages_text`` becomes one text page."""
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    kids: list[int] = []
    next_num = 4
    for text in pages_text:
        page_num, content_num = next_num, next_num + 1
        next_num += 2
        kids.append(page_num)
        content = b"BT /F1 24 Tf 72 700 Td (" + _escape(text) + b") Tj ET"
        objects[content_num] = (
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream"
        )
        objects[page_num] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_num
        )
    kids_str = b" ".join(b"%d 0 R" % k for k in kids)
    objects[2] = b"<< /Type /Pages /Kids [ " + kids_str + b" ] /Count %d >>" % len(kids)
    return _serialize(objects)


def build_image_pdf(jpeg: bytes, width: int, height: int) -> bytes:
    """Build a single-page PDF whose only content is an embedded JPEG image.

    The page carries no font/text operators, so text extraction yields nothing —
    the preprocessor must fall back to vision mode.
    """
    content = b"q %d 0 0 %d 0 0 cm /Im0 Do Q" % (width, height)
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [ 3 0 R ] /Count 1 >>",
        3: (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>" % (width, height)
        ),
        4: b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        5: (
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
            b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\n"
            b"stream\n" % (width, height, len(jpeg)) + jpeg + b"\nendstream"
        ),
    }
    return _serialize(objects)
