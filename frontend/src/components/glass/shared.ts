// ============================================================
// OPSYN GLASS — shared helpers (no components; see FloatingTreeRoot.tsx)
// ============================================================

import { useFloating, useTransitionStatus } from '@floating-ui/react';
import { OVERLAY_ROOT_ID } from '../overlay/OverlayPortal';

/**
 * Portal target for Floating UI — the #overlay-root sibling of #root.
 * Returns undefined (not null) when it's missing: Floating UI reads a null
 * root as "not ready" and renders nothing, whereas undefined falls back to
 * <body>, matching OverlayPortal.
 */
export function overlayRoot(): HTMLElement | undefined {
  if (typeof document === 'undefined') return undefined;
  return document.getElementById(OVERLAY_ROOT_ID) ?? undefined;
}

/** Enter/exit timing shared by every glass surface (matches --duration-base). */
export const GLASS_TRANSITION_MS = 180;

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}

/**
 * Mount/exit status for surfaces that aren't Floating UI-anchored (docked
 * drawers): keeps the element mounted through its exit transition and exposes
 * data-status 'initial' | 'open' | 'close'. Delegates to Floating UI's
 * useTransitionStatus so every glass surface animates on the same clock.
 *
 * Attach `setElement` to the surface: the clock only advances once an
 * element is registered (without it, status stays 'unmounted' while the
 * element is visible — no enter/exit transition runs).
 */
export function usePresence(open: boolean, durationMs = GLASS_TRANSITION_MS) {
  const { refs: { setFloating }, context } = useFloating({ open });
  const { isMounted, status } = useTransitionStatus(context, { duration: durationMs });
  return { isMounted, status, setElement: setFloating };
}
