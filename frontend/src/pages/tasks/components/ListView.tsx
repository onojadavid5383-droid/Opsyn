// ============================================================
// OPSYN TASK LIST VIEW — src/pages/tasks/components/ListView.tsx
// ============================================================

import { useState } from 'react';
import type { Task, TaskBoard } from '@shared';

const PRIORITY_COLOR: Record<string, string> = {
  critical: 'var(--rose)',
  high:     'var(--amber)',
  medium:   'var(--cyan)',
  low:      'var(--green)',
};

const STATUS_COLOR: Record<string, string> = {
  backlog:     'var(--chalk3)',
  in_progress: 'var(--cyan)',
  in_review:   'var(--amber)',
  done:        'var(--green)',
};

type SortKey = 'title' | 'priority' | 'status' | 'deadline' | 'created_at';

function flattenBoard(board: TaskBoard | undefined): Task[] {
  if (!board) return [];
  return [
    ...board.pending_approval,
    ...board.completed,
    ...board.overdue,
    ...board.today,
    ...board.this_week,
    ...board.next_week,
    ...board.no_deadline,
    ...board.backlog,
  ];
}

const PRIORITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
const STATUS_ORDER:   Record<string, number> = { in_progress: 0, in_review: 1, backlog: 2, done: 3 };

interface Props {
  board:    TaskBoard | undefined;
  loading:  boolean;
  onSelect: (task: Task) => void;
}

