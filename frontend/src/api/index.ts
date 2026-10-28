// ============================================================
// OPSYN API MODULES — Auth, Org, Roles, Outage, Onboarding,
//                    Notifications, Audit, Reports, Projects
// ============================================================

import apiClient from './client';
import type { ApiError } from '../api/client';
import type {
  TokenResponse, Department, Team, Region, Role, Permission, UserScope,
  OutageIncident, OnboardingRequest, Notification, AuditLog,
  Project, APIResponse, PaginatedResponse,
  FormSchema, FormField, FormFieldDependency, FormSubmission,
  SmartOLTConfig, SmartOLTOltMap,
  Shift, ShiftAssignment, ShiftSwapRequest, OutageNotificationRule,
  InfraPort, InfraCapacityAlert, InfraMonitoringConfig, InfraAlertRule,
  InfraMapData, InfraUtilisationPoint,
  TrendMetric, TrendBucket, TrendSeries,
} from '@shared';

// ── Auth ─────────────────────────────────────────────────────
export const authApi = {
  login: (email: string, password: string) =>
    apiClient.post<APIResponse<TokenResponse>>('/auth/login', { email, password })
      .then(r => r.data.data),

  refresh: () =>
    apiClient.post<APIResponse<TokenResponse>>('/auth/refresh', {}, { withCredentials: true })
      .then(r => r.data.data),

  logout: () => apiClient.post('/auth/logout').then(r => r.data),

  activate: (token: string, password: string) =>
    apiClient.post('/auth/activate', { token, password }).then(r => r.data),

  resetPassword: (token: string, new_password: string) =>
    apiClient.post('/auth/reset-password', { token, new_password }).then(r => r.data),

  registerTenant: (payload: {
    org_name: string; slug: string; first_name: string;
    last_name: string; email: string; password: string;
  }) => apiClient.post('/auth/register-tenant', payload).then(r => r.data),
};

// ── Organisation ─────────────────────────────────────────────
export const orgApi = {
  getDepartments: (inScope?: boolean) =>
    apiClient.get<APIResponse<Department[]>>('/departments', { params: { in_scope: inScope } })
      .then(r => r.data.data),

  createDepartment: (payload: Partial<Department>) =>
    apiClient.post<APIResponse<Department>>('/departments', payload).then(r => r.data.data),

  updateDepartment: (id: string, payload: Partial<Department>) =>
    apiClient.put<APIResponse<Department>>(`/departments/${id}`, payload).then(r => r.data.data),

  getTeams: (deptId?: string) =>
    apiClient.get<APIResponse<Team[]>>('/teams', { params: { department_id: deptId } })
      .then(r => r.data.data),

  createTeam: (payload: Partial<Team>) =>
    apiClient.post<APIResponse<Team>>('/teams', payload).then(r => r.data.data),

  getRegions: () =>
    apiClient.get<APIResponse<Region[]>>('/regions').then(r => r.data.data),
};

// ── Roles ─────────────────────────────────────────────────────
export const rolesApi = {
  getRoles: (assignable?: boolean) =>
    apiClient.get<APIResponse<Role[]>>('/roles', { params: { assignable } }).then(r => r.data.data),

  createRole: (payload: Partial<Role>) =>
    apiClient.post<APIResponse<Role>>('/roles', payload).then(r => r.data.data),

  updateRole: (id: string, payload: Partial<Role>) =>
    apiClient.put<APIResponse<Role>>(`/roles/${id}`, payload).then(r => r.data.data),

  assignRole: (roleId: string, userId: string) =>
    apiClient.post(`/roles/${roleId}/assign`, { user_id: userId }).then(r => r.data),

  getPermissions: () =>
    apiClient.get<APIResponse<Permission[]>>('/permissions').then(r => r.data.data),

  getUserScopes: (userId: string) =>
    apiClient.get<APIResponse<UserScope[]>>(`/user-scopes/${userId}`).then(r => r.data.data),

  grantScope: (payload: Omit<UserScope, 'id' | 'granted_by' | 'created_at'>) =>
    apiClient.post<APIResponse<UserScope>>('/user-scopes', payload).then(r => r.data.data),

  revokeScope: (id: string) =>
    apiClient.delete(`/user-scopes/${id}`).then(r => r.data),
};

