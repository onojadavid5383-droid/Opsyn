// ============================================================
// OPSYN DESIGN — design-mode UI state (Zustand). Server data lives in
// designQueries (TanStack Query); this holds what the planner is doing:
//   hiddenInputs  input layers switched off on the map
//   drawer        the right-hand drawer: validation issues, the BOQ or
//                 auto design (Phase 5)
//   drawing       drawing a boundary (the map's clicks place corners)
//   focusIssue    the issue shown by "View on map" (ringed on the map)
//   manual        the manual design tools are out (Phase 6)
//   edit          the tools' state machine (editMachine.ts); send() steps
//                 it and hands any finished operation to the runner that
//                 DesignOverlays registers (it owns the mutation)
//   note          the last tool message: a refusal or what was just done
//   view          looking back (Phase 8): one version read-only, or two
//                 compared; editing is off meanwhile
//   historyOf     the asset / cable whose audit trail the versions drawer shows
//   commentPick   a review comment is waiting for a click on the map (P9);
//                 commentTarget is what was clicked
//   change        what the last edit / undo / redo changed (Phase 7 deltas):
//                 the strip animates it, the tool card lists rerouted cables
//   mode          'deployment' (Phase 10): the map colours the rows by install
//                 state and the deployment drawer is out; editing is off
//   asbuilt       an as-built capture in progress: the device / cable and the
//                 points clicked so far (one for a device, a line for a cable)
// Reset whenever a different design is opened.
// ============================================================

import { create } from 'zustand';
import type { DesignDelta, DesignInputLayerKey, DesignIssue, DesignOperationBody, DesignRerouted } from '@shared';
import { INITIAL, reduce, type EditEvent, type EditState, type Step } from './editMachine';

export type DesignDrawer = 'validation' | 'boq' | 'auto' | 'versions' | 'review' | 'deployment' | null;
export type DesignMode = 'design' | 'deployment';
export interface AsBuiltCapture { kind: 'asset' | 'cable'; id: string; code: string; points: [number, number][] }
export type CommentTarget = { kind: 'asset' | 'cable'; id: string; code: string } | { kind: 'point'; lng: number; lat: number };
export type DesignView = { mode: 'version'; no: number } | { mode: 'compare'; from: number; to: number } | null;

interface DesignMapState {
  designId:     string | null;
  hiddenInputs: DesignInputLayerKey[];
  drawer:       DesignDrawer;
  drawing:      boolean;
  focusIssue:   DesignIssue | null;
  open:         (designId: string) => void;
  toggleInput:  (key: DesignInputLayerKey) => void;
  setDrawer:    (drawer: DesignDrawer) => void;
  setDrawing:   (drawing: boolean) => void;
  setFocusIssue: (issue: DesignIssue | null) => void;
  manual:       boolean;
  setManual:    (on: boolean) => void;
  edit:         EditState;
  note:         { tone: 'error' | 'ok'; text: string } | null;
  setNote:      (note: DesignMapState['note']) => void;
  runner:       ((op: DesignOperationBody) => void) | null;
  setRunner:    (run: DesignMapState['runner']) => void;
  send:         (event: EditEvent) => Step;
  change:       { seq: number; label: string; delta: DesignDelta; rerouted: DesignRerouted[] } | null;
  view:         DesignView;
  setView:      (view: DesignView) => void;
  historyOf:    { id: string; code: string } | null;
  setHistoryOf: (h: DesignMapState['historyOf']) => void;
  commentPick:   boolean;
  commentTarget: CommentTarget | null;
  setCommentPick:   (on: boolean) => void;
  setCommentTarget: (t: CommentTarget | null) => void;
  setChange:    (change: DesignMapState['change']) => void;
  mode:         DesignMode;
  setMode:      (mode: DesignMode) => void;
  asbuilt:      AsBuiltCapture | null;
  setAsBuilt:   (a: AsBuiltCapture | null) => void;
  addAsBuiltPoint: (p: [number, number]) => void;
}

const FRESH = {
  hiddenInputs: [] as DesignInputLayerKey[], drawer: null as DesignDrawer, drawing: false, focusIssue: null,
  manual: false, edit: INITIAL, note: null, change: null, view: null as DesignView,
  historyOf: null as DesignMapState['historyOf'],
  commentPick: false, commentTarget: null as CommentTarget | null,
  mode: 'design' as DesignMode, asbuilt: null as AsBuiltCapture | null,
};

export const useDesignMapStore = create<DesignMapState>((set, get) => ({
  designId: null,
  ...FRESH,
  open: designId => { if (get().designId !== designId) set({ designId, ...FRESH }); },
  toggleInput: key => set(s => ({
    hiddenInputs: s.hiddenInputs.includes(key) ? s.hiddenInputs.filter(k => k !== key) : [...s.hiddenInputs, key],
  })),
  // One drawer at a time; leaving validation drops the focused issue
  setDrawer: drawer => set(s => ({ drawer, focusIssue: drawer === 'validation' ? s.focusIssue : null })),
  setDrawing: drawing => set({ drawing }),
  setFocusIssue: focusIssue => set({ focusIssue }),
  setManual: manual => set({ manual, edit: INITIAL, note: null, drawing: false, ...(manual ? { view: null } : {}) }),
  setNote: note => set({ note }),
  change: null,
  setChange: change => set({ change }),
  view: null,
  // Looking back switches the editing tools off
  setView: view => set(view ? { view, manual: false, edit: INITIAL, drawing: false, focusIssue: null } : { view }),
  historyOf: null,
  setHistoryOf: historyOf => set({ historyOf }),
  commentPick: false,
  commentTarget: null,
  setCommentPick: commentPick => set({ commentPick }),
  setCommentTarget: commentTarget => set({ commentTarget, commentPick: false }),
  runner: null,
  setRunner: runner => set({ runner }),
  mode: 'design',
  // Deployment mode: the rows are no longer edited, they are built
  setMode: mode => set(mode === 'deployment'
    ? { mode, drawer: 'deployment', manual: false, edit: INITIAL, drawing: false, view: null, focusIssue: null }
    : { mode, drawer: null, asbuilt: null }),
  asbuilt: null,
  setAsBuilt: asbuilt => set({ asbuilt }),
  addAsBuiltPoint: p => {
    const a = get().asbuilt;
    if (!a) return;
    set({ asbuilt: { ...a, points: a.kind === 'asset' ? [p] : [...a.points, p] } });
  },
  send: event => {
    const step = reduce(get().edit, event);
    const fresh = event.type === 'TOOL' || event.type === 'CANCEL';
    set({
      edit: step.state,
      note: step.error ? { tone: 'error', text: step.error } : fresh ? null : get().note,
      // Tools from the right-click menu bring the palette out
      ...(event.type === 'TOOL' && event.tool !== 'select' ? { manual: true, drawing: false } : {}),
    });
    if (step.op) get().runner?.(step.op);
    return step;
  },
}));
