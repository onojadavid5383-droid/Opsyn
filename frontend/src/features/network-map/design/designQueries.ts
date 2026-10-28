// ============================================================
// OPSYN DESIGN — server state (TanStack Query), Network GIS Phase 4.
//
// Keys, all under ['design', id]:
//   ['designs', projectId]        a project's designs
//   ['design', id]                the design (status, boundary, counts)
//   ['design', id, 'inputs']      input layers + counts
//   ['design', id, 'input', key]  one input layer's GeoJSON
//   ['design', id, 'features']    the working set GeoJSON
//   ['design', id, 'summary']     the summary strip
//   ['design', id, 'boq']         quantities + street BOQ
//   ['design', id, 'validation']  stored issues
//   ['design', id, 'generate']    the latest auto run (polled while it runs)
//   ['design', id, 'importable']  completed FTTx runs that can be imported
//   ['design', id, 'ops']         the manual edit log + undo/redo state (P6)
//   ['design', id, 'versions']    versions; ['design', id, 'version', n] one of them
//   ['design', id, 'compare', a, b]  two compared; ['design', id, 'history'] (P8)
//   ['history', entityId]         one asset / cable's audit trail (P8)
//   ['design', id, 'approvals']   approval requests + the deployment gate (P9)
//   ['design', id, 'deployment']  progress, roll-ups, variance (P10)
// An input upload changes inputs, that layer, the summary, BOQ and the
// design's counts/bbox; a boundary change changes the design and
// validation (boundary checks). A new version (auto run finished, run
// imported) changes everything under ['design', id]. Nothing wider.
// ============================================================

import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import type { DesignDelta, DesignInputLayerKey, DesignOperationBody, DesignOpResult, DesignRunStatus } from '@shared';
import { useDesignMapStore } from './designStore';
import { designApi, type DesignPatch } from '../../../api/design.api';

export const designKeys = {
  list:       (projectId: string) => ['designs', projectId] as const,
  design:     (id: string) => ['design', id] as const,
  inputs:     (id: string) => ['design', id, 'inputs'] as const,
  input:      (id: string, key: DesignInputLayerKey) => ['design', id, 'input', key] as const,
  features:   (id: string) => ['design', id, 'features'] as const,
  summary:    (id: string) => ['design', id, 'summary'] as const,
  boq:        (id: string) => ['design', id, 'boq'] as const,
  validation: (id: string) => ['design', id, 'validation'] as const,
  generate:   (id: string) => ['design', id, 'generate'] as const,
  importable: (id: string) => ['design', id, 'importable'] as const,
  ops:        (id: string) => ['design', id, 'ops'] as const,
  versions:   (id: string) => ['design', id, 'versions'] as const,
  version:    (id: string, no: number) => ['design', id, 'version', no] as const,
  compare:    (id: string, a: number, b: number) => ['design', id, 'compare', a, b] as const,
  history:    (id: string) => ['design', id, 'history'] as const,
  approvals:  (id: string) => ['design', id, 'approvals'] as const,
  deployment: (id: string) => ['design', id, 'deployment'] as const,
};

export const RUN_ACTIVE: DesignRunStatus[] = ['queued', 'running', 'cancelling'];
const POLL_MS = 1500;

export function useProjectDesigns(projectId: string) {
  return useQuery({ queryKey: designKeys.list(projectId), queryFn: () => designApi.list(projectId) });
}

export function useCreateDesign(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description?: string }) => designApi.create(projectId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: designKeys.list(projectId) }),
  });
}

export function useDesign(id: string | null) {
  return useQuery({ queryKey: designKeys.design(id ?? ''), queryFn: () => designApi.get(id!), enabled: !!id });
}

export function useDesignInputs(id: string | null) {
  return useQuery({ queryKey: designKeys.inputs(id ?? ''), queryFn: () => designApi.inputs(id!), enabled: !!id });
}

export function useDesignInputFeatures(id: string | null, key: DesignInputLayerKey, enabled: boolean) {
  return useQuery({
    queryKey: designKeys.input(id ?? '', key),
    queryFn: () => designApi.inputFeatures(id!, key),
    enabled: !!id && enabled,
    staleTime: 60_000,
  });
}

export function useDesignFeatures(id: string | null) {
  return useQuery({ queryKey: designKeys.features(id ?? ''), queryFn: () => designApi.features(id!), enabled: !!id });
}

export function useDesignSummary(id: string | null) {
  return useQuery({ queryKey: designKeys.summary(id ?? ''), queryFn: () => designApi.summary(id!), enabled: !!id });
}

export function useDesignBoq(id: string | null, enabled: boolean) {
  // Runs the engine: kept until an input or working-set change invalidates it
  return useQuery({
    queryKey: designKeys.boq(id ?? ''), queryFn: () => designApi.boq(id!), enabled: !!id && enabled, staleTime: 5 * 60_000,
  });
}

