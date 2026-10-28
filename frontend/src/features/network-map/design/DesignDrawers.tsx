// ============================================================
// OPSYN DESIGN — the right-hand drawers.
//   ValidationPanel  stored issues by severity, each with "View on map"
//                    (rings it and frames it); Validate re-runs the checks
//   BoqDrawer        quantities (devices, cable by type and fibre count),
//                    the FTTx engine's per-street BOQ, and its notes
// ============================================================

import { formatDistanceToNow } from 'date-fns';
import { Crosshair, X } from 'lucide-react';
import type { DesignBoq, DesignIssue, DesignValidation } from '@shared';
import { SEVERITY_COLOR, SEVERITY_LABEL, designError, formatQuantity, groupIssues } from './designFormat';
import d from './Design.module.css';

function DrawerHead({ title, sub, onClose }: { title: string; sub?: string; onClose: () => void }) {
  return (
    <header className={d.drawerHead}>
      <div>
        <h2 className={d.drawerTitle}>{title}</h2>
        {sub && <p className={d.drawerSub}>{sub}</p>}
      </div>
      <button type="button" className={d.closeBtn} onClick={onClose} aria-label={`Close ${title.toLowerCase()}`}>
        <X size={18} aria-hidden />
      </button>
    </header>
  );
}

// ── Validation ───────────────────────────────────────────────

const ENGINE_SEVERITY: Record<string, string> = { ERROR: 'Error', WARNING: 'Warning', INFO: 'Note' };

interface ValidationProps {
  validation: DesignValidation | undefined;
  loading:    boolean;
  error:      unknown;
  validating: boolean;
  validateError: unknown;
  validatedAt: string | null;
  /** The FTTx engine's own findings for an auto-designed version */
  engineFindings?: { severity: string; category: string; message: string }[];
  focusId:    string | null;
  onValidate: () => void;
  onView:     (issue: DesignIssue) => void;
  onClose:    () => void;
}

