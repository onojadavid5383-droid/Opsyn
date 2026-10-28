// ============================================================
// OPSYN MAP — model (pure; unit-tested)
// One index over every mapped asset: kind, label, position and STATE.
// Kind is shown by shape, state by colour (map icons), so the two never
// compete. Nothing is placed without real coordinates.
// ============================================================

import type {
  InfraMapCabinet, InfraMapData, InfraMapNode, InfraMapOLT, InfraMapRoute, InfraMapSite,
  InfraMapSplitter, InfraUtilisationPoint, OutageIncident, OutageSeverity,
} from '@shared';

export type AssetKind = 'site' | 'olt' | 'cabinet' | 'splitter';

/** Colour role for an asset: neutral unless something needs attention */
export type AssetState = 'normal' | 'watch' | 'critical' | 'offline';

export interface MapAsset {
  key:      string;             // `${kind}:${id}` — unique across kinds
  id:       string;
  kind:     AssetKind;
  label:    string;             // what an engineer searches for (box ID, OLT name…)
  sublabel: string;             // "Splitter · Second-Level 1:8"
  lat:      number;
  lng:      number;
  state:    AssetState;
  /** Open incidents on this asset (OLTs, matched by reference) */
  incidents: OutageIncident[];
  raw:      InfraMapSite | InfraMapOLT | InfraMapCabinet | InfraMapSplitter;
}

export const KIND_LABEL: Record<AssetKind, string> = {
  site: 'Site', olt: 'OLT', cabinet: 'Cabinet', splitter: 'Splitter',
};

const valid = (lat: unknown, lng: unknown): lat is number =>
  typeof lat === 'number' && typeof lng === 'number' && Number.isFinite(lat) && Number.isFinite(lng)
  && !(lat === 0 && lng === 0);    // 0,0 is a missing coordinate, not the Gulf of Guinea

/** Capacity → state. Thresholds match the existing map's legend (70% / 90%). */
export function capacityState(pct: number | undefined, hasAlert: boolean, status = 'active'): AssetState {
  if (status !== 'active') return 'offline';
  if (hasAlert || (pct ?? 0) >= 90) return 'critical';
  if ((pct ?? 0) >= 70) return 'watch';
  return 'normal';
}

export function buildAssetIndex(
  data: InfraMapData | undefined,
  util: InfraUtilisationPoint[],
  incidents: OutageIncident[],
): MapAsset[] {
  if (!data) return [];
  const utilBySite = new Map(util.map(u => [u.site_id, u]));
  const oltIncidents = new Map<string, OutageIncident[]>();
  const byName = new Map(data.olts.map(o => [o.name.trim().toLowerCase(), o.id]));
  for (const inc of incidents) {
    if (inc.status === 'resolved' || !inc.olt_reference) continue;
    const id = byName.get(inc.olt_reference.trim().toLowerCase());
    if (id) oltIncidents.set(id, [...(oltIncidents.get(id) ?? []), inc]);
  }

  const out: MapAsset[] = [];
  for (const s of data.sites) {
    if (!valid(s.latitude, s.longitude)) continue;
    const u = utilBySite.get(s.id);
    out.push({
      key: `site:${s.id}`, id: s.id, kind: 'site', label: s.name,
      sublabel: `Site · ${s.site_type.replace(/_/g, ' ')}`,
      lat: s.latitude!, lng: s.longitude!,
      state: capacityState(u?.utilisation_pct, s.has_alert, s.status),
      incidents: [], raw: s,
    });
  }
  for (const o of data.olts) {
    if (!valid(o.latitude, o.longitude)) continue;
    const list = oltIncidents.get(o.id) ?? [];
    out.push({
      key: `olt:${o.id}`, id: o.id, kind: 'olt', label: o.name,
      sublabel: `OLT${o.location_description ? ` · ${o.location_description}` : ''}`,
      lat: o.latitude, lng: o.longitude,
      state: list.some(i => i.severity === 'critical' || i.severity === 'high') ? 'critical' : list.length ? 'watch' : 'normal',
      incidents: list, raw: o,
    });
  }
  for (const c of data.cabinets) {
    if (!valid(c.latitude, c.longitude)) continue;
    out.push({
      key: `cabinet:${c.id}`, id: c.id, kind: 'cabinet', label: c.cabinet_id,
      sublabel: `Cabinet · capacity ${c.capacity}`,
      lat: c.latitude, lng: c.longitude, state: 'normal', incidents: [], raw: c,
    });
  }
  for (const sp of data.splitters) {
    if (!valid(sp.latitude, sp.longitude)) continue;
    const full = sp.output_ports > 0 && (sp.number_customer ?? 0) >= sp.output_ports;
    out.push({
      key: `splitter:${sp.id}`, id: sp.id, kind: 'splitter', label: sp.box_id,
      sublabel: `Splitter · ${sp.splitter_level} ${sp.input_ports}:${sp.output_ports}`,
      lat: sp.latitude, lng: sp.longitude,
      state: full ? 'watch' : 'normal',
      incidents: [], raw: sp,
    });
  }
  return out;
}

