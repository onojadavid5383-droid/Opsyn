// ============================================================
// OPSYN NETWORK MAP — live network layers from the MVT endpoint.
//
// Source  'network'  vector tiles from GET /gis/tiles/network/{z}/{x}/{y}.mvt
//                    (?rev= the registry revision — a write moves it and the
//                    source re-fetches; nothing stale is ever drawn)
// Layers, bottom → top:
//   net-cable-casing   white under-stroke
//   net-cable          category colour / width (faulty = red)
//   net-cable-fault    white dashes over faulty cables
//   net-cable-select   brand halo under the selected cable
//   net-asset-select   brand disc under the selected asset
//   net-asset-capacity capacity ring (util_pct from the tile), off by default
//   net-assets         the marker plates (markerImages.ts)
// Visibility per asset type / cable category is a filter on one layer
// each, driven by the panel (store.hidden), not 27 separate layers.
// ============================================================

import { useEffect, useState } from 'react';
import type { ExpressionSpecification, MapGeoJSONFeature, MapMouseEvent, VectorTileSource } from 'maplibre-gl';
import type { GisLayerRegistry, NetAssetType, NetCableCategory, NetLifecycleStatus } from '@shared';
import { tileUrlTemplate } from '../../api/network.api';
import { useMapInstance } from './mapContext';
import { addMarkerImages } from './markerImages';
import { overlayBefore } from './mapMath';
import {
  ASSET_TYPES, CABLE_CATEGORIES, FAULT_COLOR, SELECT_COLOR, assetIconExpr, assetIconSizeExpr, assetSortExpr,
  cableCasingWidthExpr, cableColorExpr, cableWidth, cableWidthExpr, inListFilter,
} from './symbology';

export const SOURCE_ID = 'network';
export const ASSET_LAYER = 'net-assets';
export const CABLE_LAYER = 'net-cable';
const LAYER_IDS = ['net-cable-casing', CABLE_LAYER, 'net-cable-fault', 'net-cable-select', 'net-asset-select', 'net-asset-capacity', ASSET_LAYER];

// Capacity view (Phase 3): a ring from the tile's util_pct — amber from the
// warning threshold, red and thicker from the critical one
const CAPACITY_WARN = '#C77700';

export interface PickedAsset {
  kind: 'asset';
  id: string;
  asset_code: string;
  asset_type: NetAssetType;
  name: string;
  lifecycle_status: NetLifecycleStatus;
  lngLat: [number, number];
}
export interface PickedCable {
  kind: 'cable';
  id: string;
  asset_code: string;
  cable_category: NetCableCategory;
  lifecycle_status: NetLifecycleStatus;
  fiber_count: number | null;
  length_m: number | null;
  route_method: string;
  lngLat: [number, number];
}
export type Picked = PickedAsset | PickedCable;

function toPicked(f: MapGeoJSONFeature, click: [number, number]): Picked {
  const p = f.properties as Record<string, string | number | null>;
  if (f.layer.id === ASSET_LAYER) {
    const coords = f.geometry.type === 'Point' ? (f.geometry.coordinates as [number, number]) : click;
    return {
      kind: 'asset', id: String(p.id), asset_code: String(p.asset_code),
      asset_type: p.asset_type as NetAssetType, name: String(p.name ?? ''),
      lifecycle_status: p.lifecycle_status as NetLifecycleStatus, lngLat: coords,
    };
  }
  return {
    kind: 'cable', id: String(p.id), asset_code: String(p.asset_code),
    cable_category: p.cable_category as NetCableCategory,
    lifecycle_status: p.lifecycle_status as NetLifecycleStatus,
    fiber_count: p.fiber_count == null ? null : Number(p.fiber_count),
    length_m: p.length_m == null ? null : Number(p.length_m),
    route_method: String(p.route_method ?? ''), lngLat: click,
  };
}

interface Props {
  registry:   GisLayerRegistry;
  /** A trace is shown: fade the rest of the network behind it */
  dimmed?:       boolean;
  showCapacity?: boolean;
  /** From the catalogue; used for the capacity rings */
  thresholds?:   { warning: number; critical: number };
  onContextMenu?: (picked: Picked, point: { x: number; y: number }) => void;
  hidden:     string[];
  selectedId: string | null;
  onPick:     (picked: Picked | null) => void;
  onTileError?: (failed: boolean) => void;
  /** false in design mode: the live network is context, not clickable */
  interactive?: boolean;
}

