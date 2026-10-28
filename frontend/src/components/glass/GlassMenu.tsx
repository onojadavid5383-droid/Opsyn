// ============================================================
// OPSYN GLASS — GlassMenu + GlassContextMenu
// Action / overflow / profile / notification menus, and right-click menus.
//
//   <GlassMenu
//     label="Task actions"
//     items={[
//       { id: 'fwd', label: 'Forward', icon: <Forward size={16}/>, onSelect: forward },
//       { type: 'separator' },
//       { id: 'del', label: 'Delete task', danger: true, onSelect: remove },
//     ]}
//     renderTrigger={props => <button {...props}>Actions</button>}
//   />
//
// Keyboard: Enter/Space/↓ opens, ↑↓ Home End move, type-ahead, Enter selects,
// Escape closes and returns focus to the trigger. role="menu" + menuitem.
// ============================================================

import {
  FloatingFocusManager, FloatingNode, FloatingPortal, autoUpdate, flip, offset,
  shift, size, useClick, useDismiss, useFloating, useFloatingNodeId,
  useInteractions, useListNavigation, useRole, useTransitionStatus, useTypeahead,
  type Placement, type UseFloatingReturn,
} from '@floating-ui/react';
import {
  useLayoutEffect, useMemo, useRef, useState, type HTMLProps, type KeyboardEvent, type MouseEvent,
  type MutableRefObject, type ReactNode,
} from 'react';
import { WithFloatingTree } from './FloatingTreeRoot';
import { GLASS_TRANSITION_MS, cx, overlayRoot } from './shared';
import styles from './GlassFloating.module.css';

export type GlassMenuEntry =
  | {
      type?:     'item';
      id:        string;
      label:     string;
      icon?:     ReactNode;
      /** Right-aligned secondary text (e.g. a count) */
      hint?:     string;
      /** Keyboard shortcut shown for reference, e.g. "Ctrl K" */
      shortcut?: string;
      danger?:   boolean;
      disabled?: boolean;
      onSelect:  () => void;
    }
  | { type: 'separator' }
  | { type: 'group'; label: string };

type ActionEntry = Extract<GlassMenuEntry, { onSelect: () => void }>;
const isAction = (e: GlassMenuEntry): e is ActionEntry => e.type === undefined || e.type === 'item';

/** Props to spread on the trigger element (any element: button, link…). */
export type MenuTriggerProps = Record<string, unknown> & { ref: (node: HTMLElement | null) => void };

const FLOATING_MIDDLEWARE = [
  offset(6),
  flip({ padding: 8 }),
  shift({ padding: 8 }),
  size({
    padding: 8,
    apply({ availableHeight, elements }) {
      elements.floating.style.maxHeight = `${Math.min(availableHeight, 440)}px`;
    },
  }),
];


// ── Shared list ───────────────────────────────────────────────

function useMenuList(context: UseFloatingReturn['context'], items: GlassMenuEntry[], open: boolean) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const listRef = useRef<(HTMLElement | null)[]>([]);
  const actions = useMemo(() => items.filter(isAction), [items]);
  // Type-ahead reads labels on keydown; sync them after render, not during it
  const labelsRef = useRef<(string | null)[]>([]);
  useLayoutEffect(() => { labelsRef.current = actions.map(a => a.label); }, [actions]);
  const disabledIndices = useMemo(
    () => actions.flatMap((a, i) => (a.disabled ? [i] : [])),
    [actions],
  );

  const listNav = useListNavigation(context, {
    listRef, activeIndex, onNavigate: setActiveIndex, loop: true, disabledIndices,
  });
  const typeahead = useTypeahead(context, {
    listRef: labelsRef, activeIndex, onMatch: open ? setActiveIndex : undefined,
  });
  return { activeIndex, listRef, listNav, typeahead };
}

