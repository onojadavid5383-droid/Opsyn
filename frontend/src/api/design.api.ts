// ============================================================
// OPSYN — Design API (backend app/modules/design, Network GIS Phase 4)
// Every call unwraps the {success, data} envelope. Types: @shared.
// ============================================================

import type {
  APIResponse, ApprovalOverview, DeploymentAction, DeploymentAdvanceResult, DeploymentItem, DeploymentProgress, PromoteResult, ApprovalRequest, AuditEntry, BoqDiff, Design, DesignCompare, DesignRestoreResult, DesignVersionInfo, DesignBoq, DesignGenerateStatus, DesignImportResult, DesignInputLayer, DesignInputLayerKey,
  DesignInputUploadResult, DesignOpLog, DesignOperationBody, DesignOpResult, DesignRoute, DesignSnap, DesignSnapKind,
  DesignStatus, DesignSummary, DesignValidation, ImportableRun,
} from '@shared';
import apiClient from './client';

export interface DesignPatch {
  name?:          string;
  description?:   string | null;
  status?:        Extract<DesignStatus, 'DRAFT' | 'MODIFIED'>;
  /** null clears it */
  boundary?:      { type: 'Polygon' | 'MultiPolygon'; coordinates: unknown } | null;
  engine_config?: Record<string, unknown>;
}

export type RouteEnd = { asset_id: string } | { lng: number; lat: number };

