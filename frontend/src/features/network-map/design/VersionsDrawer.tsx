// ============================================================
// OPSYN DESIGN — versions and history (Network GIS Phase 8).
//   Versions  save the current state under a name; every version with
//             how it came about, who, when and what it held; View (read-
//             only on the map), Compare with the current one, Restore
//             (the current state is kept as its own version first)
//   History   the design's audit trail, or one asset / cable's
// Nothing here deletes anything: "no design state is ever lost".
// ============================================================

import { useState, type FormEvent } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { Eye, GitCompareArrows, History as HistoryIcon, RotateCcw, X } from 'lucide-react';
import type { Design, DesignVersionInfo } from '@shared';
import { designError, formatKm, isEditable } from './designFormat';
import { useDesignHistory, useEntityHistory, useRestore, useSaveVersion, useVersions } from './designQueries';
import { useDesignMapStore } from './designStore';
import { HistoryList } from './HistoryList';
import d from './Design.module.css';

const METHOD: Record<DesignVersionInfo['creation_method'], string> = {
  INITIAL: 'Created', AUTO: 'Auto design', MANUAL: 'Edited', IMPORTED: 'Imported run', RESTORED: 'Restored',
};

function ago(iso: string): string {
  try { return formatDistanceToNow(new Date(iso), { addSuffix: true }); } catch { return iso; }
}

function held(v: DesignVersionInfo): string {
  const c = v.counts;
  if (!c) return 'Not kept';
  const parts = [c.FDT && `${c.FDT} FDT`, c.FAT && `${c.FAT} FAT`, c.cable_m ? formatKm(c.cable_m / 1000) : null,
    `${c.inputs ?? 0} inputs`].filter(Boolean);
  return parts.join(' · ');
}

