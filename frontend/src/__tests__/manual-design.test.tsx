// ============================================================
// Network GIS Phase 6 — manual design UI: the tools' state machine (every
// tool's clicks → the operation it sends), what a click resolves to, the
// store's runner hand-off, and the palette (keyboard shortcuts, undo/redo
// on the server). Map interaction itself is checked in a browser.
// ============================================================

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';

vi.mock('../api/design.api', () => ({
  designApi: { operations: vi.fn(), undo: vi.fn(), redo: vi.fn(), operate: vi.fn(), snap: vi.fn() },
}));

import { designApi } from '../api/design.api';
import {
  INITIAL, hint, pathLength, reduce, snapTargets, wantFor, type EditState, type EditTarget,
} from '../features/network-map/design/editMachine';
import { useDesignMapStore } from '../features/network-map/design/designStore';
import { ManualToolbar } from '../features/network-map/design/ManualToolbar';

const api = vi.mocked(designApi);

const FDT: EditTarget = { kind: 'asset', id: 'fdt1', code: 'FDT-0001', assetType: 'FDT', lng: 3.39, lat: 6.63 };
const FAT: EditTarget = { kind: 'asset', id: 'fat1', code: 'FAT-0001', assetType: 'FAT', lng: 3.391, lat: 6.631 };
const LIVE: EditTarget = { ...FDT, id: 'olt', code: 'OLT-1', assetType: 'OLT', live: true };
const CABLE: EditTarget = { kind: 'cable', id: 'c1', code: 'B2B-0001', category: 'BOX_TO_BOX', lng: 3.3905, lat: 6.6305 };
const SPOT: EditTarget = { kind: 'point', lng: 3.392, lat: 6.632 };

function run(state: EditState, ...clicks: EditTarget[]) {
  let s = state;
  let last = reduce(s, { type: 'CANCEL' });
  for (const t of clicks) {
    last = reduce(s, { type: 'CLICK', target: t });
    s = last.state;
  }
  return last;
}
const tool = (t: EditState['tool'], subtype?: string | null) => reduce(INITIAL, { type: 'TOOL', tool: t, subtype }).state;

describe('edit state machine', () => {
  it('adds a device where clicked, not on top of another', () => {
    expect(run(tool('add', 'FDT'), SPOT).op).toEqual({ op: 'ADD_ASSET', asset_type: 'FDT', lng: 3.392, lat: 6.632 });
    expect(run(tool('add'), FAT).error).toMatch(/already there/);
  });

  it('moves in two clicks and stays on for the next', () => {
    const s1 = reduce(tool('move'), { type: 'CLICK', target: FAT });
    expect(s1.op).toBeUndefined();
    const s2 = reduce(s1.state, { type: 'CLICK', target: SPOT });
    expect(s2.op).toEqual({ op: 'MOVE_ASSET', id: 'fat1', lng: 3.392, lat: 6.632 });
    expect(reduce(s2.state, { type: 'DONE' }).state).toMatchObject({ tool: 'move', picks: [] });
    expect(run(tool('move'), LIVE).error).toMatch(/device of this design/);
  });

  it('draws cables between devices and points; drops go straight', () => {
    expect(run(tool('cable'), FDT, FAT).op).toEqual({
      op: 'DRAW_CABLE', cable_category: 'BOX_TO_BOX', route: 'road', from: { asset_id: 'fdt1' }, to: { asset_id: 'fat1' },
    });
    const drop = tool('cable', 'DROP');
    expect(drop.route).toBe('straight');
    expect(run(drop, FAT, SPOT).op).toMatchObject({ cable_category: 'DROP', route: 'straight', to: { lng: 3.392, lat: 6.632 } });
    expect(run(tool('cable'), FDT, FDT).error).toMatch(/two different ends/);
    expect(run(tool('cable'), CABLE).error).toMatch(/not on a cable/);
    const straight = reduce(tool('cable'), { type: 'ROUTE', route: 'straight' }).state;
    expect(run(straight, LIVE, FAT).op).toMatchObject({ route: 'straight', from: { asset_id: 'olt' } });
  });

  it('deletes devices and cables', () => {
    expect(run(tool('delete'), FAT).op).toEqual({ op: 'DELETE_ASSET', id: 'fat1' });
    expect(run(tool('delete'), CABLE).op).toEqual({ op: 'DELETE_CABLE', id: 'c1' });
    expect(run(tool('delete'), SPOT).error).toBeTruthy();
  });

  it('connects a feeder to a design device', () => {
    expect(run(tool('connect'), LIVE, FAT).op).toEqual({ op: 'CONNECT', source_id: 'olt', dest_id: 'fat1', connection_type: 'FEED' });
    expect(run(tool('connect'), FAT, LIVE).error).toMatch(/belong to this design/);
  });

  it('splits, with or without a closure at the cut', () => {
    expect(run(tool('split'), CABLE).op).toEqual({ op: 'SPLIT_CABLE', id: 'c1', lng: 3.3905, lat: 6.6305 });
    expect(run(tool('split', 'CLOSURE'), CABLE).op).toMatchObject({ insert_asset_type: 'CLOSURE' });
    expect(run(tool('split'), FAT).error).toBeTruthy();
  });

  it('extends from a cable to a device or spot', () => {
    expect(run(tool('extend'), CABLE, FAT).op).toEqual({ op: 'EXTEND_CABLE', id: 'c1', to: { asset_id: 'fat1' }, route: 'road' });
    expect(run(tool('extend'), FAT).error).toMatch(/cable to extend/);
  });

  it('redraws a line point by point and finishes with at least two', () => {
    let s = run(tool('redraw'), CABLE, SPOT).state;
    expect(reduce(s, { type: 'FINISH' }).error).toMatch(/at least two/);
    s = reduce(s, { type: 'CLICK', target: { kind: 'point', lng: 3.393, lat: 6.633 } }).state;
    expect(hint(s)).toMatch(/2 points/);
    expect(reduce(s, { type: 'FINISH' }).op).toEqual({ op: 'EDIT_CABLE_GEOM', id: 'c1', coordinates: [[3.392, 6.632], [3.393, 6.633]] });
  });

  it('measures without sending anything; Esc steps back, then to Select', () => {
    const s = run(tool('measure'), SPOT, { kind: 'point', lng: 3.393, lat: 6.632 });
    expect(s.op).toBeUndefined();
    expect(pathLength(s.state.points)).toBeCloseTo(110.45, 1);          // 0.001° of longitude at 6.6°N
    const back = reduce(s.state, { type: 'CANCEL' }).state;
    expect(back).toMatchObject({ tool: 'measure', points: [] });
    expect(reduce(back, { type: 'CANCEL' }).state.tool).toBe('select');
  });

  it('knows what a click should mean', () => {
    expect(wantFor(tool('split'))).toEqual(['cable']);
    expect(wantFor(run(tool('extend'), CABLE).state)).toEqual(['point']);
    expect(snapTargets(tool('add'))).toEqual(['pole_input', 'road', 'boundary']);
    expect(snapTargets(tool('cable', 'DROP'))).toContain('homepass');
    expect(snapTargets(tool('measure'))).toBeNull();
  });
});

