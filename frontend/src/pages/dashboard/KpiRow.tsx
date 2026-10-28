// ============================================================
// OPSYN — Command Center KPIs
// Every tile says what it measures and over which period. Sparklines and
// change figures appear only where the trend endpoint has real data; a
// missing value is "—" with the reason, never a stand-in number.
// ============================================================

import { useQuery } from '@tanstack/react-query';
import { format, subDays } from 'date-fns';
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { InfraUtilisationPoint, OutageIncident, TrendMetric } from '@shared';
import { dashboardApi, infrastructureApi, outageApi, reportsApi } from '../../api/index';
import { Sparkline } from '../../components/charts';
import { summariseOutages } from '../../layouts/useShellData';
import { bucketFor, seriesChange, toArr, type Period } from './dashboardData';
import s from './Dashboard.module.css';

interface Delta { text: string; direction: 'up' | 'down' | 'flat'; tone: 'good' | 'bad' | 'flat' }

export interface KpiCardProps {
  label:    string;
  value:    string | null;
  unit?:    string;
  context:  string;
  delta?:   Delta | null;
  spark?:   (number | null)[] | null;
  /** Sparkline's smallest vertical range, so small wobbles look small */
  sparkMinSpan?: number;
  to?:      string;
  loading?: boolean;
}

export function KpiCard({ label, value, unit, context, delta, spark, sparkMinSpan = 0, to, loading }: KpiCardProps) {
  const DeltaIcon = delta?.direction === 'up' ? ArrowUpRight : delta?.direction === 'down' ? ArrowDownRight : Minus;
  const body = (
    <>
      <span className={s.kpiLabel}>{label}</span>
      <span className={s.kpiRow}>
        <span className={s.kpiValue} aria-busy={loading || undefined}>
          {loading ? <span className={s.kpiMuted}>…</span>
            : value === null ? <span className={s.kpiMuted}>—</span>
            : <>{value}{unit && <span className={s.kpiUnit}>{unit}</span>}</>}
        </span>
        {spark && spark.some(v => v !== null) && (
          <span className={s.kpiSpark}><Sparkline values={spark} minSpan={sparkMinSpan} /></span>
        )}
      </span>
      <span className={s.kpiContext}>{context}</span>
      {delta && (
        <span className={`${s.delta} ${s[delta.tone]}`}>
          <DeltaIcon size={14} aria-hidden="true" />{delta.text}
        </span>
      )}
    </>
  );
  return to ? <Link to={to} className={s.kpi}>{body}</Link> : <div className={s.kpi}>{body}</div>;
}

function useTrend(metric: TrendMetric, days: Period) {
  return useQuery({
    queryKey: ['trends', metric, days],
    queryFn:  () => reportsApi.getTrends({ metric, days, bucket: bucketFor(days) }),
    staleTime: 5 * 60_000,
  });
}

const values = (t: { points: { value: number | null }[]; has_data: boolean } | undefined) =>
  t?.has_data ? t.points.map(p => p.value) : null;

/** Change over the period; `higherIsBetter` null = neutral (e.g. utilisation) */
function delta(series: (number | null)[] | null, unit: string, higherIsBetter: boolean | null, days: Period, decimals = 1): Delta | null {
  const c = series && seriesChange(series);
  if (!c) return null;
  const rounded = Number(c.diff.toFixed(decimals));
  if (rounded === 0) return { text: `No change over ${days} days`, direction: 'flat', tone: 'flat' };
  const up = rounded > 0;
  const tone = higherIsBetter === null ? 'flat' : up === higherIsBetter ? 'good' : 'bad';
  return { text: `${up ? '+' : ''}${rounded}${unit} over ${days} days`, direction: up ? 'up' : 'down', tone };
}

