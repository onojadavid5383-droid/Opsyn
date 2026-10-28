// ============================================================
// OPSYN DESIGN — the design drawn over the (dimmed) live network.
//
// Sources and layers, bottom → top:
//   design-mask        the world outside the boundary, shaded, so the
//                      design area reads as a lit window
//   design-boundary    the boundary: pale fill + dashed ink edge
//   design-in-<key>    one GeoJSON source per input layer (roads,
//                      homepasses, poles, buildings, pickups, existing
//                      structures), fetched only while it is switched on
//   design-ws          the working set, drawn exactly like the live
//                      network (same icon images and cable expressions)
//   design-issue       the issue chosen in the validation panel
// Looking back (Phase 8), the working set is swapped for a version's
// features (the `features` prop) — same layers, same symbology.
// Clicking a working-set feature shows the usual popup (no "Details": the
// inspector reads the live network only).
// ============================================================

import { useEffect, useState } from 'react';
import type { GeoJSONSource, LayerSpecification, Map as MlMap, MapMouseEvent } from 'maplibre-gl';
import type { Design, DesignInputLayerKey, DesignIssue } from '@shared';
import { useMapInstance } from '../mapContext';
import { addMarkerImages } from '../markerImages';
import type { Picked } from '../NetworkLayers';
import {
  SELECT_COLOR, assetIconExpr, assetIconSizeExpr, assetSortExpr, cableCasingWidthExpr, cableColorExpr, cableWidthExpr,
} from '../symbology';
import { INPUT_LAYERS, INPUT_META, SEVERITY_COLOR, geometryBounds, isPointBox } from './designFormat';
import { useDesignFeatures, useDesignInputFeatures } from './designQueries';

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };
const BOUNDARY_INK = '#0B1520';
export const WS_ASSET_LAYER = 'design-ws-assets';
export const WS_CABLE_LAYER = 'design-ws-cables';

function setData(map: MlMap, source: string, data: GeoJSON.FeatureCollection | GeoJSON.Feature) {
  (map.getSource(source) as GeoJSONSource | undefined)?.setData(data);
}

function removeAll(map: MlMap, layers: string[], sources: string[]) {
  if (!map.getStyle()) return;          // the map may be gone already
  for (const id of [...layers].reverse()) if (map.getLayer(id)) map.removeLayer(id);
  for (const id of sources) if (map.getSource(id)) map.removeSource(id);
}

/** The world with the boundary cut out — the shade outside the design */
function maskOf(boundary: Design['boundary']): GeoJSON.Feature | GeoJSON.FeatureCollection {
  if (!boundary) return EMPTY;
  const polys = boundary.coordinates as number[][][][];
  const world = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
  return {
    type: 'Feature', properties: {},
    geometry: { type: 'Polygon', coordinates: [world, ...polys.map(p => p[0])] },
  };
}

// ── Boundary ─────────────────────────────────────────────────