// ── Outage ────────────────────────────────────────────────────
export const outageApi = {
  list: (params?: { status?: string; region_id?: string; severity?: string }) =>
    apiClient.get<APIResponse<PaginatedResponse<OutageIncident>>>('/outages', { params })
      .then(r => r.data.data),

  // Every open (unresolved) outage, newest first. The endpoint filters on a
  // single status, so one request per open status. (This previously sent
  // ?status=active&status=monitoring in one request; FastAPI keeps only the
  // last value, so 'active' outages were silently missing.)
  getLive: async (): Promise<OutageIncident[]> => {
    const OPEN: OutageIncident['status'][] = ['active', 'monitoring', 'in_resolution'];
    const pages = await Promise.all(OPEN.map(status =>
      apiClient.get<APIResponse<PaginatedResponse<OutageIncident> | OutageIncident[]>>('/outages', { params: { status } })
        .then(r => r.data.data),
    ));
    return pages
      .flatMap(p => (Array.isArray(p) ? p : p?.items ?? []))
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
  },

  get: (id: string) =>
    apiClient.get<APIResponse<OutageIncident>>(`/outages/${id}`).then(r => r.data.data),

  log: (payload: Partial<OutageIncident>) =>
    apiClient.post<APIResponse<OutageIncident>>('/outages', payload).then(r => r.data.data),

  resolve: (id: string) =>
    apiClient.patch<APIResponse<OutageIncident>>(`/outages/${id}/resolve`, {}).then(r => r.data.data),

  updateStatus: (id: string, status: string) =>
    apiClient.patch<APIResponse<OutageIncident>>(`/outages/${id}`, { status }).then(r => r.data.data),

  notifyCustomers: (id: string) =>
    apiClient.post(`/outages/${id}/notify-customers`, {}).then(r => r.data),
};

// ── SmartOLT Settings ─────────────────────────────────────────
export const smartoltApi = {
  getConfig: () =>
    apiClient.get<APIResponse<SmartOLTConfig | null>>('/settings/integrations/smartolt').then(r => r.data.data),

  createConfig: (payload: Partial<SmartOLTConfig> & { api_key?: string; webhook_secret?: string }) =>
    apiClient.post<APIResponse<SmartOLTConfig>>('/settings/integrations/smartolt', payload).then(r => r.data.data),

  updateConfig: (payload: Partial<SmartOLTConfig> & { api_key?: string; webhook_secret?: string }) =>
    apiClient.patch<APIResponse<SmartOLTConfig>>('/settings/integrations/smartolt', payload).then(r => r.data.data),

  listOltMap: () =>
    apiClient.get<APIResponse<SmartOLTOltMap[]>>('/settings/integrations/smartolt/olt-map').then(r => r.data.data),

  addOltMapping: (payload: Partial<SmartOLTOltMap> & { smartolt_olt_id: string }) =>
    apiClient.post<APIResponse<SmartOLTOltMap>>('/settings/integrations/smartolt/olt-map', payload).then(r => r.data.data),

  deleteOltMapping: (id: string) =>
    apiClient.delete(`/settings/integrations/smartolt/olt-map/${id}`).then(r => r.data),
};

// ── Onboarding ────────────────────────────────────────────────
export const onboardingApi = {
  list: (params?: { status?: string }) =>
    apiClient.get<APIResponse<PaginatedResponse<OnboardingRequest>>>('/onboarding', { params })
      .then(r => r.data.data),

  submit: (payload: Partial<OnboardingRequest>) =>
    apiClient.post<APIResponse<OnboardingRequest>>('/onboarding', payload).then(r => r.data.data),

  managerApprove: (id: string) =>
    apiClient.patch<APIResponse<OnboardingRequest>>(`/onboarding/${id}/manager-approve`, {}).then(r => r.data.data),

  approve: (id: string) =>
    apiClient.patch<APIResponse<OnboardingRequest>>(`/onboarding/${id}/approve`, {}).then(r => r.data.data),

  reject: (id: string, reason?: string) =>
    apiClient.patch<APIResponse<OnboardingRequest>>(`/onboarding/${id}/reject`, { reason })
      .then(r => r.data.data),
};

