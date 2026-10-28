// ============================================================
// OPSYN TASKS API MODULE — Phase 5 Full Workflow Engine
// Tasks, Comments, Dependencies, Audit, Pipeline, Workflow
// ============================================================

import apiClient from './client';
import type {
  Task,
  TaskPriority,
  TaskStatus,
  TaskBoard,
  TaskStatusBoard,
  TaskComment,
  TaskDependency,
  TaskAuditEntry,
  Pipeline,
  Stage,
  AutomationRule,
  CreateTaskRequest,
  AddCommentRequest,
  TransitionRequest,
  APIResponse,
  PaginatedResponse,
} from '@shared';

// ── Extended task types ───────────────────────────────────────

export interface TaskWorkflowPayload {
  task_scope: 'internal' | 'external';
  title: string;
  // description and deadline are Optional[str] = None on the backend
  // (CreateTaskRequest in tasks/router.py). Declaring them required here
  // forced callers to invent values the API never asked for.
  description?: string;
  deadline?: string;
  priority?: TaskPriority;
  status?: TaskStatus;
  assignee_user_id?: string | null;
  department_id?: string | null;
  tags?: string[];
  estimated_hours?: number | null;
  source_app?: string | null;
  archive_refs?: string[];
}

export interface ExternalTaskResponse {
  task: Task;
  project: { id: string; ticket_number: string; name: string; auto_generated: boolean };
}

export interface DeptStaffMember {
  user_id: string;
  first_name: string;
  last_name: string;
  full_name: string;
  staff_code: string;
  job_title: string | null;
  active_task_count: number;
  overdue_task_count: number;
}

export interface ArchiveRef {
  id: string;
  type: 'task' | 'project';
  ticket_number: string | null;
  title: string;
  pipeline_stage: string | null;
  url: string;
  created_at: string | null;
}

export interface AssignmentAnalyticsRow {
  user_id: string;
  full_name: string;
  assignments_received: number;
  assignments_forwarded: number;
  tasks_completed: number;
  avg_completion_days: number;
}

export interface DepartmentAnalyticsRow {
  department_id: string;
  department_name: string;
  tasks_received: number;
  tasks_completed: number;
  tasks_pushed_back: number;
  avg_days_in_dept: number;
}

export interface ArchiveSearchResult {
  id: string;
  type: 'task' | 'project';
  ticket_number: string;
  title: string;
  archived_at: string | null;
  department_id: string | null;
}

export interface PipelineHistoryStage {
  id: string;
  dept: { id: string; name: string | null };
  routing_order: number;
  entered_at: string | null;
  exited_at: string | null;
  exit_reason: string | null;
  is_current: boolean;
  assigned_to_user_id: string | null;
}

export interface TimelineEvent {
  id: string;
  type: 'comment' | 'state_change' | 'assignment' | 'push_back';
  subtype: string;
  actor: Record<string, string>;
  body: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

// ── Tasks ─────────────────────────────────────────────────────

export const tasksApi = {
  getBoard: (params?: { dept_id?: string; assignee_id?: string }) =>
    apiClient.get<APIResponse<TaskBoard>>('/tasks/board', { params }).then(r => r.data.data),

  getStatusBoard: (params?: { dept_id?: string; assignee_id?: string }) =>
    apiClient.get<APIResponse<TaskStatusBoard>>('/tasks/status-board', { params }).then(r => r.data.data),

  getMyTasks: () =>
    apiClient.get<APIResponse<Task[]>>('/tasks/my').then(r => r.data.data),

  list: (params?: Record<string, unknown>) =>
    apiClient.get<APIResponse<PaginatedResponse<Task>>>('/tasks', { params }).then(r => r.data.data),

  listDeleted: (params?: { page?: number; size?: number }) =>
    apiClient.get<APIResponse<PaginatedResponse<Task>>>('/tasks/deleted', { params }).then(r => r.data.data),

  get: (id: string) =>
    apiClient
      .get<APIResponse<Task & { comments: TaskComment[]; dependencies: TaskDependency[] }>>(`/tasks/${id}`)
      .then(r => r.data.data),

  create: (payload: TaskWorkflowPayload) =>
    apiClient.post<APIResponse<Task | ExternalTaskResponse>>('/tasks', payload).then(r => r.data.data),

  createFromApp: (sourceApp: string, payload: TaskWorkflowPayload) =>
    apiClient
      .post<APIResponse<ExternalTaskResponse & { source_app: string }>>(`/tasks/from-app/${sourceApp}`, payload)
      .then(r => r.data.data),

  update: (id: string, payload: Partial<CreateTaskRequest>) =>
    apiClient.put<APIResponse<Task>>(`/tasks/${id}`, payload).then(r => r.data.data),

  updateStatus: (id: string, status: string) =>
    apiClient.patch<APIResponse<Task>>(`/tasks/${id}/status`, { status }).then(r => r.data.data),

  transition: (id: string, payload: TransitionRequest) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/transition`, payload).then(r => r.data.data),

  // Workflow action shortcuts
  start: (id: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/start`).then(r => r.data.data),

