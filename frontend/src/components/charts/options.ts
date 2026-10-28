// ============================================================
// OPSYN CHARTS — option builders
// Line (trends), bar (comparisons), donut (composition). One visual system:
// quiet grid, muted axes, tabular numbers in tooltips, a dashed labelled
// line for targets/thresholds, no animation under reduced motion. Missing
// data (null) is a gap, never zero.
// ============================================================

import type { ChartOption } from './echarts';
import type { ChartTheme } from './chartTheme';

export interface SeriesSpec {
  name:   string;
  data:   (number | null)[];
  /** Explicit colour (e.g. a status token for a severity series) */
  color?: string;
}

export interface Reference {
  value: number;
  label: string;
}

const fmt = (unit?: string) => (v: unknown) =>
  v === null || v === undefined || v === '-' ? 'No data' : `${Number(v).toLocaleString()}${unit ? ` ${unit}` : ''}`;

function base(t: ChartTheme): ChartOption {
  return {
    animation: !t.reducedMotion,
    animationDuration: 400,
    color: t.categorical,
    textStyle: { fontFamily: t.fontFamily, color: t.text, fontSize: 12 },
    tooltip: {
      backgroundColor: t.menuSurface,
      borderColor: t.border,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: t.text, fontSize: 12, fontFamily: t.fontFamily },
      // Floating surface → the glass menu treatment
      extraCssText: 'backdrop-filter: blur(22px) saturate(140%); -webkit-backdrop-filter: blur(22px) saturate(140%); border-radius: 8px; box-shadow: 0 12px 32px rgba(11,21,32,.16); font-variant-numeric: tabular-nums;',
    },
    legend: {
      show: true, top: 0, right: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 10,
      textStyle: { color: t.textMuted, fontSize: 12 },
    },
  };
}

function valueAxis(t: ChartTheme, unit?: string, integers = false) {
  return {
    type: 'value' as const,
    // Counts are whole things: no "1.5 outages" gridlines
    ...(integers ? { minInterval: 1 } : {}),
    axisLabel: { color: t.axis, fontSize: 11, formatter: (v: number) => `${v.toLocaleString()}${unit === '%' ? '%' : ''}` },
    splitLine: { lineStyle: { color: t.grid } },
    axisLine: { show: false },
  };
}

function categoryAxis(t: ChartTheme, categories: string[]) {
  return {
    type: 'category' as const,
    data: categories,
    axisLabel: { color: t.axis, fontSize: 11, hideOverlap: true },
    axisLine: { lineStyle: { color: t.grid } },
    axisTick: { show: false },
  };
}

function markLine(t: ChartTheme, ref?: Reference) {
  if (!ref) return undefined;
  return {
    silent: true,
    symbol: 'none',
    lineStyle: { color: t.target, type: 'dashed' as const, width: 1 },
    label: { formatter: ref.label, color: t.text, fontSize: 11, position: 'insideEndTop' as const },
    data: [{ yAxis: ref.value }],
  };
}

export function lineOption(t: ChartTheme, opts: {
  categories: string[];
  series:     SeriesSpec[];
  unit?:      string;
  target?:    Reference;
  area?:      boolean;
  /** Values are counts — whole-number axis */
  integers?:  boolean;
}): ChartOption {
  return {
    ...base(t),
    legend: { ...(base(t).legend as object), show: opts.series.length > 1 },
    grid: { left: 8, right: 16, top: opts.series.length > 1 ? 32 : 16, bottom: 8, containLabel: true },
    tooltip: { ...(base(t).tooltip as object), trigger: 'axis', valueFormatter: fmt(opts.unit) },
    xAxis: { ...categoryAxis(t, opts.categories), boundaryGap: false },
    yAxis: valueAxis(t, opts.unit, opts.integers),
    series: opts.series.map((s, i) => ({
      type: 'line',
      name: s.name,
      data: s.data,
      connectNulls: false,          // a gap is a gap
      showSymbol: opts.categories.length <= 14,
      symbolSize: 5,
      lineStyle: { width: 2 },
      ...(s.color ? { itemStyle: { color: s.color }, lineStyle: { width: 2, color: s.color } } : {}),
      ...(opts.area && opts.series.length === 1 ? { areaStyle: { opacity: 0.08 } } : {}),
      ...(i === 0 ? { markLine: markLine(t, opts.target) } : {}),
    })),
  };
}

export function barOption(t: ChartTheme, opts: {
  categories:  string[];
  series:      SeriesSpec[];
  unit?:       string;
  /** Long labels (department names, OLTs): bars run left→right */
  horizontal?: boolean;
  stacked?:    boolean;
  threshold?:  Reference;
  /** Values are counts — whole-number axis */
  integers?:   boolean;
}): ChartOption {
  const cat = categoryAxis(t, opts.categories);
  const val = valueAxis(t, opts.unit, opts.integers);
  const ml = markLine(t, opts.threshold);
  return {
    ...base(t),
    legend: { ...(base(t).legend as object), show: opts.series.length > 1 },
    grid: { left: 8, right: 24, top: opts.series.length > 1 ? 32 : 12, bottom: 8, containLabel: true },
    tooltip: { ...(base(t).tooltip as object), trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: fmt(opts.unit) },
    xAxis: opts.horizontal ? val : cat,
    yAxis: opts.horizontal ? { ...cat, inverse: true } : val,
    series: opts.series.map((s, i) => ({
      type: 'bar',
      name: s.name,
      data: s.data,
      stack: opts.stacked ? 'total' : undefined,
      barMaxWidth: 28,
      itemStyle: { borderRadius: opts.stacked ? 0 : (opts.horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0]), ...(s.color ? { color: s.color } : {}) },
      ...(i === 0 && ml
        ? { markLine: opts.horizontal ? { ...ml, data: [{ xAxis: opts.threshold!.value }] } : ml }
        : {}),
    })),
  };
}

/** Where the donut's centre sits (%, of the chart box) — for an HTML overlay label */
export const DONUT_CENTER = { x: 32, y: 50 } as const;

export function donutOption(t: ChartTheme, opts: {
  data:  { name: string; value: number; color?: string }[];
  unit?: string;
}): ChartOption {
  // The centre total is HTML laid over DONUT_CENTER (real text: selectable,
  // announced, and actually centred — ECharts positions graphics by edge).
  return {
    ...base(t),
    legend: { ...(base(t).legend as object), show: true, orient: 'vertical', top: 'middle', right: 0 },
    tooltip: { ...(base(t).tooltip as object), trigger: 'item', valueFormatter: fmt(opts.unit) },
    series: [{
      type: 'pie',
      radius: ['58%', '80%'],
      center: [`${DONUT_CENTER.x}%`, `${DONUT_CENTER.y}%`],
      avoidLabelOverlap: true,
      label: { show: false },
      itemStyle: { borderColor: t.surface, borderWidth: 2 },
      data: opts.data.map(d => ({ name: d.name, value: d.value, ...(d.color ? { itemStyle: { color: d.color } } : {}) })),
    }],
  };
}
