// ============================================================
// OPSYN — Alarms & outages
// Incident command list. Views and the severity filter live in the URL
// (?view=sla&severity=critical), so the health bar and the command palette
// can open exactly the slice they describe.
//   Open      every unresolved incident, most severe then longest-running
//   SLA risk  breached, overdue, or within 30 min of the SLA deadline
//   Resolved  closed incidents
// Severity is a shape + label badge; lifecycle state is a separate dot badge.
// ============================================================

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { OutageIncident, OutageSeverity } from '@shared';
import { outageApi } from '../../api/index';
import type { ApiError } from '../../api/client';
import { Page, PageHeader, PageStats } from '../../components/layout/Page';
import { SEVERITY_META, SEVERITY_ORDER } from '../../components/status/severity';
import {
  Button, DataTable, Input, Modal, Select, StateBadge, StatusBadge, Tabs, Textarea, type Column,
} from '../../components/ui';
import { GlassSelect } from '../../components/glass';
import { useToast } from '../../components/ui/Toast';
import { useUrlParam } from '../../hooks/useUrlTab';
import { SLA_RISK_WINDOW_MIN } from '../../layouts/useShellData';
import { formatDuration, minutesSince, slaStatus, sortIncidents, toArr } from '../dashboard/dashboardData';
import s from './Outage.module.css';

const VIEWS = ['open', 'sla', 'resolved'] as const;
type View = typeof VIEWS[number];
const SEVERITY_FILTERS = ['all', ...SEVERITY_ORDER] as const;
type SeverityFilter = typeof SEVERITY_FILTERS[number];

const RANK: Record<OutageSeverity, number> = { critical: 0, high: 1, warning: 2, low: 3 };

const SEVERITY_OPTIONS = SEVERITY_ORDER.map(sv => ({ label: SEVERITY_META[sv].label, value: sv }));
const EMPTY_FORM = { title: '', severity: 'warning', description: '', olt_reference: '' };

/** Breached, overdue, or inside the risk window */
function atSlaRisk(o: OutageIncident, now: number): boolean {
  if (o.status === 'resolved') return false;
  if (o.breached_sla) return true;
  if (!o.sla_deadline) return false;
  return (Date.parse(o.sla_deadline) - now) / 60_000 <= SLA_RISK_WINDOW_MIN;
}

