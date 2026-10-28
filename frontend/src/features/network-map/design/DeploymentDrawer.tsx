// ============================================================
// OPSYN DESIGN — deployment (Network GIS Phase 10).
//   Start     only through the approval gate (design + BOQ approved): the
//             rows go to construction, their designed geometry is kept
//   Progress  one bar through the build (not installed → installed →
//             testing → verified; the map rings use the same colours),
//             FATs installed x / y, cable installed / planned, per FDT
//   Field     choose devices / cables (filter by state), then install /
//             test / verify / fail (a failed test needs a note); the
//             server allows only legal lifecycle steps and says which
//             it refused and why
//   As-built  click where a device really went, or along a cable's real
//             route; the variance table compares it with the design
//   Promote   when everything is verified: the SAME rows become the live
//             network (confirmed first; it can't be undone)
// ============================================================

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Check, CircleDot, HardHat, MapPin, Rocket, Route, X } from 'lucide-react';
import type { Design, DeploymentAction, DeploymentAdvanceResult, DeploymentItem, NetLifecycleStatus } from '@shared';
import { designApi } from '../../../api/design.api';
import { DEPLOY_STEPS } from './DeploymentLayer';
import { designError } from './designFormat';
import { useDeployment, useDeploymentAction, useDesignFeatures } from './designQueries';
import { useDesignMapStore } from './designStore';
import d from './Design.module.css';

type Row = { kind: 'asset' | 'cable'; id: string; code: string; type: string; state: NetLifecycleStatus };

const ACTIONS: { action: DeploymentAction; label: string }[] = [
  { action: 'install', label: 'Installed' },
  { action: 'test', label: 'Testing' },
  { action: 'verify', label: 'Verified' },
];

