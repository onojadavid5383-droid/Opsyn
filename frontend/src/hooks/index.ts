// ============================================================
// OPSYN CUSTOM HOOKS — All domain hooks
// useAuth · useStaff · useTasks · useOutage · useOrg
// useRoles · useOnboarding · useNotifications · useReports
// useDebounce · usePagination · useClickOutside
// ============================================================

import { useState, useEffect, useRef, useCallback, useLayoutEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/auth.store';
import { useUIStore } from '../store/ui.store';
import { useNotificationStore } from '../store/notification.store';
import { authApi, orgApi, rolesApi, outageApi, onboardingApi, notificationsApi, reportsApi, projectsApi } from '../api/index';
import { timelineApi } from '../api/timeline.api';
import type { AddCommentPayload, TimelineEntityType } from '../components/timeline/types';
import { staffApi } from '../api/staff.api';
import { tasksApi, taskCommentsApi, taskDepsApi, pipelinesApi, stagesApi, automationApi, taskAuditApi } from '../api/tasks.api';
import type { StaffListFilters } from '../api/staff.api';
import type { AddCommentRequest, TransitionRequest } from '@shared';
import { parseApiError } from '../utils/index';


// ══ useAuth ══════════════════════════════════════════════════
export function useAuth() {
  const { user, isAuth, clearAuth, setUser } = useAuthStore();
  const navigate = useNavigate();
  const { addToast } = useUIStore();

  const login = useCallback(async (email: string, password: string) => {
    const data = await authApi.login(email, password) as any;
    const token = data.access_token;

    const [, payloadB64] = token.split('.');
    const claims = JSON.parse(atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/')));

    setUser(
      {
        id:         claims.sub,
        username:   claims.username || email.split('@')[0],
        email,
        role: {
          id:             '',
          name:           claims.role || 'Staff',
          level:          claims.role_level || 1,
          is_system_role: false,
        },
        role_level: claims.role_level || 1,
        is_active:  true,
      },
      token,
      claims.tenant_id ?? null,
    );

    navigate('/dashboard', { replace: true });
  }, [navigate, setUser]);

  const logout = useCallback(async () => {
    try { await authApi.logout(); } catch { /* ignore */ }
    clearAuth();
    navigate('/login', { replace: true });
    addToast({ type: 'info', title: 'Signed out of Opsyn' });
  }, [clearAuth, navigate, addToast]);

  return { user, isAuth, login, logout };
}


// ══ useStaff ═════════════════════════════════════════════════
export function useStaffList(filters: StaffListFilters = {}) {
  return useQuery({
    queryKey: ['staff', 'list', filters],
    queryFn:  () => staffApi.list(filters),
    staleTime: 2 * 60 * 1000,
  });
}

export function useStaffDetail(id: string | undefined) {
  return useQuery({
    queryKey: ['staff', id],
    queryFn:  () => staffApi.get(id!),
    enabled:  !!id,
    staleTime: 5 * 60 * 1000,
  });
}

export function useCreateStaff() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: staffApi.create,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['staff'] });
      addToast({ type: 'success', title: 'Staff account created', message: 'Invite email dispatched — Powered by SlimTech' });
    },
    onError: (err) => {
      addToast({ type: 'error', title: 'Failed to create staff', message: parseApiError(err) });
    },
  });
}

export function useUpdateStaffStatus() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => staffApi.updateStatus(id, status as any),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['staff'] });
      addToast({ type: 'success', title: 'Staff status updated' });
    },
    onError: (err) => {
      addToast({ type: 'error', title: 'Status update failed', message: parseApiError(err) });
    },
  });
}


// ══ useTasks ═════════════════════════════════════════════════
export function useTaskBoard(params?: { dept_id?: string; assignee_id?: string }) {
  return useQuery({
    queryKey: ['tasks', 'board', params],
    queryFn:  () => tasksApi.getBoard(params),
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });
}

export function useMyTasks() {
  return useQuery({
    queryKey: ['tasks', 'my'],
    queryFn:  tasksApi.getMyTasks,
    staleTime: 30 * 1000,
  });
}

export function useCreateTask() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: tasksApi.create,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] });
      addToast({ type: 'success', title: 'Task created' });
    },
    onError: (err) => addToast({ type: 'error', title: 'Failed to create task', message: parseApiError(err) }),
  });
}

export function useUpdateTaskStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => tasksApi.updateStatus(id, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks'] }),
  });
}

export function useAddComment() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: ({ taskId, payload }: { taskId: string; payload: AddCommentRequest }) =>
      taskCommentsApi.add(taskId, payload),
    onSuccess: async (_, vars) => {
      const fresh = await tasksApi.get(vars.taskId);
      qc.setQueryData(['tasks', vars.taskId], fresh);
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
    },
    onError: (err) => addToast({ type: 'error', title: 'Failed to post comment', message: parseApiError(err) }),
  });
}

