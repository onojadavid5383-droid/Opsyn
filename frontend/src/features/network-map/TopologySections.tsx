// ============================================================
// OPSYN NETWORK MAP — inspector sections for topology (Phase 3).
//   UtilisationSection  capacity in use from GET …/utilisation, with where
//                       the number comes from (never a bare percentage)
//   ConnectionsSection  what feeds this asset and what it feeds; trace
//                       buttons; add a link by hand; remove hand-made ones
//                       (derived links change through their source data)
//   FibresSection       a cable's fibres by tube in TIA-598 colours; record
//                       a fibre's status
// ============================================================

import { useEffect, useId, useState } from 'react';
import { ArrowDownFromLine, ArrowUpToLine, Plus, Trash2 } from 'lucide-react';
import type {
  NetAssetSummary, NetConnection, NetConnectionType, NetFibre, NetFibreStatus, NetTraceDirection, NetUtilisationBasis,
  NetUtilisationState,
} from '@shared';
import type { ApiError } from '../../api/client';
import {
  useAssetSearch, useConnections, useCreateConnection, useDeleteConnection, useFibres, useSetFibre, useUtilisation,
} from './queries';
import { formatLength } from './mapMath';
import { CONNECTION_LABEL, DERIVED_LABEL, FAULT_COLOR } from './symbology';
import s from './NetworkMap.module.css';

function errorText(err: unknown): string | null {
  if (!err) return null;
  const e = err as ApiError;
  if (e.status === 403) return "You don't have permission to change the live network. Ask an administrator for network editing access.";
  return e.detail ?? e.message ?? 'The change could not be saved.';
}

// ── Utilisation ──────────────────────────────────────────────

const STATE_LABEL: Record<NetUtilisationState, string> = {
  ok: 'Room to grow', warning: 'Filling up', critical: 'Nearly full', full: 'Over capacity', unknown: 'Not known',
};
const STATE_COLOR: Record<NetUtilisationState, string> = {
  ok: '#1F8A4C', warning: '#C77700', critical: FAULT_COLOR, full: FAULT_COLOR, unknown: '#94A3B8',
};
const BASIS_TEXT: Record<NetUtilisationBasis, string> = {
  ports: 'Counted from PON ports marked in use.',
  fat_ports: 'Ports of the FATs this FDT feeds.',
  connections: 'Counted from the assets it feeds.',
  recorded: 'As recorded on the asset; nothing is connected below it yet.',
  none: 'Nothing is connected below it and no figure is recorded.',
};

export function UtilisationSection({ assetId, capacityLabel }: { assetId: string; capacityLabel: string }) {
  const { data: u, isLoading, isError } = useUtilisation(assetId);
  return (
    <section className={s.section} aria-labelledby="insp-capacity">
      <h3 id="insp-capacity" className={s.sectionTitle}>Capacity</h3>
      {isLoading && <div className={s.skeleton} />}
      {isError && <p className={s.error} role="alert">Capacity could not be loaded.</p>}
      {u && (
        <>
          <dl className={s.facts}>
            <dt>{capacityLabel}</dt><dd>{u.capacity ?? 'Not recorded'}</dd>
            <dt>In use</dt><dd>{u.used ?? 'Not known'}{u.pct != null && ` (${Math.round(u.pct)}%)`}</dd>
            {u.available != null && (<><dt>Free</dt><dd>{Math.max(u.available, 0)}</dd></>)}
          </dl>
          {u.pct != null && (
            <div className={s.meter} role="meter" aria-label={`${capacityLabel} in use`}
              aria-valuemin={0} aria-valuemax={u.capacity ?? 0} aria-valuenow={u.used ?? 0}
              aria-valuetext={`${Math.round(u.pct)}%, ${STATE_LABEL[u.state].toLowerCase()}`}>
              <div className={s.meterFill} style={{ width: `${Math.min(100, u.pct)}%`, background: STATE_COLOR[u.state] }} />
            </div>
          )}
          <p className={s.utilState} style={{ ['--state-color' as string]: STATE_COLOR[u.state] }}>
            <span className={s.stateMark} aria-hidden="true" data-state={u.state} />
            {STATE_LABEL[u.state]}
          </p>
          <p className={s.hint}>{BASIS_TEXT[u.basis]}</p>
        </>
      )}
    </section>
  );
}

// ── Connections ──────────────────────────────────────────────

