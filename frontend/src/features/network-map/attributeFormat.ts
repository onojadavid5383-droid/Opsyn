// ============================================================
// OPSYN NETWORK MAP — attribute formatting and draft helpers (pure).
// Used by AttributeFields.tsx; the specs come from GET /network/catalogue.
// ============================================================

import type { NetFieldSpec } from '@shared';

// Industry acronyms stay in capitals: ADSS stays ADSS, SC_APC becomes "SC APC"
const ACRONYMS = new Set(['ADSS', 'SDU', 'MDU', 'WDM', 'CWDM', 'DWDM', 'SC', 'LC', 'APC', 'UPC', 'PCC', 'PON', 'POP', 'ODF', 'OLT', 'FDT', 'FAT', 'ONU']);

/** CAST_IRON → Cast iron; keeps acronyms, ratios, codes and mixed-case values as written. */
export function humaniseOption(v: string): string {
  if (!/^[A-Z0-9_]+$/.test(v) || /\d:\d/.test(v)) return v;
  return v.split('_').map((w, i) => {
    if (ACRONYMS.has(w)) return w;
    const lower = w.toLowerCase();
    return i === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
  }).join(' ');
}

export function humaniseKey(key: string): string {
  const t = key.replace(/_/g, ' ');
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function formatField(spec: NetFieldSpec, v: unknown): string {
  if (v === null || v === undefined || v === '') return 'Not recorded';
  if (spec.kind === 'bool') return v ? 'Yes' : 'No';
  if (spec.kind === 'enum') return humaniseOption(String(v));
  if (spec.kind === 'number' || spec.kind === 'int') return `${v}${spec.unit ? ` ${spec.unit}` : ''}`;
  return String(v);
}

export function formatRaw(v: unknown): string {
  if (v === null || v === undefined || v === '') return 'Not recorded';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

/** Upload-era references are shown as links elsewhere, not as raw details. */
export const isHiddenKey = (k: string) => k.startsWith('legacy_');

/** Draft values are strings (what inputs hold); the server coerces them. */
export type Draft = Record<string, string>;

export function toDraft(specs: NetFieldSpec[], values: Record<string, unknown>): Draft {
  const d: Draft = {};
  for (const f of specs) {
    const v = values[f.key];
    d[f.key] = v === null || v === undefined ? '' : f.kind === 'bool' ? (v ? 'true' : 'false') : String(v);
  }
  return d;
}

/**
 * Apply a draft onto the stored attributes: known fields take the draft
 * (blank = remove), everything else is kept exactly as it was. Untouched
 * fields go back exactly as stored, because the server only re-checks
 * values that changed.
 */
export function mergeDraft(specs: NetFieldSpec[], stored: Record<string, unknown>, draft: Draft): Record<string, unknown> {
  const out: Record<string, unknown> = { ...stored };
  for (const f of specs) {
    const raw = (draft[f.key] ?? '').trim();
    if (raw === '') { delete out[f.key]; continue; }
    const before = stored[f.key];
    if (before !== undefined && before !== null && toDraft([f], stored)[f.key] === raw) { out[f.key] = before; continue; }
    out[f.key] = f.kind === 'bool' ? raw === 'true' : raw;
  }
  return out;
}
