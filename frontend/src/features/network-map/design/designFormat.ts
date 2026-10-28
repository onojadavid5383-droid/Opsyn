// ============================================================
// OPSYN DESIGN — pure helpers for design mode (no React, no MapLibre):
// status wording, input layer styling, issue framing and the boundary
// draft rules. Tested directly in src/__tests__/design-mode.test.tsx.
// ============================================================

import type { DesignDelta, DesignInputLayerKey, DesignIssue, DesignIssueSeverity, DesignStatus } from '@shared';

export const DESIGN_STATUS_LABEL: Record<DesignStatus, string> = {
  DRAFT: 'Draft', GENERATED: 'Generated', MODIFIED: 'Modified', VALIDATING: 'Validating',
  UNDER_REVIEW: 'Under review', APPROVED: 'Approved', REJECTED: 'Rejected',
  SUPERSEDED: 'Superseded', DEPLOYED: 'Deployed',
};

/** Badge tone per status (components/ui/Badge tones) */
export const DESIGN_STATUS_TONE: Record<DesignStatus, 'neutral' | 'info' | 'review' | 'ok' | 'critical' | 'brand'> = {
  DRAFT: 'neutral', GENERATED: 'info', MODIFIED: 'info', VALIDATING: 'review', UNDER_REVIEW: 'review',
  APPROVED: 'ok', REJECTED: 'critical', SUPERSEDED: 'neutral', DEPLOYED: 'brand',
};

/** Statuses whose inputs, boundary and working set can still change */
export const EDITABLE: DesignStatus[] = ['DRAFT', 'GENERATED', 'MODIFIED', 'REJECTED'];
export const isEditable = (s: DesignStatus) => EDITABLE.includes(s);

export interface InputLayerMeta {
  key:      DesignInputLayerKey;
  label:    string;
  /** What the file must contain, shown under the upload button */
  accepts:  string;
  color:    string;
  geometry: 'line' | 'point' | 'area';
}

// Inputs are context, drawn quieter than the network: roads as a grey
// casing the cables sit on, points as small hollow rings, so the design's
// own FDT/FAT plates stay the loudest thing on the map.
export const INPUT_LAYERS: InputLayerMeta[] = [
  { key: 'road', label: 'Roads', accepts: 'Lines (GeoJSON, or Excel with geometry_wkt)', color: '#8A96A3', geometry: 'line' },
  { key: 'homepass', label: 'Homepasses', accepts: 'Points with a customer count', color: '#D9480F', geometry: 'point' },
  { key: 'pole', label: 'Poles', accepts: 'Points (GeoJSON, or Excel longitude/latitude)', color: '#5C3D99', geometry: 'point' },
  { key: 'building', label: 'Buildings', accepts: 'Polygons (GeoJSON) or points', color: '#B08968', geometry: 'area' },
  { key: 'pickup', label: 'Pickup points', accepts: 'Points', color: '#0B6E5B', geometry: 'point' },
  { key: 'existing_structure', label: 'Existing structures', accepts: 'Points', color: '#3B5B7A', geometry: 'point' },
];
export const INPUT_META = Object.fromEntries(INPUT_LAYERS.map(l => [l.key, l])) as Record<DesignInputLayerKey, InputLayerMeta>;

export const SEVERITY_ORDER: DesignIssueSeverity[] = ['ERROR', 'WARNING', 'INFO'];
export const SEVERITY_LABEL: Record<DesignIssueSeverity, string> = { ERROR: 'Errors', WARNING: 'Warnings', INFO: 'Notes' };
export const SEVERITY_COLOR: Record<DesignIssueSeverity, string> = { ERROR: '#C8231A', WARNING: '#C77700', INFO: '#3B5B7A' };

/** Issues grouped by severity, errors first; empty groups left out */
export function groupIssues(issues: DesignIssue[]): { severity: DesignIssueSeverity; issues: DesignIssue[] }[] {
  return SEVERITY_ORDER
    .map(severity => ({ severity, issues: issues.filter(i => i.severity === severity) }))
    .filter(g => g.issues.length > 0);
}

type Coords = number | Coords[];

/** [minLng, minLat, maxLng, maxLat] of any GeoJSON geometry, or null */
export function geometryBounds(geometry: { coordinates: unknown } | null | undefined): [number, number, number, number] | null {
  if (!geometry) return null;
  const box = [Infinity, Infinity, -Infinity, -Infinity];
  const walk = (c: Coords) => {
    if (!Array.isArray(c)) return;
    if (typeof c[0] === 'number' && typeof c[1] === 'number') {
      const [x, y] = c as number[];
      box[0] = Math.min(box[0], x); box[1] = Math.min(box[1], y);
      box[2] = Math.max(box[2], x); box[3] = Math.max(box[3], y);
      return;
    }
    for (const part of c) walk(part);
  };
  walk(geometry.coordinates as Coords);
  return Number.isFinite(box[0]) ? (box as [number, number, number, number]) : null;
}

