// ============================================================
// OPSYN TASK DETAIL — the task popup (GlassModal workspace)
// • 7-state pipeline stepper with canMove() validation
// • All transitions via explicit buttons (no keyword triggers)
// • Comments are pure work logs (NORMAL + ACTION types only)
// • Block / Done / routing actions open nested glass dialogs, rendered
//   inside this popup's floating tree so Escape and outside-clicks close
//   only the top-most dialog
// • ActivityTimeline unified feed on the Overview tab
// Blueprint §2.2, §4, §15.2
// ============================================================

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle, Archive, ArrowLeft, ArrowRightLeft, Ban, Building2, Check, CheckCircle2, Copy, CornerUpLeft,
  Link2, Megaphone, MessageSquare, Play, RotateCcw, Send, Trash2, Undo2, X, Zap,
} from 'lucide-react';
import { tasksApi, taskCommentsApi, taskAuditApi } from '../../../api/tasks.api';
import { useUIStore } from '../../../store/ui.store';
import { useAuthStore } from '../../../store/auth.store';
import type { AuthState } from '../../../store/auth.store';
import { usePermissions } from '../../../hooks/usePermissions';
import {
  PIPELINE_FLOW,
  STATE_LABELS,
  canMove,
  getBackwardMoves,
  stateFlowIndex,
} from '../../../lib/taskStateMachine';
import {
  hasUnresolvedActionComments,
  extractMentions,
} from '../../../lib/commentWorkflow';
import { BlockReasonModal }  from './BlockReasonModal';
import { MarkDoneModal }     from './MarkDoneModal';
import { PushBackModal }     from './PushBackModal';
import { ForwardModal }      from './ForwardModal';
import { ForwardDeptModal }  from './ForwardDeptModal';
import { EscalateModal }     from './EscalateModal';
import { ReturnDeptModal }   from './ReturnDeptModal';
import { AdminDeleteModal }  from './AdminDeleteModal';
import { ActivityTimeline } from '../../../components/timeline';
import { ErrorBoundary }   from '../../../components/ErrorBoundary';
import { GlassModal } from '../../../components/glass';
import { Badge, Button, StateBadge, Tabs, Textarea, type BadgeTone } from '../../../components/ui';
import type { ApiError } from '../../../api/client';
import type {
  Task,
  TaskComment,
  TaskAuditEntry,
  TaskStatus,
  CommentType,
  TaskDependency,
  TransitionRequest,
  AddCommentRequest,
} from '@shared';
import s from './TaskDetail.module.css';

// ── Constants ────────────────────────────────────────────────

const PRIORITY_TONE: Record<string, BadgeTone> = {
  critical: 'critical', high: 'high', medium: 'info', low: 'neutral',
};

/** Workflow state → token (the same colours as StateBadge dots) */
const STATE_VAR: Record<TaskStatus, string> = {
  new: 'var(--state-new)', assigned: 'var(--state-progress)', in_progress: 'var(--state-progress)',
  review: 'var(--state-review)', blocked: 'var(--state-blocked)', done: 'var(--state-done)', archived: 'var(--state-archived)',
};

type Tab = 'Overview' | 'Comments' | 'Dependencies' | 'History';

const when = (iso: string, withYear = false) => new Date(iso).toLocaleString('en-GB', {
  day: '2-digit', month: 'short', ...(withYear ? { year: 'numeric' as const } : {}), hour: '2-digit', minute: '2-digit',
});

// ── Sub-components ───────────────────────────────────────────

function Avatar({ name, size = 28 }: { name: string; size?: number }) {
  const initials = name.split(' ').map(w => w[0] ?? '').slice(0, 2).join('').toUpperCase();
  return (
    <span className={s.avatar} style={{ width: size, height: size, fontSize: Math.round(size * 0.38) }} aria-hidden="true">
      {initials}
    </span>
  );
}

// ── Pipeline Stepper ─────────────────────────────────────────