export const designApi = {
  list: (projectId: string) =>
    apiClient.get<APIResponse<Design[]>>(`/projects/${projectId}/designs`).then(r => r.data.data),

  create: (projectId: string, body: { name: string; description?: string }) =>
    apiClient.post<APIResponse<Design>>(`/projects/${projectId}/designs`, body).then(r => r.data.data),

  get: (id: string) =>
    apiClient.get<APIResponse<Design>>(`/designs/${id}`).then(r => r.data.data),

  update: (id: string, patch: DesignPatch) =>
    apiClient.patch<APIResponse<Design>>(`/designs/${id}`, patch).then(r => r.data.data),

  remove: (id: string) => apiClient.delete(`/designs/${id}`).then(() => undefined),

  boundaryFromInputs: (id: string) =>
    apiClient.post<APIResponse<Design>>(`/designs/${id}/boundary/from-inputs`).then(r => r.data.data),

  inputs: (id: string) =>
    apiClient.get<APIResponse<DesignInputLayer[]>>(`/designs/${id}/inputs`).then(r => r.data.data),

  inputFeatures: (id: string, layer: DesignInputLayerKey) =>
    apiClient.get<APIResponse<GeoJSON.FeatureCollection & { truncated: boolean }>>(`/designs/${id}/inputs/${layer}`)
      .then(r => r.data.data),

  uploadInputs: (id: string, layer: DesignInputLayerKey, file: File, mode: 'replace' | 'append') => {
    const fd = new FormData();
    fd.append('file', file);
    return apiClient.post<APIResponse<DesignInputUploadResult>>(`/designs/${id}/inputs/${layer}`, fd, {
      params: { mode }, headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120_000,
    }).then(r => r.data.data);
  },

  removeInputs: (id: string, layer: DesignInputLayerKey) =>
    apiClient.delete<APIResponse<{ removed: number }>>(`/designs/${id}/inputs/${layer}`).then(r => r.data.data),

  features: (id: string) =>
    apiClient.get<APIResponse<GeoJSON.FeatureCollection>>(`/designs/${id}/features`).then(r => r.data.data),

  summary: (id: string) =>
    apiClient.get<APIResponse<DesignSummary>>(`/designs/${id}/summary`).then(r => r.data.data),

  boq: (id: string) =>
    apiClient.get<APIResponse<DesignBoq>>(`/designs/${id}/boq`, { timeout: 120_000 }).then(r => r.data.data),

  validate: (id: string) =>
    apiClient.post<APIResponse<DesignValidation>>(`/designs/${id}/validate`).then(r => r.data.data),

  validation: (id: string) =>
    apiClient.get<APIResponse<DesignValidation>>(`/designs/${id}/validation`).then(r => r.data.data),

  route: (id: string, from: RouteEnd, to: RouteEnd) =>
    apiClient.post<APIResponse<DesignRoute>>(`/designs/${id}/route`, { from, to }).then(r => r.data.data),

  // ── Auto design (Phase 5) ──
  generate: (id: string, body: { engine_config?: Record<string, unknown>; replace: boolean }) =>
    apiClient.post<APIResponse<DesignGenerateStatus>>(`/designs/${id}/generate`, body).then(r => r.data.data),

  generateStatus: (id: string) =>
    apiClient.get<APIResponse<DesignGenerateStatus | null>>(`/designs/${id}/generate/status`).then(r => r.data.data),

  cancelGenerate: (id: string) =>
    apiClient.post<APIResponse<DesignGenerateStatus>>(`/designs/${id}/generate/cancel`).then(r => r.data.data),

  importableRuns: (id: string) =>
    apiClient.get<APIResponse<ImportableRun[]>>(`/designs/${id}/importable-runs`).then(r => r.data.data),

  importRun: (id: string, runId: string, replace: boolean) =>
    apiClient.post<APIResponse<DesignImportResult>>(`/designs/${id}/import-run`, { run_id: runId, replace }, { timeout: 120_000 })
      .then(r => r.data.data),

  // ── Manual design (Phase 6) ──
  operate: (id: string, body: DesignOperationBody) =>
    apiClient.post<APIResponse<DesignOpResult>>(`/designs/${id}/operations`, body, { timeout: 60_000 }).then(r => r.data.data),

  undo: (id: string) =>
    apiClient.post<APIResponse<DesignOpResult>>(`/designs/${id}/operations/undo`).then(r => r.data.data),

  redo: (id: string) =>
    apiClient.post<APIResponse<DesignOpResult>>(`/designs/${id}/operations/redo`).then(r => r.data.data),

  operations: (id: string) =>
    apiClient.get<APIResponse<DesignOpLog>>(`/designs/${id}/operations`).then(r => r.data.data),

  snap: (id: string, body: { lng: number; lat: number; radius_m?: number; targets?: DesignSnapKind[] }) =>
    apiClient.post<APIResponse<DesignSnap>>(`/designs/${id}/snap`, body).then(r => r.data.data),

  // ── Versions and audit (Phase 8) ──
  versions: (id: string) =>
    apiClient.get<APIResponse<DesignVersionInfo[]>>(`/designs/${id}/versions`).then(r => r.data.data),

  saveVersion: (id: string, label: string) =>
    apiClient.post<APIResponse<{ saved: DesignVersionInfo; versions: DesignVersionInfo[] }>>(`/designs/${id}/versions`, { label })
      .then(r => r.data.data),

  versionFeatures: (id: string, no: number) =>
    apiClient.get<APIResponse<GeoJSON.FeatureCollection & { version_no: number }>>(`/designs/${id}/versions/${no}/features`)
      .then(r => r.data.data),

  compare: (id: string, from: number, to: number) =>
    apiClient.get<APIResponse<DesignCompare>>(`/designs/${id}/compare`, { params: { from, to } }).then(r => r.data.data),

  restore: (id: string, no: number) =>
    apiClient.post<APIResponse<DesignRestoreResult>>(`/designs/${id}/versions/${no}/restore`, undefined, { timeout: 120_000 })
      .then(r => r.data.data),

  history: (id: string) =>
    apiClient.get<APIResponse<AuditEntry[]>>(`/designs/${id}/history`).then(r => r.data.data),

  entityHistory: (entityId: string) =>
    apiClient.get<APIResponse<AuditEntry[]>>(`/network/history/${entityId}`).then(r => r.data.data),

  // ── Approval (Phase 9) ──
  approvals: (id: string) =>
    apiClient.get<APIResponse<ApprovalOverview>>(`/designs/${id}/approvals`).then(r => r.data.data),

  submitDesign: (id: string, note: string | null) =>
    apiClient.post<APIResponse<ApprovalRequest>>(`/designs/${id}/submit`, { note }).then(r => r.data.data),

  submitBoq: (id: string, note: string | null) =>
    apiClient.post<APIResponse<ApprovalRequest>>(`/designs/${id}/boq/submit`, { note }, { timeout: 120_000 }).then(r => r.data.data),

  reopen: (id: string) =>
    apiClient.post<APIResponse<{ status: string; version_no: number }>>(`/designs/${id}/reopen`).then(r => r.data.data),

  decide: (requestId: string, decision: 'APPROVE' | 'REJECT', comment: string | null) =>
    apiClient.post<APIResponse<ApprovalRequest>>(`/approvals/${requestId}/decide`, { decision, comment }).then(r => r.data.data),

  withdraw: (requestId: string) =>
    apiClient.post<APIResponse<ApprovalRequest>>(`/approvals/${requestId}/withdraw`).then(r => r.data.data),

  comment: (requestId: string, body: { body: string; asset_id?: string; cable_id?: string; lng?: number; lat?: number }) =>
    apiClient.post<APIResponse<ApprovalRequest>>(`/approvals/${requestId}/comments`, body).then(r => r.data.data),

  resolveComment: (commentId: string, resolved: boolean) =>
    apiClient.patch<APIResponse<ApprovalRequest>>(`/approval-comments/${commentId}`, { resolved }).then(r => r.data.data),

  boqDiff: (requestId: string) =>
    apiClient.get<APIResponse<BoqDiff>>(`/approvals/${requestId}/boq-diff`).then(r => r.data.data),

  // ── Deployment (Phase 10) ──

  deploy: (id: string, note: string | null) =>
    apiClient.post<APIResponse<DeploymentProgress>>(`/designs/${id}/deploy`, { note }).then(r => r.data.data),

  deployment: (id: string) =>
    apiClient.get<APIResponse<DeploymentProgress>>(`/designs/${id}/deployment`).then(r => r.data.data),

  advance: (id: string, body: { items: DeploymentItem[]; action: DeploymentAction; note?: string | null }) =>
    apiClient.post<APIResponse<DeploymentAdvanceResult>>(`/designs/${id}/deployment/progress`, body).then(r => r.data.data),

  asBuilt: (id: string, body: { kind: DeploymentItem['kind']; id: string; geometry: GeoJSON.Point | GeoJSON.LineString }) =>
    apiClient.post<APIResponse<DeploymentProgress>>(`/designs/${id}/deployment/asbuilt`, body).then(r => r.data.data),

  promote: (id: string) =>
    apiClient.post<APIResponse<PromoteResult>>(`/designs/${id}/promote`).then(r => r.data.data),
};
