// ============================================================
// OPSYN — Open incidents: the Command Center's first answer.
// What is broken, how badly, since when, how many subscribers, and how it
// stands against its SLA. Most severe first, then longest-running.
// ============================================================

import { useQuery } from '@tanstack/react-query';
import { CircleCheck, TimerOff } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import type { OutageIncident } from '@shared';
import { outageApi } from '../../api/index';
import { DataTable, StatusBadge, type Column } from '../../components/ui';
import { formatDuration, minutesSince, slaStatus, sortIncidents, toArr } from './dashboardData';
import s from './Dashboard.module.css';

const SLA_CLASS = { critical: s.slaCritical, high: s.slaHigh, neutral: s.slaNeutral } as const;

// Reference + OLT ride under the summary: seven separate columns didn't fit
// beside the map, and SLA — the column that drives action — was the one cut.
const COLUMNS: Column<OutageIncident>[] = [
  { key: 'severity', header: 'Severity', width: 116, mobile: 'title', render: (_v, o) => <StatusBadge severity={o.severity} /> },
  {
    key: 'title', header: 'Incident',
    render: (_v, o) => (
      <span className={s.incident}>
        <span className={s.incidentTitle}>{o.title}</span>
        <span className={s.incidentMeta}>{o.reference}{o.olt_reference ? ` · ${o.olt_reference}` : ''}</span>
      </span>
    ),
  },
  {
    key: 'affected_subscribers', header: 'Subscribers', width: 104, numeric: true,
    render: v => (typeof v === 'number' ? v.toLocaleString() : '—'),
  },
  { key: 'created_at', header: 'Open for', width: 92, numeric: true, render: v => formatDuration(minutesSince(String(v))) },
  {
    key: 'sla_deadline', header: 'SLA', width: 136,
    render: (_v, o) => {
      const sla = slaStatus(o);
      if (!sla) return <span className={s.slaNeutral}>No SLA</span>;
      return (
        <span className={`${s.sla} ${SLA_CLASS[sla.tone]}`}>
          {sla.tone === 'critical' && <TimerOff size={14} aria-hidden="true" />}
          {sla.text}
        </span>
      );
    },
  },
];

export default function IncidentsPanel() {
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ['outages', 'live'], queryFn: () => outageApi.getLive(), refetchInterval: 30_000 });
  const incidents = sortIncidents(toArr<OutageIncident>(q.data));

  return (
    <section className={`${s.panel} ${s.incidents}`} aria-labelledby="cc-incidents">
      <header className={s.panelHead}>
        <h2 id="cc-incidents" className={s.panelTitle}>
          Open incidents
          <span className={s.panelSub}>
            {q.isPending ? 'Loading…' : `${incidents.length} open · most severe first, then longest-running`}
          </span>
        </h2>
        <Link to="/outage" className={s.link}>All outages</Link>
      </header>
      <div className={s.panelBody}>
        {!q.isPending && !q.isError && incidents.length === 0 ? (
          <p className={s.allClear}><CircleCheck size={18} aria-hidden="true" /> No open incidents. The network is clear.</p>
        ) : (
          <DataTable
            caption="Open incidents"
            columns={COLUMNS}
            data={incidents}
            rowKey={o => o.id}
            isLoading={q.isPending}
            onRowClick={o => navigate(`/outage/${o.id}`)}
            maxHeight={380}
            emptyTitle={q.isError ? "Incidents couldn't be loaded" : 'No open incidents'}
            emptyMessage={q.isError ? 'Live data is unavailable right now — the health bar shows when it resumes.' : undefined}
          />
        )}
      </div>
    </section>
  );
}
