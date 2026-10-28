// ============================================================
// OPSYN CHARTS — one chart system (ECharts, loaded lazily).
// ChartPanel frames every chart; option builders give one visual language;
// colours come from tokens (categorical = fiber-code palette; status colours
// only for series that ARE a severity).
// ============================================================

export { ChartPanel } from './ChartPanel';
export type { ChartPanelProps, ChartStatus, ChartTable } from './ChartPanel';
export { Sparkline } from './Sparkline';
export type { SparklineProps } from './Sparkline';
export { sparklinePath } from './sparklinePath';
export { useChartTheme, readChartTheme } from './chartTheme';
export type { ChartTheme } from './chartTheme';
export { lineOption, barOption, donutOption, DONUT_CENTER } from './options';
export type { SeriesSpec, Reference } from './options';