const DEFAULT_THRESHOLDS = { warning: 70, critical: 90 };

export function NetworkLayers({
  registry, hidden, selectedId, onPick, onTileError,
  dimmed = false, showCapacity = false, thresholds = DEFAULT_THRESHOLDS, onContextMenu, interactive = true,
}: Props) {
  const { map } = useMapInstance();
  const [ready, setReady] = useState(false);
  const tileUrl = tileUrlTemplate(registry);

  // ── Source + layers: once per map ────────────────────────
  useEffect(() => {
    let cancelled = false;
    addMarkerImages(map).then(() => {
      if (cancelled || map.getSource(SOURCE_ID)) return;
      map.addSource(SOURCE_ID, {
        type: 'vector',
        tiles: [tileUrl],
        minzoom: registry.tiles.min_zoom,
        maxzoom: registry.tiles.max_zoom,
      });
      const cables = registry.tiles.source_layers.cables;
      const assets = registry.tiles.source_layers.assets;
      const before = overlayBefore(map);
      map.addLayer({
        id: 'net-cable-casing', type: 'line', source: SOURCE_ID, 'source-layer': cables,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#FFFFFF', 'line-opacity': 0.9, 'line-width': cableCasingWidthExpr },
      }, before);
      map.addLayer({
        id: CABLE_LAYER, type: 'line', source: SOURCE_ID, 'source-layer': cables,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': cableColorExpr, 'line-width': cableWidthExpr },
      }, before);
      // Faulty cables are red AND broken by white gaps — colour is never the only signal
      map.addLayer({
        id: 'net-cable-fault', type: 'line', source: SOURCE_ID, 'source-layer': cables,
        filter: ['==', ['get', 'lifecycle_status'], 'FAULTY'],
        layout: { 'line-join': 'round' },
        paint: { 'line-color': '#FFFFFF', 'line-width': cableWidth(0.6), 'line-dasharray': [1.2, 2] },
      }, before);
      map.addLayer({
        id: 'net-cable-select', type: 'line', source: SOURCE_ID, 'source-layer': cables,
        filter: ['==', ['get', 'id'], ''],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': SELECT_COLOR, 'line-opacity': 0.45, 'line-width': cableWidth(1, 8) },
      }, CABLE_LAYER);
      map.addLayer({
        id: 'net-asset-select', type: 'circle', source: SOURCE_ID, 'source-layer': assets,
        filter: ['==', ['get', 'id'], ''],
        paint: {
          'circle-radius': 22, 'circle-color': SELECT_COLOR, 'circle-opacity': 0.22,
          'circle-stroke-color': SELECT_COLOR, 'circle-stroke-width': 2.5,
        },
      }, before);
      map.addLayer({
        id: 'net-asset-capacity', type: 'circle', source: SOURCE_ID, 'source-layer': assets,
        filter: ['>=', ['coalesce', ['get', 'util_pct'], -1], 70],
        layout: { visibility: 'none' },
        paint: { 'circle-radius': 17, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-width': 3, 'circle-stroke-color': CAPACITY_WARN },
      }, before);
      map.addLayer({
        id: ASSET_LAYER, type: 'symbol', source: SOURCE_ID, 'source-layer': assets,
        layout: {
          'icon-image': assetIconExpr,
          'icon-size': assetIconSizeExpr,
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
          'symbol-sort-key': assetSortExpr,
        },
      }, before);
      setReady(true);
    }).catch(() => onTileError?.(true));

    return () => {
      cancelled = true;
      // The map may already be gone when the page unmounts
      if (!map.getStyle()) return;
      for (const id of [...LAYER_IDS].reverse()) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SOURCE_ID)) map.removeSource(SOURCE_ID);
    };
    // Built once; tile URL and filters are updated by the effects below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  // ── New revision → new tile URL → fresh tiles ────────────
  useEffect(() => {
    if (!ready) return;
    (map.getSource(SOURCE_ID) as VectorTileSource | undefined)?.setTiles([tileUrl]);
  }, [map, ready, tileUrl]);

  // ── Panel visibility ─────────────────────────────────────
  useEffect(() => {
    if (!ready) return;
    const types = ASSET_TYPES.filter(t => !hidden.includes(t));
    const cats = CABLE_CATEGORIES.filter(c => !hidden.includes(c));
    map.setFilter(ASSET_LAYER, inListFilter('asset_type', types));
    map.setFilter('net-asset-select', ['all', inListFilter('asset_type', types), ['==', ['get', 'id'], selectedId ?? '']]);
    for (const id of ['net-cable-casing', CABLE_LAYER]) map.setFilter(id, inListFilter('cable_category', cats));
    map.setFilter('net-cable-select', ['all', inListFilter('cable_category', cats), ['==', ['get', 'id'], selectedId ?? '']]);
    map.setFilter('net-cable-fault', ['all', inListFilter('cable_category', cats), ['==', ['get', 'lifecycle_status'], 'FAULTY']]);
  }, [map, ready, hidden, selectedId]);

  // ── Trace dimming and capacity rings ─────────────────────
  useEffect(() => {
    if (!ready) return;
    map.setPaintProperty(ASSET_LAYER, 'icon-opacity', dimmed ? 0.3 : 1);
    map.setPaintProperty(CABLE_LAYER, 'line-opacity', dimmed ? 0.25 : 1);
    map.setPaintProperty('net-cable-casing', 'line-opacity', dimmed ? 0.3 : 0.9);
    map.setLayoutProperty('net-asset-capacity', 'visibility', showCapacity ? 'visible' : 'none');
    const pct: ExpressionSpecification = ['coalesce', ['get', 'util_pct'], -1];
    map.setFilter('net-asset-capacity', ['all',
      inListFilter('asset_type', ASSET_TYPES.filter(t => !hidden.includes(t))),
      ['>=', pct, thresholds.warning]]);
    map.setPaintProperty('net-asset-capacity', 'circle-stroke-color',
      ['case', ['>=', pct, thresholds.critical], FAULT_COLOR, CAPACITY_WARN]);
    map.setPaintProperty('net-asset-capacity', 'circle-stroke-width',
      ['case', ['>=', pct, thresholds.critical], 5, 3]);
  }, [map, ready, dimmed, showCapacity, thresholds.warning, thresholds.critical, hidden]);

  // ── Tile errors; picking + cursor ────────────────────────
  useEffect(() => {
    if (!ready) return;
    let tileErrors = 0;
    const onError = (e: { sourceId?: string }) => {
      if (e.sourceId === SOURCE_ID && ++tileErrors >= 3) onTileError?.(true);
    };
    const onData = (e: { sourceId?: string; tile?: unknown }) => {
      if (e.sourceId === SOURCE_ID && e.tile) { tileErrors = 0; onTileError?.(false); }
    };
    map.on('error', onError);
    map.on('sourcedata', onData);
    return () => { map.off('error', onError); map.off('sourcedata', onData); };
  }, [map, ready, onTileError]);

  useEffect(() => {
    if (!ready || !interactive) return;
    const pickable = [ASSET_LAYER, CABLE_LAYER];
    const hit = (e: MapMouseEvent) => {
      const { x, y } = e.point;
      return map.queryRenderedFeatures([[x - 6, y - 6], [x + 6, y + 6]], { layers: pickable });
    };
    const onClick = (e: MapMouseEvent) => {
      const features = hit(e);
      // Assets win over the cables passing under them
      const f = features.find(ft => ft.layer.id === ASSET_LAYER) ?? features[0];
      onPick(f ? toPicked(f, [e.lngLat.lng, e.lngLat.lat]) : null);
    };
    const onMove = (e: MapMouseEvent) => {
      map.getCanvas().style.cursor = hit(e).length ? 'pointer' : '';
    };
    // Right-click an asset: the page opens its trace menu
    const onMenu = (e: MapMouseEvent) => {
      const f = hit(e).find(ft => ft.layer.id === ASSET_LAYER);
      if (!f || !onContextMenu) return;
      e.preventDefault();
      onContextMenu(toPicked(f, [e.lngLat.lng, e.lngLat.lat]), e.point);
    };
    map.on('click', onClick);
    map.on('contextmenu', onMenu);
    map.on('mousemove', onMove);
    return () => {
      map.off('click', onClick);
      map.off('contextmenu', onMenu);
      map.off('mousemove', onMove);
    };
  }, [map, ready, interactive, onPick, onContextMenu]);

  return null;
}
