// ============================================================
// OPSYN — Command Center data helpers (pure; unit-tested)
// Nothing here invents a number: missing data stays missing, and every
// helper says what it could not work out.
// ============================================================

import { format } from 'date-fns';
import type { OutageIncident, OutageSeverity, TrendBucket, TrendPoint } from '@shared';
import { SEVERITY_ORDER } from '../../components/status/severity';

// ── Durations ─────────────────────────────────────────────────

/** 45 → "45m", 135 → "2h 15m", 1500 → "1d 1h" */
export function formatDuration(totalMinutes: number): string {
  const m = Math.max(0, Math.round(totalMinutes));
  if (m < 60) return `${m}m`;
  if (m < 1440) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return `${Math.floor(m / 1440)}d ${Math.floor((m % 1440) / 60)}h`;
}

export function minutesSince(iso: string, now = Date.now()): number {
  return (now - Date.parse(iso)) / 60_000;
}

// ── Incidents ─────────────────────────────────────────────────

const RANK: Record<OutageSeverity, number> = Object.fromEntries(
  SEVERITY_ORDER.map((s, i) => [s, i]),
) as Record<OutageSeverity, number>;

/** Open incidents, most severe first; within a severity, the longest-running first. */
export function sortIncidents(outages: OutageIncident[]): OutageIncident[] {
  return outages
    .filter(o => o.status !== 'resolved')
    .sort((a, b) => (RANK[a.severity] ?? 9) - (RANK[b.severity] ?? 9) || a.created_at.localeCompare(b.created_at));
}

export type SlaTone = 'critical' | 'high' | 'neutral';

/** How an incident stands against its SLA, in words. */
export function slaStatus(o: OutageIncident, now = Date.now(), riskWindowMin = 30): { text: string; tone: SlaTone } | null {
  if (o.breached_sla) return { text: 'Breached', tone: 'critical' };
  if (!o.sla_deadline) return null;
  const left = (Date.parse(o.sla_deadline) - now) / 60_000;
  if (left < 0) return { text: `Overdue ${formatDuration(-left)}`, tone: 'critical' };
  return { text: `${formatDuration(left)} left`, tone: left <= riskWindowMin ? 'high' : 'neutral' };
}

// ── Trends ────────────────────────────────────────────────────

export type Period = 7 | 30 | 90;

export const PERIODS: { value: Period; label: string; bucket: TrendBucket }[] = [
  { value: 7,  label: 'Last 7 days',  bucket: 'day' },
  { value: 30, label: 'Last 30 days', bucket: 'day' },
  { value: 90, label: 'Last 90 days', bucket: 'week' },
];

export const bucketFor = (days: Period): TrendBucket => PERIODS.find(p => p.value === days)?.bucket ?? 'day';

export function periodSubtitle(days: Period, bucket: TrendBucket): string {
  return `Last ${days} days · ${bucket === 'week' ? 'weekly' : bucket === 'hour' ? 'hourly' : 'daily'}`;
}

/** Axis labels: "24 Sep" (days/weeks), "14:00" (hours) */
export function trendLabels(points: TrendPoint[], bucket: TrendBucket): string[] {
  return points.map(p => format(new Date(p.t), bucket === 'hour' ? 'HH:mm' : 'd MMM'));
}

/** First and last real values in a series — or null when there are fewer than two. */
export function seriesChange(values: (number | null)[]): { from: number; to: number; diff: number } | null {
  const real = values.filter((v): v is number => v !== null);
  if (real.length < 2) return null;
  const from = real[0];
  const to = real[real.length - 1];
  return { from, to, diff: to - from };
}

// ── Panel state from a query ──────────────────────────────────

export interface QueryLike {
  isPending: boolean;
  isError:   boolean;
  error?:    unknown;
}

export type PanelState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'empty'; message?: string }
  | { status: 'ready' };

/**
 * Loading → error → empty → ready. A 403 is not a failure to show as an
 * error: the person simply lacks the permission, so say that instead.
 */
export function panelState(q: QueryLike, hasData: boolean, emptyMessage?: string): PanelState {
  if (q.isPending) return { status: 'loading' };
  if (q.isError) {
    const status = (q.error as { status?: number } | undefined)?.status;
    if (status === 403) return { status: 'empty', message: 'You need Reports access to see this.' };
    return { status: 'error' };
  }
  if (!hasData) return { status: 'empty', message: emptyMessage };
  return { status: 'ready' };
}

// ── Map placement ─────────────────────────────────────────────

/**
 * Place open incidents on the map by matching their OLT reference to an
 * OLT's name (case-insensitive). Incidents that can't be matched are
 * counted, not guessed at.
 */
export function placeIncidents(incidents: OutageIncident[], olts: { id: string; name: string }[]) {
  const byName = new Map(olts.map(o => [o.name.trim().toLowerCase(), o.id]));
  const byOlt = new Map<string, OutageIncident[]>();
  let unplaced = 0;
  for (const inc of incidents) {
    const id = inc.olt_reference ? byName.get(inc.olt_reference.trim().toLowerCase()) : undefined;
    if (!id) { unplaced++; continue; }
    byOlt.set(id, [...(byOlt.get(id) ?? []), inc]);
  }
  return { byOlt, unplaced };
}

export const toArr = <T,>(d: unknown): T[] =>
  Array.isArray(d) ? (d as T[]) : ((d as { items?: T[] } | undefined)?.items ?? []);
