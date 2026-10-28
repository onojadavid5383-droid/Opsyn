// ============================================================
// OPSYN — basemap tile layer that survives a blocked tile server.
//
// Some networks block or time out on tile.openstreetmap.org. Instead of a
// silently blank map (and a console full of timeouts), this tries each
// source in OSM_TILE_SOURCES in turn:
//   • switch when nothing has loaded 8 s after the first tile request
//     (Chrome only reports a timed-out tile after ~30 s), or after a run of
//     errors with no successes
//   • remember the source that worked for the rest of the session, so the
//     next map opens on it straight away
//   • if every source fails, say so on the map — assets still draw
// ============================================================

import { useEffect, useRef, useState } from 'react';
import { TileLayer } from 'react-leaflet';
import { OSM_MAX_NATIVE_ZOOM, OSM_TILE_SOURCES, OSM_TILE_URL, type Basemap, type TileSource } from '../../lib/basemap';
import s from './ResilientTileLayer.module.css';

const FIRST_TILE_TIMEOUT_MS = 8000;
const ERRORS_BEFORE_SWITCH = 6;
const SESSION_KEY = 'opsyn-tile-source';

function readPreferred(): string | null {
  try { return sessionStorage.getItem(SESSION_KEY); } catch { return null; }
}
function writePreferred(url: string) {
  try { sessionStorage.setItem(SESSION_KEY, url); } catch { /* private mode — fine */ }
}

export function ResilientTileLayer({ basemap }: { basemap: Basemap }) {
  const sources: TileSource[] = basemap.url === OSM_TILE_URL
    ? OSM_TILE_SOURCES
    : [{ url: basemap.url!, maxNativeZoom: OSM_MAX_NATIVE_ZOOM }];

  const [index, setIndex] = useState(() => {
    const preferred = readPreferred();
    const i = sources.findIndex(src => src.url === preferred);
    return i >= 0 ? i : 0;
  });
  const [failed, setFailed] = useState(false);
  const loaded = useRef(0);
  const errors = useRef(0);
  const timer = useRef<number>();

  const advance = () => {
    window.clearTimeout(timer.current);
    if (index + 1 < sources.length) setIndex(index + 1);
    else setFailed(true);
  };

  // Fresh counters for each source; no timer until tiles are actually requested
  useEffect(() => {
    loaded.current = 0;
    errors.current = 0;
    timer.current = undefined;
    return () => window.clearTimeout(timer.current);
  }, [index]);

  const source = sources[index];

  return (
    <>
      {!failed && (
        <TileLayer
          key={source.url}
          url={source.url}
          attribution={basemap.attribution}
          className={basemap.className}
          maxNativeZoom={source.maxNativeZoom}
          eventHandlers={{
            tileloadstart: () => {
              if (loaded.current === 0 && timer.current === undefined) {
                timer.current = window.setTimeout(() => { if (loaded.current === 0) advance(); }, FIRST_TILE_TIMEOUT_MS);
              }
            },
            tileload: () => {
              if (loaded.current++ === 0) {
                window.clearTimeout(timer.current);
                writePreferred(source.url);
              }
            },
            tileerror: () => {
              if (++errors.current >= ERRORS_BEFORE_SWITCH && loaded.current === 0) advance();
            },
          }}
        />
      )}
      {failed && (
        <div className={s.notice} role="status">
          Map tiles couldn't load on this network — assets are still shown.
        </div>
      )}
    </>
  );
}