function ConnectionRow({ c, onGoTo, onRemove, removing }: {
  c: NetConnection; onGoTo: (id: string, code: string) => void; onRemove: (id: string) => void; removing: boolean;
}) {
  return (
    <li className={s.connRow}>
      <div className={s.connMain}>
        <button type="button" className={s.refBtn} onClick={() => onGoTo(c.peer.id, c.peer.asset_code)}>{c.peer.asset_code}</button>
        <span className={s.connType}>
          {CONNECTION_LABEL[c.connection_type]}
          {c.via_cable && ` via ${c.via_cable.asset_code}${c.via_cable.length_m != null ? `, ${formatLength(c.via_cable.length_m)}` : ''}`}
        </span>
        <span className={s.hint}>{c.derived_from ? DERIVED_LABEL[c.derived_from] ?? 'From other records' : 'Added by hand'}</span>
      </div>
      {!c.derived_from && (
        <button type="button" className={s.iconBtn} onClick={() => onRemove(c.id)} disabled={removing}
          aria-label={`Remove the link with ${c.peer.asset_code}`} title="Remove this link">
          <Trash2 size={15} aria-hidden />
        </button>
      )}
    </li>
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

function AddConnectionForm({ assetId, assetCode, types, onDone }: {
  assetId: string; assetCode: string; types: NetConnectionType[]; onDone: () => void;
}) {
  const id = useId();
  const [side, setSide] = useState<'fedBy' | 'feeds'>('fedBy');
  const [q, setQ] = useState('');
  const [peer, setPeer] = useState<NetAssetSummary | null>(null);
  const [type, setType] = useState<NetConnectionType>('FEED');
  const term = useDebounced(q, 200);
  const search = useAssetSearch(peer ? '' : term, 'any');
  const create = useCreateConnection();
  const results = (search.data ?? []).filter(r => r.id !== assetId).slice(0, 6);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!peer) return;
    const body = side === 'fedBy'
      ? { source_asset_id: peer.id, dest_asset_id: assetId, connection_type: type }
      : { source_asset_id: assetId, dest_asset_id: peer.id, connection_type: type };
    create.mutate(body, { onSuccess: onDone });
  };

  return (
    <form className={s.form} onSubmit={submit} aria-label="Add a connection">
      <fieldset className={s.radioRow}>
        <legend className={s.srOnly}>Direction</legend>
        <label><input type="radio" name={`${id}-side`} checked={side === 'fedBy'} onChange={() => setSide('fedBy')} /> {assetCode} is fed by</label>
        <label><input type="radio" name={`${id}-side`} checked={side === 'feeds'} onChange={() => setSide('feeds')} /> {assetCode} feeds</label>
      </fieldset>
      <div className={s.formRow}>
        <label htmlFor={`${id}-peer`}>Asset</label>
        {peer ? (
          <div className={s.peerChosen}>
            <span className={s.traceCode}>{peer.asset_code}</span>
            <button type="button" className={s.textBtn} onClick={() => { setPeer(null); setQ(''); }}>Change</button>
          </div>
        ) : (
          <>
            <input id={`${id}-peer`} value={q} onChange={e => setQ(e.target.value)} placeholder="Code or name" autoComplete="off" />
            {term.trim().length >= 2 && (
              <ul className={s.peerResults} aria-label="Matching assets">
                {results.map(r => (
                  <li key={r.id}>
                    <button type="button" onClick={() => setPeer(r)}>{r.asset_code}<span className={s.hint}>{r.asset_type}</span></button>
                  </li>
                ))}
                {!search.isFetching && results.length === 0 && <li className={s.hint}>No asset in service matches.</li>}
              </ul>
            )}
          </>
        )}
      </div>
      <div className={s.formRow}>
        <label htmlFor={`${id}-type`}>Link</label>
        <select id={`${id}-type`} value={type} onChange={e => setType(e.target.value as NetConnectionType)}>
          {types.map(t => <option key={t} value={t}>{CONNECTION_LABEL[t]}</option>)}
        </select>
      </div>
      {errorText(create.error) && <p className={s.error} role="alert">{errorText(create.error)}</p>}
      <div className={s.formActions}>
        <button type="button" className={s.linkBtn} onClick={onDone}>Cancel</button>
        <button type="submit" className={s.primaryBtn} disabled={!peer || create.isPending}>
          {create.isPending ? 'Adding…' : 'Add connection'}
        </button>
      </div>
    </form>
  );
}

