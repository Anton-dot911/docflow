// Pure text-layer search: locate which text-layer item(s) a source_snippet
// falls within, given the flat list of item strings pdf.js's TextLayer
// exposes as `textContentItemsStr`. Kept separate from the DOM-touching
// pdf.js integration (DocumentPane) so the matching logic is unit-testable.

export function normalizeText(text: string): string {
  return text.replace(/\s+/g, " ").trim().toLowerCase();
}

export function findSnippetItemIndices(itemTexts: string[], snippet: string): number[] | null {
  const needle = normalizeText(snippet);
  if (!needle) return null;

  const offsets: { start: number; end: number }[] = [];
  let joined = "";
  for (const item of itemTexts) {
    const normalized = normalizeText(item);
    const start = joined.length === 0 ? 0 : joined.length + 1;
    joined = joined.length === 0 ? normalized : `${joined} ${normalized}`;
    offsets.push({ start, end: start + normalized.length });
  }

  const matchStart = joined.indexOf(needle);
  if (matchStart === -1) return null;
  const matchEnd = matchStart + needle.length;

  const indices = offsets
    .map((offset, i) => ({ offset, i }))
    .filter(({ offset }) => offset.end > matchStart && offset.start < matchEnd)
    .map(({ i }) => i);
  return indices.length > 0 ? indices : null;
}