/** Re-render every 30 s so ages and SLA countdowns stay current */
function useNow(intervalMs = 30_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

export default function OutagePage() {
  const navigate = useNavigate();
  const toast = useToast();
  const qc = useQueryClient();
  const now = useNow();
  const [view, setView] = useUrlParam<View>('view', VIEWS, 'open');
  const [severity, setSeverity] = useUrlParam<SeverityFilter>('severity', SEVERITY_FILTERS, 'all');
  const [logOpen, setLogOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);

  // Same key as the shell and Command Center: one request feeds all three
  const live = useQuery({ queryKey: ['outages', 'live'], queryFn: () => outageApi.getLive(), refetchInterval: 30_000 });
  const resolvedQ = useQuery({
    queryKey: ['outages', 'list', 'resolved'],
    queryFn: () => outageApi.list({ status: 'resolved' }),
    enabled: view === 'resolved',
  });

  const open = useMemo(() => sortIncidents(toArr<OutageIncident>(live.data)), [live.data]);
  const resolved = useMemo(
    () => toArr<OutageIncident>((resolvedQ.data as { items?: OutageIncident[] } | undefined)?.items ?? resolvedQ.data)
      .sort((a, b) => (b.resolved_at ?? b.created_at).localeCompare(a.resolved_at ?? a.created_at)),
    [resolvedQ.data],
  );
  const slaRisk = useMemo(() => open.filter(o => atSlaRisk(o, now)), [open, now]);

  const source = view === 'open' ? open : view === 'sla' ? slaRisk : resolved;
  const rows = severity === 'all' ? source : source.filter(o => o.severity === severity);
  const loading = view === 'resolved' ? resolvedQ.isLoading : live.isLoading;
  const failed = view === 'resolved' ? resolvedQ.isError : live.isError;

  const invalidate = () => qc.invalidateQueries({ queryKey: ['outages'] });

  const log = useMutation({
    mutationFn: () => outageApi.log(form as Partial<OutageIncident>),
    onSuccess: () => { invalidate(); setLogOpen(false); setForm(EMPTY_FORM); toast.success('Outage logged'); },
    onError: (e: ApiError) => toast.error("Couldn't log the outage", e?.detail),
  });
  const resolve = useMutation({
    mutationFn: (id: string) => outageApi.resolve(id),
    onSuccess: () => { invalidate(); toast.success('Outage resolved'); },
    onError: (e: ApiError) => toast.error("Couldn't resolve the outage", e?.detail),
  });
  const monitor = useMutation({
    mutationFn: (id: string) => outageApi.updateStatus(id, 'monitoring'),
    onSuccess: () => { invalidate(); toast.info('Set to monitoring'); },
    onError: (e: ApiError) => toast.error("Couldn't update the outage", e?.detail),
  });

  const set = (k: keyof typeof EMPTY_FORM, v: string) => setForm(f => ({ ...f, [k]: v }));

  const columns = useMemo<Column<OutageIncident>[]>(() => [
    {
      key: 'severity', header: 'Severity', width: 120, sortable: true, hideable: false,
      sortValue: o => RANK[o.severity] ?? 9,
      render: (_v, o) => <StatusBadge severity={o.severity} />,
    },
    {
      key: 'title', header: 'Incident', sortable: true, mobile: 'title', hideable: false,
      render: (_v, o) => (
        <span className={s.incident}>
          <span className={s.title}>{o.title}</span>
          <span className={s.ref}>{o.reference}{o.olt_reference ? ` · ${o.olt_reference}` : ''}</span>
        </span>
      ),
    },
    { key: 'status', header: 'Status', width: 140, sortable: true, render: (_v, o) => <StateBadge state={o.status} /> },
    {
      key: 'affected_subscribers', header: 'Subscribers', numeric: true, sortable: true, width: 110,
      render: (_v, o) => (o.affected_subscribers ? o.affected_subscribers.toLocaleString() : '—'),
    },
    {
      key: 'created_at', header: view === 'resolved' ? 'Duration' : 'Open for', numeric: true, sortable: true, width: 110,
      sortValue: o => Date.parse(o.created_at) * -1,
      render: (_v, o) => {
        const end = o.resolved_at ? Date.parse(o.resolved_at) : now;
        return <span title={new Date(o.created_at).toLocaleString()}>{formatDuration(minutesSince(o.created_at, end))}</span>;
      },
    },
    {
      key: 'sla_deadline', header: 'SLA', width: 140, sortable: true,
      sortValue: o => (o.breached_sla ? -Infinity : o.sla_deadline ? Date.parse(o.sla_deadline) : Infinity),
      render: (_v, o) => {
        if (o.status === 'resolved') return o.breached_sla ? <span className={s.slaCritical}>Breached</span> : <span className={s.muted}>Met</span>;
        const sla = slaStatus(o, now, SLA_RISK_WINDOW_MIN);
        if (!sla) return <span className={s.muted}>No SLA</span>;
        return <span className={sla.tone === 'critical' ? s.slaCritical : sla.tone === 'high' ? s.slaHigh : undefined}>{sla.text}</span>;
      },
    },
    {
      key: 'actions', header: 'Actions', width: 180, hideable: false, mobile: 'field',
      render: (_v, o) => o.status === 'resolved' ? null : (
        <span className={s.actions} onClick={e => e.stopPropagation()}>
          {o.status === 'active' && (
            <Button variant="secondary" size="xs" onClick={() => monitor.mutate(o.id)} disabled={monitor.isPending}>Monitor</Button>
          )}
          <Button variant="primary" size="xs" onClick={() => resolve.mutate(o.id)} disabled={resolve.isPending}>Resolve</Button>
        </span>
      ),
    },
  ], [view, now, monitor, resolve]);

  const bySeverity = useMemo(() => {
    const m = Object.fromEntries(SEVERITY_ORDER.map(sv => [sv, 0])) as Record<OutageSeverity, number>;
    for (const o of open) m[o.severity] += 1;
    return m;
  }, [open]);
  const subscribersOut = open.reduce((n, o) => n + (o.affected_subscribers ?? 0), 0);

  return (
    <Page>
      <PageHeader
        title="Alarms & outages"
        lede="Network incidents — most severe first, then longest-running · refreshes every 30 seconds"
        primary={<Button variant="danger-solid" size="sm" leftIcon={<Plus size={16} aria-hidden="true" />} onClick={() => setLogOpen(true)}>Log outage</Button>}
      />

      <PageStats
        items={[
          { label: 'open', value: live.isLoading ? '–' : open.length, tone: bySeverity.critical ? 'critical' : undefined },
          ...SEVERITY_ORDER.filter(sv => bySeverity[sv] > 0).map(sv => ({
            label: SEVERITY_META[sv].label.toLowerCase(), value: bySeverity[sv],
            tone: sv === 'critical' ? 'critical' as const : sv === 'high' || sv === 'warning' ? 'warning' as const : undefined,
          })),
          { label: 'SLA at risk or breached', value: live.isLoading ? '–' : slaRisk.length, tone: slaRisk.length ? 'warning' : undefined },
          { label: 'subscribers affected', value: live.isLoading ? '–' : subscribersOut.toLocaleString() },
        ]}
      />

      <Tabs
        label="Outage views"
        value={view}
        onChange={setView}
        idPrefix="outage-view"
        items={[
          { value: 'open', label: 'Open', count: live.isLoading ? undefined : open.length },
          { value: 'sla', label: 'SLA at risk', count: live.isLoading ? undefined : slaRisk.length, tone: 'critical' },
          { value: 'resolved', label: 'Resolved' },
        ]}
      />
      <div role="tabpanel" id="outage-view-panel" aria-labelledby={`outage-view-tab-${view}`}>
        <DataTable
          caption="Outages"
          columns={columns}
          data={rows}
          rowKey={o => o.id}
          rowLabel={o => `${SEVERITY_META[o.severity].label} outage ${o.reference}: ${o.title}`}
          isLoading={loading}
          onRowClick={o => navigate(`/outage/${o.id}`)}
          viewKey="outages"
          toolbar={
            <GlassSelect
              ariaLabel="Filter by severity"
              compact
              value={severity}
              onChange={v => setSeverity(v as SeverityFilter)}
              options={[{ label: 'All severities', value: 'all' }, ...SEVERITY_OPTIONS]}
              style={{ width: 170 }}
            />
          }
          columnChooser
          emptyTitle={failed ? "Outages couldn't load" : view === 'sla' ? 'No SLA at risk' : view === 'resolved' ? 'No resolved outages' : 'No open outages'}
          emptyMessage={
            failed ? 'Check your connection and try again.'
              : severity !== 'all' ? `Nothing ${SEVERITY_META[severity].label.toLowerCase()} in this view.`
              : view === 'open' ? 'All monitored network elements are up.' : undefined
          }
        />
      </div>

      <Modal
        open={logOpen}
        onClose={() => setLogOpen(false)}
        title="Log outage"
        footer={
          <>
            <Button variant="secondary" onClick={() => setLogOpen(false)}>Cancel</Button>
            <Button variant="danger-solid" onClick={() => log.mutate()} disabled={!form.title.trim()} loading={log.isPending}>
              Log outage
            </Button>
          </>
        }
      >
        <Input label="Title" required value={form.title} onChange={v => set('title', v)} placeholder="e.g. Lagos Island · OLT-024 fibre cut" />
        <Select label="Severity" value={form.severity} onChange={v => set('severity', v)} options={SEVERITY_OPTIONS} />
        <Input label="OLT reference" value={form.olt_reference} onChange={v => set('olt_reference', v)} placeholder="e.g. OLT-024"
          hint="Matching an OLT name places the incident on the network map." />
        <Textarea label="Description" value={form.description} onChange={v => set('description', v)} placeholder="What is affected, and what is known so far" rows={3} />
      </Modal>
    </Page>
  );
}
