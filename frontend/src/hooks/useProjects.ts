// ============================================================
// OPSYN useProjects HOOK
// React Query hooks for project operations
// ============================================================

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { projectsApi } from '../api/projects.api';

export function useProjects() {
  return useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: ['projects', id],
    queryFn: () => projectsApi.get(id),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
  });
}

export function useProjectPipeline(projectId: string) {
  return useQuery({
    queryKey: ['pipeline', projectId],
    queryFn: () => projectsApi.getPipeline(projectId),
    staleTime: 60_000, // 1 minute
    enabled: !!projectId,
  });
}

export function useAdvanceStage(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ comment }: { comment?: string }) => projectsApi.advanceStage(projectId, comment),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline', projectId] });
      qc.invalidateQueries({ queryKey: ['projects'] });
    },
  });
}

export function usePushBackStage(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ reason, comment }: { reason: string; comment?: string }) =>
      projectsApi.pushBackStage(projectId, reason, comment),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline', projectId] });
    },
  });
}

export function useAddStageComment(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ stageId, body, commentType }: { stageId: string; body: string; commentType: string }) =>
      projectsApi.addStageComment(projectId, stageId, body, commentType),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline', projectId] });
    },
  });
}

export function usePipelineTemplates() {
  return useQuery({
    queryKey: ['pipeline-templates'],
    queryFn: projectsApi.getPipelineTemplates,
    staleTime: 10 * 60 * 1000, // 10 minutes
  });
}

export function useApproveStage(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ stageId, notes }: { stageId: string; notes?: string }) =>
      projectsApi.approveStage(projectId, stageId, notes),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline', projectId] });
    },
  });
}

export function useProjectProgress(projectId: string) {
  return useQuery({
    queryKey: ['project-progress', projectId],
    queryFn: () => projectsApi.getProgress(projectId),
    enabled: !!projectId,
    staleTime: 30_000,
  });
}