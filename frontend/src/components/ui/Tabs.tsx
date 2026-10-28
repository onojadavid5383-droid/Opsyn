// ============================================================
// OPSYN UI — Tabs (solid)
// One tab strip for every page view switch (outage views, infrastructure
// asset types, settings sections). ARIA tablist: one Tab stop, arrows /
// Home / End move and select. Counts are part of the accessible name.
// Scrolls horizontally on phones instead of wrapping.
// ============================================================

import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import styles from './Tabs.module.css';

export interface TabItem<T extends string = string> {
  value:  T;
  label:  string;
  count?: number;
  icon?:  ReactNode;
  /** Colour the count when it needs attention */
  tone?:  'critical' | 'warning';
}

export function Tabs<T extends string>({ items, value, onChange, label, idPrefix, className }: {
  items:     TabItem<T>[];
  value:     T;
  onChange:  (value: T) => void;
  /** Accessible name for the tab strip, e.g. "Outage views" */
  label:     string;
  /** When set, tab i gets id `${idPrefix}-tab-${value}` and controls `${idPrefix}-panel` */
  idPrefix?: string;
  className?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = items.findIndex(t => t.value === value);
    let next = -1;
    if (e.key === 'ArrowRight') next = (i + 1) % items.length;
    else if (e.key === 'ArrowLeft') next = (i - 1 + items.length) % items.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = items.length - 1;
    if (next < 0) return;
    e.preventDefault();
    onChange(items[next].value);
    refs.current[next]?.focus();
  };

  return (
    <div role="tablist" aria-label={label} className={[styles.tabs, className].filter(Boolean).join(' ')} onKeyDown={onKeyDown}>
      {items.map((t, i) => {
        const selected = t.value === value;
        return (
          <button
            key={t.value}
            ref={el => { refs.current[i] = el; }}
            type="button"
            role="tab"
            id={idPrefix ? `${idPrefix}-tab-${t.value}` : undefined}
            aria-controls={idPrefix ? `${idPrefix}-panel` : undefined}
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            className={styles.tab}
            onClick={() => onChange(t.value)}
          >
            {t.icon && <span className={styles.icon} aria-hidden="true">{t.icon}</span>}
            {t.label}
            {t.count !== undefined && (
              <span className={styles.count} data-tone={t.count > 0 ? t.tone : undefined}>{t.count.toLocaleString()}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** The region a Tabs strip controls (pairs with idPrefix). */
export function TabPanel({ idPrefix, value, children, className }: {
  idPrefix: string; value: string; children: ReactNode; className?: string;
}) {
  return (
    <div role="tabpanel" id={`${idPrefix}-panel`} aria-labelledby={`${idPrefix}-tab-${value}`} className={className}>
      {children}
    </div>
  );
}
