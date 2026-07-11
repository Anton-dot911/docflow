"""Idempotent demo-mode seed script (T9).

Generates 5 curated demo documents in-script — extending the T3/T5 fixture
generators (`tests/_pdfgen.py`'s dependency-free PDF builders and
`tests/fixtures/generate_invoice_fixtures.py`'s fpdf2/Pillow renderers) —
uploads them to Supabase Storage under the fixed `DEMO_USER_ID`, and runs the
REAL extraction pipeline (T3 preprocess -> T5 extract -> T6 validate) on each
one exactly once, so demo visitors see genuine results rather than canned
data.

Idempotent: re-running with a `documents` row already present for one of the
5 fixed ids (`app.demo_data.DEMO_DOCUMENTS`) skips that document entirely — no
duplicate rows/Storage objects, no repeat LLM spend.

`--reset` restores every already-seeded demo document to its pristine,
just-extracted state (undoing operator edits/confirms left by public demo
traffic) from a snapshot committed at `scripts/demo_snapshots/<key>.json`,
written the first time the real pipeline runs for that document. A reset
never calls the LLM or Supabase Storage — only two small `extractions`/
`documents` updates per document — so it is cheap enough to run nightly (see
docs/decisions.md).

Usage (from backend/):

    # first run: needs real Anthropic + Supabase credentials
    ANTHROPIC_API_KEY=$METER_ANTHROPIC_API_KEY LLM_MODEL=claude-sonnet-5 \\
        uv run --env-file .env python scripts/seed_demo.py

    # nightly-safe reset: only needs Supabase credentials
    uv run --env-file .env python scripts/seed_demo.py --reset
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

# tests/_pdfgen.py's dependency-free PDF builders (T3 fixtures); scripts/ and
# tests/ are sibling directories under backend/. Mirrors the sys.path handling
# in tests/fixtures/generate_fixtures.py.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests"))
from _pdfgen import build_image_pdf

from app.config import DEMO_USER_ID
from app.demo_data import DEMO_DOCUMENTS, DemoDocSpec
from app.llm import create_docflow_llm
from app.repos.documents import DocumentsRepo
from app.repos.extractions import ExtractionsRepo
from app.repos.storage import StorageRepo, build_storage_path
from app.services.extract import ExtractionService
from app.services.preprocess import preprocess

SNAPSHOT_DIR = Path(__file__).resolve().parent / "demo_snapshots"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

_CENTS = Decimal("0.01")
_UA_MONTHS = (
    "січня",
    "лютого",
    "березня",
    "квітня",
    "травня",
    "червня",
    "липня",
    "серпня",
    "вересня",
    "жовтня",
    "листопада",
    "грудня",
)


def _ua_date(d: date) -> str:
    return f"{d.day} {_UA_MONTHS[d.month - 1]} {d.year} р."


def _money(value: Decimal) -> str:
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class _Item:
    name: str
    quantity: Decimal
    unit_price: Decimal


def _build_invoice(
    *,
    supplier_name: str,
    supplier_tax_id: str,
    supplier_address: str,
    buyer_name: str,
    buyer_tax_id: str,
    buyer_address: str,
    invoice_number: str,
    invoice_date: date,
    items: list[_Item],
    total_override: Decimal | None = None,
) -> dict[str, Any]:
    """Build an internally-consistent invoice dict (qty*price=amount etc.).

    `total_override`, when set, deliberately breaks the total_mismatch check
    (T6) without touching line/subtotal arithmetic — used for the
    arithmetic_error demo document.
    """
    line_items = []
    subtotal = Decimal("0")
    for item in items:
        amount = (item.quantity * item.unit_price).quantize(_CENTS, rounding=ROUND_HALF_UP)
        subtotal += amount
        line_items.append(
            {
                "name": item.name,
                "quantity": str(item.quantity),
                "unit_price": _money(item.unit_price),
                "amount": _money(amount),
            }
        )
    vat = (subtotal * Decimal("0.2")).quantize(_CENTS, rounding=ROUND_HALF_UP)
    total = total_override if total_override is not None else subtotal + vat
    return {
        "supplier": {
            "name": supplier_name,
            "tax_id": supplier_tax_id,
            "address": supplier_address,
        },
        "buyer": {"name": buyer_name, "tax_id": buyer_tax_id, "address": buyer_address},
        "invoice_number": invoice_number,
        "invoice_date": _ua_date(invoice_date),
        "items": line_items,
        "subtotal": _money(subtotal),
        "vat_amount": _money(vat),
        "total": _money(total),
    }


def _render_text_pdf(inv: dict[str, Any], *, page_break_after_item: int | None = None) -> bytes:
    """Render a born-digital invoice PDF (real Cyrillic text layer).

    Extends `tests/fixtures/generate_invoice_fixtures.py`'s `_build_text_pdf`
    with an optional explicit page break, used by the multi_page demo doc.
    """
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("DejaVu", "", FONT_PATH)
    pdf.add_font("DejaVu", "B", FONT_BOLD_PATH)

    def line(text: str, size: int = 11, style: str = "") -> None:
        pdf.set_font("DejaVu", style, size)
        pdf.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")

    line(inv["supplier"]["name"], size=13, style="B")
    line(f"ЄДРПОУ {inv['supplier']['tax_id']}")
    line(inv["supplier"]["address"])
    line("")
    line(f"РАХУНОК-ФАКТУРА № {inv['invoice_number']}", size=13, style="B")
    line(f"від {inv['invoice_date']}")
    line("")
    line(f"Покупець: {inv['buyer']['name']}")
    line(f"ЄДРПОУ/ІПН {inv['buyer']['tax_id']}")
    line(inv["buyer"]["address"])
    line("")
    line("№    Найменування                       К-сть    Ціна        Сума", style="B")
    for i, item in enumerate(inv["items"], start=1):
        line(
            f"{i}    {item['name']:<32} {item['quantity']:>4}    "
            f"{item['unit_price']:>9}   {item['amount']:>10}"
        )
        if page_break_after_item is not None and i == page_break_after_item:
            pdf.add_page()
    line("")
    line(f"Разом без ПДВ:                                          {inv['subtotal']}")
    line(f"ПДВ 20%:                                               {inv['vat_amount']}")
    line(f"Всього до сплати:                                      {inv['total']}", style="B")

    return bytes(pdf.output())


def _invoice_lines(inv: dict[str, Any]) -> list[str]:
    lines = [
        inv["supplier"]["name"],
        f"ЄДРПОУ {inv['supplier']['tax_id']}",
        inv["supplier"]["address"],
        "",
        f"РАХУНОК-ФАКТУРА № {inv['invoice_number']}",
        f"від {inv['invoice_date']}",
        "",
        f"Покупець: {inv['buyer']['name']}",
        f"ЄДРПОУ/ІПН {inv['buyer']['tax_id']}",
        inv["buyer"]["address"],
        "",
        "№   Найменування                К-сть   Ціна      Сума",
    ]
    for i, item in enumerate(inv["items"], start=1):
        lines.append(
            f"{i}   {item['name']:<28} {item['quantity']:>4}   "
            f"{item['unit_price']:>8}  {item['amount']:>10}"
        )
    lines += [
        "",
        f"Разом без ПДВ:                            {inv['subtotal']}",
        f"ПДВ 20%:                                   {inv['vat_amount']}",
        f"Всього до сплати:                         {inv['total']}",
    ]
    return lines


def _render_scan_image(inv: dict[str, Any]) -> Image.Image:
    """Render an invoice as a clean, high-resolution "scanned page" image.

    Adapted from `generate_invoice_fixtures.py`'s `_build_scan_jpeg`, kept as
    a `PIL.Image` (not yet JPEG-encoded) so callers can degrade it further
    (rotation/noise/compression) before encoding.
    """
    width, height = 1240, 1754
    img = Image.new("RGB", (width, height), (250, 249, 246))
    draw = ImageDraw.Draw(img)
    title = ImageFont.truetype(FONT_BOLD_PATH, 34)
    body = ImageFont.truetype(FONT_PATH, 28)
    y = 90
    for text in _invoice_lines(inv):
        if not text:
            y += 22
            continue
        font = title if "РАХУНОК" in text else body
        draw.text((90, y), text, fill=(20, 20, 20), font=font)
        y += 46
    return img


def _add_noise(img: Image.Image, *, amount: int, rng: random.Random) -> Image.Image:
    """Mutate `img` in place with mild per-pixel jitter (sensor-noise stand-in)."""
    pixels = img.load()
    width, height = img.size
    for _ in range((width * height) // 6):
        x, y = rng.randrange(width), rng.randrange(height)
        r, g, b = pixels[x, y]
        jitter = rng.randint(-amount, amount)
        pixels[x, y] = (
            max(0, min(255, r + jitter)),
            max(0, min(255, g + jitter)),
            max(0, min(255, b + jitter)),
        )
    return img


def _encode_jpeg(img: Image.Image, *, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


# --- The 5 curated invoices, keyed by app.demo_data's spec.key --------------


def _clean_text_pdf() -> bytes:
    inv = _build_invoice(
        supplier_name="ТОВ «ДокФлоу Демо»",
        supplier_tax_id="38492069",
        supplier_address="м. Київ, вул. Хрещатик, 22",
        buyer_name="ФОП Мельник Ірина Сергіївна",
        buyer_tax_id="3012415678",
        buyer_address="м. Львів, вул. Личаківська, 5",
        invoice_number="ДЕМО-0001",
        invoice_date=date.today() - timedelta(days=12),
        items=[
            _Item("Ноутбук Dell Latitude 5540", Decimal("2"), Decimal("28000.00")),
            _Item('Монітор Dell 24"', Decimal("2"), Decimal("6200.00")),
            _Item("Клавіатура бездротова Logitech", Decimal("4"), Decimal("650.00")),
        ],
    )
    return _render_text_pdf(inv)


def _good_scan_pdf() -> bytes:
    inv = _build_invoice(
        supplier_name="ТОВ «Будсервіс»",
        supplier_tax_id="30112340",
        supplier_address="м. Дніпро, вул. Європейська, 10",
        buyer_name="ТОВ «Мегабуд»",
        buyer_tax_id="3211500000",
        buyer_address="м. Одеса, вул. Дерибасівська, 3",
        invoice_number="СК-0458",
        invoice_date=date.today() - timedelta(days=20),
        items=[
            _Item("Цемент М500, мішок 25кг", Decimal("100"), Decimal("145.00")),
            _Item("Пісок будівельний, тонна", Decimal("20"), Decimal("480.00")),
            _Item("Цегла керамічна, тис. шт", Decimal("5"), Decimal("3200.00")),
        ],
    )
    img = _render_scan_image(inv)
    img = img.resize((int(img.width * 0.9), int(img.height * 0.9)), Image.Resampling.LANCZOS)
    jpeg = _encode_jpeg(img, quality=85)
    return build_image_pdf(jpeg, img.width, img.height)


def _low_quality_photo_jpg() -> bytes:
    inv = _build_invoice(
        supplier_name="ФОП Гончаренко Тарас Миколайович",
        supplier_tax_id="30112357",
        supplier_address="м. Харків, просп. Гагаріна, 15",
        buyer_name="ТОВ «Ветра Опт»",
        buyer_tax_id="3211500016",
        buyer_address="м. Полтава, вул. Соборності, 44",
        invoice_number="ФО-0092",
        invoice_date=date.today() - timedelta(days=5),
        items=[
            _Item("Овочі свіжі, ящик", Decimal("15"), Decimal("320.00")),
            _Item("Фрукти сезонні, ящик", Decimal("10"), Decimal("410.00")),
        ],
    )
    img = _render_scan_image(inv)
    # Phone-photo stand-in: downscale, slight rotation, sensor-noise jitter,
    # then a heavier JPEG compression pass than the "good scan" fixture.
    img = img.resize((int(img.width * 0.6), int(img.height * 0.6)), Image.Resampling.LANCZOS)
    img = img.rotate(3.5, expand=True, fillcolor=(235, 230, 220))
    img = _add_noise(img, amount=18, rng=random.Random(42))
    return _encode_jpeg(img, quality=45)


def _multi_page_pdf() -> bytes:
    inv = _build_invoice(
        supplier_name="ТОВ «Технопостач Груп»",
        supplier_tax_id="30112363",
        supplier_address="м. Київ, просп. Перемоги, 67",
        buyer_name="ТОВ «Офіс Плюс»",
        buyer_tax_id="3211500022",
        buyer_address="м. Вінниця, вул. Соборна, 12",
        invoice_number="ТП-1150",
        invoice_date=date.today() - timedelta(days=30),
        items=[
            _Item("Ноутбук Lenovo ThinkPad E14", Decimal("5"), Decimal("31000.00")),
            _Item("Монітор LG 27 UltraFine", Decimal("5"), Decimal("9800.00")),
            _Item("Док-станція USB-C", Decimal("5"), Decimal("2400.00")),
            _Item("Миша бездротова Logitech", Decimal("10"), Decimal("650.00")),
            _Item("Клавіатура механічна", Decimal("10"), Decimal("1450.00")),
            _Item("Гарнітура з мікрофоном", Decimal("10"), Decimal("980.00")),
            _Item("Кабель HDMI 2м", Decimal("15"), Decimal("220.00")),
            _Item("Подовжувач мережевий 5м", Decimal("8"), Decimal("340.00")),
        ],
    )
    return _render_text_pdf(inv, page_break_after_item=5)


def _arithmetic_error_pdf() -> bytes:
    inv = _build_invoice(
        supplier_name="ТОВ «ДокФлоу Демо Помилка»",
        supplier_tax_id="38492069",
        supplier_address="м. Київ, вул. Хрещатик, 22",
        buyer_name="ФОП Мельник Ірина Сергіївна",
        buyer_tax_id="3012415678",
        buyer_address="м. Львів, вул. Личаківська, 5",
        invoice_number="ДЕМО-0005",
        invoice_date=date.today() - timedelta(days=3),
        items=[
            _Item("Ноутбук Dell Latitude 5540", Decimal("1"), Decimal("28000.00")),
            _Item('Монітор Dell 24"', Decimal("2"), Decimal("6200.00")),
            _Item("Клавіатура бездротова Logitech", Decimal("3"), Decimal("650.00")),
        ],
        # subtotal 42350.00, correct total 50820.00 — the document states a
        # total 250.00 higher, deliberately tripping T6's total_mismatch check.
        total_override=Decimal("51070.00"),
    )
    return _render_text_pdf(inv)


_FIXTURE_BUILDERS: dict[str, Any] = {
    "clean_text": _clean_text_pdf,
    "good_scan": _good_scan_pdf,
    "low_quality_photo": _low_quality_photo_jpg,
    "multi_page": _multi_page_pdf,
    "arithmetic_error": _arithmetic_error_pdf,
}


def _content_type_for(filename: str) -> str:
    return "application/pdf" if filename.endswith(".pdf") else "image/jpeg"


def _snapshot_path(spec: DemoDocSpec) -> Path:
    return SNAPSHOT_DIR / f"{spec.key}.json"


def _write_snapshot(spec: DemoDocSpec, extraction_row: dict[str, Any]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "payload": extraction_row["payload"],
        "field_confidences": extraction_row["field_confidences"],
        "validation_issues": extraction_row["validation_issues"],
    }
    _snapshot_path(spec).write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _seed_one(
    spec: DemoDocSpec,
    *,
    documents: DocumentsRepo,
    extractions: ExtractionsRepo,
    storage: StorageRepo,
) -> None:
    content = _FIXTURE_BUILDERS[spec.key]()
    storage_path = build_storage_path(
        user_id=DEMO_USER_ID, document_id=spec.document_id, filename=spec.filename
    )
    storage.upload(path=storage_path, data=content, content_type=_content_type_for(spec.filename))
    documents.create(
        document_id=spec.document_id,
        user_id=DEMO_USER_ID,
        filename=spec.filename,
        storage_path=storage_path,
    )
    documents.set_status(document_id=spec.document_id, status="processing")
    try:
        preprocessed = preprocess(content)
        service = ExtractionService(llm=create_docflow_llm(component="demo-seed"))
        service.extract(document_id=spec.document_id, doc=preprocessed)
    except Exception as error:
        documents.mark_failed(document_id=spec.document_id, error=f"demo seed failed: {error}")
        raise
    documents.mark_reviewable(
        document_id=spec.document_id, mode=preprocessed.mode, pages=preprocessed.pages
    )

    row = extractions.get_latest_by_document(spec.document_id)
    assert row is not None, "extraction row must exist right after ExtractionService.extract"
    _write_snapshot(spec, row)
    print(
        f"[seed] {spec.key}: done — mode={preprocessed.mode} pages={preprocessed.pages} "
        f"model={row.get('model')} cost_usd={row.get('cost_usd')} "
        f"validation_issues={len(row.get('validation_issues') or [])}"
    )


def _reset_one(
    spec: DemoDocSpec, *, documents: DocumentsRepo, extractions: ExtractionsRepo
) -> None:
    path = _snapshot_path(spec)
    if not path.exists():
        print(f"[reset] {spec.key}: never seeded (no snapshot) — skipping")
        return
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    extraction_row = extractions.get_latest_by_document(spec.document_id)
    if extraction_row is None:
        print(f"[reset] {spec.key}: document has no extraction row — skipping")
        return
    extractions.update_after_edit(
        extraction_row["id"],
        payload=snapshot["payload"],
        field_confidences=snapshot["field_confidences"],
        validation_issues=snapshot["validation_issues"],
    )
    documents.set_status(document_id=spec.document_id, status="review")
    print(f"[reset] {spec.key}: restored to pristine extraction, status=review")


def seed(
    *,
    reset: bool,
    documents: DocumentsRepo | None = None,
    extractions: ExtractionsRepo | None = None,
    storage: StorageRepo | None = None,
) -> None:
    """Seed (or --reset) all 5 demo documents.

    Repos are injectable so `tests/test_seed_demo.py` can exercise the
    idempotency/reset orchestration with fakes, never touching real
    Supabase/Anthropic (CLAUDE.md testing conventions); real runs get the
    default real-client repos.
    """
    documents = documents if documents is not None else DocumentsRepo()
    extractions = extractions if extractions is not None else ExtractionsRepo()
    storage = storage if storage is not None else StorageRepo()

    if reset:
        for spec in DEMO_DOCUMENTS:
            _reset_one(spec, documents=documents, extractions=extractions)
        return

    storage.ensure_bucket()
    for spec in DEMO_DOCUMENTS:
        existing = documents.get_by_id(spec.document_id)
        if existing is not None:
            print(f"[skip] {spec.key}: already seeded (status={existing['status']})")
            continue
        print(f"[seed] {spec.key}: generating fixture + running the real pipeline...")
        _seed_one(spec, documents=documents, extractions=extractions, storage=storage)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="restore all seeded demo docs to their pristine snapshot (no LLM calls)",
    )
    args = parser.parse_args()
    seed(reset=args.reset)


if __name__ == "__main__":
    main()
