// ============================================================
// OPSYN — DeptInboxPage  (Phase 5 new file)
// Managers (role.level >= 3) see unassigned external tasks
// routed to their department and can assign them to staff.
// ============================================================

import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks.api';
import { useAuthStore } from '../../store/auth.store';
import { useUIStore } from '../../store/ui.store';
import { Button, Badge, Modal, Select } from '../../components/ui';
import type { ApiError } from '../../api/client';
import { PageHeader } from '../../components/layout/Page';

const toArr = (d: any): any[] => Array.isArray(d) ? d : (d?.items ?? []);

function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, message?: string) => addToast({ type: 'success', title, message }),
    error:   (title: string, message?: string) => addToast({ type: 'error',   title, message }),
  };
}

const PRIORITY_VARIANT: Record<string, any> = {
  critical: 'destructive',
  high:     'warning',
  medium:   'info',
  low:      'default',
};

function daysUntil(deadline: string | null): number | null {
  if (!deadline) return null;
  const d = new Date(deadline).getTime() - Date.now();
  return Math.ceil(d / 86400000);
}

function DeadlinePill({ deadline }: { deadline: string | null }) {
  if (!deadline) return null;
  const days = daysUntil(deadline);
  const overdue = days !== null && days < 0;
  const urgent  = days !== null && days >= 0 && days <= 1;
  const color = overdue ? 'var(--color-red)' : urgent ? 'var(--color-amber)' : 'var(--color-text-muted)';
  return (
    <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color, fontWeight: overdue || urgent ? 700 : 400 }}>
      {overdue ? `${Math.abs(days!)}d overdue` : days === 0 ? 'Due today' : `${days}d left`}
    </span>
  );
}

interface AssignModalState {
  taskId:    string;
  taskTitle: string;
}

