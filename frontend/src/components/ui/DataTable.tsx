// ============================================================
// OPSYN UI — DataTable  (Phase 4)
// The one table system. Existing call sites (7 pages) work unchanged:
//   columns · data · rowKey · isLoading · empty* · onRowClick · stickyHeader · style
//
// Built in: keyboard-sortable headers (buttons + aria-sort), numeric-aware
// sorting, tabular numbers, skeleton loading, rows that open with Enter,
// and on phones (<768px) each row becomes a card.
//
// Opt-in:
//   sort + onSortChange      controlled / server-side sorting
//   selectable + bulkActions checkboxes and a floating glass action bar
//   columnChooser            show/hide columns (glass popover)
//   densityToggle            comfortable 44px / compact 32px rows
//   viewKey                  remember hidden columns + density per table
//   maxHeight                scroll inside the table; the header sticks
//   toolbar                  content on the left of the table toolbar
//
// Columns may add: numeric (right-aligned), mono (IDs), sortValue,
// hideable/defaultHidden, mobile: 'title' | 'field' | 'hidden'.
// ============================================================

import { ArrowDown, ArrowUp, ArrowUpDown, Columns3, Rows3, X } from 'lucide-react';
import React, { useEffect, useMemo, useState } from 'react';
import { GlassButton, GlassPopover, GlassToolbar } from '../glass';
import { OverlayPortal } from '../overlay/OverlayPortal';
import { BREAKPOINTS, useMediaQuery } from '../../hooks/useMediaQuery';
import { EmptyState } from './EmptyState';
import styles from './DataTable.module.css';

export interface Column<T = any> {
  key:       string;
  header:    string;
  width?:    number | string;
  align?:    'left' | 'center' | 'right';
  sortable?: boolean;
  render?:   (value: any, row: T, index: number) => React.ReactNode;
  /** Right-aligned, tabular — counts, lengths, dB, percentages */
  numeric?:  boolean;
  /** Monospace — ticket numbers, asset IDs, IPs, coordinates */
  mono?:     boolean;
  /** Value used for sorting when the cell renders something else */
  sortValue?: (row: T) => string | number | null | undefined;
  /** Can be hidden from the column chooser (default true) */
  hideable?: boolean;
  defaultHidden?: boolean;
  /** Phone card layout: the card's title, a labelled field (default), or omitted */
  mobile?:   'title' | 'field' | 'hidden';
}

export type SortDir = 'asc' | 'desc';
export interface SortState { key: string; dir: SortDir }
export type Density = 'comfortable' | 'compact';

export interface DataTableProps<T = any> {
  columns:       Column<T>[];
  data:          T[];
  rowKey:        (row: T) => string | number;
  isLoading?:    boolean;
  emptyTitle?:   string;
  emptyMessage?: string;
  emptyIcon?:    React.ReactNode;
  onRowClick?:   (row: T) => void;
  /** Kept for compatibility — headers are always sticky within a scrolling table */
  stickyHeader?: boolean;
  style?:        React.CSSProperties;

  /** Accessible table caption (visually hidden) */
  caption?:      string;
  sort?:         SortState | null;
  onSortChange?: (sort: SortState | null) => void;
  defaultSort?:  SortState;
  selectable?:   boolean;
  selectedKeys?: (string | number)[];
  onSelectionChange?: (keys: (string | number)[]) => void;
  bulkActions?:  (rows: T[], clear: () => void) => React.ReactNode;
  columnChooser?: boolean;
  densityToggle?: boolean;
  density?:      Density;
  viewKey?:      string;
  maxHeight?:    number | string;
  toolbar?:      React.ReactNode;
  /** Names a row for screen readers (checkbox label, card title fallback) */
  rowLabel?:     (row: T) => string;
  /** Cards on phones (default true) */
  responsive?:   boolean;
}

// ── Persisted view ────────────────────────────────────────────
interface SavedView { hidden: string[]; density: Density }
const VIEW_PREFIX = 'opsyn-table:';

