// ============================================================
// OPSYN QUICK TASK PANEL — src/pages/tasks/components/QuickTaskPanel.tsx
// Slide-in side panel showing "My Tasks" list
// ============================================================

import { useQuery } from '@tanstack/react-query';
import { tasksApi } from '../../../api/tasks.api';
import type { Task } from '@shared';

const PRIORITY_COLOR: Record<string, string> = {
  critical: 'var(--rose)',
  high:     'var(--amber)',
  medium:   'var(--cyan)',
  low:      'var(--green)',
};

const BUCKET_LABEL: Record<string, string> = {
  pending_approval: 'Pending approval',
  completed:   'Completed',
  overdue:     'Overdue',
  today:       'Today',
  this_week:   'This Week',
  next_week:   'Next Week',
  no_deadline: 'No Date',
  backlog:     'Backlog',
};

interface Props {
  onSelect: (task: Task) => void;
  onClose:  () => void;
}

export default function QuickTaskPanel({ onSelect, onClose }: Props) {
  const { data: myTasks, isLoading } = useQuery({
    queryKey: ['tasks', 'my'],
    queryFn:  tasksApi.getMyTasks,
    staleTime: 30 * 1000,
  });

  const tasks: Task[] = Array.isArray(myTasks) ? myTasks : [];

  const grouped: Record<string, Task[]> = {};
  for (const t of tasks) {
    const bucket = t.deadline_bucket ?? 'backlog';
    if (!grouped[bucket]) grouped[bucket] = [];
    grouped[bucket].push(t);
  }

  const bucketOrder = ['pending_approval', 'overdue', 'today', 'this_week', 'next_week', 'backlog', 'no_deadline', 'completed'];

  return (
    <div style={{
      width:        290,
      minWidth:     290,
      background:   'var(--bg2)',
      borderLeft:   '1px solid var(--wire)',
      display:      'flex',
      flexDirection: 'column',
      boxShadow:    '-4px 0 24px rgba(0,0,0,.3)',
    }}>
      {/* Header */}
      <div style={{
        padding:        '14px 16px',
        borderBottom:   '1px solid var(--wire)',
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'space-between',
        flexShrink:     0,
      }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--chalk)' }}>My Tasks</div>
          <div style={{ fontSize: 10, color: 'var(--chalk3)', marginTop: 2 }}>
            {tasks.length} assigned to you
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            background:   'rgba(255,255,255,.05)',
            border:       '1px solid var(--wire2)',
            borderRadius: 6,
            padding:      '4px 9px',
            color:        'var(--chalk2)',
            cursor:       'pointer',
            fontSize:     13,
            fontFamily:   'var(--font)',
          }}
        >
          ✕
        </button>
      </div>

      {/* Task list */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px', scrollbarWidth: 'none' }}>
        {isLoading && (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--chalk3)', fontSize: 12 }}>
            Loading…
          </div>
        )}

        {!isLoading && tasks.length === 0 && (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--chalk3)', fontSize: 12 }}>
            No tasks assigned to you
          </div>
        )}

        {bucketOrder.map(bucket => {
          const bucketTasks = grouped[bucket];
          if (!bucketTasks?.length) return null;
          return (
            <div key={bucket} style={{ marginBottom: 16 }}>
              <div style={{
                fontSize:      9,
                fontWeight:    700,
                color:         bucket === 'overdue' ? 'var(--rose)' : 'var(--chalk3)',
                textTransform: 'uppercase',
                letterSpacing: '.1em',
                marginBottom:  6,
                padding:       '0 4px',
              }}>
                {BUCKET_LABEL[bucket] ?? bucket} · {bucketTasks.length}
              </div>
              {bucketTasks.map(t => (
                <div
                  key={t.id}
                  onClick={() => onSelect(t)}
                  style={{
                    padding:      '10px 12px',
                    borderRadius: 8,
                    cursor:       'pointer',
                    marginBottom: 6,
                    background:   'var(--bg3)',
                    border:       '1px solid var(--wire)',
                    transition:   'border-color .15s',
                    position:     'relative',
                  }}
                >
                  {/* Priority stripe */}
                  <div style={{
                    position:     'absolute',
                    top:          0,
                    bottom:       0,
                    left:         0,
                    width:        3,
                    borderRadius: '8px 0 0 8px',
                    background:   PRIORITY_COLOR[t.priority] || 'var(--chalk3)',
                  }} />

                  <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--chalk)',
                                lineHeight: 1.4, marginBottom: 6, paddingLeft: 4 }}>
                    {t.title}
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingLeft: 4 }}>
                    <span style={{ fontSize: 10, color: 'var(--chalk3)' }}>
                      {t.deadline
                        ? new Date(t.deadline).toLocaleDateString('en-GB', { month: 'short', day: 'numeric' })
                        : 'No date'}
                    </span>
                    <span style={{
                      fontSize:    10,
                      padding:     '1px 6px',
                      borderRadius: 4,
                      background:  'var(--bg4)',
                      color:       'var(--chalk3)',
                    }}>
                      {t.status.replace('_', ' ')}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          );
        })}
      </div>

      {/* Footer summary */}
      {tasks.length > 0 && (
        <div style={{
          padding:    '10px 16px',
          borderTop:  '1px solid var(--wire)',
          fontSize:   11,
          color:      'var(--chalk3)',
          flexShrink: 0,
        }}>
          {grouped['overdue']?.length
            ? <span style={{ color: 'var(--rose)', fontWeight: 600 }}>
                {grouped['overdue'].length} overdue ·{' '}
              </span>
            : null}
          {tasks.filter(t => t.status !== 'done').length} active
        </div>
      )}
    </div>
  );
}
