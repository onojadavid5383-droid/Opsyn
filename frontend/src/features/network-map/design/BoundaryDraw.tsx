// ============================================================
// OPSYN DESIGN — draw the design boundary on the map.
// Click to place corners; click the first corner, double-click or press
// Enter to finish; Backspace removes the last corner; Esc cancels.
// The draft is checked as it is drawn (designFormat.boundaryProblem) and
// saved through PATCH /designs/{id} {boundary}, which checks it again.
// ============================================================

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { GeoJSONSource, MapMouseEvent } from 'maplibre-gl';
import { useMapInstance } from '../mapContext';
import { boundaryProblem, draftFeatures, type LngLat } from './designFormat';
import d from './Design.module.css';

const SOURCE = 'design-draft';
const LAYERS = ['design-draft-area', 'design-draft-edge', 'design-draft-vertex'];
const INK = '#0B1520';
const CLOSE_PX = 12;

interface Props {
  saving:   boolean;
  error:    string | null;
  onFinish: (points: LngLat[]) => void;
  onCancel: () => void;
}

export function BoundaryDraw({ saving, error, onFinish, onCancel }: Props) {
  const { map } = useMapInstance();
  const [points, setPoints] = useState<LngLat[]>([]);
  const [cursor, setCursor] = useState<LngLat | null>(null);
  const pointsRef = useRef(points);
  const problem = boundaryProblem(points);

  const finish = () => {
    if (saving || boundaryProblem(pointsRef.current)) return;
    onFinish(pointsRef.current);
  };
  const finishRef = useRef(finish);
  // The map handlers are bound once; they read the latest corners and finish
  useLayoutEffect(() => { pointsRef.current = points; finishRef.current = finish; });

  // Draft source + layers; the map's own double-click zoom is off meanwhile
  useEffect(() => {
    map.addSource(SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({ id: 'design-draft-area', type: 'fill', source: SOURCE, filter: ['==', ['get', 'role'], 'area'],
      paint: { 'fill-color': '#00C2A8', 'fill-opacity': 0.12 } });
    map.addLayer({ id: 'design-draft-edge', type: 'line', source: SOURCE, filter: ['==', ['get', 'role'], 'edge'],
      paint: { 'line-color': INK, 'line-width': 2, 'line-dasharray': [2, 1.5] } });
    map.addLayer({ id: 'design-draft-vertex', type: 'circle', source: SOURCE, filter: ['==', ['geometry-type'], 'Point'],
      paint: {
        'circle-radius': ['match', ['get', 'role'], 'first', 7, 5],
        'circle-color': '#FFFFFF', 'circle-stroke-color': INK, 'circle-stroke-width': 2.5,
      } });
    map.doubleClickZoom.disable();
    const canvas = map.getCanvas();
    canvas.style.cursor = 'crosshair';
    return () => {
      canvas.style.cursor = '';
      map.doubleClickZoom.enable();
      if (!map.getStyle()) return;
      for (const id of [...LAYERS].reverse()) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SOURCE)) map.removeSource(SOURCE);
    };
  }, [map]);

  useEffect(() => {
    (map.getSource(SOURCE) as GeoJSONSource | undefined)?.setData(draftFeatures(points, cursor));
  }, [map, points, cursor]);

  useEffect(() => {
    const onClick = (e: MapMouseEvent) => {
      const pts = pointsRef.current;
      // A click on the first corner closes the ring
      if (pts.length >= 3) {
        const first = map.project(pts[0]);
        if (Math.hypot(first.x - e.point.x, first.y - e.point.y) <= CLOSE_PX) { finishRef.current(); return; }
      }
      setPoints([...pts, [e.lngLat.lng, e.lngLat.lat]]);
    };
    const onDbl = (e: MapMouseEvent) => {
      e.preventDefault();
      // The double-click's second click already placed a corner on top of the last one
      setPoints(pts => (pts.length > 3 ? pts.slice(0, -1) : pts));
      window.setTimeout(() => finishRef.current(), 0);
    };
    const onMove = (e: MapMouseEvent) => setCursor([e.lngLat.lng, e.lngLat.lat]);
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === 'Escape') { e.stopPropagation(); onCancel(); }
      else if (e.key === 'Enter') finishRef.current();
      else if (e.key === 'Backspace') { e.preventDefault(); setPoints(pts => pts.slice(0, -1)); }
    };
    map.on('click', onClick);
    map.on('dblclick', onDbl);
    map.on('mousemove', onMove);
    window.addEventListener('keydown', onKey, true);
    return () => {
      map.off('click', onClick);
      map.off('dblclick', onDbl);
      map.off('mousemove', onMove);
      window.removeEventListener('keydown', onKey, true);
    };
  }, [map, onCancel]);

  return (
    <div className={d.drawHint} role="region" aria-label="Draw the design boundary">
      <p className={d.drawTitle}>Drawing the boundary</p>
      <p className={d.drawStep} aria-live="polite">
        {points.length === 0 ? 'Click the map to place the first corner.'
          : problem ?? `${points.length} corners. Click the first corner, double-click or press Enter to finish.`}
      </p>
      {error && <p className={d.err} role="alert">{error}</p>}
      <div className={d.drawActions}>
        <button type="button" className={d.solidBtn} onClick={finish} disabled={!!problem || saving}>
          {saving ? 'Saving…' : 'Use this boundary'}
        </button>
        <button type="button" className={d.ghostBtn} onClick={() => setPoints(p => p.slice(0, -1))} disabled={!points.length}>
          Undo corner
        </button>
        <button type="button" className={d.ghostBtn} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
