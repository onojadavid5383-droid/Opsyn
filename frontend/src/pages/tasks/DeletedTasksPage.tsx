// ============================================================
// OPSYN — DeletedTasksPage  (Corrective Plan B.2)
// Admin view: lists soft-deleted tasks with restore + purge.
// Route: /tasks/deleted — visible to admin users (roleLevel >= 4)
// ============================================================

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks.api';
import { useUIStore } from '../../store/ui.store';
import { usePermissions } from '../../hooks/usePermissions';
import type { ApiError } from '../../api/client';
import { GlassModal } from '../../components/glass';
import { PageHeader } from '../../components/layout/Page';
import { Badge } from '../../components/ui';

function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string) => addToast({ type: 'success', title }),
    error:   (title: string, message?: string) => addToast({ type: 'error', title, message }),
  };
}

function formatDate(iso: string | null | undefined) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

interface PurgeConfirmState {
  taskId:    string;
  taskTitle: string;
}

export default function DeletedTasksPage() {
  const toast  = useToast();
  const qc     = useQueryClient();
  const perms  = usePermissions();

  const [purgeTarget, setPurgeTarget] = useState<PurgeConfirmState | null>(null);
  const [page,        setPage]        = useState(1);

  const { data, isLoading } = useQuery({
    queryKey: ['tasks', 'deleted', page],
    queryFn:  () => tasksApi.listDeleted({ page, size: 20 }),
    staleTime: 30 * 1000,
  });

  const tasks   = (data as any)?.items ?? [];
  const total   = (data as any)?.total ?? 0;
  const pages   = Math.ceil(total / 20);

  const restore = useMutation({
    mutationFn: (taskId: string) => tasksApi.restore(taskId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks', 'deleted'] });
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
      toast.success('Task restored successfully.');
    },
    onError: (err: ApiError) => toast.error('Restore failed', err?.response?.data?.detail ?? err?.message),
  });

  const purge = useMutation({
    mutationFn: (taskId: string) => tasksApi.purge(taskId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks', 'deleted'] });
      setPurgeTarget(null);
      toast.success('Task permanently purged.');
    },
    onError: (err: ApiError) => {
      setPurgeTarget(null);
      toast.error('Purge failed', err?.response?.data?.detail ?? err?.message);
    },
  });

  if (!perms.isManager) {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', height: '100%', gap: 12,
        color: 'var(--color-text-muted)', fontSize: 13,
      }}>
        <div style={{ fontSize: 40 }}>🔒</div>
        <div style={{ fontWeight: 600 }}>Access Restricted</div>
        <div style={{ fontSize: 12 }}>The Deleted Tasks view is visible to admins only.</div>
      </div>
    );
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', flex: 1,
      overflow: 'hidden', background: 'var(--color-surface)',
    }}>
      {/* Header */}
      <div style={{
        padding: '14px 24px', borderBottom: '1px solid var(--color-border)',
        background: 'var(--surface)', flexShrink: 0,
      }}>
        <PageHeader
          title="Deleted tasks"
          lede="Soft-deleted tasks. Admins can restore or permanently purge."
          meta={<Badge tone="critical" size="sm">{total} deleted</Badge>}
        />
      </div>

      {/* Task list */}
      <div style={{ overflow: 'auto', flex: 1, padding: '16px 24px' }}>
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 60, color: 'var(--color-text-muted)', fontSize: 12 }}>
            Loading…
          </div>
        ) : tasks.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 80, color: 'var(--color-text-muted)' }}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>🗑️</div>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>No deleted tasks</div>
            <div style={{ fontSize: 12 }}>Soft-deleted tasks will appear here.</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {tasks.map((t: any) => (
              <div
                key={t.id}
                style={{
                  background: 'var(--surface)',
                  border: '1px solid var(--color-border)',
                  borderLeft: '4px solid var(--color-red)',
                  borderRadius: 'var(--radius-card)',
                  padding: '14px 18px',
                  display: 'flex', alignItems: 'flex-start', gap: 16,
                  opacity: 0.85,
                }}
              >
                {/* Task info */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    {t.ticket_number && (
                      <span style={{
                        fontSize: 9, fontFamily: 'var(--font-mono)',
                        color: 'var(--color-text-muted)', background: 'var(--color-surface-2)',
                        padding: '1px 5px', borderRadius: 3,
                      }}>
                        {t.ticket_number}
                      </span>
                    )}
                    <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--color-text-primary)' }}>
                      {t.title}
                    </span>
                  </div>

                  <div style={{
                    display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
                    gap: '4px 16px', marginTop: 6,
                  }}>
                    <MetaRow label="Deleted at"  value={formatDate(t.deleted_at)} />
                    <MetaRow label="Deleted by"  value={t.deleted_by_name ?? t.deleted_by ?? '—'} />
                    <MetaRow
                      label="Reason"
                      value={t.deletion_reason ?? '—'}
                      danger
                    />
                  </div>
                </div>

                {/* Actions */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flexShrink: 0 }}>
                  <button
                    onClick={() => restore.mutate(t.id)}
                    disabled={restore.isPending}
                    style={{
                      padding: '6px 14px', borderRadius: 8, fontSize: 11, fontWeight: 700,
                      cursor: restore.isPending ? 'not-allowed' : 'pointer',
                      border: '1px solid rgba(22,163,74,.3)',
                      background: 'rgba(22,163,74,.08)', color: 'var(--color-green)',
                      fontFamily: 'var(--font)',
                    }}
                  >
                    {restore.isPending ? '…' : '↩ Restore'}
                  </button>

                  {perms.isAdmin && (
                    <button
                      onClick={() => setPurgeTarget({ taskId: t.id, taskTitle: t.title })}
                      disabled={purge.isPending}
                      style={{
                        padding: '6px 14px', borderRadius: 8, fontSize: 11, fontWeight: 700,
                        cursor: purge.isPending ? 'not-allowed' : 'pointer',
                        border: '1px solid rgba(220,38,38,.3)',
                        background: 'rgba(220,38,38,.08)', color: 'var(--color-red)',
                        fontFamily: 'var(--font)',
                      }}
                    >
                      ☠ Purge
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Pagination */}
        {pages > 1 && (
          <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 20 }}>
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page <= 1}
              style={{
                padding: '5px 12px', borderRadius: 8, fontSize: 11, fontWeight: 600,
                cursor: page <= 1 ? 'not-allowed' : 'pointer',
                border: '1px solid var(--color-border)',
                background: 'var(--surface)', color: 'var(--color-text-primary)',
                opacity: page <= 1 ? 0.4 : 1,
              }}
            >
              ← Prev
            </button>
            <span style={{ fontSize: 11, color: 'var(--color-text-muted)', alignSelf: 'center' }}>
              Page {page} of {pages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(pages, p + 1))}
              disabled={page >= pages}
              style={{
                padding: '5px 12px', borderRadius: 8, fontSize: 11, fontWeight: 600,
                cursor: page >= pages ? 'not-allowed' : 'pointer',
                border: '1px solid var(--color-border)',
                background: 'var(--surface)', color: 'var(--color-text-primary)',
                opacity: page >= pages ? 0.4 : 1,
              }}
            >
              Next →
            </button>
          </div>
        )}
      </div>

      {/* Purge confirmation dialog */}
      {purgeTarget && (
        <GlassModal open onClose={() => { if (!purge.isPending) setPurgeTarget(null); }} ariaLabel="Permanently delete task" size="sm">
            <div style={{ fontSize: 28, marginBottom: 12, textAlign: 'center' }}>☠</div>
            <div style={{
              fontSize: 15, fontWeight: 800, textAlign: 'center',
              color: 'var(--color-red)', marginBottom: 8,
            }}>
              Permanently Purge Task?
            </div>
            <div style={{
              fontSize: 12, color: 'var(--color-text-muted)', textAlign: 'center',
              marginBottom: 12, lineHeight: 1.5,
            }}>
              <strong>{purgeTarget.taskTitle}</strong>
              <br />
              This action is <strong>irreversible</strong>. All data will be permanently deleted.
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
              <button
                onClick={() => setPurgeTarget(null)}
                disabled={purge.isPending}
                style={{
                  padding: '8px 18px', borderRadius: 8, fontSize: 12, fontWeight: 600,
                  cursor: 'pointer', border: '1px solid var(--color-border)',
                  background: 'var(--color-surface-2)', color: 'var(--color-text-primary)',
                }}
              >
                Cancel
              </button>
              <button
                onClick={() => purge.mutate(purgeTarget.taskId)}
                disabled={purge.isPending}
                style={{
                  padding: '8px 18px', borderRadius: 8, fontSize: 12, fontWeight: 700,
                  cursor: purge.isPending ? 'not-allowed' : 'pointer', border: 'none',
                  background: 'rgba(220,38,38,.85)', color: 'white',
                }}
              >
                {purge.isPending ? 'Purging…' : 'Yes, Purge Permanently'}
              </button>
            </div>
          </GlassModal>
      )}
    </div>
  );
}

function MetaRow({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div>
      <div style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '.08em' }}>
        {label}
      </div>
      <div style={{
        fontSize: 11, color: danger ? 'var(--color-red)' : 'var(--color-text-primary)',
        marginTop: 1, lineHeight: 1.4,
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {value}
      </div>
    </div>
  );
}
