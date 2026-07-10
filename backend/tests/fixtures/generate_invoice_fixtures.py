"""Generate the committed T5 invoice extraction fixtures. No network.

Run from the backend dir:

    uv run python tests/fixtures/generate_invoice_fixtures.py

Writes two files next to this script, both realistic Ukrainian invoices:

- ``invoice_text.pdf`` — a clean, born-digital PDF with a real (Cyrillic) text
  layer. Drives the T5 *text* mode. This is the fixture the DoD field-accuracy
  target is measured on; its expected values are mirrored in
  ``EXPECTED_INVOICE_TEXT`` below and in ``tests/test_extract_smoke.py``.
- ``invoice_scan.jpg`` — a rasterized invoice saved as a mildly degraded JPEG,
  standing in for a scan/photo. A JPG upload always routes to T5 *vision* mode.

fpdf2 (dev-only dependency) renders the text PDF because the stdlib/other deps
cannot emit a Cyrillic text layer that pypdfium2 can extract; Pillow rasterizes
the scan. Both embed DejaVuSans for full Cyrillic coverage. Bytes are
regenerated deterministically, so the committed fixtures can always be
reproduced.
"""

from __future__ import annotations

import io
import os
from typing import Any

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# --- Canonical clean invoice (text PDF) -------------------------------------
# Expected extraction, mirrored by the smoke test's field-by-field check. The
# arithmetic is internally consistent (qty*price=amount; sum=subtotal;
# subtotal+vat=total) so it also reads as a genuine invoice.
EXPECTED_INVOICE_TEXT: dict[str, Any] = {
    "supplier": {
        "name": "ТОВ «Технопостач»",
        "tax_id": "38492067",
        "address": "м. Київ, вул. Промислова, 15, оф. 204",
    },
    "buyer": {
        "name": "ФОП Коваленко Олена Петрівна",
        "tax_id": "3012415678",
        "address": "м. Харків, просп. Науки, 47, кв. 12",
    },
    "invoice_number": "РФ-2024/0317",
    "invoice_date": "2024-04-17",
    "items": [
        {
            "name": "Ноутбук Lenovo ThinkPad",
            "quantity": "3",
            "unit_price": "32500.00",
            "amount": "97500.00",
        },
        {
            "name": "Миша бездротова Logitech",
            "quantity": "3",
            "unit_price": "850.00",
            "amount": "2550.00",
        },
        {"name": "Кабель HDMI, 2 м", "quantity": "5", "unit_price": "220.00", "amount": "1100.00"},
    ],
    "subtotal": "101150.00",
    "vat_amount": "20230.00",
    "total": "121380.00",
}

# --- Scan invoice (vision) — a different, simpler document ------------------
_SCAN_LINES: list[str] = [
    "ТОВ «Будмайстер»",
    "ЄДРПОУ 41205839",
    "м. Дніпро, вул. Заводська, 8",
    "",
    "РАХУНОК-ФАКТУРА № 254",
    "від 03.02.2024 р.",
    "",
    "Покупець: ТОВ «Оптторг»",
    "ЄДРПОУ 39587104",
    "м. Запоріжжя, просп. Соборний, 121",
    "",
    "№   Найменування товару        К-сть   Ціна      Сума",
    "1   Цемент М500, мішок           50    145.00    7250.00",
    "2   Пісок будівельний, тонна     10    480.00    4800.00",
    "",
    "Разом без ПДВ:                             12050.00",
    "ПДВ 20%:                                    2410.00",
    "Всього до сплати:                          14460.00",
]


def _build_text_pdf() -> bytes:
    inv = EXPECTED_INVOICE_TEXT
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
    line("від 17 квітня 2024 р.")
    line("")
    line(f"Покупець: {inv['buyer']['name']}")
    line(f"ІПН {inv['buyer']['tax_id']}")
    line(inv["buyer"]["address"])
    line("")
    line("№    Найменування                       К-сть    Ціна        Сума", style="B")
    for i, item in enumerate(inv["items"], start=1):
        line(
            f"{i}    {item['name']:<32} {item['quantity']:>4}    "
            f"{item['unit_price']:>9}   {item['amount']:>10}"
        )
    line("")
    line(f"Разом без ПДВ:                                          {inv['subtotal']}")
    line(f"ПДВ 20%:                                               {inv['vat_amount']}")
    line(f"Всього до сплати:                                      {inv['total']}", style="B")

    return bytes(pdf.output())


def _build_scan_jpeg() -> bytes:
    # A4-ish canvas at ~150 dpi, off-white to read like a scan.
    width, height = 1240, 1754
    img = Image.new("RGB", (width, height), (250, 249, 246))
    draw = ImageDraw.Draw(img)
    title = ImageFont.truetype(FONT_BOLD_PATH, 34)
    body = ImageFont.truetype(FONT_PATH, 28)
    y = 90
    for text in _SCAN_LINES:
        if not text:
            y += 22
            continue
        font = title if ("РАХУНОК" in text or text.startswith("ТОВ")) else body
        draw.text((90, y), text, fill=(20, 20, 20), font=font)
        y += 46
    # Mild degradation: downscale then re-encode as a lower-quality JPEG so it
    # behaves like a real scan rather than a pristine render.
    img = img.resize((int(width * 0.85), int(height * 0.85)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=72)
    return buf.getvalue()


def main() -> None:
    with open(os.path.join(HERE, "invoice_text.pdf"), "wb") as fh:
        fh.write(_build_text_pdf())
    with open(os.path.join(HERE, "invoice_scan.jpg"), "wb") as fh:
        fh.write(_build_scan_jpeg())
    print("wrote invoice_text.pdf, invoice_scan.jpg to", HERE)


if __name__ == "__main__":
    main()