function MenuItems({
  items, activeIndex, listRef, getItemProps, onDone,
}: {
  items:        GlassMenuEntry[];
  activeIndex:  number | null;
  listRef:      MutableRefObject<(HTMLElement | null)[]>;
  getItemProps: (props?: HTMLProps<HTMLElement>) => Record<string, unknown>;
  onDone:       () => void;
}) {
  let index = -1;
  return (
    <>
      {items.map((entry, pos) => {
        if (entry.type === 'separator') return <div key={`sep-${pos}`} role="separator" className={styles.separator} />;
        if (entry.type === 'group') return <div key={`grp-${pos}`} role="presentation" className={styles.groupLabel}>{entry.label}</div>;

        const i = ++index;
        return (
          <button
            key={entry.id}
            type="button"
            role="menuitem"
            ref={node => { listRef.current[i] = node; }}
            tabIndex={activeIndex === i ? 0 : -1}
            aria-disabled={entry.disabled || undefined}
            data-active={activeIndex === i ? 'true' : undefined}
            className={cx('liquid-glass-item', styles.item, entry.danger && styles.danger)}
            {...getItemProps({
              onClick() {
                if (entry.disabled) return;
                entry.onSelect();
                onDone();
              },
            })}
          >
            {entry.icon && <span className={styles.itemIcon} aria-hidden="true">{entry.icon}</span>}
            <span className={styles.itemLabel}>{entry.label}</span>
            {entry.hint && <span className={styles.itemHint}>{entry.hint}</span>}
            {entry.shortcut && <kbd className={styles.shortcut}>{entry.shortcut}</kbd>}
          </button>
        );
      })}
    </>
  );
}


// ── GlassMenu ─────────────────────────────────────────────────

export interface GlassMenuProps {
  items:          GlassMenuEntry[];
  /** Accessible name for the menu, e.g. "Task actions" */
  label:          string;
  renderTrigger:  (props: MenuTriggerProps, state: { open: boolean }) => ReactNode;
  placement?:     Placement;
  /** Optional content above the items (e.g. signed-in user) */
  header?:        ReactNode;
  className?:     string;
  /** The menu portals out of its trigger's subtree — pass 'console' when the trigger sits on the dark console surface (map, health bar) */
  surface?:       'console';
}

export function GlassMenu(props: GlassMenuProps) {
  return <WithFloatingTree><GlassMenuInner {...props} /></WithFloatingTree>;
}

function GlassMenuInner({ items, label, renderTrigger, placement = 'bottom-start', header, className, surface }: GlassMenuProps) {
  const [open, setOpen] = useState(false);
  const nodeId = useFloatingNodeId();
  const { refs: { setFloating, setReference }, floatingStyles, context } = useFloating({
    nodeId, open, onOpenChange: setOpen, placement,
    middleware: FLOATING_MIDDLEWARE, whileElementsMounted: autoUpdate,
  });

  const { activeIndex, listRef, listNav, typeahead } = useMenuList(context, items, open);
  const click = useClick(context);
  // Default bubbling: Escape closes only this menu, never the dialog it sits in
  const dismiss = useDismiss(context);
  const role = useRole(context, { role: 'menu' });
  const { getReferenceProps, getFloatingProps, getItemProps } =
    useInteractions([click, dismiss, role, listNav, typeahead]);
  const { isMounted, status } = useTransitionStatus(context, { duration: GLASS_TRANSITION_MS });

  const triggerProps = getReferenceProps();
  // useRole marks the trigger role="menuitem" whenever the menu has ANY parent
  // in the floating tree (it assumes a submenu). Inside the task popup the
  // parent is a dialog, not a menu — and OpSyn has no submenus — so the
  // trigger keeps its own role (a button stays a button).
  delete triggerProps.role;
  return (
    <FloatingNode id={nodeId}>
      {renderTrigger({ ...triggerProps, ref: setReference }, { open })}
      <FloatingPortal root={overlayRoot()}>
        {isMounted && (
          <FloatingFocusManager context={context} modal={false} initialFocus={0}>
            <div
              ref={setFloating}
              style={floatingStyles}
              data-status={status}
              data-surface={surface}
              className={cx('liquid-glass-menu', styles.floating, className)}
              {...getFloatingProps()}
              // After the spread: useRole labels the menu by its trigger, which
              // would override the more specific name ("Task actions", not "Actions")
              aria-labelledby={undefined}
              aria-label={label}
            >
              {header}
              <MenuItems
                items={items}
                activeIndex={activeIndex}
                listRef={listRef}
                getItemProps={getItemProps}
                onDone={() => setOpen(false)}
              />
            </div>
          </FloatingFocusManager>
        )}
      </FloatingPortal>
    </FloatingNode>
  );
}


