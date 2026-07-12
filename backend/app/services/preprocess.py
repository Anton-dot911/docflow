"""Preprocessing pipeline (T3).

Turns a stored upload's bytes into a `PreprocessedDoc` for downstream
classification/extraction (T4+). Two modes:

- **text**: born-digital PDFs that carry enough of a text layer. We return the
  extracted text and skip vision — cheaper and exact.
- **vision**: scanned PDFs (little/no text layer) and image uploads (JPG/PNG).
  Pages are rasterized / normalized to PNG, capped at `MAX_LONG_SIDE_PX` on the
  long side.

The text-vs-vision choice for PDFs is by *text-coverage ratio*: the fraction of
processed pages that carry a meaningful text layer. Below `TEXT_MODE_THRESHOLD`
we fall back to vision. `text_coverage_ratio()` is a pure function so the 0.3
boundary is unit-tested without any PDF I/O.

Page cap: at most `MAX_PAGES` pages are processed — both text extraction and
rasterization stop there — so a 200-page upload can't blow up latency/cost in
T3. `PreprocessedDoc.pages` is the number of pages actually processed. See
docs/decisions.md.
"""

from __future__ import annotations

import io
from collections.abc import Sequence

import pypdfium2 as pdfium
from PIL import Image

from app.models.preprocess import PreprocessedDoc
from app.services.filetypes import sniff_type

# Longest edge (px) allowed for any image handed to a vision model.
MAX_LONG_SIDE_PX = 1568
# A PDF is processed as text when at least this fraction of its processed pages
# carry a real text layer; below it we fall back to vision.
TEXT_MODE_THRESHOLD = 0.3
# A page counts as "has text" once its stripped text reaches this many chars.
MIN_CHARS_PER_PAGE = 10
# Hard cap on pages processed in T3 (protects against 200-page PDFs).
MAX_PAGES = 20


class UnsupportedDocumentError(Exception):
    """The bytes are not a supported document type (pdf/jpg/png)."""


def page_has_text(page_text: str, min_chars: int = MIN_CHARS_PER_PAGE) -> bool:
    """True if a page's extracted text is substantial enough to count. Pure."""
    return len(page_text.strip()) >= min_chars


def text_coverage_ratio(pages_text: Sequence[str], min_chars: int = MIN_CHARS_PER_PAGE) -> float:
    """Fraction of pages carrying a real text layer, in [0, 1]. Pure.

    Empty input is 0.0 (nothing to extract → vision).
    """
    if not pages_text:
        return 0.0
    with_text = sum(1 for t in pages_text if page_has_text(t, min_chars))
    return with_text / len(pages_text)


def _resize_to_long_side(image: Image.Image, max_long_side: int = MAX_LONG_SIDE_PX) -> Image.Image:
    """Downscale so the long side is <= max_long_side. Never upscales."""
    long_side = max(image.size)
    if long_side <= max_long_side:
        return image
    scale = max_long_side / long_side
    new_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _encode_png(image: Image.Image) -> bytes:
    """Encode a PIL image as PNG bytes (normalized to RGB)."""
    if image.mode != "RGB":
        image = image.convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _render_page_png(page: pdfium.PdfPage) -> bytes:
    """Rasterize one PDF page to a PNG capped at MAX_LONG_SIDE_PX on the long side."""
    width_pt, height_pt = page.get_size()
    long_side_pt = max(width_pt, height_pt)
    # Render straight to the target long side (never upscale beyond it).
    scale = MAX_LONG_SIDE_PX / long_side_pt if long_side_pt else 1.0
    bitmap = page.render(scale=scale)
    image = bitmap.to_pil()
    bitmap.close()
    # Guard rounding: enforce the cap exactly after rendering.
    image = _resize_to_long_side(image)
    return _encode_png(image)


def _preprocess_pdf(content: bytes) -> PreprocessedDoc:
    pdf = pdfium.PdfDocument(content)
    try:
        n_pages = min(len(pdf), MAX_PAGES)
        pages_text: list[str] = []
        for i in range(n_pages):
            page = pdf[i]
            textpage = page.get_textpage()
            pages_text.append(textpage.get_text_range())
            textpage.close()
            page.close()

        if text_coverage_ratio(pages_text) >= TEXT_MODE_THRESHOLD:
            text = "\n\n".join(pages_text).strip()
            page1 = pages_text[0].strip() if pages_text else ""
            first_page_text = page1 if page1 else text
            return PreprocessedDoc(
                mode="text", text=text, pages=n_pages, first_page_text=first_page_text
            )

        images: list[bytes] = []
        for i in range(n_pages):
            page = pdf[i]
            images.append(_render_page_png(page))
        return PreprocessedDoc(mode="vision", images=images, pages=n_pages)
    finally:
        pdf.close()


def _preprocess_image(content: bytes) -> PreprocessedDoc:
    with Image.open(io.BytesIO(content)) as image:
        image.load()
        normalized = _resize_to_long_side(image.convert("RGB"))
        png = _encode_png(normalized)
    return PreprocessedDoc(mode="vision", images=[png], pages=1)


def preprocess(content: bytes) -> PreprocessedDoc:
    """Preprocess raw document bytes into a `PreprocessedDoc`.

    Routing is by sniffed magic bytes (same detector ingestion validated with):
    PDFs go through text/vision selection; JPG/PNG go straight to vision.
    """
    file_type = sniff_type(content)
    if file_type == "pdf":
        return _preprocess_pdf(content)
    if file_type in ("jpg", "png"):
        return _preprocess_image(content)
    raise UnsupportedDocumentError("unrecognized document type (expected pdf/jpg/png)")
