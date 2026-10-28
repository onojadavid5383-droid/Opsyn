// ============================================================
// OPSYN GANTT VIEW — src/pages/tasks/components/GanttView.tsx
// Timeline bar chart grouped by deadline bucket
// ============================================================

import type { Task, TaskBoard } from '@shared';

const BAR_COLORS: Record<string, string> = {
  critical: 'linear-gradient(90deg,#f87171,#ef4444)',
  high:     'linear-gradient(90deg,#fbbf24,#f59e0b)',
  medium:   'linear-gradient(90deg,#06b6d4,#3b82f6)',
  low:      'linear-gradient(90deg,#4ade80,#22d3a0)',
};

const STATUS_PCT: Record<string, number> = {
  done:        90,
  archived:    100,
  in_review:   75,
  in_progress: 40,
  backlog:     5,
};

function flatTasks(board: TaskBoard | undefined): Task[] {
  if (!board) return [];
  return [
    ...board.pending_approval.map(t => ({ ...t, _bucket: 'PENDING APPROVAL' })),
    ...board.completed.map(t => ({ ...t, _bucket: 'COMPLETED' })),
    ...board.overdue.map(t => ({ ...t, _bucket: 'OVERDUE' })),
    ...board.today.map(t => ({ ...t, _bucket: 'DUE TODAY' })),
    ...board.this_week.map(t => ({ ...t, _bucket: 'THIS WEEK' })),
    ...board.next_week.map(t => ({ ...t, _bucket: 'NEXT WEEK' })),
    ...board.no_deadline.map(t => ({ ...t, _bucket: 'NO DEADLINE' })),
    ...board.backlog.map(t => ({ ...t, _bucket: 'BACKLOG' })),
  ] as (Task & { _bucket: string })[];
}

const DAY_HEADERS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function buildWeekDays(): { label: string; date: Date }[] {
  const today = new Date();
  const monday = new Date(today);
  monday.setDate(today.getDate() - ((today.getDay() + 6) % 7));
  return Array.from({ length: 14 }, (_, i) => {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    return {
      label: d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }),
      date:  d,
    };
  });
}

function getBarPosition(task: Task, days: { date: Date }[]): { left: string; width: string } | null {
  if (!task.deadline) return null;
  const deadline = new Date(task.deadline);
  const start    = new Date(task.created_at);
  const rangeStart = days[0].date.getTime();
  const rangeEnd   = days[days.length - 1].date.getTime();
  const rangeLen   = rangeEnd - rangeStart;
  if (rangeLen === 0) return null;

  const barStart = Math.max(start.getTime(), rangeStart);
  const barEnd   = Math.min(deadline.getTime(), rangeEnd + 86400000);
  if (barEnd < rangeStart || barStart > rangeEnd) return null;

  const leftPct  = ((barStart - rangeStart) / rangeLen) * 100;
  const widthPct = Math.max(((barEnd - barStart) / rangeLen) * 100, 4);

  return { left: `${leftPct.toFixed(1)}%`, width: `${Math.min(widthPct, 100 - leftPct).toFixed(1)}%` };
}

interface Props {
  board:   TaskBoard | undefined;
  loading: boolean;
  onSelect: (task: Task) => void;
}

