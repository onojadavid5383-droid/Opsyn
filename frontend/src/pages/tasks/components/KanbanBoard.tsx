// ============================================================
// OPSYN KANBAN BOARD — src/pages/tasks/components/KanbanBoard.tsx
// ============================================================

import type { Task, TaskBoard } from '@shared';
import KanbanColumn, { type ColumnDef } from './KanbanColumn';

const COLUMNS: ColumnDef[] = [
  { key: 'pending_approval', label: 'PENDING APPROVAL', color: 'var(--color-amber)', bg: 'rgba(245,158,11,.06)', border: 'rgba(245,158,11,.2)' },
  { key: 'overdue',     label: 'OVERDUE',     color: 'var(--color-red)',          bg: 'rgba(220,38,38,.06)',    border: 'rgba(220,38,38,.2)' },
  { key: 'today',       label: 'DUE TODAY',   color: 'var(--color-amber)',        bg: 'rgba(245,158,11,.06)',   border: 'rgba(245,158,11,.2)' },
  { key: 'this_week',   label: 'THIS WEEK',   color: 'var(--color-teal)',         bg: 'rgba(0,194,168,.06)',    border: 'rgba(0,194,168,.2)' },
  { key: 'next_week',   label: 'NEXT WEEK',   color: 'var(--color-green)',        bg: 'rgba(22,163,74,.06)',    border: 'rgba(22,163,74,.2)' },
  { key: 'no_deadline', label: 'NO DEADLINE', color: 'var(--color-text-muted)',   bg: 'var(--color-surface-2)', border: 'var(--color-border)' },
  { key: 'backlog',     label: 'BACKLOG',     color: 'var(--color-indigo)',       bg: 'rgba(79,70,229,.06)',    border: 'rgba(79,70,229,.2)' },
  { key: 'completed',   label: 'COMPLETED',   color: 'var(--color-green)',        bg: 'rgba(22,163,74,.06)',    border: 'rgba(22,163,74,.2)' },
];

interface Props {
  board:    TaskBoard | undefined;
  loading:  boolean;
  onSelect: (task: Task) => void;
  onAdd:    () => void;
}

export default function KanbanBoard({ board, loading, onSelect, onAdd }: Props) {
  if (loading) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: 'var(--chalk3)', fontSize: 13 }}>Loading board…</span>
      </div>
    );
  }

  return (
    <div style={{
      display:    'flex',
      gap:        12,
      overflow:   'auto',
      flex:       1,
      padding:    '16px 20px 20px',
      alignItems: 'flex-start',
    }} tabIndex={0} role="region" aria-label="Task board">
      {COLUMNS.map(col => {
        const tasks: Task[] = (board as any)?.[col.key] ?? [];
        return (
          <KanbanColumn
            key={col.key}
            col={col}
            tasks={tasks}
            onSelect={onSelect}
            onAdd={onAdd}
          />
        );
      })}
    </div>
  );
}
