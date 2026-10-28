// ============================================================
// OPSYN NETWORK MAP — the shared MapLibre instance.
// MapCanvas provides it to its children; the page re-provides it to the
// rail and status strip, which sit outside the canvas in the grid.
// ============================================================

import { createContext, useContext } from 'react';
import type { Map as MlMap } from 'maplibre-gl';

export type TileHealth = 'loading' | 'ok' | 'failed';

export interface MapCtx { map: MlMap; basemapHealth: TileHealth }

const MapContext = createContext<MapCtx | null>(null);

export const MapInstanceProvider = MapContext.Provider;

export function useMapInstance(): MapCtx {
  const ctx = useContext(MapContext);
  if (!ctx) throw new Error('useMapInstance must be used inside <MapCanvas> or <MapInstanceProvider>');
  return ctx;
}
