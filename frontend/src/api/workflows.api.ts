// ============================================================
// OPSYN WORKFLOWS API — src/api/workflows.api.ts
// Department Workflow Builder endpoints
// ============================================================

import apiClient from './client';
import type {
  DeptWorkflow,
  WorkflowGraph,
  WorkflowEdge,
  WorkflowValidationResult,
  CreateWorkflowPayload,
  AddEdgePayload,
  UpdateEdgePayload,
} from '../types/workflow.types';

interface APIResponse<T> {
  success: boolean;
  data: T;
}

export const workflowsApi = {
  list: (activeOnly = true) =>
    apiClient
      .get<APIResponse<DeptWorkflow[]>>('/workflows', { params: { active_only: activeOnly } })
      .then(r => r.data.data),

  get: (id: string) =>
    apiClient
      .get<APIResponse<WorkflowGraph>>(`/workflows/${id}`)
      .then(r => r.data.data),

  create: (payload: CreateWorkflowPayload) =>
    apiClient
      .post<APIResponse<DeptWorkflow>>('/workflows', payload)
      .then(r => r.data.data),

  update: (id: string, payload: { name?: string; description?: string }) =>
    apiClient
      .put<APIResponse<DeptWorkflow>>(`/workflows/${id}`, payload)
      .then(r => r.data.data),

  delete: (id: string) =>
    apiClient.delete<APIResponse<null>>(`/workflows/${id}`).then(r => r.data),

  addEdge: (workflowId: string, payload: AddEdgePayload) =>
    apiClient
      .post<APIResponse<WorkflowEdge>>(`/workflows/${workflowId}/edges`, payload)
      .then(r => r.data.data),

  updateEdge: (workflowId: string, edgeId: string, payload: UpdateEdgePayload) =>
    apiClient
      .put<APIResponse<WorkflowEdge>>(`/workflows/${workflowId}/edges/${edgeId}`, payload)
      .then(r => r.data.data),

  removeEdge: (workflowId: string, edgeId: string) =>
    apiClient
      .delete<APIResponse<null>>(`/workflows/${workflowId}/edges/${edgeId}`)
      .then(r => r.data),

  validate: (id: string) =>
    apiClient
      .post<APIResponse<WorkflowValidationResult>>(`/workflows/${id}/validate`)
      .then(r => r.data.data),

  publish: (id: string) =>
    apiClient
      .post<APIResponse<DeptWorkflow>>(`/workflows/${id}/publish`)
      .then(r => r.data.data),

  clone: (id: string) =>
    apiClient
      .post<APIResponse<DeptWorkflow>>(`/workflows/${id}/clone`)
      .then(r => r.data.data),
};
