// ============================================================
// OPSYN FTTX DESIGNER API — src/api/fttx-designer.api.ts
// Client for the FTTx Designer run lifecycle: create → upload layers →
// execute → poll status → fetch results. Mirrors the backend router at
// app/modules/fttx_designer/router.py exactly — every field name below
// matches that router's Pydantic response schemas (snake_case, no
// camelCase conversion, no {data: ...} envelope — this backend returns
// its Pydantic models directly, same convention as `infrastructureApi`
// in ./index.ts, not the `APIResponse<T>`-wrapped convention some other
// modules use).
// ============================================================

import apiClient from './client';

// ── Domain types ─────────────────────────────────────────────

export type FttxRunStatusValue =
  | 'draft' | 'layers_pending' | 'ready' | 'queued'
  | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled';

export type FttxLayerKey = 'road' | 'homepass' | 'pole' | 'building' | 'pickup';

/** Minimal local GeoJSON typing — this project has no @types/geojson
 * dependency, so this is deliberately narrow (only what the wizard
 * actually reads/writes) rather than a full spec-accurate type. */
export interface GeoJsonFeatureCollection {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    geometry: Record<string, unknown> | null;
    properties?: Record<string, unknown> | null;
  }>;
}

export interface FttxDesignRun {
  id: string;
  tenant_id: string;
  name: string | null;
  status: FttxRunStatusValue;
  config: Record<string, unknown>;
  progress_pct: number;
  progress_message: string | null;
  error_message: string | null;
  celery_task_id: string | null;
  result_summary: Record<string, unknown> | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  uploaded_layer_keys: FttxLayerKey[];
}

export interface FttxRunStatus {
  id: string;
  status: FttxRunStatusValue;
  progress_pct: number;
  progress_message: string | null;
  error_message: string | null;
  result_summary: Record<string, unknown> | null;
}

export interface FttxDesignRunLayer {
  id: string;
  run_id: string;
  layer_key: FttxLayerKey;
  original_filename: string | null;
  feature_count: number | null;
  uploaded_at: string;
  /** Union of attribute/property names sampled from the uploaded
   * GeoJSON's features — lets the wizard offer a real dropdown for
   * "which field holds the homepass count" instead of a blind guess. */
  property_keys: string[];
}

export interface FttxDesignRunResults {
  run_id: string;
  output_layers: Record<string, GeoJsonFeatureCollection>;
  boq_rows: Array<Record<string, unknown>> | null;
  boq_fdt_rows: Array<Record<string, unknown>> | null;
  optical_loss_summary: Record<string, unknown> | null;
  project_identity: Record<string, unknown> | null;
  created_at: string;
}

/** A run is executable once every layer in this set has been uploaded —
 * mirrors _REQUIRED_LAYER_KEYS in router.py. */
export const FTTX_REQUIRED_LAYER_KEYS: FttxLayerKey[] = ['road', 'homepass', 'pole'];
export const FTTX_OPTIONAL_LAYER_KEYS: FttxLayerKey[] = ['building', 'pickup'];
export const FTTX_ALL_LAYER_KEYS: FttxLayerKey[] = [...FTTX_REQUIRED_LAYER_KEYS, ...FTTX_OPTIONAL_LAYER_KEYS];

export const FTTX_TERMINAL_STATUSES: FttxRunStatusValue[] = ['completed', 'failed', 'cancelled'];

// ── Client-side GeoJSON parsing ──────────────────────────────
// The upload endpoint takes a JSON body ({layer_key, original_filename,
// geojson}), not multipart — so a selected file is read and parsed in the
// browser rather than sent as FormData (unlike infrastructureApi's xlsx
// uploads, which are multipart).

export async function readGeoJsonFile(file: File): Promise<GeoJsonFeatureCollection> {
  const text = await file.text();
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error(`"${file.name}" is not valid JSON.`);
  }
  const obj = parsed as Partial<GeoJsonFeatureCollection>;
  if (obj?.type !== 'FeatureCollection' || !Array.isArray(obj.features)) {
    throw new Error(`"${file.name}" is not a GeoJSON FeatureCollection.`);
  }
  return obj as GeoJsonFeatureCollection;
}

export interface FttxDedReport {
  filename: string;
  docx_base64: string;
  warnings_filename: string;
  warnings_text: string;
}

