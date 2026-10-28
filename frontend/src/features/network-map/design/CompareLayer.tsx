// ============================================================
// OPSYN DESIGN — comparing two versions on the map (Network GIS Phase 8).
// The newer version is drawn as usual (DesignLayers, fed its features);
// over it:
//   removed   the older version's features that are gone: red, dashed
//   added     new in the newer version: a green halo
//   moved     a grey ghost where the device was, an arrow to where it is
//   rerouted  a cable's previous line, amber and dashed
// Colour is never the only signal: removed is dashed, moved has the arrow.
// ============================================================

import { useEffect } from 'react';
import type { GeoJSONSource } from 'maplibre-gl';
import type { DesignCompare } from '@shared';
import { useMapInstance } from '../mapContext';
import { CMP, compareFeatures } from './compareFeatures';

const SOURCE = 'design-cmp';
const LAYERS = ['design-cmp-old', 'design-cmp-added-line', 'design-cmp-removed-line', 'design-cmp-arrow',
  'design-cmp-added-pt', 'design-cmp-removed-pt', 'design-cmp-ghost', 'design-cmp-head'];
const HEAD = 'design-cmp-arrowhead';

function arrowhead(): ImageData | null {
  const size = 22;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.fillStyle = CMP.moved;
  ctx.strokeStyle = '#FFFFFF';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(size / 2, 2);
  ctx.lineTo(size - 4, size - 3);
  ctx.lineTo(4, size - 3);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  return ctx.getImageData(0, 0, size, size);
}

const role = (r: string) => ['==', ['get', 'role'], r] as ['==', ['get', string], string];
const isLine = ['==', ['geometry-type'], 'LineString'] as ['==', ['geometry-type'], string];
const isPoint = ['==', ['geometry-type'], 'Point'] as ['==', ['geometry-type'], string];

export function CompareLayer({ compare }: { compare: DesignCompare | undefined }) {
  const { map } = useMapInstance();

  useEffect(() => {
    if (!map.hasImage(HEAD)) {
      const img = arrowhead();
      if (img) map.addImage(HEAD, img, { pixelRatio: 2 });
    }
    map.addSource(SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({ id: 'design-cmp-old', type: 'line', source: SOURCE, filter: ['all', role('old')],
      paint: { 'line-color': CMP.rerouted, 'line-width': 3, 'line-dasharray': [2, 2], 'line-opacity': 0.9 } });
    map.addLayer({ id: 'design-cmp-added-line', type: 'line', source: SOURCE, filter: ['all', role('added'), isLine],
      layout: { 'line-cap': 'round' }, paint: { 'line-color': CMP.added, 'line-width': 9, 'line-opacity': 0.35 } });
    map.addLayer({ id: 'design-cmp-removed-line', type: 'line', source: SOURCE, filter: ['all', role('removed'), isLine],
      paint: { 'line-color': CMP.removed, 'line-width': 3, 'line-dasharray': [1.5, 1.5] } });
    map.addLayer({ id: 'design-cmp-arrow', type: 'line', source: SOURCE, filter: ['all', role('arrow')],
      layout: { 'line-cap': 'round' }, paint: { 'line-color': CMP.moved, 'line-width': 2.5, 'line-dasharray': [2, 1] } });
    map.addLayer({ id: 'design-cmp-added-pt', type: 'circle', source: SOURCE, filter: ['all', role('added'), isPoint],
      paint: { 'circle-radius': 19, 'circle-color': CMP.added, 'circle-opacity': 0.18, 'circle-stroke-color': CMP.added, 'circle-stroke-width': 3 } });
    map.addLayer({ id: 'design-cmp-removed-pt', type: 'circle', source: SOURCE, filter: ['all', role('removed'), isPoint],
      paint: { 'circle-radius': 12, 'circle-color': '#FFFFFF', 'circle-opacity': 0.85, 'circle-stroke-color': CMP.removed, 'circle-stroke-width': 3 } });
    map.addLayer({ id: 'design-cmp-ghost', type: 'circle', source: SOURCE, filter: ['all', role('ghost')],
      paint: { 'circle-radius': 12, 'circle-color': CMP.ghost, 'circle-opacity': 0.35, 'circle-stroke-color': CMP.ghost, 'circle-stroke-width': 2 } });
    map.addLayer({ id: 'design-cmp-head', type: 'symbol', source: SOURCE, filter: ['all', role('head')],
      layout: { 'icon-image': HEAD, 'icon-rotate': ['get', 'bearing'], 'icon-rotation-alignment': 'map',
                'icon-allow-overlap': true, 'icon-ignore-placement': true, 'icon-offset': [0, 14] } });
    return () => {
      if (!map.getStyle()) return;
      for (const id of [...LAYERS].reverse()) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SOURCE)) map.removeSource(SOURCE);
    };
  }, [map]);

  useEffect(() => {
    (map.getSource(SOURCE) as GeoJSONSource | undefined)?.setData(
      compare ? compareFeatures(compare) : { type: 'FeatureCollection', features: [] });
  }, [map, compare]);
  return null;
}
