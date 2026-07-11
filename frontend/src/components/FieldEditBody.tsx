import { useState } from "react";
import type { FlagSeverity } from "../state/flags.ts";

export interface FieldEditBodyProps {
  label: string;
  displayValue: string;
  rawValue: string;
  severity: Exclude<FlagSeverity, "ok">;
  issueMessage: string | null;
  sourceSnippet: string | null;
  showSnippetDrawer: boolean;
  isPending: boolean;
  onSubmitEdit: (newValue: string) => void;
  onAcceptAsIs: () => void;
}

// Shared "open" body for an unresolved field — reason, snippet drawer,
// edit input (red only) and actions. Used by both the scalar Field row and
// the line-items table's per-cell expansion (UI_SPEC §3.4/§3.5).
export function FieldEditBody({
  label,
  displayValue,
  rawValue,
  severity,
  issueMessage,
  sourceSnippet,
  showSnippetDrawer,
  isPending,
  onSubmitEdit,
  onAcceptAsIs,
}: FieldEditBodyProps) {
  // Each field/cell's edit body only mounts while that one field is open (see
  // Field/ItemsTable), so `rawValue` at mount time is always the current one —
  // no effect needed to keep `draft` in sync with prop changes.
  const [draft, setDraft] = useState(rawValue);

  return (
    <>
      {severity === "err" && issueMessage && <div className="rv-field__reason">{issueMessage}</div>}
      {showSnippetDrawer && sourceSnippet && (
        <div className="rv-field__snippet">
          <div>{sourceSnippet}</div>
        </div>
      )}
      {severity === "err" && (
        <input
          className="rv-field__input"
          value={draft}
          disabled={isPending}
          autoFocus
          aria-label={`Виправлене значення для ${label}`}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              onSubmitEdit(draft);
            }
          }}
        />
      )}
      <div className="rv-field__actions">
        {severity === "err" ? (
          <>
            <button
              type="button"
              className="rv-btn"
              disabled={isPending}
              onClick={() => onSubmitEdit(draft)}
            >
              Зберегти виправлення
            </button>
            <button
              type="button"
              className="rv-btn rv-btn--ghost"
              disabled={isPending}
              onClick={onAcceptAsIs}
            >
              Прийняти як є
            </button>
          </>
        ) : (
          <button type="button" className="rv-btn" disabled={isPending} onClick={onAcceptAsIs}>
            Підтвердити {displayValue}
          </button>
        )}
      </div>
    </>
  );
}
