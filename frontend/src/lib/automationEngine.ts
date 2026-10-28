// ============================================================
// OPSYN AUTOMATION ENGINE
// Evaluates IF–THEN automation rules against task events.
// Rules are fetched from the backend but evaluated client-side
// for immediate UI feedback; backend re-validates on every API call.
// ============================================================

import type {
  Task,
  TaskStatus,
  AutomationRule,
  AutomationCondition,
  AutomationTrigger,
  AutomationAction,
} from '@shared';

// ── Engine context ───────────────────────────────────────────

export interface AutomationEventPayload {
  previousStatus?: TaskStatus;
  newStatus?: TaskStatus;
  completedTaskId?: string;
  commentBody?: string;
  commentType?: string;
}

export interface AutomationContext {
  task: Task;
  event: {
    type: AutomationTrigger;
    payload?: AutomationEventPayload;
  };
}

export interface AutomationResult {
  ruleId: string;
  ruleName: string;
  action: AutomationAction;
  params: Record<string, unknown>;
  systemComment?: string;
}

// ── Condition evaluator ──────────────────────────────────────

function evaluateCondition(condition: AutomationCondition, task: Task): boolean {
  const raw = (task as unknown as Record<string, unknown>)[condition.field];
  const val = condition.value;

  switch (condition.operator) {
    case 'eq':
      return raw === val;
    case 'neq':
      return raw !== val;
    case 'lt':
      if (typeof raw === 'string' && typeof val === 'string') {
        return new Date(raw).getTime() < new Date(val).getTime();
      }
      return (raw as number) < (val as number);
    case 'gt':
      if (typeof raw === 'string' && typeof val === 'string') {
        return new Date(raw).getTime() > new Date(val).getTime();
      }
      return (raw as number) > (val as number);
    case 'contains':
      return Array.isArray(raw)
        ? raw.includes(val)
        : String(raw).toLowerCase().includes(String(val).toLowerCase());
    case 'is_empty':
      return raw == null || (Array.isArray(raw) && raw.length === 0) || raw === '';
    default:
      return false;
  }
}

// ── Rule evaluator ───────────────────────────────────────────

export function evaluateRules(
  rules: AutomationRule[],
  context: AutomationContext,
): AutomationResult[] {
  const results: AutomationResult[] = [];

  for (const rule of rules) {
    if (!rule.is_active) continue;
    if (rule.trigger !== context.event.type) continue;

    const allMet = rule.conditions.every(c => evaluateCondition(c, context.task));
    if (!allMet) continue;

    const systemComment =
      rule.action === 'add_system_comment'
        ? String(rule.action_params.body ?? `Automation rule "${rule.name}" fired.`)
        : `[SYSTEM] Automation: "${rule.name}" applied.`;

    results.push({
      ruleId:        rule.id,
      ruleName:      rule.name,
      action:        rule.action,
      params:        rule.action_params,
      systemComment,
    });
  }

  return results;
}

// ── Built-in rules (seeded locally, extended by backend) ─────

export const BUILTIN_RULES: Omit<AutomationRule, 'id' | 'created_at'>[] = [
  {
    name:        'Escalate overdue in-progress tasks',
    description: 'Flag task when deadline has passed and it is not finished',
    pipeline_id: undefined,
    trigger:     'deadline_passed',
    conditions:  [
      { field: 'status', operator: 'neq', value: 'done' },
      { field: 'status', operator: 'neq', value: 'archived' },
    ],
    action:        'add_system_comment',
    action_params: { body: '⚠ Task deadline has passed. Consider escalating or updating the deadline.' },
    is_active:     true,
  },
  {
    name:        'Notify on dependency completion',
    description: 'Add system comment when all blocking dependencies are done',
    pipeline_id: undefined,
    trigger:     'dependency_completed',
    conditions:  [
      { field: 'status', operator: 'eq', value: 'assigned' },
    ],
    action:        'add_system_comment',
    action_params: { body: '✓ All blocking dependencies are complete. This task is ready to start.' },
    is_active:     true,
  },
  {
    name:        'Auto-archive completed tasks after soak',
    description: 'Archive tasks that have been Done for the SLA window',
    pipeline_id: undefined,
    trigger:     'sla_breached',
    conditions:  [
      { field: 'status', operator: 'eq', value: 'done' },
    ],
    action:        'move_to_status',
    action_params: { status: 'archived' },
    is_active:     false,
  },
  {
    name:        'Block task when BLOCKER comment posted',
    description: 'Automatically move task to Blocked state when a BLOCKER comment is added',
    pipeline_id: undefined,
    trigger:     'comment_added',
    conditions:  [
      { field: 'status', operator: 'neq', value: 'blocked' },
      { field: 'status', operator: 'neq', value: 'done' },
      { field: 'status', operator: 'neq', value: 'archived' },
    ],
    action:        'move_to_status',
    action_params: { status: 'blocked' },
    is_active:     true,
  },
];

// ── Deadline check helper ────────────────────────────────────

export function isDeadlinePassed(task: Task): boolean {
  if (!task.deadline) return false;
  return new Date(task.deadline).getTime() < Date.now();
}

// ── Client-side trigger helper ───────────────────────────────
// Checks which built-in automation events apply to a task right now.

export function getApplicableTriggers(task: Task): AutomationTrigger[] {
  const triggers: AutomationTrigger[] = [];
  if (isDeadlinePassed(task)) triggers.push('deadline_passed');
  return triggers;
}
