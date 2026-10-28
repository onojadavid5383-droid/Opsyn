// ============================================================
// OPSYN CALENDAR VIEW — src/pages/tasks/components/CalendarView.tsx
// Monthly calendar with tasks placed on deadline dates
// ============================================================

import { useState } from 'react';
import type { Task, TaskBoard } from '@shared';

const PRIORITY_COLOR: Record<string, string> = {
  critical: 'var(--rose)',
  high:     'var(--amber)',
  medium:   'var(--cyan)',
  low:      'var(--green)',
};

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function flatTasks(board: TaskBoard | undefined): Task[] {
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

function buildCalendarDays(year: number, month: number): (Date | null)[] {
  const firstDay  = new Date(year, month, 1);
  const lastDay   = new Date(year, month + 1, 0);
  const startDow  = (firstDay.getDay() + 6) % 7; // Mon = 0
  const totalDays = lastDay.getDate();
  const cells: (Date | null)[] = [];

  for (let i = 0; i < startDow; i++) cells.push(null);
  for (let d = 1; d <= totalDays; d++) cells.push(new Date(year, month, d));

  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

interface Props {
  board:   TaskBoard | undefined;
  loading: boolean;
  onSelect: (task: Task) => void;
}

export default function CalendarView({ board, loading, onSelect }: Props) {
  const today      = new Date();
  const [year,  setYear]  = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());

  const tasks = flatTasks(board);

  const tasksByDate: Record<string, Task[]> = {};
  for (const task of tasks) {
    if (task.deadline) {
      const key = task.deadline.slice(0, 10);
      if (!tasksByDate[key]) tasksByDate[key] = [];
      tasksByDate[key].push(task);
    }
  }

  const cells = buildCalendarDays(year, month);

  function prevMonth() {
    if (month === 0) { setYear(y => y - 1); setMonth(11); }
    else setMonth(m => m - 1);
  }
  function nextMonth() {
    if (month === 11) { setYear(y => y + 1); setMonth(0); }
    else setMonth(m => m + 1);
  }

  if (loading) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: 'var(--chalk3)', fontSize: 13 }}>Loading calendar…</span>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }} tabIndex={0} role="region" aria-label="Task calendar">
      <div style={{
        background:   'var(--bg2)',
        border:       '1px solid var(--wire)',
        borderRadius: 12,
        overflow:     'hidden',
      }}>
        {/* Header nav */}
        <div style={{
          display:        'flex',
          alignItems:     'center',
          justifyContent: 'space-between',
          padding:        '14px 18px',
          borderBottom:   '1px solid var(--wire)',
        }}>
          <button
            onClick={prevMonth}
            style={{ background: 'var(--bg3)', border: '1px solid var(--wire2)', borderRadius: 8,
                     padding: '6px 12px', color: 'var(--chalk2)', cursor: 'pointer',
                     fontSize: 12, fontFamily: 'var(--font)' }}
          >
            ‹
          </button>
          <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--chalk)' }}>
            {MONTH_NAMES[month]} {year}
          </div>
          <button
            onClick={nextMonth}
            style={{ background: 'var(--bg3)', border: '1px solid var(--wire2)', borderRadius: 8,
                     padding: '6px 12px', color: 'var(--chalk2)', cursor: 'pointer',
                     fontSize: 12, fontFamily: 'var(--font)' }}
          >
            ›
          </button>
        </div>

        {/* Day names */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', borderBottom: '1px solid var(--wire)' }}>
          {DAY_NAMES.map(d => (
            <div key={d} style={{
              padding:       '8px 0',
              textAlign:     'center',
              fontSize:      10,
              fontWeight:    700,
              color:         'var(--chalk3)',
              textTransform: 'uppercase',
              letterSpacing: '.06em',
            }}>
              {d}
            </div>
          ))}
        </div>

        {/* Calendar grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)' }}>
          {cells.map((date, i) => {
            const isCurrentDay = date &&
              date.getFullYear() === today.getFullYear() &&
              date.getMonth()    === today.getMonth() &&
              date.getDate()     === today.getDate();

            const dateKey    = date ? `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}` : '';
            const dayTasks   = dateKey ? (tasksByDate[dateKey] ?? []) : [];
            const hasOverdue = dayTasks.some(t => t.priority === 'critical');

            return (
              <div
                key={i}
                style={{
                  minHeight:   88,
                  padding:     '6px 8px',
                  borderRight: (i + 1) % 7 !== 0 ? '1px solid var(--wire)' : 'none',
                  borderBottom: i < cells.length - 7 ? '1px solid var(--wire)' : 'none',
                  background:  isCurrentDay
                    ? 'rgba(6,182,212,.06)'
                    : date
                      ? 'transparent'
                      : 'var(--bg3)',
                  opacity:     date ? 1 : 0.4,
                }}
              >
                {date && (
                  <>
                    <div style={{
                      fontSize:        11,
                      fontWeight:      isCurrentDay ? 800 : 500,
                      color:           isCurrentDay ? 'var(--cyan)' : 'var(--chalk2)',
                      marginBottom:    4,
                      display:         'flex',
                      alignItems:      'center',
                      justifyContent:  'space-between',
                    }}>
                      {date.getDate()}
                      {hasOverdue && (
                        <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--rose)',
                                       display: 'block', boxShadow: '0 0 6px rgba(248,113,113,.5)' }} />
                      )}
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                      {dayTasks.slice(0, 3).map(task => (
                        <div
                          key={task.id}
                          onClick={() => onSelect(task)}
                          title={task.title}
                          style={{
                            fontSize:     9,
                            fontWeight:   600,
                            padding:      '2px 5px',
                            borderRadius: 4,
                            cursor:       'pointer',
                            color:        PRIORITY_COLOR[task.priority] || 'var(--chalk2)',
                            background:   `${PRIORITY_COLOR[task.priority] || 'var(--chalk3)'}18`,
                            overflow:     'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace:   'nowrap',
                          }}
                        >
                          {task.title}
                        </div>
                      ))}
                      {dayTasks.length > 3 && (
                        <div style={{ fontSize: 9, color: 'var(--chalk3)', padding: '1px 5px' }}>
                          +{dayTasks.length - 3} more
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
