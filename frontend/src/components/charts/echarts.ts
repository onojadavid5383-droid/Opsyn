// ============================================================
// OPSYN CHARTS — ECharts, modular.
// Only what the Command Center and reports use is registered, and this
// module is imported lazily (via ChartCanvas) — pages without charts never
// download it.
// ============================================================

import * as echarts from 'echarts/core';
import { BarChart, LineChart, PieChart } from 'echarts/charts';
import {
  DatasetComponent, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent,
} from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';

echarts.use([
  LineChart, BarChart, PieChart,
  GridComponent, TooltipComponent, LegendComponent, DatasetComponent, MarkLineComponent,
  SVGRenderer,
]);

export { echarts };
export type { EChartsCoreOption as ChartOption } from 'echarts/core';