export function useReplyToComment() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: ({ taskId, parentId, payload }: { taskId: string; parentId: string; payload: AddCommentRequest }) =>
      taskCommentsApi.reply(taskId, parentId, payload),
    onSuccess: async (_, vars) => {
      const fresh = await tasksApi.get(vars.taskId);
      qc.setQueryData(['tasks', vars.taskId], fresh);
    },
    onError: (err) => addToast({ type: 'error', title: 'Failed to post reply', message: parseApiError(err) }),
  });
}

export function useResolveComment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId, commentId }: { taskId: string; commentId: string }) =>
      taskCommentsApi.resolve(taskId, commentId),
    onSuccess: async (_, vars) => {
      const fresh = await tasksApi.get(vars.taskId);
      qc.setQueryData(['tasks', vars.taskId], fresh);
    },
  });
}

export function useApproveComment() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: ({ taskId, commentId }: { taskId: string; commentId: string }) =>
      taskCommentsApi.approve(taskId, commentId),
    onSuccess: async (_, vars) => {
      const fresh = await tasksApi.get(vars.taskId);
      qc.setQueryData(['tasks', vars.taskId], fresh);
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
      addToast({ type: 'success', title: 'Task approved and moved to Done' });
    },
    onError: (err) => addToast({ type: 'error', title: 'Approval failed', message: parseApiError(err) }),
  });
}

export function useRejectComment() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: ({ taskId, commentId }: { taskId: string; commentId: string }) =>
      taskCommentsApi.reject(taskId, commentId),
    onSuccess: async (_, vars) => {
      const fresh = await tasksApi.get(vars.taskId);
      qc.setQueryData(['tasks', vars.taskId], fresh);
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
      addToast({ type: 'info', title: 'Task sent back to In Progress' });
    },
    onError: (err) => addToast({ type: 'error', title: 'Rejection failed', message: parseApiError(err) }),
  });
}

// ── useTaskTransition — validated status move ─────────────────
export function useTaskTransition() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: ({ taskId, payload }: { taskId: string; payload: TransitionRequest }) =>
      tasksApi.transition(taskId, payload),
    onSuccess: async (_, vars) => {
      const fresh = await tasksApi.get(vars.taskId);
      qc.setQueryData(['tasks', vars.taskId], fresh);
      qc.invalidateQueries({ queryKey: ['tasks', 'board'] });
      qc.invalidateQueries({ queryKey: ['tasks', vars.taskId, 'audit'] });
    },
    onError: (err) => addToast({ type: 'error', title: 'Transition failed', message: parseApiError(err) }),
  });
}

// ── useTaskDependencies ───────────────────────────────────────
export function useTaskDependencies(taskId: string | undefined) {
  return useQuery({
    queryKey: ['tasks', taskId, 'dependencies'],
    queryFn:  () => taskDepsApi.list(taskId!),
    enabled:  !!taskId,
    staleTime: 30 * 1000,
  });
}

export function useAddDependency() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: ({ taskId, dependsOnTaskId }: { taskId: string; dependsOnTaskId: string }) =>
      taskDepsApi.add(taskId, dependsOnTaskId),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['tasks', vars.taskId, 'dependencies'] });
      qc.invalidateQueries({ queryKey: ['tasks', vars.taskId] });
      addToast({ type: 'success', title: 'Dependency added' });
    },
    onError: (err) => addToast({ type: 'error', title: 'Failed to add dependency', message: parseApiError(err) }),
  });
}

export function useRemoveDependency() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: ({ taskId, dependencyId }: { taskId: string; dependencyId: string }) =>
      taskDepsApi.remove(taskId, dependencyId),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['tasks', vars.taskId, 'dependencies'] });
      addToast({ type: 'info', title: 'Dependency removed' });
    },
  });
}

// ── useTaskAuditLog ───────────────────────────────────────────
export function useTaskAuditLog(taskId: string | undefined) {
  return useQuery({
    queryKey: ['tasks', taskId, 'audit'],
    queryFn:  () => taskAuditApi.list(taskId!),
    enabled:  !!taskId,
    staleTime: 30 * 1000,
  });
}

// ── usePipelines ──────────────────────────────────────────────
export function usePipelines(params?: { dept_id?: string; is_active?: boolean }) {
  return useQuery({
    queryKey: ['pipelines', params],
    queryFn:  () => pipelinesApi.list(params),
    staleTime: 5 * 60 * 1000,
  });
}