/** Decode a FttxDedReport's two artifacts and trigger a browser download
 * for each — the .docx from its base64 payload (map rendering happens
 * server-side; nothing to build here beyond the Blob), the warnings file
 * from its plain text. Mirrors the plain-text download pattern already
 * used for the run log. */
export function downloadDedReport(report: FttxDedReport): void {
  const binary = atob(report.docx_base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const docxBlob = new Blob([bytes], {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  });
  const docxUrl = URL.createObjectURL(docxBlob);
  const docxLink = document.createElement('a');
  docxLink.href = docxUrl;
  docxLink.download = report.filename;
  docxLink.click();
  URL.revokeObjectURL(docxUrl);

  const warningsBlob = new Blob([report.warnings_text], { type: 'text/plain' });
  const warningsUrl = URL.createObjectURL(warningsBlob);
  const warningsLink = document.createElement('a');
  warningsLink.href = warningsUrl;
  warningsLink.download = report.warnings_filename;
  warningsLink.click();
  URL.revokeObjectURL(warningsUrl);
}

// ── API ────────────────────────────────────────────────────────

export const fttxDesignerApi = {
  listRuns: () =>
    apiClient.get<FttxDesignRun[]>('/fttx-designer/runs').then(r => r.data),

  getRun: (runId: string) =>
    apiClient.get<FttxDesignRun>(`/fttx-designer/runs/${runId}`).then(r => r.data),

  createRun: (payload: { name?: string | null; config?: Record<string, unknown> }) =>
    apiClient.post<FttxDesignRun>('/fttx-designer/runs', payload).then(r => r.data),

  updateRunConfig: (runId: string, payload: { name?: string | null; config: Record<string, unknown> }) =>
    apiClient.put<FttxDesignRun>(`/fttx-designer/runs/${runId}/config`, payload).then(r => r.data),

  uploadLayer: (
    runId: string,
    layerKey: FttxLayerKey,
    geojson: GeoJsonFeatureCollection,
    originalFilename?: string | null,
  ) =>
    apiClient
      .post<FttxDesignRunLayer>(`/fttx-designer/runs/${runId}/layers/${layerKey}`, {
        layer_key: layerKey,
        original_filename: originalFilename ?? null,
        geojson,
      })
      .then(r => r.data),

  listLayers: (runId: string) =>
    apiClient.get<FttxDesignRunLayer[]>(`/fttx-designer/runs/${runId}/layers`).then(r => r.data),

  getInputLayerGeoJson: (runId: string, layerKey: FttxLayerKey) =>
    apiClient.get<GeoJsonFeatureCollection>(`/fttx-designer/runs/${runId}/layers/${layerKey}/geojson`).then(r => r.data),

  executeRun: (runId: string) =>
    apiClient.post<FttxDesignRun>(`/fttx-designer/runs/${runId}/execute`).then(r => r.data),

  cancelRun: (runId: string) =>
    apiClient.post<FttxDesignRun>(`/fttx-designer/runs/${runId}/cancel`).then(r => r.data),

  rerunFailedRun: (runId: string, configOverrides: Record<string, unknown> = {}) =>
    apiClient.post<FttxDesignRun>(`/fttx-designer/runs/${runId}/rerun`, { config_overrides: configOverrides }).then(r => r.data),

  getStatus: (runId: string) =>
    apiClient.get<FttxRunStatus>(`/fttx-designer/runs/${runId}/status`).then(r => r.data),

  getResults: (runId: string) =>
    apiClient.get<FttxDesignRunResults>(`/fttx-designer/runs/${runId}/results`).then(r => r.data),

  getLog: (runId: string) =>
    apiClient.get<{ log_text: string | null }>(`/fttx-designer/runs/${runId}/log`).then(r => r.data),

  deleteRun: (runId: string) =>
    apiClient.delete(`/fttx-designer/runs/${runId}`).then(r => r.data),

  generateDedReport: (runId: string) =>
    // Longer timeout than the client default (30s) — map rendering
    // involves real basemap tile fetches on the backend and can take a
    // while longer than a typical API call.
    apiClient
      .post<FttxDedReport>(`/fttx-designer/runs/${runId}/ded-report`, {}, { timeout: 120_000 })
      .then(r => r.data),
};