export default function GanttView({ board, loading, onSelect }: Props) {
  const days  = buildWeekDays();
  const tasks = flatTasks(board).filter(t => !['no_deadline', 'backlog'].includes(t.deadline_bucket)).slice(0, 30);

  if (loading) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: 'var(--chalk3)', fontSize: 13 }}>Loading Gantt…</span>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }} tabIndex={0} role="region" aria-label="Task timeline">
      <div style={{
        background:   'var(--bg2)',
        border:       '1px solid var(--wire)',
        borderRadius: 12,
        overflow:     'hidden',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--wire)' }}>
          <div style={{ width: 220, flexShrink: 0, padding: '10px 14px',
                        fontSize: 10, fontWeight: 700, color: 'var(--chalk3)',
                        textTransform: 'uppercase', letterSpacing: '.08em' }}>
            Task
          </div>
          <div style={{ flex: 1, display: 'flex' }}>
            {days.map((d, i) => (
              <div key={i} style={{
                flex:           1,
                padding:        '10px 4px',
                fontSize:       9,
                fontWeight:     600,
                color:          isToday(d.date) ? 'var(--cyan)' : 'var(--chalk3)',
                textAlign:      'center',
                borderLeft:     '1px solid var(--wire)',
                background:     isToday(d.date) ? 'rgba(6,182,212,.06)' : 'transparent',
                whiteSpace:     'nowrap',
                overflow:       'hidden',
                textOverflow:   'ellipsis',
              }}>
                {DAY_HEADERS[d.date.getDay() === 0 ? 6 : d.date.getDay() - 1]}
                <br />
                <span style={{ fontFamily: 'var(--mono)', fontSize: 8 }}>
                  {d.date.getDate()}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Today indicator */}
        {tasks.length === 0 && (
          <div style={{ padding: 32, textAlign: 'center', color: 'var(--chalk3)', fontSize: 13 }}>
            No scheduled tasks in the next 2 weeks
          </div>
        )}

        {/* Task rows */}
        {tasks.map((task, i) => {
          const barPos  = getBarPosition(task, days);
          const pct     = STATUS_PCT[task.status] ?? 5;
          return (
            <div
              key={task.id}
              style={{
                display:     'flex',
                borderBottom: i < tasks.length - 1 ? '1px solid var(--wire)' : 'none',
                transition:  'background .12s',
                cursor:      'pointer',
              }}
              onClick={() => onSelect(task)}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg3)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              {/* Task name */}
              <div style={{
                width:        220,
                flexShrink:   0,
                padding:      '10px 14px',
                display:      'flex',
                alignItems:   'center',
                gap:          8,
              }}>
                <div style={{
                  width:        3,
                  height:       28,
                  borderRadius: 2,
                  background:   BAR_COLORS[task.priority]?.split(',')[0].replace('linear-gradient(90deg,', '') || 'var(--chalk3)',
                  flexShrink:   0,
                }} />
                <div>
                  <div style={{ fontSize: 11, fontWeight: 500, color: 'var(--chalk)',
                                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                maxWidth: 170 }}>
                    {task.title}
                  </div>
                  <div style={{ fontSize: 9, color: 'var(--chalk3)', marginTop: 2 }}>
                    {task.priority} · {task.status.replace('_', ' ')}
                  </div>
                </div>
              </div>

              {/* Timeline */}
              <div style={{ flex: 1, position: 'relative', display: 'flex', alignItems: 'center' }}>
                {/* Day grid lines */}
                {days.map((_, di) => (
                  <div key={di} style={{
                    position:   'absolute',
                    left:       `${(di / days.length) * 100}%`,
                    top:        0,
                    bottom:     0,
                    width:      1,
                    background: 'var(--wire)',
                  }} />
                ))}

                {/* Today line */}
                <TodayLine days={days} />

                {/* Task bar */}
                {barPos ? (
                  <div
                    title={`${task.title} — ${task.priority}`}
                    style={{
                      position:     'absolute',
                      left:         barPos.left,
                      width:        barPos.width,
                      height:       22,
                      borderRadius: 5,
                      background:   BAR_COLORS[task.priority] || 'linear-gradient(90deg,var(--cyan),var(--brand))',
                      overflow:     'hidden',
                      boxShadow:    '0 2px 8px rgba(0,0,0,.3)',
                    }}
                  >
                    {/* Progress fill */}
                    <div style={{
                      position:   'absolute',
                      left:       0,
                      top:        0,
                      bottom:     0,
                      width:      `${pct}%`,
                      background: 'rgba(255,255,255,.2)',
                    }} />
                    <div style={{
                      position:   'absolute',
                      inset:      0,
                      display:    'flex',
                      alignItems: 'center',
                      padding:    '0 7px',
                      fontSize:   9,
                      fontWeight: 700,
                      color:      '#050810',
                      overflow:   'hidden',
                      whiteSpace: 'nowrap',
                    }}>
                      {task.title}
                    </div>
                  </div>
                ) : (
                  <div style={{
                    position:     'absolute',
                    right:        4,
                    padding:      '2px 8px',
                    borderRadius: 4,
                    fontSize:     9,
                    color:        'var(--chalk3)',
                    border:       '1px dashed var(--wire2)',
                  }}>
                    No date in range
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function isToday(d: Date): boolean {
  const now = new Date();
  return d.getFullYear() === now.getFullYear() &&
         d.getMonth()    === now.getMonth() &&
         d.getDate()     === now.getDate();
}

function TodayLine({ days }: { days: { date: Date }[] }) {
  const now   = new Date();
  const start = days[0].date.getTime();
  const end   = days[days.length - 1].date.getTime() + 86400000;
  const pct   = ((now.getTime() - start) / (end - start)) * 100;
  if (pct < 0 || pct > 100) return null;
  return (
    <div style={{
      position:   'absolute',
      left:       `${pct}%`,
      top:        0,
      bottom:     0,
      width:      2,
      background: 'rgba(6,182,212,.6)',
      zIndex:     2,
    }} />
  );
}
