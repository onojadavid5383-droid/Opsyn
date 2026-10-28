// ============================================================
// OPSYN DESIGN — the manual design tools as one state machine (pure: no
// React, no map; tested in src/__tests__/manual-design.test.tsx).
//
// reduce(state, event) → { state, op?, error? }. When a tool has what it
// needs, it returns the operation to send (POST /designs/{id}/operations)
// and keeps the tool on, ready for the next one.
//
//   select   click opens the usual popup (handled by the map layers)
//   pan      clicks do nothing
//   measure  click points; Finish/Esc clears (no operation)
//   add      click where the device goes                 → ADD_ASSET
//   move     click a device, then where it goes          → MOVE_ASSET
//   delete   click a device or cable                     → DELETE_ASSET / DELETE_CABLE
//   cable    click the start, then the end               → DRAW_CABLE
//            (devices or points; a drop runs straight, the rest along roads)
//   connect  click the feeding device, then the fed one  → CONNECT
//   split    click a cable where to cut                  → SPLIT_CABLE
//   extend   click a cable, then its new end             → EXTEND_CABLE
//   redraw   click a cable, click its new points, Finish → EDIT_CABLE_GEOM
// ============================================================

import type { DesignCableEnd, DesignOperationBody, DesignSnapKind, NetAssetType, NetCableCategory } from '@shared';

export type EditTool = 'select' | 'pan' | 'measure' | 'add' | 'move' | 'delete' | 'cable' | 'connect' | 'split' | 'extend' | 'redraw';
export type RouteMode = 'road' | 'straight';

export type EditTarget =
  | { kind: 'asset'; id: string; code: string; assetType: string; lng: number; lat: number; live?: boolean }
  | { kind: 'cable'; id: string; code: string; category: string; lng: number; lat: number }
  | { kind: 'point'; lng: number; lat: number; snappedTo?: string };

export interface EditState {
  tool:    EditTool;
  /** add: the asset type; cable: the cable category; split: a device to place at the cut (or null) */
  subtype: string | null;
  route:   RouteMode;
  picks:   EditTarget[];
  points:  [number, number][];
}

export type EditEvent =
  | { type: 'TOOL'; tool: EditTool; subtype?: string | null; start?: EditTarget }
  | { type: 'CLICK'; target: EditTarget }
  | { type: 'FINISH' }
  | { type: 'CANCEL' }
  | { type: 'ROUTE'; route: RouteMode }
  | { type: 'DONE' };

export interface Step { state: EditState; op?: DesignOperationBody; error?: string }

export const INITIAL: EditState = { tool: 'select', subtype: null, route: 'road', picks: [], points: [] };

export const ADDABLE: { type: NetAssetType; label: string }[] = [
  { type: 'FDT', label: 'FDT' }, { type: 'FAT', label: 'FAT' }, { type: 'CLOSURE', label: 'Closure' },
  { type: 'POLE', label: 'Pole' }, { type: 'HANDHOLE', label: 'Handhole' }, { type: 'MANHOLE', label: 'Manhole' },
];
export const DRAWABLE: { category: NetCableCategory; label: string }[] = [
  { category: 'BOX_TO_BOX', label: 'Box to box' }, { category: 'DROP', label: 'Drop' },
  { category: 'DISTRIBUTION', label: 'Distribution' }, { category: 'CLOSURE_FDT', label: 'Closure to FDT' },
  { category: 'FEEDER', label: 'Feeder' },
];

/** Tools that act on the map's clicks (the layers' own popup stays out of their way) */
export const EDITING = (t: EditTool) => t !== 'select' && t !== 'pan';

export function cableEnd(t: EditTarget): DesignCableEnd {
  return t.kind === 'asset' ? { asset_id: t.id } : { lng: t.lng, lat: t.lat };
}

const clear = (s: EditState): EditState => ({ ...s, picks: [], points: [] });

