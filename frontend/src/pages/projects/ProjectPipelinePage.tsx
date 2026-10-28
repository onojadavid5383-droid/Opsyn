// ============================================================
// OPSYN PROJECT PIPELINE PAGE — task-style stepper edition
// Visual language matches TaskDetailModal pipeline stepper.
// ============================================================

import { Fragment, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  useProjectPipeline,
  useAdvanceStage,
  usePushBackStage,
  useAddStageComment,
  useApproveStage,
} from '../../hooks/useProjects';
import { AdvanceStageModal } from '../../components/projects/AdvanceStageModal';
import { PushBackModal }     from '../../components/projects/PushBackModal';
import { useAuthStore }      from '../../store/auth.store';
import { formBuilderApi, type ContextSchema } from '../../api/form-builder.api';
import FormRenderer from '../../components/form-builder/FormRenderer';
import { GlassModal } from '../../components/glass';

// ── Stage status colour palette ───────────────────────────────

const STAGE_COLORS: Record<string, string> = {
  approved:    '#16a34a',
  active:      '#0ea5e9',
  pushed_back: '#f59e0b',
  pending:     '#94a3b8',
};

// ── Stage Forms (Form Builder integration — Phase 8) ─────────

function StageForms({
  stageId,
  projectId,
  stageOrder,
}: {
  stageId:    string;
  projectId:  string;
  stageOrder: number;
}) {
  const [activeIdx, setActiveIdx] = useState(0);

  const contextQ = useQuery({
    queryKey: ['form-builder', 'context', 'pipeline_stage', stageId],
    queryFn:  () => formBuilderApi.getContextSchemas('pipeline_stage', stageId),
    staleTime: 60_000,
  });

  const schemas: ContextSchema[] = contextQ.data ?? [];

  if (contextQ.isLoading || !schemas.length) return null;

  const active = schemas[activeIdx] ?? schemas[0];

  return (
    <div style={{
      marginBottom: 24, background: 'var(--surface)',
      border: '1px solid var(--color-border)', borderRadius: 12, padding: 20,
    }}>
      <div style={{
        fontSize: 10, fontWeight: 700, color: 'var(--color-text-muted)',
        textTransform: 'uppercase', letterSpacing: '.1em', marginBottom: 12,
      }}>
        Stage Forms
      </div>

      {schemas.length > 1 && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
          {schemas.map((cs, i) => (
            <button
              key={cs.association.id}
              onClick={() => setActiveIdx(i)}
              style={{
                padding: '4px 12px', borderRadius: 6, fontSize: 11, fontWeight: 600,
                border:      activeIdx === i ? 'none' : '1px solid var(--color-border)',
                background:  activeIdx === i ? '#0ea5e9' : 'transparent',
                color:       activeIdx === i ? 'white'   : 'var(--color-text-muted)',
                cursor: 'pointer', fontFamily: 'var(--font-body)',
              }}
            >
              {cs.schema.name}
              {cs.schema.is_mandatory && (
                <span style={{ color: activeIdx === i ? 'rgba(255,255,255,.7)' : '#dc2626', marginLeft: 3 }}>*</span>
              )}
            </button>
          ))}
        </div>
      )}

      <FormRenderer
        schemaId={active.schema.id}
        entityType="project"
        entityId={projectId}
        associationId={active.association.id}
        pipelineStageOrder={stageOrder}
      />
    </div>
  );
}

// ── Pipeline Stepper (mirrors task modal PipelineStepper) ─────

