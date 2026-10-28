// ============================================================
// OPSYN — useLiquidGlass
// Refraction for a `.liquid-glass` element: bakes a displacement map for the
// element's size and points its backdrop-filter at a shared SVG filter.
//
//   const ref = useRef<HTMLDivElement>(null);
//   useLiquidGlass(ref);
//   <div ref={ref} className="liquid-glass">…</div>
//
// Inert (the stylesheet's blur fallback stays) when:
//   - the engine can't render SVG backdrop filters (anything but Chromium)
//   - the user prefers reduced transparency, or forced colours are active
//   - `enabled` is false
//
// Priced per surface (a canvas bake per size): use it on the panel tier only —
// modals, the task popup, sidebars, inspectors. Menus and chips never refract.
// ============================================================

import { useEffect, type RefObject } from 'react';
import {
  GLASS_PRESET, acquireFilter, isRefractionSupported, isRefractionSuppressed,
  releaseFilter, resolveRadius, type LiquidGlassConfig,
} from '../components/glass/refraction';

/** Window resizes change pageW/pageH for every instance — settle before rebaking. */
const WINDOW_RESIZE_DEBOUNCE_MS = 180;

export function useLiquidGlass<T extends HTMLElement>(
  ref: RefObject<T | null>,
  options: { enabled?: boolean; config?: Partial<LiquidGlassConfig> } = {},
): void {
  const { enabled = true, config } = options;
  // Stable dependency for an inline config object
  const configKey = config ? JSON.stringify(config) : '';

  useEffect(() => {
    const host = ref.current;
    if (!host || !enabled || !isRefractionSupported() || isRefractionSuppressed()) return;

    const cfg: LiquidGlassConfig = { ...GLASS_PRESET, ...(configKey ? JSON.parse(configKey) : {}) };
    let currentKey: string | null = null;
    let frame = 0;
    let debounce: ReturnType<typeof setTimeout> | undefined;

    const release = () => {
      if (currentKey) releaseFilter(currentKey);
      currentKey = null;
    };

    const rebuild = () => {
      const w = Math.round(host.offsetWidth);
      const h = Math.round(host.offsetHeight);
      if (w < 2 || h < 2) return;
      const radius = Math.min(
        resolveRadius(getComputedStyle(host).borderTopLeftRadius, w, h),
        Math.min(w, h) / 2,
      );
      // Displacement is in fractions of the page; the live page is the viewport
      const pageW = window.innerWidth;
      const pageH = window.innerHeight;
      const key = [w, h, radius, pageW, pageH, JSON.stringify(cfg)].join('|');
      if (key === currentKey) return;

      release();
      try {
        const entry = acquireFilter(key, w, h, radius, pageW, pageH, cfg);
        currentKey = key;
        host.style.backdropFilter = `url(#${entry.id})`;
        host.dataset.glassRefraction = 'on';
      } catch {
        // Canvas unavailable — keep the CSS fallback rather than a blank panel
        host.style.backdropFilter = '';
        delete host.dataset.glassRefraction;
      }
    };

    // Coalesce resize bursts into one rebuild per frame
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(rebuild);
    };
    const onWindowResize = () => {
      clearTimeout(debounce);
      debounce = setTimeout(schedule, WINDOW_RESIZE_DEBOUNCE_MS);
    };

    const observer = new ResizeObserver(schedule);
    observer.observe(host);
    window.addEventListener('resize', onWindowResize, { passive: true });
    schedule();

    return () => {
      observer.disconnect();
      window.removeEventListener('resize', onWindowResize);
      clearTimeout(debounce);
      cancelAnimationFrame(frame);
      release();
      host.style.backdropFilter = '';
      delete host.dataset.glassRefraction;
    };
  }, [ref, enabled, configKey]);
}
