// ============================================================
// OPSYN PROJECT DETAIL PAGE — S2.2.2  (Stage 7 token update)
// PRJ badge · Pipeline stepper · Timeline · Sidebar
// ============================================================

import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useProject, useProjectPipeline, useAdvanceStage, usePushBackStage, useProjectProgress } from '../../hooks/useProjects';
import { PipelineStageRail } from '../../components/projects/PipelineStageRail';
import { AdvanceStageModal } from '../../components/projects/AdvanceStageModal';
import { PushBackModal } from '../../components/projects/PushBackModal';
import { ActivityTimeline } from '../../components/timeline';
import { projectsApi, settingsApi } from '../../api/index';
import { useUIStore } from '../../store/ui.store';
import type { ProjectPipelineResponse } from '@shared';
import type { ApiError } from '../../api/client';
import { GlassModal, GlassSelect } from '../../components/glass';
import { ProjectDesigns } from '../../features/network-map/design/ProjectDesigns';
import { useUrlTab } from '../../hooks/useUrlTab';

function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, message?: string) => addToast({ type: 'success', title, message }),
    error:   (title: string, message?: string) => addToast({ type: 'error',   title, message }),
  };
}

// ── Project type labels ───────────────────────────────────────

const PROJECT_TYPE_LABELS: Record<string, string> = {
  internal:         'Internal',
  external:         'External',
  cable_upgrade:    'Cable Upgrade',
  olt_installation: 'OLT Installation',
  procurement:      'Procurement',
};

const PROJECT_TYPE_COLORS: Record<string, string> = {
  internal:         'rgba(6,182,212,.15)',
  external:         'rgba(167,139,250,.15)',
  cable_upgrade:    'rgba(251,191,36,.15)',
  olt_installation: 'rgba(34,197,94,.15)',
  procurement:      'rgba(248,113,113,.15)',
};