// ── Notifications ─────────────────────────────────────────────
export const notificationsApi = {
  list: () =>
    apiClient.get<APIResponse<Notification[]>>('/notifications').then(r => r.data.data),

  markRead: (id: string) =>
    apiClient.patch(`/notifications/${id}/read`, {}).then(r => r.data),

  markAllRead: () =>
    apiClient.patch('/notifications/read-all', {}).then(r => r.data),

  getUnreadCount: () =>
    apiClient.get<APIResponse<{ count: number }>>('/notifications/unread-count')
      .then(r => r.data.data.count),
};

// ── Audit ─────────────────────────────────────────────────────
export const auditApi = {
  list: (params?: { actor_id?: string; action?: string; from?: string; to?: string; page?: number }) =>
    apiClient.get<APIResponse<PaginatedResponse<AuditLog>>>('/audit-logs', { params })
      .then(r => r.data.data),

  exportCSV: (params?: Record<string, unknown>) =>
    apiClient.get('/audit-logs/export', { params, responseType: 'blob' }).then(r => r.data),
};

// ── Reports ───────────────────────────────────────────────────
export const reportsApi = {
  getSummary: (params?: { date_from?: string; date_to?: string; month?: string; year?: string }) =>
    apiClient.get('/reports/summary', { params }).then(r => r.data.data),

  getOutageMttr: (params?: { date_from?: string; date_to?: string; severity?: string }) =>
    apiClient.get('/reports/outages/mttr', { params }).then(r => r.data.data),

  exportPDF: (params?: Record<string, unknown>) =>
    apiClient.get('/reports/export/pdf', { params, responseType: 'blob' }).then(r => r.data),

  exportCSV: (params?: Record<string, unknown>) =>
    apiClient.get('/reports/export/csv', { params, responseType: 'blob' }).then(r => r.data),

  getIntelStrip: () =>
    apiClient.get<APIResponse<{
      active_outages: number;
      tasks_overdue: number;
      staff_on_call: number;
      avg_mttr_mins: number | null;
      pending_onboarding: number;
    }>>('/reports/intel-strip').then(r => r.data.data),

  getStaffBreakdown: () =>
    apiClient.get('/reports/staff/breakdown').then(r => r.data.data),

  getTasksBreakdown: () =>
    apiClient.get('/reports/tasks/breakdown').then(r => r.data.data),

  getProjectsBreakdown: () =>
    apiClient.get('/reports/projects/breakdown').then(r => r.data.data),

  getInfrastructureReport: () =>
    apiClient.get('/reports/infrastructure').then(r => r.data.data),

  getShiftsReport: () =>
    apiClient.get('/reports/shifts').then(r => r.data.data),

  getSlaReport: () =>
    apiClient.get('/reports/sla').then(r => r.data.data),

  getTrends: (params: { metric: TrendMetric; bucket?: TrendBucket; days?: number }) =>
    apiClient.get<APIResponse<TrendSeries>>('/reports/trends', { params }).then(r => r.data.data),
};

// ── Dashboard ─────────────────────────────────────────────────
export const dashboardApi = {
  getSummary: () =>
    apiClient.get('/dashboard/summary').then(r => r.data.data),
};

