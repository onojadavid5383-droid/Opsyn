/*!
 * Liquid Glass — refraction field (React port).
 *
 * The refraction field is a port of the fragment shader in liquid-glass-js
 * (https://github.com/dashersw/liquid-glass-js) — Copyright (c) 2025 Armagan
 * Amcalar, MIT. Permission is hereby granted, free of charge, to any person
 * obtaining a copy of that software to deal in it without restriction,
 * provided this notice travels with it; it is provided "as is", without
 * warranty of any kind. Keep this header on any copy or port.
 *
 * Ported from the liquid-glass skill's Angular directive. Formulas and every
 * constant are unchanged — each was fit against a reference render; see the
 * skill's references/refraction.md before touching one.
 *
 * This file is framework-free: the field math (unit-tested) and the shared
 * SVG filter registry. hooks/useLiquidGlass.ts is the React lifecycle.
 */

export interface LiquidGlassConfig {
  edgeIntensity: number;
  rimIntensity:  number;
  baseIntensity: number;
  edgeDistance:  number;
  rimDistance:   number;
  baseDistance:  number;
  cornerBoost:   number;
  rippleEffect:  number;
  blurRadius:    number;
  /** Center distortion. Off: text under the middle of a panel must stay legible. */
  warp: boolean;
}

export const GLASS_PRESET: LiquidGlassConfig = {
  edgeIntensity: 0.015,
  rimIntensity:  0.028,
  baseIntensity: 0.05,
  edgeDistance:  0.5,
  rimDistance:   1.7,
  baseDistance:  0.2,
  cornerBoost:   0.06,
  rippleEffect:  0.26,
  blurRadius:    2,
  warp:          false,
};

/**
 * Surfaces that carry reading content over dense data (modals, the task
 * popup, sidebars, inspectors). The preset's blurRadius 2 (≈0.7 px) suits
 * decorative cards but leaves table rows legible through the panel, so text
 * sits on text. Same rim refraction; frost raised to ≈9 px.
 */
export const READING_GLASS: Partial<LiquidGlassConfig> = { blurRadius: 26 };

/** Map rendered at 2× CSS size — the rim lives in a 1–2 px band. */
const SUPERSAMPLE = 2;
/** Bound the bake for large surfaces; refraction is edge-local. */
const MAX_MAP_EDGE = 1400;
/** feGaussianBlur stdDeviation per unit of blurRadius (fit to the reference). */
export const BLUR_STD_PER_RADIUS = 0.35;


// ── Field math (pure) ─────────────────────────────────────────

export interface DisplacementField {
  /** Map size in (supersampled) pixels */
  bw: number;
  bh: number;
  dx: Float32Array;
  dy: Float32Array;
  /** feDisplacementMap scale: 2 × the largest offset */
  scale: number;
}

/** Signed distance (CSS px, clamped ≥0) from a map pixel to the rounded-rect edge. */
export function edgeDistancePx(
  px: number, py: number, bw: number, bh: number, rSs: number, ss: number,
): number {
  const tx = Math.abs(px + 0.5 - bw / 2) - (bw / 2 - rSs);
  const ty = Math.abs(py + 0.5 - bh / 2) - (bh / 2 - rSs);
  const outside = Math.hypot(Math.max(tx, 0), Math.max(ty, 0));
  const inside  = Math.min(Math.max(tx, ty), 0);
  return Math.max(-(outside + inside - rSs), 0) / ss;
}

