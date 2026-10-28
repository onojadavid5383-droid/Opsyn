// ============================================================
// OPSYN — FttxDesignerWizardPage
// End-to-end flow for one FTTx design run:
//   1. Name & Configuration
//   2. Upload Input Layers (road/homepass/pole required; building/pickup optional)
//   3. Review & Run
//   4. Progress (live poll)
//   5. Results (BOQ / optical summary / log)
//
// The active step is derived from the run's own `status` (not separate
// local wizard state) so refreshing the page or coming back to it later
// always resumes at the right place. Steps 1/2/3 remain revisitable
// while status is draft/layers_pending/ready (see the backend gate fix
// in router.py — upload/config edits are allowed through "ready" so a
// bad layer can be replaced without deleting the whole run).
// ============================================================

import { useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  fttxDesignerApi,
  readGeoJsonFile,
  downloadDedReport,
  FTTX_REQUIRED_LAYER_KEYS,
  FTTX_OPTIONAL_LAYER_KEYS,
  FTTX_TERMINAL_STATUSES,
  type FttxLayerKey,
  type FttxDesignRun,
  type FttxDesignRunLayer,
} from '../../api/fttx-designer.api';
import { ArrowLeft, Check, CircleAlert, CircleCheck, FileDown, FileText, MapPinned, Network, RotateCcw, Square } from 'lucide-react';
import { useUIStore } from '../../store/ui.store';
import { Button, Spinner, Input, Select, Badge } from '../../components/ui';
import { FttxConfigFields } from '../../components/fttx/FttxConfigFields';
import { settingsFromConfig, settingsToConfig } from '../../components/fttx/fttxSettings';
import { ErrorBoundary } from '../../components/ErrorBoundary';
import type { ApiError } from '../../api/client';
import s from './FttxDesignerWizardPage.module.css';

function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, message?: string) => addToast({ type: 'success', title, message }),
    error:   (title: string, message?: string) => addToast({ type: 'error',   title, message }),
    info:    (title: string, message?: string) => addToast({ type: 'info',    title, message }),
  };
}

type StepId = 1 | 2 | 3 | 4 | 5;

const LAYER_LABELS: Record<FttxLayerKey, string> = {
  road:     'Roads',
  homepass: 'Homepasses',
  pole:     'Poles',
  building: 'Buildings',
  pickup:   'Pickup Points',
};
const LAYER_HINTS: Record<FttxLayerKey, string> = {
  road:     'Line layer — the road network the design routes cable along.',
  homepass: 'Point layer — customer count in a numeric field (e.g. "Name").',
  pole:     'Point layer — aerial attachment structures.',
  building: 'Optional — used for route/crossing avoidance.',
  pickup:   'Optional — feeder pickup point locations; auto-generated if omitted.',
};


function stepForStatus(run: FttxDesignRun | undefined): StepId {
  if (!run) return 1;
  switch (run.status) {
    case 'draft':
      return Object.keys(run.config ?? {}).length === 0 ? 1 : 2;
    case 'layers_pending':
      return 2;
    case 'ready':
      return 3;
    case 'queued':
    case 'running':
    case 'cancelling':
      return 4;
    case 'completed':
    case 'failed':
    case 'cancelled':
      return 5;
    default:
      return 1;
  }
}