export function reduce(s: EditState, e: EditEvent): Step {
  switch (e.type) {
    case 'TOOL': {
      const subtype = e.subtype ?? (e.tool === 'cable' ? 'BOX_TO_BOX' : e.tool === 'add' ? 'FAT' : null);
      const route: RouteMode = e.tool === 'cable' && subtype === 'DROP' ? 'straight' : 'road';
      return { state: { tool: e.tool, subtype, route, picks: e.start ? [e.start] : [], points: [] } };
    }
    case 'ROUTE':
      return { state: { ...s, route: e.route } };
    case 'DONE':
      return { state: clear(s) };
    case 'CANCEL':
      return { state: s.picks.length || s.points.length ? clear(s) : INITIAL };
    case 'FINISH':
      if (s.tool === 'redraw' && s.picks[0]?.kind === 'cable') {
        if (s.points.length < 2) return { state: s, error: 'Place at least two points for the new line' };
        return { state: s, op: { op: 'EDIT_CABLE_GEOM', id: s.picks[0].id, coordinates: s.points } };
      }
      return { state: clear(s) };
    case 'CLICK':
      return click(s, e.target);
  }
}

function click(s: EditState, t: EditTarget): Step {
  const [first] = s.picks;
  switch (s.tool) {
    case 'select':
    case 'pan':
      return { state: s };
    case 'measure':
      return { state: { ...s, points: [...s.points, [t.lng, t.lat]] } };
    case 'add':
      if (t.kind === 'asset' && !t.live) return { state: s, error: `${t.code} is already there; pick an empty spot` };
      return { state: s, op: { op: 'ADD_ASSET', asset_type: s.subtype ?? 'FAT', lng: t.lng, lat: t.lat } };
    case 'move':
      if (!first) {
        if (t.kind !== 'asset' || t.live) return { state: s, error: 'Click a device of this design to move' };
        return { state: { ...s, picks: [t] } };
      }
      return { state: s, op: { op: 'MOVE_ASSET', id: first.kind === 'asset' ? first.id : '', lng: t.lng, lat: t.lat } };
    case 'delete':
      if (t.kind === 'asset' && !t.live) return { state: s, op: { op: 'DELETE_ASSET', id: t.id } };
      if (t.kind === 'cable') return { state: s, op: { op: 'DELETE_CABLE', id: t.id } };
      return { state: s, error: 'Click a device or cable of this design to delete' };
    case 'cable':
      if (t.kind === 'cable') return { state: s, error: 'Start and end on a device or an empty spot, not on a cable' };
      if (!first) return { state: { ...s, picks: [t] } };
      if (first.kind === 'asset' && t.kind === 'asset' && first.id === t.id) {
        return { state: s, error: 'The cable needs two different ends' };
      }
      return {
        state: s,
        op: { op: 'DRAW_CABLE', cable_category: s.subtype ?? 'BOX_TO_BOX', route: s.route, from: cableEnd(first), to: cableEnd(t) },
      };
    case 'connect':
      if (t.kind !== 'asset') return { state: s, error: 'Click a device' };
      if (!first) return { state: { ...s, picks: [t] } };
      if (first.kind === 'asset' && first.id === t.id) return { state: s, error: 'Pick a different device to feed' };
      if (t.live) return { state: s, error: 'The fed device must belong to this design' };
      return { state: s, op: { op: 'CONNECT', source_id: first.kind === 'asset' ? first.id : '', dest_id: t.id, connection_type: 'FEED' } };
    case 'split':
      if (t.kind !== 'cable') return { state: s, error: 'Click a cable where it should be cut' };
      return { state: s, op: { op: 'SPLIT_CABLE', id: t.id, lng: t.lng, lat: t.lat, ...(s.subtype ? { insert_asset_type: s.subtype } : {}) } };
    case 'extend':
      if (!first) {
        if (t.kind !== 'cable') return { state: s, error: 'Click the cable to extend' };
        return { state: { ...s, picks: [t] } };
      }
      if (t.kind === 'cable') return { state: s, error: 'End on a device or an empty spot' };
      return { state: s, op: { op: 'EXTEND_CABLE', id: first.kind === 'cable' ? first.id : '', to: cableEnd(t), route: s.route } };
    case 'redraw':
      if (!first) {
        if (t.kind !== 'cable') return { state: s, error: 'Click the cable to redraw' };
        return { state: { ...s, picks: [t], points: [] } };
      }
      return { state: { ...s, points: [...s.points, [t.lng, t.lat]] } };
  }
}

