"""Unit tests for services/preprocess.py (T3).

Covers the two real fixture PDFs + a JPG, the pure text-coverage function around
its 0.3 boundary (both directly and end-to-end through a crafted PDF), and the
20-page processing cap. No network, no LLM — fixtures are generated locally by
tests/fixtures/generate_fixtures.py (and the oversized PDF is built in memory).
"""

from __future__ import annotations

import io
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from _pdfgen import build_text_pdf
from PIL import Image

from app.models.preprocess import PreprocessedDoc
from app.services.preprocess import (
    MAX_LONG_SIDE_PX,
    MAX_PAGES,
    TEXT_MODE_THRESHOLD,
    UnsupportedDocumentError,
    page_has_text,
    preprocess,
    text_coverage_ratio,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _long_side(png: bytes) -> int:
    with Image.open(io.BytesIO(png)) as img:
        assert img.format == "PNG"
        return max(img.size)


# --- fixture files ----------------------------------------------------------


def test_text_pdf_yields_text_mode() -> None:
    result = preprocess(_read("text_sample.pdf"))
    assert result.mode == "text"
    assert result.text is not None and result.text.strip() != ""
    assert result.images is None
    assert result.pages == 2  # correct page count
    assert "DocFlow invoice sample" in result.text


def test_scanned_pdf_yields_vision_mode_capped() -> None:
    result = preprocess(_read("scanned_sample.pdf"))
    assert result.mode == "vision"
    assert result.text is None
    assert result.images is not None and len(result.images) == 1
    assert result.pages == 1
    assert _long_side(result.images[0]) <= MAX_LONG_SIDE_PX


def test_jpg_yields_vision_mode_capped() -> None:
    result = preprocess(_read("photo_sample.jpg"))
    assert result.mode == "vision"
    assert result.images is not None and len(result.images) == 1
    assert result.pages == 1
    assert _long_side(result.images[0]) <= MAX_LONG_SIDE_PX


def test_unsupported_bytes_raise() -> None:
    with pytest.raises(UnsupportedDocumentError):
        preprocess(b"MZ\x90\x00 not a document")


# --- text-coverage ratio: pure, around the 0.3 boundary ---------------------


def test_page_has_text_threshold() -> None:
    assert page_has_text("x" * 10) is True
    assert page_has_text("x" * 9) is False
    assert page_has_text("   \n  short  ") is False  # < 10 non-whitespace


def test_coverage_ratio_empty_is_zero() -> None:
    assert text_coverage_ratio([]) == 0.0


def test_coverage_ratio_at_boundary_is_text_mode() -> None:
    # 3 of 10 pages with text -> exactly 0.3, which is NOT below the threshold.
    pages = ["real text content"] * 3 + [""] * 7
    ratio = text_coverage_ratio(pages)
    assert ratio == pytest.approx(0.3)
    assert ratio >= TEXT_MODE_THRESHOLD


def test_coverage_ratio_just_below_boundary_is_vision_mode() -> None:
    # 2 of 10 pages with text -> 0.2, below the threshold.
    pages = ["real text content"] * 2 + [""] * 8
    ratio = text_coverage_ratio(pages)
    assert ratio == pytest.approx(0.2)
    assert ratio < TEXT_MODE_THRESHOLD


def test_boundary_selects_text_mode_end_to_end() -> None:
    # 3 text + 7 blank pages -> ratio 0.3 -> text mode.
    pdf = build_text_pdf(["real text content here"] * 3 + [""] * 7)
    result = preprocess(pdf)
    assert result.mode == "text"
    assert result.pages == 10


def test_just_below_boundary_selects_vision_mode_end_to_end() -> None:
    # 2 text + 8 blank pages -> ratio 0.2 -> vision mode.
    pdf = build_text_pdf(["real text content here"] * 2 + [""] * 8)
    result = preprocess(pdf)
    assert result.mode == "vision"
    assert result.images is not None and len(result.images) == 10
    assert result.pages == 10


# --- page cap ---------------------------------------------------------------


def test_oversized_pdf_capped_at_max_pages() -> None:
    # 25 blank (no-text) pages -> vision; processing (and rasterization) capped.
    pdf = build_text_pdf([""] * 25)
    assert len(pdfium.PdfDocument(pdf)) == 25  # source really is oversized

    result = preprocess(pdf)
    assert result.mode == "vision"
    assert result.pages == MAX_PAGES == 20  # capped, noted in output
    assert result.images is not None and len(result.images) == 20
    for png in result.images:
        assert _long_side(png) <= MAX_LONG_SIDE_PX


# --- model invariants -------------------------------------------------------


def test_preprocessed_doc_rejects_inconsistent_mode() -> None:
    with pytest.raises(ValueError):
        PreprocessedDoc(mode="text", text=None, pages=1)
    with pytest.raises(ValueError):
        PreprocessedDoc(mode="vision", images=None, pages=1)