function loadView(viewKey?: string): Partial<SavedView> {
  if (!viewKey) return {};
  try { return JSON.parse(localStorage.getItem(VIEW_PREFIX + viewKey) ?? '{}'); } catch { return {}; }
}
function saveView(viewKey: string | undefined, view: SavedView) {
  if (!viewKey) return;
  try { localStorage.setItem(VIEW_PREFIX + viewKey, JSON.stringify(view)); } catch { /* not persisted */ }
}

// ── Sorting ───────────────────────────────────────────────────
function compare(a: unknown, b: unknown): number {
  const empty = (v: unknown) => v === null || v === undefined || v === '';
  if (empty(a) && empty(b)) return 0;
  if (empty(a)) return 1;   // blanks last, whichever direction
  if (empty(b)) return -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' });
}

const cellText = (v: unknown) => (typeof v === 'string' || typeof v === 'number' ? String(v) : undefined);

// ══ DATA TABLE ════════════════════════════════════════════════
export function DataTable<T>({
  columns, data, rowKey, isLoading = false, emptyTitle = 'No results', emptyMessage, emptyIcon,
  onRowClick, style, caption,
  sort: controlledSort, onSortChange, defaultSort,
  selectable = false, selectedKeys, onSelectionChange, bulkActions,
  columnChooser = false, densityToggle = false, density: densityProp, viewKey,
  maxHeight, toolbar, rowLabel, responsive = true,
}: DataTableProps<T>) {
  const saved = useMemo(() => loadView(viewKey), [viewKey]);

  // Sort: controlled (server-side) or local
  const [localSort, setLocalSort] = useState<SortState | null>(defaultSort ?? null);
  const serverSorted = onSortChange !== undefined;
  const sort = serverSorted ? controlledSort ?? null : localSort;
  const setSort = (next: SortState | null) => (serverSorted ? onSortChange!(next) : setLocalSort(next));

  // Columns + density (persisted)
  const [hidden, setHidden] = useState<string[]>(
    () => saved.hidden ?? columns.filter(c => c.defaultHidden).map(c => c.key),
  );
  const [density, setDensity] = useState<Density>(densityProp ?? saved.density ?? 'comfortable');
  useEffect(() => { saveView(viewKey, { hidden, density }); }, [viewKey, hidden, density]);
  const visible = columns.filter(c => !hidden.includes(c.key));

  // Selection: controlled or local
  const [localSel, setLocalSel] = useState<(string | number)[]>([]);
  const selected = selectedKeys ?? localSel;
  const setSelected = (keys: (string | number)[]) => (onSelectionChange ? onSelectionChange(keys) : setLocalSel(keys));

  const rows = useMemo(() => {
    if (!sort || serverSorted) return data;
    const col = columns.find(c => c.key === sort.key);
    const get = (r: T) => (col?.sortValue ? col.sortValue(r) : (r as Record<string, unknown>)[sort.key]);
    const sorted = [...data].sort((a, b) => compare(get(a), get(b)));
    return sort.dir === 'desc' ? sorted.reverse() : sorted;
  }, [data, sort, serverSorted, columns]);

  const keys = rows.map(rowKey);
  const allSelected = keys.length > 0 && keys.every(k => selected.includes(k));
  const someSelected = !allSelected && keys.some(k => selected.includes(k));
  const selectedRows = rows.filter(r => selected.includes(rowKey(r)));

  const toggleSort = (col: Column<T>) => {
    if (!sort || sort.key !== col.key) setSort({ key: col.key, dir: 'asc' });
    else if (sort.dir === 'asc') setSort({ key: col.key, dir: 'desc' });
    else setSort(null);
  };

  const isPhone = !useMediaQuery(BREAKPOINTS.tablet);
  const asCards = responsive && isPhone;

  const align = (c: Column<T>) =>
    c.numeric || c.align === 'right' ? styles.right : c.align === 'center' ? styles.center : undefined;

  const openRow = onRowClick
    ? (row: T) => ({
        tabIndex: 0,
        onClick: () => onRowClick(row),
        onKeyDown: (e: React.KeyboardEvent) => {
          if (e.target === e.currentTarget && e.key === 'Enter') { e.preventDefault(); onRowClick(row); }
        },
      })
    : () => ({});

  const showToolbar = toolbar || columnChooser || densityToggle;

  // ── Toolbar ──
  const toolbarEl = showToolbar && (
    <div className={styles.toolbar}>
      <div className={styles.toolbarStart}>{toolbar}</div>
      {densityToggle && !asCards && (
        <button
          type="button"
          className={styles.toolbarBtn}
          aria-pressed={density === 'compact'}
          onClick={() => setDensity(d => (d === 'compact' ? 'comfortable' : 'compact'))}
        >
          <Rows3 size={14} aria-hidden="true" /> Compact rows
        </button>
      )}
      {columnChooser && !asCards && (
        <GlassPopover
          title="Columns"
          placement="bottom-end"
          renderTrigger={p => (
            <button {...p} type="button" className={styles.toolbarBtn}>
              <Columns3 size={14} aria-hidden="true" /> Columns
            </button>
          )}
        >
          <div className={styles.chooser}>
            {columns.map(c => {
              const shown = !hidden.includes(c.key);
              const last = shown && visible.length === 1;
              const canHide = c.hideable !== false && !last;
              return (
                <label key={c.key} className={styles.chooserRow} style={canHide || !shown ? undefined : { opacity: 0.55, cursor: 'not-allowed' }}>
                  <input
                    type="checkbox"
                    className={styles.check}
                    checked={shown}
                    disabled={shown && !canHide}
                    onChange={() => setHidden(h => (shown ? [...h, c.key] : h.filter(k => k !== c.key)))}
                  />
                  {c.header || c.key}
                </label>
              );
            })}
          </div>
        </GlassPopover>
      )}
    </div>
  );

  // ── Bulk bar ──
  const bulkBar = selectable && bulkActions && selectedRows.length > 0 && (
    <OverlayPortal>
      <GlassToolbar label="Bulk actions" className={styles.bulk}>
        <span className={styles.bulkCount} role="status">{selectedRows.length} selected</span>
        {bulkActions(selectedRows, () => setSelected([]))}
        <GlassButton shape="icon" aria-label="Clear selection" icon={<X size={16} />} onClick={() => setSelected([])} />
      </GlassToolbar>
    </OverlayPortal>
  );

  const empty = !isLoading && rows.length === 0 && (
    <EmptyState icon={emptyIcon} title={emptyTitle} message={emptyMessage} size="sm" />
  );

  // ── Phone: cards ──
  if (asCards) {
    const titleCol = visible.find(c => c.mobile === 'title') ?? visible[0];
    const fieldCols = visible.filter(c => c !== titleCol && c.mobile !== 'hidden');
    const render = (c: Column<T>, row: T, i: number) => {
      const raw = (row as Record<string, unknown>)[c.key];
      return c.render ? c.render(raw, row, i) : (raw as React.ReactNode) ?? '—';
    };
    return (
      <div className={styles.wrap} style={style}>
        {toolbarEl}
        {isLoading && <p className={styles.card} aria-busy="true"><span className={styles.skeleton} /></p>}
        {empty}
        {!isLoading && rows.length > 0 && (
          <ul className={styles.cards} aria-label={caption}>
            {rows.map((row, i) => {
              const key = rowKey(row);
              return (
                <li key={key} className={`${styles.card} ${onRowClick ? styles.clickable : ''}`} {...openRow(row)}>
                  <div className={styles.cardHead}>
                    {selectable && (
                      <input
                        type="checkbox"
                        className={styles.check}
                        aria-label={`Select ${rowLabel?.(row) ?? `row ${i + 1}`}`}
                        checked={selected.includes(key)}
                        onClick={e => e.stopPropagation()}
                        onChange={() => setSelected(selected.includes(key) ? selected.filter(k => k !== key) : [...selected, key])}
                      />
                    )}
                    <div className={styles.cardTitle}>{titleCol && render(titleCol, row, i)}</div>
                  </div>
                  {fieldCols.length > 0 && (
                    <dl className={styles.cardFields}>
                      {fieldCols.map(c => (
                        <React.Fragment key={c.key}>
                          <dt>{c.header}</dt>
                          <dd className={c.mono ? styles.mono : undefined}>{render(c, row, i)}</dd>
                        </React.Fragment>
                      ))}
                    </dl>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {bulkBar}
      </div>
    );
  }

  // ── Table ──
  return (
    <div className={styles.wrap} style={style}>
      {toolbarEl}
      <div className={styles.frame} style={maxHeight ? { maxHeight, overflowY: 'auto' } : undefined}>
        <table className={`${styles.table} ${density === 'compact' ? styles.compact : ''}`} aria-busy={isLoading || undefined}>
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead>
            <tr>
              {selectable && (
                <th className={`${styles.th} ${styles.checkCell}`} scope="col">
                  <input
                    type="checkbox"
                    className={styles.check}
                    aria-label="Select all rows"
                    checked={allSelected}
                    ref={el => { if (el) el.indeterminate = someSelected; }}
                    onChange={() => setSelected(allSelected ? selected.filter(k => !keys.includes(k)) : Array.from(new Set([...selected, ...keys])))}
                  />
                </th>
              )}
              {visible.map(col => {
                const dir = sort?.key === col.key ? sort.dir : null;
                return (
                  <th
                    key={col.key}
                    scope="col"
                    className={[styles.th, align(col)].filter(Boolean).join(' ')}
                    style={{ width: col.width }}
                    aria-sort={col.sortable ? (dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none') : undefined}
                  >
                    {col.sortable ? (
                      <button type="button" className={styles.sortBtn} onClick={() => toggleSort(col)}>
                        {col.header}
                        {dir === 'asc' ? <ArrowUp size={12} className={styles.sortIcon} aria-hidden="true" />
                          : dir === 'desc' ? <ArrowDown size={12} className={styles.sortIcon} aria-hidden="true" />
                          : <ArrowUpDown size={12} className={styles.sortIcon} aria-hidden="true" />}
                      </button>
                    ) : col.header}
                  </th>
                );
              })}
            </tr>
          </thead>

          <tbody>
            {isLoading && Array.from({ length: 5 }, (_, i) => (
              <tr key={`sk-${i}`} aria-hidden="true">
                {selectable && <td className={`${styles.td} ${styles.checkCell}`} />}
                {visible.map(c => (
                  <td key={c.key} className={styles.td}><span className={styles.skeleton} style={{ width: `${50 + ((i * 17 + c.key.length * 7) % 40)}%` }} /></td>
                ))}
              </tr>
            ))}

            {empty && (
              <tr><td colSpan={visible.length + (selectable ? 1 : 0)}>{empty}</td></tr>
            )}

            {!isLoading && rows.map((row, rowIdx) => {
              const key = rowKey(row);
              const isSel = selected.includes(key);
              return (
                <tr
                  key={key}
                  className={[styles.row, onRowClick && styles.clickable, isSel && styles.selected].filter(Boolean).join(' ')}
                  aria-selected={selectable ? isSel : undefined}
                  {...openRow(row)}
                >
                  {selectable && (
                    <td className={`${styles.td} ${styles.checkCell}`}>
                      <input
                        type="checkbox"
                        className={styles.check}
                        aria-label={`Select ${rowLabel?.(row) ?? `row ${rowIdx + 1}`}`}
                        checked={isSel}
                        onClick={e => e.stopPropagation()}
                        onChange={() => setSelected(isSel ? selected.filter(k => k !== key) : [...selected, key])}
                      />
                    </td>
                  )}
                  {visible.map(col => {
                    const raw = (row as Record<string, unknown>)[col.key];
                    return (
                      <td
                        key={col.key}
                        className={[styles.td, align(col), col.mono && styles.mono].filter(Boolean).join(' ')}
                        style={col.width ? { maxWidth: 'none' } : undefined}
                        title={col.render ? undefined : cellText(raw)}
                      >
                        {col.render ? col.render(raw, row, rowIdx) : ((raw as React.ReactNode) ?? '—')}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {bulkBar}
    </div>
  );
}
