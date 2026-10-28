import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Cable, CircleCheck, Clock3, Layers3, Plus, Route, Trash2 } from 'lucide-react';
import { fttxDesignerApi, type FttxDesignRun, type FttxRunStatusValue } from '../../api/fttx-designer.api';
import { useUIStore } from '../../store/ui.store';
import { Badge, Button, DataTable, EmptyState, type BadgeVariant, type Column } from '../../components/ui';
import { ErrorBoundary } from '../../components/ErrorBoundary';
import type { ApiError } from '../../api/client';
import s from './FttxDesignerListPage.module.css';

function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, message?: string) => addToast({ type: 'success', title, message }),
    error: (title: string, message?: string) => addToast({ type: 'error', title, message }),
  };
}

const STATUS_BADGE: Record<FttxRunStatusValue, BadgeVariant> = {
  draft: 'draft', layers_pending: 'warning', ready: 'info', queued: 'info',
  running: 'warning', cancelling: 'warning', completed: 'resolved', failed: 'critical', cancelled: 'default',
};
const STATUS_LABEL: Record<FttxRunStatusValue, string> = {
  draft: 'Draft', layers_pending: 'Layers pending', ready: 'Ready', queued: 'Queued',
  running: 'Running', cancelling: 'Cancelling', completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled',
};

function NetworkSketch() {
  return (
    <svg className={s.sketch} viewBox="0 0 540 190" role="img" aria-label="Fiber route branching from feeder to distribution cabinets and home connections">
      <defs>
        <pattern id="fttx-grid" width="24" height="24" patternUnits="userSpaceOnUse">
          <path d="M24 0H0V24" fill="none" stroke="rgba(197,218,231,.08)" strokeWidth="1" />
        </pattern>
        <filter id="fttx-glow" x="-100%" y="-100%" width="300%" height="300%">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      <rect width="540" height="190" fill="url(#fttx-grid)" />
      <g fill="none" stroke="#385366" strokeWidth="2">
        <path d="M57 96H185M185 96H282M282 96L386 47M282 96L386 145M386 47H478M386 145H478" />
        <path d="M410 47V28M440 47V28M470 47V28M410 145V164M440 145V164M470 145V164" strokeWidth="1.5" />
      </g>
      <g fill="none" stroke="#00C2A8" strokeWidth="2.5" strokeLinecap="round" filter="url(#fttx-glow)">
        <path d="M57 96H185H282L386 47H478M282 96L386 145H478" />
      </g>
      <g fill="#0B1520" stroke="#00C2A8" strokeWidth="2">
        <rect x="38" y="77" width="38" height="38" rx="7" />
        <circle cx="185" cy="96" r="12" /><circle cx="282" cy="96" r="12" />
        <circle cx="386" cy="47" r="9" /><circle cx="386" cy="145" r="9" />
      </g>
      <g fill="#00C2A8">
        <circle cx="410" cy="28" r="3" /><circle cx="440" cy="28" r="3" /><circle cx="470" cy="28" r="3" />
        <circle cx="410" cy="164" r="3" /><circle cx="440" cy="164" r="3" /><circle cx="470" cy="164" r="3" />
      </g>
      <g fill="#B9C9D5" fontFamily="var(--font-sans)" fontSize="10">
        <text x="36" y="137">OLT / feeder</text><text x="159" y="126">FDT</text><text x="257" y="126">FAT</text>
        <text x="363" y="73">Distribution</text><text x="406" y="184">Homepass</text>
      </g>
      <circle cx="57" cy="96" r="3" fill="#E8FFFA" />
      <circle cx="185" cy="96" r="3" fill="#E8FFFA" />
      <circle cx="282" cy="96" r="3" fill="#E8FFFA" />
    </svg>
  );
}

