import { isInvoicePayload, type ExtractionDetail } from "../api/schemas.ts";
import type { FieldFlag } from "../state/flags.ts";
import { fieldLabel, formatDate, formatMoney, formatPlain } from "../state/format.ts";
import { Field } from "./Field.tsx";
import { ItemsTable } from "./ItemsTable.tsx";

interface ScalarSpec {
  path: string;
  raw: string | null;
  formatter: (raw: string | null) => string;
}

// Schema-driven per doc_type (T10): an invoice's scalar fields are
// supplier/buyer/invoice_number/invoice_date; an act's are the mirrored
// contractor/customer/act_number/act_date. subtotal/vat_amount/total are
// shared by both shapes.
function scalarFields(extraction: ExtractionDetail): ScalarSpec[] {
  const { payload } = extraction;
  if (isInvoicePayload(payload)) {
    return [
      { path: "supplier.name", raw: payload.supplier.name, formatter: formatPlain },
      { path: "supplier.tax_id", raw: payload.supplier.tax_id, formatter: formatPlain },
      { path: "supplier.address", raw: payload.supplier.address, formatter: formatPlain },
      { path: "buyer.name", raw: payload.buyer.name, formatter: formatPlain },
      { path: "buyer.tax_id", raw: payload.buyer.tax_id, formatter: formatPlain },
      { path: "buyer.address", raw: payload.buyer.address, formatter: formatPlain },
      { path: "invoice_number", raw: payload.invoice_number, formatter: formatPlain },
      { path: "invoice_date", raw: payload.invoice_date, formatter: formatDate },
      { path: "subtotal", raw: payload.subtotal, formatter: formatMoney },
      { path: "vat_amount", raw: payload.vat_amount, formatter: formatMoney },
      { path: "total", raw: payload.total, formatter: formatMoney },
    ];
  }
  return [
    { path: "contractor.name", raw: payload.contractor.name, formatter: formatPlain },
    { path: "contractor.tax_id", raw: payload.contractor.tax_id, formatter: formatPlain },
    { path: "contractor.address", raw: payload.contractor.address, formatter: formatPlain },
    { path: "customer.name", raw: payload.customer.name, formatter: formatPlain },
    { path: "customer.tax_id", raw: payload.customer.tax_id, formatter: formatPlain },
    { path: "customer.address", raw: payload.customer.address, formatter: formatPlain },
    { path: "act_number", raw: payload.act_number, formatter: formatPlain },
    { path: "act_date", raw: payload.act_date, formatter: formatDate },
    { path: "subtotal", raw: payload.subtotal, formatter: formatMoney },
    { path: "vat_amount", raw: payload.vat_amount, formatter: formatMoney },
    { path: "total", raw: payload.total, formatter: formatMoney },
  ];
}

interface FieldsPaneProps {
  extraction: ExtractionDetail;
  flags: FieldFlag[];
  openPath: string | null;
  pendingPath: string | null;
  showSnippetDrawer: boolean;
  onToggle: (path: string) => void;
  onSubmitEdit: (path: string, newValue: string) => void;
  onAcceptAsIs: (path: string) => void;
}

export function FieldsPane({
  extraction,
  flags,
  openPath,
  pendingPath,
  showSnippetDrawer,
  onToggle,
  onSubmitEdit,
  onAcceptAsIs,
}: FieldsPaneProps) {
  const flagByPath = new Map(flags.map((f) => [f.path, f]));

  return (
    <div>
      <span className="rv-section-label">Розпізнані поля</span>
      {scalarFields(extraction).map(({ path, raw, formatter }) => {
        const flag = flagByPath.get(path);
        if (!flag) return null;
        return (
          <Field
            key={path}
            path={path}
            label={fieldLabel(path)}
            displayValue={formatter(raw)}
            rawValue={raw ?? ""}
            severity={flag.severity}
            confidencePercent={Math.round(flag.confidence * 100)}
            issueMessage={flag.issue?.message ?? null}
            sourceSnippet={flag.sourceSnippet}
            showSnippetDrawer={showSnippetDrawer}
            isOpen={openPath === path}
            isPending={pendingPath === path}
            onToggle={() => onToggle(path)}
            onSubmitEdit={(value) => onSubmitEdit(path, value)}
            onAcceptAsIs={() => onAcceptAsIs(path)}
          />
        );
      })}

      <span className="rv-section-label">Позиції</span>
      <ItemsTable
        items={
          isInvoicePayload(extraction.payload)
            ? extraction.payload.items
            : extraction.payload.services
        }
        pathPrefix={isInvoicePayload(extraction.payload) ? "items" : "services"}
        flagByPath={flagByPath}
        openPath={openPath}
        pendingPath={pendingPath}
        showSnippetDrawer={showSnippetDrawer}
        onToggle={onToggle}
        onSubmitEdit={onSubmitEdit}
        onAcceptAsIs={onAcceptAsIs}
      />
    </div>
  );
}
