// ============================================================
// OPSYN DESIGN — review and approval (Network GIS Phase 9, standalone D3).
//   Gate      what deployment needs: an approved design version AND an
//             approved BOQ for it
//   Submit    the design (validation is run first; errors block it) or,
//             once the design is approved, its BOQ (frozen at submission)
//   Timeline  each request's steps: who decided, when, why
//   Decide    Approve / Send back (a reason is required), shown only when
//             this person may decide the open step (the server checks too)
//   Comments  on the design, or pinned to a device, cable or spot on the
//             map (click "Pin on the map", then click); resolvable
//   BOQ       a revision's quantities and what changed since the last one
// ============================================================

import { useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { Check, CircleDot, MapPin, MessageSquare, RotateCcw, Send, Undo2, X } from 'lucide-react';
import type { ApprovalRequest, Design, DesignIssue } from '@shared';
import { designApi } from '../../../api/design.api';
import { DESIGN_STATUS_LABEL, designError, formatQuantity } from './designFormat';
import { useApprovalAction, useApprovals, useBoqDiff, useValidateDesign } from './designQueries';
import { useDesignMapStore } from './designStore';
import d from './Design.module.css';

function ago(iso: string | null): string {
  if (!iso) return '';
  try { return formatDistanceToNow(new Date(iso), { addSuffix: true }); } catch { return iso; }
}

const STEP_ICON = { APPROVED: Check, REJECTED: X, PENDING: CircleDot, WAITING: CircleDot, CANCELLED: X };

function Timeline({ req }: { req: ApprovalRequest }) {
  return (
    <ol className={d.steps}>
      <li data-status="APPROVED">
        <Send size={13} aria-hidden />
        <div><p><strong>Submitted</strong> by {req.submitted_by ?? 'someone'} · {ago(req.submitted_at)}</p>
          {req.note && <p className={d.stepComment}>{req.note}</p>}</div>
      </li>
      {req.steps.map(s => {
        const Icon = STEP_ICON[s.status];
        return (
          <li key={s.step_no} data-status={s.status}>
            <Icon size={13} aria-hidden />
            <div>
              <p><strong>{s.label}</strong>{' '}
                {s.status === 'APPROVED' && <>approved by {s.decided_by} · {ago(s.decided_at)}</>}
                {s.status === 'REJECTED' && <>sent back by {s.decided_by} · {ago(s.decided_at)}</>}
                {s.status === 'PENDING' && <span className={d.waiting}>waiting</span>}
                {s.status === 'WAITING' && <span className={d.historyMeta}>next</span>}
                {s.status === 'CANCELLED' && <span className={d.historyMeta}>not reached</span>}
              </p>
              {s.comment && <p className={d.stepComment}>{s.comment}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function Decide({ designId, req }: { designId: string; req: ApprovalRequest }) {
  const [reason, setReason] = useState('');
  const [sending, setSending] = useState(false);
  const decide = useApprovalAction(designId, (a: { decision: 'APPROVE' | 'REJECT'; comment: string | null }) =>
    designApi.decide(req.id, a.decision, a.comment));
  const withdraw = useApprovalAction(designId, () => designApi.withdraw(req.id));
  const step = req.steps.find(s => s.status === 'PENDING');
  if (req.status !== 'PENDING') return null;
  return (
    <div className={d.decide}>
      {req.can_decide && step && !sending && (
        <div className={d.choiceBtns}>
          <button type="button" className={d.solidBtn} onClick={() => decide.mutate({ decision: 'APPROVE', comment: null })}
            disabled={decide.isPending}>
            <Check size={14} aria-hidden />{step.step_no === req.steps.length ? 'Approve' : `Pass ${step.label.toLowerCase()}`}
          </button>
          <button type="button" className={d.ghostBtn} onClick={() => setSending(true)}>Send back…</button>
        </div>
      )}
      {sending && (
        <div className={d.choice} style={{ margin: 0 }}>
          <label className={d.fieldLabel} htmlFor={`why-${req.id}`}>Why is it sent back?</label>
          <textarea id={`why-${req.id}`} className={d.textarea} rows={3} value={reason} onChange={e => setReason(e.target.value)} />
          <div className={d.choiceBtns}>
            <button type="button" className={d.miniBtn} data-danger disabled={!reason.trim() || decide.isPending}
              onClick={() => decide.mutate({ decision: 'REJECT', comment: reason.trim() }, { onSuccess: () => setSending(false) })}>
              Send back
            </button>
            <button type="button" className={d.miniBtn} onClick={() => setSending(false)}>Cancel</button>
          </div>
        </div>
      )}
      {!req.can_decide && step && <p className={d.blockNote}>Waiting for someone who can do the {step.label.toLowerCase()} ({step.feature_key}).</p>}
      {req.can_withdraw && (
        <button type="button" className={d.linkish} onClick={() => withdraw.mutate(undefined)} disabled={withdraw.isPending}>
          Withdraw this submission
        </button>
      )}
      {(decide.isError || withdraw.isError) && <p className={d.err} role="alert">{designError(decide.error ?? withdraw.error)}</p>}
    </div>
  );
}

function Comments({ designId, req }: { designId: string; req: ApprovalRequest }) {
  const { commentPick, setCommentPick, commentTarget, setCommentTarget } = useDesignMapStore();
  const [body, setBody] = useState('');
  const add = useApprovalAction(designId, (b: Parameters<typeof designApi.comment>[1]) => designApi.comment(req.id, b));
  const resolve = useApprovalAction(designId, (a: { id: string; resolved: boolean }) => designApi.resolveComment(a.id, a.resolved));
  const target = commentTarget;
  const send = () => {
    const where = !target ? {} : target.kind === 'point' ? { lng: target.lng, lat: target.lat }
      : target.kind === 'asset' ? { asset_id: target.id } : { cable_id: target.id };
    add.mutate({ body: body.trim(), ...where }, { onSuccess: () => { setBody(''); setCommentTarget(null); } });
  };
  return (
    <section className={d.boqGroup} aria-label="Review comments">
      <h3><MessageSquare size={14} aria-hidden /> Comments <span className={d.groupN}>{req.comments.filter(c => !c.resolved).length} open</span></h3>
      <ul className={d.commentList}>
        {req.comments.map(c => (
          <li key={c.id} data-resolved={c.resolved}>
            <p>{c.target_code && <code>{c.target_code}</code>} {!c.target_code && c.lng !== null && <MapPin size={12} aria-label="on the map" />} {c.body}</p>
            <p className={d.historyMeta}>
              {c.author} · {ago(c.created_at)}{c.resolved && ` · resolved by ${c.resolved_by}`}{' '}
              <button type="button" className={d.linkish} onClick={() => resolve.mutate({ id: c.id, resolved: !c.resolved })}>
                {c.resolved ? 'Reopen' : 'Resolve'}
              </button>
            </p>
          </li>
        ))}
      </ul>
      <label className={d.fieldLabel} htmlFor={`c-${req.id}`}>Add a comment</label>
      <textarea id={`c-${req.id}`} className={d.textarea} rows={2} value={body} onChange={e => setBody(e.target.value)} />
      <p className={d.historyMeta}>
        {target ? <>On {target.kind === 'point' ? 'a spot on the map' : <code>{target.code}</code>}{' '}
          <button type="button" className={d.linkish} onClick={() => setCommentTarget(null)}>remove</button></>
          : commentPick ? 'Click a device, a cable or a spot on the map…'
          : <button type="button" className={d.linkish} onClick={() => setCommentPick(true)}>Pin on the map</button>}
      </p>
      <button type="button" className={d.miniBtn} data-strong onClick={send} disabled={!body.trim() || add.isPending}>Comment</button>
      {add.isError && <p className={d.err} role="alert">{designError(add.error)}</p>}
    </section>
  );
}

function BoqRevision({ req }: { req: ApprovalRequest }) {
  const diff = useBoqDiff(req.id);
  const qs = req.payload.quantities ?? [];
  return (
    <details className={d.engineNotes}>
      <summary>Quantities ({qs.length} lines){diff.data?.previous_revision ? ` · vs revision ${diff.data.previous_revision}` : ''}</summary>
      <table className={d.boqTable}>
        <thead><tr><th scope="col">Item</th><th scope="col" className={d.num}>Quantity</th><th scope="col" className={d.num}>Change</th></tr></thead>
        <tbody>
          {qs.map(q => {
            const ch = diff.data?.changes.find(c => c.item === q.item);
            return (
              <tr key={`${q.group}${q.item}`}>
                <td>{q.item}</td><td className={d.num}>{formatQuantity(q.quantity, q.unit)}</td>
                <td className={d.num}>{ch ? `${ch.change > 0 ? '+' : ''}${formatQuantity(ch.change, ch.unit)}` : diff.data?.previous_revision ? '—' : ''}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </details>
  );
}

export function ReviewDrawer({ design, onClose, onIssues }: {
  design: Design; onClose: () => void; onIssues: (issues?: DesignIssue[]) => void;
}) {
  const approvals = useApprovals(design.id);
  const validate = useValidateDesign(design.id);
  const [note, setNote] = useState('');
  const [boqNote, setBoqNote] = useState('');
  const submitDesign = useApprovalAction(design.id, (n: string | null) => designApi.submitDesign(design.id, n));
  const submitBoq = useApprovalAction(design.id, (n: string | null) => designApi.submitBoq(design.id, n));
  const reopen = useApprovalAction(design.id, () => designApi.reopen(design.id));
  const data = approvals.data;
  const designReqs = data?.requests.filter(r => r.subject_type === 'DESIGN_VERSION') ?? [];
  const boqReqs = data?.requests.filter(r => r.subject_type === 'BOQ') ?? [];
  const checked = validate.data?.summary;

  return (
    <aside className={d.drawer} aria-label="Review and approval">
      <header className={d.drawerHead}>
        <div>
          <h2 className={d.drawerTitle}>Review</h2>
          <p className={d.drawerSub}>{DESIGN_STATUS_LABEL[design.status]} · an approved design and an approved BOQ are needed to deploy.</p>
        </div>
        <button type="button" className={d.closeBtn} onClick={onClose} aria-label="Close review"><X size={18} aria-hidden /></button>
      </header>
      <div className={d.drawerBody}>
        {approvals.isLoading && <div className={d.skel} />}
        {approvals.isError && <p className={d.err} role="alert">{designError(approvals.error, "Couldn't load the reviews.")}</p>}
        {data && (
          <ul className={d.gate} aria-label="What deployment needs">
            <li data-ok={data.gate.design_approved}>{data.gate.design_approved ? <Check size={14} aria-hidden /> : <CircleDot size={14} aria-hidden />}Design approved</li>
            <li data-ok={data.gate.boq_approved}>{data.gate.boq_approved ? <Check size={14} aria-hidden /> : <CircleDot size={14} aria-hidden />}BOQ approved</li>
            <li data-ok={data.gate.can_deploy}>{data.gate.can_deploy ? 'Ready to deploy' : 'Not ready to deploy'}</li>
          </ul>
        )}

        {data?.can_submit_design && (
          <section className={d.boqGroup} aria-label="Submit the design">
            <h3>Submit for review</h3>
            <p className={d.blockNote}>Version {design.current_version?.version_no} is frozen as it is and the design is locked while it is reviewed.</p>
            {!checked ? (
              <button type="button" className={d.miniBtn} onClick={() => validate.mutate()} disabled={validate.isPending}>
                {validate.isPending ? 'Checking…' : 'Check the design first'}
              </button>
            ) : checked.errors > 0 ? (
              <div className={d.outcome} data-tone="bad" role="alert">
                <p>{checked.errors} {checked.errors === 1 ? 'error stops' : 'errors stop'} the submission.</p>
                <button type="button" className={d.linkish} onClick={() => onIssues()}>See the issues</button>
              </div>
            ) : (<>
              <p className={d.toolOk}>No errors{checked.warnings ? `; ${checked.warnings} warnings the reviewer will see` : ''}.</p>
              <label className={d.fieldLabel} htmlFor="rv-note">Note for the reviewer (optional)</label>
              <textarea id="rv-note" className={d.textarea} rows={2} value={note} onChange={e => setNote(e.target.value)} />
              <button type="button" className={d.solidBtn} style={{ alignSelf: 'flex-start' }} disabled={submitDesign.isPending}
                onClick={() => submitDesign.mutate(note.trim() || null, { onSuccess: () => setNote('') })}>
                <Send size={14} aria-hidden />Submit version {design.current_version?.version_no}
              </button>
            </>)}
            {submitDesign.isError && <p className={d.err} role="alert">{designError(submitDesign.error)}</p>}
          </section>
        )}

        {designReqs.map((r, i) => (
          <section key={r.id} className={d.request} data-status={r.status} aria-label={`Design version ${r.revision} review`}>
            <h3>Design · version {r.revision} <span className={d.reqStatus} data-status={r.status}>{r.status.toLowerCase()}</span></h3>
            {r.payload.validation && <p className={d.historyMeta}>At submission: {r.payload.validation.errors} errors, {r.payload.validation.warnings} warnings</p>}
            <Timeline req={r} />
            <Decide designId={design.id} req={r} />
            {(i === 0 || r.status === 'PENDING') && <Comments designId={design.id} req={r} />}
          </section>
        ))}

        {design.status === 'APPROVED' && (
          <section className={d.boqGroup} aria-label="The BOQ">
            {data?.can_submit_boq && (<>
              <h3>Submit the BOQ</h3>
              <p className={d.blockNote}>Its quantities are frozen for the review. Needed before deployment.</p>
              <label className={d.fieldLabel} htmlFor="rv-boq-note">Note (optional)</label>
              <textarea id="rv-boq-note" className={d.textarea} rows={2} value={boqNote} onChange={e => setBoqNote(e.target.value)} />
              <button type="button" className={d.solidBtn} style={{ alignSelf: 'flex-start' }} disabled={submitBoq.isPending}
                onClick={() => submitBoq.mutate(boqNote.trim() || null, { onSuccess: () => setBoqNote('') })}>
                <Send size={14} aria-hidden />{submitBoq.isPending ? 'Submitting…' : 'Submit the BOQ'}
              </button>
              {submitBoq.isError && <p className={d.err} role="alert">{designError(submitBoq.error)}</p>}
            </>)}
            <button type="button" className={d.linkish} onClick={() => reopen.mutate(undefined)} disabled={reopen.isPending}>
              <RotateCcw size={12} aria-hidden /> Reopen for changes (a new version; this approval stays in the history)
            </button>
          </section>
        )}

        {boqReqs.map(r => (
          <section key={r.id} className={d.request} data-status={r.status} aria-label={`BOQ revision ${r.revision} review`}>
            <h3>BOQ · revision {r.revision} <span className={d.reqStatus} data-status={r.status}>{r.status.toLowerCase()}</span></h3>
            <p className={d.historyMeta}>For design version {r.payload.version_no}</p>
            <Timeline req={r} />
            <BoqRevision req={r} />
            <Decide designId={design.id} req={r} />
          </section>
        ))}
        {data && data.requests.length === 0 && !data.can_submit_design && (
          <p className={d.blockNote}><Undo2 size={12} aria-hidden /> Nothing has been submitted for this design.</p>
        )}
      </div>
    </aside>
  );
}
