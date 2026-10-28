// ============================================================
// OPSYN — shell data: the live counts the shell shows everywhere
// (health bar, nav badges, notification bell). One set of queries, shared.
// ============================================================

import { useQuery } from '@tanstack/react-query';
import type { OutageIncident, OutageSeverity } from '@shared';
import { notificationsApi, onboardingApi, outageApi, reportsApi } from '../api/index';
import { SEVERITY_ORDER } from '../components/status/severity';
import type { BadgeKey } from './navigation';

/** An open outage within this many minutes of its SLA deadline is "at risk". */
export const SLA_RISK_WINDOW_MIN = 30;

export interface HealthSummary {
  bySeverity:  Record<OutageSeverity, number>;
  open:        number;
  slaAtRisk:   number;
  slaBreached: number;
}

export function summariseOutages(outages: OutageIncident[], now = Date.now()): HealthSummary {
  const bySeverity = Object.fromEntries(SEVERITY_ORDER.map(s => [s, 0])) as Record<OutageSeverity, number>;
  let slaAtRisk = 0;
  let slaBreached = 0;
  for (const o of outages) {
    if (o.status === 'resolved') continue;
    if (o.severity in bySeverity) bySeverity[o.severity]++;
    if (o.breached_sla) { slaBreached++; continue; }
    if (o.sla_deadline) {
      const minsLeft = (Date.parse(o.sla_deadline) - now) / 60_000;
      if (minsLeft <= SLA_RISK_WINDOW_MIN) slaAtRisk++;
    }
  }
  const open = SEVERITY_ORDER.reduce((n, s) => n + bySeverity[s], 0);
  return { bySeverity, open, slaAtRisk, slaBreached };
}

const toArr = <T,>(d: unknown): T[] =>
  Array.isArray(d) ? d as T[] : ((d as { items?: T[] } | undefined)?.items ?? []);

export function useShellData() {
  const outages = useQuery({
    queryKey:        ['outages', 'live'],
    queryFn:         () => outageApi.getLive(),
    refetchInterval: 30_000,
  });
  const intel = useQuery({
    queryKey:        ['intel-strip'],
    queryFn:         () => reportsApi.getIntelStrip(),
    refetchInterval: 30_000,
    staleTime:       25_000,
  });
  const unread = useQuery({
    queryKey:        ['notifications', 'unread-count'],
    queryFn:         () => notificationsApi.getUnreadCount(),
    refetchInterval: 30_000,
  });
  const onboarding = useQuery({
    queryKey:        ['onboarding', 'pending-count'],
    queryFn:         () => onboardingApi.list({ status: 'pending' }),
    refetchInterval: 60_000,
  });

  const health = summariseOutages(toArr<OutageIncident>(outages.data));
  const badges: Record<BadgeKey, number> = {
    openOutages:       health.open,
    overdueTasks:      intel.data?.tasks_overdue ?? 0,
    pendingOnboarding: toArr(onboarding.data).length,
  };

  return {
    health,
    badges,
    onCall:      intel.data?.staff_on_call ?? null,
    unreadCount: unread.data ?? 0,
    updatedAt:   outages.dataUpdatedAt || null,
    /** Live data stopped arriving — the bar says so instead of showing stale numbers silently */
    stale:       outages.isError,
    loading:     outages.isPending,
  };
}
