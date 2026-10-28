// ============================================================
// OPSYN DESIGN — the design toolbar (top of the map) and the summary
// strip (bottom). Auto design and Manual design are equal entry points
// (plan §3.5): neither depends on the other. Validate runs the shared
// validation service; Issues and BOQ open the right-hand drawer.
// ============================================================

import { formatDistanceToNow } from 'date-fns';
import { BadgeCheck, ClipboardList, History, PencilRuler, ShieldCheck, Sparkles, TriangleAlert } from 'lucide-react';
import type { DesignBoq, DesignDelta, DesignSummary } from '@shared';
import { describeDelta, formatKm } from './designFormat';
import type { DesignDrawer } from './designStore';
import d from './Design.module.css';

interface ToolbarProps {
  editable:    boolean;
  validating:  boolean;
  drawer:      DesignDrawer;
  issueCount:  number | null;
  onValidate:  () => void;
  onDrawer:    (drawer: DesignDrawer) => void;
  /** Present once the track is available; absent = shown as coming */
  onAutoDesign?:   () => void;
  onManualDesign?: () => void;
  /** An auto run in flight: its percentage, shown on the button */
  autoProgress?:   number | null;
  /** The manual tools are out */
  manualOn?:       boolean;
  /** Opens versions and history (Phase 8) */
  onVersions?:     () => void;
  /** Opens review and approval (Phase 9) */
  onReview?:       () => void;
}

export function DesignToolbar({
  editable, validating, drawer, issueCount, onValidate, onDrawer, onAutoDesign, onManualDesign, autoProgress = null, manualOn = false, onVersions, onReview,
}: ToolbarProps) {
  const toggle = (which: Exclude<DesignDrawer, null>) => onDrawer(drawer === which ? null : which);
  return (
    <div className={d.toolbar} role="toolbar" aria-label="Design tools">
      <div className={d.tracks} role="group" aria-label="Build the design">
        <button type="button" className={d.trackBtn} onClick={onAutoDesign}
          disabled={!onAutoDesign || (!editable && autoProgress === null)} aria-describedby={onAutoDesign ? undefined : 'dt-soon'}
          aria-pressed={drawer === 'auto'}>
          <Sparkles size={16} aria-hidden />
          <span>Auto design</span>
          {autoProgress !== null && <span className={d.trackRun} aria-label={`designing, ${autoProgress}%`}>{autoProgress}%</span>}
        </button>
        <button type="button" className={d.trackBtn} onClick={onManualDesign}
          disabled={!onManualDesign || !editable} aria-describedby={onManualDesign ? undefined : 'dt-soon'}
          aria-pressed={manualOn}>
          <PencilRuler size={16} aria-hidden />
          <span>Manual design</span>
        </button>
      </div>
      {(!onAutoDesign || !onManualDesign) && (
        <span id="dt-soon" className={d.soon}>
          {!onAutoDesign && !onManualDesign ? 'Auto and manual design arrive next'
            : !onManualDesign ? 'Manual design arrives next' : 'Auto design arrives next'}
        </span>
      )}
      <span className={d.toolSep} aria-hidden />
      <button type="button" className={d.toolBtn} onClick={onValidate} disabled={validating}>
        <ShieldCheck size={16} aria-hidden />{validating ? 'Checking…' : 'Validate'}
      </button>
      <button type="button" className={d.toolBtn} aria-pressed={drawer === 'validation'} onClick={() => toggle('validation')}>
        <TriangleAlert size={16} aria-hidden />Issues{issueCount !== null && <span className={d.toolCount}>{issueCount}</span>}
      </button>
      <button type="button" className={d.toolBtn} aria-pressed={drawer === 'boq'} onClick={() => toggle('boq')}>
        <ClipboardList size={16} aria-hidden />BOQ
      </button>
      {onVersions && (
        <button type="button" className={d.toolBtn} aria-pressed={drawer === 'versions'} onClick={onVersions}>
          <History size={16} aria-hidden />Versions
        </button>
      )}
      {onReview && (
        <button type="button" className={d.toolBtn} aria-pressed={drawer === 'review'} onClick={onReview}>
          <BadgeCheck size={16} aria-hidden />Review
        </button>
      )}
    </div>
  );
}

interface StripProps {
  summary:  DesignSummary | undefined;
  boq:      DesignBoq | undefined;
  onIssues: () => void;
  onBoq:    () => void;
  /** The last edit's delta (Phase 7): changed stats pulse, the ribbon says what changed */
  change?:  { seq: number; label: string; delta: DesignDelta } | null;
}

function Stat({ label, value, hint, pulse }: { label: string; value: string; hint?: string; pulse?: string }) {
  return (
    <div className={d.stat} title={hint}>
      <dt>{label}</dt>
      {/* keyed by the change, so the pulse replays on every edit that touches it */}
      <dd key={pulse} data-pulse={pulse ? 'true' : undefined}>{value}</dd>
    </div>
  );
}

const n = (v: number) => v.toLocaleString('en-GB');

export function SummaryStrip({ summary, boq, onIssues, onBoq, change }: StripProps) {
  if (!summary) return <div className={d.strip} aria-busy="true"><div className={d.skel} /></div>;
  const touched = (code: string) =>
    change?.delta.boq.some(c => c.code === code && c.unit === 'each') ? String(change.seq) : undefined;
  const cableTouched = change?.delta.boq.some(c => c.unit === 'm') ? String(change.seq) : undefined;
  const validated = summary.validated_at
    ? `Checked ${formatDistanceToNow(new Date(summary.validated_at), { addSuffix: true })}`
    : 'Not checked yet';
  return (
    <section className={d.strip} aria-label="Design summary">
      <dl className={d.stats}>
        <Stat label="Homepasses" value={n(summary.homepasses)} hint={`${n(summary.customers)} customers`} />
        <Stat label="FDT" value={n(summary.fdt)} pulse={touched('FDT')} />
        <Stat label="FAT" value={n(summary.fat)} pulse={touched('FAT')} />
        <Stat label="Splitters" value={n(summary.splitters)} pulse={touched('SPLITTER')} />
        <Stat label="Closures" value={n(summary.closures)} pulse={touched('CLOSURE')} />
        <Stat label="Cable" value={formatKm(summary.cable_km)} pulse={cableTouched} />
      </dl>
      {change && describeDelta(change.delta).length > 0 && (
        <p key={change.seq} className={d.ribbon} role="status">
          <strong>{change.label}</strong> · {describeDelta(change.delta).join(' · ')}
        </p>
      )}
      <div className={d.stripSide}>
        <div className={d.stripActions}>
          <button type="button" className={d.stripBtn} onClick={onBoq}
            title="Bill of quantities from the working set; no unit rates are held yet, so it counts items rather than cost">
            <span className={d.stripBig}>{boq ? n(boq.quantities.length) : '…'}</span>
            <span>BOQ lines</span>
          </button>
          <button type="button" className={d.stripBtn} data-tone={summary.errors ? 'error' : undefined} onClick={onIssues}>
            <span className={d.stripBig}>{n(summary.errors)}</span><span>{summary.errors === 1 ? 'error' : 'errors'}</span>
          </button>
          <button type="button" className={d.stripBtn} data-tone={summary.warnings ? 'warning' : undefined} onClick={onIssues}>
            <span className={d.stripBig}>{n(summary.warnings)}</span><span>{summary.warnings === 1 ? 'warning' : 'warnings'}</span>
          </button>
        </div>
        <span className={d.checked}>{validated}</span>
      </div>
    </section>
  );
}
