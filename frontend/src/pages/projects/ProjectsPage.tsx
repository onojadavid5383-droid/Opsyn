// ============================================================
// OPSYN — ProjectsPage  (Phase 5 refactor)
// Projects are auto-generated from External Tasks.
// Creation is disabled; quick-action opens NewTaskModal.
// ============================================================

import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { projectsApi, orgApi } from '../../api/index';
import { Button, Badge, Select } from '../../components/ui';
import NewTaskModal from '../tasks/components/NewTaskModal';
import { Plus } from 'lucide-react';
import { Page, PageHeader } from '../../components/layout/Page';

const toArr = (d: any): any[] => Array.isArray(d) ? d : (d?.items ?? []);

const STATUS_COLOR: Record<string, string> = {
  active:    'var(--color-teal)',
  completed: 'var(--color-green)',
  paused:    'var(--color-amber)',
};
const STATUS_VARIANT: Record<string, any> = {
  active:    'resolved',
  completed: 'info',
  paused:    'warning',
};

const STAGE_LABELS: Record<string, string> = {
  backlog:     'Backlog',
  in_progress: 'In Progress',
  review:      'Review',
  unit_done:   'Unit Done',
  archive:     'Archive',
};
const STAGE_COLOR: Record<string, string> = {
  backlog:     'var(--color-text-muted)',
  in_progress: 'var(--color-teal)',
  review:      'var(--color-amber)',
  unit_done:   'var(--color-green)',
  archive:     'var(--color-indigo)',
};