  submitReview: (id: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/submit-review`).then(r => r.data.data),

  block: (id: string, block_reason: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/block`, { block_reason }).then(r => r.data.data),

  unblock: (id: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/unblock`).then(r => r.data.data),

  done: (id: string) =>
    apiClient
      .post<APIResponse<{ requires_routing: boolean; task?: Task; next_stage?: object }>>(`/tasks/${id}/done`)
      .then(r => r.data.data),

  archive: (id: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/archive`).then(r => r.data.data),

  clone: (id: string, overrides?: Partial<CreateTaskRequest>) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/clone`, overrides ?? {}).then(r => r.data.data),

  // Phase 5: Assignment
  assign: (id: string, assignee_user_id: string, note?: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/assign`, { assignee_user_id, note }).then(r => r.data.data),

  reassign: (id: string, to_user_id: string, reason?: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/reassign`, { to_user_id, reason }).then(r => r.data.data),

  // Phase 11: Workflow control
  forward: (id: string, to_user_id: string, note?: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/forward`, { to_user_id, note }).then(r => r.data.data),

  pushBack: (id: string, reason: string, to_user_id?: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/push-back`, { reason, to_user_id }).then(r => r.data.data),

  forwardDept: (id: string, to_dept_id: string, note?: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/forward-dept`, { to_dept_id, note }).then(r => r.data.data),

  returnDept: (id: string, reason: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/return-dept`, { reason }).then(r => r.data.data),

  escalate: (id: string, note: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/escalate`, { note }).then(r => r.data.data),

  // Phase 8: Dual approval
  markDone: (id: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/mark-done`).then(r => r.data.data),

  approveDone: (id: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/approve-done`).then(r => r.data.data),

  rejectDone: (id: string, reason: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/reject-done`, { reason }).then(r => r.data.data),

  // Phase 12: Soft-delete / restore / purge
  softDelete: (id: string, reason: string) =>
    apiClient.delete(`/tasks/${id}`, { data: { reason } }).then(r => r.data),

  restore: (id: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/restore`).then(r => r.data.data),

  purge: (id: string) =>
    apiClient.delete(`/tasks/${id}/purge`).then(r => r.data),

  // E.2.2: Reopen an archived task
  reopen: (id: string) =>
    apiClient.post<APIResponse<Task>>(`/tasks/${id}/reopen`).then(r => r.data.data),

  // Phase 7: Pipeline endpoints
  getPipelineBoard: (stage?: string, scope?: string, view?: string) =>
    apiClient.get<APIResponse<Record<string, Task[]>>>('/tasks/pipeline', { params: { stage, scope, view } }).then(r => r.data.data),

  getPipelineHistory: (id: string) =>
    apiClient
      .get<APIResponse<{ stages: PipelineHistoryStage[] }>>(`/tasks/${id}/pipeline-history`)
      .then(r => r.data.data),

  // Phase 10: Timeline
  getTimeline: (id: string) =>
    apiClient.get<APIResponse<TimelineEvent[]>>(`/tasks/${id}/timeline`).then(r => r.data.data),

  // Phase 9: Archive search
  searchArchive: (q: string, limit?: number) =>
    apiClient
      .get<APIResponse<ArchiveSearchResult[]>>('/tasks/archive/search', { params: { q, limit } })
      .then(r => r.data.data),

  // Phase 3.2: Department staff for task assignment
  getDeptStaff: (search?: string, size?: number) =>
    apiClient
      .get<APIResponse<DeptStaffMember[]>>('/tasks/staff/department', { params: { search, size } })
      .then(r => r.data.data),

  // Phase 5.5: Department inbox
  getDeptInbox: () =>
    apiClient
      .get<APIResponse<{ items: Task[]; total: number }>>('/tasks/department-inbox')
      .then(r => r.data.data),

  // H.1.1: Archive cross-references for a task
  getArchiveRefs: (taskId: string) =>
    apiClient
      .get<APIResponse<ArchiveRef[]>>(`/tasks/${taskId}/archive-references`)
      .then(r => r.data.data),

  // F.2.1: Assignment analytics
  getAssignmentAnalytics: (params?: { from_date?: string; to_date?: string; department_id?: string }) =>
    apiClient
      .get<APIResponse<AssignmentAnalyticsRow[]>>('/tasks/analytics/assignments', { params })
      .then(r => r.data.data),

  // F.2.2: Department analytics
  getDepartmentAnalytics: (params?: { from_date?: string; to_date?: string }) =>
    apiClient
      .get<APIResponse<DepartmentAnalyticsRow[]>>('/tasks/analytics/departments', { params })
      .then(r => r.data.data),
};

// ── Comments ──────────────────────────────────────────────────

