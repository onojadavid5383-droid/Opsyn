// ============================================================
// OPSYN UI — Pagination  (Phase 4)
// Same props and page-list logic. The current page is marked with the
// selection tint (teal is an action colour, not a state); page size uses a
// GlassSelect; wrapped in a labelled <nav>.
// ============================================================

import { ChevronLeft, ChevronRight } from 'lucide-react';
import type React from 'react';
import { GlassSelect } from '../glass';
import styles from './Pagination.module.css';

export interface PaginationProps {
  page:        number;
  pageSize:    number;
  total:       number;
  onPage:      (page: number) => void;
  onPageSize?: (size: number) => void;
  pageSizes?:  number[];
  style?:      React.CSSProperties;
}

export function Pagination({
  page, pageSize, total, onPage, onPageSize, pageSizes = [10, 20, 50, 100], style,
}: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to   = Math.min(page * pageSize, total);
  const pages = buildPageList(page, totalPages);

  return (
    <nav className={styles.bar} style={style} aria-label="Pagination">
      <span className={styles.count} aria-live="polite">
        {total === 0 ? 'No results' : `${from}–${to} of ${total.toLocaleString()}`}
      </span>

      {onPageSize && (
        <GlassSelect
          ariaLabel="Rows per page"
          compact
          value={String(pageSize)}
          onChange={v => { onPageSize(Number(v)); onPage(1); }}
          options={pageSizes.map(s => ({ label: `${s} per page`, value: String(s) }))}
          style={{ width: 132 }}
        />
      )}

      <div className={styles.pages}>
        <button type="button" className={styles.btn} disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
          <ChevronLeft size={16} aria-hidden="true" />
        </button>
        {pages.map((p, i) =>
          p === '...' ? (
            <span key={`gap-${i}`} className={styles.gap} aria-hidden="true">…</span>
          ) : (
            <button
              key={p}
              type="button"
              className={styles.btn}
              onClick={() => onPage(p)}
              aria-current={p === page ? 'page' : undefined}
              aria-label={`Page ${p}`}
            >
              {p}
            </button>
          ),
        )}
        <button type="button" className={styles.btn} disabled={page >= totalPages} onClick={() => onPage(page + 1)} aria-label="Next page">
          <ChevronRight size={16} aria-hidden="true" />
        </button>
      </div>
    </nav>
  );
}

function buildPageList(current: number, total: number): (number | '...')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages: (number | '...')[] = [1];
  if (current > 3)                        pages.push('...');
  if (current > 2)                        pages.push(current - 1);
  if (current !== 1 && current !== total) pages.push(current);
  if (current < total - 1)                pages.push(current + 1);
  if (current < total - 2)                pages.push('...');
  pages.push(total);
  return pages;
}
