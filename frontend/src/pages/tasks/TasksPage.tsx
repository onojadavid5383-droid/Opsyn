// ============================================================
// OPSYN TASKS PAGE — src/pages/tasks/TasksPage.tsx
// Tab controller: Kanban · List · Gantt · Calendar
// ============================================================

import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks.api';
import { orgApi } from '../../api/index';
import { useTaskStore } from '../../store/task.store';
import type { TaskFilters as TaskFiltersState } from '../../store/task.store';
import { useUIStore } from '../../store/ui.store';
import type { Department, Task, TaskBoard, TaskStatusBoard } from '@shared';

import KanbanBoard      from './components/KanbanBoard';
import StatusKanbanBoard from './components/StatusKanbanBoard';
import ListView         from './components/ListView';
import GanttView        from './components/GanttView';
import CalendarView     from './components/CalendarView';
import TaskFilters      from './components/TaskFilters';
import NewTaskModal     from './components/NewTaskModal';
import TaskDetailModal  from './components/TaskDetailModal';
import QuickTaskPanel   from './components/QuickTaskPanel';
import type { ApiError } from '../../api/client';
import { GlassSelect } from '../../components/glass';

type ViewMode = 'kanban' | 'status_board' | 'list' | 'gantt' | 'calendar' | 'pending_approvals';

const TABS: { key: ViewMode; label: string }[] = [
  { key: 'kanban',             label: 'Deadline Board' },
  { key: 'status_board',       label: 'Status Board' },
  { key: 'list',               label: 'List' },
  { key: 'gantt',              label: 'Gantt' },
  { key: 'calendar',           label: 'Calendar' },
  { key: 'pending_approvals',  label: 'Pending Approvals' },
];

function applyFilters(board: TaskBoard | undefined, filters: TaskFiltersState): TaskBoard | undefined {
  if (!board) return undefined;
  if (!filters.search && !filters.priority && !filters.status && !filters.deadline_bucket) return board;

  function filterTasks(tasks: Task[]): Task[] {
    return tasks.filter(t => {
      if (filters.search) {
        const q = filters.search.toLowerCase();
        if (!t.title.toLowerCase().includes(q) && !(t.description ?? '').toLowerCase().includes(q)) return false;
      }
      if (filters.priority && t.priority !== filters.priority) return false;
      if (filters.status   && t.status   !== filters.status)   return false;
      if (filters.deadline_bucket && t.deadline_bucket !== filters.deadline_bucket) return false;
      return true;
    });
  }

  const filtered: TaskBoard = {
    pending_approval: filterTasks(board.pending_approval),
    completed:   filterTasks(board.completed),
    overdue:     filterTasks(board.overdue),
    today:       filterTasks(board.today),
    this_week:   filterTasks(board.this_week),
    next_week:   filterTasks(board.next_week),
    no_deadline: filterTasks(board.no_deadline),
    backlog:     filterTasks(board.backlog),
    total:       0,
  };
  filtered.total =
    filtered.pending_approval.length + filtered.completed.length + filtered.overdue.length + filtered.today.length + filtered.this_week.length +
    filtered.next_week.length + filtered.no_deadline.length + filtered.backlog.length;

  return filtered;
}

