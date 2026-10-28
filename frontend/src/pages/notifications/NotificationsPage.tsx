// ============================================================
// OPSYN — NotificationsPage  (Phase 5 refactor)
// Category grouping, colored borders, clickable navigation.
// ============================================================

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { notificationsApi } from '../../api/index';
import { useUIStore } from '../../store/ui.store';
import { Button } from '../../components/ui';
import { PageHeader } from '../../components/layout/Page';

const toArr = (d: any): any[] => Array.isArray(d) ? d : (d?.items ?? []);

function useToast() {
  const { addToast } = useUIStore();
  return { success: (title: string) => addToast({ type: 'success', title }) };
}

// ── Category definitions ──────────────────────────────────────

const CATEGORIES: Array<{ key: string; label: string; color: string; types: string[] }> = [
  {
    key:   'task',
    label: 'Task Activity',
    color: 'var(--color-teal)',
    types: ['task_assigned', 'task_overdue', 'deadline_reminder', 'task_created', 'task_done',
            'task_started', 'task_blocked', 'task_unblocked', 'state_change', 'task_restored',
            'task_deleted', 'task_archived'],
  },
  {
    key:   'mention',
    label: 'Mentions',
    color: 'var(--color-indigo)',
    types: ['mention', 'archive_ref'],
  },
  {
    key:   'approval',
    label: 'Approvals',
    color: 'var(--color-green)',
    types: ['approval_needed', 'done_approved', 'done_rejected', 'task_completed',
            'onboarding_pending', 'onboarding_approved', 'onboarding_rejected'],
  },
  {
    key:   'transfer',
    label: 'Dept Transfers',
    color: 'var(--color-amber)',
    types: ['dept_transfer', 'task_forwarded', 'task_pushed_back', 'task_escalated',
            'task_returned', 'forward_dept', 'return_dept'],
  },
  {
    key:   'system',
    label: 'System',
    color: 'var(--color-text-muted)',
    types: [],   // catch-all
  },
];

function getCategoryForType(type: string) {
  for (const cat of CATEGORIES.slice(0, -1)) {
    if (cat.types.includes(type)) return cat;
  }
  return CATEGORIES[CATEGORIES.length - 1]; // system
}

const TYPE_ICONS: Record<string, string> = {
  task_assigned:       '✅',
  task_overdue:        '⏰',
  deadline_reminder:   '⏳',
  task_created:        '📝',
  task_done:           '✔️',
  task_started:        '▶️',
  task_blocked:        '🚫',
  task_unblocked:      '🔓',
  mention:             '💬',
  archive_ref:         '📎',
  approval_needed:     '⏳',
  done_approved:       '✅',
  done_rejected:       '❌',
  task_completed:      '🎉',
  onboarding_pending:  '📋',
  onboarding_approved: '✅',
  onboarding_rejected: '❌',
  dept_transfer:       '🔀',
  task_forwarded:      '➡️',
  task_pushed_back:    '⬅️',
  task_escalated:      '🔺',
  task_returned:       '↩️',
  outage_critical:     '🔴',
  outage_warning:      '⚠️',
  outage_resolved:     '✅',
  role_changed:        '⭐',
  staff_created:       '👤',
};