const CABLE_NAME: Record<string, string> = Object.fromEntries(DRAWABLE.map(d => [d.category, d.label.toLowerCase()]));

/** What to do next, in words */
export function hint(s: EditState): string {
  const [first] = s.picks;
  switch (s.tool) {
    case 'select': return 'Click a device or cable to see it.';
    case 'pan': return 'Drag to move around; clicks change nothing.';
    case 'measure': return s.points.length ? 'Click the next point; Esc clears.' : 'Click where to measure from.';
    case 'add': return `Click where the ${ADDABLE.find(a => a.type === s.subtype)?.label ?? s.subtype} goes; it snaps beside the nearest road or onto a pole.`;
    case 'move': return first ? `Click where ${first.kind === 'asset' ? first.code : ''} goes; its cables follow.` : 'Click the device to move.';
    case 'delete': return 'Click a device or cable to delete it. Undo brings it back.';
    case 'cable': {
      const name = CABLE_NAME[s.subtype ?? ''] ?? 'cable';
      const how = s.route === 'road' ? 'along the roads' : 'in a straight line';
      return first ? `Click the end of the ${name} cable; it runs ${how}.` : `Click where the ${name} cable starts.`;
    }
    case 'connect': return first ? `Click the device ${first.kind === 'asset' ? first.code : ''} feeds.` : 'Click the device that feeds.';
    case 'split': return s.subtype ? `Click a cable to cut it and place a ${s.subtype.toLowerCase()} there.` : 'Click a cable where to cut it.';
    case 'extend': return first ? 'Click the new end: a device or a spot.' : 'Click the cable to extend.';
    case 'redraw':
      return !first ? 'Click the cable to redraw.'
        : s.points.length < 2 ? 'Click the points of the new line, in order.'
        : `${s.points.length} points. Press Enter or Finish to save the line.`;
  }
}

/** Metres along a path (spherical; for the measure tool) */
export function pathLength(points: [number, number][]): number {
  let m = 0;
  for (let i = 1; i < points.length; i++) {
    const [x1, y1] = points[i - 1];
    const [x2, y2] = points[i];
    const r = Math.PI / 180;
    const a = Math.sin(((y2 - y1) * r) / 2) ** 2 + Math.cos(y1 * r) * Math.cos(y2 * r) * Math.sin(((x2 - x1) * r) / 2) ** 2;
    m += 2 * 6_371_000 * Math.asin(Math.sqrt(a));
  }
  return m;
}

export const SHORTCUTS: Record<string, EditTool> = {
  v: 'select', h: 'pan', r: 'measure', a: 'add', m: 'move', d: 'delete', c: 'cable', k: 'connect', x: 'split', e: 'extend', g: 'redraw',
};

// ── What a click means (EditLayer) ───────────────────────────

export type Want = 'asset' | 'cable' | 'point';

/** What a click should resolve to for the current tool and step */
export function wantFor(s: EditState): Want[] {
  const first = s.picks[0];
  switch (s.tool) {
    case 'delete': return ['asset', 'cable'];
    case 'split': return ['cable'];
    case 'extend': case 'redraw': return first ? ['point'] : ['cable'];
    case 'move': return first ? ['point'] : ['asset'];
    case 'connect': return ['asset'];
    case 'measure': return ['point'];
    default: return ['asset', 'point'];
  }
}

/** Server snap targets for a point click */
export function snapTargets(s: EditState): DesignSnapKind[] | null {
  switch (s.tool) {
    case 'add': case 'move': return ['pole_input', 'road', 'boundary'];
    case 'cable':
      return s.subtype === 'DROP' ? ['asset', 'homepass', 'pole_input', 'road']
        : ['asset', 'live_asset', 'pickup', 'pole_input', 'vertex', 'road'];
    case 'extend': return ['asset', 'live_asset', 'homepass', 'pickup', 'road'];
    default: return null;                 // measure, redraw: the click itself
  }
}
