import { Fragment } from "react";
import type { LineItem } from "../api/schemas.ts";
import type { FieldFlag, FlagSeverity } from "../state/flags.ts";
import { formatMoney } from "../state/format.ts";
import { FieldEditBody } from "./FieldEditBody.tsx";
import { fieldDomId } from "./Field.tsx";

interface ItemsTableProps {
  items: LineItem[];
  // "items" for an invoice, "services" for an act (T10) — picks the dot-path
  // prefix so generated paths ("items[0].amount" / "services[0].amount")
  // match the backend's FieldConfidence/ValidationIssue paths.
  pathPrefix: "items" | "services";
  flagByPath: Map<string, FieldFlag>;
  openPath: string | null;
  pendingPath: string | null;
  showSnippetDrawer: boolean;
  onToggle: (path: string) => void;
  onSubmitEdit: (path: string, newValue: string) => void;
  onAcceptAsIs: (path: string) => void;
}

function cellClass(severity: FlagSeverity | undefined): string {
  if (severity === "err") return "rv-num rv-cell--err";
  if (severity === "warn") return "rv-num rv-cell--warn";
  return "rv-num";
}

// Line items render as a table (UI_SPEC §3.5) with cell-level flags; a
// flagged cell is clickable and opens the same edit/accept-as-is affordance
// as a scalar field, in an expansion row directly under it.
export function ItemsTable({
  items,
  pathPrefix,
  flagByPath,
  openPath,
  pendingPath,
  showSnippetDrawer,
  onToggle,
  onSubmitEdit,
  onAcceptAsIs,
}: ItemsTableProps) {
  return (
    <div className="rv-items">
      <table>
        <thead>
          <tr>
            <th>Назва</th>
            <th style={{ textAlign: "right" }}>К-сть</th>
            <th style={{ textAlign: "right" }}>Ціна</th>
            <th style={{ textAlign: "right" }}>Сума</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => {
            const amountPath = `${pathPrefix}[${index}].amount`;
            const amountFlag = flagByPath.get(amountPath);
            const isOpen = openPath === amountPath;
            return (
              <Fragment key={amountPath}>
                <tr id={fieldDomId(amountPath)}>
                  <td>{item.name ?? "—"}</td>
                  <td className="rv-num">{item.quantity ?? "—"}</td>
                  <td className="rv-num">{item.unit_price ?? "—"}</td>
                  <td className={cellClass(amountFlag?.severity)}>
                    {amountFlag && amountFlag.severity !== "ok" ? (
                      <button
                        type="button"
                        onClick={() => onToggle(amountPath)}
                        style={{
                          background: "none",
                          border: 0,
                          font: "inherit",
                          color: "inherit",
                          cursor: "pointer",
                          minHeight: 44,
                        }}
                      >
                        {formatMoney(item.amount)}
                      </button>
                    ) : (
                      formatMoney(item.amount)
                    )}
                  </td>
                </tr>
                {isOpen && amountFlag && amountFlag.severity !== "ok" && (
                  <tr>
                    <td colSpan={4} style={{ borderTop: "none" }}>
                      <div className={`rv-field rv-field--${amountFlag.severity}`}>
                        <FieldEditBody
                          label={`Позиція ${index + 1} · Сума`}
                          displayValue={formatMoney(item.amount)}
                          rawValue={item.amount ?? ""}
                          severity={amountFlag.severity}
                          issueMessage={amountFlag.issue?.message ?? null}
                          sourceSnippet={amountFlag.sourceSnippet}
                          showSnippetDrawer={showSnippetDrawer}
                          isPending={pendingPath === amountPath}
                          onSubmitEdit={(value) => onSubmitEdit(amountPath, value)}
                          onAcceptAsIs={() => onAcceptAsIs(amountPath)}
                        />
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
