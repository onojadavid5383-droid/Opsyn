// ============================================================
// OPSYN — OverlayPortal
// Renders floating UI (menus, popovers, modals, the task popup) into
// #overlay-root, a sibling of #root declared in index.html.
//
// Why a portal and not in-place rendering: any ancestor with transform,
// filter, backdrop-filter or its own z-index creates a stacking context that
// traps a descendant's z-index — a dropdown opened inside a glass panel would
// render under the next panel over. Rendering outside #root also keeps one
// backdrop-filter surface from ever nesting inside another, which breaks
// glass compositing.
// ============================================================

import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';

export const OVERLAY_ROOT_ID = 'overlay-root';

export function OverlayPortal({ children }: { children: ReactNode }) {
  // Falls back to <body> where #overlay-root doesn't exist (tests, storybook).
  const target = document.getElementById(OVERLAY_ROOT_ID) ?? document.body;
  return createPortal(children, target);
}
