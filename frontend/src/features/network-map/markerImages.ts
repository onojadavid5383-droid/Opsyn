// ============================================================
// OPSYN NETWORK MAP — marker images.
//
// Builds one image per (asset type × lifecycle variant) from the
// symbology tables: a tier-shaped plate, the type's white lucide glyph,
// and the lifecycle ring/badge. Rasterised at 2× and registered with
// map.addImage(), so MapLibre draws them on the GPU like any sprite —
// no sprite sheet to host, and the glyphs stay identical to the panel's.
// ============================================================

import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { Map as MlMap } from 'maplibre-gl';
import type { NetAssetType, NetTier } from '@shared';
import {
  ASSET_GLYPH, ASSET_TIER, ASSET_TYPES, FAULT_COLOR, ICON_VARIANTS, TIER_COLOR, TIER_SHAPE,
  iconName, type IconVariant,
} from './symbology';

const VIEW = 40;         // logical px — room for the ring and the fault badge
const C = VIEW / 2;
const PIXEL_RATIO = 2;

function shape(tier: NetTier, attrs: string): string {
  switch (TIER_SHAPE[tier]) {
    case 'square':
      return `<rect x="${C - 12}" y="${C - 12}" width="24" height="24" rx="6" ${attrs}/>`;
    case 'circle':
      return `<circle cx="${C}" cy="${C}" r="12.5" ${attrs}/>`;
    case 'hexagon': {
      const pts = Array.from({ length: 6 }, (_, i) => {
        const a = (Math.PI / 3) * i - Math.PI / 2;
        return `${(C + 13 * Math.cos(a)).toFixed(2)},${(C + 13 * Math.sin(a)).toFixed(2)}`;
      }).join(' ');
      return `<polygon points="${pts}" stroke-linejoin="round" ${attrs}/>`;
    }
    case 'dot':
      return `<circle cx="${C}" cy="${C}" r="9" ${attrs}/>`;
  }
}

/** The shape grown around its centre — used for lifecycle rings. */
function ring(tier: NetTier, attrs: string): string {
  const k = TIER_SHAPE[tier] === 'dot' ? 1.45 : 1.3;
  return `<g transform="translate(${C} ${C}) scale(${k}) translate(${-C} ${-C})">${shape(tier, attrs)}</g>`;
}

export function markerSvg(type: NetAssetType, variant: IconVariant): string {
  const tier = ASSET_TIER[type];
  const fill = TIER_COLOR[tier];
  const glyphSize = TIER_SHAPE[tier] === 'dot' ? 11 : 15;
  const glyph = renderToStaticMarkup(createElement(ASSET_GLYPH[type], {
    size: glyphSize, color: '#FFFFFF', strokeWidth: 2.25, 'aria-hidden': true,
  })).replace('<svg ', `<svg x="${C - glyphSize / 2}" y="${C - glyphSize / 2}" `);

  const parts = [
    // soft dark rim: separates the plate from any basemap colour
    shape(tier, 'fill="none" stroke="rgba(11,21,32,0.45)" stroke-width="4.5"'),
    shape(tier, `fill="${fill}" stroke="#FFFFFF" stroke-width="2"`),
    glyph,
  ];
  if (variant === 'fault') {
    parts.unshift(ring(tier, `fill="none" stroke="${FAULT_COLOR}" stroke-width="2"`));
    parts.push(
      `<circle cx="${VIEW - 7}" cy="7" r="5.5" fill="${FAULT_COLOR}" stroke="#FFFFFF" stroke-width="1.5"/>`,
      `<rect x="${VIEW - 7.8}" y="3.6" width="1.6" height="4.4" rx="0.8" fill="#FFFFFF"/>`,
      `<circle cx="${VIEW - 7}" cy="9.9" r="0.95" fill="#FFFFFF"/>`,
    );
  } else if (variant === 'verify') {
    parts.unshift(ring(tier, `fill="none" stroke="${fill}" stroke-width="1.6" stroke-dasharray="3 2.4"`));
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${VIEW * PIXEL_RATIO}" height="${VIEW * PIXEL_RATIO}" viewBox="0 0 ${VIEW} ${VIEW}">${parts.join('')}</svg>`;
}

function rasterise(svg: string): Promise<ImageData> {
  return new Promise((resolve, reject) => {
    const img = new Image(VIEW * PIXEL_RATIO, VIEW * PIXEL_RATIO);
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = VIEW * PIXEL_RATIO;
      const ctx = canvas.getContext('2d');
      if (!ctx) return reject(new Error('2D canvas unavailable'));
      ctx.drawImage(img, 0, 0);
      resolve(ctx.getImageData(0, 0, canvas.width, canvas.height));
    };
    img.onerror = () => reject(new Error('marker image failed to render'));
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  });
}

let cache: Promise<Map<string, ImageData>> | null = null;

/** Every marker image, rendered once per page load. */
function allMarkers(): Promise<Map<string, ImageData>> {
  if (!cache) {
    const jobs = ASSET_TYPES.flatMap(type => ICON_VARIANTS.map(async variant =>
      [iconName(type, variant), await rasterise(markerSvg(type, variant))] as const));
    cache = Promise.all(jobs).then(entries => new Map(entries));
    cache.catch(() => { cache = null; });
  }
  return cache;
}

/** Register all marker images on a map (idempotent). */
export async function addMarkerImages(map: MlMap): Promise<void> {
  const images = await allMarkers();
  for (const [name, data] of images) {
    if (!map.hasImage(name)) map.addImage(name, data, { pixelRatio: PIXEL_RATIO });
  }
}

/** FTTx preview uses the same OpSyn glyph and tier silhouette, with an
 * engineering layer colour so devices remain distinguishable on the map. */
export const FTTX_ICON_TYPES = {
  fdt: 'FDT', fat: 'FAT', closure: 'CLOSURE', pickup_point: 'CABINET', pole_output: 'POLE',
} as const satisfies Record<string, NetAssetType>;
export const FTTX_ICON_COLORS: Record<keyof typeof FTTX_ICON_TYPES, string> = {
  fdt:'#005A9C', fat:'#A84300', closure:'#006B45', pickup_point:'#74513A', pole_output:'#53616C',
};
export function fttxIconName(key: keyof typeof FTTX_ICON_TYPES): string { return `fttx-${key}`; }
export async function addFttxMarkerImages(map: MlMap): Promise<void> {
  await Promise.all((Object.keys(FTTX_ICON_TYPES) as (keyof typeof FTTX_ICON_TYPES)[]).map(async key => {
    const svg = markerSvg(FTTX_ICON_TYPES[key], 'ok').replace(TIER_COLOR[ASSET_TIER[FTTX_ICON_TYPES[key]]], FTTX_ICON_COLORS[key]);
    const image = await rasterise(svg);
    const name = fttxIconName(key);
    if (!map.hasImage(name)) map.addImage(name, image, { pixelRatio: PIXEL_RATIO });
  }));
}

/** A marker as a data URL, for the panel legend and the inspector header. */
export function markerDataUrl(type: NetAssetType, variant: IconVariant = 'ok'): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markerSvg(type, variant))}`;
}
