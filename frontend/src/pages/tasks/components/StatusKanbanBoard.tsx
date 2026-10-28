// ============================================================
// OPSYN STATUS KANBAN BOARD — 7-state workflow view
// S2.1.4: new / assigned / in_progress / review / blocked / done / archived
// ============================================================

import type { Task, TaskStatusBoard } from '@shared';
import KanbanColumn, { type ColumnDef } from './KanbanColumn';

const STATUS_COLUMNS: ColumnDef[] = [
  { key: 'new',         label: 'NEW',         color: 'var(--chalk3)', bg: 'rgba(255,255,255,.03)', border: 'var(--wire2)' },
  { key: 'assigned',    label: 'ASSIGNED',    color: 'var(--violet)', bg: 'rgba(167,139,250,.08)', border: 'rgba(167,139,250,.2)' },
  { key: 'in_progress', label: 'IN PROGRESS', color: 'var(--cyan)',   bg: 'rgba(6,182,212,.08)',   border: 'rgba(6,182,212,.2)' },
  { key: 'review',      label: 'IN REVIEW',   color: 'var(--amber)',  bg: 'rgba(251,191,36,.08)',  border: 'rgba(251,191,36,.2)' },
  { key: 'blocked',     label: 'BLOCKED',     color: 'var(--rose)',   bg: 'rgba(248,113,113,.08)', border: 'rgba(248,113,113,.2)' },
  { key: 'done',        label: 'DONE',        color: 'var(--green)',  bg: 'rgba(74,222,128,.08)',  border: 'rgba(74,222,128,.2)' },
  { key: 'archived',    label: 'ARCHIVED',    color: 'var(--chalk4)', bg: 'rgba(255,255,255,.02)', border: 'var(--wire)' },
];

interface Props {
  board:    TaskStatusBoard | undefined;
  loading:  boolean;
  onSelect: (task: Task) => void;
  onAdd:    () => void;
}

export default function StatusKanbanBoard({ board, loading, onSelect, onAdd }: Props) {
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
    }} tabIndex={0} role="region" aria-label="Task board by status">
      {STATUS_COLUMNS.map(col => {
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
