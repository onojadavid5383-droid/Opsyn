// ============================================================
// OPSYN — Outage detail  /outage/:id
// What is broken, how badly, since when, and against which SLA — then the
// timeline, affected customers and linked task as URL tabs (?tab=).
// ============================================================

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, BellRing, CheckCircle2, Clock, Cog, GitCommitHorizontal, MessageSquare, Radio } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { OutageIncident } from '@shared';
import { outageApi } from '../../api/index';
import type { ApiError } from '../../api/client';
import { Page, PageHeader } from '../../components/layout/Page';
import { Button, Card, EmptyState, StateBadge, StatusBadge, Tabs } from '../../components/ui';
import { useToast } from '../../components/ui/Toast';
import { useUrlTab } from '../../hooks/useUrlTab';
import { SLA_RISK_WINDOW_MIN } from '../../layouts/useShellData';
import { formatDuration, minutesSince, slaStatus } from '../dashboard/dashboardData';
import s from './OutageDetail.module.css';

/** Fields the detail endpoint returns beyond the shared list type */
interface TimelineEvent { id: string; event_type: string; body: string; created_at?: string; meta?: { sla_event?: string } }
type OutageDetail = OutageIncident & { timeline?: TimelineEvent[]; affected_customer_ids?: string[] };

const TABS = ['timeline', 'customers', 'task'] as const;
type Tab = typeof TABS[number];

const EVENT_ICON: Record<string, typeof MessageSquare> = {
  comment: MessageSquare, state_change: GitCommitHorizontal, stage_event: Radio, system: Cog,
};

const fmt = (iso?: string | null) => (iso ? new Date(iso).toLocaleString('en-GB', {
  day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
}) : '—');