function FttxDesignerListContent() {
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);

  const runsQuery = useQuery({
    queryKey: ['fttx-designer', 'runs'],
    queryFn: () => fttxDesignerApi.listRuns(),
    refetchInterval: query => query.state.data?.some(run => ['queued', 'running', 'cancelling'].includes(run.status)) ? 3000 : false,
  });
  const runs = runsQuery.data ?? [];
  const counts = useMemo(() => ({
    total: runs.length,
    completed: runs.filter(run => run.status === 'completed').length,
    active: runs.filter(run => run.status === 'queued' || run.status === 'running' || run.status === 'cancelling').length,
    layers: runs.reduce((sum, run) => sum + run.uploaded_layer_keys.length, 0),
  }), [runs]);

  const createMutation = useMutation({
    mutationFn: () => fttxDesignerApi.createRun({ name: null, config: {} }),
    onSuccess: run => {
      queryClient.invalidateQueries({ queryKey: ['fttx-designer', 'runs'] });
      navigate(`/fttx-designer/${run.id}`);
    },
    onError: (error: ApiError) => toast.error('Could not start a new run', error?.detail),
    onSettled: () => setCreating(false),
  });
  const deleteMutation = useMutation({
    mutationFn: (runId: string) => fttxDesignerApi.deleteRun(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fttx-designer', 'runs'] });
      toast.success('Run deleted');
    },
    onError: (error: ApiError) => toast.error('Could not delete run', error?.detail),
  });

  const handleCreate = () => { setCreating(true); createMutation.mutate(); };
  const handleDelete = (run: FttxDesignRun, event: React.MouseEvent) => {
    event.stopPropagation();
    if (run.status === 'queued' || run.status === 'running' || run.status === 'cancelling') {
      toast.error('Cannot delete', run.status === 'cancelling'
        ? 'Cancellation is still in progress. The run will become removable once the worker stops.'
        : 'This run is currently queued or running.');
      return;
    }
    if (!window.confirm(`Delete design run "${run.name || run.id.slice(0, 8)}"? This cannot be undone.`)) return;
    deleteMutation.mutate(run.id);
  };

  const columns: Column<FttxDesignRun>[] = [
    { key: 'name', header: 'Design run', render: (_value, run) => (
      <div className={s.runCell}>
        <span className={s.runGlyph} aria-hidden="true"><Route size={17} /></span>
        <span className={s.runCopy}>
          <span className={s.runName}>{run.name || `Untitled run — ${run.id.slice(0, 8)}`}</span>
          <span className={s.runMeta}>{run.uploaded_layer_keys.length} {run.uploaded_layer_keys.length === 1 ? 'layer' : 'layers'} uploaded</span>
        </span>
      </div>
    ) },
    { key: 'status', header: 'Status', width: 160, render: (_value, run) => (
      <Badge variant={STATUS_BADGE[run.status]} dot>{STATUS_LABEL[run.status]}</Badge>
    ) },
    { key: 'progress_pct', header: 'Progress', width: 150, render: (_value, run) => {
      const progress = run.status === 'completed' ? 100 : ['queued', 'running', 'cancelling'].includes(run.status) ? run.progress_pct : null;
      return progress === null ? <span className={s.muted}>—</span> : (
        <span className={s.progressCell}>
          <span className={s.progressTrack} aria-label={`${progress}% complete`}><span style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} /></span>
          <span>{progress}%</span>
        </span>
      );
    } },
    { key: 'created_at', header: 'Created', width: 190, render: (_value, run) => (
      <time className={s.created} dateTime={run.created_at}>{new Date(run.created_at).toLocaleString()}</time>
    ) },
    { key: 'actions', header: '', width: 64, align: 'right', render: (_value, run) => (
      <Button variant="ghost" size="xs" aria-label={`Delete ${run.name || 'design run'}`} title="Delete run"
        className={s.deleteButton} onClick={event => handleDelete(run, event)} disabled={deleteMutation.isPending}>
        <Trash2 size={15} aria-hidden="true" />
      </Button>
    ) },
  ];

  return (
    <main className={s.page}>
      <div className={s.inner}>
        <section className={s.hero} aria-labelledby="fttx-title">
          <div className={s.heroCopy}>
            <div className={s.moduleLine}><span className={s.moduleMark}><Cable size={16} /></span> Network engineering <span className={s.slash}>/</span> Fiber access</div>
            <h1 id="fttx-title">FTTx Designer</h1>
            <p>Plan distribution points and cable routes from your road, pole and homepass layers.</p>
            <Button variant="primary" size="md" leftIcon={<Plus size={17} />} onClick={handleCreate} loading={creating}>
              New design run
            </Button>
          </div>
          <div className={s.heroDrawing}><NetworkSketch /></div>
          <div className={s.heroFoot}><span><i /> Route planning workspace</span><span>FDT <b>›</b> FAT <b>›</b> Homepass</span></div>
        </section>

        <section className={s.metrics} aria-label="Design run summary">
          <div className={s.metric}><span className={s.metricIcon}><Layers3 size={17} /></span><span className={s.metricValue}>{counts.total}</span><span className={s.metricLabel}>Design runs</span></div>
          <div className={s.metric}><span className={`${s.metricIcon} ${s.okIcon}`}><CircleCheck size={17} /></span><span className={s.metricValue}>{counts.completed}</span><span className={s.metricLabel}>Completed</span></div>
          <div className={s.metric}><span className={`${s.metricIcon} ${s.activeIcon}`}><Clock3 size={17} /></span><span className={s.metricValue}>{counts.active}</span><span className={s.metricLabel}>In progress</span></div>
          <div className={s.metric}><span className={`${s.metricIcon} ${s.layerIcon}`}><Cable size={17} /></span><span className={s.metricValue}>{counts.layers}</span><span className={s.metricLabel}>Source layers</span></div>
        </section>

        <section className={s.register} aria-labelledby="runs-heading">
          <div className={s.registerHead}>
            <div><h2 id="runs-heading">Design runs</h2><p>Open a run to continue configuration or review its results.</p></div>
            <span className={s.runCount}>{counts.total} {counts.total === 1 ? 'run' : 'runs'}</span>
          </div>
          {runsQuery.isError ? (
            <div className={s.errorState} role="alert">Design runs could not be loaded. Refresh the page and try again.</div>
          ) : runsQuery.isLoading ? (
            <DataTable columns={columns} data={[]} rowKey={run => run.id} isLoading />
          ) : runs.length === 0 ? (
            <EmptyState size="md" icon={<Route size={34} strokeWidth={1.5} />} title="No design runs yet"
              message="Start with your network layers. The designer will help place distribution points, route cable and prepare a bill of quantities."
              action={{ label: 'Start a design run', onClick: handleCreate, variant: 'primary' }} />
          ) : (
            <DataTable columns={columns} data={runs} rowKey={run => run.id} onRowClick={run => navigate(`/fttx-designer/${run.id}`)} />
          )}
        </section>
      </div>
    </main>
  );
}

export default function FttxDesignerListPage() {
  return <ErrorBoundary><FttxDesignerListContent /></ErrorBoundary>;
}
