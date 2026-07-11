// Dot-path get/set over an InvoiceData-shaped payload, mirroring
// backend/app/services/field_path.py so optimistic edits in the reducer apply
// the same "items[2].amount" / "supplier.tax_id" / "total" paths the API uses.

export class FieldPathError extends Error {}

type Segment = { name: string; index: number | null };

const SEGMENT_RE = /^([^.[\]]+)(\[(\d+)\])?$/;

function tokenize(path: string): Segment[] {
  if (!path) throw new FieldPathError("field_path must not be empty");
  return path.split(".").map((part) => {
    const match = SEGMENT_RE.exec(part);
    const name = match?.[1];
    if (!match || name === undefined) {
      throw new FieldPathError(`malformed field_path segment: ${part}`);
    }
    return { name, index: match[3] !== undefined ? Number(match[3]) : null };
  });
}

type Node = Record<string, unknown> | unknown[];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// Read the current raw value at `path` — used for "Прийняти як є" (accept as
// is), which PATCHes the field's own current value unchanged.
export function getFieldValue(payload: Record<string, unknown>, path: string): unknown {
  let node: unknown = payload;
  for (const { name, index } of tokenize(path)) {
    if (!isRecord(node) || !(name in node)) {
      throw new FieldPathError(`field_path ${path} does not resolve: missing ${name}`);
    }
    node = node[name];
    if (index !== null) {
      if (!Array.isArray(node) || index >= node.length) {
        throw new FieldPathError(
          `field_path ${path} does not resolve: index ${index} out of range`,
        );
      }
      node = node[index];
    }
  }
  return node;
}

export function setFieldValue(
  payload: Record<string, unknown>,
  path: string,
  value: unknown,
): Record<string, unknown> {
  const result = structuredClone(payload);
  const tokens = tokenize(path);
  let node: Node = result;
  tokens.forEach(({ name, index }, i) => {
    const isLast = i === tokens.length - 1;
    if (!isRecord(node) || !(name in node)) {
      throw new FieldPathError(`field_path ${path} does not resolve: missing ${name}`);
    }
    if (index !== null) {
      const container = node[name];
      if (!Array.isArray(container) || index >= container.length) {
        throw new FieldPathError(
          `field_path ${path} does not resolve: index ${index} out of range`,
        );
      }
      if (isLast) {
        container[index] = value;
      } else {
        node = container[index] as Node;
      }
    } else if (isLast) {
      node[name] = value;
    } else {
      node = node[name] as Node;
    }
  });
  return result;
}