/** "Can this be fitted?" — a single point needs a zoom, not a box */
export function isPointBox(b: [number, number, number, number]): boolean {
  return b[0] === b[2] && b[1] === b[3];
}

// ── Boundary drawing ──────────────────────────────────────────

export type LngLat = [number, number];

/** The draft as GeoJSON: the edges so far, and the closed area from 3 points */
export function draftFeatures(points: LngLat[], cursor: LngLat | null): GeoJSON.FeatureCollection {
  const line = cursor ? [...points, cursor] : points;
  const features: GeoJSON.Feature[] = points.map((p, i) => ({
    type: 'Feature', properties: { role: i === 0 ? 'first' : 'vertex' }, geometry: { type: 'Point', coordinates: p },
  }));
  if (line.length >= 2) {
    features.push({ type: 'Feature', properties: { role: 'edge' }, geometry: { type: 'LineString', coordinates: line } });
  }
  if (line.length >= 3) {
    features.push({ type: 'Feature', properties: { role: 'area' }, geometry: { type: 'Polygon', coordinates: [[...line, line[0]]] } });
  }
  return { type: 'FeatureCollection', features };
}

function cross(o: LngLat, a: LngLat, b: LngLat) {
  return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
}

function segmentsCross(p1: LngLat, p2: LngLat, p3: LngLat, p4: LngLat): boolean {
  const d1 = cross(p3, p4, p1);
  const d2 = cross(p3, p4, p2);
  const d3 = cross(p1, p2, p3);
  const d4 = cross(p1, p2, p4);
  return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
}

/**
 * Why the drawn ring can't be a boundary, or null if it can. The server
 * checks again (ST_IsValid, area); this only saves a round trip for the
 * obvious cases and says what to do.
 */
export function boundaryProblem(points: LngLat[]): string | null {
  if (points.length < 3) return 'Place at least three corners';
  const ring = [...points, points[0]];
  for (let i = 0; i < ring.length - 1; i++) {
    for (let j = i + 2; j < ring.length - 1; j++) {
      if (i === 0 && j === ring.length - 2) continue;          // the closing edge touches the first
      if (segmentsCross(ring[i], ring[i + 1], ring[j], ring[j + 1])) return 'The edges cross; undo the last corner and place it elsewhere';
    }
  }
  let twiceArea = 0;
  for (let i = 0; i < ring.length - 1; i++) twiceArea += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
  if (Math.abs(twiceArea) < 1e-12) return 'The corners are in a line; the boundary needs an area';
  return null;
}

export function boundaryPolygon(points: LngLat[]): { type: 'Polygon'; coordinates: LngLat[][] } {
  return { type: 'Polygon', coordinates: [[...points, points[0]]] };
}

