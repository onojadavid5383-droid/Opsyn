// ============================================================
// OPSYN GLASS — GlassButton, GlassToolbar
//
//   <GlassToolbar label="Map controls" orientation="vertical">
//     <GlassButton shape="icon" aria-label="Zoom in" icon={<Plus size={16}/>} />
//     <GlassToolbarDivider />
//     <GlassButton shape="icon" aria-label="Layers" aria-pressed={layersOpen} … />
//   </GlassToolbar>
//
// Icon-only buttons must carry aria-label (enforced by the types) and get a
// GlassTooltip with the same text automatically.
// ============================================================

import {
  createContext, forwardRef, useCallback, useContext, useLayoutEffect, useRef,
  type ButtonHTMLAttributes, type KeyboardEvent, type ReactNode,
} from 'react';
import { useLiquidGlass } from '../../hooks/useLiquidGlass';
import { GlassTooltip } from './GlassPopover';
import { cx } from './shared';
import styles from './GlassControls.module.css';

type Base = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> & {
  variant?: 'glass' | 'brand';
  size?:    'sm' | 'md' | 'lg';
  icon?:    ReactNode;
};

export type GlassButtonProps =
  | (Base & { shape?: 'default'; 'aria-label'?: string })
  /** Icon-only and FAB have no visible text, so a name is mandatory */
  | (Base & { shape: 'icon' | 'fab'; 'aria-label': string });

/** True inside a GlassToolbar: its buttons share the toolbar's glass (rule 3/4) */
const InToolbarContext = createContext(false);

export const GlassButton = forwardRef<HTMLButtonElement, GlassButtonProps>(function GlassButton(
  { variant = 'glass', size = 'md', shape = 'default', icon, children, className, type = 'button', ...rest },
  forwardedRef,
) {
  const inToolbar = useContext(InToolbarContext);
  const localRef = useRef<HTMLButtonElement | null>(null);
  // Only the FAB refracts — toolbars repeat buttons, and chips are CSS-only
  useLiquidGlass(localRef, { enabled: shape === 'fab' && !inToolbar });

  const setRef = useCallback((node: HTMLButtonElement | null) => {
    localRef.current = node;
    if (typeof forwardedRef === 'function') forwardedRef(node);
    else if (forwardedRef) forwardedRef.current = node;
  }, [forwardedRef]);

  const iconOnly = shape === 'icon' || shape === 'fab';
  const button = (
    <button
      ref={setRef}
      type={type}
      className={cx(
        styles.button,
        // Inside a toolbar: no surface of its own — no nested backdrop-filter
        variant === 'glass' && !inToolbar && (shape === 'fab' ? 'liquid-glass' : 'liquid-glass-chip'),
        variant === 'glass' && styles.glass,
        variant === 'brand' && styles.brand,
        size !== 'md' && styles[size],
        shape === 'icon' && styles.icon,
        shape === 'fab' && styles.fab,
        className,
      )}
      {...rest}
    >
      {icon && <span aria-hidden="true" style={{ display: 'contents' }}>{icon}</span>}
      {!iconOnly && children}
    </button>
  );

  return iconOnly
    ? <GlassTooltip content={rest['aria-label'] as string}>{button}</GlassTooltip>
    : button;
});


// ── Toolbar ───────────────────────────────────────────────────

export interface GlassToolbarProps {
  /** Accessible name, e.g. "Map controls" or "Bulk actions" */
  label:        string;
  orientation?: 'horizontal' | 'vertical';
  children:     ReactNode;
  className?:   string;
}

const ITEM_SELECTOR = 'button:not(:disabled), [data-toolbar-item]:not([aria-disabled="true"])';

export function GlassToolbar({ label, orientation = 'horizontal', children, className }: GlassToolbarProps) {
  const ref = useRef<HTMLDivElement>(null);

  // Roving tabindex: the toolbar is one Tab stop; arrows move inside it
  useLayoutEffect(() => {
    const items = Array.from(ref.current?.querySelectorAll<HTMLElement>(ITEM_SELECTOR) ?? []);
    if (items.length === 0) return;
    const current = items.findIndex(el => el.tabIndex === 0);
    items.forEach((el, i) => { el.tabIndex = i === (current >= 0 ? current : 0) ? 0 : -1; });
  });

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const next = orientation === 'horizontal' ? 'ArrowRight' : 'ArrowDown';
    const prev = orientation === 'horizontal' ? 'ArrowLeft' : 'ArrowUp';
    if (![next, prev, 'Home', 'End'].includes(e.key)) return;

    const items = Array.from(ref.current?.querySelectorAll<HTMLElement>(ITEM_SELECTOR) ?? []);
    const at = items.indexOf(document.activeElement as HTMLElement);
    if (at < 0) return;
    e.preventDefault();

    const target =
      e.key === 'Home' ? 0 :
      e.key === 'End'  ? items.length - 1 :
      e.key === next   ? (at + 1) % items.length :
                         (at - 1 + items.length) % items.length;
    items.forEach((el, i) => { el.tabIndex = i === target ? 0 : -1; });
    items[target].focus();
  };

  return (
    <div
      ref={ref}
      role="toolbar"
      aria-label={label}
      aria-orientation={orientation}
      className={cx('liquid-glass-chip', styles.toolbar, className)}
      onKeyDown={onKeyDown}
    >
      <InToolbarContext.Provider value={true}>{children}</InToolbarContext.Provider>
    </div>
  );
}

export function GlassToolbarDivider() {
  return <span role="separator" className={styles.divider} />;
}
