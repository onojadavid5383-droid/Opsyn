// ============================================================
// OPSYN NETWORK MAP — trace highlight (Phase 3).
// The trace's own geometry (GET /network/assets/{id}/trace) as a GeoJSON
// source drawn over the network, which NetworkLayers dims meanwhile:
//   trace-cable   the cables walked, brand teal on a white casing
//   trace-link    links with no cable (patch / split / parent FDT), dashed:
//                 they are logical, not a route on the ground
//   trace-node    rings: start (dark, thick), root OLT (teal, filled),
//                 path (teal), branches (grey)
//   trace-icon    the traced assets' plates at full strength
// Frames the trace once when it arrives.
// ============================================================

import { useEffect, useRef } from 'react';
import type { GeoJSONSource } from 'maplibre-gl';
import type { NetTrace } from '@shared';
import { useMapInstance } from './mapContext';
import { assetIconSizeExpr, cableWidth, SELECT_COLOR } from './symbology';

const SOURCE = 'trace';
const LAYERS = ['trace-cable-casing', 'trace-cable', 'trace-link', 'trace-node', 'trace-icon'];
const START_COLOR = '#0B1520';
const BRANCH_COLOR = '#76879B';

export function TraceLayer({ trace }: { trace: NetTrace | undefined }) {
  const { map } = useMapInstance();
  const framed = useRef<string | null>(null);

  useEffect(() => {
    map.addSource(SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({
      id: 'trace-cable-casing', type: 'line', source: SOURCE, filter: ['==', ['get', 'kind'], 'cable'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#FFFFFF', 'line-width': cableWidth(1.4, 5) },
    });
    map.addLayer({
      id: 'trace-cable', type: 'line', source: SOURCE, filter: ['==', ['get', 'kind'], 'cable'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': SELECT_COLOR, 'line-width': cableWidth(1.4, 1) },
    });
    map.addLayer({
      id: 'trace-link', type: 'line', source: SOURCE, filter: ['==', ['get', 'kind'], 'link'],
      paint: { 'line-color': SELECT_COLOR, 'line-width': 2.5, 'line-dasharray': [1.5, 1.5] },
    });
    map.addLayer({
      id: 'trace-node', type: 'circle', source: SOURCE, filter: ['==', ['get', 'kind'], 'asset'],
      paint: {
        'circle-radius': ['match', ['get', 'role'], 'start', 20, 'root', 20, 16],
        'circle-color': ['match', ['get', 'role'], 'root', SELECT_COLOR, '#FFFFFF'],
        'circle-opacity': ['match', ['get', 'role'], 'root', 0.25, 0],
        'circle-stroke-width': ['match', ['get', 'role'], 'start', 4, 'root', 3.5, 2.5],
        'circle-stroke-color': ['match', ['get', 'role'], 'start', START_COLOR, 'branch', BRANCH_COLOR, SELECT_COLOR],
      },
    });
    map.addLayer({
      id: 'trace-icon', type: 'symbol', source: SOURCE, filter: ['==', ['get', 'kind'], 'asset'],
      layout: {
        'icon-image': ['concat', 'net-', ['get', 'asset_type'], '-ok'],
        'icon-size': assetIconSizeExpr, 'icon-allow-overlap': true, 'icon-ignore-placement': true,
      },
    });
    return () => {
      if (!map.getStyle()) return;
      for (const id of [...LAYERS].reverse()) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SOURCE)) map.removeSource(SOURCE);
    };
  }, [map]);

  useEffect(() => {
    const src = map.getSource(SOURCE) as GeoJSONSource | undefined;
    src?.setData((trace?.geometry ?? { type: 'FeatureCollection', features: [] }) as GeoJSON.FeatureCollection);
    if (!trace) { framed.current = null; return; }
    const key = `${trace.start_id}:${trace.direction}`;
    if (framed.current === key) return;
    framed.current = key;
    const pts = trace.hops.map(h => [h.asset.lng, h.asset.lat] as [number, number]);
    if (pts.length < 2) return;
    const lngs = pts.map(p => p[0]);
    const lats = pts.map(p => p[1]);
    map.fitBounds([[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
      { padding: { top: 90, bottom: 220, left: 80, right: 80 }, maxZoom: 18, duration: 600 });
  }, [map, trace]);

  return null;
}
