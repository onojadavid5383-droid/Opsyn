// ============================================================
// OPSYN GLASS — GlassSelect
// A listbox replacing the native <select>, whose open menu the OS draws and
// CSS cannot style. Props match components/ui/Select exactly, so Select can
// switch to this implementation without touching a call site (Phase 4).
//
// Keyboard (matches native select): Enter/Space/↑/↓ open, ↑↓ Home End move,
// type-ahead (also while closed, like native), Enter selects, Escape closes.
// ============================================================

import {
  FloatingFocusManager, FloatingNode, FloatingPortal, autoUpdate, flip, offset,
  size, useClick, useDismiss, useFloating, useFloatingNodeId, useInteractions,
  useListNavigation, useRole, useTransitionStatus, useTypeahead,
} from '@floating-ui/react';
import { Check, ChevronDown } from 'lucide-react';
import { useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { WithFloatingTree } from './FloatingTreeRoot';
import { GLASS_TRANSITION_MS, cx, overlayRoot } from './shared';
import floating from './GlassFloating.module.css';
import styles from './GlassSelect.module.css';

export interface GlassSelectOption {
  label:     string;
  value:     string;
  disabled?: boolean;
}

export interface GlassSelectProps {
  label?:       string;
  id?:          string;
  value:        string;
  onChange:     (value: string) => void;
  options:      GlassSelectOption[];
  /** Shown when value is '' — and offered as the first option, as before */
  placeholder?: string;
  error?:       string;
  hint?:        string;
  required?:    boolean;
  disabled?:    boolean;
  style?:       CSSProperties;
  selectStyle?: CSSProperties;
  /** Submitted with native forms via a hidden input */
  name?:        string;
  /** 32px control for toolbars and filter bars */
  compact?:     boolean;
  /** Accessible name when there is no visible label (e.g. a filter) */
  ariaLabel?:   string;
}

export function GlassSelect(props: GlassSelectProps) {
  return <WithFloatingTree><GlassSelectInner {...props} /></WithFloatingTree>;
}

function GlassSelectInner({
  label, id, value, onChange, options, placeholder, error, hint, required,
  disabled, style, selectStyle, name, compact, ariaLabel,
}: GlassSelectProps) {
  const autoId = useId();
  const triggerId = id ?? (label ? label.toLowerCase().replace(/\s+/g, '-') : `select-${autoId}`);
  const labelId = `${triggerId}-label`;
  const valueId = `${triggerId}-value`;
  const messageId = `${triggerId}-message`;

  // The placeholder stays selectable (value ''), exactly like the native version
  const allOptions = useMemo<GlassSelectOption[]>(
    () => (placeholder ? [{ label: placeholder, value: '' }, ...options] : options),
    [placeholder, options],
  );
  const selectedIndex = allOptions.findIndex(o => o.value === value);
  const selected = selectedIndex >= 0 ? allOptions[selectedIndex] : undefined;

  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const nodeId = useFloatingNodeId();

  const { refs: { setFloating, setReference }, floatingStyles, context } = useFloating({
    nodeId,
    open,
    onOpenChange: setOpen,
    placement: 'bottom-start',
    whileElementsMounted: autoUpdate,
    middleware: [
      offset(4),
      flip({ padding: 8 }),
      size({
        padding: 8,
        apply({ rects, availableHeight, elements }) {
          Object.assign(elements.floating.style, {
            minWidth:  `${rects.reference.width}px`,
            maxHeight: `${Math.min(availableHeight, 320)}px`,
          });
        },
      }),
    ],
  });

  const listRef = useRef<(HTMLElement | null)[]>([]);
  // Type-ahead reads labels on keydown; sync them after render, not during it
  const labelsRef = useRef<(string | null)[]>([]);
  useLayoutEffect(() => { labelsRef.current = allOptions.map(o => o.label); }, [allOptions]);
  const disabledIndices = useMemo(
    () => allOptions.flatMap((o, i) => (o.disabled ? [i] : [])),
    [allOptions],
  );

  const choose = (index: number) => {
    const option = allOptions[index];
    if (!option || option.disabled) return;
    if (option.value !== value) onChange(option.value);
    setOpen(false);
  };

  const click = useClick(context, { enabled: !disabled });
  const dismiss = useDismiss(context);
  const role = useRole(context, { role: 'listbox' });
  const listNav = useListNavigation(context, {
    listRef, activeIndex, selectedIndex: selectedIndex >= 0 ? selectedIndex : null,
    onNavigate: setActiveIndex, loop: true, disabledIndices,
  });
  const typeahead = useTypeahead(context, {
    listRef: labelsRef,
    activeIndex,
    selectedIndex: selectedIndex >= 0 ? selectedIndex : null,
    // Closed: type-ahead changes the value directly, as a native select does
    onMatch: index => (open ? setActiveIndex(index) : choose(index)),
  });
  const { getReferenceProps, getFloatingProps, getItemProps } =
    useInteractions([click, dismiss, role, listNav, typeahead]);
  const { isMounted, status } = useTransitionStatus(context, { duration: GLASS_TRANSITION_MS });

  const describedBy = error || hint ? messageId : undefined;
  const showPlaceholder = !selected || (selected.value === '' && !!placeholder);

  return (
    <FloatingNode id={nodeId}>
      <div className={styles.field} data-inline={!label || undefined} style={style}>
        {label && (
          <label id={labelId} htmlFor={triggerId} className={styles.label}>
            {label}
            {required && <span className={styles.required} aria-hidden="true">*</span>}
          </label>
        )}

        <button
          id={triggerId}
          ref={setReference}
          type="button"
          disabled={disabled}
          aria-labelledby={label ? `${labelId} ${valueId}` : undefined}
          aria-label={!label ? ariaLabel : undefined}
          aria-required={required || undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={cx(styles.trigger, compact && styles.compact)}
          style={selectStyle}
          {...getReferenceProps()}
        >
          <span id={valueId} className={cx(styles.value, showPlaceholder && styles.placeholder)}>
            {selected?.label ?? placeholder ?? 'Select…'}
          </span>
          <ChevronDown size={16} className={styles.chevron} aria-hidden="true" />
        </button>

        {name && <input type="hidden" name={name} value={value} />}

        {(error || hint) && (
          <div id={messageId} className={cx(styles.message, error && styles.error)} role={error ? 'alert' : undefined}>
            {error ?? hint}
          </div>
        )}
      </div>

      <FloatingPortal root={overlayRoot()}>
        {isMounted && (
          <FloatingFocusManager context={context} modal={false}>
            <div
              ref={setFloating}
              style={floatingStyles}
              data-status={status}
              aria-labelledby={label ? labelId : undefined}
              aria-label={!label ? ariaLabel : undefined}
              className={cx('liquid-glass-menu', floating.floating)}
              {...getFloatingProps()}
            >
              {allOptions.map((option, i) => {
                const isSelected = i === selectedIndex;
                return (
                  <div
                    key={option.value || '__placeholder'}
                    ref={node => { listRef.current[i] = node; }}
                    role="option"
                    tabIndex={activeIndex === i ? 0 : -1}
                    aria-selected={isSelected}
                    aria-disabled={option.disabled || undefined}
                    data-active={activeIndex === i ? 'true' : undefined}
                    className={cx('liquid-glass-item', floating.item)}
                    {...getItemProps({
                      onClick: () => choose(i),
                      onKeyDown: e => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          choose(i);
                        }
                      },
                    })}
                  >
                    <span className={cx(floating.itemLabel, option.value === '' && placeholder && styles.placeholder)}>
                      {option.label}
                    </span>
                    {isSelected && <Check size={16} className={floating.check} aria-hidden="true" />}
                  </div>
                );
              })}
            </div>
          </FloatingFocusManager>
        )}
      </FloatingPortal>
    </FloatingNode>
  );
}