export default function ListView({ board, loading, onSelect }: Props) {
  const [sortKey,  setSortKey]  = useState<SortKey>('priority');
  const [sortAsc,  setSortAsc]  = useState(true);

  const tasks = flattenBoard(board);

  const sorted = [...tasks].sort((a, b) => {
    let cmp = 0;
    if (sortKey === 'priority') {
      cmp = (PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9);
    } else if (sortKey === 'status') {
      cmp = (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9);
    } else if (sortKey === 'deadline') {
      const aDate = a.deadline ? new Date(a.deadline).getTime() : Infinity;
      const bDate = b.deadline ? new Date(b.deadline).getTime() : Infinity;
      cmp = aDate - bDate;
    } else if (sortKey === 'title') {
      cmp = a.title.localeCompare(b.title);
    } else if (sortKey === 'created_at') {
      cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
    }
    return sortAsc ? cmp : -cmp;
  });

  function Col({ label, sk }: { label: string; sk: SortKey }) {
    const active = sortKey === sk;
    return (
      <th
        onClick={() => { if (active) setSortAsc(a => !a); else { setSortKey(sk); setSortAsc(true); } }}
        style={{
          padding:       '10px 12px',
          textAlign:     'left',
          fontSize:      10,
          fontWeight:    700,
          letterSpacing: '.08em',
          color:         active ? 'var(--cyan)' : 'var(--chalk3)',
          textTransform: 'uppercase',
          cursor:        'pointer',
          userSelect:    'none',
          whiteSpace:    'nowrap',
        }}
      >
        {label} {active ? (sortAsc ? '↑' : '↓') : ''}
      </th>
    );
  }

  if (loading) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: 'var(--chalk3)', fontSize: 13 }}>Loading tasks…</span>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }} tabIndex={0} role="region" aria-label="Task list">
      <div style={{
        background:   'var(--bg2)',
        border:       '1px solid var(--wire)',
        borderRadius: 12,
        overflow:     'hidden',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--wire)' }}>
              <Col label="Task"       sk="title"      />
              <Col label="Priority"   sk="priority"   />
              <Col label="Status"     sk="status"     />
              <Col label="Deadline"   sk="deadline"   />
              <Col label="Created"    sk="created_at" />
              <th style={{ padding: '10px 12px', fontSize: 10, fontWeight: 700,
                           color: 'var(--chalk3)', textAlign: 'right', textTransform: 'uppercase',
                           letterSpacing: '.08em' }}>
                Assignee
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((task, i) => (
              <tr
                key={task.id}
                onClick={() => onSelect(task)}
                style={{
                  borderBottom: i < sorted.length - 1 ? '1px solid var(--wire)' : 'none',
                  cursor:       'pointer',
                  transition:   'background .12s',
                  background:   'transparent',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg3)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              >
                <td style={{ padding: '12px 12px', maxWidth: 280 }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                    <div style={{
                      width:        3,
                      height:       '100%',
                      minHeight:    14,
                      borderRadius: 2,
                      background:   PRIORITY_COLOR[task.priority] || 'var(--chalk3)',
                      flexShrink:   0,
                      marginTop:    2,
                    }} />
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--chalk)',
                                    lineHeight: 1.4, marginBottom: task.tags.length ? 4 : 0 }}>
                        {task.title}
                      </div>
                      {task.tags.length > 0 && (
                        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                          {task.tags.map(t => (
                            <span key={t} style={{
                              fontSize: 9, padding: '1px 5px', borderRadius: 3,
                              background: 'var(--bg4)', color: 'var(--chalk3)',
                            }}>
                              #{t}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </td>
                <td style={{ padding: '12px 12px' }}>
                  <span style={{
                    display:      'inline-flex',
                    alignItems:   'center',
                    gap:          4,
                    padding:      '2px 7px',
                    borderRadius: 5,
                    fontSize:     11,
                    fontWeight:   600,
                    color:        PRIORITY_COLOR[task.priority] || 'var(--chalk3)',
                    background:   `${PRIORITY_COLOR[task.priority] || 'var(--chalk3)'}22`,
                  }}>
                    {task.priority}
                  </span>
                </td>
                <td style={{ padding: '12px 12px' }}>
                  <span style={{
                    display:      'inline-flex',
                    alignItems:   'center',
                    gap:          4,
                    padding:      '2px 7px',
                    borderRadius: 5,
                    fontSize:     11,
                    fontWeight:   600,
                    color:        STATUS_COLOR[task.status] || 'var(--chalk3)',
                    background:   `${STATUS_COLOR[task.status] || 'var(--chalk3)'}22`,
                  }}>
                    {task.status.replace('_', ' ')}
                  </span>
                </td>
                <td style={{ padding: '12px 12px', fontFamily: 'var(--mono)', fontSize: 11,
                              color: 'var(--chalk2)', whiteSpace: 'nowrap' }}>
                  {task.deadline
                    ? new Date(task.deadline).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
                    : <span style={{ color: 'var(--chalk3)' }}>No deadline</span>}
                </td>
                <td style={{ padding: '12px 12px', fontFamily: 'var(--mono)', fontSize: 11,
                              color: 'var(--chalk3)', whiteSpace: 'nowrap' }}>
                  {new Date(task.created_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}
                </td>
                <td style={{ padding: '12px 12px', textAlign: 'right' }}>
                  {task.assignee ? (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 6 }}>
                      <div style={{
                        width:          24,
                        height:         24,
                        borderRadius:   '50%',
                        background:     'var(--brand)',
                        display:        'flex',
                        alignItems:     'center',
                        justifyContent: 'center',
                        fontSize:       9,
                        fontWeight:     700,
                        color:          '#050810',
                      }}>
                        {(task.assignee.first_name?.[0] ?? '') + (task.assignee.last_name?.[0] ?? '')}
                      </div>
                      <span style={{ fontSize: 11, color: 'var(--chalk2)' }}>
                        {task.assignee.full_name}
                      </span>
                    </div>
                  ) : (
                    <span style={{ fontSize: 11, color: 'var(--chalk3)' }}>Unassigned</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {sorted.length === 0 && (
          <div style={{ padding: 32, textAlign: 'center', color: 'var(--chalk3)', fontSize: 13 }}>
            No tasks found
          </div>
        )}
      </div>

      <div style={{ marginTop: 10, fontSize: 11, color: 'var(--chalk3)', textAlign: 'right' }}>
        {sorted.length} task{sorted.length !== 1 ? 's' : ''}
      </div>
    </div>
  );
}
