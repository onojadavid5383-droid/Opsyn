// ============================================================
// OPSYN — AuditPage  (Stage 5 redesign)
// ============================================================

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { auditApi } from '../../api/index';
import { Button, DataTable, Pagination, type Column } from '../../components/ui';
import { GlassSelect } from '../../components/glass';
import { Page, PageHeader } from '../../components/layout/Page';

const AC: Record<string, string> = {
  'staff.created':        'var(--color-green)',
  'staff.status_changed': 'var(--color-amber)',
  'staff.deactivated':    'var(--color-red)',
  'role.changed':         'var(--color-indigo)',
  'onboarding.approved':  'var(--color-teal)',
  'onboarding.rejected':  'var(--color-red)',
  'auth.login':           'var(--color-text-muted)',
  'auth.logout':          'var(--color-text-muted)',
};

const AC_BG: Record<string, string> = {
  'staff.created':        'rgba(22,163,74,.1)',
  'staff.status_changed': 'rgba(245,158,11,.1)',
  'staff.deactivated':    'rgba(220,38,38,.1)',
  'role.changed':         'rgba(79,70,229,.1)',
  'onboarding.approved':  'rgba(0,194,168,.1)',
  'onboarding.rejected':  'rgba(220,38,38,.1)',
  'auth.login':           'rgba(100,116,139,.08)',
  'auth.logout':          'rgba(100,116,139,.08)',
};

const ACTION_OPTS = [
  'staff.created', 'staff.status_changed', 'role.changed',
  'onboarding.approved', 'onboarding.rejected', 'auth.login', 'auth.logout',
];

export default function AuditPage() {
  const [actionFilter, setActionFilter] = useState('');
  const [page, setPage]                 = useState(1);

  const { data, isLoading } = useQuery({
    queryKey: ['audit', actionFilter, page],
    queryFn:  () => auditApi.list({ action: actionFilter || undefined, page }),
  });

  const exportCSV = () =>
    auditApi.exportCSV()
      .then((blob: any) => {
        const url = URL.createObjectURL(blob);
        const a   = document.createElement('a');
        a.href = url; a.download = 'opsyn-audit.csv'; a.click();
        URL.revokeObjectURL(url);
      })
      .catch(() => {});

  const items      = (data as any)?.items ?? [];
  const total      = (data as any)?.total ?? 0;

  const columns: Column[] = [
    {
      key: 'created_at', header: 'Timestamp', width: 130,
      render: (_v: any, row: any) => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-text-muted)' }}>
          {new Date(row.created_at).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
        </span>
      ),
    },
    {
      key: 'actor_id', header: 'Actor', width: 110,
      render: (_v: any, row: any) => (
        <span style={{ fontSize: 12, color: 'var(--color-text-primary)', fontWeight: 500 }}>
          {row.actor_id ? row.actor_id.slice(0, 8) + '…' : 'System'}
        </span>
      ),
    },
    {
      key: 'action', header: 'Action', width: 180,
      render: (_v: any, row: any) => {
        const color = AC[row.action] ?? 'var(--color-text-muted)';
        const bg    = AC_BG[row.action] ?? 'rgba(100,116,139,.08)';
        return (
          <span style={{
            fontSize: 10, padding: '2px 7px', borderRadius: 4,
            background: bg, color, fontWeight: 600,
            fontFamily: 'var(--font-mono)',
          }}>
            {row.action}
          </span>
        );
      },
    },
    {
      key: 'target_type', header: 'Target',
      render: (_v: any, row: any) => (
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
          {row.target_type}{row.target_id ? ` · ${row.target_id.slice(0, 8)}…` : ''}
        </span>
      ),
    },
    {
      key: 'ip_address', header: 'IP Address', width: 120,
      render: (_v: any, row: any) => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-text-muted)' }}>
          {row.ip_address ?? '—'}
        </span>
      ),
    },
  ];

  return (
    <Page>

        {/* Header */}
        <PageHeader
        title="Audit Logs"
        lede={<>Immutable record · {total} total events</>}
        primary={<Button variant="secondary" size="sm" onClick={exportCSV}>Export CSV</Button>}
      />

        {/* Filter */}
        <div style={{ marginBottom: 16 }}>
          <GlassSelect value={String(actionFilter)} onChange={v => { setActionFilter(v); setPage(1); }} options={[...ACTION_OPTS.map((a) => ({ value: String(a), label: String(a) }))]} placeholder={'All Actions'} ariaLabel="Filter by action" compact />
        </div>

        <DataTable
          columns={columns}
          data={items}
          rowKey={(row: any) => row.id}
          isLoading={isLoading}
          emptyTitle="No audit events found"
          emptyMessage="Audit events will appear here as actions are performed."
        />

        <div style={{ marginTop: 12 }}>
          <Pagination page={page} pageSize={20} total={total} onPage={setPage} />
        </div>
      
    </Page>
  );
}
