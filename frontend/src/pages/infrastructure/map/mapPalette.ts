// ============================================================
// OPSYN MAP — palette from the console surface
// Leaflet draws with concrete colours, so they are read from the map's own
// data-surface="console" element: the same tokens as everything else, in
// their dark-surface values.
// ============================================================

import { useMemo } from 'react';
import type { MapPalette } from './mapIcons';

export function useMapPalette(el: HTMLElement | null): MapPalette | null {
  return useMemo(() => {
    if (!el) return null;
    const cs = getComputedStyle(el);
    const v = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
    const critical = v('--status-critical-fg', '#FF6B6B');
    const warning = v('--status-warning-fg', '#FFC53D');
    return {
      state: {
        normal:   v('--chart-5', '#9AAABB'),
        watch:    warning,
        critical,
        offline:  v('--text-disabled', '#5F7185'),
      },
      severity: {
        critical,
        high:    v('--status-high-fg', '#FF8A3D'),
        warning,
        low:     v('--status-low-fg', '#6AA8FF'),
      },
      outline: v('--canvas', '#0B1520'),
      select:  v('--accent-text', '#2FD8BF'),
      route: {
        normal:   v('--text-secondary', '#A9B8C7'),
        watch:    warning,
        critical,
        unknown:  v('--text-muted', '#8C9DAF'),
      },
    };
  }, [el]);
}