export function ConnectionsSection({ assetId, assetCode, types, onGoTo, onTrace }: {
  assetId: string; assetCode: string; types: NetConnectionType[];
  onGoTo: (id: string, code: string) => void; onTrace: (direction: NetTraceDirection) => void;
}) {
  const { data, isLoading, isError } = useConnections(assetId);
  const remove = useDeleteConnection();
  const [adding, setAdding] = useState(false);
  const up = data?.upstream ?? [];
  const down = data?.downstream ?? [];

  return (
    <section className={s.section} aria-labelledby="insp-links">
      <div className={s.sectionHead}>
        <h3 id="insp-links" className={s.sectionTitle}>Connections</h3>
        {!adding && (
          <button type="button" className={s.textBtn} onClick={() => setAdding(true)}>
            <Plus size={13} aria-hidden /> Add connection
          </button>
        )}
      </div>
      {isLoading && <div className={s.skeleton} />}
      {isError && <p className={s.error} role="alert">Connections could not be loaded.</p>}
      {data && (
        <>
          <h4 className={s.subTitle}>Fed from</h4>
          {up.length ? (
            <ul className={s.connList}>{up.map(c => <ConnectionRow key={c.id} c={c} onGoTo={onGoTo} onRemove={id => remove.mutate(id)} removing={remove.isPending} />)}</ul>
          ) : <p className={s.muted}>Nothing recorded feeds {assetCode}.</p>}
          <h4 className={s.subTitle}>Feeds</h4>
          {down.length ? (
            <ul className={s.connList}>{down.map(c => <ConnectionRow key={c.id} c={c} onGoTo={onGoTo} onRemove={id => remove.mutate(id)} removing={remove.isPending} />)}</ul>
          ) : <p className={s.muted}>{assetCode} feeds nothing recorded.</p>}
          {errorText(remove.error) && <p className={s.error} role="alert">{errorText(remove.error)}</p>}
          <div className={s.transition}>
            <button type="button" className={s.linkBtn} onClick={() => onTrace('upstream')}>
              <ArrowUpToLine size={14} aria-hidden /> Trace to OLT
            </button>
            <button type="button" className={s.linkBtn} onClick={() => onTrace('downstream')}>
              <ArrowDownFromLine size={14} aria-hidden /> Trace what it feeds
            </button>
          </div>
        </>
      )}
      {adding && <AddConnectionForm assetId={assetId} assetCode={assetCode} types={types} onDone={() => setAdding(false)} />}
    </section>
  );
}

// ── Fibres ───────────────────────────────────────────────────

const FIBRE_STATUS_LABEL: Record<NetFibreStatus, string> = {
  FREE: 'Free', USED: 'In use', RESERVED: 'Reserved', FAULTY: 'Faulty', DARK: 'Dark (unlit)',
};

export function FibresSection({ cableId, statuses }: { cableId: string; statuses: NetFibreStatus[] }) {
  const { data: fibres, isLoading, isError } = useFibres(cableId);
  const save = useSetFibre(cableId);
  const [chosen, setChosen] = useState<NetFibre | null>(null);
  const [status, setStatus] = useState<NetFibreStatus>('FREE');

  const tubes = new Map<number, NetFibre[]>();
  for (const f of fibres ?? []) tubes.set(f.tube_no, [...(tubes.get(f.tube_no) ?? []), f]);
  const used = (fibres ?? []).filter(f => f.status === 'USED').length;

  return (
    <section className={s.section} aria-labelledby="insp-fibres">
      <h3 id="insp-fibres" className={s.sectionTitle}>Fibres</h3>
      {isLoading && <div className={s.skeleton} />}
      {isError && <p className={s.error} role="alert">Fibres could not be loaded.</p>}
      {fibres && fibres.length === 0 && <p className={s.muted}>No fibre count recorded for this cable.</p>}
      {fibres && fibres.length > 0 && (
        <>
          <p className={s.muted} style={{ marginTop: 0 }}>{fibres.length} fibres, {used} in use. Choose a fibre to record its status.</p>
          {[...tubes.entries()].map(([tube, fs]) => (
            <div key={tube} className={s.tube}>
              <span className={s.tubeLabel}>
                <span className={s.tubeSwatch} style={{ background: fs[0].tube_colour_hex }} aria-hidden="true" />
                Tube {tube}, {fs[0].tube_colour.toLowerCase()}
              </span>
              <div className={s.fibres} role="group" aria-label={`Tube ${tube}`}>
                {fs.map(f => (
                  <button key={f.fiber_no} type="button" className={s.fibre} data-status={f.status}
                    aria-pressed={chosen?.fiber_no === f.fiber_no}
                    style={{ ['--fibre' as string]: f.colour_hex }}
                    onClick={() => { setChosen(f); setStatus(f.status); save.reset(); }}
                    aria-label={`Fibre ${f.fiber_no}, ${f.colour.toLowerCase()}, ${FIBRE_STATUS_LABEL[f.status].toLowerCase()}`}
                    title={`Fibre ${f.fiber_no}: ${f.colour}, ${FIBRE_STATUS_LABEL[f.status]}`} />
                ))}
              </div>
            </div>
          ))}
          <p className={s.hint}>Filled: in use. Ring: free. Crossed: faulty.</p>
          {chosen && (
            <form className={s.transition} onSubmit={e => { e.preventDefault(); save.mutate({ fiberNo: chosen.fiber_no, status }, { onSuccess: f => setChosen(f) }); }}>
              <label className={s.srOnly} htmlFor="fibre-status">Status of fibre {chosen.fiber_no}</label>
              <span className={s.fibreChosen}>Fibre {chosen.fiber_no}</span>
              <select id="fibre-status" value={status} onChange={e => setStatus(e.target.value as NetFibreStatus)}>
                {statuses.map(st => <option key={st} value={st}>{FIBRE_STATUS_LABEL[st]}</option>)}
              </select>
              <button type="submit" className={s.primaryBtn} disabled={save.isPending || status === chosen.status}>
                {save.isPending ? 'Saving…' : 'Save'}
              </button>
            </form>
          )}
          {errorText(save.error) && <p className={s.error} role="alert">{errorText(save.error)}</p>}
        </>
      )}
    </section>
  );
}
