// ============================================================
// OPSYN UI — Modal  (Phase 4)
// Same props as before; now a GlassModal. Gains what the old one lacked:
// rendered above the app (no stacking-context traps), focus that follows
// content changes (the old trap captured focusable elements once, at open),
// focus returned to the trigger on close, and correct nesting — Escape
// closes only the top-most dialog.
// ============================================================

import type React from 'react';
import { GlassModal } from '../glass';

export type ModalSize = 'sm' | 'md' | 'lg' | 'xl';

export interface ModalProps {
  open:             boolean;
  onClose:          () => void;
  title?:           React.ReactNode;
  children:         React.ReactNode;
  footer?:          React.ReactNode;
  size?:            ModalSize;
  closeOnBackdrop?: boolean;
  style?:           React.CSSProperties;
}

export function Modal({ open, onClose, title, children, footer, size = 'md', closeOnBackdrop = true, style }: ModalProps) {
  return (
    <GlassModal
      open={open}
      onClose={onClose}
      title={title}
      ariaLabel={typeof title === 'string' ? title : 'Dialog'}
      footer={footer}
      size={size}
      closeOnBackdrop={closeOnBackdrop}
      style={style}
    >
      {children}
    </GlassModal>
  );
}
