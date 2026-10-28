// ============================================================
// OPSYN GLASS — GlassDrawer, GlassSidebar, GlassInspector
//
// GlassSidebar   secondary / contextual navigation (left). Visibly separate
//                from the solid primary sidebar: it floats, as glass.
// GlassInspector detail panel for a selected map feature / record (right);
//                a bottom sheet on phones.
//
// Docked (default): rendered in place, absolutely positioned inside the
// caller's `position: relative` container. Escape closes it while focus is
// inside; it never traps focus.
// Modal: rendered in #overlay-root over a scrim, focus trapped, Escape /
// outside-click close — for narrow screens where it covers the content.
// ============================================================

import {
  FloatingFocusManager, FloatingOverlay, FloatingPortal, useDismiss, useFloating,
  useInteractions, useRole, useTransitionStatus,
} from '@floating-ui/react';
import { X } from 'lucide-react';
import { useId, useRef, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react';
import { useLiquidGlass } from '../../hooks/useLiquidGlass';
import { WithFloatingTree } from './FloatingTreeRoot';
import { READING_GLASS } from './refraction';
import { GLASS_TRANSITION_MS, cx, overlayRoot, usePresence } from './shared';
import styles from './GlassDrawer.module.css';

export interface GlassDrawerProps {
  open:          boolean;
  onOpenChange:  (open: boolean) => void;
  side:          'left' | 'right';
  /** Landmark element: nav for navigation, aside for details */
  as?:           'nav' | 'aside' | 'section';
  /** Accessible name — required: a landmark must say what it is */
  label:         string;
  title?:        ReactNode;
  subtitle?:     ReactNode;
  /** Icon buttons beside the close button */
  actions?:      ReactNode;
  children:      ReactNode;
  width?:        number;
  modal?:        boolean;
  /** Right-side drawers become a bottom sheet under 768px (default: right only) */
  sheetOnMobile?: boolean;
  hideClose?:    boolean;
  className?:    string;
  style?:        CSSProperties;
}

export function GlassDrawer(props: GlassDrawerProps) {
  return props.modal
    ? <WithFloatingTree><ModalDrawer {...props} /></WithFloatingTree>
    : <DockedDrawer {...props} />;
}

export function GlassSidebar(props: Omit<GlassDrawerProps, 'side' | 'as'>) {
  return <GlassDrawer {...props} side="left" as="nav" />;
}

export function GlassInspector(props: Omit<GlassDrawerProps, 'side' | 'as'>) {
  return <GlassDrawer {...props} side="right" as="aside" />;
}


function DrawerContent({
  title, subtitle, actions, children, hideClose, onClose, titleId,
}: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode;
  hideClose?: boolean; onClose: () => void; titleId: string;
}) {
  return (
    <>
      {(title || actions || !hideClose) && (
        <header className={styles.header}>
          <div className={styles.headings}>
            {title && <h2 id={titleId} className={styles.title}>{title}</h2>}
            {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
          </div>
          {actions && <div className={styles.actions}>{actions}</div>}
          {!hideClose && (
            <button type="button" className={cx('liquid-glass-item', styles.close)} onClick={onClose} aria-label="Close panel">
              <X size={18} aria-hidden="true" />
            </button>
          )}
        </header>
      )}
      <div className={styles.body}>{children}</div>
    </>
  );
}

function drawerClasses(p: GlassDrawerProps, extra?: string) {
  const sheet = p.sheetOnMobile ?? p.side === 'right';
  return cx(
    'liquid-glass', 'liquid-glass--solid-read',
    styles.drawer, styles[p.side], sheet && styles.sheet, extra, p.className,
  );
}

function DockedDrawer(props: GlassDrawerProps) {
  const { open, onOpenChange, as: Tag = 'aside', label, title, width, style } = props;
  const { isMounted, status, setElement } = usePresence(open);
  const ref = useRef<HTMLElement | null>(null);
  const titleId = useId();
  useLiquidGlass(ref, { enabled: isMounted, config: READING_GLASS });

  if (!isMounted) return null;

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onOpenChange(false);
    }
  };

  return (
    <Tag
      ref={(node: HTMLElement | null) => { ref.current = node; setElement(node); }}
      aria-label={title ? undefined : label}
      aria-labelledby={title ? titleId : undefined}
      data-status={status}
      className={drawerClasses(props)}
      style={{ ...(width ? { ['--drawer-w' as string]: `${width}px` } : null), ...style }}
      onKeyDown={onKeyDown}
    >
      <DrawerContent {...props} onClose={() => onOpenChange(false)} titleId={titleId} />
    </Tag>
  );
}

function ModalDrawer(props: GlassDrawerProps) {
  const { open, onOpenChange, label, title, width, style } = props;
  const titleId = useId();
  const { refs: { setFloating }, context } = useFloating({ open, onOpenChange });
  const dismiss = useDismiss(context, { outsidePressEvent: 'mousedown' });
  const role = useRole(context, { role: 'dialog' });
  const { getFloatingProps } = useInteractions([dismiss, role]);
  // Anchored to this dialog's own context, so its transition clock runs
  const { isMounted, status } = useTransitionStatus(context, { duration: GLASS_TRANSITION_MS });
  const ref = useRef<HTMLElement | null>(null);
  useLiquidGlass(ref, { enabled: isMounted, config: READING_GLASS });

  return (
    <FloatingPortal root={overlayRoot()}>
      {isMounted && (
        <FloatingOverlay lockScroll className={cx('liquid-glass-scrim', styles.modalScrim)} data-status={status}>
          <FloatingFocusManager context={context}>
            <div
              ref={node => { setFloating(node); ref.current = node; }}
              aria-label={title ? undefined : label}
              aria-labelledby={title ? titleId : undefined}
              data-status={status}
              className={drawerClasses(props, styles.modal)}
              style={{ ...(width ? { ['--drawer-w' as string]: `${width}px` } : null), ...style }}
              {...getFloatingProps()}
            >
              <DrawerContent {...props} onClose={() => onOpenChange(false)} titleId={titleId} />
            </div>
          </FloatingFocusManager>
        </FloatingOverlay>
      )}
    </FloatingPortal>
  );
}
