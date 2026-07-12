"""Generate the committed T10 act extraction + classifier fixtures. No network.

Run from the backend dir:

    uv run python tests/fixtures/generate_act_fixtures.py

Writes three files next to this script:

- ``act_text.pdf`` — a clean, born-digital PDF with a real (Cyrillic) text
  layer: a realistic акт виконаних робіт (act of completed works/services).
  Drives T10's *text* mode extraction; its expected values are mirrored in
  ``EXPECTED_ACT_TEXT`` below and in the classifier/extraction smoke tests.
- ``act_scan.jpg`` — the same act rasterized and saved as a mildly degraded
  JPEG, standing in for a scan/photo. A JPG upload always routes to *vision*
  mode.
- ``other_letter.pdf`` — a personal letter: neither an invoice nor an act, for
  the classifier smoke test's "unrecognized -> other" case.

Mirrors ``generate_invoice_fixtures.py``'s approach: fpdf2 (dev-only
dependency) renders the text PDF because the stdlib/other deps cannot emit a
Cyrillic text layer that pypdfium2 can extract; Pillow rasterizes the scan.
Both embed DejaVuSans for full Cyrillic coverage. Bytes are regenerated
deterministically, so the committed fixtures can always be reproduced.
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

# --- Canonical clean act (text PDF) ------------------------------------------
# Expected extraction, mirrored by the smoke test's field-by-field check. The
# arithmetic is internally consistent (qty*price=amount; sum=subtotal;
# subtotal+vat=total) and both tax ids are checksum-valid (same known-good
# vectors used by generate_invoice_fixtures.py / test_validate.py), so the
# clean fixture produces zero T6 issues.
EXPECTED_ACT_TEXT: dict[str, Any] = {
    "contractor": {
        "name": "ТОВ «Сервіс Плюс»",
        "tax_id": "38492069",
        "address": "м. Дніпро, вул. Європейська, 10",
    },
    "customer": {
        "name": "ТОВ «Мегабуд»",
        "tax_id": "3012415678",
        "address": "м. Одеса, вул. Дерибасівська, 3",
    },
    "act_number": "58",
    "act_date": "2024-04-12",
    "services": [
        {
            "name": "Технічне обслуговування обладнання",
            "quantity": "1",
            "unit_price": "8500.00",
            "amount": "8500.00",
        },
        {
            "name": "Консультаційні послуги",
            "quantity": "4",
            "unit_price": "1200.00",
            "amount": "4800.00",
        },
        {
            "name": "Ремонт мережевого обладнання",
            "quantity": "2",
            "unit_price": "950.00",
            "amount": "1900.00",
        },
    ],
    "subtotal": "15200.00",
    "vat_amount": "3040.00",
    "total": "18240.00",
}


def _build_text_pdf(act: dict[str, Any] = EXPECTED_ACT_TEXT) -> bytes:
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("DejaVu", "", FONT_PATH)
    pdf.add_font("DejaVu", "B", FONT_BOLD_PATH)

    def line(text: str, size: int = 11, style: str = "") -> None:
        pdf.set_font("DejaVu", style, size)
        pdf.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")

    line(f"АКТ № {act['act_number']}", size=13, style="B")
    line("приймання-передачі виконаних робіт (наданих послуг)", size=13, style="B")
    line("від 12 квітня 2024 р.")
    line("")
    line(f"Виконавець: {act['contractor']['name']}")
    line(f"ЄДРПОУ {act['contractor']['tax_id']}")
    line(act["contractor"]["address"])
    line("")
    line(f"Замовник: {act['customer']['name']}")
    line(f"ЄДРПОУ/ІПН {act['customer']['tax_id']}")
    line(act["customer"]["address"])
    line("")
    line("№    Найменування послуги               К-сть    Ціна        Сума", style="B")
    for i, svc in enumerate(act["services"], start=1):
        line(
            f"{i}    {svc['name']:<32} {svc['quantity']:>4}    "
            f"{svc['unit_price']:>9}   {svc['amount']:>10}"
        )
    line("")
    line(f"Разом без ПДВ:                                          {act['subtotal']}")
    line(f"ПДВ 20%:                                               {act['vat_amount']}")
    line(f"Всього:                                                {act['total']}", style="B")
    line("")
    line("Роботи виконано в повному обсязі, претензій сторони не мають.")

    return bytes(pdf.output())


def _act_lines(act: dict[str, Any]) -> list[str]:
    lines = [
        f"АКТ № {act['act_number']} наданих послуг",
        "",
        f"Виконавець: {act['contractor']['name']}",
        f"ЄДРПОУ {act['contractor']['tax_id']}",
        act["contractor"]["address"],
        "",
        f"Замовник: {act['customer']['name']}",
        f"ЄДРПОУ/ІПН {act['customer']['tax_id']}",
        act["customer"]["address"],
        "",
        "№   Найменування послуги          К-сть   Ціна      Сума",
    ]
    for i, svc in enumerate(act["services"], start=1):
        lines.append(
            f"{i}   {svc['name']:<28} {svc['quantity']:>4}   "
            f"{svc['unit_price']:>8}  {svc['amount']:>10}"
        )
    lines += [
        "",
        f"Разом без ПДВ:                            {act['subtotal']}",
        f"ПДВ 20%:                                   {act['vat_amount']}",
        f"Всього:                                    {act['total']}",
    ]
    return lines


def _build_scan_jpeg() -> bytes:
    # A4-ish canvas at ~150 dpi, off-white to read like a scan.
    width, height = 1240, 1754
    img = Image.new("RGB", (width, height), (250, 249, 246))
    draw = ImageDraw.Draw(img)
    title = ImageFont.truetype(FONT_BOLD_PATH, 34)
    body = ImageFont.truetype(FONT_PATH, 28)
    y = 90
    for text in _act_lines(EXPECTED_ACT_TEXT):
        if not text:
            y += 22
            continue
        font = title if text.startswith("АКТ") else body
        draw.text((90, y), text, fill=(20, 20, 20), font=font)
        y += 46
    # Mild degradation: downscale then re-encode as a lower-quality JPEG so it
    # behaves like a real scan rather than a pristine render.
    img = img.resize((int(width * 0.85), int(height * 0.85)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=72)
    return buf.getvalue()


# --- "Other" fixture: a personal letter, neither invoice nor act ------------
_OTHER_LETTER_TEXT = """Привіт, Олено!

Дякую за запрошення на день народження минулих вихідних — було дуже весело.
Наступного тижня я їду до Карпат з друзями, тож напишу, коли повернуся.
Візьми, будь ласка, ту книжку, яку я тобі позичав, якщо вже дочитала.

До зустрічі,
Максим"""


def _build_other_letter_pdf() -> bytes:
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("DejaVu", "", FONT_PATH)
    pdf.set_font("DejaVu", "", 12)
    for line in _OTHER_LETTER_TEXT.split("\n"):
        pdf.cell(0, 7, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def main() -> None:
    with open(os.path.join(HERE, "act_text.pdf"), "wb") as fh:
        fh.write(_build_text_pdf())
    with open(os.path.join(HERE, "act_scan.jpg"), "wb") as fh:
        fh.write(_build_scan_jpeg())
    with open(os.path.join(HERE, "other_letter.pdf"), "wb") as fh:
        fh.write(_build_other_letter_pdf())
    print("wrote act_text.pdf, act_scan.jpg, other_letter.pdf to", HERE)


if __name__ == "__main__":
    main()
