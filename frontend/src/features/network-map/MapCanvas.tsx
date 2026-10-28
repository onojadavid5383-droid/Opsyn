// ============================================================
// OPSYN NETWORK MAP — MapCanvas, the thin in-house MapLibre wrapper.
//
// One map instance per mount, removed on unmount. Children render only
// once the style has loaded and read the instance through useMapInstance(),
// adding their own sources/layers in effects that clean up after
// themselves — no react-map-gl.
//
// Basemap: OpenStreetMap raster, same host fallback as the Leaflet maps
// (lib/basemap OSM_TILE_SOURCES; switch after 8 s with no tile or a run of
// errors; remembered in sessionStorage 'opsyn-tile-source'). Light and
// night variants are raster paint properties, not a second provider.
//
// Auth: MapLibre fetches tiles itself, so transformRequest adds the bearer
// token — but only to OpSyn API URLs, never to the basemap hosts.
// ============================================================

import { useEffect, useRef, useState, type ReactNode } from 'react';
import maplibregl, { type Map as MlMap, type RasterLayerSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { OSM_ATTRIBUTION, OSM_TILE_SOURCES } from '../../lib/basemap';
import { tokenStore } from '../../api/client';
import { isApiUrl } from '../../api/network.api';
import { MapInstanceProvider, type MapCtx, type TileHealth } from './mapContext';
import { webglAvailable } from './mapMath';
import type { NetworkBasemap } from './store';

const BASEMAP_SOURCE = 'basemap';
const BASEMAP_LAYER = 'basemap';
const FIRST_TILE_TIMEOUT_MS = 8000;
const ERRORS_BEFORE_SWITCH = 6;
const SESSION_KEY = 'opsyn-tile-source';

// Before the network extent is known (or when there is no network yet)
const FALLBACK_CENTER: [number, number] = [3.3792, 6.5244];  // Lagos
const FALLBACK_ZOOM = 10;

const BACKGROUND: Record<NetworkBasemap, string> = { light: '#E9EDF1', dark: '#0E1A26', none: '#E9EDF1' };

const RASTER_PAINT: Record<'light' | 'dark', RasterLayerSpecification['paint']> = {
  // A quieter street map, so the plant — not the POIs — is what stands out
  light: { 'raster-saturation': -0.35, 'raster-contrast': -0.04, 'raster-brightness-min': 0.02, 'raster-brightness-max': 1 },
  dark:  { 'raster-saturation': -0.85, 'raster-contrast': 0.12, 'raster-brightness-min': 0.06, 'raster-brightness-max': 0.4 },
};

function readPreferred(): number {
  try {
    const url = sessionStorage.getItem(SESSION_KEY);
    const i = OSM_TILE_SOURCES.findIndex(s => s.url === url);
    return i >= 0 ? i : 0;
  } catch { return 0; }
}

interface Props {
  basemap:   NetworkBasemap;
  className?: string;
  children?: ReactNode;
  /** Accessible name for the map region */
  label:     string;
  /** The ready map (or null while loading / after unmount) for UI outside the canvas */
  onMapChange?: (ctx: MapCtx | null) => void;
}

export function MapCanvas({ basemap, className, children, label, onMapChange }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MlMap | null>(null);
  const [health, setHealth] = useState<TileHealth>('loading');
  const [noWebgl] = useState(() => !webglAvailable());
  const sourceIndex = useRef(readPreferred());

  // ── Create / destroy ─────────────────────────────────────
  useEffect(() => {
    if (noWebgl || !containerRef.current) return;
    const src = OSM_TILE_SOURCES[sourceIndex.current];
    const instance = new maplibregl.Map({
      container: containerRef.current,
      center: FALLBACK_CENTER,
      zoom: FALLBACK_ZOOM,
      maxZoom: 21,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      transformRequest: url => (isApiUrl(url)
        ? { url, headers: { Authorization: `Bearer ${tokenStore.get() ?? ''}` } }
        : { url }),
      style: {
        version: 8,
        glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
        sources: {
          [BASEMAP_SOURCE]: {
            type: 'raster', tiles: [src.url], tileSize: 256, maxzoom: src.maxNativeZoom,
            attribution: OSM_ATTRIBUTION,
          },
        },
        layers: [
          { id: 'background', type: 'background', paint: { 'background-color': BACKGROUND.light } },
          { id: BASEMAP_LAYER, type: 'raster', source: BASEMAP_SOURCE, paint: RASTER_PAINT.light },
        ],
      },
    });
    instance.touchZoomRotate.disableRotation();
    instance.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
    instance.getCanvas().setAttribute('aria-label', label);
    // Ready as soon as the style is parsed — NOT on 'load', which waits for
    // every source's tiles: a slow or blocked OSM host would hold the
    // network layers back until its requests time out.
    instance.once('style.load', () => setMap(instance));
    return () => {
      setMap(null);
      instance.remove();
    };
    // label only names the canvas; it never recreates the map
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noWebgl]);

  // ── Resilient basemap: fall back to the next OSM host ─────
  useEffect(() => {
    if (!map) return;
    let loaded = 0;
    let errors = 0;
    let timer: number | undefined;

    const swapTo = (i: number) => {
      const next = OSM_TILE_SOURCES[i];
      sourceIndex.current = i;
      loaded = 0;
      errors = 0;
      const vis = map.getLayoutProperty(BASEMAP_LAYER, 'visibility');
      const paint = RASTER_PAINT[basemap === 'dark' ? 'dark' : 'light'];
      map.removeLayer(BASEMAP_LAYER);
      map.removeSource(BASEMAP_SOURCE);
      map.addSource(BASEMAP_SOURCE, {
        type: 'raster', tiles: [next.url], tileSize: 256, maxzoom: next.maxNativeZoom, attribution: OSM_ATTRIBUTION,
      });
      // keep the basemap under every network layer
      const firstOverlay = map.getStyle().layers.find(l => l.id !== 'background')?.id;
      map.addLayer({ id: BASEMAP_LAYER, type: 'raster', source: BASEMAP_SOURCE, paint, layout: { visibility: vis ?? 'visible' } }, firstOverlay);
      arm();
    };
    const advance = () => {
      window.clearTimeout(timer);
      if (sourceIndex.current + 1 < OSM_TILE_SOURCES.length) swapTo(sourceIndex.current + 1);
      else setHealth('failed');
    };
    const arm = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => { if (loaded === 0) advance(); }, FIRST_TILE_TIMEOUT_MS);
    };
    const onData = (e: maplibregl.MapSourceDataEvent) => {
      if (e.sourceId !== BASEMAP_SOURCE || !e.tile) return;
      if (loaded++ === 0) {
        window.clearTimeout(timer);
        setHealth('ok');
        try { sessionStorage.setItem(SESSION_KEY, OSM_TILE_SOURCES[sourceIndex.current].url); } catch { /* fine */ }
      }
    };
    const onError = (e: maplibregl.ErrorEvent & { sourceId?: string }) => {
      if (e.sourceId === BASEMAP_SOURCE && ++errors >= ERRORS_BEFORE_SWITCH && loaded === 0) advance();
    };
    map.on('sourcedata', onData);
    map.on('error', onError);
    arm();
    return () => {
      window.clearTimeout(timer);
      map.off('sourcedata', onData);
      map.off('error', onError);
    };
    // re-arming on basemap change would restart the fallback clock for nothing
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  // ── Basemap variant ───────────────────────────────────────
  useEffect(() => {
    if (!map) return;
    map.setPaintProperty('background', 'background-color', BACKGROUND[basemap]);
    map.setLayoutProperty(BASEMAP_LAYER, 'visibility', basemap === 'none' ? 'none' : 'visible');
    if (basemap !== 'none') {
      for (const [k, v] of Object.entries(RASTER_PAINT[basemap] ?? {})) {
        map.setPaintProperty(BASEMAP_LAYER, k, v);
      }
    }
  }, [map, basemap]);

  const effectiveHealth: TileHealth = basemap === 'none' ? 'ok' : health;
  useEffect(() => {
    onMapChange?.(map ? { map, basemapHealth: effectiveHealth } : null);
  }, [map, effectiveHealth, onMapChange]);

  if (noWebgl) {
    return (
      <div className={className} role="alert" data-map-state="no-webgl">
        <p style={{ margin: 'auto', maxWidth: 420, padding: 24, textAlign: 'center' }}>
          This browser can't draw the network map because WebGL is turned off or unsupported.
          Turn on hardware acceleration in your browser settings, or open OpSyn in a current
          version of Edge, Chrome or Firefox.
        </p>
      </div>
    );
  }

  return (
    <div className={className} data-map-state={map ? 'ready' : 'loading'}>
      <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />
      {map && (
        <MapInstanceProvider value={{ map, basemapHealth: effectiveHealth }}>
          {children}
        </MapInstanceProvider>
      )}
    </div>
  );
}
