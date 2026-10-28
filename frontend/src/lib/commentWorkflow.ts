// ============================================================
// OPSYN COMMENT WORKFLOW — helpers only (v5)
// Comments are pure work logs. State changes happen via
// explicit action buttons, not keyword detection.
// ============================================================

import type {
  TaskComment,
  CommentType,
} from '@shared';

// ── Unresolved action check ───────────────────────────────────

export function hasUnresolvedActionComments(comments: TaskComment[]): boolean {
  return comments.some(c => c.type === 'ACTION' && !c.is_resolved);
}

export function hasPendingApproval(comments: TaskComment[]): boolean {
  return comments.some(c => c.type === 'APPROVAL' && c.approval_action === 'pending');
}

// ── System comment builder ────────────────────────────────────

export function buildSystemComment(action: string, actorName?: string): string {
  const who = actorName ? `${actorName} ` : '';
  const ts = new Date().toLocaleString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
  return `${who}${action} — ${ts}`;
}

// ── Comment type display metadata ─────────────────────────────

export interface CommentTypeMeta {
  label: string;
  color: string;
  bg: string;
  icon: string;
  description: string;
}

export const COMMENT_TYPE_META: Record<CommentType, CommentTypeMeta> = {
  NORMAL:   { label: 'Comment',  color: 'var(--chalk2)',  bg: 'var(--bg3)',           icon: '💬', description: 'Standard message' },
  SYSTEM:   { label: 'System',   color: 'var(--chalk3)',  bg: 'var(--bg2)',           icon: '⚙',  description: 'Auto-generated log entry' },
  ACTION:   { label: 'Action',   color: 'var(--amber)',   bg: 'rgba(245,158,11,.08)', icon: '⚡', description: 'Requires response or resolution' },
  APPROVAL: { label: 'Approval', color: 'var(--green)',   bg: 'rgba(74,222,128,.08)', icon: '✅', description: 'Approve or reject the task' },
  BLOCKER:  { label: 'Blocker',  color: 'var(--rose)',    bg: 'rgba(244,63,94,.08)',  icon: '🚫', description: 'Flags an issue blocking progress' },
};

// ── Mention parser ────────────────────────────────────────────
// Extracts @username mentions from comment body.

export function extractMentions(body: string): string[] {
  const matches = body.match(/@[\w.-]+/g) ?? [];
  return [...new Set(matches.map(m => m.slice(1)))];
}