function BoundaryLayer({ boundary }: { boundary: Design['boundary'] }) {
  const { map } = useMapInstance();
  useEffect(() => {
    map.addSource('design-mask', { type: 'geojson', data: EMPTY });
    map.addSource('design-boundary', { type: 'geojson', data: EMPTY });
    map.addLayer({ id: 'design-mask', type: 'fill', source: 'design-mask',
      paint: { 'fill-color': BOUNDARY_INK, 'fill-opacity': 0.12 } });
    map.addLayer({ id: 'design-boundary-fill', type: 'fill', source: 'design-boundary',
      paint: { 'fill-color': SELECT_COLOR, 'fill-opacity': 0.04 } });
    map.addLayer({ id: 'design-boundary-line', type: 'line', source: 'design-boundary',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': BOUNDARY_INK, 'line-width': 2, 'line-dasharray': [3, 2] } });
    return () => removeAll(map, ['design-mask', 'design-boundary-fill', 'design-boundary-line'], ['design-mask', 'design-boundary']);
  }, [map]);
  useEffect(() => {
    setData(map, 'design-boundary', boundary ? { type: 'Feature', properties: {}, geometry: boundary as GeoJSON.MultiPolygon } : EMPTY);
    setData(map, 'design-mask', maskOf(boundary));
  }, [map, boundary]);
  return null;
}

// ── Inputs ───────────────────────────────────────────────────

function inputLayers(key: DesignInputLayerKey, source: string): LayerSpecification[] {
  const { color } = INPUT_META[key];
  const id = (s: string) => `${source}-${s}`;
  switch (key) {
    case 'road':
      // The routing graph: a slate band the cables will sit on
      return [
        { id: id('casing'), type: 'line', source, layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#FFFFFF', 'line-width': ['interpolate', ['linear'], ['zoom'], 12, 3, 17, 9] } },
        { id: id('line'), type: 'line', source, layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': color, 'line-opacity': 0.85, 'line-width': ['interpolate', ['linear'], ['zoom'], 12, 1.5, 17, 5] } },
      ];
    case 'building':
      return [
        { id: id('fill'), type: 'fill', source, filter: ['!=', ['geometry-type'], 'Point'],
          paint: { 'fill-color': color, 'fill-opacity': 0.25, 'fill-outline-color': color } },
        { id: id('point'), type: 'circle', source, filter: ['==', ['geometry-type'], 'Point'],
          paint: { 'circle-radius': 3, 'circle-color': color } },
      ];
    case 'homepass':
      // Rings sized by customers: a block of 8 reads bigger than a house
      return [{ id: id('point'), type: 'circle', source, paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'],
          12, 2, 16, ['+', 3.5, ['*', 0.6, ['min', ['coalesce', ['get', 'customers'], 1], 12]]]],
        'circle-color': '#FFFFFF', 'circle-stroke-color': color,
        'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 12, 1, 16, 2],
      } }];
    case 'pickup':
      return [{ id: id('point'), type: 'circle', source, paint: {
        'circle-radius': 7, 'circle-color': color, 'circle-stroke-color': '#FFFFFF', 'circle-stroke-width': 2.5,
      } }];
    default:
      // Poles and existing structures: small solid dots with a white rim
      return [{ id: id('point'), type: 'circle', source, paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 13, 2, 17, 4.5],
        'circle-color': color, 'circle-stroke-color': '#FFFFFF', 'circle-stroke-width': 1.2,
      } }];
  }
}

function InputLayer({ designId, layerKey, visible, count }: {
  designId: string; layerKey: DesignInputLayerKey; visible: boolean; count: number;
}) {
  const { map } = useMapInstance();
  const source = `design-in-${layerKey}`;
  const q = useDesignInputFeatures(designId, layerKey, visible && count > 0);
  const [layers] = useState(() => inputLayers(layerKey, source));

  useEffect(() => {
    map.addSource(source, { type: 'geojson', data: EMPTY });
    // Inputs go under the working set and the issue ring, whichever exists
    const before = map.getLayer('design-ws-casing') ? 'design-ws-casing' : undefined;
    for (const l of layers) map.addLayer(l, before);
    return () => removeAll(map, layers.map(l => l.id), [source]);
  }, [map, source, layers]);

  useEffect(() => {
    setData(map, source, visible && count > 0 && q.data ? q.data : EMPTY);
  }, [map, source, visible, count, q.data]);
  return null;
}

// ── Working set ──────────────────────────────────────────────

const WS_LAYERS = ['design-ws-casing', WS_CABLE_LAYER, WS_ASSET_LAYER];

