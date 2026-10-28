// ============================================================
// OPSYN DESIGN — design mode's pieces of the map page
// (/network?mode=design&design=<id>). NetworkMapPage renders:
//   <DesignMapContent>  inside the canvas: the design's layers and, while
//                       drawing, the boundary tool
//   <DesignOverlays>    over the map: toolbar, summary strip, drawers
// Both read the design through designQueries and the UI state through
// designStore. Manual design (Phase 6): EditLayer on the map, ManualToolbar
// over it; DesignOverlays runs the tools' operations (useOperate).
// Deployment mode (Phase 10): the rows ringed by install state, as-built
// capture on the map, the deployment drawer; no editing.
// ============================================================

import { useCallback, useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { Design } from '@shared';
import type { Picked } from '../NetworkLayers';
import { BoundaryDraw } from './BoundaryDraw';
import { DesignLayers } from './DesignLayers';
import { AutoDesignDrawer } from './AutoDesignDrawer';
import { EditLayer } from './EditLayer';
import { EDITING } from './editMachine';
import { ManualToolbar } from './ManualToolbar';
import { BoqDrawer, ValidationPanel } from './DesignDrawers';
import { CompareLayer } from './CompareLayer';
import { VersionsDrawer } from './VersionsDrawer';
import { ReviewDrawer } from './ReviewDrawer';
import { CommentPicker, ReviewPins } from './ReviewLayer';
import { AsBuiltPicker, DeploymentStates } from './DeploymentLayer';
import { DeploymentDrawer } from './DeploymentDrawer';
import { ViewCard } from './ViewCard';
import { DesignToolbar, SummaryStrip } from './DesignToolbar';
import { boundaryPolygon, designError, isEditable, type LngLat } from './designFormat';
import {
  RUN_ACTIVE, refreshDesign, useApprovals, useCompare, useDesignBoq, useDesignSummary, useDesignValidation, useGenerateStatus, useOperate,
  useUpdateDesign, useValidateDesign, useVersionFeatures, useVersions,
} from './designQueries';
import { useDesignMapStore } from './designStore';

export function DesignMapContent({ design, onPick }: { design: Design; onPick: (p: Picked | null) => void }) {
  const { hiddenInputs, focusIssue, drawing, setDrawing, edit, view, commentPick, drawer, mode, asbuilt } = useDesignMapStore();
  const deploying = mode === 'deployment';
  // Review comments pinned on the map: the latest design review's (Phase 9;
  // a later BOQ submission has no map comments of its own)
  const approvals = useApprovals(drawer === 'review' ? design.id : null);
  const pins = approvals.data?.requests.find(r => r.subject_type === 'DESIGN_VERSION')?.comments ?? [];
  // Looking back: another version on the map (the newer one when comparing), read-only
  const shownNo = view?.mode === 'version' ? view.no : view?.mode === 'compare' ? view.to : null;
  const shown = useVersionFeatures(view ? design.id : null, shownNo);
  const compare = useCompare(design.id, view?.mode === 'compare' ? { from: view.from, to: view.to } : null);
  const update = useUpdateDesign(design.id);
  const cancel = useCallback(() => { update.reset(); setDrawing(false); }, [update, setDrawing]);
  const finish = (points: LngLat[]) =>
    update.mutate({ boundary: boundaryPolygon(points) }, { onSuccess: () => setDrawing(false) });
  return (
    <>
      <DesignLayers design={design} hidden={hiddenInputs} focusIssue={view ? null : focusIssue}
        features={view ? shown.data ?? { type: 'FeatureCollection', features: [] } : undefined}
        onPick={drawing || commentPick || asbuilt || EDITING(edit.tool) ? () => {} : onPick} />
      {deploying && !view && <DeploymentStates designId={design.id} />}
      {deploying && asbuilt && <AsBuiltPicker />}
      {drawer === 'review' && <ReviewPins comments={pins} />}
      {commentPick && <CommentPicker />}
      {view?.mode === 'compare' && <CompareLayer compare={compare.data} />}
      {!drawing && !view && !deploying && <EditLayer designId={design.id} editable={isEditable(design.status)} />}
      {drawing && (
        <BoundaryDraw saving={update.isPending} error={designError(update.error)} onFinish={finish} onCancel={cancel} />
      )}
    </>
  );
}

interface OverlayProps {
  design: Design;
  /** Frame the map on a box (a new version arrived) */
  onFit:  (bbox: [number, number, number, number]) => void;
}

export function DesignOverlays({ design, onFit }: OverlayProps) {
  const qc = useQueryClient();
  const { drawer, setDrawer, focusIssue, setFocusIssue, manual, setManual, setRunner, send, setNote, change, view, setView, setMode } = useDesignMapStore();
  const versions = useVersions(design.id, !!view);
  const compare = useCompare(design.id, view?.mode === 'compare' ? { from: view.from, to: view.to } : null);
  const viewed = view?.mode === 'version' ? versions.data?.find(v => v.version_no === view.no) : undefined;
  const currentNo = design.current_version?.version_no;

  // The manual tools' operations run here (always mounted in design mode, so
  // the right-click menu works with the palette closed too)
  const operate = useOperate(design.id);
  const { mutate: runOp } = operate;
  useEffect(() => {
    setRunner(op => runOp(op, {
      onSuccess: res => { send({ type: 'DONE' }); setNote({ tone: 'ok', text: res.operation.label }); },
      onError: err => {
        const e = err as { detail?: string; message?: string };
        setNote({ tone: 'error', text: e.detail ?? e.message ?? 'That change could not be made.' });
      },
    }));
    return () => setRunner(null);
  }, [runOp, send, setNote, setRunner]);
  const generation = useGenerateStatus(design.id);
  const runStatus = generation.data?.status;
  const running = !!runStatus && RUN_ACTIVE.includes(runStatus);

  // A run that stops (done or failed) may have replaced the working set
  const lastRun = useRef(runStatus);
  useEffect(() => {
    if (lastRun.current && RUN_ACTIVE.includes(lastRun.current) && runStatus && !RUN_ACTIVE.includes(runStatus)) {
      refreshDesign(qc, design.id, design.project_id);
    }
    lastRun.current = runStatus;
  }, [qc, runStatus, design.id, design.project_id]);

  // A new version (auto run, import): frame what it holds
  const lastVersion = useRef(design.current_version?.id);
  useEffect(() => {
    const v = design.current_version?.id;
    if (lastVersion.current && v && v !== lastVersion.current && design.bbox) onFit(design.bbox);
    lastVersion.current = v;
  }, [design.current_version?.id, design.bbox, onFit]);

  const summary = useDesignSummary(design.id);
  const validation = useDesignValidation(design.id);
  const validate = useValidateDesign(design.id);
  // The BOQ runs the engine; fetched for the strip's line count and the drawer
  const boq = useDesignBoq(design.id, true);

  const runValidate = () => { setDrawer('validation'); validate.mutate(); };
  const issueCount = validation.data ? validation.data.issues.length : null;

  return (
    <>
      <DesignToolbar
        editable={isEditable(design.status)}
        validating={validate.isPending}
        drawer={drawer}
        issueCount={issueCount}
        onValidate={runValidate}
        onDrawer={setDrawer}
        onAutoDesign={() => setDrawer(drawer === 'auto' ? null : 'auto')}
        autoProgress={running ? generation.data?.progress_pct ?? 0 : null}
        onManualDesign={() => setManual(!manual)}
        manualOn={manual}
        onVersions={() => setDrawer(drawer === 'versions' ? null : 'versions')}
        onReview={() => setDrawer(drawer === 'review' ? null : 'review')}
      />
      {/* Before the strip: the strip steps aside for the rail (Design.module.css .palette ~ .strip) */}
      {manual && isEditable(design.status) && <ManualToolbar designId={design.id} busy={operate.isPending} />}
      <SummaryStrip
        summary={summary.data}
        boq={boq.data}
        onIssues={() => setDrawer('validation')}
        onBoq={() => setDrawer('boq')}
        change={change}
      />
      {drawer === 'validation' && (
        <ValidationPanel
          validation={validation.data}
          loading={validation.isLoading}
          error={validation.error}
          validating={validate.isPending}
          validateError={validate.error}
          validatedAt={validation.data?.summary.validated_at ?? summary.data?.validated_at ?? null}
          engineFindings={validation.data?.engine_findings ?? []}
          focusId={focusIssue?.id ?? null}
          onValidate={() => validate.mutate()}
          onView={setFocusIssue}
          onClose={() => setDrawer(null)}
        />
      )}
      {drawer === 'auto' && (
        <AutoDesignDrawer
          design={design}
          summary={summary.data}
          status={generation.data}
          onClose={() => setDrawer(null)}
          onIssues={() => setDrawer('validation')}
        />
      )}
      {drawer === 'deployment' && <DeploymentDrawer design={design} onClose={() => setMode('design')} />}
      {drawer === 'versions' && <VersionsDrawer design={design} onClose={() => setDrawer(null)} />}
      {drawer === 'review' && <ReviewDrawer design={design} onClose={() => setDrawer(null)} onIssues={() => setDrawer('validation')} />}
      {view && (
        <ViewCard
          view={view}
          label={viewed?.label ?? null}
          compare={compare.data}
          loading={compare.isLoading}
          error={compare.isError}
          canRestore={isEditable(design.status)}
          onBack={() => setView(null)}
          onCompare={() => view.mode === 'version' && currentNo && setView({ mode: 'compare', from: view.no, to: currentNo })}
          onRestore={() => setDrawer('versions')}
          onGo={(lng, lat) => onFit([lng - 0.0004, lat - 0.0004, lng + 0.0004, lat + 0.0004])}
        />
      )}
      {drawer === 'boq' && (
        <BoqDrawer boq={boq.data} loading={boq.isLoading} error={boq.error} onClose={() => setDrawer(null)} />
      )}
    </>
  );
}
