// ============================================================
// OPSYN useWorkflows HOOKS — src/hooks/useWorkflows.ts
// React Query hooks for the Workflow Builder
// ============================================================

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { workflowsApi } from '../api/workflows.api';
import type { AddEdgePayload, UpdateEdgePayload, CreateWorkflowPayload } from '../types/workflow.types';

export const WORKFLOWS_KEY = 'workflows';

export function useWorkflows(activeOnly = true) {
  return useQuery({
    queryKey: [WORKFLOWS_KEY, { activeOnly }],
    queryFn: () => workflowsApi.list(activeOnly),
  });
}

export function useWorkflow(id: string | null) {
  return useQuery({
    queryKey: [WORKFLOWS_KEY, id],
    queryFn: () => workflowsApi.get(id!),
    enabled: !!id,
  });
}

export function useCreateWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateWorkflowPayload) => workflowsApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: [WORKFLOWS_KEY] }),
  });
}

export function useUpdateWorkflow(workflowId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name?: string; description?: string }) =>
      workflowsApi.update(workflowId, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: [WORKFLOWS_KEY] }),
  });
}

export function useDeleteWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => workflowsApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: [WORKFLOWS_KEY] }),
  });
}

export function useAddEdge(workflowId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: AddEdgePayload) => workflowsApi.addEdge(workflowId, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: [WORKFLOWS_KEY, workflowId] }),
  });
}

export function useUpdateEdge(workflowId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ edgeId, payload }: { edgeId: string; payload: UpdateEdgePayload }) =>
      workflowsApi.updateEdge(workflowId, edgeId, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: [WORKFLOWS_KEY, workflowId] }),
  });
}

export function useRemoveEdge(workflowId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (edgeId: string) => workflowsApi.removeEdge(workflowId, edgeId),
    onSuccess: () => qc.invalidateQueries({ queryKey: [WORKFLOWS_KEY, workflowId] }),
  });
}

export function useValidateWorkflow(workflowId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => workflowsApi.validate(workflowId),
    onSuccess: () => qc.invalidateQueries({ queryKey: [WORKFLOWS_KEY, workflowId] }),
  });
}

export function usePublishWorkflow(workflowId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => workflowsApi.publish(workflowId),
    onSuccess: () => qc.invalidateQueries({ queryKey: [WORKFLOWS_KEY] }),
  });
}

export function useCloneWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => workflowsApi.clone(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: [WORKFLOWS_KEY] }),
  });
}
