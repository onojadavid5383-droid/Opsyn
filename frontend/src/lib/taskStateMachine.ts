// ============================================================
// OPSYN TASK STATE MACHINE
// Enforces valid transitions, permission checks, dependency
// validation, and mandatory comment requirements.
// canMove() is the single authoritative validation gate.
// ============================================================

import type {
  Task,
  TaskStatus,
  AuthUser,
  TaskDependency,
} from '@shared';

// ── State metadata ───────────────────────────────────────────

export const TASK_STATES: TaskStatus[] = [
  'new', 'assigned', 'in_progress', 'review', 'blocked', 'done', 'archived',
];

export const STATE_LABELS: Record<TaskStatus, string> = {
  new:         'New',
  assigned:    'Assigned',
  in_progress: 'In Progress',
  review:      'Review',
  blocked:     'Blocked',
  done:        'Done',
  archived:    'Archived',
};

export const STATE_COLORS: Record<TaskStatus, string> = {
  new:         'var(--chalk3)',
  assigned:    'var(--cyan)',
  in_progress: 'var(--brand)',
  review:      'var(--amber)',
  blocked:     'var(--rose)',
  done:        'var(--green)',
  archived:    'var(--chalk3)',
};

// Primary pipeline order (BLOCKED and ARCHIVED are side states)
export const PIPELINE_FLOW: TaskStatus[] = [
  'new', 'assigned', 'in_progress', 'review', 'done',
];

// ── Transition map ───────────────────────────────────────────
// Defines every valid state transition.

export const TRANSITIONS: Record<TaskStatus, TaskStatus[]> = {
  new:         ['assigned', 'in_progress'],
  assigned:    ['in_progress', 'blocked'],
  in_progress: ['review', 'blocked', 'assigned'],
  review:      ['in_progress', 'done', 'blocked'],
  blocked:     ['in_progress', 'assigned'],
  done:        ['review', 'archived'],
  archived:    [],
};

// ── Role-level caps per transition ───────────────────────────
// Minimum role_level required to perform a transition.

const TRANSITION_ROLE_REQUIREMENTS: Partial<Record<TaskStatus, number>> = {
  done:     2,   // at least operator level to approve Done
  archived: 3,   // team lead+ to archive
};

// ── Validation types ─────────────────────────────────────────

export interface TransitionValidationResult {
  allowed: boolean;
  reason?: string;
}

export interface CanMoveParams {
  task: Task & { dependencies?: TaskDependency[] };
  fromStatus: TaskStatus;
  toStatus: TaskStatus;
  user: AuthUser;
  hasUnresolvedActions?: boolean;
}

// ── canMove — the single validation gate ─────────────────────

export function canMove(params: CanMoveParams): TransitionValidationResult {
  const { task, fromStatus, toStatus, user, hasUnresolvedActions } = params;

  // 1. Archived is a hard dead-end.
  if (fromStatus === 'archived') {
    return { allowed: false, reason: 'Archived tasks cannot be moved. Clone or reopen the task instead.' };
  }

  // 2. Validate transition is in the allowed map.
  const allowed = TRANSITIONS[fromStatus] ?? [];
  if (!allowed.includes(toStatus)) {
    return {
      allowed: false,
      reason: `Cannot transition from ${STATE_LABELS[fromStatus]} to ${STATE_LABELS[toStatus]}.`,
    };
  }

  // 3. Role-level permission check.
  const requiredLevel = TRANSITION_ROLE_REQUIREMENTS[toStatus] ?? 1;
  if (user.role_level < requiredLevel) {
    return {
      allowed: false,
      reason: `Your role level (${user.role_level}) is insufficient for this transition. Required: ${requiredLevel}.`,
    };
  }

  // 4. Dependency gate: cannot start a task when dependencies are incomplete.
  if (toStatus === 'in_progress' && task.dependencies && task.dependencies.length > 0) {
    const incomplete = task.dependencies.filter(d => d.depends_on_task?.status !== 'done');
    if (incomplete.length > 0) {
      const titles = incomplete
        .map(d => d.depends_on_task?.title ?? d.depends_on_task_id)
        .slice(0, 2)
        .join(', ');
      return {
        allowed: false,
        reason: `${incomplete.length} blocking dependenc${incomplete.length === 1 ? 'y' : 'ies'} must be completed first: ${titles}${incomplete.length > 2 ? '…' : ''}.`,
      };
    }
  }

  // 5. Unresolved ACTION comments block forward movement
  //    (but not backward moves or BLOCKED transitions).
  const isForward = PIPELINE_FLOW.indexOf(toStatus) > PIPELINE_FLOW.indexOf(fromStatus);
  if (isForward && hasUnresolvedActions && toStatus !== 'blocked') {
    return {
      allowed: false,
      reason: 'Unresolved ACTION comments must be closed before moving forward.',
    };
  }

  return { allowed: true };
}

// ── Helper utilities ─────────────────────────────────────────

export function getForwardMoves(status: TaskStatus): TaskStatus[] {
  const idx = PIPELINE_FLOW.indexOf(status);
  return (TRANSITIONS[status] ?? []).filter(s => {
    const tidx = PIPELINE_FLOW.indexOf(s);
    return tidx > idx || s === 'archived';
  });
}

export function getBackwardMoves(status: TaskStatus): TaskStatus[] {
  const idx = PIPELINE_FLOW.indexOf(status);
  return (TRANSITIONS[status] ?? []).filter(s => {
    const tidx = PIPELINE_FLOW.indexOf(s);
    return tidx < idx && s !== 'blocked';
  });
}

export function getSideMoves(status: TaskStatus): TaskStatus[] {
  return (TRANSITIONS[status] ?? []).filter(s => s === 'blocked' || s === 'archived');
}

export function isDeadEnd(status: TaskStatus): boolean {
  return status === 'archived';
}

export function isTerminal(status: TaskStatus): boolean {
  return status === 'done' || status === 'archived';
}

export function stateFlowIndex(status: TaskStatus): number {
  const idx = PIPELINE_FLOW.indexOf(status);
  return idx === -1 ? 99 : idx;
}
