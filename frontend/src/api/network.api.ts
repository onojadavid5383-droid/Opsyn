// ============================================================
// OPSYN — Network GIS API (backend app/modules/network + app/modules/gis)
// Every call unwraps the {success, data} envelope. Types: @shared.
// ============================================================

import type {
  APIResponse, GisBounds, GisLayerRegistry, NetAsset, NetAssetPage, NetAssetSummary,
  NetAssetConnections, NetAssetType, NetBackfillResult, NetCable, NetCablePage, NetCatalogue,
  NetConnection, NetConnectionType, NetFibre, NetFibreStatus, NetLifecycleStatus, NetTrace,
  NetTraceDirection, NetUtilisation, UploadTypeSpec,
} from '@shared';
import apiClient from './client';

export type NetworkSearchField = 'any' | 'code' | 'name';

export interface NetAssetPatch {
  asset_code?:       string;
  name?:             string | null;
  description?:      string | null;
  lifecycle_status?: NetLifecycleStatus;
  attributes?:       Record<string, unknown>;
  capacity?:         number | null;
  used_capacity?:    number | null;
}

export interface NetCablePatch {
  asset_code?:        string;
  name?:              string | null;
  description?:       string | null;
  lifecycle_status?:  NetLifecycleStatus;
  fiber_count?:       number | null;
  installation_type?: string | null;
  attributes?:        Record<string, unknown>;
}

export const networkApi = {
  catalogue: () =>
    apiClient.get<APIResponse<NetCatalogue>>('/network/catalogue').then(r => r.data.data),

  cables: (params: { category?: string; status?: string; q?: string; page?: number; size?: number }) =>
    apiClient.get<APIResponse<NetCablePage>>('/network/cables', { params }).then(r => r.data.data),

  getCable: (id: string) =>
    apiClient.get<APIResponse<NetCable>>(`/network/cables/${id}`).then(r => r.data.data),

  updateCable: (id: string, patch: NetCablePatch) =>
    apiClient.patch<APIResponse<NetCable>>(`/network/cables/${id}`, patch).then(r => r.data.data),

  // ── Topology (Phase 3) ──
  connections: (assetId: string) =>
    apiClient.get<APIResponse<NetAssetConnections>>(`/network/assets/${assetId}/connections`).then(r => r.data.data),

  trace: (assetId: string, direction: NetTraceDirection) =>
    apiClient.get<APIResponse<NetTrace>>(`/network/assets/${assetId}/trace`, { params: { direction } }).then(r => r.data.data),

  utilisation: (assetId: string) =>
    apiClient.get<APIResponse<NetUtilisation>>(`/network/assets/${assetId}/utilisation`).then(r => r.data.data),

  createConnection: (body: { source_asset_id: string; dest_asset_id: string; connection_type: NetConnectionType; via_cable_id?: string }) =>
    apiClient.post<APIResponse<NetConnection>>('/network/connections', body).then(r => r.data.data),

  deleteConnection: (id: string) =>
    apiClient.delete(`/network/connections/${id}`).then(() => undefined),

  fibres: (cableId: string) =>
    apiClient.get<APIResponse<NetFibre[]>>(`/network/cables/${cableId}/fibers`).then(r => r.data.data),

  setFibre: (cableId: string, fiberNo: number, status: NetFibreStatus) =>
    apiClient.patch<APIResponse<NetFibre>>(`/network/cables/${cableId}/fibers/${fiberNo}`, { status }).then(r => r.data.data),

  uploadTypes: () =>
    apiClient.get<APIResponse<UploadTypeSpec[]>>('/infrastructure/upload-types').then(r => r.data.data),

  uploadTemplate: (key: string) =>
    apiClient.get<Blob>(`/infrastructure/upload-types/${key}/template`, { responseType: 'blob' }).then(r => r.data),

  layers: () =>
    apiClient.get<APIResponse<GisLayerRegistry>>('/gis/layers').then(r => r.data.data),

  bounds: () =>
    apiClient.get<APIResponse<GisBounds>>('/gis/bounds').then(r => r.data.data),

  search: (q: string, field: NetworkSearchField = 'any', type?: NetAssetType, limit = 12) =>
    apiClient.get<APIResponse<NetAssetSummary[]>>('/network/search', { params: { q, field, type, limit } })
      .then(r => r.data.data),

  list: (params: { type?: string; status?: string; bbox?: string; q?: string; page?: number; size?: number }) =>
    apiClient.get<APIResponse<NetAssetPage>>('/network/assets', { params }).then(r => r.data.data),

  get: (id: string) =>
    apiClient.get<APIResponse<NetAsset>>(`/network/assets/${id}`).then(r => r.data.data),

  update: (id: string, patch: NetAssetPatch) =>
    apiClient.patch<APIResponse<NetAsset>>(`/network/assets/${id}`, patch).then(r => r.data.data),

  syncUploaded: () =>
    apiClient.post<APIResponse<NetBackfillResult>>('/network/assets/sync-uploaded').then(r => r.data.data),
};

/** Absolute tile URL template for MapLibre (the API base may be relative or absolute). */
export function tileUrlTemplate(registry: GisLayerRegistry): string {
  const base = (apiClient.defaults.baseURL ?? '').replace(/\/$/, '');
  const absolute = new URL(`${base}${registry.tiles.url_template}`, window.location.origin).toString();
  // URL() percent-encodes the braces; MapLibre needs them literal
  return `${decodeURI(absolute)}?rev=${registry.revision}`;
}

/** Only API requests get the bearer token — never basemap tile hosts. */
export function isApiUrl(url: string): boolean {
  const base = new URL((apiClient.defaults.baseURL ?? ''), window.location.origin).toString();
  return url.startsWith(base);
}