// ── Step indicator ───────────────────────────────────────────
function StepIndicator({ current, canEditSetup, onSelect }: {
  current: StepId;
  canEditSetup: boolean;
  onSelect: (step: StepId) => void;
}) {
  const steps: { id: StepId; label: string }[] = [
    { id: 1, label: 'Configuration' },
    { id: 2, label: 'Upload Layers' },
    { id: 3, label: 'Review & Run' },
    { id: 4, label: 'Progress' },
    { id: 5, label: 'Results' },
  ];
  return (
    <nav className={s.stepper} aria-label="Design run steps">
      <ol>
        {steps.map((item, index) => (
          <li key={item.id} className={item.id < current ? s.stepComplete : item.id === current ? s.stepCurrent : s.stepUpcoming}
            aria-current={item.id === current ? 'step' : undefined}>
            {canEditSetup && item.id <= 2 ? (
              <button type="button" className={s.stepButton} onClick={() => onSelect(item.id)} aria-label={`Go to ${item.label}`} aria-current={item.id === current ? 'step' : undefined}>
                <span className={s.stepNode}>{item.id < current ? <Check size={15} strokeWidth={2.5} /> : item.id}</span>
                <span className={s.stepLabel}>{item.label}</span>
              </button>
            ) : <>
              <span className={s.stepNode}>{item.id < current ? <Check size={15} strokeWidth={2.5} /> : item.id}</span>
              <span className={s.stepLabel}>{item.label}</span>
            </>}
            {index < steps.length - 1 && <span className={s.stepConnector} aria-hidden="true" />}
          </li>
        ))}
      </ol>
    </nav>
  );
}