export function useDesignValidation(id: string | null) {
  return useQuery({ queryKey: designKeys.validation(id ?? ''), queryFn: () => designApi.validation(id!), enabled: !!id });
}

export function useUpdateDesign(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: DesignPatch) => designApi.update(id, patch),
    onSuccess: design => {
      qc.setQueryData(designKeys.design(id), design);
      qc.invalidateQueries({ queryKey: ['designs', design.project_id] });
    },
  });
}

export function useBoundaryFromInputs(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => designApi.boundaryFromInputs(id),
    onSuccess: design => qc.setQueryData(designKeys.design(id), design),
  });
}

export function useUploadInputs(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ layer, file, mode }: { layer: DesignInputLayerKey; file: File; mode: 'replace' | 'append' }) =>
      designApi.uploadInputs(id, layer, file, mode),
    onSuccess: (res, vars) => {
      if (res.status !== 'saved') return;
      for (const key of [designKeys.inputs(id), designKeys.input(id, vars.layer), designKeys.summary(id),
                         designKeys.boq(id), designKeys.design(id)]) {
        qc.invalidateQueries({ queryKey: key });
      }
    },
  });
}

export function useRemoveInputs(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (layer: DesignInputLayerKey) => designApi.removeInputs(id, layer),
    onSuccess: (_r, layer) => {
      for (const key of [designKeys.inputs(id), designKeys.input(id, layer), designKeys.summary(id),
                         designKeys.boq(id), designKeys.design(id)]) {
        qc.invalidateQueries({ queryKey: key });
      }
    },
  });
}

export function useValidateDesign(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => designApi.validate(id),
    onSuccess: result => {
      qc.setQueryData(designKeys.validation(id), result);
      qc.invalidateQueries({ queryKey: designKeys.summary(id) });
    },
  });
}

// ── Auto design (Phase 5) ────────────────────────────────────

/** A new version replaced the working set: everything about the design is stale */
export function refreshDesign(qc: QueryClient, id: string, projectId?: string) {
  void qc.invalidateQueries({ queryKey: ['design', id] });
  if (projectId) void qc.invalidateQueries({ queryKey: designKeys.list(projectId) });
}

export function useGenerateStatus(id: string | null) {
  return useQuery({
    queryKey: designKeys.generate(id ?? ''),
    queryFn: () => designApi.generateStatus(id!),
    enabled: !!id,
    refetchInterval: q => (q.state.data && RUN_ACTIVE.includes(q.state.data.status) ? POLL_MS : false),
  });
}

export function useGenerate(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { engine_config?: Record<string, unknown>; replace: boolean }) => designApi.generate(id, body),
    onSuccess: status => {
      qc.setQueryData(designKeys.generate(id), status);
      void qc.invalidateQueries({ queryKey: designKeys.design(id), exact: true });     // settings kept on the design
    },
  });
}

export function useCancelGenerate(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => designApi.cancelGenerate(id),
    onSuccess: status => qc.setQueryData(designKeys.generate(id), status),
  });
}

export function useImportableRuns(id: string | null, enabled: boolean) {
  return useQuery({ queryKey: designKeys.importable(id ?? ''), queryFn: () => designApi.importableRuns(id!), enabled: !!id && enabled });
}

export function useImportRun(id: string, projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, replace }: { runId: string; replace: boolean }) => designApi.importRun(id, runId, replace),
    onSuccess: () => refreshDesign(qc, id, projectId),
  });
}

// ── Manual design (Phase 6) ──────────────────────────────────

export function useOperationLog(id: string | null) {
  return useQuery({ queryKey: designKeys.ops(id ?? ''), queryFn: () => designApi.operations(id!), enabled: !!id });
}

/** The working set with an edit's delta applied: removed ids out, changed features in (Phase 7) */
export function patchFeatures(old: GeoJSON.FeatureCollection | undefined, delta: DesignDelta): GeoJSON.FeatureCollection | undefined {
  if (!old) return old;
  const gone = new Set([...delta.removed.assets, ...delta.removed.cables, ...delta.features.map(f => String(f.properties?.id))]);
  return { ...old, features: [...old.features.filter(f => !gone.has(String(f.properties?.id))), ...delta.features] };
}

/**
 * After an edit, undo or redo. The answer carries the summary, undo state
 * and the delta: the map is patched from it (no reload of the working set);
 * the street BOQ (engine) and the issue list refetch.
 */
