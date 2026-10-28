// ============================================================
// OPSYN — Command Center charts
//   Outages opened            line   · by severity (series ARE severities)
//   Site capacity             h-bar  · most-utilised sites
//   Tasks by status           donut  · composition (colours = workflow states)
//   Tasks created vs done     line   · throughput
//   Projects by pipeline stage h-bar
// Every chart: real data only, an empty state that says what's missing, a
// 403 explained as a permission, and a Table view of the same numbers.
// ============================================================

import { useQuery } from '@tanstack/react-query';
import type { InfraUtilisationPoint, OutageSeverity, TaskStatus, TrendSeries } from '@shared';
import { infrastructureApi, reportsApi } from '../../api/index';
import { barOption, ChartPanel, donutOption, DONUT_CENTER, lineOption, type ChartTheme } from '../../components/charts';
import { SEVERITY_META, SEVERITY_ORDER } from '../../components/status/severity';
import { bucketFor, panelState, periodSubtitle, toArr, trendLabels, type Period } from './dashboardData';
import s from './Dashboard.module.css';

const trendQuery = (metric: TrendSeries['metric'], days: Period) => ({
  queryKey: ['trends', metric, days],
  queryFn:  () => reportsApi.getTrends({ metric, days, bucket: bucketFor(days) }),
  staleTime: 5 * 60_000,
});

const readable = (key: string) => key.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());

// ── Outages opened, by severity ───────────────────────────────

export function OutageTrendChart({ days, className }: { days: Period; className?: string }) {
  const q = useQuery(trendQuery('outages_opened', days));
  const t = q.data;
  const bucket = bucketFor(days);
  const state = panelState(q, !!t?.has_data, `No outages opened in the last ${days} days.`);
  const labels = t ? trendLabels(t.points, bucket) : [];
  const sevs = SEVERITY_ORDER.filter(sv => t?.breakdown?.[sv]?.some(n => n > 0));

  return (
    <ChartPanel
      className={className}
      title="Outages opened"
      subtitle={`${periodSubtitle(days, bucket)} · by severity`}
      status={state.status}
      emptyMessage={state.status === 'empty' ? state.message : undefined}
      onRetry={() => q.refetch()}
      // Stacked bars, not lines: daily counts are small whole numbers, and four
      // crossing lines of 0–3 are unreadable. The stack shows total and mix at once.
      option={(theme: ChartTheme) => barOption(theme, {
        categories: labels,
        stacked: true,
        integers: true,
        series: sevs.length
          ? sevs.map(sv => ({ name: SEVERITY_META[sv].label, data: t!.breakdown![sv], color: theme.status[sv as OutageSeverity] }))
          : [{ name: 'Outages', data: t?.points.map(p => p.value) ?? [] }],
      })}
      table={t ? {
        columns: [{ key: 'date', label: 'Period' }, ...sevs.map(sv => ({ key: sv, label: SEVERITY_META[sv].label, numeric: true })), { key: 'total', label: 'Total', numeric: true }],
        rows: t.points.map((p, i) => ({
          date: labels[i],
          ...Object.fromEntries(sevs.map(sv => [sv, t.breakdown![sv][i]])),
          total: p.value ?? 0,
        })),
      } : undefined}
    />
  );
}

// ── Site capacity ─────────────────────────────────────────────

export function SiteCapacityChart({ className }: { className?: string }) {
  const q = useQuery({ queryKey: ['infrastructure', 'utilisation'], queryFn: () => infrastructureApi.getUtilisation(), refetchInterval: 60_000 });
  const sites = toArr<InfraUtilisationPoint>(q.data)
    .filter(p => p.total > 0)
    .sort((a, b) => b.utilisation_pct - a.utilisation_pct)
    .slice(0, 10);
  const state = panelState(q, sites.length > 0, 'No port capacity recorded at any site yet.');

  return (
    <ChartPanel
      className={className}
      title="Site capacity"
      subtitle={`Port utilisation now · ${sites.length ? `top ${sites.length} sites` : 'by site'}`}
      status={state.status}
      emptyMessage={state.status === 'empty' ? state.message : undefined}
      onRetry={() => q.refetch()}
      height={Math.max(160, sites.length * 30 + 40)}
      option={theme => barOption(theme, {
        categories: sites.map(p => p.name),
        series: [{ name: 'Utilisation', data: sites.map(p => p.utilisation_pct) }],
        unit: '%',
        horizontal: true,
      })}
      table={{
        columns: [{ key: 'site', label: 'Site' }, { key: 'used', label: 'Ports used', numeric: true }, { key: 'total', label: 'Capacity', numeric: true }, { key: 'pct', label: 'Utilisation', numeric: true }],
        rows: sites.map(p => ({ site: p.name, used: p.used.toLocaleString(), total: p.total.toLocaleString(), pct: `${p.utilisation_pct}%` })),
      }}
    />
  );
}

// ── Tasks by status (donut) ───────────────────────────────────