function Pbar({ value, color = 'var(--color-teal)' }: { value: number; color?: string }) {
  return (
    <div style={{ height: 4, background: 'var(--color-border)', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{
        height: '100%', width: `${Math.min(100, Math.max(0, value))}%`,
        background: color, borderRadius: 2, transition: 'width .3s',
      }} />
    </div>
  );
}

export default function ProjectsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [newTaskOpen, setNewTaskOpen] = useState(false);
  const [newNetworkOpen, setNewNetworkOpen] = useState(false);
  const [networkName, setNetworkName] = useState('');
  const [networkDescription, setNetworkDescription] = useState('');

  // ── Filters ──────────────────────────────────────────────────
  const [filterDept,   setFilterDept]   = useState('');
  const [filterStage,  setFilterStage]  = useState('');
  const [filterSource, setFilterSource] = useState('');

  const { data, isLoading } = useQuery({ queryKey: ['projects'], queryFn: () => projectsApi.list() });
  const { data: depts }     = useQuery({ queryKey: ['departments'], queryFn: () => orgApi.getDepartments() });
  const createNetworkProject = useMutation({
    mutationFn: () => projectsApi.create({ name: networkName.trim(), description: networkDescription.trim() || undefined, project_type: 'infrastructure' }),
    onSuccess: project => {
      void qc.invalidateQueries({ queryKey: ['projects'] });
      setNewNetworkOpen(false);
      setNetworkName('');
      setNetworkDescription('');
      navigate(`/projects/${project.id}?tab=designs`);
    },
  });

  const projects  = toArr(data);
  const deptList  = toArr(depts);

  const networkProjects = projects.filter((p: any) => p.project_type === 'infrastructure');
  const taskProjects = projects.filter((p: any) => p.project_type !== 'infrastructure');
  const [projectView, setProjectView] = useState<'all' | 'network' | 'tasks'>('all');

  const filtered = useMemo(() => {
    return projects.filter((p: any) => {
      if (projectView === 'network' && p.project_type !== 'infrastructure') return false;
      if (projectView === 'tasks' && p.project_type === 'infrastructure') return false;
      if (filterDept   && p.department_id !== filterDept)   return false;
      if (filterStage  && p.pipeline_stage !== filterStage) return false;
      if (filterSource && p.source_app     !== filterSource) return false;
      return true;
    });
  }, [projects, filterDept, filterStage, filterSource, projectView]);

  const sourceApps = useMemo(() => {
    const apps = new Set<string>();
    projects.forEach((p: any) => { if (p.source_app) apps.add(p.source_app); });
    return Array.from(apps);
  }, [projects]);

  return (
    <Page>

        {/* Header */}
        <PageHeader
        title="Projects"
        lede={<>{filtered.length} shown · {networkProjects.length} network · {taskProjects.length} task workflow</>}
        primary={<div style={{ display: 'flex', gap: 8 }}>
          <Button variant="secondary" size="sm" onClick={() => setNewNetworkOpen(v => !v)} leftIcon={<Plus size={16} aria-hidden="true" />}>New network project</Button>
          <Button variant="primary" size="sm" onClick={() => setNewTaskOpen(true)} leftIcon={<Plus size={16} aria-hidden="true" />}>Create External Task</Button>
        </div>}
      />

        <div role="tablist" aria-label="Project types" style={{ display: 'flex', gap: 8, margin: '0 0 18px' }}>
          {([['all', `All (${projects.length})`], ['network', `Network (${networkProjects.length})`], ['tasks', `Task workflows (${taskProjects.length})`]] as const).map(([view, label]) => (
            <button key={view} type="button" role="tab" aria-selected={projectView === view} onClick={() => setProjectView(view)}
              style={{ border: '1px solid var(--color-border)', borderRadius: 8, padding: '8px 12px', cursor: 'pointer', color: projectView === view ? 'var(--color-teal)' : 'var(--color-text-secondary)', background: projectView === view ? 'rgba(0,194,168,.1)' : 'transparent' }}>
              {label}
            </button>
          ))}
        </div>

        {newNetworkOpen && <form onSubmit={e => { e.preventDefault(); createNetworkProject.mutate(); }} style={{ display: 'grid', gap: 10, maxWidth: 620, padding: 16, marginBottom: 18, border: '1px solid var(--color-border)', borderRadius: 12, background: 'var(--surface)' }}>
          <strong>Create a network design project</strong>
          <label style={{ display: 'grid', gap: 5, fontSize: 12 }}>Project name
            <input value={networkName} onChange={e => setNetworkName(e.target.value)} maxLength={200} required placeholder="e.g. Ikeja Phase 1 fibre rollout" />
          </label>
          <label style={{ display: 'grid', gap: 5, fontSize: 12 }}>Description
            <textarea value={networkDescription} onChange={e => setNetworkDescription(e.target.value)} maxLength={2000} rows={2} placeholder="Area, scope, or delivery notes" />
          </label>
          {createNetworkProject.isError && <p role="alert" style={{ color: 'var(--color-red)', margin: 0 }}>{(createNetworkProject.error as any)?.response?.data?.detail ?? 'Could not create the network project.'}</p>}
          <div style={{ display: 'flex', gap: 8 }}>
            <Button type="submit" variant="primary" size="sm" disabled={!networkName.trim() || createNetworkProject.isPending}>{createNetworkProject.isPending ? 'Creating…' : 'Create project and open designs'}</Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setNewNetworkOpen(false)}>Cancel</Button>
          </div>
        </form>}

        {/* Info banner */}
        <div style={{
          background: 'rgba(0,194,168,.07)',
          border: '1px solid rgba(0,194,168,.25)',
          borderRadius: 8,
          padding: '10px 16px',
          fontSize: 12,
          color: 'var(--color-text-secondary)',
          marginBottom: 18,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}>
          <span style={{ fontSize: 16 }}>ℹ️</span>
          <span>
            Task workflow projects are generated from External Tasks. Network GIS projects are created here and open to their designs.{' '}
            <span
              onClick={() => setNewTaskOpen(true)}
              style={{ color: 'var(--color-teal)', fontWeight: 600, cursor: 'pointer', textDecoration: 'underline' }}
            >
              Go to Tasks to create a new workflow.
            </span>
          </span>
        </div>

        {/* Filters */}
        {(deptList.length > 0 || sourceApps.length > 0) && (
          <div style={{ display: 'flex', gap: 10, marginBottom: 18, flexWrap: 'wrap' }}>
            <Select
              label=""
              value={filterDept}
              onChange={setFilterDept}
              options={[{ label: 'All Departments', value: '' }, ...deptList.map((d: any) => ({ label: d.name, value: d.id }))]}
            />
            <Select
              label=""
              value={filterStage}
              onChange={setFilterStage}
              options={[
                { label: 'All Stages',   value: '' },
                { label: 'Backlog',      value: 'backlog' },
                { label: 'In Progress',  value: 'in_progress' },
                { label: 'Review',       value: 'review' },
                { label: 'Unit Done',    value: 'unit_done' },
                { label: 'Archive',      value: 'archive' },
              ]}
            />
            {sourceApps.length > 0 && (
              <Select
                label=""
                value={filterSource}
                onChange={setFilterSource}
                options={[{ label: 'All Sources', value: '' }, ...sourceApps.map(a => ({ label: a, value: a }))]}
              />
            )}
            {(filterDept || filterStage || filterSource) && (
              <Button variant="ghost" size="sm" onClick={() => { setFilterDept(''); setFilterStage(''); setFilterSource(''); }}>
                Clear filters
              </Button>
            )}
          </div>
        )}

        {/* Cards grid */}
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 60, color: 'var(--color-text-muted)', fontSize: 12 }}>Loading…</div>
        ) : filtered.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 60, color: 'var(--color-text-muted)', fontSize: 13 }}>
            {projects.length === 0
              ? 'No projects yet. Create an External Task to auto-generate a project.'
              : 'No projects match the selected filters.'}
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
            {filtered.map((p: any) => {
              const progress  = p.progress ?? 0;
              const barColor  = STATUS_COLOR[p.status] ?? 'var(--color-teal)';
              const stage     = p.pipeline_stage ?? '';
              const stageColor = STAGE_COLOR[stage] ?? 'var(--color-text-muted)';
              const dept = deptList.find((d: any) => d.id === p.department_id);

              return (
                <div
                  key={p.id}
                  onClick={() => navigate(p.project_type === 'infrastructure' ? `/projects/${p.id}?tab=designs` : `/projects/${p.id}/pipeline`)}
                  style={{
                    background: 'var(--surface)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 'var(--radius-card)',
                    padding: '16px 18px',
                    cursor: 'pointer',
                    transition: 'box-shadow .15s, border-color .15s',
                    borderTop: `3px solid ${barColor}`,
                  }}
                  onMouseEnter={e => {
                    (e.currentTarget as HTMLDivElement).style.boxShadow = '0 4px 16px rgba(0,0,0,.08)';
                    (e.currentTarget as HTMLDivElement).style.borderColor = barColor;
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLDivElement).style.boxShadow = '';
                    (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--color-border)';
                  }}
                >
                  {/* Title row */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
                    <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--color-text-primary)', lineHeight: 1.3, flex: 1, marginRight: 8 }}>
                      {p.name}
                    </div>
                    <Badge variant={STATUS_VARIANT[p.status] ?? 'info'} size="sm">{p.status ?? '—'}</Badge>
                  </div>

                  {/* Ticket number + auto-generated badge */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                    {p.ticket_number && (
                      <span style={{
                        fontSize: 10, fontFamily: 'var(--font-mono)',
                        color: 'var(--color-text-muted)', background: 'var(--color-surface-2)',
                        padding: '1px 5px', borderRadius: 3,
                      }}>
                        {p.ticket_number}
                      </span>
                    )}
                    {p.auto_generated && (
                      <span style={{
                        fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3,
                        background: 'rgba(99,102,241,.12)', color: 'var(--color-indigo)',
                        letterSpacing: '.04em',
                      }}>
                        AUTO
                      </span>
                    )}
                  </div>
                  {p.project_type === 'infrastructure' && <span style={{ display: 'inline-block', marginBottom: 8, padding: '3px 7px', borderRadius: 5, background: 'rgba(0,194,168,.12)', color: 'var(--color-teal)', fontSize: 9, fontWeight: 700, letterSpacing: '.06em' }}>NETWORK GIS PROJECT · OPEN DESIGNS</span>}

                  {/* Source task ref */}
                  {p.source_task_id && (
                    <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginBottom: 8 }}>
                      From task: <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-teal)' }}>
                        {p.source_task_ticket ?? p.source_task_id.slice(0, 8)}
                      </span>
                      {p.source_app && (
                        <span style={{ marginLeft: 6, color: 'var(--color-text-muted)' }}>via {p.source_app}</span>
                      )}
                    </div>
                  )}

                  {/* Description */}
                  {p.description && (
                    <div style={{
                      fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 10, lineHeight: 1.5,
                      overflow: 'hidden', display: '-webkit-box',
                      WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as any,
                    }}>
                      {p.description}
                    </div>
                  )}

                  {/* Progress */}
                  <div style={{ marginBottom: 10 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>Progress</span>
                      <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--color-text-primary)', fontWeight: 600 }}>{progress}%</span>
                    </div>
                    <Pbar value={progress} color={barColor} />
                  </div>

                  {/* Meta chips */}
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                    {stage && (
                      <span style={{
                        fontSize: 9, padding: '2px 6px', borderRadius: 4,
                        background: `${stageColor}18`, color: stageColor, fontWeight: 700,
                        fontFamily: 'var(--font-mono)', letterSpacing: '.04em',
                      }}>
                        {STAGE_LABELS[stage] ?? stage}
                      </span>
                    )}
                    {dept && (
                      <span style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>{dept.name}</span>
                    )}
                    {p.due_date && (
                      <span style={{ fontSize: 10, color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)', marginLeft: 'auto' }}>
                        Due {new Date(p.due_date).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: '2-digit' })}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      

      <NewTaskModal
        open={newTaskOpen}
        onClose={() => setNewTaskOpen(false)}
        initialScope="external"
      />
    </Page>
  );
}