export default function DeptInboxPage() {
  const toast    = useToast();
  const qc       = useQueryClient();
  const roleLevel = useAuthStore(s => s.roleLevel);

  const [assignModal, setAssignModal] = useState<AssignModalState | null>(null);
  const [assigneeId,  setAssigneeId]  = useState('');
  const [assignNote,  setAssignNote]  = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['dept-inbox'],
    queryFn:  tasksApi.getDeptInbox,
    refetchInterval: 60000,
  });

  const { data: staffData } = useQuery({
    queryKey: ['dept-staff'],
    queryFn:  () => tasksApi.getDeptStaff(undefined, 100),
  });

  const assign = useMutation({
    mutationFn: () => tasksApi.assign(assignModal!.taskId, assigneeId, assignNote || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dept-inbox'] });
      toast.success('Task assigned');
      setAssignModal(null);
      setAssigneeId('');
      setAssignNote('');
    },
    onError: (e: ApiError) => toast.error('Assignment failed', e?.response?.data?.detail ?? e?.message),
  });

  const tasks    = toArr(data?.items ?? data);
  const staffList = toArr(staffData);

  const stats = useMemo(() => {
    const total   = tasks.length;
    const overdue = tasks.filter((t: any) => daysUntil(t.deadline) !== null && daysUntil(t.deadline)! < 0).length;
    const oldest  = tasks.reduce((max: any, t: any) => {
      if (!t.created_at) return max;
      const d = new Date(t.created_at).getTime();
      return (!max || d < new Date(max.created_at).getTime()) ? t : max;
    }, null as any);
    const oldestAge = oldest
      ? Math.floor((Date.now() - new Date(oldest.created_at).getTime()) / 86400000)
      : 0;
    return { total, overdue, oldestAge };
  }, [tasks]);

  if (roleLevel < 3) {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        height: '100%', gap: 12, color: 'var(--color-text-muted)', fontSize: 13,
      }}>
        <div style={{ fontSize: 40 }}>🔒</div>
        <div style={{ fontWeight: 600 }}>Access Restricted</div>
        <div style={{ fontSize: 12 }}>The Department Inbox is visible to managers and above.</div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', background: 'var(--color-surface)' }}>

      {/* Header */}
      <div style={{
        padding: '14px 24px',
        borderBottom: '1px solid var(--color-border)',
        background: 'var(--surface)',
        flexShrink: 0,
      }}>
        <PageHeader
        title="Department Inbox"
        lede="Unassigned external tasks routed to your department"
        primary={<><StatChip label="Pending" value={stats.total} color="var(--color-teal)" /><StatChip label="Overdue" value={stats.overdue} color="var(--color-red)" /><StatChip label="Oldest (days)" value={stats.oldestAge} color="var(--color-amber)" /></>}
      />
      </div>

      {/* Task list */}
      <div style={{ overflow: 'auto', flex: 1, padding: '16px 24px' }}>
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 60, color: 'var(--color-text-muted)', fontSize: 12 }}>Loading…</div>
        ) : tasks.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 80, color: 'var(--color-text-muted)' }}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>📥</div>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>Inbox clear</div>
            <div style={{ fontSize: 12 }}>No unassigned tasks in your department.</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {tasks.map((t: any) => {
              const days = daysUntil(t.deadline);
              const isOverdue = days !== null && days < 0;
              return (
                <div
                  key={t.id}
                  style={{
                    background: 'var(--surface)',
                    border: '1px solid var(--color-border)',
                    borderLeft: `4px solid ${isOverdue ? 'var(--color-red)' : 'var(--color-teal)'}`,
                    borderRadius: 'var(--radius-card)',
                    padding: '14px 18px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 16,
                  }}
                >
                  {/* Main info */}
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

                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      {t.priority && (
                        <Badge variant={PRIORITY_VARIANT[t.priority] ?? 'default'} size="sm">
                          {t.priority}
                        </Badge>
                      )}
                      {t.created_by_name && (
                        <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                          From <strong>{t.created_by_name}</strong>
                        </span>
                      )}
                      <DeadlinePill deadline={t.deadline} />
                    </div>

                    {t.description && (
                      <div style={{
                        fontSize: 11, color: 'var(--color-text-muted)', marginTop: 6, lineHeight: 1.5,
                        overflow: 'hidden', display: '-webkit-box',
                        WebkitLineClamp: 1, WebkitBoxOrient: 'vertical' as any,
                      }}>
                        {t.description}
                      </div>
                    )}
                  </div>

                  {/* Action */}
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => {
                      setAssignModal({ taskId: t.id, taskTitle: t.title });
                      setAssigneeId('');
                      setAssignNote('');
                    }}
                  >
                    Assign to Staff
                  </Button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Assign modal */}
      {assignModal && (
        <Modal
          open
          onClose={() => setAssignModal(null)}
          title="Assign Task to Staff"
          footer={
            <>
              <Button variant="secondary" onClick={() => setAssignModal(null)}>Cancel</Button>
              <Button
                variant="primary"
                onClick={() => assign.mutate()}
                disabled={!assigneeId || assign.isPending}
                loading={assign.isPending}
              >
                Assign
              </Button>
            </>
          }
        >
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 14 }}>
            Assigning: <strong style={{ color: 'var(--color-text-primary)' }}>{assignModal.taskTitle}</strong>
          </div>
          <Select
            label="Select Staff Member *"
            value={assigneeId}
            onChange={setAssigneeId}
            options={[
              { label: 'Choose a staff member…', value: '' },
              ...staffList.map((s: any) => {
                const active  = s.active_task_count  ?? 0;
                const overdue = s.overdue_task_count ?? 0;
                const workload = overdue > 0
                  ? `${active} active, ${overdue} overdue ⚠`
                  : `${active} active`;
                return {
                  label: `${s.full_name} — ${workload}`,
                  value: s.user_id,
                };
              }),
            ]}
          />
          <div style={{ marginTop: 12 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text-secondary)', display: 'block', marginBottom: 4 }}>
              Assignment Note (optional)
            </label>
            <textarea
              value={assignNote}
              onChange={e => setAssignNote(e.target.value)}
              placeholder="Add context for the assignee…"
              rows={3}
              style={{
                width: '100%', boxSizing: 'border-box',
                border: '1px solid var(--color-border)', borderRadius: 6,
                padding: '8px 10px', fontSize: 12, resize: 'vertical',
                fontFamily: 'var(--font)', color: 'var(--color-text-primary)',
                background: 'var(--surface)', outline: 'none',
              }}
            />
          </div>
        </Modal>
      )}
    </div>
  );
}

function StatChip({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 20, fontWeight: 800, fontFamily: 'var(--font-mono)', color }}>{value}</div>
      <div style={{ fontSize: 10, color: 'var(--color-text-muted)', fontWeight: 500 }}>{label}</div>
    </div>
  );
}