export function useStages(pipelineId: string | undefined) {
  return useQuery({
    queryKey: ['pipelines', pipelineId, 'stages'],
    queryFn:  () => stagesApi.list(pipelineId!),
    enabled:  !!pipelineId,
    staleTime: 5 * 60 * 1000,
  });
}

// ── useAutomationRules ────────────────────────────────────────
export function useAutomationRules(pipelineId?: string) {
  return useQuery({
    queryKey: ['automation-rules', pipelineId],
    queryFn:  () => automationApi.list(pipelineId),
    staleTime: 2 * 60 * 1000,
  });
}


// ══ useOutage ════════════════════════════════════════════════
export function useLiveOutages() {
  return useQuery({
    queryKey: ['outages', 'live'],
    queryFn:  outageApi.getLive,
    staleTime: 30 * 1000,
    refetchInterval: 30 * 1000, // Poll every 30s
  });
}

export function useOutageList(params?: Parameters<typeof outageApi.list>[0]) {
  return useQuery({
    queryKey: ['outages', 'list', params],
    queryFn:  () => outageApi.list(params),
    staleTime: 30 * 1000,
    refetchInterval: 30 * 1000,
  });
}

export function useLogOutage() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: outageApi.log,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['outages'] });
      addToast({ type: 'warning', title: 'Outage logged', message: 'Incident recorded in Opsyn' });
    },
    onError: (err) => addToast({ type: 'error', title: 'Failed to log outage', message: parseApiError(err) }),
  });
}

export function useResolveOutage() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: (id: string) => outageApi.resolve(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['outages'] });
      addToast({ type: 'success', title: 'Outage resolved' });
    },
  });
}


// ══ useOrg ═══════════════════════════════════════════════════
export function useDepartments(inScope?: boolean) {
  return useQuery({
    queryKey: ['departments', inScope],
    queryFn:  () => orgApi.getDepartments(inScope),
    staleTime: 10 * 60 * 1000,
  });
}

export function useTeams(deptId?: string) {
  return useQuery({
    queryKey: ['teams', deptId],
    queryFn:  () => orgApi.getTeams(deptId),
    staleTime: 10 * 60 * 1000,
  });
}

export function useRegions() {
  return useQuery({
    queryKey: ['regions'],
    queryFn:  orgApi.getRegions,
    staleTime: 60 * 60 * 1000, // 1 hour
  });
}


// ══ useRoles ═════════════════════════════════════════════════
export function useRoles(assignable?: boolean) {
  return useQuery({
    queryKey: ['roles', assignable],
    queryFn:  () => rolesApi.getRoles(assignable),
    staleTime: 10 * 60 * 1000,
  });
}

export function useAssignRole() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: ({ roleId, userId }: { roleId: string; userId: string }) =>
      rolesApi.assignRole(roleId, userId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['staff'] });
      qc.invalidateQueries({ queryKey: ['roles'] });
      addToast({ type: 'success', title: 'Role assigned' });
    },
    onError: (err) => addToast({ type: 'error', title: 'Role assignment failed', message: parseApiError(err) }),
  });
}


// ══ useOnboarding ════════════════════════════════════════════
export function useOnboardingList(status?: string) {
  return useQuery({
    queryKey: ['onboarding', status],
    queryFn:  () => onboardingApi.list(status ? { status } : undefined),
    staleTime: 2 * 60 * 1000,
  });
}

export function useApproveOnboarding() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: (id: string) => onboardingApi.approve(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['onboarding'] });
      addToast({ type: 'success', title: 'Onboarding request approved', message: 'Account provisioned on Opsyn' });
    },
    onError: (err) => addToast({ type: 'error', title: 'Approval failed', message: parseApiError(err) }),
  });
}

export function useRejectOnboarding() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) => onboardingApi.reject(id, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['onboarding'] });
      addToast({ type: 'info', title: 'Request rejected' });
    },
  });
}

export function useSubmitOnboarding() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  return useMutation({
    mutationFn: onboardingApi.submit,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['onboarding'] });
      addToast({ type: 'success', title: 'Onboarding request submitted', message: 'Pending admin approval' });
    },
    onError: (err) => addToast({ type: 'error', title: 'Submission failed', message: parseApiError(err) }),
  });
}


// ══ useNotifications ═════════════════════════════════════════
export function useNotifications() {
  const { setNotifications } = useNotificationStore();
  const query = useQuery({
    queryKey: ['notifications'],
    queryFn:  notificationsApi.list,
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
  });

  // Sync server data into the notification store whenever it arrives
  useLayoutEffect(() => {
    if (!query.data) return;
    const items = Array.isArray(query.data) ? query.data : (query.data as any)?.items ?? [];
    setNotifications(items);
  }, [query.data, setNotifications]);

  return query;
}

