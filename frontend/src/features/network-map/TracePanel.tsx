// ============================================================
// OPSYN NETWORK MAP — trace panel (Phase 3).
// Upstream: the path from the asset to its OLT as a route list — each
// step says what links it (the cable and its length, or a patch/split),
// with the total cable length; if no OLT is reached it says where the
// chain stops. Downstream: what the asset feeds, counted by type, and the
// customers served. Choosing a step opens it in the inspector.
// ============================================================

import { X } from 'lucide-react';
import type { NetAssetType, NetTrace, NetTraceHop } from '@shared';
import { markerDataUrl } from './markerImages';
import { formatLength } from './mapMath';
import { ASSET_TYPES, CONNECTION_LABEL } from './symbology';
import s from './NetworkMap.module.css';

function linkText(hop: NetTraceHop, cableLabel: (c: string) => string): string {
  if (hop.via_cable) {
    const len = hop.via_cable.length_m != null ? `, ${formatLength(hop.via_cable.length_m)}` : '';
    return `${hop.via_cable.asset_code} (${cableLabel(hop.via_cable.cable_category).toLowerCase()}${len})`;
  }
  return hop.connection_type ? `${CONNECTION_LABEL[hop.connection_type]}, no cable recorded` : '';
}

interface Props {
  trace:      NetTrace | undefined;
  loading:    boolean;
  error:      boolean;
  startCode:  string;
  direction:  'upstream' | 'downstream';
  typeLabel:  (t: NetAssetType) => string;
  cableLabel: (c: string) => string;
  onOpen:     (assetId: string) => void;
  onClose:    () => void;
}

export function TracePanel({ trace, loading, error, startCode, direction, typeLabel, cableLabel, onOpen, onClose }: Props) {
  const byId = new Map(trace?.hops.map(h => [h.asset.id, h]) ?? []);
  const path = trace?.path_ids.map(id => byId.get(id)!).filter(Boolean) ?? [];
  const extraParents = trace && direction === 'upstream'
    ? trace.hops.filter(h => h.depth > 0 && !trace.path_ids.includes(h.asset.id)).length : 0;
  const last = path[path.length - 1];

  const title = direction === 'upstream' ? `Path from ${startCode} to the OLT` : `Everything fed by ${startCode}`;

  return (
    <section className={s.tracePanel} aria-label={title}>
      <div className={s.traceHead}>
        <h2 className={s.traceTitle}>{title}</h2>
        <button type="button" className={s.iconBtn} onClick={onClose} aria-label="Clear trace">
          <X size={16} aria-hidden />
        </button>
      </div>

      {loading && <p className={s.muted} role="status">Tracing…</p>}
      {error && <p className={s.error} role="alert">The trace could not be loaded. Try again in a moment.</p>}

      {trace && direction === 'upstream' && (
        <>
          <p className={s.traceSummary}>
            {path.length - 1} {path.length - 1 === 1 ? 'step' : 'steps'}
            {trace.path_length_m != null && `, ${formatLength(trace.path_length_m)} of cable`}
          </p>
          <ol className={s.traceList}>
            {path.map((hop, i) => (
              <li key={hop.asset.id}>
                {i > 0 && <span className={s.traceLink}>{linkText(hop, cableLabel)}</span>}
                <button type="button" className={s.traceStep} onClick={() => onOpen(hop.asset.id)}>
                  <img src={markerDataUrl(hop.asset.asset_type)} alt="" width={24} height={24} />
                  <span className={s.traceCode}>{hop.asset.asset_code}</span>
                  <span className={s.traceType}>{typeLabel(hop.asset.asset_type)}</span>
                </button>
              </li>
            ))}
          </ol>
          {!trace.reached_root && (
            <p className={s.traceWarn} role="status">
              No OLT reached. The chain stops at {last?.asset.asset_code ?? startCode}: record what feeds it,
              with a cable that has both ends set or a connection in the inspector.
            </p>
          )}
          {extraParents > 0 && (
            <p className={s.hint}>Also fed along {extraParents} other {extraParents === 1 ? 'branch' : 'branches'}, drawn in grey.</p>
          )}
        </>
      )}

      {trace && direction === 'downstream' && (
        <>
          <p className={s.traceSummary}>
            {trace.customers} {trace.customers === 1 ? 'customer' : 'customers'} served
            {trace.hops.length > 1 && `, ${trace.hops.length - 1} assets in all`}
          </p>
          {trace.hops.length > 1 ? (
            <ul className={s.traceCounts}>
              {ASSET_TYPES.filter(t => trace.counts_by_type[t]).map(t => (
                <li key={t}>
                  <img src={markerDataUrl(t)} alt="" width={22} height={22} />
                  <span>{typeLabel(t)}</span>
                  <span className={s.traceCount}>{trace.counts_by_type[t]}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className={s.muted}>{startCode} does not feed anything recorded yet.</p>
          )}
          {trace.truncated && <p className={s.hint}>The trace stopped at 5,000 assets; zoom into a smaller part of the network.</p>}
        </>
      )}
    </section>
  );
}