export default function KpiRow({ days }: { days: Period }) {
  const summary = useQuery({ queryKey: ['dashboard', 'summary'], queryFn: () => dashboardApi.getSummary(), refetchInterval: 30_000 });
  const outages = useQuery({ queryKey: ['outages', 'live'], queryFn: () => outageApi.getLive(), refetchInterval: 30_000 });
  const util = useQuery({ queryKey: ['infrastructure', 'utilisation'], queryFn: () => infrastructureApi.getUtilisation(), refetchInterval: 60_000 });
  const dateFrom = format(subDays(new Date(), days), 'yyyy-MM-dd');
  const mttr = useQuery({ queryKey: ['reports', 'mttr', days], queryFn: () => reportsApi.getOutageMttr({ date_from: dateFrom }) });

  const availTrend = useTrend('node_availability_pct', days);
  const mttrTrend = useTrend('mttr_hours', days);
  const utilTrend = useTrend('port_utilisation_pct', days);

  const k = summary.data as {
    tasks?: { open: number; overdue: number; today: number };
    infrastructure?: { total_nodes: number; active_nodes: number };
  } | undefined;

  // Node availability — active / total nodes, right now (not historical uptime)
  const nodes = k?.infrastructure;
  const availPct = nodes && nodes.total_nodes > 0 ? (nodes.active_nodes / nodes.total_nodes) * 100 : null;
  const availSeries = values(availTrend.data);

  // MTTR
  const mttrData = mttr.data as { overall_mttr_hours: number | null; total_resolved: number } | undefined;
  const mttrForbidden = (mttr.error as { status?: number } | null)?.status === 403;
  const mttrSeries = values(mttrTrend.data);

  // PON / port utilisation across all sites
  const points = toArr<InfraUtilisationPoint>(util.data);
  const used = points.reduce((n, p) => n + (p.used ?? 0), 0);
  const total = points.reduce((n, p) => n + (p.total ?? 0), 0);
  const utilPct = total > 0 ? (used / total) * 100 : null;
  const utilSeries = values(utilTrend.data);

  // SLA
  const health = summariseOutages(toArr<OutageIncident>(outages.data));

  return (
    <section className={s.kpis} aria-label="Key indicators">
      <KpiCard
        label="Node availability"
        loading={summary.isPending}
        value={availPct === null ? null : availPct.toFixed(1)}
        unit="%"
        context={nodes && nodes.total_nodes > 0 ? `${nodes.active_nodes} of ${nodes.total_nodes} nodes active now` : 'No nodes registered yet'}
        spark={availSeries}
        sparkMinSpan={5}
        delta={delta(availSeries, ' pts', true, days)}
        to="/infrastructure?tab=nodes"
      />
      <KpiCard
        label="Mean time to resolve"
        loading={mttr.isPending}
        value={mttrData?.overall_mttr_hours != null ? mttrData.overall_mttr_hours.toFixed(1) : null}
        unit="h"
        context={mttrForbidden ? 'Needs Reports access'
          : mttrData?.total_resolved ? `${mttrData.total_resolved} outages resolved · last ${days} days`
          : `No outages resolved in the last ${days} days`}
        spark={mttrSeries}
        sparkMinSpan={2}
        delta={delta(mttrSeries, 'h', false, days)}
        to="/reports"
      />
      <KpiCard
        label="Port utilisation"
        loading={util.isPending}
        value={utilPct === null ? null : utilPct.toFixed(0)}
        unit="%"
        context={total > 0 ? `${used.toLocaleString()} of ${total.toLocaleString()} ports in use` : 'No port capacity recorded yet'}
        spark={utilSeries}
        sparkMinSpan={5}
        delta={delta(utilSeries, ' pts', null, days)}
        to="/infrastructure"
      />
      <KpiCard
        label="SLA at risk"
        loading={outages.isPending}
        value={String(health.slaAtRisk)}
        context={`${health.slaBreached} breached · ${health.open} open incidents`}
        to="/outage"
      />
      <KpiCard
        label="Open tasks"
        loading={summary.isPending}
        value={k?.tasks ? String(k.tasks.open) : null}
        context={k?.tasks ? `${k.tasks.overdue} overdue · ${k.tasks.today} due today` : 'Task summary unavailable'}
        to="/tasks"
      />
    </section>
  );
}
