// ============================================================
// OPSYN — ActivityPage  (Stage 6 redesign)
// ============================================================

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { activityApi } from '../../api/index';
import { Pagination } from '../../components/ui';
import { GlassSelect } from '../../components/glass';
import { PageHeader } from '../../components/layout/Page';

const ENTITY_COLORS: Record<string, string> = {
  task:        'var(--color-teal)',
  project:     'var(--color-indigo)',
  outage:      'var(--color-red)',
  staff:       'var(--color-green)',
  onboarding:  'var(--color-amber)',
  system:      'var(--color-text-muted)',
};

const ENTITY_BG: Record<string, string> = {
  task:        'rgba(0,194,168,.06)',
  project:     'rgba(79,70,229,.1)',
  outage:      'rgba(220,38,38,.1)',
  staff:       'rgba(22,163,74,.1)',
  onboarding:  'rgba(245,158,11,.1)',
  system:      'rgba(100,116,139,.08)',
};

const EVENT_ICONS: Record<string, string> = {
  comment:       '💬',
  status_change: '🔄',
  created:       '✨',
  approved:      '✅',
  rejected:      '❌',
  resolved:      '✅',
  assigned:      '👤',
  updated:       '✏️',
};

const ENTITY_OPTS = [
  { value: '',           label: 'All Entities' },
  { value: 'task',       label: 'Tasks' },
  { value: 'project',    label: 'Projects' },
  { value: 'outage',     label: 'Outages' },
  { value: 'staff',      label: 'Staff' },
  { value: 'onboarding', label: 'Onboarding' },
  { value: 'system',     label: 'System' },
];

export default function ActivityPage() {
  const [entityFilter, setEntityFilter] = useState('');
  const [page, setPage]                 = useState(1);

  const { data, isLoading } = useQuery({
    queryKey:        ['activity', entityFilter, page],
    queryFn:         () => activityApi.getGlobalFeed({ entity_type: entityFilter || undefined, page, size: 50 }),
    refetchInterval: 30000,
  });

  const items = (data as any)?.items ?? [];
  const total = (data as any)?.total ?? 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', background: 'var(--color-surface)' }}>

      {/* Live indicator header */}
      <PageHeader
        title="Activity Feed"
        meta={<><div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{
              width: 7, height: 7, borderRadius: '50%',
              background: 'var(--color-green)',
              boxShadow: '0 0 6px rgba(22,163,74,.5)',
              display: 'inline-block',
            }} />
            <span style={{ fontSize: 10, color: 'var(--color-green)', fontWeight: 600, letterSpacing: '.04em' }}>LIVE</span>
          </div></>}
        primary={<><span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{total} events</span><GlassSelect value={String(entityFilter)} onChange={v => { setEntityFilter(v); setPage(1); }} options={[...ENTITY_OPTS.map((o) => ({ value: String(o.value), label: String(o.label) }))]} ariaLabel="Filter by entity type" compact /></>}
      />

      {/* Timeline list */}
      <div style={{ overflow: 'auto', flex: 1, padding: '16px 24px' }}>
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--color-text-muted)', fontSize: 12 }}>Loading…</div>
        ) : items.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 60, color: 'var(--color-text-muted)', fontSize: 13 }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>📋</div>
            <div>No activity events found</div>
          </div>
        ) : (
          <div style={{ maxWidth: 720, margin: '0 auto' }}>
            {items.map((item: any, i: number) => {
              const ec    = ENTITY_COLORS[item.entity_type] ?? 'var(--color-text-muted)';
              const eb    = ENTITY_BG[item.entity_type]    ?? 'rgba(100,116,139,.08)';
              const icon  = EVENT_ICONS[item.event_type]   ?? '📌';
              const isLast = i === items.length - 1;

              return (
                <div key={item.id ?? i} style={{ display: 'flex', gap: 12, position: 'relative' }}>
                  {/* Connector line */}
                  {!isLast && (
                    <div style={{
                      position: 'absolute', left: 15, top: 32, bottom: -4,
                      width: 1, background: 'var(--color-border)',
                    }} />
                  )}

                  {/* Icon bubble */}
                  <div style={{
                    width: 32, height: 32,
                    borderRadius: '50%',
                    background: eb,
                    border: `1px solid ${ec}30`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 14, flexShrink: 0, zIndex: 1,
                    marginBottom: 4,
                  }}>
                    {icon}
                  </div>

                  {/* Content */}
                  <div style={{ flex: 1, paddingBottom: 16 }}>
                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                        {/* Entity badge */}
                        <span style={{
                          fontSize: 9, padding: '2px 6px', borderRadius: 4,
                          background: eb, color: ec, fontWeight: 700,
                          fontFamily: 'var(--font-mono)', letterSpacing: '.04em',
                          textTransform: 'uppercase',
                        }}>
                          {item.entity_type}
                        </span>
                        {/* Event type */}
                        <span style={{ fontSize: 11, color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
                          {item.event_type}
                        </span>
                      </div>
                      <span style={{ fontSize: 10, color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap', flexShrink: 0 }}>
                        {new Date(item.created_at ?? item.timestamp).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>

                    {/* Body */}
                    {item.body && (
                      <div style={{ fontSize: 12, color: 'var(--color-text-primary)', lineHeight: 1.5, marginBottom: 4 }}>
                        {item.body}
                      </div>
                    )}

                    {/* Meta row */}
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      {item.entity_id && (
                        <span style={{ fontSize: 10, color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
                          id:{item.entity_id.slice(0, 8)}
                        </span>
                      )}
                      {item.actor_id && (
                        <span style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>
                          by {item.actor_name ?? item.actor_id.slice(0, 8)}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div style={{ maxWidth: 720, margin: '0 auto', paddingTop: 8 }}>
          <Pagination page={page} pageSize={50} total={total} onPage={setPage} />
        </div>
      </div>
    </div>
  );
}
