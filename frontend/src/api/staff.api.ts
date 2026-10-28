// ============================================================
// OPSYN STAFF API MODULE
// All HTTP calls for the staff domain
// ============================================================

import apiClient from './client';
import type {
  StaffProfile, CreateStaffRequest,
  PaginatedResponse, APIResponse
} from '@shared';

export interface StaffListFilters {
  page?: number;
  size?: number;
  dept_id?: string;
  role_id?: string;
  status?: string;
  region_id?: string;
  search?: string;
}

export const staffApi = {
  list: (filters: StaffListFilters = {}) =>
    apiClient.get<APIResponse<PaginatedResponse<StaffProfile>>>('/staff', { params: filters })
      .then(r => r.data.data),

  get: (id: string) =>
    apiClient.get<APIResponse<StaffProfile>>(`/staff/${id}`)
      .then(r => r.data.data),

  create: (payload: CreateStaffRequest) =>
    apiClient.post<APIResponse<StaffProfile>>('/staff', payload)
      .then(r => r.data.data),

  update: (id: string, payload: Partial<CreateStaffRequest>) =>
    apiClient.put<APIResponse<StaffProfile>>(`/staff/${id}`, payload)
      .then(r => r.data.data),

  updateStatus: (id: string, status: 'active' | 'inactive' | 'suspended' | 'on_leave') =>
    apiClient.patch<APIResponse<StaffProfile>>(`/staff/${id}/status`, { status })
      .then(r => r.data.data),

  delete: (id: string) =>
    apiClient.delete(`/staff/${id}`).then(r => r.data),

  getTasks: (id: string) =>
    apiClient.get(`/staff/${id}/tasks`).then(r => r.data.data),

  getAuditEvents: (id: string) =>
    apiClient.get(`/staff/${id}/audit`).then(r => r.data.data),

  checkEmailUnique: (email: string) =>
    apiClient.get('/staff/check/email', { params: { email } }).then(r => r.data.data),

  checkUsernameUnique: (username: string) =>
    apiClient.get('/staff/check/username', { params: { username } }).then(r => r.data.data),

  getPerformance: (id: string) =>
    apiClient.get<{ success: boolean; data: StaffPerformance }>(`/staff/${id}/performance`).then(r => r.data.data),

  invite: (payload: { email: string; role_id?: string; message?: string }) =>
    apiClient.post('/staff/invite', payload).then(r => r.data),
};

export interface StaffPerformance {
  user_id:                string;
  efficiency_score:       number | null;
  efficiency_computed_at: string | null;
  lookback_days:          number;
  tasks_assigned:         number;
  tasks_done:             number;
  tasks_open:             number;
  tasks_on_time:          number;
  avg_resolution_hours:   number;
  completion_rate_pct:    number;
  sla_adherence_pct:      number;
}