function ProjectPipelineStepper({
  stages,
}: {
  stages: any[];
  currentStageId?: string | null;
}) {
  if (!stages.length) return null;

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{
        fontSize: 10, fontWeight: 700, color: 'var(--color-text-muted)',
        textTransform: 'uppercase', letterSpacing: '.1em', marginBottom: 12,
      }}>
        Pipeline
      </div>

      <div style={{ display: 'flex', alignItems: 'flex-start' }}>
        {stages.map((stage: any, i: number) => {
          const isCurrent    = stage.status === 'active';
          const isPast       = stage.status === 'approved';
          const isPushedBack = stage.status === 'pushed_back';
          const color        = isPushedBack ? STAGE_COLORS.pushed_back
                             : isCurrent    ? STAGE_COLORS.active
                             : isPast       ? STAGE_COLORS.approved
                             :                STAGE_COLORS.pending;

          return (
            <Fragment key={stage.id}>
              {i > 0 && (
                <div style={{
                  flex: 1, height: 2, marginTop: 15,
                  background: isPast ? STAGE_COLORS.approved : isCurrent ? '#bae6fd' : '#e2e8f0',
                  transition: 'background .3s',
                }} />
              )}
              <div
                title={stage.stageName}
                style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5, minWidth: 56 }}
              >
                <div style={{
                  width: 32, height: 32, borderRadius: '50%',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 11, fontWeight: 700, transition: 'all .25s',
                  border:     `2px solid ${isPast ? STAGE_COLORS.approved : (isCurrent || isPushedBack) ? color : '#e2e8f0'}`,
                  background: isPast       ? 'rgba(22,163,74,.1)'
                            : isCurrent    ? 'rgba(14,165,233,.12)'
                            : isPushedBack ? 'rgba(245,158,11,.12)'
                            :                'transparent',
                  color,
                  boxShadow: isCurrent ? `0 0 14px ${color}55` : 'none',
                }}>
                  {isPast ? '✓' : isPushedBack ? '↩' : i + 1}
                </div>
                <div style={{
                  fontSize: 9, whiteSpace: 'nowrap', fontWeight: isCurrent ? 700 : 400,
                  color,
                }}>
                  {stage.stageName}
                </div>
              </div>
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────

export function ProjectPipelinePage() {
  const { id } = useParams<{ id: string }>();
  const { data: pipeline, isLoading, isError } = useProjectPipeline(id!);
  const advanceMutation    = useAdvanceStage(id!);
  const pushBackMutation   = usePushBackStage(id!);
  const addCommentMutation = useAddStageComment(id!);
  const approveMutation    = useApproveStage(id!);
  const roleLevel          = useAuthStore(s => s.roleLevel);

  const [showAdvanceModal,  setShowAdvanceModal]  = useState(false);
  const [showPushBackModal, setShowPushBackModal] = useState(false);
  const [showApproveModal,  setShowApproveModal]  = useState(false);
  const [approveNotes,      setApproveNotes]      = useState('');
  const [commentText,  setCommentText]  = useState('');
  const [commentType,  setCommentType]  = useState<'progress' | 'issue' | 'note'>('progress');
  const [advanceError, setAdvanceError] = useState<string | null>(null);

  // ── Loading / error ──────────────────────────────────────────

  if (isLoading) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-muted)', fontSize: 13 }}>
        Loading pipeline…
      </div>
    );
  }

  if (isError || !pipeline?.data) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, color: 'var(--color-text-muted)', fontSize: 13 }}>
        <div style={{ fontSize: 36 }}>📋</div>
        <div style={{ fontWeight: 600, color: 'var(--color-text-primary)', fontSize: 15 }}>No pipeline available</div>
        <div style={{ maxWidth: 320, textAlign: 'center', lineHeight: 1.5 }}>
          This project does not have an active pipeline yet.
        </div>
        <button
          onClick={() => window.history.back()}
          style={{
            marginTop: 8, padding: '8px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600,
            border: '1px solid var(--color-border)', background: 'var(--color-surface-2)',
            color: 'var(--color-text-primary)', cursor: 'pointer', fontFamily: 'var(--font-body)',
          }}
        >
          ← Back
        </button>
      </div>
    );
  }

  // ── Data ─────────────────────────────────────────────────────

  const pdata              = (pipeline.data ?? {}) as any;
  const projectName        = pdata.projectName        ?? 'Project';
  const pipelineStatus     = pdata.pipelineStatus     ?? 'active';
  const currentStage       = pdata.currentStage       ?? null;
  const canAdvance         = pdata.canAdvance         ?? false;
  const canPushBack        = pdata.canPushBack        ?? false;
  const safeAllStages: any[] = Array.isArray(pdata.allStages) ? pdata.allStages : [];

  const isCompleted          = pipelineStatus === 'completed';
  const isMutating           = advanceMutation.isPending || pushBackMutation.isPending || approveMutation.isPending;
  const canApprove           = roleLevel >= 3 && !isCompleted && !!currentStage;
  const stageApproval        = (pdata.currentStageApproval ?? null) as any;
  const isGateApproved       = !!(stageApproval?.approvedAt);
  const stageRequiresApproval = !!(pdata.stageRequiresApproval);
  const missingFields: string[] = Array.isArray(pdata.missingRequiredFields) ? pdata.missingRequiredFields : [];

  // ── Handlers ─────────────────────────────────────────────────

  const handleAdvance = async (comment?: string) => {
    setAdvanceError(null);
    try {
      await advanceMutation.mutateAsync({ comment });
      setShowAdvanceModal(false);
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const missing = (detail as { missing_required_forms?: string[] } | undefined)?.missing_required_forms;
      setAdvanceError(missing?.length
        ? `Complete the required form${missing.length === 1 ? '' : 's'} before advancing: ${missing.join(', ')}`
        : typeof detail === 'string' ? detail : 'Could not advance this stage. Check required fields and approvals.');
    }
  };

  const handlePushBack = async (reason: string, comment?: string) => {
    await pushBackMutation.mutateAsync({ reason, comment });
    setShowPushBackModal(false);
  };

  const handleApprove = async () => {
    if (!currentStage) return;
    await approveMutation.mutateAsync({ stageId: currentStage.id, notes: approveNotes || undefined });
    setShowApproveModal(false);
    setApproveNotes('');
  };

  const handleAddComment = async () => {
    if (!currentStage || !commentText.trim()) return;
    await addCommentMutation.mutateAsync({ stageId: currentStage.id, body: commentText, commentType });
    setCommentText('');
  };

  // ── Render ───────────────────────────────────────────────────

  return (
    <div style={{ overflow: 'auto', flex: 1, background: 'var(--color-surface)' }}>
      <div style={{ padding: '28px', maxWidth: 780, margin: '0 auto' }}>

        {/* Header */}
        <div style={{ marginBottom: 22 }}>
          <div style={{
            fontWeight: 800, fontSize: 18, color: 'var(--color-text-primary)',
            letterSpacing: '-.02em', marginBottom: 8,
          }}>
            {projectName}
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <span style={{
              padding: '2px 10px', borderRadius: 5, fontSize: 11, fontWeight: 700,
              background: isCompleted ? 'rgba(22,163,74,.1)' : 'rgba(14,165,233,.1)',
              color:      isCompleted ? '#16a34a'             : '#0ea5e9',
            }}>
              {pipelineStatus.replace(/_/g, ' ').toUpperCase()}
            </span>
          </div>
        </div>

        {advanceError && <div role="alert" style={{ marginBottom: 16, padding: '10px 14px', borderRadius: 8, background: 'rgba(239,68,68,.06)', border: '1px solid rgba(239,68,68,.25)', color: '#dc2626', fontSize: 12 }}>{advanceError}</div>}

        {/* Pipeline Stepper */}
        {safeAllStages.length > 0 && (
          <ProjectPipelineStepper stages={safeAllStages} currentStageId={currentStage?.id} />
        )}

        {/* Completion banner */}
        {isCompleted && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '10px 14px', borderRadius: 8, marginBottom: 20,
            background: 'rgba(22,163,74,.07)', border: '1px solid rgba(22,163,74,.25)',
            fontSize: 12, color: '#16a34a', fontWeight: 600,
          }}>
            <span>🎉</span> All pipeline stages complete.
          </div>
        )}

        {/* Approval gate banner */}
        {!isCompleted && currentStage && (
          <>
            {isGateApproved ? (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 14px', borderRadius: 8, marginBottom: 14,
                background: 'rgba(22,163,74,.07)', border: '1px solid rgba(22,163,74,.25)',
                fontSize: 12, color: '#16a34a', fontWeight: 600,
              }}>
                <span>✓</span> Stage gate approved — ready to advance
              </div>
            ) : stageRequiresApproval ? (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 14px', borderRadius: 8, marginBottom: 14,
                background: 'rgba(245,158,11,.07)', border: '1px solid rgba(245,158,11,.3)',
                fontSize: 12, color: '#d97706', fontWeight: 600,
              }}>
                <span>⏳</span> Awaiting stage approval before advancement
              </div>
            ) : null}

            {missingFields.length > 0 && (
              <div style={{
                padding: '10px 14px', borderRadius: 8, marginBottom: 14,
                background: 'rgba(239,68,68,.05)', border: '1px solid rgba(239,68,68,.25)',
              }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#dc2626', marginBottom: 6 }}>
                  Required fields not yet completed:
                </div>
                <ul style={{ margin: 0, paddingLeft: 16 }}>
                  {missingFields.map(f => (
                    <li key={f} style={{ fontSize: 11, color: '#dc2626', marginBottom: 2 }}>{f}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}

        {/* Action Buttons — task-modal style */}
        {!isCompleted && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 20 }}>
            <button
              disabled={!canAdvance || isMutating}
              onClick={() => setShowAdvanceModal(true)}
              style={{
                padding: '6px 14px', borderRadius: 8, border: 'none',
                fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-body)',
                background:  canAdvance && !isMutating ? 'rgba(14,165,233,.15)' : 'rgba(0,0,0,.04)',
                color:       canAdvance && !isMutating ? '#0ea5e9'               : 'var(--color-text-muted)',
                cursor:      canAdvance && !isMutating ? 'pointer'               : 'not-allowed',
                opacity:     canAdvance && !isMutating ? 1                       : 0.5,
                transition:  'all .15s',
              }}
            >
              {isMutating ? '…' : '▶ Advance Stage'}
            </button>

            <button
              disabled={!canPushBack || isMutating}
              onClick={() => setShowPushBackModal(true)}
              style={{
                padding: '6px 14px', borderRadius: 8, fontFamily: 'var(--font-body)',
                border:      canPushBack && !isMutating ? '1px solid rgba(239,68,68,.35)' : '1px solid var(--color-border)',
                fontSize:    11, fontWeight: 700,
                background:  canPushBack && !isMutating ? 'rgba(239,68,68,.07)'   : 'transparent',
                color:       canPushBack && !isMutating ? '#dc2626'                : 'var(--color-text-muted)',
                cursor:      canPushBack && !isMutating ? 'pointer'                : 'not-allowed',
                opacity:     canPushBack && !isMutating ? 1                        : 0.5,
                transition:  'all .15s',
              }}
            >
              {isMutating ? '…' : '◀ Push Back'}
            </button>

            {canApprove && (
              <button
                disabled={isGateApproved || isMutating}
                onClick={() => setShowApproveModal(true)}
                style={{
                  padding: '6px 14px', borderRadius: 8, fontFamily: 'var(--font-body)',
                  border:      !isGateApproved && !isMutating ? '1px solid rgba(22,163,74,.4)' : '1px solid var(--color-border)',
                  fontSize:    11, fontWeight: 700,
                  background:  isGateApproved ? 'rgba(22,163,74,.1)' : !isMutating ? 'rgba(22,163,74,.07)' : 'transparent',
                  color:       isGateApproved ? '#16a34a' : !isMutating ? '#16a34a' : 'var(--color-text-muted)',
                  cursor:      !isGateApproved && !isMutating ? 'pointer' : 'not-allowed',
                  opacity:     isGateApproved || isMutating ? 0.55 : 1,
                  transition:  'all .15s',
                }}
              >
                {isGateApproved ? '✓ Gate Approved' : isMutating ? '…' : '✓ Approve Gate'}
              </button>
            )}
          </div>
        )}

        {/* Current Stage Detail */}
        {currentStage && !isCompleted && (
          <div style={{
            background: 'var(--surface)', borderRadius: 12, marginBottom: 24,
            border: '1px solid var(--color-border)',
            borderLeft: '3px solid #0ea5e9',
            padding: 20,
          }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#0ea5e9', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 4 }}>
              Current Stage
            </div>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--color-text-primary)', marginBottom: 4 }}>
              {currentStage.stageName}
            </div>
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 16 }}>
              {currentStage.departmentName}
              {currentStage.enteredAt && (
                <> · Entered {new Date(currentStage.enteredAt).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}</>
              )}
            </div>

            {/* Comment input */}
            <textarea
              value={commentText}
              onChange={e => setCommentText(e.target.value)}
              placeholder="Add a progress update…"
              rows={3}
              style={{
                width: '100%', padding: '10px 12px', borderRadius: 8, resize: 'vertical',
                border: '1px solid var(--color-border)', background: 'var(--color-surface)',
                color: 'var(--color-text-primary)', fontFamily: 'var(--font-body)',
                fontSize: 12, outline: 'none', boxSizing: 'border-box',
              }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
              <div style={{ display: 'flex', gap: 4 }}>
                {(['progress', 'issue', 'note'] as const).map(t => (
                  <button key={t} onClick={() => setCommentType(t)}
                    style={{
                      padding: '3px 8px', borderRadius: 5, fontSize: 10, fontWeight: 600,
                      cursor: 'pointer', fontFamily: 'var(--font-body)',
                      background:   commentType === t ? 'rgba(14,165,233,.1)' : 'transparent',
                      color:        commentType === t ? '#0ea5e9'              : 'var(--color-text-muted)',
                      border:       commentType === t ? '1px solid rgba(14,165,233,.35)' : '1px solid var(--color-border)',
                    }}>
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </button>
                ))}
              </div>
              <button
                onClick={handleAddComment}
                disabled={!commentText.trim() || addCommentMutation.isPending}
                style={{
                  padding: '5px 12px', borderRadius: 7, fontSize: 11, fontWeight: 700, border: 'none',
                  background:  commentText.trim() && !addCommentMutation.isPending ? '#0ea5e9' : 'rgba(0,0,0,.06)',
                  color:       commentText.trim() && !addCommentMutation.isPending ? 'white'   : 'var(--color-text-muted)',
                  cursor:      commentText.trim() && !addCommentMutation.isPending ? 'pointer'  : 'not-allowed',
                  fontFamily: 'var(--font-body)',
                }}
              >
                {addCommentMutation.isPending ? '…' : 'Post'}
              </button>
            </div>
          </div>
        )}

        {/* Stage Forms — dynamic forms attached to the current stage */}
        {currentStage && !isCompleted && (
          <StageForms
            stageId={currentStage.id}
            projectId={id!}
            stageOrder={currentStage.stageOrder ?? 1}
          />
        )}

        {/* Stage History */}
        {safeAllStages.some((s: any) => s.status === 'approved' || s.status === 'pushed_back') && (
          <div>
            <div style={{
              fontSize: 10, fontWeight: 700, color: 'var(--color-text-muted)',
              textTransform: 'uppercase', letterSpacing: '.1em', marginBottom: 12,
            }}>
              Stage History
            </div>

            {safeAllStages
              .filter((s: any) => s.status === 'approved' || s.status === 'pushed_back')
              .map((stage: any) => {
                const isApproved   = stage.status === 'approved';
                const color        = isApproved ? '#16a34a' : '#f59e0b';
                const comments: any[] = stage.comments ?? [];

                return (
                  <div key={stage.id} id={`stage-${stage.id}`} style={{
                    background: 'var(--surface)',
                    border: '1px solid var(--color-border)',
                    borderLeft: `3px solid ${color}`,
                    borderRadius: 10, padding: '14px 16px', marginBottom: 10,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary)' }}>
                        {stage.stageName}
                      </span>
                      <span style={{
                        padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700,
                        background: `${color}18`, color,
                      }}>
                        {isApproved ? '✓ APPROVED' : '↩ PUSHED BACK'}
                      </span>
                    </div>

                    {stage.pushedBackReason && (
                      <div style={{
                        fontSize: 11, color: '#f59e0b', fontStyle: 'italic', marginBottom: 8,
                        padding: '4px 8px', background: 'rgba(245,158,11,.08)', borderRadius: 4,
                      }}>
                        Reason: {stage.pushedBackReason}
                      </div>
                    )}

                    {stage.enteredAt && (
                      <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginBottom: comments.length ? 10 : 0 }}>
                        {new Date(stage.enteredAt).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}
                        {stage.exitedAt && (
                          <> → {new Date(stage.exitedAt).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}</>
                        )}
                        {stage.durationDays != null && <> · {stage.durationDays.toFixed(1)} days</>}
                      </div>
                    )}

                    {comments.length > 0 && (
                      <div style={{
                        borderTop: '1px solid var(--color-border)',
                        paddingTop: 8, marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6,
                      }}>
                        {comments.map((c: any) => (
                          <div key={c.id} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                            <div style={{
                              width: 22, height: 22, borderRadius: '50%', flexShrink: 0,
                              background: 'var(--color-surface-2)',
                              display: 'flex', alignItems: 'center', justifyContent: 'center',
                              fontSize: 9, fontWeight: 700, color: 'var(--color-text-muted)',
                            }}>
                              {(c.authorName ?? '?').charAt(0).toUpperCase()}
                            </div>
                            <div style={{ flex: 1 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text-primary)' }}>
                                  {c.authorName ?? 'Unknown'}
                                </span>
                                <span style={{
                                  fontSize: 9, padding: '1px 5px', borderRadius: 3, fontWeight: 700,
                                  background: 'var(--color-surface-2)', color: 'var(--color-text-muted)',
                                }}>
                                  {c.commentType}
                                </span>
                              </div>
                              <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
                                {c.body}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
        )}

        {/* Modals */}
        <AdvanceStageModal
          isOpen={showAdvanceModal}
          onClose={() => setShowAdvanceModal(false)}
          onSubmit={handleAdvance}
          currentStage={currentStage ?? undefined}
          nextStage={safeAllStages.find((s: any) => s.stageOrder === ((currentStage?.stageOrder ?? 0) + 1))}
        />
        <PushBackModal
          isOpen={showPushBackModal}
          onClose={() => setShowPushBackModal(false)}
          onSubmit={handlePushBack}
          currentStage={currentStage ?? undefined}
          prevStage={safeAllStages.find((s: any) => s.stageOrder === ((currentStage?.stageOrder ?? 0) - 1))}
        />

        {/* Approve Gate Modal */}
        {showApproveModal && currentStage && (
          <GlassModal open onClose={() => setShowApproveModal(false)} ariaLabel="Approve stage" size="sm">
              <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--color-text-primary)', marginBottom: 4 }}>
                Approve Stage Gate
              </div>
              <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 16 }}>
                Approving <strong>{currentStage.stageName}</strong> will allow the pipeline to be advanced.
              </div>
              <textarea
                value={approveNotes}
                onChange={e => setApproveNotes(e.target.value)}
                placeholder="Approval notes (optional)…"
                rows={3}
                style={{
                  width: '100%', padding: '10px 12px', borderRadius: 8, resize: 'vertical',
                  border: '1px solid var(--color-border)', background: 'var(--color-surface)',
                  color: 'var(--color-text-primary)', fontFamily: 'var(--font-body)',
                  fontSize: 12, outline: 'none', boxSizing: 'border-box',
                }}
              />
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
                <button
                  onClick={() => setShowApproveModal(false)}
                  style={{
                    padding: '7px 16px', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer',
                    border: '1px solid var(--color-border)', background: 'transparent',
                    color: 'var(--color-text-secondary)', fontFamily: 'var(--font-body)',
                  }}
                >
                  Cancel
                </button>
                <button
                  onClick={handleApprove}
                  disabled={approveMutation.isPending}
                  style={{
                    padding: '7px 16px', borderRadius: 8, fontSize: 12, fontWeight: 700, cursor: 'pointer',
                    border: 'none', background: '#16a34a', color: 'white', fontFamily: 'var(--font-body)',
                    opacity: approveMutation.isPending ? 0.6 : 1,
                  }}
                >
                  {approveMutation.isPending ? 'Approving…' : 'Confirm Approval'}
                </button>
              </div>
            </GlassModal>
        )}
      </div>
    </div>
  );
}

export default ProjectPipelinePage;
