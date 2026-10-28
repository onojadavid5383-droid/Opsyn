// ============================================================
// EDGE CONFIG PANEL — right-side form for editing a workflow edge
// ============================================================

import { useState, useEffect } from 'react';
import type { WorkflowEdge, UpdateEdgePayload } from '../../../types/workflow.types';
import { useUpdateEdge } from '../../../hooks/useWorkflows';

interface EdgeConfigPanelProps {
  workflowId: string;
  edge: WorkflowEdge;
  onClose: () => void;
}

const field: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 14,
};

const label: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, letterSpacing: '.08em',
  textTransform: 'uppercase', color: 'var(--chalk3)',
};

const input: React.CSSProperties = {
  padding: '7px 10px', borderRadius: 7,
  border: '1px solid var(--wire)', background: 'var(--bg)',
  color: 'var(--chalk)', fontSize: 12, fontFamily: 'var(--font)',
  width: '100%', boxSizing: 'border-box',
};

const toggleRow: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  padding: '8px 10px', borderRadius: 7,
  border: '1px solid var(--wire)', background: 'var(--bg)', marginBottom: 14,
};

export function EdgeConfigPanel({ workflowId, edge, onClose }: EdgeConfigPanelProps) {
  const updateEdge = useUpdateEdge(workflowId);

  const [form, setForm] = useState({
    label: edge.label ?? '',
    isParallel: edge.isParallel,
    parallelGroupId: edge.parallelGroupId ?? '',
    gateRequiresGroup: edge.gateRequiresGroup ?? '',
    canPushBack: edge.canPushBack,
    expectedDays: edge.expectedDays ?? '',
    edgeOrder: edge.edgeOrder,
  });

  useEffect(() => {
    // Re-seeds the form when a different edge is selected. Depending on
    // // edge.id alone is deliberate: depending on the individual fields would
    // // overwrite the user's edits on every parent re-render.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setForm({
      label: edge.label ?? '',
      isParallel: edge.isParallel,
      parallelGroupId: edge.parallelGroupId ?? '',
      gateRequiresGroup: edge.gateRequiresGroup ?? '',
      canPushBack: edge.canPushBack,
      expectedDays: edge.expectedDays ?? '',
      edgeOrder: edge.edgeOrder,
    });
  // Re-seeds the form when a different edge is selected. Depending on
  // // edge.id alone is deliberate: depending on the individual fields would
  // // overwrite the user's edits on every parent re-render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edge.id]);

  const saving = updateEdge.isPending;

  function save() {
    const payload: UpdateEdgePayload = {
      label: form.label || undefined,
      is_parallel: form.isParallel,
      parallel_group_id: form.isParallel && form.parallelGroupId ? form.parallelGroupId : null,
      gate_requires_group: form.gateRequiresGroup || null,
      can_push_back: form.canPushBack,
      expected_days: form.expectedDays !== '' ? Number(form.expectedDays) : null,
      edge_order: Number(form.edgeOrder),
    };
    updateEdge.mutate({ edgeId: edge.id, payload });
  }

  return (
    <div style={{
      width: 260, flexShrink: 0,
      background: 'var(--bg2)', borderLeft: '1px solid var(--wire)',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
    }}>
      {/* header */}
      <div style={{
        padding: '12px 14px 10px', borderBottom: '1px solid var(--wire)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--chalk)' }}>Edit Stage</div>
          <div style={{ fontSize: 10, color: 'var(--chalk3)', marginTop: 1 }}>{edge.toDeptName}</div>
        </div>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', cursor: 'pointer',
                   color: 'var(--chalk3)', fontSize: 16, lineHeight: 1, padding: 4 }}
        >×</button>
      </div>

      {/* form body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '14px', scrollbarWidth: 'none' }}>
        <div style={field}>
          <span style={label}>Step order</span>
          <input
            type="number" min={1} style={input}
            value={form.edgeOrder}
            onChange={e => setForm(f => ({ ...f, edgeOrder: Number(e.target.value) }))}
          />
          <span style={{ fontSize: 10, color: 'var(--chalk3)' }}>
            Stages with the same order run in parallel
          </span>
        </div>

        <div style={field}>
          <span style={label}>Label / note</span>
          <input
            type="text" style={input} placeholder="e.g. Technical review"
            value={form.label}
            onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
          />
        </div>

        <div style={field}>
          <span style={label}>Expected duration (days)</span>
          <input
            type="number" min={1} style={input} placeholder="e.g. 3"
            value={form.expectedDays}
            onChange={e => setForm(f => ({ ...f, expectedDays: e.target.value }))}
          />
        </div>

        <div style={toggleRow}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--chalk)' }}>Parallel stage</div>
            <div style={{ fontSize: 10, color: 'var(--chalk3)', marginTop: 1 }}>
              Runs alongside stages at same order
            </div>
          </div>
          <Toggle value={form.isParallel} onChange={v => setForm(f => ({ ...f, isParallel: v }))} />
        </div>

        {form.isParallel && (
          <div style={field}>
            <span style={label}>Parallel group ID</span>
            <input
              type="text" style={input} placeholder="e.g. review"
              value={form.parallelGroupId}
              onChange={e => setForm(f => ({ ...f, parallelGroupId: e.target.value }))}
            />
            <span style={{ fontSize: 10, color: 'var(--chalk3)' }}>
              Stages sharing a group ID are visually grouped
            </span>
          </div>
        )}

        <div style={{ height: 1, background: 'var(--wire)', margin: '6px 0 16px' }} />

        <div style={toggleRow}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--chalk)' }}>Allow push-back</div>
            <div style={{ fontSize: 10, color: 'var(--chalk3)', marginTop: 1 }}>
              Dept can reject and revert to sender
            </div>
          </div>
          <Toggle value={form.canPushBack} onChange={v => setForm(f => ({ ...f, canPushBack: v }))} />
        </div>

        <div style={field}>
          <span style={label}>Gate: requires group</span>
          <input
            type="text" style={input} placeholder="e.g. management"
            value={form.gateRequiresGroup}
            onChange={e => setForm(f => ({ ...f, gateRequiresGroup: e.target.value }))}
          />
          <span style={{ fontSize: 10, color: 'var(--chalk3)' }}>
            Only users in this role group can approve entry
          </span>
        </div>

        {updateEdge.isError && (
          <div style={{ padding: '8px 10px', borderRadius: 7, background: 'rgba(239,68,68,.1)',
                        border: '1px solid rgba(239,68,68,.25)', fontSize: 11, color: 'var(--red)',
                        marginBottom: 14 }}>
            Save failed — check inputs and try again.
          </div>
        )}

        <button
          onClick={save}
          disabled={saving}
          style={{
            width: '100%', padding: '9px', borderRadius: 8, border: 'none',
            background: saving ? 'var(--wire)' : 'var(--brand)',
            color: saving ? 'var(--chalk3)' : '#050810',
            fontFamily: 'var(--font)', fontWeight: 700, fontSize: 12,
            cursor: saving ? 'not-allowed' : 'pointer',
          }}
        >
          {saving ? 'Saving…' : 'Save changes'}
        </button>
      </div>
    </div>
  );
}

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <div
      onClick={() => onChange(!value)}
      style={{
        width: 38, height: 21, borderRadius: 11, cursor: 'pointer',
        background: value ? 'var(--brand)' : 'var(--wire)',
        position: 'relative', transition: 'background .2s', flexShrink: 0,
      }}
    >
      <div style={{
        position: 'absolute', top: 3, left: value ? 20 : 3,
        width: 15, height: 15, borderRadius: '50%',
        background: value ? '#050810' : 'var(--chalk3)',
        transition: 'left .2s',
      }} />
    </div>
  );
}