// ── Infrastructure ────────────────────────────────────────────
export const infrastructureApi = {
  getSummary: () =>
    apiClient.get('/infrastructure/summary').then(r => r.data),

  listSites: (params?: { status?: string; page?: number; size?: number }) =>
    apiClient.get('/infrastructure/sites', { params }).then(r => r.data),

  createSite: (payload: Record<string, unknown>) =>
    apiClient.post<{ id: string; name: string }>('/infrastructure/sites', payload)
      .then(r => r.data),

  updateSite: (id: string, payload: Record<string, unknown>) =>
    apiClient.put(`/infrastructure/sites/${id}`, payload).then(r => r.data),

  deleteSite: (id: string) =>
    apiClient.delete(`/infrastructure/sites/${id}`).then(r => r.data),

  listNodes: (params?: { site_id?: string; status?: string; page?: number; size?: number }) =>
    apiClient.get('/infrastructure/nodes', { params }).then(r => r.data),

  createNode: (payload: Record<string, unknown>) =>
    apiClient.post('/infrastructure/nodes', payload).then(r => r.data),

  updateNode: (id: string, payload: Record<string, unknown>) =>
    apiClient.put(`/infrastructure/nodes/${id}`, payload).then(r => r.data),

  deleteNode: (id: string) =>
    apiClient.delete(`/infrastructure/nodes/${id}`).then(r => r.data),

  listRoutes: (params?: { from_node_id?: string; to_node_id?: string; status?: string; page?: number; size?: number }) =>
    apiClient.get('/infrastructure/routes', { params }).then(r => r.data),

  createRoute: (payload: Record<string, unknown>) =>
    apiClient.post('/infrastructure/routes', payload).then(r => r.data),

  deleteRoute: (id: string) =>
    apiClient.delete(`/infrastructure/routes/${id}`).then(r => r.data),

  // S4.1 additions
  getDashboardMap: () =>
    apiClient.get<Pick<InfraMapData, 'sites' | 'olts'>>('/infrastructure/dashboard-map').then(r => r.data),

  getMap: () =>
    apiClient.get<InfraMapData>('/infrastructure/map').then(r => r.data),

  getUtilisation: () =>
    apiClient.get<InfraUtilisationPoint[]>('/infrastructure/utilisation').then(r => r.data),

  listPorts: (nodeId: string) =>
    apiClient.get<InfraPort[]>(`/infrastructure/nodes/${nodeId}/ports`).then(r => r.data),

  createPort: (nodeId: string, payload: Partial<InfraPort>) =>
    apiClient.post<InfraPort>(`/infrastructure/nodes/${nodeId}/ports`, payload).then(r => r.data),

  updatePort: (portId: string, payload: Partial<InfraPort>) =>
    apiClient.patch<InfraPort>(`/infrastructure/ports/${portId}`, payload).then(r => r.data),

  deletePort: (portId: string) =>
    apiClient.delete(`/infrastructure/ports/${portId}`).then(r => r.data),

  listCapacityAlerts: (resolved?: boolean) =>
    apiClient.get<InfraCapacityAlert[]>('/infrastructure/capacity-alerts', { params: resolved !== undefined ? { resolved } : {} }).then(r => r.data),

  resolveCapacityAlert: (alertId: string) =>
    apiClient.patch<InfraCapacityAlert>(`/infrastructure/capacity-alerts/${alertId}/resolve`).then(r => r.data),

  listMonitoringConfigs: () =>
    apiClient.get<{ data: InfraMonitoringConfig[] }>('/settings/infrastructure/monitoring').then(r => r.data.data),

  createMonitoringConfig: (payload: Partial<InfraMonitoringConfig>) =>
    apiClient.post<{ data: InfraMonitoringConfig }>('/settings/infrastructure/monitoring', payload).then(r => r.data.data),

  updateMonitoringConfig: (id: string, payload: Partial<InfraMonitoringConfig>) =>
    apiClient.put<{ data: InfraMonitoringConfig }>(`/settings/infrastructure/monitoring/${id}`, payload).then(r => r.data.data),

  deleteMonitoringConfig: (id: string) =>
    apiClient.delete(`/settings/infrastructure/monitoring/${id}`).then(r => r.data),

  listAlertRules: () =>
    apiClient.get<{ data: InfraAlertRule[] }>('/settings/infrastructure/alert-rules').then(r => r.data.data),

  createAlertRule: (payload: Partial<InfraAlertRule>) =>
    apiClient.post<{ data: InfraAlertRule }>('/settings/infrastructure/alert-rules', payload).then(r => r.data.data),

  updateAlertRule: (id: string, payload: Partial<InfraAlertRule>) =>
    apiClient.put<{ data: InfraAlertRule }>(`/settings/infrastructure/alert-rules/${id}`, payload).then(r => r.data.data),

  deleteAlertRule: (id: string) =>
    apiClient.delete(`/settings/infrastructure/alert-rules/${id}`).then(r => r.data),

  listSubscribers: (params?: { site_id?: string; node_id?: string; service_type?: string }) =>
    apiClient.get<any[]>('/infrastructure/subscribers', { params }).then(r => r.data),

  triggerSyncPorts: () =>
    apiClient.post<{ queued: boolean; message: string }>('/infrastructure/sync-ports').then(r => r.data),

  // ── FTTH Upload workflow ──────────────────────────────────
  uploadAssetFile: (assetType: string, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return apiClient.post<any>(`/infrastructure/upload/${assetType}`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data);
  },

  getUploadSession: (sessionId: string) =>
    apiClient.get<any>(`/infrastructure/upload/${sessionId}`).then(r => r.data),

  commitUploadSession: (sessionId: string) =>
    apiClient.post<any>(`/infrastructure/upload/${sessionId}/commit`).then(r => r.data),

  downloadErrorReport: (sessionId: string) =>
    apiClient.get(`/infrastructure/upload/${sessionId}/error-report`, {
      responseType: 'blob',
    }),

  // ── FTTH Asset lists ─────────────────────────────────────
  listCabinets: (params?: { page?: number; size?: number }) =>
    apiClient.get<any>('/infrastructure/cabinets', { params }).then(r => r.data),

  listOlts: (params?: { page?: number; size?: number }) =>
    apiClient.get<any>('/infrastructure/olts', { params }).then(r => r.data),

  listSplitters: (params?: { page?: number; size?: number; splitter_level?: string }) =>
    apiClient.get<any>('/infrastructure/splitters', { params }).then(r => r.data),

  // ── FTTH Deletion workflow ────────────────────────────────
  uploadDeletionFile: (assetType: string, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return apiClient.post<any>(`/infrastructure/deletion/${assetType}`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data);
  },

  getDeletionSession: (sessionId: string) =>
    apiClient.get<any>(`/infrastructure/deletion/${sessionId}`).then(r => r.data),

  executeDeletion: (sessionId: string) =>
    apiClient.post<any>(`/infrastructure/deletion/${sessionId}/execute`).then(r => r.data),

  // ── Audit log ─────────────────────────────────────────────
  listAuditLog: (params?: {
    page?: number; size?: number; asset_type?: string;
    action?: string; asset_key?: string; session_id?: string;
  }) =>
    apiClient.get<any>('/infrastructure/audit', { params }).then(r => r.data),

  getAuditEntry: (entryId: string) =>
    apiClient.get<any>(`/infrastructure/audit/${entryId}`).then(r => r.data),
};

