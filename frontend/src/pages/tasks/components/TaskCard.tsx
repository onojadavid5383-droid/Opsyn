// ============================================================
// OPSYN TASK CARD — src/pages/tasks/components/TaskCard.tsx
// ============================================================

import type { Task } from '@shared';

const PRIORITY_COLOR: Record<string, string> = {
  critical: 'var(--color-red)',
  high:     'var(--color-amber)',
  medium:   'var(--color-teal)',
  low:      'var(--color-green)',
};

function formatDeadline(task: Task): string {
  if (task.deadline_bucket === 'pending_approval') return 'Pending approval';
  if (task.deadline_bucket === 'completed')   return 'Completed';
  if (task.deadline_bucket === 'overdue')     return 'Overdue';
  if (task.deadline_bucket === 'today')       return 'Due Today';
  if (task.deadline_bucket === 'no_deadline') return 'No deadline';
  if (task.deadline_bucket === 'backlog')     return 'Backlog';
  if (task.deadline) {
    return new Date(task.deadline).toLocaleDateString('en-GB', {
      month: 'short', day: 'numeric',
    });
  }
  return '—';
}

interface Props {
  task:    Task;
  onClick: (task: Task) => void;
}

export default function TaskCard({ task, onClick }: Props) {
  const barColor = PRIORITY_COLOR[task.priority] || 'var(--chalk3)';

  return (
    <div
      onClick={() => onClick(task)}
      style={{
        background: 'var(--surface)',
        border:       '1px solid var(--color-border)',
        borderRadius: 'var(--radius-card)',
        padding:      '11px 11px 11px 14px',
        cursor:       'pointer',
        transition:   'all .18s',
        position:     'relative',
      }}
    >
      {/* Priority stripe */}
      <div style={{
        position:     'absolute',
        top:          0, bottom: 0, left: 0,
        width:        3,
        borderRadius: '12px 0 0 12px',
        background:   barColor,
      }} />

      {/* Ticket number + blocked badge */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
        {task.ticket_number && (
          <span
            title="Copy ticket number"
            onClick={e => { e.stopPropagation(); navigator.clipboard.writeText(task.ticket_number!); }}
            style={{
              fontFamily:   'var(--font-mono)',
              fontSize:     9,
              color:        'var(--color-teal)',
              letterSpacing: '0.04em',
              cursor:       'copy',
            }}
          >
            {task.ticket_number}
          </span>
        )}
        {task.status === 'blocked' && task.block_reason && (
          <span
            title={task.block_reason}
            style={{
              fontSize:     9,
              padding:      '1px 5px',
              borderRadius: 3,
              background:   'rgba(220,38,38,0.10)',
              color:        'var(--color-red)',
              maxWidth:     120,
              overflow:     'hidden',
              textOverflow: 'ellipsis',
              whiteSpace:   'nowrap',
            }}
          >
            ⊘ {task.block_reason}
          </span>
        )}
      </div>

      {/* Title */}
      <div style={{
        fontSize:     12,
        fontWeight:   500,
        color:        'var(--color-text-primary)',
        lineHeight:   1.4,
        marginBottom: 8,
      }}>
        {task.title}
      </div>

      {/* Tags */}
      {task.tags?.length > 0 && (
        <div style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap' }}>
          {task.tags.map(t => (
            <span key={t} style={{
              fontSize:    10,
              padding:     '2px 6px',
              borderRadius: 4,
              background:  'var(--color-surface-2)',
              color:       'var(--color-text-muted)',
            }}>
              #{t}
            </span>
          ))}
        </div>
      )}

      {/* Footer row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--color-text-muted)' }}>
          {formatDeadline(task)}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {task.assignee && (
            <div
              title={task.assignee.full_name}
              style={{
                width:           20,
                height:          20,
                borderRadius:    '50%',
                background:      'var(--brand)',
                display:         'flex',
                alignItems:      'center',
                justifyContent:  'center',
                fontSize:        8,
                fontWeight:      700,
                color:           'var(--color-navy)',
              }}
            >
              {(task.assignee.first_name?.[0] ?? '') + (task.assignee.last_name?.[0] ?? '')}
            </div>
          )}
          {task.comment_count > 0 && (
            <span style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>
              💬 {task.comment_count}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