export default function NotificationsPage() {
  const toast    = useToast();
  const navigate = useNavigate();
  const qc       = useQueryClient();

  const [activeCategory, setActiveCategory] = useState<string>('all');

  const { data, isLoading } = useQuery({
    queryKey: ['notifications'],
    queryFn:  notificationsApi.list,
    refetchInterval: 30000,
  });

  const markRead = useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  });
  const markAll = useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['notifications'] }); toast.success('All marked as read'); },
  });
  const markCategoryRead = useMutation({
    mutationFn: async (catKey: string) => {
      const items = filtered.filter((n: any) => !n.is_read &&
        (catKey === 'all' ? true : getCategoryForType(n.type).key === catKey));
      await Promise.all(items.map((n: any) => notificationsApi.markRead(n.id)));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  });

  const notifs = toArr(data);
  const unread = notifs.filter((n: any) => !n.is_read).length;

  const filtered = activeCategory === 'all'
    ? notifs
    : notifs.filter((n: any) => getCategoryForType(n.type).key === activeCategory);

  const unreadInView = filtered.filter((n: any) => !n.is_read).length;

  function handleNotifClick(n: any) {
    if (!n.is_read) markRead.mutate(n.id);
    const url = n.action_url;
    if (url) {
      if (url.startsWith('/')) navigate(url);
      else window.open(url, '_blank', 'noopener');
    }
  }

  // Category badge counts
  const catCounts: Record<string, number> = { all: unread };
  for (const cat of CATEGORIES) {
    catCounts[cat.key] = notifs.filter((n: any) => !n.is_read && getCategoryForType(n.type).key === cat.key).length;
  }

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden', background: 'var(--color-surface)' }}>

      {/* Sidebar: category tabs */}
      <div style={{
        width: 180, flexShrink: 0,
        borderRight: '1px solid var(--color-border)',
        background: 'var(--surface)',
        display: 'flex', flexDirection: 'column',
        paddingTop: 16,
      }}>
        <div style={{ padding: '0 12px 10px', fontSize: 10, fontWeight: 700, color: 'var(--color-text-muted)', letterSpacing: '.08em' }}>
          CATEGORIES
        </div>
        {[{ key: 'all', label: 'All', color: 'var(--color-text-primary)' }, ...CATEGORIES].map(cat => {
          const active = activeCategory === cat.key;
          const count  = catCounts[cat.key] ?? 0;
          return (
            <button
              key={cat.key}
              onClick={() => setActiveCategory(cat.key)}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '8px 14px',
                background: active ? `${(cat as any).color ?? 'var(--color-teal)'}12` : 'transparent',
                border: 'none', cursor: 'pointer', textAlign: 'left',
                borderRight: active ? `3px solid ${(cat as any).color ?? 'var(--color-teal)'}` : '3px solid transparent',
                transition: 'background .1s',
              }}
            >
              <span style={{
                fontSize: 12, fontWeight: active ? 700 : 500,
                color: active ? ((cat as any).color ?? 'var(--color-teal)') : 'var(--color-text-secondary)',
              }}>
                {cat.label}
              </span>
              {count > 0 && (
                <span style={{
                  fontSize: 10, fontWeight: 700, minWidth: 18, height: 18,
                  background: (cat as any).color ?? 'var(--color-teal)',
                  color: 'white', borderRadius: 9,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  padding: '0 4px',
                }}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Main panel */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* Header bar */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '14px 24px',
          borderBottom: '1px solid var(--color-border)',
          flexShrink: 0, background: 'var(--surface)',
        }}>
          <PageHeader
            title="Notifications"
            meta={unread > 0 ? `${unread} unread` : undefined}
            primary={<>
            {unreadInView > 0 && activeCategory !== 'all' && (
              <Button
                variant="ghost" size="sm"
                onClick={() => markCategoryRead.mutate(activeCategory)}
                disabled={markCategoryRead.isPending}
              >
                Mark category read
              </Button>
            )}
            {unread > 0 && (
              <Button variant="secondary" size="sm" onClick={() => markAll.mutate()} disabled={markAll.isPending}>
                Mark All Read
              </Button>
            )}
            </>}
          />
        </div>

        {/* Notification list */}
        <div style={{ overflow: 'auto', flex: 1 }}>
          {isLoading ? (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--color-text-muted)', fontSize: 12 }}>Loading…</div>
          ) : filtered.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 60, color: 'var(--color-text-muted)', fontSize: 12 }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>🔔</div>
              <div>{activeCategory === 'all' ? 'No notifications yet' : 'No notifications in this category'}</div>
            </div>
          ) : filtered.map((n: any) => {
            const cat = getCategoryForType(n.type);
            const borderColor = n.is_read ? 'transparent' : cat.color;
            const hasLink = !!n.action_url;
            return (
              <div
                key={n.id}
                onClick={() => handleNotifClick(n)}
                style={{
                  display:    'flex',
                  gap:        12,
                  alignItems: 'flex-start',
                  padding:    '14px 24px',
                  borderBottom: '1px solid var(--color-border)',
                  cursor:     hasLink || !n.is_read ? 'pointer' : 'default',
                  background: !n.is_read ? `${cat.color}08` : 'var(--surface)',
                  borderLeft: `4px solid ${borderColor}`,
                  transition: 'background .15s',
                }}
                onMouseEnter={e => {
                  if (hasLink || !n.is_read)
                    (e.currentTarget as HTMLDivElement).style.background = `${cat.color}12`;
                }}
                onMouseLeave={e => {
                  (e.currentTarget as HTMLDivElement).style.background = !n.is_read ? `${cat.color}08` : 'var(--surface)';
                }}
              >
                {/* Unread dot */}
                <div style={{ width: 7, flexShrink: 0, marginTop: 6 }}>
                  {!n.is_read && (
                    <div style={{
                      width: 7, height: 7, borderRadius: '50%',
                      background: cat.color,
                      boxShadow: `0 0 8px ${cat.color}80`,
                    }} />
                  )}
                </div>

                {/* Icon */}
                <div style={{
                  width: 34, height: 34, borderRadius: 9,
                  background: `${cat.color}15`,
                  border: `1px solid ${cat.color}30`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 16, flexShrink: 0,
                }}>
                  {TYPE_ICONS[n.type] ?? '📬'}
                </div>

                {/* Content */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-primary)' }}>
                      {n.title}
                    </span>
                    <span style={{
                      fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3,
                      background: `${cat.color}18`, color: cat.color, letterSpacing: '.04em',
                    }}>
                      {cat.label}
                    </span>
                  </div>
                  {n.body && (
                    <div style={{
                      fontSize: 12, color: 'var(--color-text-muted)', marginTop: 2,
                      fontStyle: n.type === 'task_mentioned' ? 'italic' : 'normal',
                    }}>{n.body}</div>
                  )}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
                    <span style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>
                      {new Date(n.created_at).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                    </span>
                    {hasLink && (
                      <span style={{ fontSize: 10, color: cat.color, fontWeight: 600 }}>View →</span>
                    )}
                  </div>
                </div>

                {/* Mark read */}
                {!n.is_read && (
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={(e: any) => { e.stopPropagation(); markRead.mutate(n.id); }}
                  >
                    Read
                  </Button>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