export function computeDisplacementField(
  w: number, h: number, radius: number, pageW: number, pageH: number, cfg: LiquidGlassConfig,
): DisplacementField {
  const ss = Math.max(0.25, Math.min(SUPERSAMPLE, MAX_MAP_EDGE / Math.max(w, h)));
  const bw = Math.max(1, Math.round(w * ss));
  const bh = Math.max(1, Math.round(h * ss));
  const r = radius * ss;
  const minDim = Math.min(w, h);
  const dx = new Float32Array(bw * bh);
  const dy = new Float32Array(bw * bh);
  let maxAbs = 0;

  for (let py = 0; py < bh; py++) {
    for (let px = 0; px < bw; px++) {
      const cx = (px + 0.5) / bw;
      const cy = (py + 0.5) / bh;
      const distPx = edgeDistancePx(px, py, bw, bh, r, ss);

      const edgeFall = Math.exp(-distPx * cfg.edgeDistance);
      const rimFall  = Math.exp(-distPx * cfg.rimDistance);
      const baseFall = 1 - Math.exp(-distPx * cfg.baseDistance);
      const baseComponent = cfg.warp ? baseFall * cfg.baseIntensity : 0;
      const total = baseComponent + edgeFall * cfg.edgeIntensity + rimFall * cfg.rimIntensity;

      // Rounded-rect normal, taken in texcoord space as the shader does
      let nx = cx - 0.5;
      let ny = cy - 0.5;
      const len = Math.hypot(nx, ny);
      if (len > 0) { nx /= len; ny /= len; }

      const cornerNorm = Math.max(Math.min(cx, 1 - cx), Math.min(cy, 1 - cy)) * minDim;
      const corner = Math.exp(-cornerNorm * 0.3) * cfg.cornerBoost;
      const ripple = Math.sin((distPx / minDim) * 25) * cfg.rippleEffect * rimFall;

      const fx = (nx * (total + corner) - ny * ripple) * pageW;
      const fy = (ny * (total + corner) + nx * ripple) * pageH;

      const i = py * bw + px;
      dx[i] = fx;
      dy[i] = fy;
      maxAbs = Math.max(maxAbs, Math.abs(fx), Math.abs(fy));
    }
  }

  return { bw, bh, dx, dy, scale: Math.max(maxAbs * 2, 1e-4) };
}

/**
 * feDisplacementMap decodes byte b as scale·(b/255 − 0.5). Transcribed from
 * the reference, which pre-subtracts the 128/255 decode bias. Note that no
 * byte decodes to exactly zero (the midpoint is 127.5): the bias step moves
 * the neutral byte from 128 to 127, i.e. the interior drifts by scale/510 px
 * in the opposite direction instead — sub-pixel at every real panel size,
 * and bounded in the unit tests.
 */
export function encodeOffset(offset: number, scale: number): number {
  const bias = scale * (128 / 255 - 0.5);
  return clampByte(255 * (0.5 + (offset - bias) / scale));
}

/** The browser's decode, for tests that bound the neutral drift. */
export function decodeByte(byte: number, scale: number): number {
  return scale * (byte / 255 - 0.5);
}

function clampByte(v: number): number {
  return Math.max(0, Math.min(255, Math.round(v)));
}

/** Resolve a computed border-radius (px or %) to CSS pixels. */
export function resolveRadius(computed: string, w: number, h: number): number {
  const value = parseFloat(computed) || 0;
  return computed.trim().endsWith('%') ? (value / 100) * Math.min(w, h) : value;
}


// ── Engine gate ───────────────────────────────────────────────

/**
 * SVG-referenced backdrop filters render in Chromium only. Safari parses the
 * declaration and paints nothing, so @supports would lie — gate on engine.
 */
export function isRefractionSupported(): boolean {
  if (typeof navigator === 'undefined' || typeof document === 'undefined') return false;
  const brands = (navigator as Navigator & { userAgentData?: { brands?: { brand: string }[] } })
    .userAgentData?.brands;
  if (brands) return brands.some(b => /Chromium|Google Chrome|Microsoft Edge/i.test(b.brand));
  return /Chrome\//.test(navigator.userAgent);
}

/** User settings that must turn refraction off (the CSS fallbacks take over). */
export function isRefractionSuppressed(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  return window.matchMedia('(prefers-reduced-transparency: reduce)').matches
      || window.matchMedia('(forced-colors: active)').matches;
}


// ── Shared filter registry ────────────────────────────────────
// Same-size surfaces share one <filter>; refcounted, dropped at zero.

interface FilterEntry { id: string; node: SVGFilterElement; refs: number }

const filters = new Map<string, FilterEntry>();
let defs: SVGSVGElement | null = null;
let nextId = 0;
const SVG_NS = 'http://www.w3.org/2000/svg';