// ── Step 1: Name & Configuration ─────────────────────────────
function StepConfig({ run, onSaved }: { run: FttxDesignRun; onSaved: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(run.name ?? '');
  // The settings form is shared with the map's Auto design drawer (components/fttx)
  const [settings, setSettings] = useState(() => settingsFromConfig(run.config));

  const saveMutation = useMutation({
    mutationFn: () => fttxDesignerApi.updateRunConfig(run.id, {
      name: name.trim() || null,
      config: settingsToConfig(settings, run.config),
    }),
    onSuccess: () => { toast.success('Configuration saved'); onSaved(); },
    onError: (e: ApiError) => toast.error('Could not save configuration', e?.detail),
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <Input label="Run Name" value={name} onChange={setName} placeholder="e.g. Kokona Estate — Phase 1" />
      <FttxConfigFields value={settings} onChange={setSettings}
        unavailableDeployments={['underground','drainage','hybrid']}
        deploymentNote="The web design engine currently supports aerial runs. Other modes are shown for planning but cannot run here yet." />
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
          {saveMutation.isPending ? <><Spinner size="xs" /> Saving…</> : 'Save & Continue'}
        </Button>
      </div>
    </div>
  );
}

// ── Step 2: Layer uploads ────────────────────────────────────
function LayerUploadCard({
  run, layerKey, uploaded, onUploaded,
}: {
  run: FttxDesignRun;
  layerKey: FttxLayerKey;
  uploaded?: FttxDesignRunLayer;
  onUploaded: () => void;
}) {
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(uploaded?.original_filename ?? null);

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const geojson = await readGeoJsonFile(file);
      return fttxDesignerApi.uploadLayer(run.id, layerKey, geojson, file.name);
    },
    onSuccess: (layer) => {
      toast.success(`${LAYER_LABELS[layerKey]} uploaded`, `${layer.feature_count ?? 0} feature(s)`);
      onUploaded();
    },
    onError: (e: ApiError | Error) => {
      toast.error(`Could not upload ${LAYER_LABELS[layerKey]}`, (e as ApiError)?.detail ?? e.message);
      setFileName(uploaded?.original_filename ?? null);
    },
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFileName(f.name);
    uploadMutation.mutate(f);
  };

  const isRequired = FTTX_REQUIRED_LAYER_KEYS.includes(layerKey);
  const inputId = `fttx-layer-upload-${layerKey}`;

  return (
    <div style={{
      border: `2px dashed ${uploaded ? 'var(--accent)' : 'var(--border)'}`,
      borderRadius: 10, padding: '16px 18px', background: 'var(--surface2)',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
          <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--chalk1)' }}>{LAYER_LABELS[layerKey]}</span>
          {isRequired ? (
            <Badge variant="danger" size="xs">Required</Badge>
          ) : (
            <Badge variant="default" size="xs">Optional</Badge>
          )}
        </div>
        <div style={{ fontSize: 11, color: 'var(--chalk3)', marginBottom: 4 }}>{LAYER_HINTS[layerKey]}</div>
        {fileName && (
          <div style={{ fontSize: 12, color: uploaded ? 'var(--accent)' : 'var(--chalk3)' }}>
            {fileName}{uploaded?.feature_count != null ? ` — ${uploaded.feature_count} feature(s)` : ''}
          </div>
        )}
      </div>
      <div>
        <input
          ref={fileRef} type="file" accept=".json,.geojson,application/geo+json,application/json"
          onChange={handleChange} style={{ display: 'none' }} id={inputId}
        />
        <Button
          variant={uploaded ? 'secondary' : 'primary'} size="sm"
          disabled={uploadMutation.isPending}
          onClick={() => fileRef.current?.click()}
        >
          {uploadMutation.isPending ? <><Spinner size="xs" /> Uploading…</> : uploaded ? 'Replace' : 'Choose File'}
        </Button>
      </div>
    </div>
  );
}

// Field on the homepass layer that holds the customer count — mirrors the
// engine's FTTXConfig.homepass_field_name (default "Name"). Offered as a
// dropdown of the uploaded layer's own property names (see LayerOut.
// property_keys in router.py) rather than free text, so the user can't
// typo a field name the layer doesn't actually have.
function HomepassFieldSelector({ run, homepassLayer }: { run: FttxDesignRun; homepassLayer: FttxDesignRunLayer }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const configuredValue = String(run.config.homepass_field_name ?? '') || null;
  const options = homepassLayer.property_keys ?? [];
  // Pre-fill with the engine's own default ("Name") when nothing has been
  // explicitly chosen yet and the layer actually has that field — matches
  // what a run would use if the user skipped this control entirely.
  const [selected, setSelected] = useState(
    configuredValue ?? (options.includes('Name') ? 'Name' : ''),
  );

  const saveMutation = useMutation({
    mutationFn: (value: string) => fttxDesignerApi.updateRunConfig(run.id, {
      config: { ...run.config, homepass_field_name: value },
    }),
    onSuccess: () => {
      toast.success('Homepass field saved');
      queryClient.invalidateQueries({ queryKey: ['fttx-designer', 'run', run.id] });
    },
    onError: (e: ApiError) => toast.error('Could not save homepass field', e?.detail),
  });

  const handleChange = (value: string) => {
    setSelected(value);
    if (value) saveMutation.mutate(value);
  };

  if (options.length === 0) {
    return (
      <div style={{
        fontSize: 12, color: 'var(--chalk3)', background: 'var(--surface2)',
        border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', marginTop: -4,
      }}>
        No attribute fields found on the uploaded homepass layer — each feature needs a
        numeric "properties" value for the customer count.
      </div>
    );
  }

  const value = selected && options.includes(selected) ? selected : '';

  return (
    <Select
      label="Homepass Field"
      value={value}
      onChange={handleChange}
      options={options.map(k => ({ label: k, value: k }))}
      placeholder="Select the field holding the customer count…"
      hint={
        saveMutation.isPending
          ? 'Saving…'
          : `Which property on the uploaded homepass layer holds the customer count${
              configuredValue ? ` (currently "${configuredValue}")` : ''
            }.`
      }
      required
    />
  );
}

function StepLayers({
  run, layers, onContinue,
}: {
  run: FttxDesignRun;
  layers: FttxDesignRunLayer[];
  onContinue: () => void;
}) {
  const byKey = useMemo(() => {
    const m = new Map<FttxLayerKey, FttxDesignRunLayer>();
    layers.forEach(l => m.set(l.layer_key, l));
    return m;
  }, [layers]);

  const queryClient = useQueryClient();
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['fttx-designer', 'run', run.id] });
    queryClient.invalidateQueries({ queryKey: ['fttx-designer', 'run', run.id, 'layers'] });
  };

  const allRequiredUploaded = FTTX_REQUIRED_LAYER_KEYS.every(k => byKey.has(k));
  const homepassLayer = byKey.get('homepass');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {[...FTTX_REQUIRED_LAYER_KEYS, ...FTTX_OPTIONAL_LAYER_KEYS].map(key => (
        <div key={key} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <LayerUploadCard run={run} layerKey={key} uploaded={byKey.get(key)} onUploaded={refresh} />
          {key === 'homepass' && homepassLayer && (
            <HomepassFieldSelector run={run} homepassLayer={homepassLayer} />
          )}
        </div>
      ))}
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
        <Button onClick={onContinue} disabled={!allRequiredUploaded}>
          {allRequiredUploaded ? 'Continue to Review' : 'Upload required layers to continue'}
        </Button>
      </div>
    </div>
  );
}