function PipelineStepper({ status, isPending }: { status: TaskStatus; isPending: boolean }) {
  const currentIdx = stateFlowIndex(status);
  const isBlocked = status === 'blocked';

  return (
    <section aria-label="Pipeline">
      <ol className={s.stepper} aria-busy={isPending || undefined}>
        {PIPELINE_FLOW.map((stage, i) => {
          const idx = stateFlowIndex(stage);
          const state = stage === status ? 'current' : !isBlocked && idx < currentIdx ? 'past' : 'future';
          return (
            <li
              key={stage}
              className={s.step}
              data-state={state}
              aria-current={state === 'current' ? 'step' : undefined}
              style={{ ['--step-color' as string]: STATE_VAR[stage] }}
            >
              <span className={s.dot} aria-hidden="true">{state === 'past' ? <Check size={14} /> : i + 1}</span>
              <span className={s.stepLabel}>
                {STATE_LABELS[stage]}
                {state === 'past' && <span className="sr-only"> (complete)</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

// ── Action Buttons ────────────────────────────────────────────
// Explicit transitions — replaces comment-keyword triggers. A move the
// state machine refuses stays visible but disabled, with the reason.

function ActionButtons({
  status, task, dependencies, unresolvedActions, user, isPending, canApprove, onMove,
}: {
  status:            TaskStatus;
  task:              Task;
  dependencies:      TaskDependency[];
  unresolvedActions: boolean;
  user:              AuthState['user'];
  isPending:         boolean;
  canApprove:        boolean;
  onMove:            (to: TaskStatus) => void;
}) {
  if (!user || status === 'archived') return null;

  const checkMove = (to: TaskStatus) =>
    canMove({ task: { ...task, dependencies }, fromStatus: status, toStatus: to, user, hasUnresolvedActions: unresolvedActions });

  // Why the main forward move is refused — shown as text, not only a tooltip
  const blockedReasons: string[] = [];
  const btn = (
    to: TaskStatus,
    label: string,
    variant: 'primary' | 'secondary' | 'danger',
    icon: React.ReactNode,
    key: string = to,
  ) => {
    const result = checkMove(to);
    if (!result.allowed && variant === 'primary' && result.reason) blockedReasons.push(`${label}: ${result.reason}`);
    return (
      <Button
        key={key}
        variant={variant}
        size="sm"
        leftIcon={icon}
        onClick={() => result.allowed && !isPending && onMove(to)}
        disabled={!result.allowed || isPending}
        title={!result.allowed ? (result.reason ?? 'Not allowed') : undefined}
      >
        {label}
      </Button>
    );
  };

  const buttons = (
    <div className={s.actions} role="group" aria-label="Move task">
      {(status === 'new' || status === 'assigned') && btn('in_progress', 'Start work', 'primary', <Play size={14} aria-hidden="true" />)}
      {status === 'in_progress' && btn('review', 'Submit for review', 'primary', <Send size={14} aria-hidden="true" />)}
      {status === 'review' && canApprove && btn('done', 'Mark as done', 'primary', <CheckCircle2 size={14} aria-hidden="true" />)}
      {status === 'review' && canApprove && btn('in_progress', 'Reject', 'danger', <X size={14} aria-hidden="true" />, 'reject')}
      {status === 'blocked' && btn('in_progress', 'Resume work', 'primary', <Play size={14} aria-hidden="true" />)}
      {status === 'done' && canApprove && btn('archived', 'Archive', 'secondary', <Archive size={14} aria-hidden="true" />)}
      {/* 'archived' is already excluded by the early return above */}
      {status !== 'blocked' && status !== 'done' && btn('blocked', 'Mark as blocked', 'danger', <Ban size={14} aria-hidden="true" />)}
      {getBackwardMoves(status).map(to =>
        btn(to, `Back to ${STATE_LABELS[to].toLowerCase()}`, 'secondary', <ArrowLeft size={14} aria-hidden="true" />, `back-${to}`))}
    </div>
  );

  return (
    <>
      {buttons}
      {blockedReasons.map(r => <p key={r} className={s.actionHint}>{r}</p>)}
    </>
  );
}

// ── Comment Thread ───────────────────────────────────────────

function CommentItem({
  comment, onReply, onResolve, canResolve,
}: {
  comment:    TaskComment;
  onReply:    (parentId: string) => void;
  onResolve:  (commentId: string) => void;
  canResolve: boolean;
}) {
  if (comment.type === 'SYSTEM') {
    return (
      <li className={s.system}>
        <span>{comment.body}</span>
        <time dateTime={comment.created_at} style={{ marginLeft: 'auto' }}>
          {new Date(comment.created_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
        </time>
      </li>
    );
  }

  const isAction = comment.type === 'ACTION';
  return (
    <li className={s.comment} data-type={comment.type ?? 'NORMAL'} data-resolved={comment.is_resolved || undefined}>
      <div className={s.commentHead}>
        <Avatar name={comment.author.full_name} size={22} />
        <span className={s.commentAuthor}>{comment.author.full_name}</span>
        {isAction && (
          <Badge tone={comment.is_resolved ? 'ok' : 'warning'} size="xs">
            {comment.is_resolved ? 'Action · resolved' : 'Action needed'}
          </Badge>
        )}
        <time className={s.commentTime} dateTime={comment.created_at}>{when(comment.created_at)}</time>
      </div>
      <p className={s.commentBody}>{comment.body}</p>
      {comment.mentions && comment.mentions.length > 0 && (
        <div className={s.mentions}>{comment.mentions.map(m => <span key={m} className={s.mention}>@{m}</span>)}</div>
      )}
      <div className={s.commentActions}>
        {isAction && !comment.is_resolved && canResolve && (
          <Button variant="secondary" size="xs" leftIcon={<Check size={12} aria-hidden="true" />} onClick={() => onResolve(comment.id)}>
            Mark resolved
          </Button>
        )}
        <Button variant="ghost" size="xs" leftIcon={<CornerUpLeft size={12} aria-hidden="true" />} onClick={() => onReply(comment.id)}>
          Reply
        </Button>
      </div>
      {comment.replies && comment.replies.length > 0 && (
        <ol className={s.replies} aria-label="Replies">
          {comment.replies.map(reply => (
            <li key={reply.id}>
              <div className={s.commentHead}>
                <Avatar name={reply.author.full_name} size={18} />
                <span className={s.commentAuthor}>{reply.author.full_name}</span>
                <time className={s.commentTime} dateTime={reply.created_at}>{when(reply.created_at)}</time>
              </div>
              <p className={s.commentBody}>{reply.body}</p>
            </li>
          ))}
        </ol>
      )}
    </li>
  );
}

// ── Dependency Panel ─────────────────────────────────────────

function DependencyPanel({ dependencies }: { dependencies: TaskDependency[] }) {
  if (dependencies.length === 0) return <p className={s.empty}>No blocking dependencies.</p>;
  const pending = dependencies.some(d => d.depends_on_task?.status !== 'done');
  return (
    <div className={s.main}>
      <ul className={s.list}>
        {dependencies.map(dep => {
          const t = dep.depends_on_task;
          const done = t?.status === 'done';
          return (
            <li key={dep.id} className={s.dep}>
              <span className={s.depText}>
                <span className={s.depTitle}>{t?.title ?? dep.depends_on_task_id}</span>
                <span className={s.depMeta} style={{ display: 'block' }}>
                  {t?.assignee ? `${t.assignee.full_name} · ` : ''}{t ? STATE_LABELS[t.status] : 'Status unknown'}
                </span>
              </span>
              <Badge tone={done ? 'ok' : 'critical'} size="xs">{done ? 'Done' : 'Pending'}</Badge>
            </li>
          );
        })}
      </ul>
      {pending && (
        <p className={s.banner} data-tone="critical">
          <AlertTriangle size={16} aria-hidden="true" />
          <span className={s.bannerBody}>This task can't start until every dependency is done.</span>
        </p>
      )}
    </div>
  );
}

// ── History Tab ──────────────────────────────────────────────

function HistoryPanel({ entries }: { entries: TaskAuditEntry[] }) {
  if (entries.length === 0) return <p className={s.empty}>No history recorded yet.</p>;
  return (
    <ol className={s.list} style={{ gap: 0 }}>
      {entries.map(entry => (
        <li key={entry.id} className={s.history}>
          <span className={s.historyDot} style={{ background: entry.to_status ? STATE_VAR[entry.to_status] : 'var(--text-disabled)' }} aria-hidden="true" />
          <div>
            <p>
              {entry.actor && <strong>{entry.actor.full_name} </strong>}
              {entry.from_status && entry.to_status && (
                <>moved {STATE_LABELS[entry.from_status]} → {STATE_LABELS[entry.to_status]}</>
              )}
              {entry.note && <span style={{ color: 'var(--text-secondary)' }}> — {entry.note}</span>}
            </p>
            <p className={s.historyMeta}>
              <span>{entry.trigger_type}</span>
              <time dateTime={entry.created_at}>{when(entry.created_at, true)}</time>
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

// ── Main Modal ───────────────────────────────────────────────

interface Props {
  task:    Task | null;
  onClose: () => void;
}

export default function TaskDetailModal({ task: taskProp, onClose }: Props) {
  // Keep the last task on screen while the popup animates closed
  const [lastTask, setLastTask] = useState<Task | null>(taskProp);
  if (taskProp && taskProp !== lastTask) setLastTask(taskProp);
  const task = taskProp ?? lastTask;

  const [activeTab,       setActiveTab]      = useState<Tab>('Overview');
  const [localStatus,     setLocalStatus]    = useState<TaskStatus>(task?.status ?? 'new');
  const [commentBody,     setCommentBody]    = useState('');
  const [commentType,     setCommentType]    = useState<CommentType>('NORMAL');
  const [replyingTo,      setReplyingTo]     = useState<string | null>(null);
  const [transitionError, setTransitionError] = useState<string | null>(null);
  const [showBlockModal,       setShowBlockModal]       = useState(false);
  const [showDoneModal,        setShowDoneModal]        = useState(false);
  // Workflow routing modals (Corrective Plan A + B)
  const [showPushBackModal,    setShowPushBackModal]    = useState(false);
  const [showForwardModal,     setShowForwardModal]     = useState(false);
  const [showForwardDeptModal, setShowForwardDeptModal] = useState(false);
  const [showEscalateModal,    setShowEscalateModal]    = useState(false);
  const [showReturnDeptModal,  setShowReturnDeptModal]  = useState(false);
  const [showAdminDeleteModal, setShowAdminDeleteModal] = useState(false);

  const qc                    = useQueryClient();
  const { addToast }          = useUIStore();
  const { user, roleLevel }   = useAuthStore();
  const perms                 = usePermissions();

  useEffect(() => {
    // localStatus is optimistic: it moves ahead of the server during a
    // // transition and re-syncs when the task prop catches up.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (task?.status) setLocalStatus(task.status);
  }, [task?.status]);

  const { data: detail } = useQuery({
    queryKey: ['tasks', task?.id],
    queryFn:  () => tasksApi.get(task!.id),
    enabled:  !!task?.id,
    staleTime: 30 * 1000,
  });

  const comments:          TaskComment[]    = (detail as any)?.comments ?? [];
  const dependencies:      TaskDependency[] = (detail as any)?.dependencies ?? [];
  const unresolvedActions                   = hasUnresolvedActionComments(comments);

  const { data: auditEntries = [] } = useQuery({
    queryKey: ['tasks', task?.id, 'audit'],
    queryFn:  () => taskAuditApi.list(task!.id),
    enabled:  !!task?.id && activeTab === 'History',
    staleTime: 30 * 1000,
  });

  // H.1.2: Archive cross-references
  const { data: archiveRefs = [] } = useQuery({
    queryKey: ['tasks', task?.id, 'archive-refs'],
    queryFn:  () => tasksApi.getArchiveRefs(task!.id),
    enabled:  !!task?.id,
    staleTime: 60 * 1000,
  });

  // ── Transition mutation ──────────────────────────────────
  const doTransition = useMutation({
    mutationFn: (payload: TransitionRequest) => tasksApi.transition(task!.id, payload),
    onSuccess: async (_, payload) => {
      setLocalStatus(payload.to_status);
      setTransitionError(null);
      setShowBlockModal(false);
      setShowDoneModal(false);
      const fresh = await tasksApi.get(task!.id);
      qc.setQueryData(['tasks', task!.id], fresh);
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
      qc.invalidateQueries({ queryKey: ['tasks', task!.id, 'audit'] });
      addToast({ type: 'success', title: `Task moved to ${STATE_LABELS[payload.to_status]}` });
    },
    onError: (err: ApiError) => {
      setShowBlockModal(false);
      setShowDoneModal(false);
      const msg = err?.response?.data?.detail ?? 'Transition failed. Check validation rules.';
      setTransitionError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    },
  });

  // ── Comment mutations ────────────────────────────────────
  const postComment = useMutation({
    mutationFn: (payload: AddCommentRequest) => taskCommentsApi.add(task!.id, payload),
    onSuccess: async () => {
      const fresh = await tasksApi.get(task!.id);
      qc.setQueryData(['tasks', task!.id], fresh);
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
      setCommentBody('');
      setReplyingTo(null);
    },
    onError: () => addToast({ type: 'error', title: 'Failed to post comment' }),
  });

  const postReply = useMutation({
    mutationFn: ({ parentId, payload }: { parentId: string; payload: AddCommentRequest }) =>
      taskCommentsApi.reply(task!.id, parentId, payload),
    onSuccess: async () => {
      const fresh = await tasksApi.get(task!.id);
      qc.setQueryData(['tasks', task!.id], fresh);
      setCommentBody('');
      setReplyingTo(null);
    },
    onError: () => addToast({ type: 'error', title: 'Failed to post reply' }),
  });

  const resolveComment = useMutation({
    mutationFn: (commentId: string) => taskCommentsApi.resolve(task!.id, commentId),
    onSuccess: async () => {
      const fresh = await tasksApi.get(task!.id);
      qc.setQueryData(['tasks', task!.id], fresh);
    },
  });

  // ── Workflow routing mutations (Corrective Plan A) ────────
  const doPushBack = useMutation({
    mutationFn: ({ reason, toUserId }: { reason: string; toUserId?: string }) =>
      tasksApi.pushBack(task!.id, reason, toUserId),
    onSuccess: async () => {
      const fresh = await tasksApi.get(task!.id);
      qc.setQueryData(['tasks', task!.id], fresh);
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
      setShowPushBackModal(false);
      addToast({ type: 'success', title: 'Task returned. Reason logged and parties notified.' });
    },
    onError: (err: ApiError) => {
      setShowPushBackModal(false);
      setTransitionError(err?.response?.data?.detail ?? 'Push back failed.');
    },
  });

  const doForward = useMutation({
    mutationFn: ({ toUserId, note }: { toUserId: string; note?: string }) =>
      tasksApi.forward(task!.id, toUserId, note),
    onSuccess: async () => {
      const fresh = await tasksApi.get(task!.id);
      qc.setQueryData(['tasks', task!.id], fresh);
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
      setShowForwardModal(false);
      addToast({ type: 'success', title: 'Task forwarded. Assignment log updated.' });
    },
    onError: (err: ApiError) => {
      setShowForwardModal(false);
      setTransitionError(err?.response?.data?.detail ?? 'Forward failed.');
    },
  });

  const doForwardDept = useMutation({
    mutationFn: ({ toDeptId, note }: { toDeptId: string; note?: string }) =>
      tasksApi.forwardDept(task!.id, toDeptId, note),
    onSuccess: async () => {
      const fresh = await tasksApi.get(task!.id);
      qc.setQueryData(['tasks', task!.id], fresh);
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
      qc.invalidateQueries({ queryKey: ['dept-inbox'] });
      setShowForwardDeptModal(false);
      addToast({ type: 'success', title: 'Task routed to department. They have been notified.' });
    },
    onError: (err: ApiError) => {
      setShowForwardDeptModal(false);
      setTransitionError(err?.response?.data?.detail ?? 'Department forward failed.');
    },
  });

  const doEscalate = useMutation({
    mutationFn: (note: string) => tasksApi.escalate(task!.id, note),
    onSuccess: async () => {
      const fresh = await tasksApi.get(task!.id);
      qc.setQueryData(['tasks', task!.id], fresh);
      setShowEscalateModal(false);
      addToast({ type: 'success', title: 'Escalated. Department manager has been notified.' });
    },
    onError: (err: ApiError) => {
      setShowEscalateModal(false);
      setTransitionError(err?.response?.data?.detail ?? 'Escalation failed.');
    },
  });

  const doReturnDept = useMutation({
    mutationFn: (reason: string) => tasksApi.returnDept(task!.id, reason),
    onSuccess: async () => {
      const fresh = await tasksApi.get(task!.id);
      qc.setQueryData(['tasks', task!.id], fresh);
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
      qc.invalidateQueries({ queryKey: ['dept-inbox'] });
      setShowReturnDeptModal(false);
      addToast({ type: 'success', title: 'Task returned to previous department.' });
    },
    onError: (err: ApiError) => {
      setShowReturnDeptModal(false);
      setTransitionError(err?.response?.data?.detail ?? 'Return to department failed.');
    },
  });

  // ── Admin soft-delete mutation (Corrective Plan B) ────────
  const doSoftDelete = useMutation({
    mutationFn: (reason: string) => tasksApi.softDelete(task!.id, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
      qc.invalidateQueries({ queryKey: ['tasks'] });
      setShowAdminDeleteModal(false);
      addToast({
        type: 'success',
        title: `Task ${task?.ticket_number ?? ''} deleted. Department manager has been notified.`,
      });
      onClose();
    },
    onError: (err: ApiError) => {
      setShowAdminDeleteModal(false);
      setTransitionError(err?.response?.data?.detail ?? 'Deletion failed.');
    },
  });

  // ── Reopen archived task mutation (E.2.3) ────────────────
  const doReopen = useMutation({
    mutationFn: () => tasksApi.reopen(task!.id),
    onSuccess: async () => {
      const fresh = await tasksApi.get(task!.id);
      qc.setQueryData(['tasks', task!.id], fresh);
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
      addToast({ type: 'success', title: 'Task reopened and moved back to In Progress.' });
    },
    onError: (err: ApiError) => {
      setTransitionError(err?.response?.data?.detail ?? 'Reopen failed.');
    },
  });

  // ── Move handler (routes blocked/done through modals) ────
  function handleMove(toStatus: TaskStatus) {
    if (!task || !user) return;

    const result = canMove({
      task:                 { ...task, dependencies },
      fromStatus:           localStatus,
      toStatus,
      user,
      hasUnresolvedActions: unresolvedActions,
    });

    if (!result.allowed) {
      setTransitionError(result.reason ?? 'This transition is not allowed.');
      return;
    }

    setTransitionError(null);

    if (toStatus === 'blocked') { setShowBlockModal(true); return; }
    if (toStatus === 'done')    { setShowDoneModal(true);  return; }

    doTransition.mutate({ to_status: toStatus });
  }

  function handleBlockConfirm(reason: string) {
    doTransition.mutate({
      to_status: 'blocked',
      comment:   { body: reason, type: 'NORMAL' },
    });
  }

  function handleDoneConfirm() {
    doTransition.mutate({ to_status: 'done' });
  }

  // ── Comment submit (pure work log — no workflow parsing) ──
  function handleCommentSubmit() {
    if (!commentBody.trim()) return;

    const payload: AddCommentRequest = {
      body:      commentBody.trim(),
      type:      commentType,
      mentions:  extractMentions(commentBody),
      parent_id: replyingTo ?? undefined,
    };

    if (replyingTo) {
      postReply.mutate({ parentId: replyingTo, payload });
    } else {
      postComment.mutate(payload);
    }
  }

  if (!task) return null;

  const isArchived = localStatus === 'archived';
  const isMutating = doTransition.isPending || postComment.isPending || postReply.isPending;

  // ── Workflow routing visibility (Corrective Plan A + B) ──
  const td: any       = detail ?? task;
  const scope         = td?.task_scope;
  const isDeleted     = td?.is_deleted ?? false;
  const assigneeId    = td?.assignee_user_id ?? (task as any)?.assignee_user_id;
  const isAssignee    = !!user?.id && assigneeId === user.id;
  const canRoute      = !!user && !isArchived && !isDeleted;
  const showPushBack   = canRoute && (isAssignee || roleLevel >= 4);
  const showFwdStaff   = canRoute && scope === 'internal' && (isAssignee || roleLevel >= 3);
  const showFwdDept    = canRoute && scope === 'external' && (isAssignee || roleLevel >= 3);
  const showEscalate   = canRoute && isAssignee;
  const showReturnDept = canRoute && scope === 'external' && roleLevel >= 3;
  const showDelete     = canRoute && roleLevel >= 4;
  const anyRouting = showPushBack || showFwdStaff || showFwdDept || showEscalate || showReturnDept || showDelete;

  const hasBlockers = dependencies.some(d => d.depends_on_task?.status !== 'done');
  const commentCount = comments.filter(c => c.type !== 'SYSTEM').length;
  const people = [
    { label: 'Assignee', person: task.assignee },
    { label: 'Responsible', person: task.responsible_user },
  ].filter(r => r.person);

  const copyTicket = () => {
    navigator.clipboard?.writeText(task.ticket_number!).then(
      () => addToast({ type: 'success', title: 'Ticket number copied' }),
      () => undefined,
    );
  };

  return (
    <GlassModal
      open={!!taskProp}
      onClose={onClose}
      size="workspace"
      title={task.title}
      description={task.department?.name}
      eyebrow={task.ticket_number ? (
        <button type="button" className={s.ticket} onClick={copyTicket} aria-label={`Copy ticket number ${task.ticket_number}`}>
          {task.ticket_number} <Copy size={12} aria-hidden="true" />
        </button>
      ) : undefined}
      footer={
        <>
          {isArchived && (
            <Button
              variant="secondary"
              onClick={() => tasksApi.clone(task.id).then(() => {
                addToast({ type: 'success', title: 'Task cloned' });
                qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
                onClose();
              })}
            >
              Clone task
            </Button>
          )}
          <Button variant="secondary" onClick={onClose}>Close</Button>
        </>
      }
    >
      <div className={s.layout}>
        {/* ── The work ── */}
        <div className={s.main}>
          {!isArchived ? (
            <PipelineStepper status={localStatus} isPending={doTransition.isPending} />
          ) : (
            <div className={s.banner}>
              <Archive size={16} aria-hidden="true" />
              <span className={s.bannerBody}>This task is archived. Clone it to start a new instance.</span>
              {user && (roleLevel >= 4 || (task as any)?.created_by === user.id) && (
                <Button variant="secondary" size="xs" leftIcon={<RotateCcw size={12} aria-hidden="true" />}
                  onClick={() => doReopen.mutate()} loading={doReopen.isPending}>
                  Reopen task
                </Button>
              )}
            </div>
          )}

          {localStatus === 'blocked' && (
            <p className={s.banner} data-tone="critical">
              <Ban size={16} aria-hidden="true" />
              <span className={s.bannerBody}><strong>Blocked</strong>{td?.block_reason ? ` — ${td.block_reason}` : '. Resume work once the blocker is cleared.'}</span>
            </p>
          )}

          {user && !isArchived && (
            <ActionButtons
              status={localStatus}
              task={task}
              dependencies={dependencies}
              unresolvedActions={unresolvedActions}
              user={user}
              isPending={doTransition.isPending}
              canApprove={perms.canApproveTask}
              onMove={handleMove}
            />
          )}

          {transitionError && (
            <p className={s.banner} data-tone="critical" role="alert">
              <AlertTriangle size={16} aria-hidden="true" />
              <span className={s.bannerBody}>{transitionError}</span>
            </p>
          )}

          <Tabs
            label="Task details"
            value={activeTab}
            onChange={setActiveTab}
            idPrefix="task-detail"
            items={[
              { value: 'Overview', label: 'Overview' },
              { value: 'Comments', label: 'Comments', count: commentCount },
              { value: 'Dependencies', label: 'Dependencies', count: dependencies.length, tone: hasBlockers ? 'critical' : undefined },
              { value: 'History', label: 'History', count: auditEntries.length || undefined },
            ]}
          />

          <div role="tabpanel" id="task-detail-panel" aria-labelledby={`task-detail-tab-${activeTab}`} className={s.main}>
            {activeTab === 'Overview' && (
              <>
                {task.description && <p className={`${s.card} ${s.description}`}>{task.description}</p>}

                {dependencies.length > 0 && (
                  <button type="button" className={s.linkRow} onClick={() => setActiveTab('Dependencies')}>
                    <Link2 size={16} aria-hidden="true" />
                    {dependencies.length} dependenc{dependencies.length === 1 ? 'y' : 'ies'} —{' '}
                    {dependencies.filter(d => d.depends_on_task?.status === 'done').length} of {dependencies.length} done
                    <span className={s.linkHint}>View</span>
                  </button>
                )}

                {/* H.1.2: Archive cross-references */}
                {archiveRefs.length > 0 && (
                  <section>
                    <h3 className={s.sectionTitle}>Archive references</h3>
                    <ul className={s.refs}>
                      {(archiveRefs as any[]).map((ref: any) => (
                        <li key={ref.id} className={s.ref}>
                          {ref.ticket_number && <span className={s.mono}>{ref.ticket_number}</span>}
                          <span style={{ flex: 1 }}>{ref.title}</span>
                          {ref.pipeline_stage && <span className={s.mono}>{ref.pipeline_stage}</span>}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                {/* Unified activity feed */}
                <ErrorBoundary>
                  <ActivityTimeline entityType="task" entityId={task.id} canComment showFilter maxHeight={320} />
                </ErrorBoundary>
              </>
            )}

            {activeTab === 'Comments' && (
              <>
                {comments.length === 0 ? (
                  <p className={s.empty}>No comments yet. Start the work log.</p>
                ) : (
                  <ol className={s.comments}>
                    {comments.map(c => (
                      <CommentItem
                        key={c.id}
                        comment={c}
                        onReply={id => { setReplyingTo(id); setCommentBody(''); }}
                        onResolve={id => resolveComment.mutate(id)}
                        canResolve={perms.canResolveAction}
                      />
                    ))}
                  </ol>
                )}

                <div className={s.composer}>
                  {replyingTo && (
                    <div className={s.replying}>
                      <span><CornerUpLeft size={12} aria-hidden="true" /> Replying to a comment</span>
                      <Button variant="ghost" size="xs" onClick={() => setReplyingTo(null)}>Cancel reply</Button>
                    </div>
                  )}
                  <div className={s.typePicker} role="group" aria-label="Comment type">
                    {(['NORMAL', 'ACTION'] as CommentType[]).map(t => (
                      <button key={t} type="button" className={s.typeBtn} aria-pressed={commentType === t} onClick={() => setCommentType(t)}>
                        {t === 'ACTION'
                          ? <><Zap size={12} aria-hidden="true" /> Action needed</>
                          : <><MessageSquare size={12} aria-hidden="true" /> Work log</>}
                      </button>
                    ))}
                  </div>
                  <div className={s.composerRow}>
                    <Textarea
                      label={replyingTo ? 'Reply' : 'Comment'}
                      value={commentBody}
                      onChange={setCommentBody}
                      placeholder={commentType === 'ACTION'
                        ? 'What needs attention? @mention a colleague.'
                        : 'Work log entry — @mention a colleague.'}
                      rows={3}
                      style={{ marginBottom: 0 }}
                    />
                    <Button variant="primary" onClick={handleCommentSubmit} disabled={!commentBody.trim() || isMutating}
                      loading={postComment.isPending || postReply.isPending}>
                      Post
                    </Button>
                  </div>
                </div>
              </>
            )}

            {activeTab === 'Dependencies' && <DependencyPanel dependencies={dependencies} />}
            {activeTab === 'History' && <HistoryPanel entries={auditEntries as TaskAuditEntry[]} />}
          </div>
        </div>

        {/* ── The facts ── */}
        <aside className={s.side} aria-label="Task facts">
          <section className={s.card}>
            <dl className={s.facts}>
              <dt>Status</dt><dd><StateBadge state={localStatus} /></dd>
              <dt>Priority</dt><dd><Badge tone={PRIORITY_TONE[task.priority] ?? 'neutral'} size="sm">{task.priority}</Badge></dd>
              {task.deadline && (
                <>
                  <dt>Deadline</dt>
                  <dd><time dateTime={task.deadline}>{new Date(task.deadline).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}</time></dd>
                </>
              )}
              {hasBlockers && <><dt>Blockers</dt><dd><Badge tone="critical" size="sm">Has open dependencies</Badge></dd></>}
              {(task.tags ?? []).length > 0 && (
                <>
                  <dt>Tags</dt>
                  <dd className={s.tags}>{(task.tags ?? []).map(t => <span key={t} className={s.tag}>#{t}</span>)}</dd>
                </>
              )}
            </dl>
          </section>

          {people.length > 0 && (
            <section className={s.card}>
              <h3 className={s.sectionTitle}>People</h3>
              {people.map(({ label, person }) => person && (
                <div key={label} className={s.person}>
                  <Avatar name={person.full_name} />
                  <span className={s.personText}>
                    <span className={s.personRole}>{label}</span>
                    <span>{person.full_name}</span>
                    {person.job_title && <span className={s.personRole}>{person.job_title}</span>}
                  </span>
                </div>
              ))}
            </section>
          )}

          {anyRouting && (
            <section className={s.card}>
              <h3 className={s.sectionTitle}>Routing</h3>
              <div className={s.routing}>
                {showPushBack && (
                  <Button variant="secondary" size="sm" fullWidth leftIcon={<Undo2 size={14} aria-hidden="true" />} onClick={() => setShowPushBackModal(true)}>Push back</Button>
                )}
                {showFwdStaff && (
                  <Button variant="secondary" size="sm" fullWidth leftIcon={<ArrowRightLeft size={14} aria-hidden="true" />} onClick={() => setShowForwardModal(true)}>Forward to staff</Button>
                )}
                {showFwdDept && (
                  <Button variant="secondary" size="sm" fullWidth leftIcon={<Building2 size={14} aria-hidden="true" />} onClick={() => setShowForwardDeptModal(true)}>Forward to department</Button>
                )}
                {showEscalate && (
                  <Button variant="secondary" size="sm" fullWidth leftIcon={<Megaphone size={14} aria-hidden="true" />} onClick={() => setShowEscalateModal(true)}>Escalate to manager</Button>
                )}
                {showReturnDept && (
                  <Button variant="secondary" size="sm" fullWidth leftIcon={<CornerUpLeft size={14} aria-hidden="true" />} onClick={() => setShowReturnDeptModal(true)}>Return to department</Button>
                )}
                {showDelete && (
                  <Button variant="danger" size="sm" fullWidth leftIcon={<Trash2 size={14} aria-hidden="true" />} onClick={() => setShowAdminDeleteModal(true)}>Delete task</Button>
                )}
              </div>
            </section>
          )}
        </aside>
      </div>

      {/* ── Nested dialogs: inside this popup's floating tree ── */}
      {showBlockModal && (
        <BlockReasonModal onConfirm={handleBlockConfirm} onClose={() => setShowBlockModal(false)} isPending={doTransition.isPending} />
      )}
      {showDoneModal && (
        <MarkDoneModal taskTitle={task.title} onConfirm={handleDoneConfirm} onClose={() => setShowDoneModal(false)} isPending={doTransition.isPending} />
      )}
      {showPushBackModal && (
        <PushBackModal
          taskId={task.id}
          taskTitle={task.title}
          onConfirm={(reason, toUserId) => doPushBack.mutate({ reason, toUserId })}
          onClose={() => setShowPushBackModal(false)}
          isPending={doPushBack.isPending}
        />
      )}
      {showForwardModal && (
        <ForwardModal
          taskTitle={task.title}
          currentUserId={user?.id ?? ''}
          onConfirm={(toUserId, note) => doForward.mutate({ toUserId, note })}
          onClose={() => setShowForwardModal(false)}
          isPending={doForward.isPending}
        />
      )}
      {showForwardDeptModal && (
        <ForwardDeptModal
          taskTitle={task.title}
          currentDeptId={(detail as any)?.department_id ?? (task as any)?.department_id ?? ''}
          onConfirm={(toDeptId, note) => doForwardDept.mutate({ toDeptId, note })}
          onClose={() => setShowForwardDeptModal(false)}
          isPending={doForwardDept.isPending}
        />
      )}
      {showEscalateModal && (
        <EscalateModal taskTitle={task.title} onConfirm={note => doEscalate.mutate(note)} onClose={() => setShowEscalateModal(false)} isPending={doEscalate.isPending} />
      )}
      {showReturnDeptModal && (
        <ReturnDeptModal
          taskId={task.id}
          taskTitle={task.title}
          onConfirm={reason => doReturnDept.mutate(reason)}
          onClose={() => setShowReturnDeptModal(false)}
          isPending={doReturnDept.isPending}
        />
      )}
      {showAdminDeleteModal && (
        <AdminDeleteModal
          taskId={task.id}
          taskTitle={task.title}
          ticketNumber={task.ticket_number ?? null}
          deptName={(detail as any)?.department?.name ?? task.department?.name ?? null}
          onConfirm={reason => doSoftDelete.mutate(reason)}
          onClose={() => setShowAdminDeleteModal(false)}
          isPending={doSoftDelete.isPending}
        />
      )}
    </GlassModal>
  );
}