// ── GlassContextMenu ──────────────────────────────────────────

export interface ContextMenuBindings {
  onContextMenu: (e: MouseEvent<HTMLElement>) => void;
  /** Shift+F10 / the Menu key open it from the keyboard at the focused element */
  onKeyDown:     (e: KeyboardEvent<HTMLElement>) => void;
}

export interface GlassContextMenuProps {
  items:    GlassMenuEntry[];
  label:    string;
  /** Spread the bindings onto the region that owns the menu (a row, a map feature…) */
  children: (bind: ContextMenuBindings) => ReactNode;
}

export function GlassContextMenu(props: GlassContextMenuProps) {
  return <WithFloatingTree><GlassContextMenuInner {...props} /></WithFloatingTree>;
}

function GlassContextMenuInner({ items, label, children }: GlassContextMenuProps) {
  const [open, setOpen] = useState(false);
  const nodeId = useFloatingNodeId();
  const { refs: { setFloating, setPositionReference }, floatingStyles, context } = useFloating({
    nodeId, open, onOpenChange: setOpen, placement: 'right-start',
    middleware: [offset({ mainAxis: 4, alignmentAxis: 4 }), ...FLOATING_MIDDLEWARE.slice(1)],
    whileElementsMounted: autoUpdate,
  });

  const { activeIndex, listRef, listNav, typeahead } = useMenuList(context, items, open);
  const dismiss = useDismiss(context);
  const role = useRole(context, { role: 'menu' });
  const { getFloatingProps, getItemProps } = useInteractions([dismiss, role, listNav, typeahead]);
  const { isMounted, status } = useTransitionStatus(context, { duration: GLASS_TRANSITION_MS });

  const openAt = (x: number, y: number) => {
    setPositionReference({
      getBoundingClientRect: () => ({ x, y, width: 0, height: 0, top: y, left: x, right: x, bottom: y }),
    });
    setOpen(true);
  };

  const bind: ContextMenuBindings = {
    onContextMenu(e) {
      e.preventDefault();
      openAt(e.clientX, e.clientY);
    },
    onKeyDown(e) {
      if ((e.shiftKey && e.key === 'F10') || e.key === 'ContextMenu') {
        e.preventDefault();
        const rect = e.currentTarget.getBoundingClientRect();
        openAt(rect.left + 8, rect.top + rect.height / 2);
      }
    },
  };

  return (
    <FloatingNode id={nodeId}>
      {children(bind)}
      <FloatingPortal root={overlayRoot()}>
        {isMounted && (
          <FloatingFocusManager context={context} modal={false} initialFocus={0}>
            <div
              ref={setFloating}
              style={floatingStyles}
              data-status={status}
              className={cx('liquid-glass-menu', styles.floating)}
              {...getFloatingProps()}
              aria-labelledby={undefined}
              aria-label={label}
            >
              <MenuItems
                items={items}
                activeIndex={activeIndex}
                listRef={listRef}
                getItemProps={getItemProps}
                onDone={() => setOpen(false)}
              />
            </div>
          </FloatingFocusManager>
        )}
      </FloatingPortal>
    </FloatingNode>
  );
}