// ── Activity Timeline ─────────────────────────────────────────
export const activityApi = {
  getGlobalFeed: (params?: { entity_type?: string; page?: number; size?: number }) =>
    apiClient.get('/activity-timeline', { params }).then(r => r.data.data),

  getTaskTimeline: (taskId: string, page = 1) =>
    apiClient.get(`/tasks/${taskId}/timeline`, { params: { page } }).then(r => r.data.data),

  getProjectTimeline: (projectId: string, page = 1) =>
    apiClient.get(`/projects/${projectId}/timeline`, { params: { page } }).then(r => r.data.data),

  postTaskComment: (taskId: string, body: string) =>
    apiClient.post(`/tasks/${taskId}/timeline`, { body }).then(r => r.data),

  postProjectComment: (projectId: string, body: string) =>
    apiClient.post(`/projects/${projectId}/timeline`, { body }).then(r => r.data),
};

// ── Settings ──────────────────────────────────────────────────
export const settingsApi = {
  getOrg: () =>
    apiClient.get('/settings/organisation').then(r => r.data.data),

  updateOrg: (payload: { name?: string; timezone?: string; logo_url?: string }) =>
    apiClient.patch('/settings/organisation', payload).then(r => r.data),

  getDepartments: () =>
    apiClient.get('/settings/departments').then(r => r.data.data),

  createDepartment: (payload: { name: string; parent_id?: string; head_user_id?: string }) =>
    apiClient.post('/settings/departments', payload).then(r => r.data.data),

  updateDepartment: (id: string, payload: { name?: string }) =>
    apiClient.put(`/settings/departments/${id}`, payload).then(r => r.data.data),

  deleteDepartment: (id: string) =>
    apiClient.delete(`/settings/departments/${id}`).then(r => r.data),

  getDeptFeatures: (deptId: string) =>
    apiClient.get(`/settings/departments/${deptId}/features`).then(r => r.data.data),

  grantDeptFeature: (deptId: string, feature_key: string, min_role_level: number) =>
    apiClient.post(`/settings/departments/${deptId}/features`, { feature_key, min_role_level }).then(r => r.data),

  revokeDeptFeature: (deptId: string, featureKey: string) =>
    apiClient.delete(`/settings/departments/${deptId}/features/${featureKey}`).then(r => r.data),

  getRoles: () =>
    apiClient.get('/settings/roles').then(r => r.data.data),

  createRole: (payload: { name: string; level: number; description?: string }) =>
    apiClient.post('/settings/roles', payload).then(r => r.data.data),

  getRegions: () =>
    apiClient.get('/settings/regions').then(r => r.data.data),

  createRegion: (payload: { name: string; code: string; parent_id?: string }) =>
    apiClient.post<{ data: Region }>('/settings/regions', payload).then(r => r.data.data),

  getFeaturePermissions: () =>
    apiClient.get('/settings/feature-permissions').then(r => r.data.data),

  updateOrgBrand: (payload: { primary_color?: string; logo_url?: string; favicon_url?: string; company_tagline?: string }) =>
    apiClient.patch('/settings/organisation/brand', payload).then(r => r.data),

  getPipelines: () =>
    apiClient.get('/settings/pipelines').then(r => r.data.data),

  createPipeline: (payload: { name: string; description?: string }) =>
    apiClient.post('/settings/pipelines', payload).then(r => r.data.data),

  updatePipelineStages: (templateId: string, stages: any[]) =>
    apiClient.put(`/settings/pipelines/${templateId}/stages`, { stages }).then(r => r.data.data),

  getIntegrations: () =>
    apiClient.get('/settings/integrations').then(r => r.data.data),

  getIntegrationConfig: (key: string) =>
    apiClient.get(`/settings/integrations/${key}/config`).then(r => r.data.data),

  saveIntegrationConfig: (key: string, config: Record<string, string>) =>
    apiClient.post(`/settings/integrations/${key}/config`, { config }).then(r => r.data),

  removeIntegrationConfig: (key: string) =>
    apiClient.delete(`/settings/integrations/${key}/config`).then(r => r.data),

  getNotificationRules: () =>
    apiClient.get<APIResponse<OutageNotificationRule[]>>('/settings/notification-rules').then(r => r.data.data),

  createNotificationRule: (payload: Partial<OutageNotificationRule>) =>
    apiClient.post<APIResponse<OutageNotificationRule>>('/settings/notification-rules', payload).then(r => r.data.data),

  updateNotificationRule: (id: string, payload: Partial<OutageNotificationRule>) =>
    apiClient.patch<APIResponse<OutageNotificationRule>>(`/settings/notification-rules/${id}`, payload).then(r => r.data.data),

  deleteNotificationRule: (id: string) =>
    apiClient.delete(`/settings/notification-rules/${id}`).then(r => r.data),

  testNotificationRule: (id: string) =>
    apiClient.post(`/settings/notification-rules/${id}/test`, {}).then(r => r.data),
};

