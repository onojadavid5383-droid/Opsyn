// ============================================================
// OPSYN DESIGN — the card shown while looking back (Network GIS Phase 8):
// which version is on the map (read-only), or what changed between two
// with a key to the compare overlay and the lists (click one to go there).
// ============================================================

import { ArrowLeft, RotateCcw } from 'lucide-react';
import type { DesignCompare } from '@shared';
import { CMP } from './compareFeatures';
import type { DesignView } from './designStore';
import d from './Design.module.css';

interface Props {
  view:      Exclude<DesignView, null>;
  label:     string | null;
  compare:   DesignCompare | undefined;
  loading:   boolean;
  error:     boolean;
  canRestore: boolean;
  onBack:    () => void;
  onCompare: () => void;
  onRestore: () => void;
  onGo:      (lng: number, lat: number) => void;
}

function center(f: GeoJSON.Feature): [number, number] | null {
  const g = f.geometry;
  if (g?.type === 'Point') return g.coordinates as [number, number];
  if (g?.type === 'LineString') return g.coordinates[Math.floor(g.coordinates.length / 2)] as [number, number];
  return null;
}

export function ViewCard({ view, label, compare, loading, error, canRestore, onBack, onCompare, onRestore, onGo }: Props) {
  const code = (f: GeoJSON.Feature) => String(f.properties?.asset_code ?? '');
  return (
    <section className={d.viewCard} aria-label={view.mode === 'version' ? `Viewing version ${view.no}` : 'Comparing versions'}>
      {view.mode === 'version' ? (<>
        <p className={d.viewTitle}>Viewing version {view.no} <span className={d.readOnly}>read-only</span></p>
        {label && <p className={d.versionLabel}>{label}</p>}
        <p className={d.toolHint}>This is how the design was then. Nothing you see here can be edited.</p>
        <div className={d.choiceBtns}>
          <button type="button" className={d.miniBtn} onClick={onCompare}>Compare with current</button>
          {canRestore && <button type="button" className={d.miniBtn} onClick={onRestore}><RotateCcw size={13} aria-hidden />Restore…</button>}
          <button type="button" className={d.miniBtn} data-strong onClick={onBack}><ArrowLeft size={13} aria-hidden />Back to current</button>
        </div>
      </>) : (<>
        <p className={d.viewTitle}>Version {view.from} → version {view.to}</p>
        {loading && <div className={d.skel} />}
        {error && <p className={d.err} role="alert">Couldn't compare these versions.</p>}
        {compare && (<>
          <ul className={d.cmpKey}>
            <li><span className={d.keyAdded} style={{ ['--k' as string]: CMP.added }} aria-hidden />{compare.counts.added} added</li>
            <li><span className={d.keyRemoved} style={{ ['--k' as string]: CMP.removed }} aria-hidden />{compare.counts.removed} removed</li>
            <li><span className={d.keyMoved} aria-hidden>→</span>{compare.counts.moved} moved</li>
            <li><span className={d.keyRerouted} style={{ ['--k' as string]: CMP.rerouted }} aria-hidden />{compare.counts.changed} changed</li>
          </ul>
          <div className={d.cmpLists}>
            {compare.moved.slice(0, 6).map(m => (
              <button key={`m${m.id}`} type="button" className={d.cmpItem} onClick={() => onGo(m.to[0], m.to[1])}>
                <code>{m.code}</code> moved {Math.round(m.distance_m)} m
              </button>
            ))}
            {compare.added.slice(0, 4).map(f => {
              const c = center(f);
              return c && <button key={`a${f.properties?.id}`} type="button" className={d.cmpItem} onClick={() => onGo(c[0], c[1])}>
                <code>{code(f)}</code> added</button>;
            })}
            {compare.removed.slice(0, 4).map(f => {
              const c = center(f);
              return c && <button key={`r${f.properties?.id}`} type="button" className={d.cmpItem} onClick={() => onGo(c[0], c[1])}>
                <code>{code(f)}</code> removed</button>;
            })}
            {compare.changed.filter(c => c.kind === 'cable' && c.length_before_m != null).slice(0, 4).map(c => (
              <p key={`c${c.id}`} className={d.cmpItem}><code>{c.code}</code> {Math.round(c.length_before_m ?? 0)} → {Math.round(c.length_after_m ?? 0)} m</p>
            ))}
            {compare.counts.added + compare.counts.removed + compare.counts.moved + compare.counts.changed === 0 && (
              <p className={d.blockNote}>The two versions hold the same network.</p>
            )}
          </div>
        </>)}
        <div className={d.choiceBtns}>
          <button type="button" className={d.miniBtn} data-strong onClick={onBack}><ArrowLeft size={13} aria-hidden />Back to current</button>
        </div>
      </>)}
    </section>
  );
}