// ── Search ────────────────────────────────────────────────────

/** Rank assets for a query: exact ID > prefix > substring (label, then sublabel). */
export function searchAssets(assets: MapAsset[], query: string, limit = 8): MapAsset[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return assets
    .map(a => {
      const label = a.label.toLowerCase();
      const score = label === q ? 4 : label.startsWith(q) ? 3 : label.includes(q) ? 2
        : a.sublabel.toLowerCase().includes(q) ? 1 : 0;
      return { a, score };
    })
    .filter(r => r.score > 0)
    .sort((x, y) => y.score - x.score || x.a.label.localeCompare(y.a.label, undefined, { numeric: true }))
    .slice(0, limit)
    .map(r => r.a);
}

// ── Path trace ────────────────────────────────────────────────

export interface TraceHop { asset: MapAsset; relation: string }

/**
 * Splitter → parent splitter(s) → cabinet, from the stored topology.
 * Stops (and says why) where a link is missing; guards against cycles.
 * The drawn line is the LOGICAL path between assets, not the cable's route.
 */
export function traceSplitter(startId: string, data: InfraMapData, assets: MapAsset[]): { hops: TraceHop[]; stop: string } {
  const byKey = new Map(assets.map(a => [a.key, a]));
  const splitters = new Map(data.splitters.map(s => [s.id, s]));
  const hops: TraceHop[] = [];
  const seen = new Set<string>();
  let current = splitters.get(startId);

  const start = byKey.get(`splitter:${startId}`);
  if (!current || !start) return { hops, stop: 'This splitter has no mapped position.' };
  hops.push({ asset: start, relation: 'Selected splitter' });

  while (current) {
    seen.add(current.id);
    if (current.parent_splitter_id) {
      if (seen.has(current.parent_splitter_id)) return { hops, stop: 'The stored topology loops back on itself — check the parent links.' };
      const parent = byKey.get(`splitter:${current.parent_splitter_id}`);
      if (!parent) return { hops, stop: 'The parent splitter has no mapped position.' };
      hops.push({ asset: parent, relation: 'Fed by splitter' });
      current = splitters.get(current.parent_splitter_id);
      continue;
    }
    if (current.cabinet_id) {
      const cab = byKey.get(`cabinet:${current.cabinet_id}`);
      if (!cab) return { hops, stop: 'The cabinet has no mapped position.' };
      hops.push({ asset: cab, relation: 'Housed in cabinet' });
      return { hops, stop: 'The cabinet is the last recorded link — cabinets are not linked to an OLT in the asset data.' };
    }
    return { hops, stop: hops.length === 1 ? 'No upstream link is recorded for this splitter.' : 'No further upstream link is recorded.' };
  }
  return { hops, stop: '' };
}

// ── Routes ────────────────────────────────────────────────────

export type RouteState = 'normal' | 'watch' | 'critical' | 'unknown';

export function routeState(status: string): RouteState {
  const s = status.toLowerCase();
  if (s === 'active') return 'normal';
  if (s === 'degraded' || s === 'maintenance') return 'watch';
  if (s === 'cut' || s === 'inactive' || s === 'down') return 'critical';
  return 'unknown';
}

/** Weight by cable role; dash pattern by state, so state never rests on colour alone. */
export function routeStyle(r: Pick<InfraMapRoute, 'status' | 'cable_type'>): { weight: number; dashArray?: string; state: RouteState } {
  const ct = (r.cable_type ?? '').toLowerCase();
  const weight = ct.includes('trunk') || ct.includes('core') ? 4 : ct.includes('dist') || ct.includes('feed') ? 3 : 2;
  const state = routeState(r.status);
  return { weight, state, dashArray: state === 'critical' ? '2 6' : state === 'watch' ? '8 6' : undefined };
}

/** Node → coordinates, via its site (nodes carry no position of their own). */
export function nodePosition(node: InfraMapNode | undefined, sites: Map<string, InfraMapSite>): [number, number] | null {
  if (!node?.site_id) return null;
  const s = sites.get(node.site_id);
  return s && valid(s.latitude, s.longitude) ? [s.latitude!, s.longitude!] : null;
}

export const worstSeverity = (list: OutageIncident[]): OutageSeverity | null =>
  (['critical', 'high', 'warning', 'low'] as OutageSeverity[]).find(s => list.some(o => o.severity === s)) ?? null;