function useNow(intervalMs = 30_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

export default function OutageDetailPage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const toast = useToast();
  const now = useNow();
  const [tab, setTab] = useUrlTab<Tab>(TABS, 'timeline');
  const [notified, setNotified] = useState(false);

  const q = useQuery({ queryKey: ['outage', id], queryFn: () => outageApi.get(id!), enabled: !!id, refetchInterval: 30_000 });
  const inc = q.data as OutageDetail | undefined;

  const refresh = () => { qc.invalidateQueries({ queryKey: ['outage', id] }); qc.invalidateQueries({ queryKey: ['outages'] }); };
  const resolve = useMutation({
    mutationFn: () => outageApi.resolve(id!),
    onSuccess: () => { refresh(); toast.success('Outage resolved'); },
    onError: (e: ApiError) => toast.error("Couldn't resolve the outage", e?.detail),
  });
  const monitor = useMutation({
    mutationFn: () => outageApi.updateStatus(id!, 'monitoring'),
    onSuccess: () => { refresh(); toast.info('Set to monitoring'); },
    onError: (e: ApiError) => toast.error("Couldn't update the outage", e?.detail),
  });
  const notify = useMutation({
    mutationFn: () => outageApi.notifyCustomers(id!),
    onSuccess: () => { setNotified(true); toast.success('Customers notified'); },
    onError: (e: ApiError) => toast.error("Couldn't notify customers", e?.detail),
  });

  const back = <Link to="/outage" className={s.back}><ArrowLeft size={14} aria-hidden="true" /> Alarms & outages</Link>;

  if (q.isLoading) return <Page width="narrow">{back}<p className={s.muted} role="status">Loading incident…</p></Page>;
  if (q.isError || !inc) {
    return (
      <Page width="narrow">
        {back}
        <EmptyState title="Incident not found" message="It may have been removed, or you may not have access to it." />
      </Page>
    );
  }

  const resolved = inc.status === 'resolved';
  const sla = resolved ? null : slaStatus(inc, now, SLA_RISK_WINDOW_MIN);
  const openMin = minutesSince(inc.created_at, inc.resolved_at ? Date.parse(inc.resolved_at) : now);
  const slaPct = inc.sla_deadline
    ? Math.min(100, Math.max(0, ((now - Date.parse(inc.created_at)) / (Date.parse(inc.sla_deadline) - Date.parse(inc.created_at))) * 100))
    : 0;
  const slaTone = inc.breached_sla || sla?.tone === 'critical' ? 'critical' : sla?.tone === 'high' ? 'high' : 'ok';
  const customers = inc.affected_customer_ids ?? [];
  const timeline = [...(inc.timeline ?? [])].reverse();

  return (
    <Page width="narrow">
      {back}
      <PageHeader
        title={inc.title}
        lede={<span className={s.ids}><span className={s.mono}>{inc.reference}</span>{inc.olt_reference && <> · OLT <span className={s.mono}>{inc.olt_reference}</span></>}</span>}
        primary={!resolved ? (
          <Button variant="primary" size="sm" leftIcon={<CheckCircle2 size={16} aria-hidden="true" />} onClick={() => resolve.mutate()} loading={resolve.isPending}>
            Resolve
          </Button>
        ) : undefined}
        secondary={resolved ? [] : [
          ...(inc.status === 'active' ? [{ id: 'monitor', label: 'Set to monitoring', icon: <Clock size={16} aria-hidden="true" />, onSelect: () => monitor.mutate(), disabled: monitor.isPending }] : []),
          { id: 'notify', label: notified ? 'Customers notified' : 'Notify customers', icon: <BellRing size={16} aria-hidden="true" />, onSelect: () => notify.mutate(), disabled: notify.isPending || notified },
        ]}
      />

      <div className={s.badges}>
        <StatusBadge severity={inc.severity} size="md" />
        <StateBadge state={inc.status} size="md" />
        {inc.source && inc.source !== 'manual' && <span className={s.source}>via {inc.source}</span>}
      </div>

      <div className={s.summary}>
        <Card padding={0}>
          <dl className={s.facts}>
            <div><dt>{resolved ? 'Duration' : 'Open for'}</dt><dd>{formatDuration(openMin)}</dd></div>
            <div><dt>Subscribers affected</dt><dd>{inc.affected_subscribers ? inc.affected_subscribers.toLocaleString() : '—'}</dd></div>
            <div><dt>Logged</dt><dd>{fmt(inc.created_at)}</dd></div>
            {inc.resolved_at && <div><dt>Resolved</dt><dd>{fmt(inc.resolved_at)}</dd></div>}
          </dl>
        </Card>

        <Card padding={16}>
          <h2 className={s.h2}>SLA</h2>
          {!inc.sla_deadline ? (
            <p className={s.muted}>No SLA deadline is set for this incident.</p>
          ) : (
            <>
              <p className={s.slaLine} data-tone={slaTone}>
                {inc.breached_sla ? 'Breached' : resolved ? 'Met' : sla?.text}
              </p>
              <p className={s.muted}>Deadline {fmt(inc.sla_deadline)}</p>
              {!resolved && (
                <div className={s.meter} role="meter" aria-label="SLA time used" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(inc.breached_sla ? 100 : slaPct)}>
                  <div className={s.meterFill} data-tone={slaTone} style={{ width: `${inc.breached_sla ? 100 : slaPct}%` }} />
                </div>
              )}
            </>
          )}
        </Card>
      </div>

      {inc.description && <Card padding={16}><h2 className={s.h2}>Description</h2><p className={s.description}>{inc.description}</p></Card>}

      <Tabs
        label="Incident details"
        value={tab}
        onChange={setTab}
        idPrefix="outage-detail"
        items={[
          { value: 'timeline', label: 'Timeline', count: timeline.length },
          { value: 'customers', label: 'Affected customers', count: customers.length },
          { value: 'task', label: 'Linked task' },
        ]}
      />

      <div role="tabpanel" id="outage-detail-panel" aria-labelledby={`outage-detail-tab-${tab}`}>
        {tab === 'timeline' && (timeline.length === 0 ? (
          <EmptyState size="sm" title="No timeline events yet" />
        ) : (
          <ol className={s.timeline}>
            {timeline.map(e => {
              const Icon = EVENT_ICON[e.event_type] ?? MessageSquare;
              return (
                <li key={e.id} className={s.event}>
                  <span className={s.eventIcon} aria-hidden="true"><Icon size={14} /></span>
                  <div>
                    <p className={s.eventBody}>{e.body}</p>
                    <p className={s.eventMeta}>
                      {e.created_at && <time dateTime={e.created_at}>{fmt(e.created_at)}</time>}
                      {e.meta?.sla_event && <span className={s.slaEvent}>SLA {e.meta.sla_event}</span>}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        ))}

        {tab === 'customers' && (customers.length === 0 ? (
          <EmptyState size="sm" title="No customers recorded" message="No customer IDs are attached to this incident." />
        ) : (
          <Card padding={0}>
            <ol className={s.customers}>
              {customers.map(cid => <li key={cid} className={s.mono}>{cid}</li>)}
            </ol>
          </Card>
        ))}

        {tab === 'task' && (!inc.linked_task_id ? (
          <EmptyState size="sm" title="No linked task" message="No task has been created for this incident." />
        ) : (
          <Card padding={16}>
            <p className={s.muted}>Linked task</p>
            <p className={s.mono}>{inc.linked_task_id}</p>
            <Link to={`/tasks?highlight=${inc.linked_task_id}`} className={s.link}>Open the task</Link>
          </Card>
        ))}
      </div>
    </Page>
  );
}