function km(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`;
}

function Bar({ states, items }: { states: Partial<Record<NetLifecycleStatus, number>>; items: number }) {
  return (
    <div className={d.deployBar} role="img"
      aria-label={DEPLOY_STEPS.map(s => `${s.label} ${states[s.state] ?? 0}`).join(', ')}>
      {DEPLOY_STEPS.map(s => (states[s.state] ?? 0) > 0 && (
        <span key={s.state} style={{ flexGrow: states[s.state], background: s.color }} title={`${s.label}: ${states[s.state]}`} />
      ))}
      {items === 0 && <span style={{ flexGrow: 1 }} />}
    </div>
  );
}

function AsBuiltCard({ designId }: { designId: string }) {
  const { asbuilt, setAsBuilt } = useDesignMapStore();
  const save = useDeploymentAction(designId, (a: NonNullable<typeof asbuilt>) => designApi.asBuilt(designId, {
    kind: a.kind, id: a.id,
    geometry: a.kind === 'asset' ? { type: 'Point', coordinates: a.points[0] } : { type: 'LineString', coordinates: a.points },
  }));
  if (!asbuilt) return null;
  const enough = asbuilt.kind === 'asset' ? asbuilt.points.length === 1 : asbuilt.points.length >= 2;
  return (
    <div className={d.outcome} data-tone="ok" role="status">
      <p><strong>As-built: <code>{asbuilt.code}</code></strong></p>
      <p className={d.blockNote}>
        {asbuilt.kind === 'asset' ? 'Click where it was really installed.' : 'Click along the route the cable really takes, end to end.'}
        {' '}{asbuilt.points.length} {asbuilt.points.length === 1 ? 'point' : 'points'}.
      </p>
      <div className={d.choiceBtns}>
        <button type="button" className={d.miniBtn} data-strong disabled={!enough || save.isPending}
          onClick={() => save.mutate(asbuilt, { onSuccess: () => setAsBuilt(null) })}>
          {save.isPending ? 'Saving…' : 'Save as-built'}
        </button>
        {asbuilt.kind === 'cable' && asbuilt.points.length > 0 && (
          <button type="button" className={d.miniBtn} onClick={() => setAsBuilt({ ...asbuilt, points: asbuilt.points.slice(0, -1) })}>
            Undo point
          </button>
        )}
        <button type="button" className={d.miniBtn} onClick={() => setAsBuilt(null)}>Cancel</button>
      </div>
      {save.isError && <p className={d.err} role="alert">{designError(save.error)}</p>}
    </div>
  );
}

function FieldUpdates({ designId }: { designId: string }) {
  const ws = useDesignFeatures(designId);
  const setAsBuilt = useDesignMapStore(s => s.setAsBuilt);
  const [filter, setFilter] = useState<NetLifecycleStatus | 'ALL'>('ALL');
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [failing, setFailing] = useState(false);
  const [note, setNote] = useState('');
  const [outcome, setOutcome] = useState<DeploymentAdvanceResult | null>(null);
  const advance = useDeploymentAction(designId,
    (b: { items: DeploymentItem[]; action: DeploymentAction; note?: string | null }) => designApi.advance(designId, b));

  const rows: Row[] = useMemo(() => (ws.data?.features ?? []).map(f => {
    const p = f.properties as Record<string, string>;
    return { kind: p.kind as Row['kind'], id: String(p.id), code: String(p.asset_code),
             type: String(p.kind === 'asset' ? p.asset_type : p.cable_category), state: p.lifecycle_status as NetLifecycleStatus };
  }).sort((a, b) => a.kind.localeCompare(b.kind) || a.code.localeCompare(b.code)), [ws.data]);
  const shown = filter === 'ALL' ? rows : rows.filter(r => r.state === filter);
  const chosen = rows.filter(r => picked.has(r.id));
  const allShown = shown.length > 0 && shown.every(r => picked.has(r.id));

  const toggle = (id: string) => setPicked(s => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const run = (action: DeploymentAction, why?: string) => advance.mutate(
    { items: chosen.map(r => ({ kind: r.kind, id: r.id })), action, note: why ?? null },
    { onSuccess: res => { setOutcome(res); setPicked(new Set()); setFailing(false); setNote(''); } },
  );

  return (
    <section className={d.boqGroup} aria-label="Field updates">
      <h3><HardHat size={14} aria-hidden /> Field updates <span className={d.groupN}>{chosen.length} chosen</span></h3>
      <div className={d.chips} role="radiogroup" aria-label="Show">
        {[{ state: 'ALL' as const, label: 'All' }, ...DEPLOY_STEPS].map(s => (
          <button key={s.state} type="button" role="radio" className={d.chip} aria-checked={filter === s.state}
            onClick={() => setFilter(s.state)}>
            {s.label} {s.state === 'ALL' ? rows.length : rows.filter(r => r.state === s.state).length}
          </button>
        ))}
      </div>
      <div className={d.itemScroll}>
        <table className={d.boqTable}>
          <thead>
            <tr>
              <th scope="col"><input type="checkbox" aria-label="Choose all shown" checked={allShown}
                onChange={() => setPicked(s => { const n = new Set(s); for (const r of shown) { if (allShown) n.delete(r.id); else n.add(r.id); } return n; })} /></th>
              <th scope="col">Code</th><th scope="col">State</th><th scope="col"><span className="sr-only">As-built</span></th>
            </tr>
          </thead>
          <tbody>
            {shown.map(r => {
              const step = DEPLOY_STEPS.find(s => s.state === r.state);
              return (
                <tr key={r.id}>
                  <td><input type="checkbox" aria-label={`Choose ${r.code}`} checked={picked.has(r.id)} onChange={() => toggle(r.id)} /></td>
                  <td><code>{r.code}</code> <span className={d.pieces}>{r.type.replace(/_/g, ' ').toLowerCase()}</span></td>
                  <td><span className={d.stateMark} style={{ ['--c' as string]: step?.color ?? '#94A3B8' }} />{step?.label ?? r.state.toLowerCase()}</td>
                  <td className={d.num}>
                    {r.state !== 'CONSTRUCTION' && (
                      <button type="button" className={d.linkish} title="Record where it was really installed"
                        onClick={() => setAsBuilt({ kind: r.kind, id: r.id, code: r.code, points: [] })}>
                        {r.kind === 'asset' ? <MapPin size={12} aria-hidden /> : <Route size={12} aria-hidden />} As-built
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!failing ? (
        <div className={d.choiceBtns}>
          <span className={d.historyMeta}>Mark as</span>
          {ACTIONS.map(a => (
            <button key={a.action} type="button" className={d.miniBtn} disabled={!chosen.length || advance.isPending}
              onClick={() => run(a.action)}>{a.label}</button>
          ))}
          <button type="button" className={d.miniBtn} data-danger disabled={!chosen.length || advance.isPending}
            onClick={() => setFailing(true)}>Failed test…</button>
        </div>
      ) : (
        <div className={d.choice} style={{ margin: 0 }}>
          <label className={d.fieldLabel} htmlFor="dp-fail">What failed? It goes back to installed for rework.</label>
          <textarea id="dp-fail" className={d.textarea} rows={2} value={note} onChange={e => setNote(e.target.value)} />
          <div className={d.choiceBtns}>
            <button type="button" className={d.miniBtn} data-danger disabled={!note.trim() || advance.isPending}
              onClick={() => run('fail', note.trim())}>Record the failure</button>
            <button type="button" className={d.miniBtn} onClick={() => setFailing(false)}>Cancel</button>
          </div>
        </div>
      )}
      {outcome && (
        <div className={d.outcome} data-tone={outcome.refused.length ? 'bad' : 'ok'} role="status">
          <p>{outcome.changed.length} updated{outcome.refused.length ? `, ${outcome.refused.length} not` : ''}.</p>
          {outcome.refused.length > 0 && (
            <ul>{outcome.refused.slice(0, 8).map(r => <li key={r.code}><code>{r.code}</code>: {r.reason}</li>)}</ul>
          )}
        </div>
      )}
      {advance.isError && <p className={d.err} role="alert">{designError(advance.error)}</p>}
    </section>
  );
}

export function DeploymentDrawer({ design, onClose }: { design: Design; onClose: () => void }) {
  const q = useDeployment(design.id);
  const [note, setNote] = useState('');
  const [confirming, setConfirming] = useState(false);
  const start = useDeploymentAction(design.id, (n: string | null) => designApi.deploy(design.id, n), true);
  const promote = useDeploymentAction(design.id, () => designApi.promote(design.id), true);
  const p = q.data;
  const dep = p?.deployment;
  const open = dep?.status === 'IN_PROGRESS';

  return (
    <aside className={d.drawer} aria-label="Deployment">
      <header className={d.drawerHead}>
        <div>
          <h2 className={d.drawerTitle}>Deployment</h2>
          <p className={d.drawerSub}>
            {!dep ? 'Not started' : open ? `In construction since ${new Date(dep.started_at).toLocaleDateString()}`
              : `In service since ${new Date(dep.promoted_at!).toLocaleDateString()}`}
          </p>
        </div>
        <button type="button" className={d.closeBtn} onClick={onClose} aria-label="Close deployment"><X size={18} aria-hidden /></button>
      </header>
      <div className={d.drawerBody}>
        {q.isLoading && <div className={d.skel} />}
        {q.isError && <p className={d.err} role="alert">{designError(q.error, "Couldn't load the deployment.")}</p>}

        {p && !dep && (
          <section className={d.boqGroup} aria-label="Start the deployment">
            <ul className={d.gate} aria-label="What deployment needs">
              <li data-ok={p.gate.design_approved}>{p.gate.design_approved ? <Check size={14} aria-hidden /> : <CircleDot size={14} aria-hidden />}Design approved</li>
              <li data-ok={p.gate.boq_approved}>{p.gate.boq_approved ? <Check size={14} aria-hidden /> : <CircleDot size={14} aria-hidden />}BOQ approved</li>
            </ul>
            {p.gate.can_deploy ? (<>
              <p className={d.blockNote}>
                {p.items} devices and cables go to construction. Their designed positions are kept, so what is really built
                can be compared with them.
              </p>
              <label className={d.fieldLabel} htmlFor="dp-note">Note for the field (optional)</label>
              <textarea id="dp-note" className={d.textarea} rows={2} value={note} onChange={e => setNote(e.target.value)} />
              <button type="button" className={d.solidBtn} style={{ alignSelf: 'flex-start' }} disabled={start.isPending}
                onClick={() => start.mutate(note.trim() || null)}>
                <HardHat size={14} aria-hidden />{start.isPending ? 'Starting…' : 'Start the deployment'}
              </button>
            </>) : (
              <p className={d.blockNote}>{p.gate.reasons.join('. ')}. Approvals are in Review.</p>
            )}
            {start.isError && <p className={d.err} role="alert">{designError(start.error)}</p>}
          </section>
        )}

        {p && dep && (
          <section className={d.boqGroup} aria-label="Progress">
            <Bar states={p.states} items={p.items} />
            <ul className={d.deployLegend}>
              {DEPLOY_STEPS.map(s => (
                <li key={s.state}><span className={d.stateMark} style={{ ['--c' as string]: s.color }} />{s.label} <strong>{p.states[s.state] ?? 0}</strong></li>
              ))}
            </ul>
            <dl className={d.deployStats}>
              <div className={d.stat}><dt>Installed</dt><dd>{p.installed_pct}%</dd></div>
              <div className={d.stat}><dt>Verified</dt><dd>{p.verified_pct}%</dd></div>
              <div className={d.stat}><dt>FATs installed</dt><dd>{p.fats.installed} / {p.fats.total}</dd></div>
              <div className={d.stat}><dt>Cable installed</dt><dd>{km(p.cable_m.installed)} <small>/ {km(p.cable_m.planned)}</small></dd></div>
            </dl>
            {p.per_fdt.length > 0 && (
              <table className={d.boqTable} aria-label="Per FDT">
                <thead><tr><th scope="col">FDT</th><th scope="col" className={d.num}>FATs installed</th><th scope="col" className={d.num}>Verified</th></tr></thead>
                <tbody>{p.per_fdt.map(f => (
                  <tr key={f.fdt}><td><code>{f.fdt}</code></td><td className={d.num}>{f.installed} / {f.fats}</td><td className={d.num}>{f.verified}</td></tr>
                ))}</tbody>
              </table>
            )}
          </section>
        )}

        {open && <AsBuiltCard designId={design.id} />}
        {open && <FieldUpdates designId={design.id} />}

        {p && dep && p.variance.length > 0 && (
          <section className={d.boqGroup} aria-label="Design against as-built">
            <h3>Design against as-built</h3>
            <table className={d.boqTable}>
              <thead><tr><th scope="col">Item</th><th scope="col" className={d.num}>Designed</th><th scope="col" className={d.num}>As built</th><th scope="col" className={d.num}>Difference</th></tr></thead>
              <tbody>{p.variance.map(v => (
                <tr key={v.id}>
                  <td><code>{v.code}</code></td>
                  {v.kind === 'cable' ? (<>
                    <td className={d.num}>{km(v.design_m ?? 0)}</td><td className={d.num}>{km(v.asbuilt_m ?? 0)}</td>
                    <td className={d.num} data-over={(v.difference_m ?? 0) > 0 || undefined}>
                      {(v.difference_m ?? 0) > 0 ? '+' : ''}{v.difference_m} m{v.difference_pct != null ? ` (${v.difference_pct > 0 ? '+' : ''}${v.difference_pct}%)` : ''}
                    </td>
                  </>) : (<>
                    <td className={d.num}>—</td><td className={d.num}>—</td><td className={d.num}>moved {v.moved_m} m</td>
                  </>)}
                </tr>
              ))}</tbody>
            </table>
          </section>
        )}

        {p && open && (
          <section className={d.boqGroup} aria-label="Promote">
            <h3><Rocket size={14} aria-hidden /> Hand over to the live network</h3>
            {!p.ready_to_promote ? (
              <p className={d.blockNote}>{p.not_verified} still to verify. Everything must be verified first.</p>
            ) : !confirming ? (
              <button type="button" className={d.solidBtn} style={{ alignSelf: 'flex-start' }} onClick={() => setConfirming(true)}>
                <Rocket size={14} aria-hidden />Promote to the live network…
              </button>
            ) : (
              <div className={d.outcome} data-tone="bad" role="alertdialog" aria-label="Confirm promotion">
                <p>{p.items} devices and cables become the network in service, and this design is closed. This can't be undone.</p>
                <div className={d.choiceBtns}>
                  <button type="button" className={d.solidBtn} disabled={promote.isPending}
                    onClick={() => promote.mutate(undefined, { onSuccess: () => setConfirming(false) })}>
                    {promote.isPending ? 'Promoting…' : 'Promote'}
                  </button>
                  <button type="button" className={d.miniBtn} onClick={() => setConfirming(false)}>Cancel</button>
                </div>
              </div>
            )}
            {promote.isError && <p className={d.err} role="alert">{designError(promote.error)}</p>}
          </section>
        )}

        {dep?.status === 'PROMOTED' && dep.summary && (
          <div className={d.outcome} data-tone="ok">
            <p><strong>In service.</strong> {dep.summary.assets} devices, {dep.summary.cables} cables ({km(dep.summary.cable_m)}) are
              now part of the live network. The as-built state is kept as version {dep.summary.version_no}.</p>
            <Link className={d.linkish} to="/network">Open the network map</Link>
          </div>
        )}
      </div>
    </aside>
  );
}