// ── Shifts ────────────────────────────────────────────────────
export const shiftsApi = {
  list: () =>
    apiClient.get<APIResponse<Shift[]>>('/shifts').then(r => r.data.data),

  create: (payload: Partial<Shift>) =>
    apiClient.post<APIResponse<Shift>>('/shifts', payload).then(r => r.data.data),

  delete: (id: string) =>
    apiClient.delete(`/shifts/${id}`).then(r => r.data),

  getWeekly: (weekStart: string) =>
    apiClient.get<APIResponse<{ assignments: ShiftAssignment[]; week_start: string }>>('/shifts/weekly', { params: { week_start: weekStart } })
      .then(r => r.data.data),

  listAssignments: (params?: { date?: string; user_id?: string; status?: string }) =>
    apiClient.get<APIResponse<ShiftAssignment[]>>('/shifts/assignments', { params }).then(r => r.data.data),

  createAssignment: (payload: { shift_id: string; user_id: string; date: string; notes?: string }) =>
    apiClient.post<APIResponse<ShiftAssignment>>('/shifts/assignments', payload).then(r => r.data.data),

  updateAssignmentStatus: (id: string, status: string) =>
    apiClient.patch<APIResponse<ShiftAssignment>>(`/shifts/assignments/${id}/status`, { status }).then(r => r.data.data),

  deleteAssignment: (id: string) =>
    apiClient.delete(`/shifts/assignments/${id}`).then(r => r.data),

  listSwapRequests: (params?: { status?: string }) =>
    apiClient.get<APIResponse<ShiftSwapRequest[]>>('/shifts/swap-requests', { params }).then(r => r.data.data),

  createSwapRequest: (payload: { from_assignment_id: string; to_user_id: string; reason?: string }) =>
    apiClient.post<APIResponse<ShiftSwapRequest>>('/shifts/swap-requests', payload).then(r => r.data.data),

  respondSwapRequest: (id: string, status: 'approved' | 'rejected') =>
    apiClient.patch<APIResponse<ShiftSwapRequest>>(`/shifts/swap-requests/${id}/respond`, { status }).then(r => r.data.data),
};

