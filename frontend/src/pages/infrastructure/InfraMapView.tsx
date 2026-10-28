// ============================================================
// OPSYN INFRA MAP — the network workspace (console surface)
//
// Map first: the map fills the workspace; everything else floats over it as
// glass — search (top left), layers panel, view/basemap toolbar (top right),
// zoom toolbar (bottom right), inspector (right; a bottom sheet on phones).
//
//   Asset KIND  → shape   (site ◉ · OLT ■ · cabinet ▬ · splitter ▼/▽)
//   Asset STATE → colour  (neutral unless it needs attention)
//   Incidents   → severity shapes (⬣ ▲ ◆ ●) at the OLT they reference
//   Routes      → dash pattern by state, weight by cable role
//
// Clusters at low zoom (bubble ring = worst state inside). The List view is
// the accessible, searchable equivalent of the map. Nothing is placed without
// real coordinates; on-call staff have none, so they are listed, not drawn.
// ============================================================

import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { useQuery } from '@tanstack/react-query';
import { Layers, List, Map as MapIcon, Maximize2, Minus, Moon, MoreHorizontal, Plus, Sun } from 'lucide-react';
import { memo, useCallback, useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import { Link } from 'react-router-dom';
import {
  Circle, CircleMarker, MapContainer, Marker, Polyline, ScaleControl, Tooltip, useMap,
} from 'react-leaflet';
import MarkerClusterGroup from 'react-leaflet-cluster';
import type {
  InfraMapData, InfraMapRoute, InfraMapSite, InfraMapSplitter, InfraUtilisationPoint, OutageIncident, OutageSeverity,
  ShiftAssignment,
} from '@shared';

import { infrastructureApi, outageApi, shiftsApi } from '../../api/index';
import { GlassButton, GlassMenu, GlassPanel, GlassToolbar, GlassToolbarDivider } from '../../components/glass';
import { SEVERITY_META, SEVERITY_ORDER } from '../../components/status/severity';
import { BREAKPOINTS, useMediaQuery } from '../../hooks/useMediaQuery';
import { useThemeStore } from '../../store/theme.store';
import { BASEMAPS, type Basemap } from '../../lib/basemap';
import { ResilientTileLayer } from '../../components/map/ResilientTileLayer';
import AssetList from './map/AssetList';
import LayerPanel from './map/LayerPanel';
import { DEFAULT_LAYERS, type LayerCounts, type LayerKey, type LayerState } from './map/layers';
import { clusterIcon, createIconCache, type IconCache, type MapPalette } from './map/mapIcons';
import MapInspector, { type Selection } from './map/MapInspector';
import {
  buildAssetIndex, capacityState, KIND_LABEL, nodePosition, routeStyle, traceSplitter, worstSeverity,
  type AssetKind, type AssetState, type MapAsset, type TraceHop,
} from './map/mapModel';
import { useMapPalette } from './map/mapPalette';
import MapSearch from './map/MapSearch';
import s from './map/InfraMap.module.css';

// Leaflet focuses the map on mousedown, then restores only the WINDOW's
// scroll. OpSyn scrolls inside <main>, so the focus scrolled the page between
// mousedown and mouseup and the click on a marker was lost.
type KeyboardHandler = { _onMouseDown: () => void; _focused: boolean; _map: L.Map };
// (the handler class is real but missing from @types/leaflet)
const keyboardHandler = (L.Map as unknown as { Keyboard: { prototype: KeyboardHandler } }).Keyboard.prototype;
keyboardHandler._onMouseDown = function (this: KeyboardHandler) {
  if (!this._focused) this._map.getContainer().focus({ preventScroll: true });
};

// ── Persisted view preferences (per viewer; safe when storage is blocked) ──

const LAYERS_KEY = 'opsyn-map-layers';
const BASEMAP_KEY = 'opsyn-map-basemap';

function readLayers(): LayerState {
  try {
    const raw = localStorage.getItem(LAYERS_KEY);
    return raw ? { ...DEFAULT_LAYERS, ...(JSON.parse(raw) as Partial<LayerState>) } : DEFAULT_LAYERS;
  } catch { return DEFAULT_LAYERS; }
}

/** The viewer's own basemap choice, or null if they haven't made one */
function readBasemap(): Basemap | null {
  try {
    const id = localStorage.getItem(BASEMAP_KEY);
    return BASEMAPS.find(b => b.id === id) ?? null;
  } catch { return null; }
}

const DARK_MAP  = BASEMAPS.find(b => b.id === 'osm-dark')!;
const LIGHT_MAP = BASEMAPS.find(b => b.id === 'osm')!;

function store(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* preference only */ }
}

