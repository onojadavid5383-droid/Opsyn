// ============================================================
// OPSYN KANBAN COLUMN — src/pages/tasks/components/KanbanColumn.tsx
// ============================================================

import type { Task } from '@shared';
import TaskCard from './TaskCard';

export interface ColumnDef {
  key:    string;
  label:  string;
  color:  string;
  bg:     string;
  border: string;
}

interface Props {
  col:      ColumnDef;
  tasks:    Task[];
  onSelect: (task: Task) => void;
  onAdd:    () => void;
}

export default function KanbanColumn({ col, tasks, onSelect, onAdd }: Props) {
  return (
    <div style={{ flexShrink: 0, width: 272 }}>
      {/* Column header */}
      <div style={{
        display:         'flex',
        alignItems:      'center',
        justifyContent:  'space-between',
        padding:         '10px 12px',
        borderRadius:    '12px 12px 0 0',
        background:      col.bg,
        border:          `1px solid ${col.border}`,
        borderBottom:    'none',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <div style={{
            width:           22,
            height:          22,
            borderRadius:    6,
            display:         'flex',
            alignItems:      'center',
            justifyContent:  'center',
            fontSize:        11,
            fontWeight:      800,
            background:      `${col.color}22`,
            color:           col.color,
          }}>
            {tasks.length}
          </div>
          <span style={{
            fontSize:      11,
            fontWeight:    800,
            letterSpacing: '.06em',
            color:         col.color,
          }}>
            {col.label}
          </span>
        </div>
      </div>

      {/* Column body */}
      <div style={{
        display:       'flex',
        flexDirection: 'column',
        gap:           8,
        padding:       '10px 8px',
        borderRadius:  '0 0 12px 12px',
        background:    'var(--bg3)',
        border:        `1px solid ${col.border}`,
        borderTop:     'none',
        minHeight:     80,
      }}>
        {tasks.map(task => (
          <TaskCard key={task.id} task={task} onClick={onSelect} />
        ))}

        {tasks.length === 0 && col.key !== 'overdue' && (
          <div style={{
            padding:     '12px 8px',
            textAlign:   'center',
            fontSize:    11,
            color:       'var(--chalk3)',
            border:      '1px dashed var(--wire2)',
            borderRadius: 8,
          }}>
            No tasks here
          </div>
        )}

        <div
          onClick={onAdd}
          style={{
            display:     'flex',
            alignItems:  'center',
            gap:         6,
            padding:     '7px 10px',
            borderRadius: 8,
            color:       'var(--chalk3)',
            fontSize:    11,
            cursor:      'pointer',
            border:      '1px dashed var(--wire2)',
          }}
        >
          + Add task
        </div>
      </div>
    </div>
  );
}