// ── Webhooks ──────────────────────────────────────────────────
export const webhooksApi = {
  listKeys: () =>
    apiClient.get<APIResponse<{ id: string; app_name: string; is_active: boolean; created_at: string }[]>>('/webhooks/keys')
      .then(r => r.data.data),

  createKey: (app_name: string) =>
    apiClient.post<APIResponse<{ id: string; app_name: string; secret_key: string; created_at: string; note: string }>>('/webhooks/keys', { app_name })
      .then(r => r.data.data),

  deactivateKey: (keyId: string) =>
    apiClient.delete(`/webhooks/keys/${keyId}`).then(r => r.data),
};

// ── Forms ─────────────────────────────────────────────────────
export const formsApi = {
  getSchema: (context: string) =>
    apiClient.get<APIResponse<FormSchema>>(`/forms/${context}`)
      .then(r => r.data.data)
      .catch((e: ApiError) => {
        // Handle both raw axios shape (e.response.status) and
        // normalised error shape (e.status) from the Axios interceptor.
        const status = e?.status ?? e?.response?.status;
        if (status === 404) return null;
        return Promise.reject(e);
      }),

  addField: (context: string, payload: {
    field_key: string; field_type: string; label: string;
    placeholder?: string; help_text?: string; required?: boolean;
    field_order?: number; options?: unknown; validation_rules?: unknown;
  }) =>
    apiClient.post<APIResponse<FormField>>(`/admin/forms/${context}/fields`, payload).then(r => r.data.data),

  updateField: (context: string, fieldId: string, payload: {
    label?: string; placeholder?: string; help_text?: string; required?: boolean;
    field_order?: number; options?: unknown; validation_rules?: unknown;
  }) =>
    apiClient.put<APIResponse<FormField>>(`/admin/forms/${context}/fields/${fieldId}`, payload).then(r => r.data.data),

  deleteField: (context: string, fieldId: string) =>
    apiClient.delete(`/admin/forms/${context}/fields/${fieldId}`),

  reorderFields: (context: string, order: string[]) =>
    apiClient.patch<APIResponse<FormSchema>>(`/admin/forms/${context}/fields/reorder`, { order }).then(r => r.data.data),

  publishSchema: (context: string) =>
    apiClient.post<APIResponse<FormSchema>>(`/admin/forms/${context}/publish`).then(r => r.data.data),

  addDependency: (context: string, payload: {
    source_field_key: string; target_field_key: string;
    condition_operator: string; condition_value?: string; action: string;
  }) =>
    apiClient.post<APIResponse<FormFieldDependency>>(`/admin/forms/${context}/dependencies`, payload).then(r => r.data.data),

  deleteDependency: (context: string, depId: string) =>
    apiClient.delete(`/admin/forms/${context}/dependencies/${depId}`),

  submit: (payload: {
    context: string; entity_type?: string; entity_id?: string;
    submitted_data: Record<string, unknown>;
  }) =>
    apiClient.post<APIResponse<FormSubmission>>('/forms/submit', payload).then(r => r.data.data),

  getSubmissions: (entityType: string, entityId: string) =>
    apiClient.get<APIResponse<FormSubmission[]>>(`/forms/submissions/${entityType}/${entityId}`).then(r => r.data.data),
};

// ── Staff (re-export from staff.api.ts for convenience) ──────
export { staffApi } from './staff.api';

// ── Projects ──────────────────────────────────────────────────
export const projectsApi = {
  list: (params?: { status?: string; dept_id?: string }) =>
    apiClient.get<APIResponse<PaginatedResponse<Project>>>('/projects', { params })
      .then(r => r.data.data),

  get: (id: string) =>
    apiClient.get<APIResponse<Project>>(`/projects/${id}`).then(r => r.data.data),

  create: (payload: Partial<Project>) =>
    apiClient.post<APIResponse<Project>>('/projects', payload).then(r => r.data.data),

  update: (id: string, payload: Partial<Project>) =>
    apiClient.put<APIResponse<Project>>(`/projects/${id}`, payload).then(r => r.data.data),

  startPipeline: (id: string, body: { template_id?: string; workflow_id?: string }) =>
    apiClient.post(`/projects/${id}/pipeline/start`, body).then(r => r.data.data),
};