describe('design store edit hand-off', () => {
  beforeEach(() => useDesignMapStore.setState({ designId: 'd1', manual: false, edit: INITIAL, note: null, runner: null }));

  it('gives a finished operation to the runner and opens the palette from a menu tool', () => {
    const runner = vi.fn();
    useDesignMapStore.getState().setRunner(runner);
    useDesignMapStore.getState().send({ type: 'TOOL', tool: 'delete' });
    expect(useDesignMapStore.getState().manual).toBe(true);
    useDesignMapStore.getState().send({ type: 'CLICK', target: FAT });
    expect(runner).toHaveBeenCalledWith({ op: 'DELETE_ASSET', id: 'fat1' });
  });

  it('shows a refusal as a note', () => {
    useDesignMapStore.getState().send({ type: 'TOOL', tool: 'split' });
    useDesignMapStore.getState().send({ type: 'CLICK', target: FAT });
    expect(useDesignMapStore.getState().note).toMatchObject({ tone: 'error' });
  });
});

describe('ManualToolbar', () => {
  function wrap(ui: ReactNode) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
  }
  beforeEach(() => {
    vi.clearAllMocks();
    useDesignMapStore.setState({ designId: 'd1', manual: true, edit: INITIAL, note: null, runner: null });
  });

  it('switches tools from the rail and the keyboard', async () => {
    api.operations.mockResolvedValue({ can_undo: false, can_redo: false, undo_label: null, redo_label: null, applied: 0, operations: [] });
    wrap(<ManualToolbar designId="d1" busy={false} />);
    await userEvent.click(screen.getByRole('button', { name: 'Draw a cable' }));
    expect(screen.getByRole('radio', { name: 'Box to box' })).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(screen.getByRole('radio', { name: 'Drop' }));
    expect(screen.getByLabelText('Follow the roads')).not.toBeChecked();
    await userEvent.keyboard('m');
    expect(screen.getByRole('button', { name: 'Move' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Click the device to move.')).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(useDesignMapStore.getState().edit.tool).toBe('select');
  });

  it('undoes and redoes on the server, labelled with what they undo', async () => {
    api.operations.mockResolvedValue({ can_undo: true, can_redo: true, undo_label: 'Add FAT-0003', redo_label: 'Move FAT-0001',
      applied: 3, operations: [] });
    const res = { operation: { seq: 3, op: 'ADD_ASSET', label: 'Undid: Add FAT-0003' }, history: { can_undo: true, can_redo: true,
      undo_label: 'x', redo_label: 'y', applied: 2 }, summary: {}, validation: { errors: 0, warnings: 0, info: 0 },
      delta: { boq: [], issues: { new: [], resolved: [] }, features: [], removed: { assets: ['fat3'], cables: [] } } };
    api.undo.mockResolvedValue(res as never);
    api.redo.mockResolvedValue(res as never);
    wrap(<ManualToolbar designId="d1" busy={false} />);
    const undo = await screen.findByRole('button', { name: 'Undo' });
    await waitFor(() => expect(undo).toBeEnabled());
    expect(undo).toHaveAttribute('title', 'Undo: Add FAT-0003 (Ctrl+Z)');
    await userEvent.click(undo);
    await waitFor(() => expect(api.undo).toHaveBeenCalledWith('d1'));
    await userEvent.keyboard('{Control>}{Shift>}z{/Shift}{/Control}');
    await waitFor(() => expect(api.redo).toHaveBeenCalledWith('d1'));
  });
});
