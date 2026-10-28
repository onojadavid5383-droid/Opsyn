// ============================================================
// OPSYN GLASS — GlassModal
// Dialogs and the task-popup workspace, on the modal glass tier.
//
//   <GlassModal open={open} onClose={close} title="Forward task"
//               footer={<><Button …>Cancel</Button><Button …>Forward</Button></>}>
//     …
//   </GlassModal>
//
// Behaviour (Floating UI):
//   - rendered in #overlay-root, above the app, never nested in other glass
//   - focus moves in on open, is trapped, and returns to the trigger on close
//   - Escape and outside-click close only the top-most layer; a glass menu or
//     nested GlassModal opened from inside counts as inside
//   - background scroll locked; aria-modal, labelled by the title
// ============================================================

import {
  FloatingFocusManager, FloatingNode, FloatingOverlay, FloatingPortal,
  useDismiss, useFloating, useFloatingNodeId, useInteractions, useRole,
  useTransitionStatus,
} from '@floating-ui/react';
import { X } from 'lucide-react';
import { useId, useRef, type CSSProperties, type MutableRefObject, type ReactNode } from 'react';
import { useLiquidGlass } from '../../hooks/useLiquidGlass';
import { WithFloatingTree } from './FloatingTreeRoot';
import { READING_GLASS } from './refraction';
import { GLASS_TRANSITION_MS, cx, overlayRoot } from './shared';
import styles from './GlassModal.module.css';

export type GlassModalSize = 'sm' | 'md' | 'lg' | 'xl' | 'workspace';

export interface GlassModalProps {
  open:         boolean;
  onClose:      () => void;
  /** Dialog name — shown in the header and used as the accessible label */
  title?:       ReactNode;
  /** Accessible name when no visible title is rendered */
  ariaLabel?:   string;
  /** Short supporting line under the title (also the accessible description) */
  description?: ReactNode;
  /** Small content above the title — e.g. a ticket-number badge */
  eyebrow?:     ReactNode;
  children:     ReactNode;
  footer?:      ReactNode;
  size?:        GlassModalSize;
  /** 'top' for the command palette; dialogs default to centred */
  align?:       'center' | 'top';
  closeOnBackdrop?: boolean;
  /** Hide the × button (the dialog must then offer its own way out) */
  hideClose?:   boolean;
  /** 'alertdialog' for destructive confirmations */
  role?:        'dialog' | 'alertdialog';
  /** Element to focus first; defaults to the first focusable element */
  initialFocus?: MutableRefObject<HTMLElement | null>;
  className?:   string;
  bodyClassName?: string;
  /** No body padding — for content that manages its own edges (command palette) */
  flush?:       boolean;
  style?:       CSSProperties;
}

export function GlassModal(props: GlassModalProps) {
  return (
    <WithFloatingTree>
      <GlassModalInner {...props} />
    </WithFloatingTree>
  );
}

function GlassModalInner({
  open, onClose, title, ariaLabel, description, eyebrow, children, footer,
  size = 'md', align = 'center', closeOnBackdrop = true, hideClose = false,
  role = 'dialog', initialFocus, className, bodyClassName, flush = false, style,
}: GlassModalProps) {
  const nodeId = useFloatingNodeId();
  const titleId = useId();
  const descId = useId();

  const { refs: { setFloating }, context } = useFloating({
    nodeId,
    open,
    onOpenChange: next => { if (!next) onClose(); },
  });

  const dismiss = useDismiss(context, {
    outsidePress: closeOnBackdrop,
    outsidePressEvent: 'mousedown',
  });
  const roleProps = useRole(context, { role });
  const { getFloatingProps } = useInteractions([dismiss, roleProps]);
  const { isMounted, status } = useTransitionStatus(context, { duration: GLASS_TRANSITION_MS });

  const panelRef = useRef<HTMLDivElement | null>(null);
  useLiquidGlass(panelRef, { enabled: isMounted, config: READING_GLASS });

  return (
    <FloatingNode id={nodeId}>
      <FloatingPortal root={overlayRoot()}>
        {isMounted && (
          <FloatingOverlay
            lockScroll
            className={cx('liquid-glass-scrim', styles.scrim)}
            data-status={status}
            data-align={align}
          >
            <FloatingFocusManager context={context} initialFocus={initialFocus ?? 0} returnFocus>
              <div
                ref={node => { setFloating(node); panelRef.current = node; }}
                className={cx('liquid-glass', 'liquid-glass--modal', styles.panel, styles[size], className)}
                data-status={status}
                aria-labelledby={title ? titleId : undefined}
                aria-label={title ? undefined : ariaLabel}
                aria-describedby={description ? descId : undefined}
                style={style}
                {...getFloatingProps()}
              >
                {(title || eyebrow || description || !hideClose) && (
                  <header className={styles.header}>
                    <div className={styles.headings}>
                      {eyebrow && <div className={styles.eyebrow}>{eyebrow}</div>}
                      {title && <h2 id={titleId} className={styles.title}>{title}</h2>}
                      {description && <p id={descId} className={styles.description}>{description}</p>}
                    </div>
                    {!hideClose && (
                      <button
                        type="button"
                        className={cx('liquid-glass-item', styles.close)}
                        onClick={onClose}
                        aria-label="Close"
                      >
                        <X size={18} aria-hidden="true" />
                      </button>
                    )}
                  </header>
                )}

                <div className={cx(styles.body, bodyClassName)} data-flush={flush || undefined}>{children}</div>

                {footer && <footer className={styles.footer}>{footer}</footer>}
              </div>
            </FloatingFocusManager>
          </FloatingOverlay>
        )}
      </FloatingPortal>
    </FloatingNode>
  );
}
