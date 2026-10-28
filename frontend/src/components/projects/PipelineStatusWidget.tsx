// ============================================================
// PIPELINE STATUS WIDGET COMPONENT
// Dashboard widget showing pipeline overview
// ============================================================

import { useQuery } from '@tanstack/react-query';
import { projectsApi } from '../../api/projects.api';

export function PipelineStatusWidget() {
  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects', 'pipeline-status'],
    queryFn: () => projectsApi.list(),
    refetchInterval: 30000 // Refresh every 30 seconds
  });

  if (isLoading) {
    return (
      <div style={{
        background: 'var(--bg2)',
        border: '1px solid var(--wire)',
        borderRadius: 12,
        padding: 16,
        height: 200,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }}>
        <span style={{ color: 'var(--chalk3)', fontSize: 12 }}>Loading pipeline status...</span>
      </div>
    );
  }

  const items = (projects as any)?.items ?? [];
  const pipelineProjects = items.filter((p: any) => p.pipeline_template_id);

  const stats = {
    active: pipelineProjects.filter((p: any) => p.pipeline_status === 'active').length,
    completed: pipelineProjects.filter((p: any) => p.pipeline_status === 'completed').length,
    paused: pipelineProjects.filter((p: any) => p.pipeline_status === 'paused').length,
    total: pipelineProjects.length
  };

  const getStageDistribution = () => {
    const stages: Record<string, number> = {};
    pipelineProjects.forEach((p: any) => {
      if (p.current_stage_name) {
        stages[p.current_stage_name] = (stages[p.current_stage_name] || 0) + 1;
      }
    });
    return Object.entries(stages).sort(([,a], [,b]) => b - a).slice(0, 5);
  };

  const stageDistribution = getStageDistribution();

  return (
    <div style={{
      background: 'var(--bg2)',
      border: '1px solid var(--wire)',
      borderRadius: 12,
      padding: 16
    }}>
      <div style={{
        fontSize: 14,
        fontWeight: 600,
        color: 'var(--chalk)',
        marginBottom: 16
      }}>
        Pipeline Status
      </div>

      {/* Status Summary */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div style={{
            fontSize: 20,
            fontWeight: 700,
            color: 'var(--brand)',
            marginBottom: 4
          }}>
            {stats.active}
          </div>
          <div style={{
            fontSize: 10,
            color: 'var(--chalk3)',
            textTransform: 'uppercase',
            letterSpacing: 0.5
          }}>
            Active
          </div>
        </div>
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div style={{
            fontSize: 20,
            fontWeight: 700,
            color: 'var(--green)',
            marginBottom: 4
          }}>
            {stats.completed}
          </div>
          <div style={{
            fontSize: 10,
            color: 'var(--chalk3)',
            textTransform: 'uppercase',
            letterSpacing: 0.5
          }}>
            Completed
          </div>
        </div>
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div style={{
            fontSize: 20,
            fontWeight: 700,
            color: 'var(--amber)',
            marginBottom: 4
          }}>
            {stats.paused}
          </div>
          <div style={{
            fontSize: 10,
            color: 'var(--chalk3)',
            textTransform: 'uppercase',
            letterSpacing: 0.5
          }}>
            Paused
        </div>
        </div>
      </div>

      {/* Current Stages */}
      {stageDistribution.length > 0 && (
        <div>
          <div style={{
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--chalk)',
            marginBottom: 8
          }}>
            Current Stages
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {stageDistribution.map(([stageName, count]) => (
              <div
                key={stageName}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  fontSize: 11,
                  color: 'var(--chalk2)'
                }}
              >
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {stageName}
                </span>
                <span style={{
                  background: 'var(--bg3)',
                  padding: '2px 6px',
                  borderRadius: 4,
                  fontSize: 10,
                  fontWeight: 600,
                  color: 'var(--chalk)'
                }}>
                  {count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {stats.total === 0 && (
        <div style={{
          textAlign: 'center',
          color: 'var(--chalk3)',
          fontSize: 12,
          padding: 20
        }}>
          No pipeline projects yet
        </div>
      )}
    </div>
  );
}