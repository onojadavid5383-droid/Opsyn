// ============================================================
// OPSYN CHARTS — theme from design tokens
// ECharts needs concrete colours, so they are read from the live CSS
// variables — the same tokens as the rest of the UI — and re-read when the
// theme changes. Categorical series use the fiber-code palette (--chart-*);
// status colours are only for series that ARE a severity.
// ============================================================

import { useMemo } from 'react';
import { useThemeStore } from '../../store/theme.store';

export interface ChartTheme {
  categorical: string[];
  text:        string;
  textMuted:   string;
  grid:        string;
  axis:        string;
  target:      string;
  surface:     string;
  menuSurface: string;
  border:      string;
  fontFamily:  string;
  monoFamily:  string;
  status:      { critical: string; high: string; warning: string; low: string; ok: string };
  /** Workflow states — for charts whose segments ARE states (matches StateBadge) */
  state:       { new: string; progress: string; review: string; blocked: string; done: string; archived: string };
  reducedMotion: boolean;
}

// Light-theme values: the fallback wherever tokens can't be read (tests, SSR)
const FALLBACK: Omit<ChartTheme, 'reducedMotion'> = {
  categorical: ['#0A8599', '#BE3A74', '#6D4AC2', '#8A5A3C', '#5B6B7E', '#0B1520'],
  text: '#0B1520', textMuted: '#5B6B7E', grid: '#E2E8F0', axis: '#5B6B7E', target: '#0B1520',
  surface: '#FFFFFF', menuSurface: '#F7F9FB', border: 'rgba(11, 21, 32, 0.12)',
  fontFamily: "'IBM Plex Sans', system-ui, sans-serif", monoFamily: "'IBM Plex Mono', monospace",
  status: { critical: '#C8102E', high: '#B93C00', warning: '#8A5A00', low: '#1F5FCC', ok: '#13773D' },
  state:  { new: '#76879B', progress: '#4F46E5', review: '#6D28D9', blocked: '#C8102E', done: '#13773D', archived: '#94A3B8' },
};

export function readChartTheme(root: Element | null = typeof document !== 'undefined' ? document.documentElement : null): ChartTheme {
  const reducedMotion = typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  if (!root || typeof getComputedStyle === 'undefined') return { ...FALLBACK, reducedMotion };
  const cs = getComputedStyle(root);
  const v = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
  return {
    categorical: [1, 2, 3, 4, 5, 6].map((n, i) => v(`--chart-${n}`, FALLBACK.categorical[i])),
    text:        v('--text-primary', FALLBACK.text),
    textMuted:   v('--text-muted', FALLBACK.textMuted),
    grid:        v('--chart-grid', FALLBACK.grid),
    axis:        v('--chart-axis', FALLBACK.axis),
    target:      v('--chart-target', FALLBACK.target),
    surface:     v('--surface', FALLBACK.surface),
    menuSurface: v('--glass-menu-surface', FALLBACK.menuSurface),
    border:      v('--glass-border', FALLBACK.border),
    fontFamily:  v('--font-sans', FALLBACK.fontFamily),
    monoFamily:  v('--font-mono', FALLBACK.monoFamily),
    status: {
      critical: v('--status-critical-fg', FALLBACK.status.critical),
      high:     v('--status-high-fg', FALLBACK.status.high),
      warning:  v('--status-warning-fg', FALLBACK.status.warning),
      low:      v('--status-low-fg', FALLBACK.status.low),
      ok:       v('--status-ok-fg', FALLBACK.status.ok),
    },
    state: {
      new:      v('--state-new', FALLBACK.state.new),
      progress: v('--state-progress', FALLBACK.state.progress),
      review:   v('--state-review', FALLBACK.state.review),
      // blocked/done tokens alias the status fg tokens (var() — resolved here)
      blocked:  v('--status-critical-fg', FALLBACK.state.blocked),
      done:     v('--status-ok-fg', FALLBACK.state.done),
      archived: v('--state-archived', FALLBACK.state.archived),
    },
    reducedMotion,
  };
}

/** The chart theme for the current light/dark mode; recomputed on switch. */
export function useChartTheme(): ChartTheme {
  const resolved = useThemeStore(s => s.resolved);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- `resolved` is the trigger: tokens change with it
  return useMemo(() => readChartTheme(), [resolved]);
}
