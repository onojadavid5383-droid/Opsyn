// ============================================================
// WORKFLOW BUILDER PAGE — three-panel: list | canvas | config
// ============================================================

import { useState } from 'react';
import {
  useWorkflows, useWorkflow, useCreateWorkflow,
  useDeleteWorkflow, useValidateWorkflow, usePublishWorkflow, useCloneWorkflow,
} from '../../hooks/useWorkflows';
import { useDepartments } from '../../hooks';
import { WorkflowCanvas } from './components/WorkflowCanvas';
import { EdgeConfigPanel } from './components/EdgeConfigPanel';
import type { CreateWorkflowPayload } from '../../types/workflow.types';
import { usePermissions } from '../../hooks/usePermissions';
import { GlassModal } from '../../components/glass';

export default function WorkflowBuilderPage() {
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId]         = useState<string | null>(null);
  const [showCreate, setShowCreate]                 = useState(false);
  const [newName, setNewName]                       = useState('');
  const [newDesc, setNewDesc]                       = useState('');
  const [validationErrors, setValidationErrors]     = useState<string[]>([]);
  const [showValidation, setShowValidation]         = useState(false);

  const { isTeamLead } = usePermissions();
  const canEdit = isTeamLead;

  const { data: workflows = [], isLoading: listLoading } = useWorkflows(false);
  const { data: graph, isLoading: graphLoading }         = useWorkflow(selectedWorkflowId);
  const { data: departments = [] }                       = useDepartments();

  const createWorkflow   = useCreateWorkflow();
  const deleteWorkflow   = useDeleteWorkflow();
  const validateWorkflow = useValidateWorkflow(selectedWorkflowId ?? '');
  const publishWorkflow  = usePublishWorkflow(selectedWorkflowId ?? '');
  const cloneWorkflow    = useCloneWorkflow();

  const activeWorkflow  = graph?.workflow ?? null;
  const edges           = graph?.edges ?? [];
  const selectedEdge    = edges.find(e => e.id === selectedEdgeId) ?? null;
  const isDraft         = activeWorkflow?.isDraft ?? true;

  function handleCreate() {
    if (!newName.trim()) return;
    const payload: CreateWorkflowPayload = {
      name: newName.trim(),
      description: newDesc.trim() || undefined,
    };
    createWorkflow.mutate(payload, {
      onSuccess: wf => {
        setSelectedWorkflowId(wf.id);
        setShowCreate(false);
        setNewName('');
        setNewDesc('');
      },
    });
  }

  function handleValidate() {
    setValidationErrors([]);
    setShowValidation(false);
    validateWorkflow.mutate(undefined, {
      onSuccess: result => {
        setValidationErrors(result.errors);
        setShowValidation(true);
      },
    });
  }

  function handlePublish() {
    setShowValidation(false);
    publishWorkflow.mutate();
  }

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      <h1 className="sr-only">Workflow builder</h1>

      {/* ── Left panel: workflow list ── */}
      <aside style={{
        width: 240, flexShrink: 0,
        borderRight: '1px solid var(--wire)', background: 'var(--bg2)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}>
        <div style={{ padding: '12px 14px 10px', borderBottom: '1px solid var(--wire)' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--chalk)', marginBottom: 8 }}>
            Workflows
          </div>
          {canEdit && (
            <button
              onClick={() => setShowCreate(true)}
              style={{
                width: '100%', padding: '7px', borderRadius: 7,
                border: 'none', background: 'var(--brand)',
                color: '#050810', fontFamily: 'var(--font)',
                fontWeight: 700, fontSize: 11, cursor: 'pointer',
              }}
            >+ New Workflow</button>
          )}
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: 8, scrollbarWidth: 'none' }}>
          {listLoading && (
            <div style={{ padding: 12, fontSize: 11, color: 'var(--chalk3)', textAlign: 'center' }}>
              Loading…
            </div>
          )}
          {!listLoading && workflows.length === 0 && (
            <div style={{ padding: 12, fontSize: 11, color: 'var(--chalk3)', textAlign: 'center' }}>
              No workflows yet.
            </div>
          )}
          {workflows.map(wf => {
            const active = selectedWorkflowId === wf.id;
            return (
              <div
                key={wf.id}
                onClick={() => { setSelectedWorkflowId(wf.id); setSelectedEdgeId(null); }}
                style={{
                  padding: '8px 10px', borderRadius: 8, cursor: 'pointer',
                  marginBottom: 4,
                  background: active ? 'linear-gradient(135deg,rgba(74,222,128,.08),rgba(6,182,212,.08))' : 'transparent',
                  boxShadow: active ? 'inset 0 0 0 1px rgba(6,182,212,.18)' : 'none',
                  border: active ? 'none' : '1px solid transparent',
                  transition: 'all .15s',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                  <span style={{ fontSize: 12, fontWeight: active ? 700 : 500,
                                 color: active ? 'var(--cyan)' : 'var(--chalk)',
                                 flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {wf.name}
                  </span>
                  {wf.isActive && !wf.isDraft && (
                    <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px',
                                   borderRadius: 4, background: 'rgba(74,222,128,.15)',
                                   color: 'var(--green)' }}>LIVE</span>
                  )}
                  {wf.isDraft && (
                    <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px',
                                   borderRadius: 4, background: 'rgba(251,191,36,.12)',
                                   color: 'var(--amber)' }}>DRAFT</span>
                  )}
                </div>
                <div style={{ fontSize: 10, color: 'var(--chalk3)' }}>
                  {wf.edgeCount ?? 0} stage{wf.edgeCount !== 1 ? 's' : ''} · v{wf.version}
                </div>
              </div>
            );
          })}
        </div>
      </aside>

      {/* ── Center: canvas ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* canvas toolbar */}
        {activeWorkflow && (
          <div style={{
            height: 46, borderBottom: '1px solid var(--wire)',
            background: 'var(--bg2)', display: 'flex',
            alignItems: 'center', gap: 10, padding: '0 16px', flexShrink: 0,
          }}>
            <div style={{ flex: 1 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--chalk)' }}>
                {activeWorkflow.name}
              </span>
              {activeWorkflow.description && (
                <span style={{ fontSize: 11, color: 'var(--chalk3)', marginLeft: 8 }}>
                  {activeWorkflow.description}
                </span>
              )}
            </div>

            {/* clone */}
            {canEdit && (
              <button
                onClick={() => cloneWorkflow.mutate(activeWorkflow.id, {
                  onSuccess: wf => setSelectedWorkflowId(wf.id),
                })}
                style={ghostBtn}
                title="Clone this workflow"
              >Clone</button>
            )}

            {/* delete (only drafts with no stages) */}
            {canEdit && isDraft && edges.length === 0 && (
              <button
                onClick={() => {
                  deleteWorkflow.mutate(activeWorkflow.id, {
                    onSuccess: () => setSelectedWorkflowId(null),
                  });
                }}
                style={{ ...ghostBtn, color: 'var(--red)', borderColor: 'rgba(239,68,68,.3)' }}
              >Delete</button>
            )}

            {/* validate */}
            {canEdit && isDraft && (
              <button
                onClick={handleValidate}
                disabled={validateWorkflow.isPending}
                style={ghostBtn}
              >
                {validateWorkflow.isPending ? 'Checking…' : 'Validate'}
              </button>
            )}

            {/* publish */}
            {canEdit && isDraft && (
              <button
                onClick={handlePublish}
                disabled={publishWorkflow.isPending}
                style={{
                  padding: '5px 14px', borderRadius: 7, border: 'none',
                  background: 'var(--brand)', color: '#050810',
                  fontFamily: 'var(--font)', fontWeight: 700, fontSize: 11,
                  cursor: publishWorkflow.isPending ? 'not-allowed' : 'pointer',
                  opacity: publishWorkflow.isPending ? 0.6 : 1,
                }}
              >
                {publishWorkflow.isPending ? 'Publishing…' : 'Publish'}
              </button>
            )}

            {!isDraft && (
              <span style={{ fontSize: 10, fontWeight: 700, padding: '3px 10px',
                             borderRadius: 6, background: 'rgba(74,222,128,.12)',
                             color: 'var(--green)' }}>PUBLISHED</span>
            )}
          </div>
        )}

        {/* validation banner */}
        {showValidation && (
          <div style={{
            padding: '10px 16px', flexShrink: 0,
            background: validationErrors.length ? 'rgba(239,68,68,.08)' : 'rgba(74,222,128,.08)',
            borderBottom: '1px solid ' + (validationErrors.length ? 'rgba(239,68,68,.2)' : 'rgba(74,222,128,.2)'),
            display: 'flex', alignItems: 'flex-start', gap: 10,
          }}>
            <span style={{ fontSize: 16 }}>{validationErrors.length ? '⚠️' : '✅'}</span>
            <div style={{ flex: 1 }}>
              {validationErrors.length === 0 ? (
                <div style={{ fontSize: 12, color: 'var(--green)', fontWeight: 600 }}>
                  Workflow is valid — ready to publish.
                </div>
              ) : (
                <>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--red)', marginBottom: 4 }}>
                    {validationErrors.length} validation error{validationErrors.length !== 1 ? 's' : ''}
                  </div>
                  {validationErrors.map((err, i) => (
                    <div key={i} style={{ fontSize: 11, color: 'var(--red)', marginBottom: 2 }}>
                      · {err}
                    </div>
                  ))}
                </>
              )}
            </div>
            <button
              onClick={() => setShowValidation(false)}
              style={{ background: 'none', border: 'none', cursor: 'pointer',
                       color: 'var(--chalk3)', fontSize: 14 }}
            >×</button>
          </div>
        )}

        {/* no workflow selected */}
        {!selectedWorkflowId && (
          <div style={{
            flex: 1, display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: 12,
            color: 'var(--chalk3)', padding: 40,
          }}>
            <div style={{ fontSize: 32 }}>⬡</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--chalk2)' }}>
              Select a workflow to edit
            </div>
            <div style={{ fontSize: 12, textAlign: 'center', maxWidth: 300 }}>
              Choose a workflow from the left panel, or create a new one.
            </div>
            {canEdit && (
              <button
                onClick={() => setShowCreate(true)}
                style={{
                  padding: '8px 20px', borderRadius: 8, border: 'none',
                  background: 'var(--brand)', color: '#050810',
                  fontFamily: 'var(--font)', fontWeight: 700, fontSize: 12, cursor: 'pointer',
                }}
              >+ New Workflow</button>
            )}
          </div>
        )}

        {/* canvas */}
        {selectedWorkflowId && !graphLoading && graph && (
          <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
            <WorkflowCanvas
              workflowId={selectedWorkflowId}
              edges={edges}
              departments={departments}
              canEdit={canEdit && isDraft}
              selectedEdgeId={selectedEdgeId}
              onSelectEdge={id => setSelectedEdgeId(id)}
            />

            {selectedEdge && (
              <EdgeConfigPanel
                workflowId={selectedWorkflowId}
                edge={selectedEdge}
                onClose={() => setSelectedEdgeId(null)}
              />
            )}
          </div>
        )}

        {selectedWorkflowId && graphLoading && (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: 'var(--chalk3)', fontSize: 12 }}>
            Loading workflow…
          </div>
        )}
      </div>

      {/* ── Create modal ── */}
      {showCreate && (
        <GlassModal open onClose={() => setShowCreate(false)} ariaLabel="Create workflow" size="sm">
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--chalk)' }}>
              New Workflow
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.08em',
                              textTransform: 'uppercase', color: 'var(--chalk3)' }}>
                Name *
              </label>
              <input
                autoFocus
                type="text"
                placeholder="e.g. Project Approval Flow"
                value={newName}
                onChange={e => setNewName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleCreate()}
                style={{
                  padding: '8px 10px', borderRadius: 7,
                  border: '1px solid var(--wire)', background: 'var(--bg)',
                  color: 'var(--chalk)', fontSize: 13, fontFamily: 'var(--font)',
                }}
              />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.08em',
                              textTransform: 'uppercase', color: 'var(--chalk3)' }}>
                Description
              </label>
              <textarea
                placeholder="Optional description…"
                value={newDesc}
                onChange={e => setNewDesc(e.target.value)}
                rows={2}
                style={{
                  padding: '8px 10px', borderRadius: 7,
                  border: '1px solid var(--wire)', background: 'var(--bg)',
                  color: 'var(--chalk)', fontSize: 12, fontFamily: 'var(--font)',
                  resize: 'vertical',
                }}
              />
            </div>

            {createWorkflow.isError && (
              <div style={{ fontSize: 11, color: 'var(--red)', padding: '6px 10px',
                            borderRadius: 6, background: 'rgba(239,68,68,.08)',
                            border: '1px solid rgba(239,68,68,.2)' }}>
                Failed to create workflow. Check inputs and try again.
              </div>
            )}

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                onClick={() => { setShowCreate(false); setNewName(''); setNewDesc(''); }}
                style={{
                  padding: '8px 16px', borderRadius: 7,
                  border: '1px solid var(--wire)', background: 'transparent',
                  color: 'var(--chalk2)', fontFamily: 'var(--font)', fontSize: 12, cursor: 'pointer',
                }}
              >Cancel</button>
              <button
                onClick={handleCreate}
                disabled={!newName.trim() || createWorkflow.isPending}
                style={{
                  padding: '8px 18px', borderRadius: 7, border: 'none',
                  background: newName.trim() ? 'var(--brand)' : 'var(--wire)',
                  color: newName.trim() ? '#050810' : 'var(--chalk3)',
                  fontFamily: 'var(--font)', fontWeight: 700, fontSize: 12,
                  cursor: newName.trim() ? 'pointer' : 'not-allowed',
                }}
              >
                {createWorkflow.isPending ? 'Creating…' : 'Create'}
              </button>
            </div>
          </GlassModal>
      )}
    </div>
  );
}

const ghostBtn: React.CSSProperties = {
  padding: '5px 12px', borderRadius: 7,
  border: '1px solid var(--wire)', background: 'transparent',
  color: 'var(--chalk2)', fontFamily: 'var(--font)', fontSize: 11,
  cursor: 'pointer',
};
