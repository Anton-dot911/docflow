import type { FlagSeverity } from "../state/flags.ts";
import { FieldEditBody } from "./FieldEditBody.tsx";

export interface FieldProps {
  path: string;
  label: string;
  displayValue: string;
  rawValue: string;
  severity: FlagSeverity;
  confidencePercent: number;
  issueMessage: string | null;
  sourceSnippet: string | null;
  showSnippetDrawer: boolean;
  isOpen: boolean;
  isPending: boolean;
  onToggle: () => void;
  onSubmitEdit: (newValue: string) => void;
  onAcceptAsIs: () => void;
}

// One review field per UI_SPEC §1/§3: green renders collapsed and inert; amber
// gets a single "Підтвердити <value>" accept-as-is action; red additionally
// gets an editable input plus "Прийняти як є" and always shows the T6 issue
// message verbatim.
export function Field({
  path,
  label,
  displayValue,
  rawValue,
  severity,
  confidencePercent,
  issueMessage,
  sourceSnippet,
  showSnippetDrawer,
  isOpen,
  isPending,
  onToggle,
  onSubmitEdit,
  onAcceptAsIs,
}: FieldProps) {
  const resolved = severity === "ok";
  const stateClass =
    severity === "err" ? "rv-field--err" : severity === "warn" ? "rv-field--warn" : "";

  const confidenceText = resolved
    ? `✓ впевненість ${confidencePercent}%`
    : severity === "warn"
      ? `впевненість ${confidencePercent}% — перевірте фрагмент`
      : "перевірка арифметики/формату не пройдена";

  return (
    <div
      id={fieldDomId(path)}
      className={`rv-field ${stateClass} ${isOpen ? "rv-field--open" : ""}`}
    >
      {resolved ? (
        <div className="rv-field__row">
          <span className="rv-field__label">{label}</span>
          <span className="rv-field__value">{displayValue}</span>
        </div>
      ) : (
        <button
          type="button"
          className="rv-field__row"
          onClick={onToggle}
          aria-expanded={isOpen}
          onKeyDown={(event) => {
            // Guided review (UI_SPEC §3.3): Enter confirms the focused field
            // as-is; Escape closes it; any other printable key opens it so
            // typing continues straight into the edit input.
            if (event.key === "Enter") {
              event.preventDefault();
              onAcceptAsIs();
            } else if (event.key === "Escape" && isOpen) {
              onToggle();
            } else if (!isOpen && event.key.length === 1 && !event.ctrlKey && !event.metaKey) {
              onToggle();
            }
          }}
        >
          <span className="rv-field__label">{label}</span>
          <span className="rv-field__value">{displayValue}</span>
        </button>
      )}
      <div className="rv-field__conf">{confidenceText}</div>

      {isOpen && severity !== "ok" && (
        <FieldEditBody
          label={label}
          displayValue={displayValue}
          rawValue={rawValue}
          severity={severity}
          issueMessage={issueMessage}
          sourceSnippet={sourceSnippet}
          showSnippetDrawer={showSnippetDrawer}
          isPending={isPending}
          onSubmitEdit={onSubmitEdit}
          onAcceptAsIs={onAcceptAsIs}
        />
      )}
    </div>
  );
}

export function fieldDomId(path: string): string {
  return `field-${path.replace(/[[\].]/g, "-")}`;
}
