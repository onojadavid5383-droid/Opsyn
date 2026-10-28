// ============================================================
// OPSYN GLASS — GlassPopover + GlassTooltip
//
// GlassPopover: an anchored, non-modal panel for interactive content —
// filter panels, column choosers, date pickers, status pickers.
//
//   <GlassPopover title="Filter outages"
//     renderTrigger={p => <button {...p}>Filters</button>}>
//     {({ close }) => <FilterForm onApply={close} />}
//   </GlassPopover>
//
// GlassTooltip: the visible name of an icon-only control, on hover and focus.
// It supplements aria-label; it never carries information nothing else does.
// ============================================================

import {
  FloatingFocusManager, FloatingNode, FloatingPortal, autoUpdate, flip, offset,
  safePolygon, shift, size, useClick, useDismiss, useFloating, useFloatingNodeId,
  useFocus, useHover, useInteractions, useMergeRefs, useRole, useTransitionStatus,
  type Placement,
} from '@floating-ui/react';
import { cloneElement, isValidElement, useId, useState, type ReactElement, type ReactNode, type Ref } from 'react';
import { WithFloatingTree } from './FloatingTreeRoot';
import { GLASS_TRANSITION_MS, cx, overlayRoot } from './shared';
import styles from './GlassFloating.module.css';

/** Props to spread on the trigger element (any element: button, link…). */
export type PopoverTriggerProps = Record<string, unknown> & { ref: (node: HTMLElement | null) => void };

export interface GlassPopoverProps {
  renderTrigger: (props: PopoverTriggerProps, state: { open: boolean }) => ReactNode;
  children:      ReactNode | ((api: { close: () => void }) => ReactNode);
  /** Visible heading; also the popover's accessible name */
  title?:        string;
  ariaLabel?:    string;
  placement?:    Placement;
  /** Controlled mode */
  open?:         boolean;
  onOpenChange?: (open: boolean) => void;
  className?:    string;
}

export function GlassPopover(props: GlassPopoverProps) {
  return <WithFloatingTree><GlassPopoverInner {...props} /></WithFloatingTree>;
}

function GlassPopoverInner({
  renderTrigger, children, title, ariaLabel, placement = 'bottom-start',
  open: controlledOpen, onOpenChange, className,
}: GlassPopoverProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  const open = controlledOpen ?? uncontrolledOpen;
  const setOpen = (next: boolean) => {
    if (controlledOpen === undefined) setUncontrolledOpen(next);
    onOpenChange?.(next);
  };

  const nodeId = useFloatingNodeId();
  const titleId = useId();
  const { refs: { setFloating, setReference }, floatingStyles, context } = useFloating({
    nodeId, open, onOpenChange: setOpen, placement,
    whileElementsMounted: autoUpdate,
    middleware: [
      offset(8), flip({ padding: 8 }), shift({ padding: 8 }),
      size({
        padding: 8,
        apply({ availableHeight, elements }) {
          elements.floating.style.maxHeight = `${availableHeight}px`;
        },
      }),
    ],
  });

  const click = useClick(context);
  // Default bubbling: Escape closes only this popover, never its parent layer
  const dismiss = useDismiss(context);
  const role = useRole(context, { role: 'dialog' });
  const { getReferenceProps, getFloatingProps } = useInteractions([click, dismiss, role]);
  const { isMounted, status } = useTransitionStatus(context, { duration: GLASS_TRANSITION_MS });
  const close = () => setOpen(false);

  return (
    <FloatingNode id={nodeId}>
      {renderTrigger({ ...getReferenceProps(), ref: setReference }, { open })}
      <FloatingPortal root={overlayRoot()}>
        {isMounted && (
          <FloatingFocusManager context={context} modal={false}>
            <div
              ref={setFloating}
              style={floatingStyles}
              data-status={status}
              aria-labelledby={title ? titleId : undefined}
              aria-label={title ? undefined : ariaLabel}
              className={cx('liquid-glass-menu', styles.floating, styles.popover, className)}
              {...getFloatingProps()}
            >
              {title && <h3 id={titleId} className={styles.popoverTitle}>{title}</h3>}
              {typeof children === 'function' ? children({ close }) : children}
            </div>
          </FloatingFocusManager>
        )}
      </FloatingPortal>
    </FloatingNode>
  );
}


// ── GlassTooltip ──────────────────────────────────────────────

export interface GlassTooltipProps {
  content:    string;
  /** A single element that accepts a ref (a button, a link) */
  children:   ReactElement;
  placement?: Placement;
}

export function GlassTooltip({ content, children, placement = 'top' }: GlassTooltipProps) {
  const [open, setOpen] = useState(false);
  const { refs: { setFloating, setReference }, floatingStyles, context } = useFloating({
    open, onOpenChange: setOpen, placement,
    whileElementsMounted: autoUpdate,
    middleware: [offset(6), flip({ padding: 8 }), shift({ padding: 8 })],
  });
  const hover = useHover(context, { delay: { open: 400, close: 0 }, move: false, handleClose: safePolygon() });
  const focus = useFocus(context);
  const dismiss = useDismiss(context);
  const role = useRole(context, { role: 'tooltip' });
  const { getReferenceProps, getFloatingProps } = useInteractions([hover, focus, dismiss, role]);
  const { isMounted, status } = useTransitionStatus(context, { duration: 120 });
  // Keep the child's own ref working (e.g. GlassButton's refraction ref):
  // cloneElement with a new ref would otherwise replace it.
  const childRef = isValidElement(children) ? (children as unknown as { ref?: Ref<HTMLElement> }).ref : undefined;
  const mergedRef = useMergeRefs([setReference, childRef]);

  if (!isValidElement(children)) return children;
  const child = children as ReactElement<Record<string, unknown>>;

  return (
    <>
      {cloneElement(child, getReferenceProps({ ...child.props, ref: mergedRef }))}
      <FloatingPortal root={overlayRoot()}>
        {isMounted && (
          <div
            ref={setFloating}
            style={floatingStyles}
            data-status={status}
            className={cx('liquid-glass-menu', styles.tooltip)}
            {...getFloatingProps()}
          >
            {content}
          </div>
        )}
      </FloatingPortal>
    </>
  );
}