function ensureDefs(): SVGSVGElement {
  if (!defs || !defs.isConnected) {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('width', '0');
    svg.setAttribute('height', '0');
    svg.setAttribute('aria-hidden', 'true');
    svg.style.position = 'fixed';
    svg.appendChild(document.createElementNS(SVG_NS, 'defs'));
    document.body.appendChild(svg);
    defs = svg;
  }
  return defs;
}

function bakeMapUrl(field: DisplacementField): string {
  const canvas = document.createElement('canvas');
  canvas.width = field.bw;
  canvas.height = field.bh;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('2D canvas unavailable');
  const image = ctx.createImageData(field.bw, field.bh);
  const data = image.data;
  for (let i = 0; i < field.bw * field.bh; i++) {
    data[i * 4]     = encodeOffset(field.dx[i], field.scale);
    data[i * 4 + 1] = encodeOffset(field.dy[i], field.scale);
    data[i * 4 + 2] = 128;
    data[i * 4 + 3] = 255;
  }
  ctx.putImageData(image, 0, 0);
  return canvas.toDataURL('image/png');
}

export function acquireFilter(
  key: string, w: number, h: number, radius: number, pageW: number, pageH: number, cfg: LiquidGlassConfig,
): FilterEntry {
  let entry = filters.get(key);
  // Reuse only while still in the live document — a detached <defs> makes
  // url(#id) resolve to nothing and every panel goes blank.
  if (entry && entry.node.isConnected) {
    entry.refs++;
    return entry;
  }
  if (entry) filters.delete(key);

  const field = computeDisplacementField(w, h, radius, pageW, pageH, cfg);
  const id = `opsyn-glass-${nextId++}`;

  const filter = document.createElementNS(SVG_NS, 'filter');
  filter.setAttribute('id', id);
  // Edge pixels sample up to scale/2 away plus the blur spread; size the region
  // from the field or the refraction clips to transparent at the corners.
  const marginPx = field.scale / 2 + 3 * cfg.blurRadius * BLUR_STD_PER_RADIUS;
  const mx = (marginPx / w) * 100;
  const my = (marginPx / h) * 100;
  filter.setAttribute('x', `${-mx}%`);
  filter.setAttribute('y', `${-my}%`);
  filter.setAttribute('width', `${100 + 2 * mx}%`);
  filter.setAttribute('height', `${100 + 2 * my}%`);
  filter.setAttribute('color-interpolation-filters', 'sRGB');

  const feImage = document.createElementNS(SVG_NS, 'feImage');
  feImage.setAttribute('href', bakeMapUrl(field));
  feImage.setAttribute('x', '0');
  feImage.setAttribute('y', '0');
  feImage.setAttribute('width', String(w));
  feImage.setAttribute('height', String(h));
  feImage.setAttribute('preserveAspectRatio', 'none');
  feImage.setAttribute('result', 'map');

  const feDisplacement = document.createElementNS(SVG_NS, 'feDisplacementMap');
  feDisplacement.setAttribute('in', 'SourceGraphic');
  feDisplacement.setAttribute('in2', 'map');
  feDisplacement.setAttribute('scale', String(field.scale));
  feDisplacement.setAttribute('xChannelSelector', 'R');
  feDisplacement.setAttribute('yChannelSelector', 'G');
  feDisplacement.setAttribute('result', 'displaced');

  const feBlur = document.createElementNS(SVG_NS, 'feGaussianBlur');
  feBlur.setAttribute('in', 'displaced');
  feBlur.setAttribute('stdDeviation', String(cfg.blurRadius * BLUR_STD_PER_RADIUS));

  filter.append(feImage, feDisplacement, feBlur);
  ensureDefs().querySelector('defs')!.appendChild(filter);

  entry = { id, node: filter, refs: 1 };
  filters.set(key, entry);
  return entry;
}

export function releaseFilter(key: string): void {
  const entry = filters.get(key);
  if (entry && --entry.refs <= 0) {
    filters.delete(key);
    entry.node.remove();
  }
}
