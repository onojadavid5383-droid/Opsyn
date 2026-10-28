// ============================================================
// OPSYN TASK FILTERS — src/pages/tasks/components/TaskFilters.tsx
// Search bar + priority / status / deadline_bucket dropdowns
// ============================================================

import type { TaskFilters } from '../../../store/task.store';
import type { Department } from '@shared';
import { GlassSelect } from '../../../components/glass';


const PRIORITY_OPTIONS = [
  { label: 'All Priorities', value: '' },
  { label: 'Critical',       value: 'critical' },
  { label: 'High',           value: 'high' },
  { label: 'Medium',         value: 'medium' },
  { label: 'Low',            value: 'low' },
];

const STATUS_OPTIONS = [
  { label: 'All Statuses',   value: '' },
  { label: 'Backlog',        value: 'backlog' },
  { label: 'In Progress',    value: 'in_progress' },
  { label: 'In Review',      value: 'in_review' },
  { label: 'Done',           value: 'done' },
];

const BUCKET_OPTIONS = [
  { label: 'All Deadlines',  value: '' },
  { label: 'Pending Approval', value: 'pending_approval' },
  { label: 'Completed',     value: 'completed' },
  { label: 'Overdue',        value: 'overdue' },
  { label: 'Today',          value: 'today' },
  { label: 'This Week',      value: 'this_week' },
  { label: 'Next Week',      value: 'next_week' },
  { label: 'No Deadline',    value: 'no_deadline' },
  { label: 'Backlog',        value: 'backlog' },
];

interface Props {
  filters:      TaskFilters;
  departments:  Department[];
  onChange:     (patch: Partial<TaskFilters>) => void;
  onClear:      () => void;
  totalCount:   number;
}

export default function TaskFilters({ filters, departments, onChange, onClear, totalCount }: Props) {
  const hasActive = filters.search || filters.priority || filters.status || filters.deadline_bucket || filters.dept_id;

  return (
    <div style={{
      display:     'flex',
      alignItems:  'center',
      gap:         8,
      padding:     '8px 20px',
      flexShrink:  0,
      borderBottom: '1px solid var(--wire)',
      background:  'var(--bg2)',
      flexWrap:    'wrap',
    }}>
      {/* Search */}
      <div style={{ position: 'relative', flex: 1, minWidth: 180, maxWidth: 300 }}>
        <input
          type="text"
          placeholder="Search tasks…"
          value={filters.search}
          onChange={e => onChange({ search: e.target.value })}
          style={{
            width:        '100%',
            background:   'var(--bg3)',
            border:       '1px solid var(--wire2)',
            borderRadius: 8,
            padding:      '6px 10px 6px 32px',
            color:        'var(--chalk)',
            fontFamily:   'var(--font)',
            fontSize:     11,
            outline:      'none',
          }}
        />
        <span style={{
          position:  'absolute',
          left:      10,
          top:       '50%',
          transform: 'translateY(-50%)',
          fontSize:  12,
          color:     'var(--chalk3)',
        }}>
          ⌕
        </span>
      </div>

      {/* Priority */}
      <GlassSelect value={String(filters.priority)} onChange={v => onChange({ priority: v as any })} options={[...PRIORITY_OPTIONS.map((o) => ({ value: String(o.value), label: String(o.label) }))]} ariaLabel="Filter by priority" compact />

      {/* Status */}
      <GlassSelect value={String(filters.status)} onChange={v => onChange({ status: v as any })} options={[...STATUS_OPTIONS.map((o) => ({ value: String(o.value), label: String(o.label) }))]} ariaLabel="Filter by status" compact />

      {/* Department */}
      <GlassSelect value={String(filters.dept_id)} onChange={v => onChange({ dept_id: v })} options={[...departments.map((d) => ({ value: String(d.id), label: String(d.name) }))]} placeholder={'All Departments'} ariaLabel="Filter by department" compact />

      {/* Deadline bucket */}
      <GlassSelect value={String(filters.deadline_bucket)} onChange={v => onChange({ deadline_bucket: v as any })} options={[...BUCKET_OPTIONS.map((o) => ({ value: String(o.value), label: String(o.label) }))]} ariaLabel="Filter by deadline" compact />

      {/* Clear */}
      {hasActive && (
        <button
          onClick={onClear}
          style={{
            background:   'rgba(248,113,113,.12)',
            border:       '1px solid rgba(248,113,113,.2)',
            borderRadius: 8,
            padding:      '6px 10px',
            color:        'var(--rose)',
            cursor:       'pointer',
            fontFamily:   'var(--font)',
            fontSize:     11,
            fontWeight:   600,
          }}
        >
          ✕ Clear
        </button>
      )}

      {/* Count */}
      <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--chalk3)' }}>
        {totalCount} task{totalCount !== 1 ? 's' : ''}
      </span>
    </div>
  );
}