export function formatKm(km: number): string {
  if (km === 0) return '0 km';
  return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toFixed(km < 10 ? 2 : 1)} km`;
}

export function formatQuantity(q: number, unit: 'each' | 'm'): string {
  return unit === 'm'
    ? `${q.toLocaleString('en-GB', { maximumFractionDigits: 1 })} m`
    : q.toLocaleString('en-GB');
}

/** A failed design request, in words a planner can act on */
export function designError(err: unknown, fallback = 'The change could not be saved.'): string | null {
  if (!err) return null;
  const e = err as { status?: number; detail?: string; message?: string };
  if (e.status === 403) return "You don't have permission to edit designs. Ask an administrator for design editing access.";
  return e.detail ?? e.message ?? fallback;
}

/** The map, opened on one design */
export const designHref = (id: string) => `/network?mode=design&design=${id}`;

// ── What an edit changed (Phase 7) ───────────────────────────

const signed = (v: number, unit: 'each' | 'm') =>
  `${v > 0 ? '+' : '−'}${unit === 'm' ? formatKm(Math.abs(v) / 1000) : Math.abs(v).toLocaleString('en-GB')}`;

/** "Box to box cable +212 m · Drop cable +312 m · 3 new issues · 1 resolved" */
export function describeDelta(delta: DesignDelta): string[] {
  const parts = delta.boq.slice(0, 4).map(c => `${c.item} ${signed(c.change, c.unit)}`);
  if (delta.boq.length > 4) parts.push(`${delta.boq.length - 4} more BOQ lines`);
  const n = delta.issues.new.length;
  const r = delta.issues.resolved.length;
  if (n) parts.push(`${n} new ${n === 1 ? 'issue' : 'issues'}`);
  if (r) parts.push(`${r} resolved`);
  return parts;
}


// ── Audit trail in words (Phase 8) ───────────────────────────

const FIELD_LABEL: Record<string, string> = {
  name: 'Name', asset_code: 'Code', capacity: 'Capacity', used_capacity: 'In use', lifecycle_status: 'Status',
  fiber_count: 'Fibres', route_method: 'Route', cable_category: 'Category', attributes: 'Details', parent_id: 'Housed in',
  source_asset_id: 'Start', dest_asset_id: 'End', geom: 'Position', length_m: 'Length', deleted_at: 'Deleted',
};
const VERB: Record<string, string> = {
  create: 'Added', delete: 'Deleted', move: 'Moved', update: 'Changed', lifecycle: 'Status changed', restore: 'Restored',
  version_saved: 'Saved a version', version_restored: 'Restored a version', auto_design: 'Auto design', run_imported: 'Imported a run',
  upload: 'Uploaded inputs', version: 'New version', auto_design_queued: 'Auto design started',
};
const LINK_VERB: Record<string, string> = { create: 'Connected', delete: 'Disconnected', update: 'Link changed' };

function shown(v: unknown): string {
  if (v === null || v === undefined || v === '') return '–';
  if (typeof v === 'object') return 'updated';
  return String(v);
}

function pointOf(v: unknown): [number, number] | null {
  const g = v as { type?: string; coordinates?: unknown } | null;
  return g && g.type === 'Point' && Array.isArray(g.coordinates) ? (g.coordinates as [number, number]) : null;
}

/** One audit entry as { verb, detail } a planner can read */
export function describeAudit(e: { action: string; changed_fields: string[]; old: Record<string, unknown> | null;
                                   new: Record<string, unknown> | null; entity_type?: string }): { verb: string; detail: string } {
  const raw = VERB[e.action] ?? e.action.replace(/_/g, ' ');
  const verb = e.entity_type === 'connection' ? LINK_VERB[e.action] ?? raw : raw.charAt(0).toUpperCase() + raw.slice(1);
  const n = e.new ?? {};
  const o = e.old ?? {};
  if (e.action === 'version_saved') return { verb, detail: `Version ${n.version_no}${n.label ? ` “${n.label}”` : ''}` };
  if (e.action === 'version_restored') return { verb, detail: `Version ${n.restored_from} brought back as version ${n.version_no}` };
  if (e.action === 'auto_design' || e.action === 'run_imported') return { verb, detail: `Became version ${n.version_no}` };
  if (e.action === 'move') {
    const a = pointOf(o.geom);
    const b = pointOf(n.geom);
    if (a && b) {
      const lat = ((a[1] + b[1]) / 2) * Math.PI / 180;
      const m = Math.hypot((b[0] - a[0]) * Math.cos(lat), b[1] - a[1]) * Math.PI / 180 * 6_371_000;
      return { verb, detail: `${Math.round(m)} m` };
    }
    if (typeof o.length_m === 'number' || typeof n.length_m === 'number') {
      return { verb: 'Rerouted', detail: `${Math.round(Number(o.length_m ?? 0))} → ${Math.round(Number(n.length_m ?? 0))} m` };
    }
    return { verb, detail: '' };
  }
  if (e.action === 'update' || e.action === 'lifecycle') {
    // Older entries (infrastructure log) hold whole records: find what differs
    const fields = e.changed_fields?.length ? e.changed_fields
      : [...new Set([...Object.keys(o), ...Object.keys(n)])]
        .filter(k => !['updated_at', 'updated_by'].includes(k) && JSON.stringify(o[k]) !== JSON.stringify(n[k]));
    const parts = fields.filter(f => f !== 'geom' && f !== 'length_m').flatMap(f => {
      const a = o[f], b = n[f];
      // Details (attributes) say which of them changed, not "updated → updated"
      if (a && b && typeof a === 'object' && typeof b === 'object') {
        const ao = a as Record<string, unknown>, bo = b as Record<string, unknown>;
        return [...new Set([...Object.keys(ao), ...Object.keys(bo)])]
          .filter(k => JSON.stringify(ao[k]) !== JSON.stringify(bo[k]))
          .map(k => `${k.replace(/_/g, ' ')}: ${shown(ao[k])} → ${shown(bo[k])}`);
      }
      return [`${FIELD_LABEL[f] ?? f}: ${shown(a)} → ${shown(b)}`];
    });
    return { verb, detail: parts.join('; ') };
  }
  return { verb, detail: '' };
}
