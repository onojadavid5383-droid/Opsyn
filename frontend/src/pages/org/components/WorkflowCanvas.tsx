// ============================================================
// WORKFLOW CANVAS — Phase A: linear list with parallel groups
// ============================================================

import { useState } from 'react';
import type { WorkflowEdge, AddEdgePayload } from '../../../types/workflow.types';
import type { Department } from '@shared';
import { WorkflowStageNode } from './WorkflowStageNode';
import { useAddEdge, useRemoveEdge, useUpdateEdge } from '../../../hooks/useWorkflows';
import { GlassSelect } from '../../../components/glass';

interface WorkflowCanvasProps {
  workflowId: string;
  edges: WorkflowEdge[];
  departments: Department[];
  canEdit: boolean;
  selectedEdgeId: string | null;
  onSelectEdge: (id: string | null) => void;
}

// Group edges by edge_order, preserving order
function groupByOrder(edges: WorkflowEdge[]): Map<number, WorkflowEdge[]> {
  const sorted = [...edges].sort((a, b) => a.edgeOrder - b.edgeOrder);
  const map = new Map<number, WorkflowEdge[]>();
  for (const e of sorted) {
    const bucket = map.get(e.edgeOrder) ?? [];
    bucket.push(e);
    map.set(e.edgeOrder, bucket);
  }
  return map;
}

const ArrowDown = () => (
  <div style={{ display: 'flex', justifyContent: 'center', padding: '6px 0' }}>
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0,
    }}>
      <div style={{ width: 1, height: 14, background: 'var(--wire2)' }} />
      <svg width="10" height="7" viewBox="0 0 10 7" fill="var(--wire2)">
        <path d="M5 7L0 0h10z" />
      </svg>
    </div>
  </div>
);

