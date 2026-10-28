// ============================================================
// OPSYN CHARTS — Sparkline
// A KPI's recent shape, as plain SVG (no chart library for a 96×28 line).
// Nulls break the line — a gap, not a dip to zero. Decorative: the KPI
// beside it states the value and the change in text.
// ============================================================

import { sparklinePath } from './sparklinePath';

export interface SparklineProps {
  values:  (number | null)[];
  width?:  number;
  height?: number;
  /** Stroke colour; defaults to currentColor so the parent decides */
  color?:  string;
  /** Smallest vertical range, in the data's units (see sparklinePath) */
  minSpan?: number;
}

export function Sparkline({ values, width = 96, height = 28, color = 'currentColor', minSpan = 0 }: SparklineProps) {
  const d = sparklinePath(values, width, height, 2, minSpan);
  if (!d) return null;
  const last = values[values.length - 1];
  const lastPoint = last !== null ? d.split(/[ML]/).filter(Boolean).pop()?.trim().split(' ') : null;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false" style={{ overflow: 'visible' }}>
      <path d={d} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      {lastPoint && <circle cx={lastPoint[0]} cy={lastPoint[1]} r={2.5} fill={color} />}
    </svg>
  );
}