const LAYER_OF: Record<AssetKind, LayerKey> = { site: 'sites', olt: 'olts', cabinet: 'cabinets', splitter: 'splitters' };
const STATE_RANK: Record<AssetState, number> = { critical: 3, watch: 2, normal: 1, offline: 0 };
/** Clusters break apart at street level, so an asset picked from search is always visible */
const UNCLUSTER_ZOOM = 16;

/** Local calendar date — the on-call rota is by local day, not UTC */
function localDate(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

interface Subscriber { id: string; customer_id?: string; service_type?: string; status?: string; latitude?: number; longitude?: number }

// ── Map-side helpers (must live inside <MapContainer>) ─────────

/** Hands the Leaflet map to the workspace and names it for screen readers. */
function MapBridge({ onReady, label }: { onReady: (m: L.Map) => void; label: string }) {
  const map = useMap();
  useEffect(() => { onReady(map); }, [map, onReady]);
  useEffect(() => {
    const el = map.getContainer();
    el.setAttribute('role', 'application');
    el.setAttribute('aria-label', label);
  }, [map, label]);
  return null;
}

/** Cursor position + zoom, written straight to the status chip (no React re-render per mousemove). */
function StatusReporter({ target }: { target: RefObject<HTMLDivElement> }) {
  const map = useMap();
  useEffect(() => {
    const write = (ll?: L.LatLng) => {
      const [pos, zoom] = target.current?.children ?? [];
      if (ll && pos) pos.textContent = `${ll.lat.toFixed(5)}, ${ll.lng.toFixed(5)}`;
      if (zoom) zoom.textContent = `z${map.getZoom()}`;
    };
    const onMove = (e: L.LeafletMouseEvent) => write(e.latlng);
    const onZoom = () => write();
    map.on('mousemove', onMove);
    map.on('zoomend', onZoom);
    onZoom();
    return () => { map.off('mousemove', onMove); map.off('zoomend', onZoom); };
  }, [map, target]);
  return null;
}

/** Fits the whole network once, when assets first arrive. */
function FitOnce({ points }: { points: [number, number][] }) {
  const map = useMap();
  const done = useRef(false);
  useEffect(() => {
    if (done.current || points.length === 0) return;
    done.current = true;
    if (points.length === 1) map.setView(points[0], 14);
    else map.fitBounds(L.latLngBounds(points), { padding: [48, 48], maxZoom: 14 });
  }, [map, points]);
  return null;
}

// ── Asset markers (memoised: the heavy layer) ─────────────────

const AssetMarkers = memo(function AssetMarkers({ assets, palette, icons, selectedKey, onSelect }: {
  assets: MapAsset[]; palette: MapPalette; icons: IconCache; selectedKey: string | null; onSelect: (a: MapAsset) => void;
}) {
  const clusterRing = useCallback((cluster: L.MarkerCluster) => {
    let worst: AssetState = 'offline';
    for (const m of cluster.getAllChildMarkers()) {
      const cls = (m.options.icon?.options as L.DivIconOptions | undefined)?.className ?? '';
      const st = (['critical', 'watch', 'normal', 'offline'] as AssetState[]).find(x => cls.includes(`state-${x}`)) ?? 'normal';
      if (STATE_RANK[st] > STATE_RANK[worst]) worst = st;
      if (worst === 'critical') break;
    }
    return clusterIcon(cluster.getChildCount(), worst === 'normal' || worst === 'offline' ? palette.route.normal : palette.state[worst]);
  }, [palette]);

  return (
    <MarkerClusterGroup
      chunkedLoading
      showCoverageOnHover={false}
      spiderfyOnMaxZoom
      maxClusterRadius={48}
      disableClusteringAtZoom={UNCLUSTER_ZOOM}
      iconCreateFunction={clusterRing}
    >
      {assets.map(a => (
        <Marker
          key={a.key}
          position={[a.lat, a.lng]}
          icon={icons.asset(a.kind, a.state, (a.raw as InfraMapSplitter).splitter_level, a.key === selectedKey)}
          keyboard
          eventHandlers={{
            click: () => onSelect(a),
            add: e => {
              // Leaflet gives keyboard markers role=button but no name
              (e.target as L.Marker).getElement()?.setAttribute('aria-label', `${KIND_LABEL[a.kind]} ${a.label}`);
            },
          }}
        >
          <Tooltip direction="top" offset={[0, -10]}>
            <span style={{ fontFamily: 'var(--font-mono)' }}>{a.label}</span> · {KIND_LABEL[a.kind]}
          </Tooltip>
        </Marker>
      ))}
    </MarkerClusterGroup>
  );
});

// ── Workspace ─────────────────────────────────────────────────

export default function InfraMapView() {
  const phone = !useMediaQuery(BREAKPOINTS.tablet);
  const [workspaceEl, setWorkspaceEl] = useState<HTMLDivElement | null>(null);
  const palette = useMapPalette(workspaceEl);
  const icons = useMemo(() => (palette ? createIconCache(palette) : null), [palette]);
  const [map, setMap] = useState<L.Map | null>(null);
  const statusRef = useRef<HTMLDivElement>(null);

  const [layers, setLayers] = useState<LayerState>(readLayers);
  // Until the viewer picks one, the basemap follows the app theme
  const appTheme = useThemeStore(st => st.resolved);
  const [chosenBasemap, setBasemap] = useState<Basemap | null>(readBasemap);
  const basemap = chosenBasemap ?? (appTheme === 'dark' ? DARK_MAP : LIGHT_MAP);
  const [view, setView] = useState<'map' | 'list'>('map');
  const [layersOpen, setLayersOpen] = useState(() => !phone);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [trace, setTrace] = useState<{ hops: TraceHop[]; stop: string } | null>(null);

  // ── Data ──
  const mapQ = useQuery<InfraMapData>({ queryKey: ['infra', 'map'], queryFn: () => infrastructureApi.getMap(), refetchInterval: 60_000 });
  const utilQ = useQuery<InfraUtilisationPoint[]>({ queryKey: ['infra', 'utilisation'], queryFn: () => infrastructureApi.getUtilisation(), refetchInterval: 60_000 });
  const outagesQ = useQuery({ queryKey: ['outages', 'live'], queryFn: () => outageApi.getLive(), refetchInterval: 30_000 });
  const subsQ = useQuery<Subscriber[]>({
    queryKey: ['infra', 'subscribers'],
    queryFn: () => infrastructureApi.listSubscribers(),
    enabled: layers.subscribers,        // only fetched when someone asks for it
    refetchInterval: 120_000,
  });
  const today = localDate();
  const shiftsQ = useQuery({ queryKey: ['shifts', 'weekly', today], queryFn: () => shiftsApi.getWeekly(today), refetchInterval: 300_000 });

  const util = useMemo(() => (Array.isArray(utilQ.data) ? utilQ.data : []), [utilQ.data]);
  const openIncidents = useMemo<OutageIncident[]>(
    () => (Array.isArray(outagesQ.data) ? outagesQ.data : []).filter(o => o.status !== 'resolved'),
    [outagesQ.data],
  );
  const assets = useMemo(() => buildAssetIndex(mapQ.data, util, openIncidents), [mapQ.data, util, openIncidents]);
  const utilBySite = useMemo(() => new Map(util.map(u => [u.site_id, u])), [util]);
  const sitesById = useMemo(() => new Map<string, InfraMapSite>((mapQ.data?.sites ?? []).map(x => [x.id, x])), [mapQ.data]);
  const nodesById = useMemo(() => new Map((mapQ.data?.nodes ?? []).map(n => [n.id, n])), [mapQ.data]);
  const cabinetSplitters = useMemo(() => {
    const m = new Map<string, number>();
    for (const sp of mapQ.data?.splitters ?? []) if (sp.cabinet_id) m.set(sp.cabinet_id, (m.get(sp.cabinet_id) ?? 0) + 1);
    return m;
  }, [mapQ.data]);

  const routes = useMemo(() => (mapQ.data?.routes ?? []).flatMap(r => {
    const from = nodePosition(nodesById.get(r.from_node_id), sitesById);
    const to = nodePosition(nodesById.get(r.to_node_id), sitesById);
    if (!from || !to || (from[0] === to[0] && from[1] === to[1])) return [];
    return [{ route: r, positions: [from, to] as [number, number][], style: routeStyle(r) }];
  }), [mapQ.data, nodesById, sitesById]);

  const alarms = useMemo(() => assets.flatMap(a => {
    const sev = worstSeverity(a.incidents);
    return sev ? [{ asset: a, severity: sev }] : [];
  }), [assets]);

  const visibleAssets = useMemo(() => assets.filter(a => layers[LAYER_OF[a.kind]]), [assets, layers]);
  const allPoints = useMemo<[number, number][]>(() => assets.map(a => [a.lat, a.lng]), [assets]);

  const subscribers = useMemo(
    () => (Array.isArray(subsQ.data) ? subsQ.data : []).filter(x => Number.isFinite(x.latitude) && Number.isFinite(x.longitude) && !(x.latitude === 0 && x.longitude === 0)),
    [subsQ.data],
  );

  const onCall = useMemo<string[] | null>(() => {
    if (shiftsQ.isLoading) return null;
    const list: ShiftAssignment[] = shiftsQ.data?.assignments ?? [];
    const names = list
      .filter(a => a.date === today && a.status !== 'cancelled' && a.shift?.shift_type === 'oncall')
      .map(a => a.user?.name ?? 'Unnamed staff member');
    return [...new Set(names)].sort();
  }, [shiftsQ.isLoading, shiftsQ.data, today]);

  const counts = useMemo<LayerCounts>(() => {
    const bySev = Object.fromEntries(SEVERITY_ORDER.map(sv => [sv, 0])) as Record<OutageSeverity, number>;
    for (const al of alarms) for (const inc of al.asset.incidents) bySev[inc.severity] += 1;
    const placed = alarms.reduce((n, al) => n + al.asset.incidents.length, 0);
    const kinds = { site: 0, olt: 0, cabinet: 0, splitter: 0 };
    let l2 = 0;
    for (const a of assets) {
      kinds[a.kind] += 1;
      if (a.kind === 'splitter' && /second/i.test((a.raw as InfraMapSplitter).splitter_level)) l2 += 1;
    }
    return {
      sites: kinds.site, olts: kinds.olt, cabinets: kinds.cabinet,
      splitterL1: kinds.splitter - l2, splitterL2: l2,
      routes: routes.length, subscribers: subscribers.length,
      alarmsBySeverity: bySev, alarmsUnplaced: openIncidents.length - placed,
    };
  }, [alarms, assets, routes.length, subscribers.length, openIncidents.length]);

  // Keep the selected asset's data fresh across refetches
  // (memoised: the inspector keeps the last selection by identity while it animates closed)
  const liveSelection = useMemo<Selection | null>(() => {
    if (selection?.type !== 'asset') return selection;
    const fresh = assets.find(a => a.key === selection.asset.key);
    return fresh && fresh !== selection.asset ? { type: 'asset', asset: fresh } : selection;
  }, [selection, assets]);
  const selectedKey = liveSelection?.type === 'asset' ? liveSelection.asset.key : null;

  // ── Actions ──
  const toggleLayer = useCallback((k: LayerKey) => {
    setLayers(prev => {
      const next = { ...prev, [k]: !prev[k] };
      store(LAYERS_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const pickBasemap = (b: Basemap) => { setBasemap(b); store(BASEMAP_KEY, b.id); };

  const selectAsset = useCallback((a: MapAsset) => {
    setSelection({ type: 'asset', asset: a });
    setTrace(null);
  }, []);

  const showAsset = useCallback((a: MapAsset) => {
    selectAsset(a);
    setView('map');
    if (!layers[LAYER_OF[a.kind]]) toggleLayer(LAYER_OF[a.kind]);
    map?.flyTo([a.lat, a.lng], Math.max(map.getZoom(), UNCLUSTER_ZOOM), { duration: 0.6 });
  }, [map, layers, selectAsset, toggleLayer]);

  const selectRoute = (route: InfraMapRoute) => {
    const from = nodesById.get(route.from_node_id);
    const to = nodesById.get(route.to_node_id);
    setSelection({ type: 'route', route, fromName: from?.name, toName: to?.name });
    setTrace(null);
  };

  const runTrace = (splitterId: string) => {
    if (!mapQ.data) return;
    const t = traceSplitter(splitterId, mapQ.data, assets);
    setTrace(t);
    if (map && t.hops.length > 1) map.fitBounds(L.latLngBounds(t.hops.map(h => [h.asset.lat, h.asset.lng] as [number, number])), { padding: [64, 64], maxZoom: 17 });
  };

  const zoomToSelection = () => {
    if (!map || !liveSelection) return;
    if (liveSelection.type === 'asset') map.flyTo([liveSelection.asset.lat, liveSelection.asset.lng], Math.max(map.getZoom(), UNCLUSTER_ZOOM + 1), { duration: 0.6 });
    else {
      const r = routes.find(x => x.route.id === liveSelection.route.id);
      if (r) map.fitBounds(L.latLngBounds(r.positions), { padding: [64, 64] });
    }
  };

  const fitAll = () => {
    if (!map || allPoints.length === 0) return;
    map.fitBounds(L.latLngBounds(allPoints), { padding: [48, 48], maxZoom: 14 });
  };

  const closeInspector = useCallback(() => { setSelection(null); setTrace(null); }, []);

  const onMapReady = useCallback((m: L.Map) => setMap(m), []);

  const mapLabel = `Network map: ${visibleAssets.length} assets shown${alarms.length ? `, ${alarms.length} with open incidents` : ''}. The list view shows the same assets as a table.`;
  const inspectorOpen = selection !== null;
  const empty = !mapQ.isLoading && !mapQ.isError && assets.length === 0;

  return (
    <div ref={setWorkspaceEl} className={s.workspace} data-surface="console">
      {palette && icons && (
        // Zoom limits live on the map, not the tiles: with no basemap, clustering still needs a maxZoom
        <MapContainer className={s.map} center={[6.5244, 3.3792]} zoom={11} minZoom={3} maxZoom={19} zoomControl={false} worldCopyJump>
          <MapBridge onReady={onMapReady} label={mapLabel} />
          <FitOnce points={allPoints} />
          <StatusReporter target={statusRef} />
          <ScaleControl position="bottomright" imperial={false} />
          {basemap.url && <ResilientTileLayer key={basemap.id} basemap={basemap} />}

          {layers.heat && util.filter(u => Number.isFinite(u.latitude) && Number.isFinite(u.longitude)).map(u => {
            const st = capacityState(u.utilisation_pct, false);
            const color = st === 'normal' ? palette.route.normal : palette.state[st];
            return (
              <Circle
                key={`heat:${u.site_id}`}
                center={[u.latitude!, u.longitude!]}
                radius={Math.max(400, Math.min(2000, u.total * 8))}
                pathOptions={{ fillColor: color, fillOpacity: 0.18, color, weight: 1, opacity: 0.35 }}
                interactive={false}
              />
            );
          })}

          {layers.routes && routes.map(({ route, positions, style }) => {
            const sel = liveSelection?.type === 'route' && liveSelection.route.id === route.id;
            return (
              <Polyline
                key={`route:${route.id}`}
                positions={positions}
                pathOptions={{
                  color: sel ? palette.select : palette.route[style.state],
                  weight: style.weight + (sel ? 2 : 0),
                  dashArray: style.dashArray,
                  opacity: 0.9,
                  lineCap: 'round',
                }}
                eventHandlers={{ click: () => selectRoute(route) }}
              >
                <Tooltip sticky>{route.cable_type ?? 'Fiber route'} · {route.status}</Tooltip>
              </Polyline>
            );
          })}

          {layers.subscribers && subscribers.map(x => (
            <CircleMarker
              key={`sub:${x.id}`}
              center={[x.latitude!, x.longitude!]}
              radius={3}
              interactive={false}
              pathOptions={{ color: palette.route.unknown, fillColor: palette.route.unknown, fillOpacity: 0.6, weight: 0 }}
            />
          ))}

          <AssetMarkers assets={visibleAssets} palette={palette} icons={icons} selectedKey={selectedKey} onSelect={selectAsset} />

          {trace && trace.hops.length > 1 && (
            <Polyline
              positions={trace.hops.map(h => [h.asset.lat, h.asset.lng] as [number, number])}
              pathOptions={{ color: palette.select, weight: 3, dashArray: '1 8', lineCap: 'round', opacity: 1 }}
              interactive={false}
            />
          )}

          {layers.alarms && alarms.map(({ asset, severity }) => (
            <Marker
              key={`alarm:${asset.key}`}
              position={[asset.lat, asset.lng]}
              icon={icons.alarm(severity, asset.key === selectedKey)}
              zIndexOffset={1000}
              keyboard
              eventHandlers={{
                click: () => selectAsset(asset),
                add: e => {
                  (e.target as L.Marker).getElement()?.setAttribute(
                    'aria-label',
                    `${SEVERITY_META[severity].label} incident at ${KIND_LABEL[asset.kind]} ${asset.label}: ${asset.incidents.length} open`,
                  );
                },
              }}
            >
              <Tooltip direction="top" offset={[0, -12]}>
                {asset.incidents.length} open · <span style={{ fontFamily: 'var(--font-mono)' }}>{asset.label}</span>
              </Tooltip>
            </Marker>
          ))}
        </MapContainer>
      )}

      {view === 'list' && palette && <AssetList assets={assets} layers={layers} palette={palette} onShow={showAsset} />}

      {/* ── Floating controls ── */}
      {palette && (
        <div className={`${s.overlay} ${s.topLeft}`}>
          <MapSearch assets={assets} palette={palette} onPick={showAsset} />
          {view === 'map' && layersOpen && (
            <LayerPanel layers={layers} onToggle={toggleLayer} counts={counts} palette={palette} onCall={onCall} onClose={() => setLayersOpen(false)} />
          )}
        </div>
      )}

      <div className={`${s.overlay} ${s.topRight} ${inspectorOpen && view === 'map' ? s.withInspector : ''}`}>
        <GlassToolbar label="Map view">
          <button type="button" className={s.seg} aria-pressed={view === 'map'} onClick={() => setView('map')}>
            <MapIcon size={14} aria-hidden="true" style={{ verticalAlign: -2, marginRight: 6 }} />Map
          </button>
          <button type="button" className={s.seg} aria-pressed={view === 'list'} onClick={() => setView('list')}>
            <List size={14} aria-hidden="true" style={{ verticalAlign: -2, marginRight: 6 }} />List
          </button>
          {view === 'map' && (
            <>
              <GlassToolbarDivider />
              <GlassButton shape="icon" aria-label={layersOpen ? 'Hide layers' : 'Show layers'} aria-pressed={layersOpen} icon={<Layers size={16} />} onClick={() => setLayersOpen(o => !o)} />
              <div role="group" aria-label="Basemap style" className={s.segGroup}>
                <button type="button" className={s.seg} aria-pressed={basemap.id === 'osm-dark'} onClick={() => pickBasemap(DARK_MAP)}>
                  <Moon size={14} aria-hidden="true" style={{ verticalAlign: -2, marginRight: 6 }} />Dark
                </button>
                <button type="button" className={s.seg} aria-pressed={basemap.id === 'osm'} onClick={() => pickBasemap(LIGHT_MAP)}>
                  <Sun size={14} aria-hidden="true" style={{ verticalAlign: -2, marginRight: 6 }} />Light
                </button>
              </div>
              <GlassMenu
                label="More basemaps"
                placement="bottom-end"
                surface="console"
                header={<div style={{ padding: '6px 10px', fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>Basemap</div>}
                items={BASEMAPS.map(b => ({
                  id: b.id,
                  label: b.label,
                  hint: b.id === basemap.id ? 'Current' : undefined,
                  onSelect: () => pickBasemap(b),
                }))}
                renderTrigger={p => (
                  <GlassButton {...p} shape="icon" aria-label={`More basemaps (current: ${basemap.label})`} icon={<MoreHorizontal size={16} />} />
                )}
              />
            </>
          )}
        </GlassToolbar>
      </div>

      {view === 'map' && (
        <div className={`${s.overlay} ${s.bottomRight} ${inspectorOpen ? s.withInspector : ''}`}>
          <GlassToolbar label="Zoom" orientation="vertical">
            <GlassButton shape="icon" aria-label="Zoom in" icon={<Plus size={16} />} onClick={() => map?.zoomIn()} />
            <GlassButton shape="icon" aria-label="Zoom out" icon={<Minus size={16} />} onClick={() => map?.zoomOut()} />
            <GlassToolbarDivider />
            <GlassButton shape="icon" aria-label="Show the whole network" icon={<Maximize2 size={16} />} onClick={fitAll} disabled={allPoints.length === 0} />
          </GlassToolbar>
        </div>
      )}

      {view === 'map' && (
        <div ref={statusRef} className={`liquid-glass-chip ${s.overlay} ${s.status}`} aria-hidden="true">
          <span>—</span><span>z11</span><span>{basemap.id === 'none' ? 'No basemap' : basemap.label}</span>
        </div>
      )}

      {/* ── States ── */}
      {mapQ.isLoading && (
        <GlassPanel readable className={`${s.overlay} ${s.notice}`} role="status">
          <p>Loading the network map…</p>
        </GlassPanel>
      )}
      {mapQ.isError && (
        <GlassPanel readable className={`${s.overlay} ${s.notice}`} role="alert">
          <h2>The network map couldn't load</h2>
          <p>Asset positions are unavailable right now. <button type="button" className={s.action} style={{ marginTop: 12 }} onClick={() => mapQ.refetch()}>Try again</button></p>
        </GlassPanel>
      )}
      {empty && view === 'map' && (
        <GlassPanel readable className={`${s.overlay} ${s.notice}`} role="status">
          <h2>No assets have coordinates yet</h2>
          <p>Upload OLTs, cabinets and splitters with latitude and longitude to place them here. <Link to="/infrastructure/upload">Go to bulk upload</Link></p>
        </GlassPanel>
      )}

      {palette && view === 'map' && (
        <MapInspector
          selection={liveSelection}
          palette={palette}
          util={utilBySite}
          cabinetSplitters={cabinetSplitters}
          trace={trace}
          onTrace={runTrace}
          onZoom={zoomToSelection}
          onClose={closeInspector}
        />
      )}

      <p className={s.srOnly} aria-live="polite">
        {mapQ.isSuccess ? `${visibleAssets.length} assets shown, ${counts.routes} routes, ${alarms.length} assets with open incidents.` : ''}
      </p>

    </div>
  );
}