function WorkingSet({ designId, onPick, features }: {
  designId: string; onPick: (p: Picked | null) => void; features?: GeoJSON.FeatureCollection;
}) {
  const { map } = useMapInstance();
  const ws = useDesignFeatures(designId);
  const shown = features ?? ws.data;
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    addMarkerImages(map).then(() => {
      if (cancelled || map.getSource('design-ws')) return;
      map.addSource('design-ws', { type: 'geojson', data: EMPTY });
      const before = map.getLayer('design-issue-line') ? 'design-issue-line' : undefined;
      map.addLayer({ id: 'design-ws-casing', type: 'line', source: 'design-ws', filter: ['==', ['get', 'kind'], 'cable'],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#FFFFFF', 'line-opacity': 0.9, 'line-width': cableCasingWidthExpr } }, before);
      map.addLayer({ id: WS_CABLE_LAYER, type: 'line', source: 'design-ws', filter: ['==', ['get', 'kind'], 'cable'],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': cableColorExpr, 'line-width': cableWidthExpr } }, before);
      map.addLayer({ id: WS_ASSET_LAYER, type: 'symbol', source: 'design-ws', filter: ['==', ['get', 'kind'], 'asset'],
        layout: {
          'icon-image': assetIconExpr, 'icon-size': assetIconSizeExpr, 'icon-allow-overlap': true,
          'icon-ignore-placement': true, 'symbol-sort-key': assetSortExpr,
        } }, before);
      setReady(true);
    }).catch(() => { /* images failed: the live layers report tile trouble already */ });
    return () => { cancelled = true; removeAll(map, WS_LAYERS, ['design-ws']); };
  }, [map]);

  useEffect(() => {
    if (ready) setData(map, 'design-ws', shown ?? EMPTY);
  }, [map, ready, shown]);

  useEffect(() => {
    if (!ready) return;
    const layers = [WS_ASSET_LAYER, WS_CABLE_LAYER];
    const hit = (e: MapMouseEvent) => {
      const { x, y } = e.point;
      return map.queryRenderedFeatures([[x - 6, y - 6], [x + 6, y + 6]], { layers });
    };
    const onClick = (e: MapMouseEvent) => {
      const features = hit(e);
      const f = features.find(ft => ft.layer.id === WS_ASSET_LAYER) ?? features[0];
      if (!f) { onPick(null); return; }
      const p = f.properties as Record<string, string | number | null>;
      const click: [number, number] = [e.lngLat.lng, e.lngLat.lat];
      onPick(p.kind === 'asset'
        ? { kind: 'asset', id: String(p.id), asset_code: String(p.asset_code), asset_type: p.asset_type as never,
            name: String(p.name ?? ''), lifecycle_status: p.lifecycle_status as never,
            lngLat: f.geometry.type === 'Point' ? (f.geometry.coordinates as [number, number]) : click }
        : { kind: 'cable', id: String(p.id), asset_code: String(p.asset_code), cable_category: p.cable_category as never,
            lifecycle_status: p.lifecycle_status as never,
            fiber_count: p.fiber_count == null ? null : Number(p.fiber_count),
            length_m: p.length_m == null ? null : Number(p.length_m),
            route_method: String(p.route_method ?? ''), lngLat: click });
    };
    const onMove = (e: MapMouseEvent) => { map.getCanvas().style.cursor = hit(e).length ? 'pointer' : ''; };
    map.on('click', onClick);
    map.on('mousemove', onMove);
    return () => { map.off('click', onClick); map.off('mousemove', onMove); };
  }, [map, ready, onPick]);
  return null;
}

// ── Focused issue ────────────────────────────────────────────

function IssueFocus({ issue }: { issue: DesignIssue | null }) {
  const { map } = useMapInstance();
  useEffect(() => {
    map.addSource('design-issue', { type: 'geojson', data: EMPTY });
    map.addLayer({ id: 'design-issue-line', type: 'line', source: 'design-issue',
      filter: ['!=', ['geometry-type'], 'Point'],
      paint: { 'line-color': ['get', 'color'], 'line-width': 7, 'line-opacity': 0.45 } });
    map.addLayer({ id: 'design-issue-point', type: 'circle', source: 'design-issue',
      filter: ['==', ['geometry-type'], 'Point'],
      paint: { 'circle-radius': 22, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-width': 3.5, 'circle-stroke-color': ['get', 'color'] } });
    return () => removeAll(map, ['design-issue-line', 'design-issue-point'], ['design-issue']);
  }, [map]);

  useEffect(() => {
    const g = issue?.geometry;
    setData(map, 'design-issue', g
      ? { type: 'Feature', properties: { color: SEVERITY_COLOR[issue.severity] }, geometry: g as GeoJSON.Geometry }
      : EMPTY);
    const box = geometryBounds(g);
    if (!box) return;
    if (isPointBox(box)) map.flyTo({ center: [box[0], box[1]], zoom: Math.max(map.getZoom(), 18), duration: 600 });
    else map.fitBounds([[box[0], box[1]], [box[2], box[3]]], { padding: 120, maxZoom: 18, duration: 600 });
  }, [map, issue]);
  return null;
}

// ── All of it ────────────────────────────────────────────────

interface Props {
  design:     Design;
  hidden:     DesignInputLayerKey[];
  focusIssue: DesignIssue | null;
  onPick:     (p: Picked | null) => void;
  /** Another version's features instead of the working set (Phase 8: view / compare) */
  features?:  GeoJSON.FeatureCollection;
}

export function DesignLayers({ design, hidden, focusIssue, onPick, features }: Props) {
  return (
    <>
      <BoundaryLayer boundary={design.boundary} />
      {INPUT_LAYERS.map(l => (
        <InputLayer
          key={l.key}
          designId={design.id}
          layerKey={l.key}
          visible={!hidden.includes(l.key)}
          count={design.input_counts[l.key] ?? 0}
        />
      ))}
      <WorkingSet designId={design.id} onPick={onPick} features={features} />
      <IssueFocus issue={focusIssue} />
    </>
  );
}