export function WorkflowCanvas({
  workflowId, edges, departments, canEdit, selectedEdgeId, onSelectEdge,
}: WorkflowCanvasProps) {
  const addEdge    = useAddEdge(workflowId);
  const removeEdge = useRemoveEdge(workflowId);
  const updateEdge = useUpdateEdge(workflowId);

  const [showAdd, setShowAdd] = useState(false);
  const [addDeptId, setAddDeptId] = useState('');
  const [addLabel, setAddLabel] = useState('');

  const grouped = groupByOrder(edges);
  const orderKeys = [...grouped.keys()].sort((a, b) => a - b);
  const maxOrder = orderKeys.length ? Math.max(...orderKeys) : 0;

  function handleAdd() {
    if (!addDeptId) return;
    const payload: AddEdgePayload = {
      to_dept_id: addDeptId,
      edge_order: maxOrder + 1,
      label: addLabel || undefined,
      can_push_back: true,
    };
    addEdge.mutate(payload, {
      onSuccess: () => {
        setAddDeptId('');
        setAddLabel('');
        setShowAdd(false);
      },
    });
  }

  function handleMoveUp(edge: WorkflowEdge) {
    const prevOrder = orderKeys[orderKeys.indexOf(edge.edgeOrder) - 1];
    if (prevOrder === undefined) return;
    updateEdge.mutate({ edgeId: edge.id, payload: { edge_order: prevOrder } });
  }

  function handleMoveDown(edge: WorkflowEdge) {
    const nextOrder = orderKeys[orderKeys.indexOf(edge.edgeOrder) + 1];
    if (nextOrder === undefined) return;
    updateEdge.mutate({ edgeId: edge.id, payload: { edge_order: nextOrder } });
  }

  if (edges.length === 0 && !canEdit) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: 'var(--chalk3)', fontSize: 13 }}>
        No stages configured for this workflow.
      </div>
    );
  }

  return (
    <div style={{
      flex: 1, overflowY: 'auto', padding: '24px 28px',
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      scrollbarWidth: 'thin',
    }}>
      {/* Entry cap */}
      {edges.length > 0 && (
        <div style={{
          padding: '4px 14px', borderRadius: 6, fontSize: 10, fontWeight: 700,
          letterSpacing: '.08em', background: 'var(--brand)', color: '#050810',
          marginBottom: 8,
        }}>START</div>
      )}

      {orderKeys.map((order, idx) => {
        const group = grouped.get(order)!;
        const isLastGroup = idx === orderKeys.length - 1;

        return (
          <div key={order} style={{ width: '100%', maxWidth: 560 }}>
            {/* parallel group row */}
            <div style={{
              display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap',
            }}>
              {group.map((edge, edgeIdx) => (
                <WorkflowStageNode
                  key={edge.id}
                  edge={edge}
                  isSelected={selectedEdgeId === edge.id}
                  isEntry={idx === 0}
                  canEdit={canEdit}
                  onSelect={() => onSelectEdge(selectedEdgeId === edge.id ? null : edge.id)}
                  onMoveUp={() => handleMoveUp(edge)}
                  onMoveDown={() => handleMoveDown(edge)}
                  onRemove={() => {
                    if (selectedEdgeId === edge.id) onSelectEdge(null);
                    removeEdge.mutate(edge.id);
                  }}
                  isFirst={idx === 0 && edgeIdx === 0}
                  isLast={isLastGroup}
                />
              ))}
            </div>

            {/* arrow between groups */}
            {!isLastGroup && <ArrowDown />}
          </div>
        );
      })}

      {/* Terminal cap */}
      {edges.length > 0 && (
        <>
          <ArrowDown />
          <div style={{
            padding: '4px 14px', borderRadius: 6, fontSize: 10, fontWeight: 700,
            letterSpacing: '.08em', border: '1px solid var(--wire2)',
            color: 'var(--chalk3)',
          }}>END</div>
        </>
      )}

      {/* Add stage section */}
      {canEdit && (
        <div style={{ marginTop: 24, width: '100%', maxWidth: 400 }}>
          {!showAdd ? (
            <button
              onClick={() => setShowAdd(true)}
              style={{
                width: '100%', padding: '9px', borderRadius: 8,
                border: '1px dashed var(--wire2)', background: 'transparent',
                color: 'var(--chalk3)', fontFamily: 'var(--font)', fontSize: 12,
                cursor: 'pointer', display: 'flex', alignItems: 'center',
                justifyContent: 'center', gap: 6,
              }}
            >
              <span style={{ fontSize: 16, lineHeight: 1 }}>+</span>
              Add stage
            </button>
          ) : (
            <div style={{
              padding: 14, borderRadius: 10,
              border: '1px solid var(--wire)', background: 'var(--bg2)',
              display: 'flex', flexDirection: 'column', gap: 10,
            }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--chalk)' }}>Add next stage</div>

              <GlassSelect value={String(addDeptId)} onChange={v => setAddDeptId(v)} options={[...departments.map((d) => ({ value: String(d.id), label: String(d.name) }))]} placeholder={'Select department…'} ariaLabel="Department" />

              <input
                type="text"
                placeholder="Label (optional)"
                value={addLabel}
                onChange={e => setAddLabel(e.target.value)}
                style={{
                  padding: '7px 10px', borderRadius: 7,
                  border: '1px solid var(--wire)', background: 'var(--bg)',
                  color: 'var(--chalk)', fontSize: 12, fontFamily: 'var(--font)',
                  width: '100%', boxSizing: 'border-box',
                }}
              />

              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={handleAdd}
                  disabled={!addDeptId || addEdge.isPending}
                  style={{
                    flex: 1, padding: '8px', borderRadius: 7, border: 'none',
                    background: addDeptId ? 'var(--brand)' : 'var(--wire)',
                    color: addDeptId ? '#050810' : 'var(--chalk3)',
                    fontFamily: 'var(--font)', fontWeight: 700, fontSize: 12,
                    cursor: addDeptId ? 'pointer' : 'not-allowed',
                  }}
                >
                  {addEdge.isPending ? 'Adding…' : 'Add'}
                </button>
                <button
                  onClick={() => { setShowAdd(false); setAddDeptId(''); setAddLabel(''); }}
                  style={{
                    padding: '8px 14px', borderRadius: 7,
                    border: '1px solid var(--wire)', background: 'transparent',
                    color: 'var(--chalk2)', fontFamily: 'var(--font)', fontSize: 12,
                    cursor: 'pointer',
                  }}
                >Cancel</button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* empty state prompt */}
      {edges.length === 0 && canEdit && (
        <p style={{ color: 'var(--chalk3)', fontSize: 12, marginTop: 16, textAlign: 'center' }}>
          Add your first department stage above to start building this workflow.
        </p>
      )}
    </div>
  );
}