function afterEdit(qc: QueryClient, id: string, res: DesignOpResult) {
  qc.setQueryData(designKeys.summary(id), res.summary);
  qc.setQueryData(designKeys.ops(id), (old: object | undefined) => ({ ...(old ?? { operations: [] }), ...res.history }));
  if (res.delta) {
    qc.setQueryData(designKeys.features(id), (old: GeoJSON.FeatureCollection | undefined) => patchFeatures(old, res.delta));
    useDesignMapStore.getState().setChange({ seq: Date.now(), label: res.operation.label, delta: res.delta,
      rerouted: res.operation.rerouted ?? [] });
  } else {
    void qc.invalidateQueries({ queryKey: designKeys.features(id), exact: true });     // no delta: reload the map
  }
  for (const key of [designKeys.validation(id), designKeys.boq(id), designKeys.design(id), designKeys.ops(id)]) {
    void qc.invalidateQueries({ queryKey: key, exact: true });
  }
}

export function useOperate(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DesignOperationBody) => designApi.operate(id, body),
    onSuccess: res => afterEdit(qc, id, res),
  });
}

export function useUndoRedo(id: string) {
  const qc = useQueryClient();
  const undo = useMutation({ mutationFn: () => designApi.undo(id), onSuccess: res => afterEdit(qc, id, res) });
  const redo = useMutation({ mutationFn: () => designApi.redo(id), onSuccess: res => afterEdit(qc, id, res) });
  return { undo, redo };
}

// ── Versions and audit (Phase 8) ─────────────────────────────

export function useVersions(id: string | null, enabled = true) {
  return useQuery({ queryKey: designKeys.versions(id ?? ''), queryFn: () => designApi.versions(id!), enabled: !!id && enabled });
}

export function useSaveVersion(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (label: string) => designApi.saveVersion(id, label),
    onSuccess: res => {
      qc.setQueryData(designKeys.versions(id), res.versions);
      for (const key of [designKeys.design(id), designKeys.ops(id), designKeys.history(id)]) {
        void qc.invalidateQueries({ queryKey: key, exact: true });
      }
    },
  });
}

/** A version's features. Frozen versions never change; the current one is invalidated with the design */
export function useVersionFeatures(id: string | null, no: number | null) {
  return useQuery({
    queryKey: designKeys.version(id ?? '', no ?? 0), queryFn: () => designApi.versionFeatures(id!, no!),
    enabled: !!id && no !== null,
  });
}

export function useCompare(id: string | null, pair: { from: number; to: number } | null) {
  return useQuery({
    queryKey: designKeys.compare(id ?? '', pair?.from ?? 0, pair?.to ?? 0),
    queryFn: () => designApi.compare(id!, pair!.from, pair!.to), enabled: !!id && !!pair,
  });
}

export function useRestore(id: string, projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (no: number) => designApi.restore(id, no),
    onSuccess: () => refreshDesign(qc, id, projectId),       // a new version: everything about the design moved
  });
}

export function useDesignHistory(id: string | null, enabled: boolean) {
  return useQuery({ queryKey: designKeys.history(id ?? ''), queryFn: () => designApi.history(id!), enabled: !!id && enabled });
}

export function useEntityHistory(entityId: string | null) {
  return useQuery({ queryKey: ['history', entityId ?? ''], queryFn: () => designApi.entityHistory(entityId!), enabled: !!entityId });
}

// ── Approval (Phase 9) ───────────────────────────────────────

export function useApprovals(id: string | null) {
  return useQuery({ queryKey: designKeys.approvals(id ?? ''), queryFn: () => designApi.approvals(id!), enabled: !!id });
}

/**
 * Submitting, deciding, withdrawing and reopening can change the design's
 * status and start a version, so the design, its versions and the history
 * refresh with the approvals.
 */
export function useApprovalAction<T>(id: string, fn: (arg: T) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      for (const key of [designKeys.approvals(id), designKeys.design(id), designKeys.versions(id), designKeys.history(id),
                         designKeys.ops(id)]) {
        void qc.invalidateQueries({ queryKey: key, exact: true });
      }
    },
  });
}

export function useBoqDiff(requestId: string | null) {
  return useQuery({ queryKey: ['boq-diff', requestId ?? ''], queryFn: () => designApi.boqDiff(requestId!), enabled: !!requestId });
}

// ── Deployment (Phase 10) ────────────────────────────────────

export function useDeployment(id: string | null) {
  return useQuery({ queryKey: designKeys.deployment(id ?? ''), queryFn: () => designApi.deployment(id!), enabled: !!id });
}

/**
 * A field step or an as-built capture changes the rows' lifecycle and
 * geometry: the progress, the map and the history refresh. Starting and
 * promoting change the design itself, so everything about it refreshes
 * (`whole`).
 */
export function useDeploymentAction<T, R = unknown>(id: string, fn: (arg: T) => Promise<R>, whole = false) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      if (whole) { refreshDesign(qc, id); return; }
      for (const key of [designKeys.deployment(id), designKeys.features(id), designKeys.history(id), designKeys.summary(id)]) {
        void qc.invalidateQueries({ queryKey: key, exact: true });
      }
    },
  });
}
