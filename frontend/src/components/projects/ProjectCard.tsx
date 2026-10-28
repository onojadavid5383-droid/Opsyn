// ============================================================
// OPSYN PROJECT CARD — S2.2.4
// PRJ badge · type badge · current stage · progress bar
// ============================================================

import { useNavigate } from 'react-router-dom';
import type { Project } from '@shared';

const TYPE_LABELS: Record<string, string> = {
  internal:         'Internal',
  external:         'External',
  cable_upgrade:    'Cable Upgrade',
  olt_installation: 'OLT Installation',
  procurement:      'Procurement',
};

const TYPE_COLORS: Record<string, string> = {
  internal:         'var(--cyan)',
  external:         'var(--violet)',
  cable_upgrade:    'var(--amber)',
  olt_installation: 'var(--green)',
  procurement:      'var(--rose)',
};

const PIPELINE_STATUS_COLORS: Record<string, string> = {
  not_started: 'var(--chalk3)',
  active:      'var(--cyan)',
  stalled:     'var(--amber)',
  completed:   'var(--green)',
  cancelled:   'var(--rose)',
};

interface Props {
  project: Project;
}

export default function ProjectCard({ project }: Props) {
  const navigate  = useNavigate();
  const typeColor = TYPE_COLORS[project.project_type]  ?? 'var(--chalk3)';
  const pipeColor = PIPELINE_STATUS_COLORS[project.pipeline_status ?? 'not_started'] ?? 'var(--chalk3)';
  const pct       = project.completion_pct ?? 0;

  return (
    <div
      onClick={() => navigate(`/projects/${project.id}`)}
      style={{
        background:   'var(--bg2)',
        border:       '1px solid var(--wire2)',
        borderRadius: 12,
        padding:      12,
        cursor:       'pointer',
        transition:   'all .18s',
        position:     'relative',
      }}
    >
      {/* PRJ badge + type badge */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        {project.ticket_number && (
          <span
            onClick={e => { e.stopPropagation(); navigator.clipboard.writeText(project.ticket_number!); }}
            title="Copy ticket"
            style={{
              fontFamily: 'var(--mono)', fontSize: 9, fontWeight: 700,
              color: 'var(--brand)', letterSpacing: '0.06em', cursor: 'copy',
            }}
          >
            {project.ticket_number}
          </span>
        )}
        <span style={{
          fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
          background: `${typeColor}18`, color: typeColor,
        }}>
          {TYPE_LABELS[project.project_type] ?? project.project_type}
        </span>
      </div>

      {/* Project name */}
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--chalk)', lineHeight: 1.3, marginBottom: 6 }}>
        {project.name}
      </div>

      {/* Current stage */}
      {project.pipeline_status && project.pipeline_status !== 'not_started' && (
        <div style={{ fontSize: 10, color: pipeColor, marginBottom: 8 }}>
          {(project.pipeline_status).replace(/_/g, ' ').toUpperCase()}
        </div>
      )}

      {/* Progress bar */}
      <div style={{ height: 4, borderRadius: 2, background: 'var(--wire)', overflow: 'hidden' }}>
        <div style={{
          height: '100%', borderRadius: 2,
          width: `${pct}%`,
          background: pct >= 100 ? 'var(--green)' : pct > 50 ? 'var(--cyan)' : 'var(--amber)',
          transition: 'width .4s ease',
        }} />
      </div>
      <div style={{ fontSize: 9, color: 'var(--chalk3)', marginTop: 3 }}>{pct}% complete</div>
    </div>
  );
}
