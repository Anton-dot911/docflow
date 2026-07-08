"""Generate the committed T3 preprocessing fixtures. Deterministic; no network.

Run from the backend dir:

    uv run python tests/fixtures/generate_fixtures.py

Writes three tiny files next to this script:

- ``text_sample.pdf``    — 2-page born-digital PDF with a real text layer.
- ``scanned_sample.pdf`` — 1-page PDF whose only content is an embedded JPEG
                           (no text layer → a stand-in for a scan).
- ``photo_sample.jpg``   — a small JPEG larger than 1568px on its long side so
                           the resize path is exercised.

The bytes are regenerated identically on every run, so the committed fixtures
can always be reproduced.
"""

from __future__ import annotations

import io
import os
import sys

from PIL import Image, ImageDraw

# Import the dependency-free PDF builders from the tests package (parent dir).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _pdfgen import build_image_pdf, build_text_pdf

HERE = os.path.dirname(os.path.abspath(__file__))


def _solid_photo(width: int, height: int) -> bytes:
    """A small, deterministic JPEG with a couple of shapes (never all one color)."""
    img = Image.new("RGB", (width, height), (240, 240, 240))
    draw = ImageDraw.Draw(img)
    draw.rectangle((width // 8, height // 8, width // 2, height // 2), fill=(30, 90, 160))
    draw.ellipse(
        (width // 2, height // 2, width - width // 8, height - height // 8),
        fill=(200, 60, 40),
    )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def main() -> None:
    text_pdf = build_text_pdf(
        [
            "DocFlow invoice sample - page 1 of 2",
            "Line items and totals - page 2 of 2",
        ]
    )
    with open(os.path.join(HERE, "text_sample.pdf"), "wb") as fh:
        fh.write(text_pdf)

    # "Scanned" page: an image embedded in a PDF with no text layer.
    scan_jpeg = _solid_photo(1700, 2200)
    scanned_pdf = build_image_pdf(scan_jpeg, 1700, 2200)
    with open(os.path.join(HERE, "scanned_sample.pdf"), "wb") as fh:
        fh.write(scanned_pdf)

    # Standalone photo upload, oversized on the long side to force a resize.
    photo = _solid_photo(2000, 1400)
    with open(os.path.join(HERE, "photo_sample.jpg"), "wb") as fh:
        fh.write(photo)

    print("wrote text_sample.pdf, scanned_sample.pdf, photo_sample.jpg to", HERE)


if __name__ == "__main__":
    main()
