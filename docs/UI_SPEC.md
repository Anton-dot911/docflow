# DocFlow Review UI — Spec for T7

Source of truth for visuals: `docs/mockups/review.html` (the approved interactive
mockup — commit it to the repo). This spec distills its FINAL tokens and behavior;
the mockup's CSS contains layered iterations and must NOT be copy-pasted as-is.
Implement from tokens below; when the mockup and this spec disagree on values,
this spec wins.

## 1. Design tokens

Implement as CSS variables on `body`, switched via `data-theme="light|dark"`.

| Token | Light | Dark |
|---|---|---|
| bg | #eef2f7 (+subtle top radial indigo tint) | #050816 (violet/cyan radial tints) |
| surface | #ffffff | #101827 |
| surface-2 | #e7ecf4 | #162033 |
| surface-3 | #dfe6ef | #243047 |
| line | #cfd8e5 | #26354f |
| line-strong | #aeb8c8 | #42526d |
| ink (headings/values) | #0f172a | #f8fafc |
| text | #334155 | #d7deea |
| muted | #64748b | #9aa8bb |
| accent (primary action) | #111827 (hover #0b1220) | gradient #8b5cf6 → #2563eb (hover #7c3aed → #1d4ed8) |
| accent-fg | #ffffff | #ffffff |
| amber / bg / line | #b7791f / #fff8e7 / #f2d596 | #fbbf24 / #241b08 / #a87512 |
| red / bg / line | #dc2626 / #fff1f2 / #fecdd3 | #fb7185 / #251019 / #9f2e46 |
| green / bg / line | #15803d / #ecfdf3 / #bbf7d0 | #4ade80 / #0d2116 / #2d7d49 |

**Document ("scan paper") tokens — theme-independent rule: the scanned document
is ALWAYS light paper, even in dark theme.**

| Token | Light | Dark |
|---|---|---|
| scan-frame bg | #e5ebf5 → #d8e1ee | #151f35 → #08101f (violet tint) |
| scan-frame line | #b6c4d6 | rgba(139,92,246,.42) |
| scan-paper bg | #ffffff → #fbfdff | #ffffff → #f3f7fb (stays white) |
| scan-paper ink/text | #111827 / #334155 | same (paper is light in both) |
| scan accent (kicker/chip) | #2563eb | #a78bfa |

Typography: system stack `-apple-system, "SF Pro Text", Inter, "Segoe UI", Roboto,
sans-serif`; mono `"SF Mono", "Roboto Mono", ui-monospace, Menlo`. Headings
tight (-.025em). Kickers/section labels: 10–12px, 800, uppercase, letter-spacing
.12–.16em, muted color. No decorative serif in the product (mockup evolved past it).

Shape & depth: radius 18–24px cards, 999px pills; layered soft shadows per theme;
document card sits inside a "scan frame" with a slight −.45deg rotation, dashed
inner border, and a "СКАН / ФОТО" pill + source chip ("Фото · Viber").

`color-scheme` must be explicitly managed (`light dark` + data-theme), never left
to browser auto-darkening — verified failure mode on iOS webviews.

## 2. Layout

- Desktop (≥880px): two panes — document 55% left (sticky), form 45% right.
  Header fixed above both: filename, source, status badge, attention counter,
  Confirm button.
- Mobile: vertical stack — header, counter strip, scan frame (document),
  fields list, sticky bottom bar (Next field / Confirm). This is exactly the
  mockup's layout.

## 3. Interaction spec (binding decisions)

1. **Confidence threshold 0.85** (`settings.REVIEW_THRESHOLD`): below → amber
   field; validation issue → red field. Green fields render collapsed (label,
   value, one confidence line).
2. **Panel linking is click-driven, not hover:** clicking a flagged field
   scrolls/centers the matching source fragment in the document and highlights
   it (amber/red per severity); mobile expands an inline "фрагмент документа"
   drawer inside the field instead. Hover may pre-highlight only.
3. **Guided review:** "Next field" button and Tab jump ONLY across unresolved
   flagged fields. Enter confirms the focused field (confidence → 1.0,
   highlight cleared, review_log written via PATCH). Typing switches to edit.
4. **Red fields cannot be confirmed as-is silently:** they require either an
   edited value or an explicit "Прийняти як є" action; the validation reason
   text is always shown (e.g. "позиції дають 14 460, у документі 14 640").
5. **Line items render as a table** (not stacked fields); cell-level highlight
   for flagged amounts.
6. **All-green state:** full form still shown; counter strip switches to the
   success message and the Confirm button becomes enabled/primary. Confirm →
   POST /confirm, badge switches to "підтверджено", success toast.
7. Every field edit fires PATCH /api/extractions/{id} {field_path, new_value}
   (writes review_log); Confirm only after zero unresolved flags or explicit
   accepts.

## 4. Accessibility & robustness

- Theme switch: radio inputs + labels (role=radiogroup, aria-checked), JS sets
  `data-theme`; CSS `:has()` fallback keeps it functional without JS.
- prefers-reduced-motion: disable transitions.
- Keyboard: full guided flow operable without mouse (Tab/Enter/Escape closes
  fragment drawer).
- Touch targets ≥44px on mobile; safe-area padding on the bottom bar.

## 5. Out of scope for T7

Auth UI, history page polish beyond T8, PDF.js virtualization for 100-page
documents (render first 20 pages, matching the T3 cap).