export function useUnreadCount() {
  const { setUnreadCount } = useNotificationStore();
  const query = useQuery({
    queryKey: ['notifications', 'unread'],
    queryFn:  notificationsApi.getUnreadCount,
    staleTime: 30 * 1000,
    refetchInterval: 30 * 1000,
  });

  useLayoutEffect(() => {
    if (typeof query.data === 'number') setUnreadCount(query.data);
  }, [query.data, setUnreadCount]);

  return query;
}

export function useMarkRead() {
  const qc = useQueryClient();
  const { markReadOptimistic } = useNotificationStore();
  return useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onMutate: (id) => markReadOptimistic(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  });
}

export function useMarkAllRead() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();
  const { markAllReadOptimistic } = useNotificationStore();
  return useMutation({
    mutationFn: notificationsApi.markAllRead,
    onMutate: () => markAllReadOptimistic(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
    onError: (err) => {
      qc.invalidateQueries({ queryKey: ['notifications'] }); // revert optimistic on error
      addToast({ type: 'error', title: 'Failed to mark all read', message: parseApiError(err) });
    },
  });
}


// ══ useReports ═══════════════════════════════════════════════
export function useReportSummary(params?: { month?: string; year?: string }) {
  return useQuery({
    queryKey: ['reports', 'summary', params],
    queryFn:  () => reportsApi.getSummary(params),
    staleTime: 5 * 60 * 1000,
  });
}

export function useProjects(params?: Parameters<typeof projectsApi.list>[0]) {
  return useQuery({
    queryKey: ['projects', params],
    queryFn:  () => projectsApi.list(params),
    staleTime: 5 * 60 * 1000,
  });
}


// ══ useTimeline ══════════════════════════════════════════════

export function useTaskTimeline(taskId: string | undefined) {
  return useQuery({
    queryKey: ['timeline', 'task', taskId],
    queryFn:  () => timelineApi.getForTask(taskId!),
    enabled:  !!taskId,
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
  });
}

export function useProjectTimeline(projectId: string | undefined) {
  return useQuery({
    queryKey: ['timeline', 'project', projectId],
    queryFn:  () => timelineApi.getForProject(projectId!),
    enabled:  !!projectId,
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
  });
}

export function useOutageTimeline(outageId: string | undefined) {
  return useQuery({
    queryKey: ['timeline', 'outage', outageId],
    queryFn:  () => timelineApi.getForOutage(outageId!),
    enabled:  !!outageId,
    staleTime: 30 * 1000,
    refetchInterval: 30 * 1000, // Outages poll more frequently
  });
}

export function useOnboardingTimeline(requestId: string | undefined) {
  return useQuery({
    queryKey: ['timeline', 'onboarding', requestId],
    queryFn:  () => timelineApi.getForOnboarding(requestId!),
    enabled:  !!requestId,
    staleTime: 60 * 1000,
  });
}

export function useAddTimelineComment() {
  const qc = useQueryClient();
  const { addToast } = useUIStore();

  return useMutation({
    mutationFn: ({
      entityType,
      entityId,
      payload,
    }: {
      entityType: TimelineEntityType;
      entityId:   string;
      payload:    AddCommentPayload;
    }) => {
      if (entityType === 'task')    return timelineApi.addToTask(entityId, payload);
      if (entityType === 'project') return timelineApi.addToProject(entityId, payload);
      return Promise.reject(new Error(`Comment not supported for entity type: ${entityType}`));
    },
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['timeline', vars.entityType, vars.entityId] });
      if (vars.entityType === 'task') {
        qc.invalidateQueries({ queryKey: ['tasks', vars.entityId] });
      }
    },
    onError: (err) =>
      addToast({ type: 'error', title: 'Failed to post comment', message: parseApiError(err) }),
  });
}


// ══ UTILITY HOOKS ════════════════════════════════════════════

// useDebounce — delay reactive updates
export function useDebounce<T>(value: T, delay = 350): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

// usePagination — page/size/totalPages management
export function usePagination(totalItems: number, defaultSize = 20) {
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(defaultSize);
  const totalPages = Math.max(1, Math.ceil(totalItems / size));

  const goTo     = (p: number) => setPage(Math.max(1, Math.min(p, totalPages)));
  const next     = () => goTo(page + 1);
  const previous = () => goTo(page - 1);
  const reset    = () => setPage(1);

  return { page, size, totalPages, setPage: goTo, next, previous, reset, setSize };
}

// useClickOutside — close dropdowns / modals on outside click
export function useClickOutside(callback: () => void) {
  const ref = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        callback();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [callback]);
  return ref;
}