export function ValidationPanel({
  validation, loading, error, validating, validateError, validatedAt, engineFindings = [], focusId, onValidate, onView, onClose,
}: ValidationProps) {
  const groups = groupIssues(validation?.issues ?? []);
  const sub = validatedAt
    ? `Checked ${formatDistanceToNow(new Date(validatedAt), { addSuffix: true })}`
    : 'Not checked yet: run Validate to check the design';
  return (
    <aside className={d.drawer} aria-label="Validation issues">
      <DrawerHead title="Issues" sub={sub} onClose={onClose} />
      <div className={d.drawerBody}>
        <button type="button" className={d.solidBtn} onClick={onValidate} disabled={validating} style={{ alignSelf: 'flex-start' }}>
          {validating ? 'Checking the design…' : validatedAt ? 'Check again' : 'Validate now'}
        </button>
        {!!validateError && <p className={d.err} role="alert">{designError(validateError, 'The check could not run.')}</p>}
        {loading && <div className={d.skel} />}
        {!!error && <p className={d.err} role="alert">{designError(error, "Couldn't load the issues.")}</p>}
        {validation && validatedAt && groups.length === 0 && (
          <p className={d.allClear}>No issues. The design passes every check.</p>
        )}
        {groups.map(g => (
          <section key={g.severity} className={d.issueGroup} aria-label={SEVERITY_LABEL[g.severity]}>
            <h3 style={{ ['--sev' as string]: SEVERITY_COLOR[g.severity] }}>
              <span className={d.sevMark} data-sev={g.severity} aria-hidden />
              {SEVERITY_LABEL[g.severity]} <span className={d.groupN}>{g.issues.length}</span>
            </h3>
            <ul className={d.issueList}>
              {g.issues.map(issue => (
                <li key={issue.id} className={d.issue} aria-current={issue.id === focusId || undefined}
                  style={{ ['--sev' as string]: SEVERITY_COLOR[issue.severity] }}>
                  <p className={d.issueMsg}>{issue.message}</p>
                  <p className={d.issueMeta}>
                    <code>{issue.code}</code>
                    {issue.rule && <span> · {issue.rule}</span>}
                  </p>
                  {issue.geometry && (
                    <button type="button" className={d.viewBtn} onClick={() => onView(issue)}>
                      <Crosshair size={13} aria-hidden />View on map
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))}
        {engineFindings.length > 0 && (
          <details className={d.engineNotes}>
            <summary>From the engine run <span className={d.groupN}>{engineFindings.length}</span></summary>
            <p className={d.blockNote}>What the FTTx engine reported while it designed this version. It was accepted with these; they are not re-checked.</p>
            <ul>
              {engineFindings.map((f, i) => (
                <li key={i} data-sev={f.severity}>
                  <span className={d.engineCat}>{ENGINE_SEVERITY[f.severity] ?? 'Note'}{f.category ? ` · ${f.category}` : ''}</span>
                  {f.message}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </aside>
  );
}

// ── BOQ ──────────────────────────────────────────────────────

// The engine's BOQ layer fields (engine/pipeline.py _OUTPUT_LAYER_SCHEMAS["boq"]) worth a column
const STREET_COLUMNS: { key: string; label: string }[] = [
  { key: 'street_name', label: 'Street' },
  { key: 'total_homepass', label: 'Homepasses' },
  { key: 'total_fdt', label: 'FDT' },
  { key: 'total_fat', label: 'FAT' },
  { key: 'total_poles', label: 'Poles' },
  { key: 'total_closures', label: 'Closures' },
  { key: 'total_box_to_box_cable', label: 'B2B cable m' },
  { key: 'feeder_cable_length_m', label: 'Feeder m' },
];

function cell(v: string | number | null | undefined): string {
  if (v == null || v === '') return '—';
  return typeof v === 'number' ? v.toLocaleString('en-GB', { maximumFractionDigits: 1 }) : v;
}

interface BoqProps {
  boq:     DesignBoq | undefined;
  loading: boolean;
  error:   unknown;
  onClose: () => void;
}

export function BoqDrawer({ boq, loading, error, onClose }: BoqProps) {
  const devices = boq?.quantities.filter(q => q.group === 'Devices') ?? [];
  const cables = boq?.quantities.filter(q => q.group === 'Cable') ?? [];
  // Only the columns the engine actually filled
  const columns = STREET_COLUMNS.filter(c => boq?.streets.some(r => r[c.key] != null && r[c.key] !== ''));
  return (
    <aside className={d.drawer} aria-label="Bill of quantities">
      <DrawerHead title="Bill of quantities" sub="From the design's working set, recomputed on every change" onClose={onClose} />
      <div className={d.drawerBody}>
        {loading && <><div className={d.skel} /><div className={d.skel} /></>}
        {!!error && <p className={d.err} role="alert">{designError(error, "Couldn't compute the BOQ.")}</p>}
        {boq && boq.quantities.length === 0 && (
          <p className={d.blockNote}>Nothing to count yet. The BOQ fills in once the design has FDTs, FATs and cables.</p>
        )}
        {[{ title: 'Devices', rows: devices }, { title: 'Cable', rows: cables }].filter(g => g.rows.length).map(g => (
          <section key={g.title} className={d.boqGroup}>
            <h3>{g.title}</h3>
            <table className={d.boqTable}>
              <thead><tr><th scope="col">Item</th><th scope="col" className={d.num}>Quantity</th></tr></thead>
              <tbody>
                {g.rows.map(r => (
                  <tr key={`${r.code}-${r.item}`}>
                    <td>{r.item}{r.pieces ? <span className={d.pieces}>{r.pieces} {r.pieces === 1 ? 'run' : 'runs'}</span> : null}</td>
                    <td className={d.num}>{formatQuantity(r.quantity, r.unit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))}
        {boq?.street_boq_available && boq.streets.length > 0 && columns.length > 0 && (
          <section className={d.boqGroup}>
            <h3>By street <span className={d.groupN}>FTTx engine</span></h3>
            <div className={d.tableScroll}>
              <table className={d.boqTable}>
                <thead><tr>{columns.map(c => <th key={c.key} scope="col" className={c.key === 'street_name' ? undefined : d.num}>{c.label}</th>)}</tr></thead>
                <tbody>
                  {boq.streets.map((r, i) => (
                    <tr key={i}>{columns.map(c => <td key={c.key} className={c.key === 'street_name' ? undefined : d.num}>{cell(r[c.key])}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
        {boq && boq.notes.length > 0 && (
          <ul className={d.notes}>{boq.notes.map(note => <li key={note}>{note}</li>)}</ul>
        )}
      </div>
    </aside>
  );
}
