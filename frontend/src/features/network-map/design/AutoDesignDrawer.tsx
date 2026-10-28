// ============================================================
// OPSYN DESIGN — Auto design drawer (Network GIS Phase 5, Track A).
// Settings (the FTTx Designer's own form, shared), a check of what the
// engine will get, then Run: POST /designs/{id}/generate queues the engine;
// progress is polled (designQueries.useGenerateStatus) and, when the run
// finishes, the new version is shown and the map fits the design
// (DesignWorkspace). A design that already has content asks first: its
// current state is kept as its own version. Also: import a completed run
// from the standalone FTTx Designer.
// ============================================================

import { useEffect, useRef, useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { CheckCircle2, CircleAlert, Download, Square, X } from 'lucide-react';
import type { Design, DesignGenerateStatus, DesignSummary } from '@shared';
import { FttxConfigFields } from '../../../components/fttx/FttxConfigFields';
import { settingsFromConfig, settingsToConfig } from '../../../components/fttx/fttxSettings';
import { designError, isEditable } from './designFormat';
import { RUN_ACTIVE, useCancelGenerate, useGenerate, useImportRun, useImportableRuns } from './designQueries';
import d from './Design.module.css';

// Only aerial has a deployment strategy in the web engine so far (the server refuses the rest)
const UNAVAILABLE = ['underground', 'drainage', 'hybrid'];

const COUNT_LABEL: Record<string, [string, string]> = {
  FDT: ['FDT', 'FDTs'], FAT: ['FAT', 'FATs'], SPLITTER: ['splitter', 'splitters'], CLOSURE: ['closure', 'closures'],
  POLE: ['pole', 'poles'], BOX_TO_BOX: ['box-to-box cable', 'box-to-box cables'], DROP: ['drop', 'drops'],
  CLOSURE_FDT: ['closure cable', 'closure cables'], FEEDER: ['feeder', 'feeders'],
};
const counted = (key: string, n: number) =>
  `${n.toLocaleString('en-GB')} ${COUNT_LABEL[key]?.[n === 1 ? 0 : 1] ?? key.toLowerCase()}`;

function ago(iso: string | null): string {
  if (!iso) return '';
  try { return formatDistanceToNow(new Date(iso), { addSuffix: true }); } catch { return iso; }
}

function RunProgress({ status, onCancel, cancelling }: { status: DesignGenerateStatus; onCancel: () => void; cancelling: boolean }) {
  if (RUN_ACTIVE.includes(status.status)) {
    return (
      <section className={d.runBox} aria-live="polite" aria-label="Auto design progress">
        <p className={d.runHead}>{status.status === 'queued' ? 'Waiting for the engine…' : status.status === 'cancelling' ? 'Stopping design…' : 'Designing…'}</p>
        <div className={d.runBar} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={status.progress_pct}>
          <span style={{ width: `${Math.max(3, status.progress_pct)}%` }} />
        </div>
        <p className={d.runMsg}>{status.progress_pct}% · {status.progress_message || 'Starting'}</p>
        <button type="button" className={d.ghostBtn} onClick={onCancel} disabled={cancelling || status.progress_message?.startsWith('Cancellation requested')}>
          <Square size={13} aria-hidden />{cancelling || status.progress_message?.startsWith('Cancellation requested') ? 'Cancellation requested' : 'Cancel design'}
        </button>
      </section>
    );
  }
  if (status.status === 'failed') {
    return (
      <section className={d.runBox} data-tone="bad" role="alert">
        <p className={d.runHead}><CircleAlert size={16} aria-hidden />The auto design did not finish</p>
        <p className={d.runMsg}>{status.error_message ?? 'The engine stopped without saying why.'}</p>
        <p className={d.runMsg}>Nothing in the design was changed.</p>
      </section>
    );
  }
  if (status.status === 'completed') {
    const applied = status.result_summary?.design;
    return (
      <section className={d.runBox} data-tone="ok" aria-label="Last auto design">
        <p className={d.runHead}>
          <CheckCircle2 size={16} aria-hidden />
          {status.design_version ? `Version ${status.design_version.version_no} designed` : 'Designed'} {ago(status.completed_at)}
        </p>
        {applied && (
          <p className={d.runMsg}>
            {Object.entries(applied.counts).map(([k, n]) => counted(k, n)).join(' · ')}
          </p>
        )}
        {applied && (
          <p className={d.runMsg}>
            Checked: {applied.validation.errors} {applied.validation.errors === 1 ? 'error' : 'errors'}, {applied.validation.warnings} {applied.validation.warnings === 1 ? 'warning' : 'warnings'}.
          </p>
        )}
        {applied?.warnings?.length ? (
          <ul className={d.runNotes}>{applied.warnings.slice(0, 4).map(w => <li key={w}>{w}</li>)}</ul>
        ) : null}
      </section>
    );
  }
  if (status.status === 'cancelled') {
    return (
      <section className={d.runBox} aria-label="Auto design cancelled">
        <p className={d.runHead}>Auto design cancelled</p>
        <p className={d.runMsg}>The engine stopped before applying new outputs to this design.</p>
      </section>
    );
  }
  return null;
}

interface Props {
  design:   Design;
  summary:  DesignSummary | undefined;
  status:   DesignGenerateStatus | null | undefined;
  onClose:  () => void;
  onIssues: () => void;
}

export function AutoDesignDrawer({ design, summary, status, onClose, onIssues }: Props) {
  const [settings, setSettings] = useState(() => settingsFromConfig(design.engine_config));
  const [confirming, setConfirming] = useState<null | { kind: 'run' | 'exception' } | { kind: 'import'; runId: string; name: string }>(null);
  const [showImport, setShowImport] = useState(false);
  const generate = useGenerate(design.id);
  const cancel = useCancelGenerate(design.id);
  const importRun = useImportRun(design.id, design.project_id);
  const runs = useImportableRuns(design.id, showImport);
  // The run's progress and result sit at the top: bring them into view when a run starts or ends
  const body = useRef<HTMLDivElement>(null);
  const runKey = status ? `${status.run_id}:${status.status}` : '';
  useEffect(() => { body.current?.scrollTo?.({ top: 0, behavior: 'smooth' }); }, [runKey]);

  const editable = isEditable(design.status);
  const running = !!status && RUN_ACTIVE.includes(status.status);
  const hasB2bLengthFailure = status?.status === 'failed'
    && (status.error_message?.includes('[CABLE_LENGTH_EXCEEDED]') ?? false);
  const roads = design.input_counts.road ?? 0;
  const homepasses = design.input_counts.homepass ?? 0;
  const hasContent = !!summary && (summary.fdt + summary.fat + summary.poles + summary.closures > 0 || summary.cable_km > 0);
  const version = design.current_version?.version_no ?? 1;
  const blocked = !editable ? `This design is ${design.status.toLowerCase().replace('_', ' ')}; it can't be redesigned.`
    : !roads ? 'Upload the roads first: every cable is routed along them.'
    : !homepasses ? 'Upload the homepasses to design for.'
    : null;

  const run = (replace: boolean, allowB2bExceptions = false) => {
    setConfirming(null);
    const engineConfig = settingsToConfig(settings, design.engine_config);
    if (allowB2bExceptions) engineConfig.allow_documented_b2b_exceptions = true;
    generate.mutate({ engine_config: engineConfig, replace });
  };
  const rerunWithB2bExceptions = () => {
    if (hasContent) setConfirming({ kind: 'exception' });
    else run(false, true);
  };
  const doImport = (runId: string, replace: boolean) => {
    setConfirming(null);
    importRun.mutate({ runId, replace });
  };

  return (
    <aside className={d.drawer} aria-label="Auto design">
      <header className={d.drawerHead}>
        <div>
          <h2 className={d.drawerTitle}>Auto design</h2>
          <p className={d.drawerSub}>The FTTx engine places FDTs, FATs and closures and routes every cable along the roads.</p>
        </div>
        <button type="button" className={d.closeBtn} onClick={onClose} aria-label="Close auto design"><X size={18} aria-hidden /></button>
      </header>
      <div className={d.drawerBody} ref={body}>
        {status && <RunProgress status={status} onCancel={() => cancel.mutate()} cancelling={cancel.isPending || cancel.isSuccess} />}
        {hasB2bLengthFailure && (
          <button type="button" className={d.ghostBtn}
            disabled={!!blocked || running || generate.isPending}
            onClick={rerunWithB2bExceptions}>
            Complete design with documented B2B exceptions
          </button>
        )}
        {cancel.isError && <p className={d.err} role="alert">{designError(cancel.error, 'The auto design could not be cancelled.')}</p>}
        {status?.status === 'completed' && status.result_summary?.design && (
          <button type="button" className={d.ghostBtn} onClick={onIssues} style={{ alignSelf: 'flex-start' }}>See the issues</button>
        )}
        {generate.data?.notes?.length ? (
          <ul className={d.runNotes} aria-label="What the engine was given">{generate.data.notes.map(n => <li key={n}>{n}</li>)}</ul>
        ) : null}

        <section className={d.boqGroup} aria-labelledby="ad-input">
          <h3 id="ad-input">What the engine gets</h3>
          <ul className={d.checkList}>
            <li data-ok={roads > 0}>{roads.toLocaleString('en-GB')} road segments</li>
            <li data-ok={homepasses > 0}>{homepasses.toLocaleString('en-GB')} homepasses{summary ? `, ${summary.customers.toLocaleString('en-GB')} customers` : ''}</li>
            <li data-ok={!!design.boundary}>
              {design.boundary ? 'Inside the boundary only' : 'No boundary: every homepass is designed for'}
            </li>
            <li data-ok>{(design.input_counts.pole ?? 0) + (design.input_counts.existing_structure ?? 0)} poles and structures, plus poles already in the network nearby</li>
          </ul>
        </section>

        <section className={d.boqGroup} aria-labelledby="ad-settings">
          <h3 id="ad-settings">Settings</h3>
          <div className={d.settings}>
            <FttxConfigFields value={settings} onChange={setSettings} showProject={false}
              unavailableDeployments={UNAVAILABLE} deploymentNote="Only aerial can be designed automatically so far." />
          </div>
        </section>

        {blocked && <p className={d.err} role="status">{blocked}</p>}
        {confirming?.kind === 'run' || confirming?.kind === 'exception' ? (
          <div className={d.choice} role="alertdialog" aria-label={confirming.kind === 'exception' ? 'Replace the current design with B2B exceptions?' : 'Replace the current design?'} style={{ margin: 0 }}>
            <p>
              This replaces the design's {summary?.fdt ?? 0} FDTs, {summary?.fat ?? 0} FATs and {summary?.cable_km ?? 0} km of cable.
              They are kept as version {version}, so nothing is lost.
              {confirming.kind === 'exception' && ' Over-limit B2B cables will be flagged and costed for engineering sign-off.'}
            </p>
            <div className={d.choiceBtns}>
              <button type="button" className={d.solidBtn}
                onClick={() => run(true, confirming.kind === 'exception')}>
                {confirming.kind === 'exception' ? 'Replace and complete with exceptions' : 'Replace and design'}
              </button>
              <button type="button" className={d.ghostBtn} onClick={() => setConfirming(null)}>Keep the current design</button>
            </div>
          </div>
        ) : (
          <button type="button" className={d.solidBtn} style={{ alignSelf: 'flex-start' }}
            disabled={!!blocked || running || generate.isPending}
            onClick={() => (hasContent ? setConfirming({ kind: 'run' }) : run(false))}>
            {generate.isPending ? 'Starting…' : running ? 'Designing…' : hasContent ? 'Redesign automatically' : 'Design automatically'}
          </button>
        )}
        {generate.isError && <p className={d.err} role="alert">{designError(generate.error, 'The auto design could not start.')}</p>}

        <section className={d.boqGroup} aria-labelledby="ad-import">
          <h3 id="ad-import">From the FTTx Designer</h3>
          {!showImport ? (
            <button type="button" className={d.miniBtn} onClick={() => setShowImport(true)} disabled={!editable || running}>
              <Download size={13} aria-hidden />Import an existing run
            </button>
          ) : (
            <>
              <p className={d.blockNote}>A completed run's result becomes a new version of this design. Inputs the design lacks are copied from the run, and its settings become the design's.</p>
              {runs.isLoading && <div className={d.skel} />}
              {runs.isError && <p className={d.err}>{designError(runs.error, "Couldn't list the runs.")}</p>}
              {runs.data?.length === 0 && <p className={d.blockNote}>No completed runs yet.</p>}
              <ul className={d.runList}>
                {runs.data?.map(r => (
                  <li key={r.id}>
                    <div>
                      <p className={d.runName}>{r.name || 'Unnamed run'}</p>
                      <p className={d.runMsg}>
                        {[r.fdt_count != null && `${r.fdt_count} FDTs`, r.fat_count != null && `${r.fat_count} FATs`,
                          r.homepass_count != null && `${r.homepass_count} homepasses`, ago(r.completed_at)].filter(Boolean).join(' · ')}
                      </p>
                    </div>
                    <button type="button" className={d.miniBtn} disabled={importRun.isPending}
                      onClick={() => (hasContent ? setConfirming({ kind: 'import', runId: r.id, name: r.name || 'this run' }) : doImport(r.id, false))}>
                      Import
                    </button>
                  </li>
                ))}
              </ul>
              {confirming?.kind === 'import' && (
                <div className={d.choice} role="alertdialog" aria-label="Replace with the imported run?" style={{ margin: 0 }}>
                  <p>Replace the current design with {confirming.name}? It is kept as version {version}.</p>
                  <div className={d.choiceBtns}>
                    <button type="button" className={d.solidBtn} onClick={() => doImport(confirming.runId, true)}>Replace and import</button>
                    <button type="button" className={d.ghostBtn} onClick={() => setConfirming(null)}>Cancel</button>
                  </div>
                </div>
              )}
              {importRun.isPending && <p className={d.runMsg} role="status">Importing…</p>}
              {importRun.isSuccess && (
                <p className={d.runMsg} role="status">
                  Imported as version {importRun.data.version_no}
                  {importRun.data.inputs_copied.length ? `; copied its ${importRun.data.inputs_copied.join(', ')} inputs` : ''}.
                </p>
              )}
              {importRun.isError && <p className={d.err} role="alert">{designError(importRun.error, 'The run could not be imported.')}</p>}
            </>
          )}
        </section>
      </div>
    </aside>
  );
}