export const taskCommentsApi = {
  list: (taskId: string) =>
    apiClient.get<APIResponse<TaskComment[]>>(`/tasks/${taskId}/comments`).then(r => r.data.data),

  add: (taskId: string, payload: AddCommentRequest) =>
    apiClient.post<APIResponse<TaskComment>>(`/tasks/${taskId}/comments`, payload).then(r => r.data.data),

  reply: (taskId: string, parentId: string, payload: AddCommentRequest) =>
    apiClient
      .post<APIResponse<TaskComment>>(`/tasks/${taskId}/comments/${parentId}/replies`, payload)
      .then(r => r.data.data),

  resolve: (taskId: string, commentId: string) =>
    apiClient
      .patch<APIResponse<TaskComment>>(`/tasks/${taskId}/comments/${commentId}/resolve`, {})
      .then(r => r.data.data),

  approve: (taskId: string, commentId: string) =>
    apiClient
      .patch<APIResponse<TaskComment>>(`/tasks/${taskId}/comments/${commentId}/approve`, {})
      .then(r => r.data.data),

  reject: (taskId: string, commentId: string) =>
    apiClient
      .patch<APIResponse<TaskComment>>(`/tasks/${taskId}/comments/${commentId}/reject`, {})
      .then(r => r.data.data),

  addPlain: (taskId: string, body: string) =>
    apiClient
      .post<APIResponse<TaskComment>>(`/tasks/${taskId}/comments`, { body, type: 'NORMAL' })
      .then(r => r.data.data),
};

// ── Dependencies ──────────────────────────────────────────────

export const taskDepsApi = {
  list: (taskId: string) =>
    apiClient.get<APIResponse<TaskDependency[]>>(`/tasks/${taskId}/dependencies`).then(r => r.data.data),

  add: (taskId: string, dependsOnTaskId: string) =>
    apiClient
      .post<APIResponse<TaskDependency>>(`/tasks/${taskId}/dependencies`, { depends_on_task_id: dependsOnTaskId })
      .then(r => r.data.data),

  remove: (taskId: string, dependencyId: string) =>
    apiClient.delete(`/tasks/${taskId}/dependencies/${dependencyId}`).then(r => r.data),
};

// ── Pipelines ─────────────────────────────────────────────────

export const pipelinesApi = {
  list: (params?: { dept_id?: string; is_active?: boolean }) =>
    apiClient.get<APIResponse<Pipeline[]>>('/pipelines', { params }).then(r => r.data.data),

  get: (id: string) =>
    apiClient.get<APIResponse<Pipeline>>(`/pipelines/${id}`).then(r => r.data.data),

  create: (payload: { name: string; description?: string; department_id?: string }) =>
    apiClient.post<APIResponse<Pipeline>>('/pipelines', payload).then(r => r.data.data),

  update: (id: string, payload: Partial<Pipeline>) =>
    apiClient.put<APIResponse<Pipeline>>(`/pipelines/${id}`, payload).then(r => r.data.data),

  delete: (id: string) =>
    apiClient.delete(`/pipelines/${id}`).then(r => r.data),
};

// ── Stages ────────────────────────────────────────────────────

export const stagesApi = {
  list: (pipelineId: string) =>
    apiClient.get<APIResponse<Stage[]>>(`/pipelines/${pipelineId}/stages`).then(r => r.data.data),

  create: (pipelineId: string, payload: Omit<Stage, 'id' | 'pipeline_id' | 'created_at'>) =>
    apiClient.post<APIResponse<Stage>>(`/pipelines/${pipelineId}/stages`, payload).then(r => r.data.data),

  update: (pipelineId: string, stageId: string, payload: Partial<Stage>) =>
    apiClient.put<APIResponse<Stage>>(`/pipelines/${pipelineId}/stages/${stageId}`, payload).then(r => r.data.data),

  delete: (pipelineId: string, stageId: string) =>
    apiClient.delete(`/pipelines/${pipelineId}/stages/${stageId}`).then(r => r.data),
};

// ── Automation Rules ──────────────────────────────────────────

export const automationApi = {
  list: (pipelineId?: string) =>
    apiClient.get<APIResponse<AutomationRule[]>>('/automation-rules', { params: { pipeline_id: pipelineId } }).then(r => r.data.data),

  create: (payload: Omit<AutomationRule, 'id' | 'created_at'>) =>
    apiClient.post<APIResponse<AutomationRule>>('/automation-rules', payload).then(r => r.data.data),

  update: (id: string, payload: Partial<AutomationRule>) =>
    apiClient.put<APIResponse<AutomationRule>>(`/automation-rules/${id}`, payload).then(r => r.data.data),

  delete: (id: string) =>
    apiClient.delete(`/automation-rules/${id}`).then(r => r.data),
};

// ── Task Audit Log ────────────────────────────────────────────

export const taskAuditApi = {
  list: (taskId: string) =>
    apiClient.get<APIResponse<TaskAuditEntry[]>>(`/tasks/${taskId}/audit`).then(r => r.data.data),
};
