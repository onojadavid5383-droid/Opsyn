// ============================================================
// OPSYN NETWORK MAP — server state (TanStack Query).
//
// Keys:
//   ['network','layers']        registry + counts + revision (tile URL)
//   ['network','bounds']        live extent, for "fit to network"
//   ['network','asset', id]     one asset, authoritative detail
//   ['network','search', …]     search results
//
//   ['network','catalogue']     types + attribute specs (static per deploy)
//   ['network','cable', id]     one cable
//   ['network','register', …]   the Infrastructure register pages
//
// A write to the live network (lifecycle change, edit, sync) moves the
// revision, so it invalidates layers (new tile URL → fresh tiles), bounds,
// the register pages and the one object it touched — never the whole cache.
// ============================================================

import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import type { NetAssetType, NetFibreStatus, NetTraceDirection } from '@shared';
import { networkApi, type NetAssetPatch, type NetCablePatch, type NetworkSearchField } from '../../api/network.api';

export const networkKeys = {
  all:       ['network'] as const,
  layers:    ['network', 'layers'] as const,
  bounds:    ['network', 'bounds'] as const,
  catalogue: ['network', 'catalogue'] as const,
  asset:     (id: string) => ['network', 'asset', id] as const,
  cable:     (id: string) => ['network', 'cable', id] as const,
  search:    (q: string, field: NetworkSearchField, type?: NetAssetType) => ['network', 'search', q, field, type ?? ''] as const,
  assetPage: (p: object) => ['network', 'register', 'assets', p] as const,
  cablePage: (p: object) => ['network', 'register', 'cables', p] as const,
};

/** Types, attribute specs and vocabularies — changes only with a deploy */
export function useCatalogue() {
  return useQuery({ queryKey: networkKeys.catalogue, queryFn: networkApi.catalogue, staleTime: Infinity, gcTime: Infinity });
}

export function useCable(id: string | null) {
  return useQuery({
    queryKey: networkKeys.cable(id ?? ''),
    queryFn: () => networkApi.getCable(id!),
    enabled: !!id,
    staleTime: 30_000,
  });
}

export function useUpdateCable(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: NetCablePatch) => networkApi.updateCable(id, patch),
    onSuccess: cable => {
      qc.setQueryData(networkKeys.cable(id), cable);
      qc.invalidateQueries({ queryKey: networkKeys.layers });
      qc.invalidateQueries({ queryKey: ['network', 'register'] });
    },
  });
}

export function useAssetPage(params: { type?: string; status?: string; q?: string; page: number; size: number }) {
  return useQuery({
    queryKey: networkKeys.assetPage(params),
    queryFn: () => networkApi.list(params),
    placeholderData: keepPreviousData,
  });
}

export function useCablePage(params: { category?: string; status?: string; q?: string; page: number; size: number }) {
  return useQuery({
    queryKey: networkKeys.cablePage(params),
    queryFn: () => networkApi.cables(params),
    placeholderData: keepPreviousData,
  });
}

export function useLayerRegistry() {
  return useQuery({ queryKey: networkKeys.layers, queryFn: networkApi.layers, staleTime: 60_000 });
}

export function useNetworkBounds() {
  return useQuery({ queryKey: networkKeys.bounds, queryFn: networkApi.bounds, staleTime: 60_000 });
}

export function useAsset(id: string | null) {
  return useQuery({
    queryKey: networkKeys.asset(id ?? ''),
    queryFn: () => networkApi.get(id!),
    enabled: !!id,
    staleTime: 30_000,
  });
}

export function useAssetSearch(q: string, field: NetworkSearchField, type?: NetAssetType) {
  const term = q.trim();
  return useQuery({
    queryKey: networkKeys.search(term, field, type),
    queryFn: () => networkApi.search(term, field, type),
    enabled: term.length >= 2,
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  });
}

export function useUpdateAsset(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: NetAssetPatch) => networkApi.update(id, patch),
    onSuccess: asset => {
      qc.setQueryData(networkKeys.asset(id), asset);
      qc.invalidateQueries({ queryKey: networkKeys.layers });
      qc.invalidateQueries({ queryKey: networkKeys.bounds });
      qc.invalidateQueries({ queryKey: ['network', 'search'] });
      qc.invalidateQueries({ queryKey: ['network', 'register'] });
    },
  });
}

export function useSyncUploaded() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: networkApi.syncUploaded,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: networkKeys.layers });
      qc.invalidateQueries({ queryKey: networkKeys.bounds });
    },
  });
}

// ── Topology (Phase 3) ───────────────────────────────────────
//   ['network','connections', id]   fed from / feeds
//   ['network','utilisation', id]   capacity in use
//   ['network','trace', id, dir]    one trace
//   ['network','fibres', cableId]   TIA-598 fibre list
// A new or removed link changes both ends' connections and utilisation,
// the tiles (utilisation is in them) and any trace — invalidated by prefix.

export function useConnections(assetId: string | null) {
  return useQuery({
    queryKey: ['network', 'connections', assetId ?? ''],
    queryFn: () => networkApi.connections(assetId!),
    enabled: !!assetId,
  });
}

export function useUtilisation(assetId: string | null) {
  return useQuery({
    queryKey: ['network', 'utilisation', assetId ?? ''],
    queryFn: () => networkApi.utilisation(assetId!),
    enabled: !!assetId,
  });
}

export function useTrace(assetId: string | null, direction: NetTraceDirection) {
  return useQuery({
    queryKey: ['network', 'trace', assetId ?? '', direction],
    queryFn: () => networkApi.trace(assetId!, direction),
    enabled: !!assetId,
    staleTime: 30_000,
  });
}

function invalidateTopology(qc: ReturnType<typeof useQueryClient>) {
  for (const k of ['connections', 'utilisation', 'trace']) qc.invalidateQueries({ queryKey: ['network', k] });
  qc.invalidateQueries({ queryKey: networkKeys.layers });
}

export function useCreateConnection() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: networkApi.createConnection, onSuccess: () => invalidateTopology(qc) });
}

export function useDeleteConnection() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: networkApi.deleteConnection, onSuccess: () => invalidateTopology(qc) });
}

export function useFibres(cableId: string | null) {
  return useQuery({
    queryKey: ['network', 'fibres', cableId ?? ''],
    queryFn: () => networkApi.fibres(cableId!),
    enabled: !!cableId,
  });
}

export function useSetFibre(cableId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ fiberNo, status }: { fiberNo: number; status: NetFibreStatus }) => networkApi.setFibre(cableId, fiberNo, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['network', 'fibres', cableId] }),
  });
}
