// ============================================================
// OPSYN — basemap tiles, configured in one place.
//
// Provider: OpenStreetMap (tile.openstreetmap.org — already allowed by the
// nginx CSP img-src). No API key. The attribution below is required by the
// OSM licence and must stay visible on every map.
//
//   OSM Dark      the same OSM tiles, darkened with a CSS filter
//                 (.opsyn-tiles-dark in global.css) so they sit on the
//                 console surface without a second provider
//   OSM Standard  the tiles as published
//   None          assets on the plain console canvas
//
// OSM's public tile servers are for light use (see the OSM tile usage
// policy). For heavy production traffic, point VITE_BASEMAP_URL at your own
// OSM tile server or a mirror, and add its host to the CSP img-src:
//
//   VITE_BASEMAP_URL=https://tiles.example.com/{z}/{x}/{y}.png
//   VITE_BASEMAP_ATTRIBUTION=© OpenStreetMap contributors
//   VITE_BASEMAP_SATELLITE_URL=…      (optional — adds "Satellite")
//   VITE_BASEMAP_SATELLITE_ATTRIBUTION=…
// ============================================================

const env = import.meta.env;

export const OSM_TILE_URL: string =
  env.VITE_BASEMAP_URL ?? 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

export const OSM_ATTRIBUTION: string =
  env.VITE_BASEMAP_ATTRIBUTION ??
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

/** OSM's standard tiles go no further than zoom 19 */
export const OSM_MAX_NATIVE_ZOOM = 19;

/**
 * Where OSM tiles can come from, tried in order. Some networks block or
 * time out on tile.openstreetmap.org; the German OSM community server serves
 * the same standard style, so the map falls back to it instead of going
 * blank. A self-hosted VITE_BASEMAP_URL is never second-guessed — no
 * fallback is added. Every host here must be in the nginx CSP img-src.
 */
export interface TileSource { url: string; maxNativeZoom: number }
export const OSM_TILE_SOURCES: TileSource[] = env.VITE_BASEMAP_URL
  ? [{ url: OSM_TILE_URL, maxNativeZoom: OSM_MAX_NATIVE_ZOOM }]
  : [
      { url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', maxNativeZoom: 19 },
      { url: 'https://tile.openstreetmap.de/{z}/{x}/{y}.png',  maxNativeZoom: 18 },
    ];

export interface Basemap {
  id:           'osm-dark' | 'osm' | 'satellite' | 'none';
  label:        string;
  url?:         string;
  attribution?: string;
  /** Applied to the tile layer — the dark variant is a filter over OSM */
  className?:   string;
}

/** The basemaps this build can offer; the first is the default. */
export const BASEMAPS: Basemap[] = [
  { id: 'osm-dark', label: 'Dark map', url: OSM_TILE_URL, attribution: OSM_ATTRIBUTION, className: 'opsyn-tiles-dark' },
  { id: 'osm', label: 'Light map', url: OSM_TILE_URL, attribution: OSM_ATTRIBUTION },
  ...(env.VITE_BASEMAP_SATELLITE_URL
    ? [{ id: 'satellite' as const, label: 'Satellite', url: env.VITE_BASEMAP_SATELLITE_URL as string, attribution: (env.VITE_BASEMAP_SATELLITE_ATTRIBUTION as string | undefined) ?? '' }]
    : []),
  { id: 'none', label: 'No basemap (assets only)' },
];

export const DEFAULT_BASEMAP: Basemap = BASEMAPS[0];