export function VersionsDrawer({ design, onClose }: { design: Design; onClose: () => void }) {
  const [tab, setTab] = useState<'versions' | 'history'>('versions');
  const { view, setView, historyOf, setHistoryOf } = useDesignMapStore();
  const versions = useVersions(design.id);
  const save = useSaveVersion(design.id);
  const restore = useRestore(design.id, design.project_id);
  const [label, setLabel] = useState('');
  const [confirm, setConfirm] = useState<number | null>(null);
  // A request to see one asset's history opens straight on that tab
  const shownTab = historyOf ? 'history' : tab;
  const designTrail = useDesignHistory(design.id, shownTab === 'history' && !historyOf);
  const entityTrail = useEntityHistory(shownTab === 'history' ? historyOf?.id ?? null : null);
  const editable = isEditable(design.status);
  const current = versions.data?.find(v => v.is_current);

  const onSave = (e: FormEvent) => {
    e.preventDefault();
    if (label.trim()) save.mutate(label.trim(), { onSuccess: () => setLabel('') });
  };
  const doRestore = (no: number) => restore.mutate(no, {
    onSuccess: () => { setConfirm(null); setView(null); },
  });
  return (
    <aside className={d.drawer} aria-label="Versions and history">
      <header className={d.drawerHead}>
        <div>
          <h2 className={d.drawerTitle}>Versions</h2>
          <p className={d.drawerSub}>Every state of this design is kept. Restoring keeps the one it replaces.</p>
        </div>
        <button type="button" className={d.closeBtn} onClick={onClose} aria-label="Close versions"><X size={18} aria-hidden /></button>
      </header>
      <div className={d.tabs} role="tablist" aria-label="Versions or history">
        <button type="button" role="tab" aria-selected={shownTab === 'versions'} className={d.tab}
          onClick={() => { setHistoryOf(null); setTab('versions'); }}>Versions</button>
        <button type="button" role="tab" aria-selected={shownTab === 'history'} className={d.tab}
          onClick={() => setTab('history')}><HistoryIcon size={14} aria-hidden />History</button>
      </div>

      <div className={d.drawerBody} role="tabpanel">
        {shownTab === 'versions' && (<>
          {editable && (
            <form className={d.saveVersion} onSubmit={onSave}>
              <label htmlFor="vd-label">Save the current state as a version</label>
              <div className={d.newDesignRow}>
                <input id="vd-label" value={label} onChange={e => setLabel(e.target.value)} maxLength={200}
                  placeholder="e.g. Before splitting FDT-0002" />
                <button type="submit" className={d.solidBtn} disabled={!label.trim() || save.isPending}>
                  {save.isPending ? 'Saving…' : 'Save'}
                </button>
              </div>
              {save.isError && <p className={d.err} role="alert">{designError(save.error, 'The version could not be saved.')}</p>}
              {save.isSuccess && <p className={d.toolOk} role="status">Saved as version {save.data.saved.version_no}.</p>}
            </form>
          )}
          {versions.isLoading && <div className={d.skel} />}
          {versions.isError && <p className={d.err} role="alert">{designError(versions.error, "Couldn't load the versions.")}</p>}
          <ol className={d.versionList}>
            {versions.data?.map(v => {
              const viewing = (view?.mode === 'version' && view.no === v.version_no)
                || (view?.mode === 'compare' && view.from === v.version_no);
              return (
                <li key={v.id} className={d.versionItem} data-current={v.is_current} aria-current={viewing || undefined}>
                  <div className={d.versionHead}>
                    <p className={d.versionNo}>
                      Version {v.version_no}
                      {v.is_current && <span className={d.currentTag}>Current</span>}
                    </p>
                    <span className={d.methodTag}>{METHOD[v.creation_method]}</span>
                  </div>
                  {v.label && <p className={d.versionLabel}>{v.label}</p>}
                  <p className={d.runMsg}>{held(v)}{v.validation?.errors != null ? ` · ${v.validation.errors} errors` : ''}</p>
                  <p className={d.historyMeta}>{v.created_by ?? 'System'} · {ago(v.created_at)}</p>
                  {!v.is_current && (
                    v.frozen ? (
                      <div className={d.choiceBtns}>
                        <button type="button" className={d.miniBtn} aria-pressed={view?.mode === 'version' && view.no === v.version_no}
                          onClick={() => setView({ mode: 'version', no: v.version_no })}>
                          <Eye size={13} aria-hidden />View
                        </button>
                        {current && (
                          <button type="button" className={d.miniBtn}
                            aria-pressed={view?.mode === 'compare' && view.from === v.version_no}
                            onClick={() => setView({ mode: 'compare', from: v.version_no, to: current.version_no })}>
                            <GitCompareArrows size={13} aria-hidden />Compare with current
                          </button>
                        )}
                        {editable && (
                          <button type="button" className={d.miniBtn} onClick={() => setConfirm(v.version_no)}>
                            <RotateCcw size={13} aria-hidden />Restore
                          </button>
                        )}
                      </div>
                    ) : <p className={d.blockNote}>Its state wasn't kept (from before versions were frozen).</p>
                  )}
                  {confirm === v.version_no && (
                    <div className={d.choice} role="alertdialog" aria-label={`Restore version ${v.version_no}?`} style={{ margin: 'var(--space-2) 0 0' }}>
                      <p>
                        Bring back version {v.version_no}: its devices, cables, inputs and boundary. The current state is
                        kept as version {current?.version_no}.
                      </p>
                      <div className={d.choiceBtns}>
                        <button type="button" className={d.solidBtn} onClick={() => doRestore(v.version_no)} disabled={restore.isPending}>
                          {restore.isPending ? 'Restoring…' : `Restore version ${v.version_no}`}
                        </button>
                        <button type="button" className={d.ghostBtn} onClick={() => setConfirm(null)}>Cancel</button>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
          {restore.isError && <p className={d.err} role="alert">{designError(restore.error, 'The version could not be restored.')}</p>}
          {restore.isSuccess && (
            <p className={d.toolOk} role="status">
              Version {restore.data.restored_from} is back as version {restore.data.version_no}; the state before is version {restore.data.kept_as}.
            </p>
          )}
        </>)}

        {shownTab === 'history' && (<>
          {historyOf ? (
            <p className={d.blockNote}>
              Changes to <code>{historyOf.code}</code>.{' '}
              <button type="button" className={d.linkish} onClick={() => setHistoryOf(null)}>All changes to the design</button>
            </p>
          ) : <p className={d.blockNote}>Every change to this design, newest first.</p>}
          {historyOf
            ? <HistoryList entries={entityTrail.data} loading={entityTrail.isLoading} error={entityTrail.error} showCode={false} />
            : <HistoryList entries={designTrail.data} loading={designTrail.isLoading} error={designTrail.error} />}
        </>)}
      </div>
    </aside>
  );
}
