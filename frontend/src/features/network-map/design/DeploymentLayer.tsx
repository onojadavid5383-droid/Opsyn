// ============================================================
// OPSYN DESIGN — deployment on the map (Network GIS Phase 10).
//   DeploymentStates  every device ringed and every cable overdrawn in the
//                     colour of where it is in the build: not started,
//                     installed, testing, verified (the legend is in the
//                     deployment drawer; the state is also in the popup)
//   AsBuiltPicker     an as-built capture: each click places the device /
//                     adds a point of the cable's real route, drawn dashed
// ============================================================

import { useEffect } from 'react';
import type { ExpressionSpecification, GeoJSONSource, Map as MlMap, MapMouseEvent } from 'maplibre-gl';
import type { NetLifecycleStatus } from '@shared';
import { useMapInstance } from '../mapContext';
import { useDesignFeatures } from './designQueries';
import { useDesignMapStore, type AsBuiltCapture } from './designStore';

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

/** The build, in order: each state its own colour (the drawer's legend and bars use the same) */
export const DEPLOY_STEPS: { state: NetLifecycleStatus; label: string; color: string }[] = [
  { state: 'CONSTRUCTION', label: 'Not installed', color: '#C2410C' },
  { state: 'INSTALLED',    label: 'Installed',     color: '#2563EB' },
  { state: 'TESTING',      label: 'Testing',       color: '#7C3AED' },
  { state: 'VERIFIED',     label: 'Verified',      color: '#15803D' },
];
const OTHER = '#94A3B8';

const stateColor = ['match', ['get', 'lifecycle_status'],
  ...DEPLOY_STEPS.flatMap(s => [s.state, s.color]), OTHER] as unknown as ExpressionSpecification;

function drop(map: MlMap, layers: string[], sources: string[]) {
  if (!map.getStyle()) return;
  for (const id of layers) if (map.getLayer(id)) map.removeLayer(id);
  for (const id of sources) if (map.getSource(id)) map.removeSource(id);
}

export function DeploymentStates({ designId }: { designId: string }) {
  const { map } = useMapInstance();
  const ws = useDesignFeatures(designId);
  useEffect(() => {
    map.addSource('design-deploy', { type: 'geojson', data: EMPTY });
    map.addLayer({ id: 'design-deploy-cable', type: 'line', source: 'design-deploy', filter: ['==', ['get', 'kind'], 'cable'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': stateColor, 'line-width': ['interpolate', ['linear'], ['zoom'], 13, 2.5, 18, 6], 'line-opacity': 0.9 } });
    map.addLayer({ id: 'design-deploy-ring', type: 'circle', source: 'design-deploy',
      filter: ['all', ['==', ['get', 'kind'], 'asset'], ['==', ['geometry-type'], 'Point']],
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 13, 8, 18, 17], 'circle-color': 'rgba(0,0,0,0)',
               'circle-stroke-color': stateColor, 'circle-stroke-width': 3 } });
    return () => drop(map, ['design-deploy-ring', 'design-deploy-cable'], ['design-deploy']);
  }, [map]);
  useEffect(() => {
    (map.getSource('design-deploy') as GeoJSONSource | undefined)?.setData(ws.data ?? EMPTY);
  }, [map, ws.data]);
  return null;
}

function sketchOf(a: AsBuiltCapture): GeoJSON.FeatureCollection {
  const pts = a.points.map(p => ({ type: 'Feature' as const, properties: {}, geometry: { type: 'Point' as const, coordinates: p } }));
  const line = a.kind === 'cable' && a.points.length > 1
    ? [{ type: 'Feature' as const, properties: {}, geometry: { type: 'LineString' as const, coordinates: a.points } }] : [];
  return { type: 'FeatureCollection', features: [...line, ...pts] };
}

export function AsBuiltPicker() {
  const { map } = useMapInstance();
  const asbuilt = useDesignMapStore(s => s.asbuilt);
  const addPoint = useDesignMapStore(s => s.addAsBuiltPoint);
  useEffect(() => {
    const canvas = map.getCanvas();
    canvas.style.cursor = 'crosshair';
    map.addSource('design-asbuilt', { type: 'geojson', data: EMPTY });
    map.addLayer({ id: 'design-asbuilt-line', type: 'line', source: 'design-asbuilt', filter: ['==', ['geometry-type'], 'LineString'],
      paint: { 'line-color': '#0B1520', 'line-width': 3, 'line-dasharray': [2, 1.5] } });
    map.addLayer({ id: 'design-asbuilt-pt', type: 'circle', source: 'design-asbuilt', filter: ['==', ['geometry-type'], 'Point'],
      paint: { 'circle-radius': 5, 'circle-color': '#FFFFFF', 'circle-stroke-color': '#0B1520', 'circle-stroke-width': 2.5 } });
    const onClick = (e: MapMouseEvent) => addPoint([e.lngLat.lng, e.lngLat.lat]);
    map.on('click', onClick);
    return () => {
      map.off('click', onClick);
      canvas.style.cursor = '';
      drop(map, ['design-asbuilt-pt', 'design-asbuilt-line'], ['design-asbuilt']);
    };
  }, [map, addPoint]);
  useEffect(() => {
    (map.getSource('design-asbuilt') as GeoJSONSource | undefined)?.setData(asbuilt ? sketchOf(asbuilt) : EMPTY);
  }, [map, asbuilt]);
  return null;
}
