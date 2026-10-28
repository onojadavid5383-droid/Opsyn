// ============================================================
// OPSYN CHARTS — ChartPanel
// The frame every chart sits in: title + period, loading / empty / error
// states that explain themselves, and a Chart/Table toggle — the table is
// the chart's accessible equivalent and its "show me the numbers" view.
//
//   <ChartPanel title="Outages opened" subtitle="Last 30 days, by severity"
//     status={q.isPending ? 'loading' : q.isError ? 'error' : !q.data?.has_data ? 'empty' : 'ready'}
//     onRetry={q.refetch}
//     table={{ columns, rows }}
//     option={theme => lineOption(theme, …)} />
// ============================================================

import { lazy, Suspense, useId, useMemo, useState, type ReactNode } from 'react';
import { useChartTheme, type ChartTheme } from './chartTheme';
import type { ChartOption } from './echarts';
import styles from './ChartPanel.module.css';

const ChartCanvas = lazy(() => import('./ChartCanvas'));

export type ChartStatus = 'loading' | 'error' | 'empty' | 'ready';

export interface ChartTable {
  columns: { key: string; label: string; numeric?: boolean }[];
  rows:    Record<string, ReactNode>[];
}

export interface ChartPanelProps {
  title:         string;
  /** Period and basis, e.g. "Last 30 days · daily" */
  subtitle?:     string;
  status:        ChartStatus;
  /** Builds the ECharts option from the current theme */
  option?:       (theme: ChartTheme) => ChartOption;
  /** Accessible data view (and the Table toggle) */
  table?:        ChartTable;
  height?:       number;
  emptyMessage?: string;
  errorMessage?: string;
  onRetry?:      () => void;
  actions?:      ReactNode;
  /** Content laid over the chart (e.g. a donut's centre total) */
  overlay?:      ReactNode;
  className?:    string;
}

export function ChartPanel({
  title, subtitle, status, option, table, height = 240,
  emptyMessage = 'No data for this period yet.', errorMessage = "This chart couldn't be loaded.",
  onRetry, actions, overlay, className,
}: ChartPanelProps) {
  const theme = useChartTheme();
  const [view, setView] = useState<'chart' | 'table'>('chart');
  const titleId = useId();
  const built = useMemo(() => (option && status === 'ready' ? option(theme) : null), [option, theme, status]);

  const canToggle = !!table && status === 'ready';

  return (
    <section className={[styles.panel, className].filter(Boolean).join(' ')} aria-labelledby={titleId}>
      <header className={styles.head}>
        <div className={styles.headings}>
          <h3 id={titleId} className={styles.title}>{title}</h3>
          {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
        </div>
        <div className={styles.actions}>
          {actions}
          {canToggle && (
            <div className={styles.toggle} role="group" aria-label={`${title}: view`}>
              <button type="button" className={styles.toggleBtn} aria-pressed={view === 'chart'} onClick={() => setView('chart')}>Chart</button>
              <button type="button" className={styles.toggleBtn} aria-pressed={view === 'table'} onClick={() => setView('table')}>Table</button>
            </div>
          )}
        </div>
      </header>

      <div className={styles.body}>
        {status === 'loading' && (
          <div style={{ height }} aria-busy="true" aria-label={`${title}: loading`}><div className={styles.skeleton} /></div>
        )}

        {status === 'error' && (
          <div className={styles.state} style={{ height }} role="alert">
            <p>{errorMessage}</p>
            {onRetry && <button type="button" className={styles.retry} onClick={onRetry}>Try again</button>}
          </div>
        )}

        {status === 'empty' && (
          <div className={styles.state} style={{ height }}><p>{emptyMessage}</p></div>
        )}

        {status === 'ready' && view === 'chart' && built && (
          // The drawing is decorative for assistive tech; the Table view is the data
          <div role="img" aria-label={`${title}${subtitle ? `, ${subtitle}` : ''}. Switch to Table to read the values.`} style={{ position: 'relative' }}>
            <Suspense fallback={<div style={{ height }}><div className={styles.skeleton} /></div>}>
              <ChartCanvas option={built} height={height} />
            </Suspense>
            {overlay}
          </div>
        )}

        {status === 'ready' && view === 'table' && table && (
          <div className={styles.tableWrap} style={{ maxHeight: height }}>
            <table className={styles.table}>
              <caption className="sr-only">{title}</caption>
              <thead>
                <tr>{table.columns.map(c => <th key={c.key} scope="col" className={c.numeric ? styles.num : undefined}>{c.label}</th>)}</tr>
              </thead>
              <tbody>
                {table.rows.map((r, i) => (
                  <tr key={i}>{table.columns.map(c => <td key={c.key} className={c.numeric ? styles.num : undefined}>{r[c.key] ?? '—'}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
