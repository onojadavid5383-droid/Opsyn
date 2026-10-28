// ============================================================
// PIPELINE STAGE RAIL — S2.2.3
// Enhanced: timing, duration colours, dept visibility gate,
// entered_at / exited_at / expected_duration display.
// ============================================================

import type { ProjectPipelineStage } from '@shared';

interface PipelineStageRailProps {
  stages:          ProjectPipelineStage[];
  currentStageId?: string;
  callerDeptId?:   string;
  onStageClick:    (stageId: string) => void;
}

function durationDays(enteredAt: string | null, exitedAt: string | null): number | null {
  if (!enteredAt) return null;
  const end = exitedAt ? new Date(exitedAt) : new Date();
  const start = new Date(enteredAt);
  return Math.max(0, Math.round((end.getTime() - start.getTime()) / 86_400_000));
}

function stageBorderColor(
  status: string,
  isCurrent: boolean,
  durationDays: number | null,
  expectedDays: number | null,
): string {
  if (isCurrent) return 'var(--cyan)';
  if (status === 'approved') {
    if (durationDays !== null && expectedDays !== null) {
      if (durationDays > expectedDays * 1.5) return 'var(--rose)';
      if (durationDays > expectedDays)       return 'var(--amber)';
      return 'var(--green)';
    }
    return 'var(--green)';
  }
  if (status === 'pushed_back') return 'var(--amber)';
  return 'var(--wire2)';
}

function stageBg(status: string, isCurrent: boolean): string {
  if (isCurrent)                 return 'rgba(6,182,212,.12)';
  if (status === 'approved')     return 'rgba(74,222,128,.08)';
  if (status === 'pushed_back')  return 'rgba(251,191,36,.08)';
  return 'var(--bg3)';
}

function stageTextColor(status: string, isCurrent: boolean): string {
  if (isCurrent)                 return 'var(--cyan)';
  if (status === 'approved')     return 'var(--green)';
  if (status === 'pushed_back')  return 'var(--amber)';
  return 'var(--chalk3)';
}

export function PipelineStageRail({ stages, currentStageId, callerDeptId, onStageClick }: PipelineStageRailProps) {
  const sorted = [...stages].sort((a, b) => a.stageOrder - b.stageOrder);

  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 0, overflowX: 'auto', padding: '4px 0' }}>
      {sorted.map((stage, i) => {
        const isCurrent  = stage.id === currentStageId;
        const durDays    = durationDays(stage.enteredAt, stage.exitedAt);
        const expDays    = (stage as any).expectedDurationDays ?? null;
        const borderCol  = stageBorderColor(stage.status, isCurrent, durDays, expDays);
        const textColor  = stageTextColor(stage.status, isCurrent);
        const isCallerDept = callerDeptId ? stage.departmentId === callerDeptId : true;

        return (
          <div key={stage.id} style={{ display: 'flex', alignItems: 'center' }}>
            {/* Stage node */}
            <button
              onClick={() => onStageClick(stage.id)}
              title={`${stage.stageName} — ${stage.departmentName}${durDays !== null ? ` · ${durDays}d elapsed` : ''}`}
              style={{
                display:        'flex',
                flexDirection:  'column',
                alignItems:     'center',
                gap:            4,
                padding:        '10px 12px',
                borderRadius:   10,
                border:         `2px solid ${borderCol}`,
                background:     stageBg(stage.status, isCurrent),
                cursor:         'pointer',
                minWidth:       84,
                transition:     'all .18s',
                boxShadow:      isCurrent ? `0 0 12px ${borderCol}33` : 'none',
                outline:        'none',
              }}
            >
              {/* Step number circle */}
              <div style={{
                width: 22, height: 22, borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 10, fontWeight: 700,
                background: isCurrent ? 'var(--cyan)' : stage.status === 'approved' ? 'var(--green)' : 'var(--wire)',
                color:      isCurrent ? '#050810'     : stage.status === 'approved' ? '#050810'      : 'var(--chalk2)',
              }}>
                {stage.status === 'approved' ? '✓' : stage.stageOrder}
              </div>

              {/* Stage name */}
              <span style={{ fontSize: 10, fontWeight: 600, color: textColor, textAlign: 'center', lineHeight: 1.2, maxWidth: 72 }}>
                {stage.stageName}
              </span>

              {/* Department — dimmed for non-dept members */}
              <span style={{ fontSize: 9, color: isCallerDept ? 'var(--chalk2)' : 'var(--chalk4)', textAlign: 'center' }}>
                {stage.departmentName}
              </span>

              {/* Duration chip */}
              {durDays !== null && (
                <span style={{
                  fontSize: 8, fontFamily: 'var(--mono)',
                  color: expDays && durDays > expDays * 1.5 ? 'var(--rose)'
                       : expDays && durDays > expDays       ? 'var(--amber)'
                       : 'var(--chalk3)',
                }}>
                  {durDays}d{expDays ? ` / ${expDays}d` : ''}
                </span>
              )}
            </button>

            {/* Connector */}
            {i < sorted.length - 1 && (
              <div style={{
                width:      28,
                height:     2,
                background: stage.status === 'approved' ? 'var(--green)' : 'var(--wire2)',
                flexShrink: 0,
                transition: 'background .3s',
              }} />
            )}
          </div>
        );
      })}
    </div>
  );
}
