// ============================================================
// OPSYN — Command Center  (Phase 5 rebuild)
// Answers, in order of urgency:
//   what is broken, how badly, since when          → Open incidents
//   where                                          → Network map
//   the condition of the network and the work      → KPIs
//   what is changing                               → trend charts
//   what is outstanding, what just happened        → pipeline, activity
// The health bar (shell) carries the live severity counts above all of it.
// Every figure is real API data; missing data says so.
// ============================================================

import { useState } from 'react';
import { GlassSelect } from '../../components/glass';
import { OutageTrendChart, ProjectStageChart, SiteCapacityChart, TaskFlowChart, TaskStatusChart } from './DashboardCharts';
import { PERIODS, type Period } from './dashboardData';
import IncidentsPanel from './IncidentsPanel';
import KpiRow from './KpiRow';
import MapPanel from './MapPanel';
import { ActivityPanel, TaskPipelinePanel } from './OperationsPanels';
import s from './Dashboard.module.css';

export default function DashboardPage() {
  const [days, setDays] = useState<Period>(30);

  return (
    <div className={s.page}>
      <div className={s.inner}>
        <header className={s.header}>
          <div className={s.headings}>
            <h1 className={s.h1}>Command Center</h1>
            <p className={s.lede}>Live network state · incidents and counts refresh every 30 seconds</p>
          </div>
          <GlassSelect
            ariaLabel="Trend period"
            compact
            value={String(days)}
            onChange={v => setDays(Number(v) as Period)}
            options={PERIODS.map(p => ({ label: p.label, value: String(p.value) }))}
            style={{ width: 160 }}
          />
        </header>

        <IncidentsPanel />
        <MapPanel />

        <KpiRow days={days} />

        <OutageTrendChart days={days} className={s.wide} />
        <SiteCapacityChart className={s.narrow} />

        <TaskStatusChart className={s.narrow} />
        <TaskFlowChart days={days} className={s.wide} />

        <TaskPipelinePanel className={s.third} />
        <ProjectStageChart className={s.third} />
        <ActivityPanel className={s.third} />
      </div>
    </div>
  );
}