const PIPELINE_STATUS_COLORS: Record<string, string> = {
  not_started: 'var(--color-text-muted)',
  active:      'var(--color-teal)',
  stalled:     'var(--color-amber)',
  completed:   'var(--color-green)',
  cancelled:   'var(--color-red)',
};

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const toast    = useToast();
  const qc       = useQueryClient();
  const [showAdvance,        setShowAdvance]        = useState(false);
  const [showPushBack,       setShowPushBack]       = useState(false);
  const [activeTab,          setActiveTab]          = useUrlTab(['timeline', 'pipeline', 'designs'] as const, 'timeline');
  const [showStartPipeline,  setShowStartPipeline]  = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState('');

  const { data: project, isLoading: projLoading } = useProject(id!);
  const { data: pipelineRes }                     = useProjectPipeline(id!);
  const { data: progressRes }                     = useProjectProgress(id!);
  const { data: templates = [] }                  = useQuery({
    queryKey: ['pipeline-templates'],
    queryFn:  () => settingsApi.getPipelines(),
    enabled:  showStartPipeline,
  });
  const pipeline: ProjectPipelineResponse | undefined = (pipelineRes as any)?.data ?? pipelineRes;

  const advanceMutation  = useAdvanceStage(id!);
  const pushBackMutation = usePushBackStage(id!);

  const startPipelineMutation = useMutation({
    mutationFn: (templateId: string) => projectsApi.startPipeline(id!, { template_id: templateId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline', id] });
      qc.invalidateQueries({ queryKey: ['project', id] });
      setShowStartPipeline(false);
      toast.success('Pipeline started', 'The pipeline is now active.');
    },
    onError: (e: ApiError) => toast.error('Failed to start pipeline', e?.detail ?? e?.message),
  });

  if (projLoading) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>Loading project…</span>
      </div>
    );
  }

  if (!project) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: 'var(--color-red)', fontSize: 13 }}>Project not found.</span>
      </div>
    );
  }

  const allStages    = pipeline?.allStages ?? [];
  const currentStage = pipeline?.currentStage ?? null;
  const canAdvance   = pipeline?.canAdvance ?? false;
  const canPushBack  = pipeline?.canPushBack ?? false;
  const nextStageIdx = allStages.findIndex(s => s.id === currentStage?.id) + 1;
  const nextStage    = allStages[nextStageIdx] ?? null;
  const prevStage    = allStages[Math.max(0, nextStageIdx - 2)] ?? null;

  const handleAdvance = async (comment?: string) => {
    try {
      await advanceMutation.mutateAsync({ comment });
      setShowAdvance(false);
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const missing = (detail as { missing_required_forms?: string[] } | undefined)?.missing_required_forms;
      toast.error('Cannot advance stage', missing?.length
        ? `Complete the required form${missing.length === 1 ? '' : 's'}: ${missing.join(', ')}`
        : typeof detail === 'string' ? detail : 'Check stage fields, forms, and approvals.');
    }
  };

  const handlePushBack = async (reason: string, comment?: string) => {
    await pushBackMutation.mutateAsync({ reason, comment });
    setShowPushBack(false);
  };

  const typeLabel = PROJECT_TYPE_LABELS[project.project_type] ?? project.project_type;
  const typeBg    = PROJECT_TYPE_COLORS[project.project_type] ?? 'rgba(100,116,139,.08)';
  const pipeColor = PIPELINE_STATUS_COLORS[project.pipeline_status ?? 'not_started'] ?? 'var(--color-text-muted)';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', background: 'var(--color-surface)' }}>

      {/* ── Header ── */}
      <div style={{
        padding: '16px 24px 12px',
        borderBottom: '1px solid var(--color-border)',
        background: 'var(--surface)',
        flexShrink: 0,
      }}>
        {/* Back link */}
        <div
          onClick={() => navigate('/projects')}
          style={{ fontSize: 11, color: 'var(--color-text-muted)', cursor: 'pointer', marginBottom: 8, display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          ← Projects
        </div>

        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div style={{ flex: 1 }}>
            {/* PRJ ticket badge */}
            {project.ticket_number && (
              <div
                title="Click to copy"
                onClick={() => navigator.clipboard.writeText(project.ticket_number!)}
                style={{
                  display: 'inline-flex', alignItems: 'center',
                  fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700,
                  color: 'var(--color-teal)', letterSpacing: '0.06em',
                  padding: '2px 8px', borderRadius: 4,
                  background: 'rgba(0,194,168,.08)', border: '1px solid rgba(0,194,168,.2)',
                  marginBottom: 6, cursor: 'copy',
                }}
              >
                {project.ticket_number}
              </div>
            )}

            <h1 style={{ fontSize: 18, fontWeight: 800, color: 'var(--color-text-primary)', margin: 0, letterSpacing: '-.02em' }}>
              {project.name}
            </h1>
            {project.description && (
              <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '4px 0 0', lineHeight: 1.5 }}>
                {project.description}
              </p>
            )}

            {/* Badges row */}
            <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: typeBg, color: 'var(--color-text-primary)' }}>
                {typeLabel}
              </span>
              <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: 'var(--color-surface-2)', color: pipeColor }}>
                {(project.pipeline_status ?? 'not_started').replace('_', ' ').toUpperCase()}
              </span>
              {(progressRes?.data?.progress ?? project.completion_pct) > 0 && (
                <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: 'rgba(22,163,74,.08)', color: 'var(--color-green)' }}>
                  {progressRes?.data?.progress ?? project.completion_pct}% complete
                </span>
              )}
            </div>
          </div>

          {/* Pipeline action buttons */}
          <div style={{ display: 'flex', gap: 8, flexShrink: 0, marginTop: 4 }}>
            {!pipeline && (
              <button
                onClick={() => setShowStartPipeline(true)}
                style={{
                  padding: '6px 14px', borderRadius: 7, border: 'none',
                  background: 'var(--brand)', color: 'var(--brand-contrast)', fontSize: 11, fontWeight: 700,
                  cursor: 'pointer', fontFamily: 'var(--font-body)',
                }}
              >
                Start Pipeline
              </button>
            )}
            {pipeline && canPushBack && (
              <button
                onClick={() => setShowPushBack(true)}
                style={{
                  padding: '6px 12px', borderRadius: 7, border: '1px solid var(--color-border)',
                  background: 'transparent', color: 'var(--color-amber)', fontSize: 11, fontWeight: 700,
                  cursor: 'pointer', fontFamily: 'var(--font-body)',
                }}
              >
                ← Push Back
              </button>
            )}
            {pipeline && canAdvance && (
              <button
                onClick={() => setShowAdvance(true)}
                style={{
                  padding: '6px 14px', borderRadius: 7, border: 'none',
                  background: 'var(--brand)', color: 'var(--brand-contrast)', fontSize: 11, fontWeight: 700,
                  cursor: 'pointer', fontFamily: 'var(--font-body)',
                }}
              >
                Advance Stage →
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Pipeline Stage Rail ── */}
      {allStages.length > 0 && (
        <div style={{ padding: '12px 24px', borderBottom: '1px solid var(--color-border)', flexShrink: 0, background: 'var(--surface)' }}>
          <PipelineStageRail
            stages={allStages}
            currentStageId={currentStage?.id}
            callerDeptId={undefined}
            onStageClick={() => {}}
          />
        </div>
      )}

      {/* ── Tabs ── */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--color-border)', padding: '0 24px', background: 'var(--surface)', flexShrink: 0 }}>
        {(['timeline', 'pipeline', 'designs'] as const).map(tab => (
          <div
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              padding: '10px 14px', fontSize: 11, fontWeight: activeTab === tab ? 700 : 400,
              color: activeTab === tab ? 'var(--color-teal)' : 'var(--color-text-muted)',
              borderBottom: activeTab === tab ? '2px solid var(--color-teal)' : '2px solid transparent',
              cursor: 'pointer', marginBottom: -1, textTransform: 'capitalize',
            }}
          >
            {tab === 'pipeline' ? 'Stage Comments' : tab === 'designs' ? 'Network designs' : 'Timeline'}
          </div>
        ))}
      </div>

      {/* ── Body ── */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

        {/* Main content */}
        <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
          {activeTab === 'timeline' && (
            <ActivityTimeline entityType="project" entityId={id!} canComment />
          )}
          {activeTab === 'designs' && <ProjectDesigns projectId={id!} />}
          {activeTab === 'pipeline' && currentStage && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '.1em', marginBottom: 12 }}>
                Current Stage: {currentStage.stageName}
              </div>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                Comments for this stage can be added from the Pipeline page.
              </div>
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div style={{
          width: 240, flexShrink: 0, borderLeft: '1px solid var(--color-border)',
          padding: 20, overflow: 'auto', background: 'var(--surface)',
        }}>
          <SidebarField label="Department" value={project.department_id ? '—' : '—'} />
          {project.due_date && (
            <SidebarField label="Due Date" value={new Date(project.due_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })} />
          )}
          {currentStage && (
            <SidebarField label="Current Stage" value={`${currentStage.stageName} (${currentStage.departmentName})`} />
          )}
          <SidebarField label="Pipeline" value={(project.pipeline_status ?? 'not_started').replace(/_/g, ' ')} />

          {/* Completion progress bar — live data from /progress endpoint */}
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '.1em', marginBottom: 6 }}>
              Completion
            </div>
            <div style={{ height: 6, borderRadius: 3, background: 'var(--color-border)', overflow: 'hidden' }}>
              <div style={{
                height: '100%', borderRadius: 3,
                width: `${progressRes?.data?.progress ?? project.completion_pct ?? 0}%`,
                background: 'var(--color-green)',
                transition: 'width .4s ease',
              }} />
            </div>
            <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 4 }}>
              {progressRes?.data?.progress ?? project.completion_pct ?? 0}%
              {progressRes?.data?.total_stages ? ` · ${progressRes.data.completed_stages}/${progressRes.data.total_stages} stages` : ''}
            </div>
          </div>

          <div style={{ marginTop: 20 }}>
            <button
              onClick={() => navigate(`/projects/${id}/pipeline`)}
              style={{
                width: '100%', padding: '7px 0', borderRadius: 7,
                border: '1px solid var(--color-border)', background: 'transparent',
                color: 'var(--color-text-primary)', fontSize: 11, fontWeight: 600,
                cursor: 'pointer', fontFamily: 'var(--font-body)',
              }}
            >
              Full Pipeline View
            </button>
          </div>
        </div>
      </div>

      {/* Modals */}
      <AdvanceStageModal
        isOpen={showAdvance}
        onClose={() => setShowAdvance(false)}
        onSubmit={handleAdvance}
        currentStage={currentStage ?? undefined}
        nextStage={nextStage ?? undefined}
      />
      <PushBackModal
        isOpen={showPushBack}
        onClose={() => setShowPushBack(false)}
        onSubmit={handlePushBack}
        currentStage={currentStage ?? undefined}
        prevStage={prevStage ?? undefined}
      />

      {/* Start Pipeline Modal */}
      {showStartPipeline && (
        <GlassModal open onClose={() => setShowStartPipeline(false)} ariaLabel="Start pipeline" size="sm">
            <div style={{ fontWeight: 800, fontSize: 16, color: 'var(--color-text-primary)', marginBottom: 16 }}>Start Pipeline</div>
            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 16 }}>
              Select a pipeline template to apply to this project.
            </div>
            <div style={{ marginBottom: 20 }}>
              <label style={{ display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--color-text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '.1em' }}>
                Pipeline Template
              </label>
              <GlassSelect value={String(selectedTemplateId)} onChange={v => setSelectedTemplateId(v)} options={[...(templates as any[]).map((t: any) => ({ value: String(t.id), label: String(t.name) }))]} placeholder={'— Select a template —'} ariaLabel="Pipeline template" />
            </div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button
                onClick={() => setShowStartPipeline(false)}
                style={{ padding: '8px 16px', borderRadius: 8, border: '1px solid var(--color-border)', background: 'transparent', color: 'var(--color-text-primary)', fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'var(--font-body)' }}
              >
                Cancel
              </button>
              <button
                onClick={() => { if (selectedTemplateId) startPipelineMutation.mutate(selectedTemplateId); }}
                disabled={!selectedTemplateId || startPipelineMutation.isPending}
                style={{
                  padding: '8px 18px', borderRadius: 8, border: 'none',
                  background: selectedTemplateId ? 'var(--color-teal)' : 'var(--color-border)',
                  color: 'white', fontSize: 12, fontWeight: 700,
                  cursor: selectedTemplateId ? 'pointer' : 'not-allowed', fontFamily: 'var(--font-body)',
                }}
              >
                {startPipelineMutation.isPending ? 'Starting…' : 'Start Pipeline'}
              </button>
            </div>
          </GlassModal>
      )}
    </div>
  );
}

function SidebarField({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '.1em', marginBottom: 3 }}>
        {label}
      </div>
      <div style={{ fontSize: 12, color: 'var(--color-text-primary)' }}>{value || '—'}</div>
    </div>
  );
}
