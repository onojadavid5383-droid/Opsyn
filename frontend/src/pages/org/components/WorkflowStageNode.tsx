// ============================================================
// WORKFLOW STAGE NODE — single department node on the canvas
// ============================================================

import type { WorkflowEdge } from '../../../types/workflow.types';

interface WorkflowStageNodeProps {
  edge: WorkflowEdge;
  isSelected: boolean;
  isEntry: boolean;
  canEdit: boolean;
  onSelect: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
  isFirst: boolean;
  isLast: boolean;
}

const PARALLEL_COLORS = [
  '#7c5ff0', '#0ea5e9', '#10b981', '#f59e0b',
  '#ef4444', '#ec4899', '#8b5cf6', '#06b6d4',
];

function parallelColor(groupId: string): string {
  let hash = 0;
  for (const c of groupId) hash = (hash * 31 + c.charCodeAt(0)) & 0xffffff;
  return PARALLEL_COLORS[hash % PARALLEL_COLORS.length];
}

export function WorkflowStageNode({
  edge, isSelected, isEntry, canEdit,
  onSelect, onMoveUp, onMoveDown, onRemove,
  isFirst, isLast,
}: WorkflowStageNodeProps) {
  const parallelClr = edge.parallelGroupId ? parallelColor(edge.parallelGroupId) : 'var(--brand)';

  return (
    <div
      onClick={onSelect}
      style={{
        position: 'relative',
        padding: '12px 14px',
        borderRadius: 10,
        border: `2px solid ${isSelected ? 'var(--brand)' : edge.isParallel ? parallelClr + '55' : 'var(--wire)'}`,
        background: isSelected ? 'rgba(110,231,183,.08)' : 'var(--bg2)',
        cursor: 'pointer',
        minWidth: 140,
        transition: 'border-color .15s, box-shadow .15s',
        boxShadow: isSelected ? '0 0 0 3px rgba(110,231,183,.15)' : 'none',
        userSelect: 'none',
      }}
    >
      {/* entry badge */}
      {isEntry && (
        <span style={{
          position: 'absolute', top: -10, left: 12,
          fontSize: 9, fontWeight: 700, letterSpacing: '.06em',
          background: 'var(--brand)', color: '#050810',
          padding: '1px 6px', borderRadius: 4,
        }}>ENTRY</span>
      )}

      {/* parallel badge */}
      {edge.isParallel && (
        <span style={{
          position: 'absolute', top: -10, right: 12,
          fontSize: 9, fontWeight: 700, letterSpacing: '.06em',
          background: parallelClr, color: '#fff',
          padding: '1px 6px', borderRadius: 4,
        }}>
          {edge.parallelGroupId ? `∥ ${edge.parallelGroupId}` : '∥ PARALLEL'}
        </span>
      )}

      {/* order badge */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6,
      }}>
        <span style={{
          width: 22, height: 22, borderRadius: '50%',
          background: 'var(--wire)', color: 'var(--chalk)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 11, fontWeight: 700, flexShrink: 0,
        }}>{edge.edgeOrder}</span>
        <span style={{
          fontSize: 13, fontWeight: 600, color: 'var(--chalk)',
          lineHeight: 1.3, flex: 1,
        }}>{edge.toDeptName}</span>
      </div>

      {/* meta row */}
      {(edge.label || edge.expectedDays) && (
        <div style={{ fontSize: 11, color: 'var(--chalk3)', lineHeight: 1.4 }}>
          {edge.label && <div style={{ marginBottom: 2 }}>{edge.label}</div>}
          {edge.expectedDays && <div>~{edge.expectedDays}d expected</div>}
        </div>
      )}
      {edge.gateRequiresGroup && (
        <div style={{
          marginTop: 4, fontSize: 10, color: 'var(--amber)',
          display: 'flex', alignItems: 'center', gap: 4,
        }}>
          <span>⛩</span> gate: {edge.gateRequiresGroup}
        </div>
      )}
      {!edge.canPushBack && (
        <div style={{ marginTop: 4, fontSize: 10, color: 'var(--chalk3)' }}>
          no push-back
        </div>
      )}

      {/* reorder + remove controls */}
      {canEdit && (
        <div
          style={{
            display: 'flex', gap: 4, marginTop: 8,
            justifyContent: 'flex-end',
          }}
          onClick={e => e.stopPropagation()}
        >
          <button
            disabled={isFirst}
            onClick={onMoveUp}
            style={btnStyle(isFirst)}
            title="Move earlier"
          >↑</button>
          <button
            disabled={isLast}
            onClick={onMoveDown}
            style={btnStyle(isLast)}
            title="Move later"
          >↓</button>
          <button
            onClick={onRemove}
            style={{ ...btnStyle(false), color: 'var(--red)', borderColor: 'rgba(239,68,68,.3)' }}
            title="Remove stage"
          >×</button>
        </div>
      )}
    </div>
  );
}

function btnStyle(disabled: boolean) {
  return {
    padding: '2px 7px', borderRadius: 5, fontSize: 12, cursor: disabled ? 'not-allowed' : 'pointer',
    border: '1px solid var(--wire)', background: 'var(--bg)', color: 'var(--chalk2)',
    opacity: disabled ? 0.35 : 1, lineHeight: 1.4,
  };
}