export default function TasksPage() {
  const [view,         setView]         = useState<ViewMode>('kanban');
  const [panelOpen,    setPanelOpen]    = useState(false);
  const [newTaskOpen,  setNewTaskOpen]  = useState(false);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);

  const { filters, setFilters, clearFilters } = useTaskStore();
  const { addToast } = useUIStore();
  const qc = useQueryClient();

  const { data: departments } = useQuery<Department[]>({
    queryKey:        ['departments'],
    queryFn:         () => orgApi.getDepartments(),
    staleTime:       5 * 60 * 1000,
  });

  const { data: rawBoard, isLoading } = useQuery({
    queryKey:        ['tasks', 'board', filters.dept_id],
    queryFn:         () => tasksApi.getBoard(filters.dept_id ? { dept_id: filters.dept_id } : undefined),
    staleTime:       60 * 1000,
    refetchInterval: 60 * 1000,
  });

  const { data: statusBoard, isLoading: statusBoardLoading } = useQuery<TaskStatusBoard>({
    queryKey:        ['tasks', 'status-board', filters.dept_id],
    queryFn:         () => tasksApi.getStatusBoard(filters.dept_id ? { dept_id: filters.dept_id } : undefined),
    staleTime:       60 * 1000,
    refetchInterval: 60 * 1000,
    enabled:         view === 'status_board',
  });

  // E.1.2: Pending Approvals view — tasks awaiting creator sign-off
  const { data: pendingApprovals, isLoading: pendingLoading } = useQuery<Task[]>({
    queryKey:  ['tasks', 'pending-approvals'],
    queryFn:   () => tasksApi.getPipelineBoard(undefined, undefined, 'pending_approvals') as any,
    staleTime: 30 * 1000,
    enabled:   view === 'pending_approvals',
  });

  const doApprove = useMutation({
    mutationFn: (taskId: string) => tasksApi.approveDone(taskId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks', 'pending-approvals'] });
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
      qc.invalidateQueries({ queryKey: ['tasks', 'status-board'] });
      addToast({ type: 'success', title: 'Task approved and completed.' });
    },
    onError: (err: ApiError) => addToast({ type: 'error', title: 'Approve failed', message: err?.response?.data?.detail }),
  });

  const doRejectDone = useMutation({
    mutationFn: (taskId: string) => tasksApi.rejectDone(taskId, 'Rejected from approvals view — please revise.'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks', 'pending-approvals'] });
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
      qc.invalidateQueries({ queryKey: ['tasks', 'status-board'] });
      addToast({ type: 'success', title: 'Task sent back to In Progress.' });
    },
    onError: (err: ApiError) => addToast({ type: 'error', title: 'Reject failed', message: err?.response?.data?.detail }),
  });

  const board = useMemo(
    () => applyFilters(rawBoard as TaskBoard | undefined, filters),
    [rawBoard, filters],
  );

  const totalCount = board?.total ?? 0;
  const overdueCount = board?.overdue?.length ?? 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
      <h1 className="sr-only">Tasks</h1>

      {/* ── Tab bar ─────────────────────────────────────────── */}
      <div style={{
        display:      'flex',
        borderBottom: '1px solid var(--color-border)',
        flexShrink:   0,
        padding:      '0 20px',
        background: 'var(--surface)',
        alignItems:   'center',
      }}>
        {TABS.map((tab, i) => {
          const active = view === tab.key;
          return (
            <div
              key={tab.key}
              onClick={() => setView(tab.key)}
              style={{
                padding:      '11px 14px',
                fontSize:     12,
                fontWeight:   active ? 700 : 400,
                color:        active ? 'var(--color-teal)' : 'var(--color-text-muted)',
                cursor:       'pointer',
                borderBottom: active ? '2px solid var(--color-teal)' : '2px solid transparent',
                marginBottom: -1,
                display:      'flex',
                alignItems:   'center',
                gap:          6,
                transition:   'color .15s',
              }}
            >
              {tab.label}
              {i === 0 && (
                <span style={{
                  fontSize:   9,
                  fontWeight: 700,
                  padding:    '1px 5px',
                  borderRadius: 4,
                  background: 'rgba(0,194,168,.12)',
                  color:      'var(--color-teal)',
                }}>
                  {totalCount}
                </span>
              )}
            </div>
          );
        })}

        {/* Actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginLeft: 'auto' }}>
          <div style={{ display: 'flex', flexDirection: 'column', minWidth: 190 }}>
            <label style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.1em', color: 'var(--color-text-muted)', marginBottom: 4 }}>Department</label>
            <GlassSelect value={String(filters.dept_id)} onChange={v => setFilters({ dept_id: v })} options={[...(departments ?? []).map((dept) => ({ value: String(dept.id), label: String(dept.name) }))]} placeholder={'All departments'} ariaLabel="Department" compact />
          </div>
          <button
            onClick={() => setPanelOpen(p => !p)}
            style={{
              display:      'inline-flex',
              alignItems:   'center',
              gap:          5,
              padding:      '5px 11px',
              borderRadius: 8,
              fontSize:     11,
              fontWeight:   600,
              cursor:       'pointer',
              fontFamily:   'var(--font)',
              background:   panelOpen ? 'rgba(0,194,168,.12)' : 'var(--color-surface-2)',
              color:        panelOpen ? 'var(--color-teal)' : 'var(--color-text-muted)',
              border:       panelOpen ? '1px solid rgba(0,194,168,.3)' : '1px solid var(--color-border)',
              transition:   'all .15s',
            }}
          >
            ☰ My List
          </button>
          <button
            onClick={() => setNewTaskOpen(true)}
            style={{
              display:      'inline-flex',
              alignItems:   'center',
              gap:          5,
              padding:      '5px 13px',
              borderRadius: 8,
              fontSize:     11,
              fontWeight:   700,
              cursor:       'pointer',
              fontFamily:   'var(--font)',
              background:   'var(--brand)',
              color:        'var(--color-navy)',
              border:       'none',
              boxShadow:    '0 0 16px rgba(0,194,168,.25)',
            }}
          >
            + New Task
          </button>
        </div>
      </div>

      {/* ── Filters ─────────────────────────────────────────── */}
      <TaskFilters
        filters={filters}
        departments={departments ?? []}
        onChange={setFilters}
        onClear={clearFilters}
        totalCount={totalCount}
      />

      {/* ── Overdue alert bar ───────────────────────────────── */}
      {overdueCount > 0 && (
        <div style={{
          padding:         '6px 20px',
          flexShrink:      0,
          background:      'rgba(220,38,38,.06)',
          borderBottom:    '1px solid rgba(220,38,38,.15)',
          display:         'flex',
          alignItems:      'center',
          gap:             8,
          fontSize:        11,
        }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--color-red)',
                         boxShadow: '0 0 6px rgba(220,38,38,.5)', display: 'block' }} />
          <span style={{ color: 'var(--color-red)', fontWeight: 600 }}>
            {overdueCount} overdue task{overdueCount > 1 ? 's' : ''} — action required
          </span>
          <span style={{ color: 'var(--color-text-muted)' }}>· {totalCount} total open</span>
        </div>
      )}

      {/* ── Main content + optional panel ───────────────────── */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* View area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {view === 'kanban' && (
            <KanbanBoard
              board={board}
              loading={isLoading}
              onSelect={setSelectedTask}
              onAdd={() => setNewTaskOpen(true)}
            />
          )}
          {view === 'status_board' && (
            <StatusKanbanBoard
              board={statusBoard}
              loading={statusBoardLoading}
              onSelect={setSelectedTask}
              onAdd={() => setNewTaskOpen(true)}
            />
          )}
          {view === 'list' && (
            <ListView
              board={board}
              loading={isLoading}
              onSelect={setSelectedTask}
            />
          )}
          {view === 'gantt' && (
            <GanttView
              board={board}
              loading={isLoading}
              onSelect={setSelectedTask}
            />
          )}
          {view === 'calendar' && (
            <CalendarView
              board={board}
              loading={isLoading}
              onSelect={setSelectedTask}
            />
          )}

          {/* E.1.2-E.1.3: Pending Approvals */}
          {view === 'pending_approvals' && (
            <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }} tabIndex={0} role="region" aria-label="Pending approvals">
              {pendingLoading ? (
                <div style={{ textAlign: 'center', padding: 60, color: 'var(--color-text-muted)', fontSize: 12 }}>
                  Loading…
                </div>
              ) : !pendingApprovals?.length ? (
                <div style={{ textAlign: 'center', padding: 80, color: 'var(--color-text-muted)' }}>
                  <div style={{ fontSize: 36, marginBottom: 12 }}>✓</div>
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>No tasks awaiting approval</div>
                  <div style={{ fontSize: 12 }}>Tasks marked done by their assignee will appear here for your sign-off.</div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {(pendingApprovals as any[]).map((t: any) => (
                    <div key={t.id} style={{
                      background: 'var(--surface)', border: '1px solid var(--color-border)',
                      borderLeft: '4px solid var(--color-teal)',
                      borderRadius: 10, padding: '14px 18px',
                      display: 'flex', alignItems: 'flex-start', gap: 16,
                    }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                          {t.ticket_number && (
                            <span style={{
                              fontSize: 9, fontFamily: 'monospace', fontWeight: 700,
                              color: 'var(--color-teal)', padding: '1px 5px',
                              background: 'rgba(0,194,168,.08)', border: '1px solid rgba(0,194,168,.2)',
                              borderRadius: 3,
                            }}>
                              {t.ticket_number}
                            </span>
                          )}
                          <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--color-text-primary)' }}>
                            {t.title}
                          </span>
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                          Assignee marked done — awaiting your approval
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                        <button
                          onClick={() => setSelectedTask(t)}
                          style={{
                            padding: '6px 12px', borderRadius: 8, fontSize: 11, fontWeight: 600,
                            cursor: 'pointer', border: '1px solid var(--color-border)',
                            background: 'var(--color-surface-2)', color: 'var(--color-text-primary)',
                          }}>
                          View
                        </button>
                        <button
                          onClick={() => doApprove.mutate(t.id)}
                          disabled={doApprove.isPending}
                          style={{
                            padding: '6px 14px', borderRadius: 8, fontSize: 11, fontWeight: 700,
                            cursor: doApprove.isPending ? 'not-allowed' : 'pointer',
                            border: 'none', background: 'var(--brand)', color: 'var(--brand-contrast)',
                          }}>
                          ✓ Approve
                        </button>
                        <button
                          onClick={() => doRejectDone.mutate(t.id)}
                          disabled={doRejectDone.isPending}
                          style={{
                            padding: '6px 12px', borderRadius: 8, fontSize: 11, fontWeight: 700,
                            cursor: doRejectDone.isPending ? 'not-allowed' : 'pointer',
                            border: '1px solid rgba(220,38,38,.3)',
                            background: 'rgba(220,38,38,.08)', color: 'var(--color-red)',
                          }}>
                          ✕ Send Back
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* My Tasks panel */}
        {panelOpen && (
          <QuickTaskPanel
            onSelect={t => { setSelectedTask(t); setPanelOpen(false); }}
            onClose={() => setPanelOpen(false)}
          />
        )}
      </div>

      {/* ── Modals ──────────────────────────────────────────── */}
      <NewTaskModal
        open={newTaskOpen}
        onClose={() => setNewTaskOpen(false)}
      />

      <TaskDetailModal
        task={selectedTask}
        onClose={() => setSelectedTask(null)}
      />
    </div>
  );
}
