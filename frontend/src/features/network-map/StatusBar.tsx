// ============================================================
// OPSYN NETWORK MAP — status strip: cursor position, zoom, scale bar,
// and tile health. The scale is computed from the map's own resolution
// (web mercator, 512 px world tiles) so it can live outside the canvas.
// ============================================================

import { useEffect, useState } from 'react';
import { TriangleAlert } from 'lucide-react';
import { useMapInstance } from './mapContext';
import { scaleFor } from './mapMath';
import s from './NetworkMap.module.css';

interface Props {
  tilesFailed:   boolean;
  showCapacity?: boolean;
  thresholds?:   { warning: number; critical: number };
}

export function StatusBar({ tilesFailed, showCapacity = false, thresholds = { warning: 70, critical: 90 } }: Props) {
  const { map, basemapHealth } = useMapInstance();
  const [cursor, setCursor] = useState<{ lng: number; lat: number } | null>(null);
  const [view, setView] = useState(() => ({ zoom: map.getZoom(), lat: map.getCenter().lat }));

  useEffect(() => {
    const onMove = (e: { lngLat: { lng: number; lat: number } }) => setCursor({ lng: e.lngLat.lng, lat: e.lngLat.lat });
    const onOut = () => setCursor(null);
    const onView = () => setView({ zoom: map.getZoom(), lat: map.getCenter().lat });
    map.on('mousemove', onMove);
    map.on('mouseout', onOut);
    map.on('moveend', onView);
    map.on('zoom', onView);
    return () => {
      map.off('mousemove', onMove);
      map.off('mouseout', onOut);
      map.off('moveend', onView);
      map.off('zoom', onView);
    };
  }, [map]);

  const scale = scaleFor(view.lat, view.zoom);

  return (
    <footer className={s.status} aria-label="Map status">
      <span className={s.coords} data-live={!!cursor} aria-live="off">
        {cursor ? `${cursor.lat.toFixed(5)}, ${cursor.lng.toFixed(5)}` : 'Point at the map for coordinates'}
      </span>
      <span>Zoom {view.zoom.toFixed(1)}</span>
      <span className={s.scale} aria-label={`Scale bar ${scale.label}`}>
        <span className={s.scaleBar} style={{ width: scale.px }} aria-hidden />
        {scale.label}
      </span>
      <span className={s.statusSpacer} />
      {showCapacity && (
        <span className={s.capLegend}>
          Capacity rings: <span className={s.capRing} data-level="warn" aria-hidden="true" /> from {thresholds.warning}%
          <span className={s.capRing} data-level="critical" aria-hidden="true" /> from {thresholds.critical}% (thicker)
        </span>
      )}
      {basemapHealth === 'failed' && (
        <span className={s.statusWarn} role="status">
          <TriangleAlert size={14} aria-hidden /> Street map couldn't load on this network; assets are still shown
        </span>
      )}
      {tilesFailed && (
        <span className={s.statusWarn} role="status">
          <TriangleAlert size={14} aria-hidden /> Network layer isn't loading. Check your connection
        </span>
      )}
    </footer>
  );
}
