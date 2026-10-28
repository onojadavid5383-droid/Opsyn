// ============================================================
// OPSYN NETWORK MAP — small pure helpers (display only; engineering
// maths such as cable length always comes from the backend).
// ============================================================

import type { Map as MlMap } from 'maplibre-gl';
import type { GisBounds } from '@shared';

const NICE = [1, 2, 5];

/** Largest round distance (1/2/5 × 10ⁿ m) that fits in maxPx at this latitude/zoom. */
export function scaleFor(lat: number, zoom: number, maxPx = 110): { px: number; label: string } {
  // web mercator with MapLibre's 512 px world tiles
  const metresPerPx = (40075016.686 * Math.cos((lat * Math.PI) / 180)) / (512 * 2 ** zoom);
  const maxMetres = metresPerPx * maxPx;
  const pow = 10 ** Math.floor(Math.log10(maxMetres));
  const step = [...NICE].reverse().find(n => n * pow <= maxMetres) ?? 1;
  const metres = step * pow;
  return {
    px: Math.round(metres / metresPerPx),
    label: metres >= 1000 ? `${metres / 1000} km` : `${metres} m`,
  };
}

/** Length as people read it: metres below 1 km, else km to 10 m. */
export function formatLength(m: number | null): string {
  if (m == null) return 'Unknown';
  return m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`;
}

/** Frame the whole live network. False when there is nothing to frame. */
export function fitNetwork(map: MlMap, bounds: GisBounds | undefined, animate = true): boolean {
  if (!bounds?.bbox) return false;
  const [x1, y1, x2, y2] = bounds.bbox;
  map.fitBounds([[x1, y1], [x2, y2]], { padding: 64, maxZoom: 17, duration: animate ? 600 : 0 });
  return true;
}

export function webglAvailable(): boolean {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch { return false; }
}

/**
 * The first overlay layer (design mode, trace) already on the map. The live
 * network is added after its marker images load, so it may arrive after an
 * overlay; inserting under it keeps the overlay on top.
 */
export function overlayBefore(map: { getStyle: () => { layers?: { id: string }[] } | undefined }): string | undefined {
  return map.getStyle()?.layers?.find(l => l.id.startsWith('design-') || l.id.startsWith('trace-'))?.id;
}