// ── Step 3: Review & Run ─────────────────────────────────────
function StepReview({
  run, layers, onQueued,
}: {
  run: FttxDesignRun;
  layers: FttxDesignRunLayer[];
  onQueued: () => void;
}) {
  const toast = useToast();

  const executeMutation = useMutation({
    mutationFn: () => fttxDesignerApi.executeRun(run.id),
    onSuccess: () => { toast.success('Design run started'); onQueued(); },
    onError: (e: ApiError) => toast.error('Could not start run', e?.detail),
  });

  const configRows: [string, unknown][] = [
    ['Deployment Type', run.config.deployment_type ?? 'aerial'],
    ['Cascade Architecture', run.config.cascade_architecture ?? 'pcc'],
    ['PON Architecture', run.config.pon_architecture ?? 'single_pon'],
    ['Box-to-box routing', run.config.b2b_routing_mode === 'pole_to_pole' ? 'Pole to pole' : 'Road network'],
    ['Documented cable exceptions', run.config.allow_documented_b2b_exceptions === true ? 'Enabled — requires engineering sign-off' : 'Disabled'],
    ['Coverage %', run.config.coverage_pct ?? 100],
    ['Homepass Field', run.config.homepass_field_name ?? 'Name (default)'],
    ['Optical Trace', run.config.optical_enabled === false ? 'Disabled' : 'Enabled'],
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--chalk2)', marginBottom: 8 }}>Configuration</div>
        {run.config.allow_documented_b2b_exceptions === true && <div style={{ marginBottom: 8, padding: '10px 12px', border: '1px solid var(--status-warning-fg)', borderRadius: 8, color: 'var(--text-primary)', fontSize: 12 }}>
          Over-limit box-to-box cables will be included as documented engineering exceptions and need sign-off.
        </div>}
        <div style={{ background: 'var(--surface2)', borderRadius: 8, padding: '4px 16px' }}>
          {configRows.map(([label, value]) => (
            <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
              <span style={{ fontSize: 12, color: 'var(--chalk3)' }}>{label}</span>
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--chalk1)' }}>{String(value)}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--chalk2)', marginBottom: 8 }}>Layers</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {layers.map(l => (
            <span key={l.id} style={{
              padding: '4px 10px', borderRadius: 6, background: 'var(--surface2)',
              border: '1px solid var(--border)', fontSize: 12, color: 'var(--chalk2)',
            }}>
              {LAYER_LABELS[l.layer_key]}: {l.feature_count ?? 0}
            </span>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button onClick={() => executeMutation.mutate()} disabled={executeMutation.isPending}>
          {executeMutation.isPending ? <><Spinner size="xs" /> Starting…</> : '▶ Run Design'}
        </Button>
      </div>
    </div>
  );
}

// ── Step 4: Progress ──────────────────────────────────────────
function StepProgress({ runId }: { runId: string }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [cancelRequested, setCancelRequested] = useState(false);
  const statusQuery = useQuery({
    queryKey: ['fttx-designer', 'run', runId, 'status'],
    queryFn:  () => fttxDesignerApi.getStatus(runId),
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s && FTTX_TERMINAL_STATUSES.includes(s) ? false : 2000;
    },
  });
  const cancelMutation = useMutation({
    mutationFn: () => fttxDesignerApi.cancelRun(runId),
    onSuccess: run => {
      setCancelRequested(true);
      void queryClient.invalidateQueries({ queryKey: ['fttx-designer', 'run', runId] });
      void queryClient.invalidateQueries({ queryKey: ['fttx-designer', 'run', runId, 'status'] });
      toast.info(run.status === 'cancelled' ? 'Design cancelled' : 'Cancellation requested',
        run.status === 'cancelled' ? 'The queued design was stopped.' : 'The engine will stop at its next safe checkpoint.');
    },
    onError: (e: ApiError) => toast.error('Could not cancel design', e?.detail),
  });

  const s = statusQuery.data;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16, padding: '20px 0' }}>
      <Spinner size="lg" />
      <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--chalk1)' }}>
        {statusQuery.isError ? 'Progress unavailable; reconnecting to the design worker…' : s?.progress_message || 'Running network design…'}
      </div>
      <div style={{ width: '100%', maxWidth: 420, background: 'var(--surface2)', borderRadius: 999, height: 10, overflow: 'hidden' }}>
        <div style={{
          width: `${s?.progress_pct ?? 0}%`, height: '100%',
          background: 'var(--accent)', transition: 'width 0.3s ease',
        }} />
      </div>
      <div style={{ fontSize: 12, color: 'var(--chalk3)' }}>{s?.progress_pct ?? 0}%</div>
      <Button variant="secondary" leftIcon={<Square size={15} />} onClick={() => cancelMutation.mutate()}
        disabled={cancelMutation.isPending || cancelRequested || s?.status === 'cancelling' || s?.status === 'cancelled'}>
        {cancelMutation.isPending ? 'Requesting cancellation…' : cancelRequested || s?.status === 'cancelling' ? 'Cancellation in progress' : 'Cancel design'}
      </Button>
    </div>
  );
}

