// ============================================================
// OPSYN — useMediaQuery + the shell's breakpoints
// Breakpoints match the design system (tokens.css / Phase 1 plan):
//   wall ≥1920 · desktop ≥1280 · laptop ≥1024 · tablet ≥768 · field <768
// ============================================================

import { useSyncExternalStore } from 'react';

export const BREAKPOINTS = {
  wall:    '(min-width: 1920px)',
  desktop: '(min-width: 1280px)',
  laptop:  '(min-width: 1024px)',
  tablet:  '(min-width: 768px)',
} as const;

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    onChange => {
      if (typeof window === 'undefined' || !window.matchMedia) return () => {};
      const mql = window.matchMedia(query);
      mql.addEventListener?.('change', onChange);
      return () => mql.removeEventListener?.('change', onChange);
    },
    () => typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia(query).matches,
    () => false,
  );
}

export type ShellLayout = 'desktop' | 'laptop' | 'tablet' | 'field';

/** The shell's layout mode for the current viewport. */
export function useShellLayout(): ShellLayout {
  const desktop = useMediaQuery(BREAKPOINTS.desktop);
  const laptop  = useMediaQuery(BREAKPOINTS.laptop);
  const tablet  = useMediaQuery(BREAKPOINTS.tablet);
  if (desktop) return 'desktop';
  if (laptop) return 'laptop';
  if (tablet) return 'tablet';
  return 'field';
}
