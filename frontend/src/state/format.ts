// Display formatting for InvoiceData fields — presentation only, never used
// for the value sent back in a PATCH (that always goes through the raw
// string form, see reviewReducer/fieldPath).

export function formatMoney(raw: string | null): string {
  if (raw === null) return "—";
  const value = Number(raw);
  if (Number.isNaN(value)) return raw;
  return `₴ ${value.toLocaleString("uk-UA", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatDate(raw: string | null): string {
  if (raw === null) return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  if (!match) return raw;
  const [, year, month, day] = match;
  return `${day}.${month}.${year}`;
}

export function formatPlain(raw: string | null): string {
  return raw === null ? "—" : raw;
}

const LABELS: Record<string, string> = {
  "supplier.name": "Постачальник",
  "supplier.tax_id": "ЄДРПОУ/ІПН постачальника",
  "supplier.address": "Адреса постачальника",
  "buyer.name": "Покупець",
  "buyer.tax_id": "ЄДРПОУ/ІПН покупця",
  "buyer.address": "Адреса покупця",
  invoice_number: "Номер накладної",
  invoice_date: "Дата",
  subtotal: "Разом без ПДВ",
  vat_amount: "ПДВ",
  total: "До сплати",
};

const ITEM_LEAF_LABELS: Record<string, string> = {
  name: "Назва",
  quantity: "К-сть",
  unit_price: "Ціна",
  amount: "Сума",
};

const ITEM_PATH_RE = /^items\[(\d+)]\.(\w+)$/;

export function fieldLabel(path: string): string {
  const known = LABELS[path];
  if (known) return known;
  const match = ITEM_PATH_RE.exec(path);
  if (match) {
    const [, index, leaf] = match;
    const leafLabel = (leaf && ITEM_LEAF_LABELS[leaf]) || leaf;
    return `Позиція ${Number(index) + 1} · ${leafLabel}`;
  }
  return path;
}
