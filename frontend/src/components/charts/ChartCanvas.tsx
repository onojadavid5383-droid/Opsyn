// ============================================================
// OPSYN CHARTS — ChartCanvas (lazy: the only module that loads ECharts)
// Owns one ECharts instance: init, resize with its box, re-render on
// option change, dispose on unmount. The canvas itself is presentational —
// ChartPanel supplies the accessible name and the table view.
// ============================================================

import { useEffect, useRef } from 'react';
import { echarts, type ChartOption } from './echarts';

export interface ChartCanvasProps {
  option: ChartOption;
  height: number;
}

export default function ChartCanvas({ option, height }: ChartCanvasProps) {
  const el = useRef<HTMLDivElement | null>(null);
  const chart = useRef<ReturnType<typeof echarts.init> | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const instance = echarts.init(el.current, undefined, { renderer: 'svg' });
    chart.current = instance;
    const ro = new ResizeObserver(() => instance.resize());
    ro.observe(el.current);
    return () => { ro.disconnect(); instance.dispose(); chart.current = null; };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={el} style={{ width: '100%', height }} aria-hidden="true" />;
}
