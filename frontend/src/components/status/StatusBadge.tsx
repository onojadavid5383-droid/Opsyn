// ============================================================
// OPSYN — StatusBadge + StateBadge
// Two systems, never mixed:
//   StatusBadge  alarm SEVERITY — shape + colour + text (critical ⬣ …)
//   StateBadge   workflow STATE — neutral pill + coloured dot + text
// ============================================================

import type { OutageSeverity, TaskStatus } from '@shared';
import styles from '../ui/Badge.module.css';
import { SEVERITY_META } from './severity';
import { SeverityIcon } from './SeverityIcon';

export interface StatusBadgeProps {
  severity: OutageSeverity;
  /** Optional count shown before the label, e.g. "3 Critical" */
  count?:   number;
  size?:    'xs' | 'sm' | 'md';
}

export function StatusBadge({ severity, count, size = 'sm' }: StatusBadgeProps) {
  const tone = severity === 'low' ? 'info' : severity;
  return (
    <span className={`${styles.badge} ${styles[tone]} ${styles[size]}`}>
      <SeverityIcon severity={severity} size={size === 'md' ? 14 : 12} />
      {count !== undefined && <span style={{ fontVariantNumeric: 'tabular-nums' }}>{count}</span>}
      {SEVERITY_META[severity].label}
    </span>
  );
}

type WorkflowState = TaskStatus | 'pending' | 'approved' | 'rejected' | 'active' | 'paused' | 'completed'
  | 'monitoring' | 'in_resolution' | 'resolved';

const STATE_META: Record<WorkflowState, { label: string; dot: string }> = {
  new:         { label: 'New',         dot: 'var(--state-new)' },
  assigned:    { label: 'Assigned',    dot: 'var(--state-progress)' },
  in_progress: { label: 'In progress', dot: 'var(--state-progress)' },
  review:      { label: 'In review',   dot: 'var(--state-review)' },
  blocked:     { label: 'Blocked',     dot: 'var(--state-blocked)' },
  done:        { label: 'Done',        dot: 'var(--state-done)' },
  archived:    { label: 'Archived',    dot: 'var(--state-archived)' },
  pending:     { label: 'Pending',     dot: 'var(--status-warning-fg)' },
  approved:    { label: 'Approved',    dot: 'var(--state-done)' },
  rejected:    { label: 'Rejected',    dot: 'var(--state-blocked)' },
  active:      { label: 'Active',      dot: 'var(--state-progress)' },
  paused:      { label: 'Paused',      dot: 'var(--state-new)' },
  completed:   { label: 'Completed',   dot: 'var(--state-done)' },
  // Outage lifecycle (severity is a separate badge — StatusBadge)
  monitoring:    { label: 'Monitoring',    dot: 'var(--state-review)' },
  in_resolution: { label: 'In resolution', dot: 'var(--state-progress)' },
  resolved:      { label: 'Resolved',      dot: 'var(--state-done)' },
};

export interface StateBadgeProps {
  state:  WorkflowState | string;
  /** Override the displayed text (defaults to a readable form of the state) */
  label?: string;
  size?:  'xs' | 'sm' | 'md';
}

export function StateBadge({ state, label, size = 'sm' }: StateBadgeProps) {
  const meta = STATE_META[state as WorkflowState];
  const text = label ?? meta?.label ?? state.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
  return (
    <span className={`${styles.badge} ${styles.state} ${styles[size]}`}>
      <span className={styles.dot} style={{ ['--tone-dot' as string]: meta?.dot ?? 'var(--state-new)' }} aria-hidden="true" />
      {text}
    </span>
  );
}