// ── Step 5: Results ───────────────────────────────────────────
function StepResults({ run, navigate }: { run: FttxDesignRun; navigate: (path: string) => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const rerunMutation = useMutation({
    mutationFn: (configOverrides: Record<string, unknown>) => fttxDesignerApi.rerunFailedRun(run.id, configOverrides),
    onSuccess: (rerun) => {
      queryClient.invalidateQueries({ queryKey: ['fttx-designer', 'runs'] });
      toast.success('Rerun started', rerun.config.allow_documented_b2b_exceptions === true
        ? 'Saved layers reused. Over-limit cables will be listed and costed for engineering sign-off.'
        : 'Your saved configuration and uploaded layers were reused.');
      navigate(`/fttx-designer/${rerun.id}`);
    },
    onError: (e: ApiError) => toast.error('Could not rerun design', e?.detail),
  });

  const resultsQuery = useQuery({
    queryKey: ['fttx-designer', 'run', run.id, 'results'],
    queryFn:  () => fttxDesignerApi.getResults(run.id),
    enabled:  run.status === 'completed',
  });

  const logMutation = useMutation({
    mutationFn: () => fttxDesignerApi.getLog(run.id),
    onSuccess: (data) => {
      if (!data.log_text) { toast.info('No log available'); return; }
      const blob = new Blob([data.log_text], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `fttx_run_${run.id.slice(0, 8)}.log`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      // Let the browser start consuming the Blob before releasing its URL.
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
    onError: (e: ApiError) => toast.error('Could not fetch log', e?.detail),
  });

  const dedReportMutation = useMutation({
    mutationFn: () => fttxDesignerApi.generateDedReport(run.id),
    onSuccess: (report) => {
      downloadDedReport(report);
      toast.success('DED report generated', `${report.filename} + ${report.warnings_filename}`);
    },
    onError: (e: ApiError) => toast.error('Could not generate DED report', e?.detail),
  });

  const summary = (run.result_summary ?? {}) as Record<string, any>;
  const optical = summary.optical as Record<string, any> | undefined;
  const hasB2bLengthFailure = run.error_message?.includes('[CABLE_LENGTH_EXCEEDED]') ?? false;

  if (run.status === 'failed') {
    return (
      <div className={s.outcome}>
        <div className={s.failureBanner}>
          <CircleAlert size={21} />
          <div><h2>Design run failed</h2><p>{run.error_message || 'An unexpected error occurred while processing this design.'}</p></div>
        </div>
        <div className={s.outcomeActions}>
          <Button variant="primary" leftIcon={<RotateCcw size={16} />} onClick={() => rerunMutation.mutate({})} loading={rerunMutation.isPending}>
            Rerun design
          </Button>
          {hasB2bLengthFailure && (
            <Button variant="secondary" leftIcon={<RotateCcw size={16} />} onClick={() => rerunMutation.mutate({ allow_documented_b2b_exceptions: true })} loading={rerunMutation.isPending}>
              Rerun with documented exceptions
            </Button>
          )}
          <Button variant="secondary" leftIcon={<FileDown size={16} />} onClick={() => logMutation.mutate()} disabled={logMutation.isPending}>
            {logMutation.isPending ? 'Fetching log…' : 'Download log'}
          </Button>
          <Button variant="ghost" leftIcon={<ArrowLeft size={16} />} onClick={() => navigate('/fttx-designer')}>Back to runs</Button>
        </div>
        {hasB2bLengthFailure && <p style={{ margin: '-6px 0 0', color: 'var(--chalk3)', fontSize: 12, textAlign: 'right' }}>
          This opt-in completes the design with over-limit cables flagged and costed for engineering sign-off.
        </p>}
      </div>
    );
  }

  if (run.status === 'cancelled') {
    return (
      <div className={s.cancelledState}>
        <div className={s.cancelledMark}><Network size={23} /></div>
        <h2>This run was cancelled</h2>
        <p>No design outputs were generated for this run.</p>
        <Button variant="secondary" leftIcon={<ArrowLeft size={16} />} onClick={() => navigate('/fttx-designer')}>Back to runs</Button>
      </div>
    );
  }

  const opticalPass = Number(optical?.passed_customers ?? 0);
  const opticalMarginal = Number(optical?.marginal_customers ?? 0);
  const opticalFail = Number(optical?.failed_customers ?? 0);
  const opticalInvalid = Number(optical?.invalid_customers ?? 0);
  const opticalTotal = opticalPass + opticalMarginal + opticalFail + opticalInvalid;
  const boqCount = resultsQuery.data?.boq_rows?.length;

  return (
    <div className={s.results}>
      <div className={s.successBanner} role="status">
        <span className={s.successIcon}><CircleCheck size={20} /></span>
        <span><strong>Design completed successfully</strong><small>Network outputs and quantities are ready to review.</small></span>
        <Badge className={s.successBadge} variant="resolved" dot>Completed</Badge>
      </div>

      <section className={s.inventory} aria-labelledby="inventory-title">
        <div className={s.sectionHeading}><div><h2 id="inventory-title">Network inventory</h2><p>Assets generated from this design</p></div></div>
        <dl className={s.metrics}>
        {[
          ['Homepasses', summary.homepass_count],
          ['FATs', summary.fat_count],
          ['FDTs', summary.fdt_count],
          ['Closures', summary.closure_count],
          ['Box-to-Box Cables', summary.b2b_cable_count],
          ['Drop Cables', summary.b2c_cable_count],
        ].map(([label, value]) => (
          <div key={label as string} className={s.metric}><dt>{label}</dt><dd>{value ?? '—'}</dd></div>
        ))}
        </dl>
      </section>

      {optical && (
        <section className={s.optical} aria-labelledby="optical-title">
          <div className={s.sectionHeading}><div><h2 id="optical-title">Optical power budget</h2><p>Customer link status against the configured power budget</p></div>
            <span className={s.opticalTotal}>{opticalTotal.toLocaleString()} evaluated</span>
          </div>
          <div className={s.budgetBar} aria-label={`${opticalPass} pass, ${opticalMarginal} marginal, ${opticalFail} fail${opticalInvalid ? `, ${opticalInvalid} invalid` : ''}`}>
            {opticalTotal > 0 && <>
              {opticalPass > 0 && <span className={s.budgetPass} style={{ width: `${opticalPass / opticalTotal * 100}%` }} />}
              {opticalMarginal > 0 && <span className={s.budgetMarginal} style={{ width: `${opticalMarginal / opticalTotal * 100}%` }} />}
              {opticalFail > 0 && <span className={s.budgetFail} style={{ width: `${opticalFail / opticalTotal * 100}%` }} />}
              {opticalInvalid > 0 && <span className={s.budgetInvalid} style={{ width: `${opticalInvalid / opticalTotal * 100}%` }} />}
            </>}
          </div>
          <div className={s.budgetLegend}>
            <Badge variant="resolved" dot>{opticalPass.toLocaleString()} pass</Badge>
            <Badge variant="warning" dot>{opticalMarginal.toLocaleString()} marginal</Badge>
            <Badge variant="critical" dot>{opticalFail.toLocaleString()} fail</Badge>
            {opticalInvalid > 0 && <Badge variant="default" dot>{opticalInvalid.toLocaleString()} invalid</Badge>}
          </div>
        </section>
      )}

      <div className={s.quantityNote}>
        <FileText size={16} />
        {resultsQuery.isLoading ? 'Loading bill of quantities…' : resultsQuery.isError ? 'Bill of quantities could not be loaded.' : `${boqCount ?? 0} bill of quantities line items generated.`}
      </div>

      <div className={s.resultActions}>
        <div className={s.primaryAction}>
          <Button variant="primary" leftIcon={<MapPinned size={16} />} onClick={() => navigate(`/network?fttxRun=${encodeURIComponent(run.id)}`)}>
            View design on map
          </Button>
          <Button variant="secondary" leftIcon={<FileText size={16} />} onClick={() => dedReportMutation.mutate()} disabled={dedReportMutation.isPending}>
            {dedReportMutation.isPending ? <><Spinner size="xs" /> Generating report…</> : 'Generate DED report'}
          </Button>
        </div>
        <div className={s.secondaryActions}>
          <Button variant="ghost" leftIcon={<FileDown size={16} />} onClick={() => logMutation.mutate()} disabled={logMutation.isPending}>
            {logMutation.isPending ? 'Fetching log…' : 'Download log'}
          </Button>
          <Button variant="ghost" leftIcon={<ArrowLeft size={16} />} onClick={() => navigate('/fttx-designer')}>Back to runs</Button>
        </div>
      </div>
    </div>
  );
}

// ── Page shell ─────────────────────────────────────────────────
function FttxDesignerWizardContent() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [stepSelection, setStepSelection] = useState<{ runId: string; step: StepId } | null>(null);

  const runQuery = useQuery({
    queryKey: ['fttx-designer', 'run', runId],
    queryFn:  () => fttxDesignerApi.getRun(runId!),
    enabled:  !!runId,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === 'queued' || s === 'running' || s === 'cancelling' ? 4000 : false;
    },
  });

  const layersQuery = useQuery({
    queryKey: ['fttx-designer', 'run', runId, 'layers'],
    queryFn:  () => fttxDesignerApi.listLayers(runId!),
    enabled:  !!runId,
  });

  const queryClient = useQueryClient();
  const refreshRun = () => queryClient.invalidateQueries({ queryKey: ['fttx-designer', 'run', runId] });

  if (!runId) return <div className={s.statePage}>No run selected.</div>;
  if (runQuery.isLoading) return <div className={s.statePage}><Spinner size="md" /></div>;
  if (runQuery.isError || !runQuery.data) {
    return (
      <div className={s.statePage}>
        <div className={s.failureBanner}><CircleAlert size={20} /><div><h2>Design run not found</h2><p>It may have been removed or you may not have access to it.</p></div></div>
        <Button variant="secondary" leftIcon={<ArrowLeft size={16} />} onClick={() => navigate('/fttx-designer')}>Back to runs</Button>
      </div>
    );
  }

  const run = runQuery.data;
  const step = stepSelection?.runId === run.id ? stepSelection.step : stepForStatus(run);
  const canEditSetup = run.status === 'draft' || run.status === 'layers_pending' || run.status === 'ready';
  const statusVariant = run.status === 'completed' ? 'resolved' as const
    : run.status === 'failed' ? 'critical' as const
    : run.status === 'running' || run.status === 'queued' || run.status === 'cancelling' ? 'warning' as const
    : run.status === 'cancelled' ? 'default' as const : 'info' as const;

  return (
    <main className={s.page}>
      <div className={s.inner}>
        <header className={s.header}>
          <Button variant="ghost" size="sm" leftIcon={<ArrowLeft size={16} />} onClick={() => navigate('/fttx-designer')}>FTTx Designer</Button>
          <span className={s.headerDivider} aria-hidden="true">/</span>
          <div className={s.headerTitle}>
            <span className={s.eyebrow}>Design run</span>
            <h1>{run.name || `Design Run ${run.id.slice(0, 8)}`}</h1>
          </div>
          <Badge className={s.headerBadge} variant={statusVariant} dot>{run.status.replaceAll('_', ' ')}</Badge>
        </header>
        <StepIndicator current={step} canEditSetup={canEditSetup} onSelect={selected => setStepSelection({ runId: run.id, step: selected })} />
        <section className={s.stepPanel} aria-label={`${step === 5 ? 'Results' : step === 4 ? 'Design progress' : 'Design setup'} step`}>
          <div className={s.panelHead}>
            <div className={s.panelIcon}><Network size={18} /></div>
            <div><h2>{run.status === 'failed' ? 'Design run failed' : run.status === 'cancelled' ? 'Design run cancelled' : run.status === 'cancelling' ? 'Stopping design run' : step === 5 ? 'Design results' : step === 4 ? 'Design in progress' : 'Design setup'}</h2>
              <p>{run.status === 'failed' ? 'Review the error and download the run log for troubleshooting.' : run.status === 'cancelled' ? 'This run was stopped before outputs were generated.' : run.status === 'cancelling' ? 'Cancellation was requested. The worker is stopping at its next safe checkpoint.' : step === 5 ? 'Review generated network assets and deliverables.' : step === 4 ? 'The designer is processing your network layers.' : 'Configure the run and prepare the source layers.'}</p>
            </div>
          </div>
          {step === 1 && <StepConfig run={run} onSaved={() => { setStepSelection(null); refreshRun(); }} />}
          {step === 2 && <StepLayers run={run} layers={layersQuery.data ?? []} onContinue={() => { setStepSelection({ runId: run.id, step: 3 }); refreshRun(); }} />}
          {step === 3 && <StepReview run={run} layers={layersQuery.data ?? []} onQueued={() => { setStepSelection(null); refreshRun(); }} />}
          {step === 4 && <StepProgress runId={run.id} />}
          {step === 5 && <StepResults run={run} navigate={navigate} />}
        </section>
      </div>
    </main>
  );
}

export default function FttxDesignerWizardPage() {
  return (
    <ErrorBoundary>
      <FttxDesignerWizardContent />
    </ErrorBoundary>
  );
}
