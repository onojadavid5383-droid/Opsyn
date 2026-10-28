// ============================================================
// OPSYN PROJECTS API MODULE
// All HTTP calls for the projects domain
// ============================================================

import apiClient from './client';
import type {
  Project, ProjectPipelineResponse, ProjectPipelineStage, StageComment,
  PipelineTemplate, APIResponse
} from '@shared';

// Backend returns snake_case; pipeline components expect camelCase.
function toCamel(s: string): string {
  return s.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
}
function camelizeKeys(o: any): any {
  if (Array.isArray(o)) return o.map(camelizeKeys);
  if (o && typeof o === 'object') {
    return Object.fromEntries(Object.entries(o).map(([k, v]) => [toCamel(k), camelizeKeys(v)]));
  }
  return o;
}

export const projectsApi = {
  list: () =>
    apiClient.get<APIResponse<Project[]>>('/projects')
      .then(r => r.data.data),

  get: (id: string) =>
    apiClient.get<APIResponse<Project>>(`/projects/${id}`)
      .then(r => r.data.data),

  create: (payload: any) =>
    apiClient.post<APIResponse<Project>>('/projects', payload)
      .then(r => r.data.data),

  update: (id: string, payload: Partial<Project>) =>
    apiClient.put<APIResponse<Project>>(`/projects/${id}`, payload)
      .then(r => r.data.data),

  delete: (id: string) =>
    apiClient.delete(`/projects/${id}`).then(r => r.data),

  // Pipeline APIs — camelizeKeys normalises snake_case API responses to camelCase
  getPipeline: (projectId: string): Promise<APIResponse<ProjectPipelineResponse>> =>
    apiClient.get(`/projects/${projectId}/pipeline`).then(r => camelizeKeys(r.data)),

  startPipeline: (projectId: string, templateId: string): Promise<APIResponse<ProjectPipelineStage>> =>
    apiClient.post(`/projects/${projectId}/pipeline/start`, { template_id: templateId }).then(r => camelizeKeys(r.data)),

  advanceStage: (projectId: string, comment?: string): Promise<APIResponse<ProjectPipelineStage>> =>
    apiClient.post(`/projects/${projectId}/pipeline/advance`, { comment }).then(r => camelizeKeys(r.data)),

  pushBackStage: (projectId: string, reason: string, comment?: string): Promise<APIResponse<ProjectPipelineStage>> =>
    apiClient.post(`/projects/${projectId}/pipeline/pushback`, { reason, comment }).then(r => camelizeKeys(r.data)),

  addStageComment: (projectId: string, stageId: string, body: string, commentType: string): Promise<APIResponse<StageComment>> =>
    apiClient.post(`/projects/${projectId}/pipeline/stages/${stageId}/comments`, { body, comment_type: commentType }).then(r => camelizeKeys(r.data)),

  getStageComments: (projectId: string, stageId: string): Promise<APIResponse<StageComment[]>> =>
    apiClient.get(`/projects/${projectId}/pipeline/stages/${stageId}/comments`).then(r => camelizeKeys(r.data)),

  getPipelineTemplates: (): Promise<APIResponse<PipelineTemplate[]>> =>
    apiClient.get('/pipeline-templates').then(r => camelizeKeys(r.data)),

  approveStage: (projectId: string, stageId: string, notes?: string): Promise<APIResponse<any>> =>
    apiClient.post(`/projects/${projectId}/pipeline/stages/${stageId}/approve`, { notes })
      .then(r => camelizeKeys(r.data)),

  getProgress: (projectId: string): Promise<{ success: boolean; data: { progress: number; total_stages: number; completed_stages: number } }> =>
    apiClient.get(`/projects/${projectId}/progress`).then(r => r.data),
};