const STATE_COLOR: Record<TaskStatus, keyof ChartTheme['state']> = {
  new: 'new', assigned: 'progress', in_progress: 'progress', review: 'review', blocked: 'blocked', done: 'done', archived: 'archived',
};

export function TaskStatusChart({ className }: { className?: string }) {
  const q = useQuery({ queryKey: ['reports', 'tasks-breakdown'], queryFn: () => reportsApi.getTasksBreakdown() });
  const d = q.data as { total: number; by_status: { status: string; count: number }[] } | undefined;
  const rows = (d?.by_status ?? []).filter(r => r.count > 0 && r.status !== 'archived');
  const open = rows.reduce((n, r) => n + r.count, 0);
  const state = panelState(q, rows.length > 0, 'No tasks yet.');

  return (
    <ChartPanel
      className={className}
      title="Tasks by status"
      subtitle="All current tasks, excluding archived"
      status={state.status}
      emptyMessage={state.status === 'empty' ? state.message : undefined}
      onRetry={() => q.refetch()}
      option={theme => donutOption(theme, {
        data: rows.map(r => ({
          name: readable(r.status === 'review' ? 'in_review' : r.status),
          value: r.count,
          color: theme.state[STATE_COLOR[r.status as TaskStatus] ?? 'new'],
        })),
      })}
      overlay={
        <div className={s.donutCenter} style={{ left: `${DONUT_CENTER.x}%`, top: `${DONUT_CENTER.y}%` }} aria-hidden="true">
          <div className={s.donutTotal}>{open.toLocaleString()}</div>
          <div className={s.donutLabel}>tasks</div>
        </div>
      }
      table={{
        columns: [{ key: 'status', label: 'Status' }, { key: 'count', label: 'Tasks', numeric: true }, { key: 'share', label: 'Share', numeric: true }],
        rows: rows.map(r => ({ status: readable(r.status), count: r.count, share: `${Math.round((r.count / (open || 1)) * 100)}%` })),
      }}
    />
  );
}

// ── Tasks created vs completed ────────────────────────────────

export function TaskFlowChart({ days, className }: { days: Period; className?: string }) {
  const created = useQuery(trendQuery('tasks_created', days));
  const done = useQuery(trendQuery('tasks_completed', days));
  const bucket = bucketFor(days);
  const hasData = !!(created.data?.has_data || done.data?.has_data);
  const state = panelState(
    { isPending: created.isPending || done.isPending, isError: created.isError || done.isError, error: created.error ?? done.error },
    hasData,
    `No tasks created or completed in the last ${days} days.`,
  );
  const labels = created.data ? trendLabels(created.data.points, bucket) : [];

  return (
    <ChartPanel
      className={className}
      title="Tasks created vs completed"
      subtitle={periodSubtitle(days, bucket)}
      status={state.status}
      emptyMessage={state.status === 'empty' ? state.message : undefined}
      onRetry={() => { created.refetch(); done.refetch(); }}
      option={theme => lineOption(theme, {
        categories: labels,
        integers: true,
        series: [
          { name: 'Created', data: created.data?.points.map(p => p.value) ?? [] },
          { name: 'Completed', data: done.data?.points.map(p => p.value) ?? [] },
        ],
      })}
      table={created.data && done.data ? {
        columns: [{ key: 'date', label: 'Period' }, { key: 'created', label: 'Created', numeric: true }, { key: 'done', label: 'Completed', numeric: true }],
        rows: created.data.points.map((p, i) => ({ date: labels[i], created: p.value ?? 0, done: done.data!.points[i]?.value ?? 0 })),
      } : undefined}
    />
  );
}

// ── Projects by pipeline stage ────────────────────────────────

export function ProjectStageChart({ className }: { className?: string }) {
  const q = useQuery({ queryKey: ['reports', 'projects-breakdown'], queryFn: () => reportsApi.getProjectsBreakdown() });
  const d = q.data as { total: number; by_pipeline_status: { status: string; count: number }[]; by_status: { status: string; count: number }[] } | undefined;
  const stages = (d?.by_pipeline_status ?? []).filter(r => r.count > 0).sort((a, b) => b.count - a.count);
  const active = d?.by_status.find(r => r.status === 'active')?.count;
  const state = panelState(q, stages.length > 0, 'No projects yet.');

  return (
    <ChartPanel
      className={className}
      title="Projects by pipeline stage"
      subtitle={d ? `${d.total} projects${active !== undefined ? ` · ${active} active` : ''}` : 'Current projects'}
      status={state.status}
      emptyMessage={state.status === 'empty' ? state.message : undefined}
      onRetry={() => q.refetch()}
      height={Math.max(160, stages.length * 30 + 40)}
      option={theme => barOption(theme, {
        categories: stages.map(r => readable(r.status)),
        series: [{ name: 'Projects', data: stages.map(r => r.count) }],
        horizontal: true,
        integers: true,
      })}
      table={{
        columns: [{ key: 'stage', label: 'Stage' }, { key: 'count', label: 'Projects', numeric: true }],
        rows: stages.map(r => ({ stage: readable(r.status), count: r.count })),
      }}
    />
  );
}
