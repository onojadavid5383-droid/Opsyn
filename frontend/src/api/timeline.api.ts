// ============================================================
// OPSYN TIMELINE API — Activity Timeline endpoints
// Blueprint Section 4.3
// ============================================================

import apiClient from './client';
import type { APIResponse, PaginatedResponse } from '@shared';
import type {
  TimelineEntry,
  TimelineEntityType,
  TimelineEventType,
  AddCommentPayload,
} from '../components/timeline/types';

export const timelineApi = {
  // ── Entity-scoped feeds ───────────────────────────────────
  getForTask: (taskId: string, params?: { limit?: number; offset?: number }) =>
    apiClient
      .get<APIResponse<TimelineEntry[]>>(`/tasks/${taskId}/timeline`, { params })
      .then(r => r.data.data ?? []),

  getForProject: (projectId: string, params?: { limit?: number; offset?: number }) =>
    apiClient
      .get<APIResponse<TimelineEntry[]>>(`/projects/${projectId}/timeline`, { params })
      .then(r => r.data.data ?? []),

  getForOutage: (outageId: string, params?: { limit?: number; offset?: number }) =>
    apiClient
      .get<APIResponse<TimelineEntry[]>>(`/outages/${outageId}/timeline`, { params })
      .then(r => r.data.data ?? []),

  getForOnboarding: (requestId: string, params?: { limit?: number; offset?: number }) =>
    apiClient
      .get<APIResponse<TimelineEntry[]>>(`/onboarding/${requestId}/timeline`, { params })
      .then(r => r.data.data ?? []),

  // ── Add user comment ──────────────────────────────────────
  addToTask: (taskId: string, payload: AddCommentPayload) =>
    apiClient
      .post<APIResponse<TimelineEntry>>(`/tasks/${taskId}/timeline`, payload)
      .then(r => r.data.data),

  addToProject: (projectId: string, payload: AddCommentPayload) =>
    apiClient
      .post<APIResponse<TimelineEntry>>(`/projects/${projectId}/timeline`, payload)
      .then(r => r.data.data),

  // ── Cross-entity query ────────────────────────────────────
  query: (params: {
    entity_type?: TimelineEntityType;
    entity_id?:   string;
    event_type?:  TimelineEventType;
    limit?:       number;
    offset?:      number;
  }) =>
    apiClient
      .get<APIResponse<PaginatedResponse<TimelineEntry>>>('/activity-timeline', { params })
      .then(r => r.data.data),
};
