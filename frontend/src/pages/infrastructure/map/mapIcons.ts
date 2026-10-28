// ============================================================
// OPSYN MAP — marker shapes
// Asset KIND is the shape; asset STATE is the colour.
//   Site ◉   OLT ■   Cabinet ▬   Splitter L1 ▼ (solid)   Splitter L2 ▽ (outline)
// Alarm markers use the severity shapes (⬣ ▲ ◆ ●) — deliberately a
// different vocabulary, so an asset never reads as an alarm.
// ============================================================

import L from 'leaflet';
import type { OutageSeverity } from '@shared';
import type { AssetKind, AssetState } from './mapModel';

export interface MapPalette {
  state:    Record<AssetState, string>;
  severity: Record<OutageSeverity, string>;
  outline:  string;   // canvas colour — separates markers from the basemap
  select:   string;   // selection / trace colour
  route:    Record<'normal' | 'watch' | 'critical' | 'unknown', string>;
}

/** Inline SVG for an asset shape (20×20). Exported for legend/list/inspector. */
export function assetShapeSvg(kind: AssetKind, color: string, outline: string, level?: string, size = 20): string {
  const secondLevel = kind === 'splitter' && /second/i.test(level ?? '');
  const shape = {
    site:     `<circle cx="10" cy="10" r="7.5" fill="${color}" stroke="${outline}" stroke-width="1.5"/><circle cx="10" cy="10" r="3" fill="${outline}"/>`,
    olt:      `<rect x="3" y="3" width="14" height="14" rx="1.5" fill="${color}" stroke="${outline}" stroke-width="1.5"/>`,
    cabinet:  `<rect x="1.5" y="5.5" width="17" height="9" rx="2" fill="${color}" stroke="${outline}" stroke-width="1.5"/>`,
    splitter: secondLevel
      ? `<polygon points="3,4 17,4 10,16.5" fill="${outline}" stroke="${color}" stroke-width="2.5" stroke-linejoin="round"/>`
      : `<polygon points="3,4 17,4 10,16.5" fill="${color}" stroke="${outline}" stroke-width="1.5" stroke-linejoin="round"/>`,
  }[kind];
  return `<svg width="${size}" height="${size}" viewBox="0 0 20 20" aria-hidden="true" focusable="false">${shape}</svg>`;
}

const SEVERITY_SHAPE: Record<OutageSeverity, string> = {
  critical: '<polygon points="8,1 16,1 23,8 23,16 16,23 8,23 1,16 1,8"/>',
  high:     '<polygon points="12,1 23,22 1,22"/>',
  warning:  '<polygon points="12,1 23,12 12,23 1,12"/>',
  low:      '<circle cx="12" cy="12" r="10"/>',
};

export function severityShapeSvg(sev: OutageSeverity, color: string, outline: string, size = 24): string {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><g fill="${color}" stroke="${outline}" stroke-width="2" stroke-linejoin="round">${SEVERITY_SHAPE[sev]}</g></svg>`;
}

export function assetIcon(kind: AssetKind, state: AssetState, p: MapPalette, opts: { level?: string; selected?: boolean } = {}) {
  const size = kind === 'site' || kind === 'olt' ? 20 : 16;
  return L.divIcon({
    // state-* lets the cluster bubble find the worst state among its members
    className: `opsyn-marker state-${state}${opts.selected ? ' is-selected' : ''}`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: assetShapeSvg(kind, p.state[state], p.outline, opts.level, size),
  });
}

export function alarmIcon(sev: OutageSeverity, p: MapPalette, selected = false) {
  return L.divIcon({
    // Only a live critical moves (and the global reduced-motion rule stops it)
    className: `opsyn-marker opsyn-alarm${sev === 'critical' ? ' is-critical' : ''}${selected ? ' is-selected' : ''}`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    html: severityShapeSvg(sev, p.severity[sev], p.outline, 26),
  });
}

/** Cluster bubble: count, plus the worst state inside as its ring colour. */
export function clusterIcon(count: number, ring: string) {
  const size = count < 10 ? 32 : count < 100 ? 38 : 44;
  return L.divIcon({
    className: 'opsyn-cluster',
    iconSize: [size, size],
    html: `<span style="--ring:${ring}">${count}</span>`,
  });
}

/**
 * Icons cached per palette. Leaflet replaces a marker's element whenever it
 * gets a new icon object — fresh icons on every render would rebuild every
 * marker (and swallow clicks that straddle a re-render).
 */
export function createIconCache(p: MapPalette) {
  const assets = new Map<string, L.DivIcon>();
  const alarms = new Map<string, L.DivIcon>();
  return {
    asset(kind: AssetKind, state: AssetState, level: string | undefined, selected: boolean) {
      const secondLevel = kind === 'splitter' && /second/i.test(level ?? '');
      const k = `${kind}|${state}|${secondLevel}|${selected}`;
      let icon = assets.get(k);
      if (!icon) assets.set(k, (icon = assetIcon(kind, state, p, { level, selected })));
      return icon;
    },
    alarm(sev: OutageSeverity, selected: boolean) {
      const k = `${sev}|${selected}`;
      let icon = alarms.get(k);
      if (!icon) alarms.set(k, (icon = alarmIcon(sev, p, selected)));
      return icon;
    },
  };
}
export type IconCache = ReturnType<typeof createIconCache>;
