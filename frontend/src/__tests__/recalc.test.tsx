// ============================================================
// Network GIS Phase 7 — local recalculation on the client: the working
// set patched from an edit's delta (no reload), the delta in words, the
// summary strip's pulse and ribbon, and the rerouted cables in the tool
// card. The recalculation itself runs on the server (test_recalc_db.py).
// ============================================================

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, renderHook, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import type { DesignDelta, DesignOpResult, DesignSummary } from '@shared';

vi.mock('../api/design.api', () => ({
  designApi: { operate: vi.fn(), operations: vi.fn(), undo: vi.fn(), redo: vi.fn(), features: vi.fn() },
}));

import { designApi } from '../api/design.api';
import { designKeys, patchFeatures, useOperate } from '../features/network-map/design/designQueries';
import { describeDelta } from '../features/network-map/design/designFormat';
import { SummaryStrip } from '../features/network-map/design/DesignToolbar';
import { ManualToolbar } from '../features/network-map/design/ManualToolbar';
import { useDesignMapStore } from '../features/network-map/design/designStore';
import { INITIAL } from '../features/network-map/design/editMachine';

const api = vi.mocked(designApi);

const feat = (id: string, kind: 'asset' | 'cable', x = 3.39): GeoJSON.Feature => ({
  type: 'Feature', geometry: { type: 'Point', coordinates: [x, 6.63] }, properties: { id, kind },
});

const DELTA: DesignDelta = {
  boq: [
    { item: 'Box to box cable', code: 'BOX_TO_BOX', unit: 'm', group: 'Cable', before: 97, after: 309.5, change: 212.5 },
    { item: 'Drop cable', code: 'DROP', unit: 'm', group: 'Cable', before: 24, after: 336.2, change: 312.2 },
  ],
  issues: { new: [1, 2, 3].map(() => ({ severity: 'ERROR', code: 'DROP_TOO_LONG', message: 'long' })), resolved: [] },
  features: [feat('fat1', 'asset', 3.3927)],
  removed: { assets: [], cables: ['gone'] },
};
const SUMMARY: DesignSummary = { homepasses: 96, customers: 120, fdt: 1, fat: 2, splitters: 0, closures: 0, poles: 0,
  cable_km: 0.65, errors: 3, warnings: 0, validated_at: null };

beforeEach(() => {
  vi.clearAllMocks();
  useDesignMapStore.setState({ designId: 'd1', manual: true, edit: INITIAL, note: null, runner: null, change: null });
});

describe('patching the working set from a delta', () => {
  it('replaces changed features and drops removed ones, keeping the rest', () => {
    const old: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [feat('fat1', 'asset'), feat('gone', 'cable'), feat('keep', 'cable')] };
    const out = patchFeatures(old, DELTA)!;
    expect(out.features.map(f => f.properties!.id).sort()).toEqual(['fat1', 'keep']);
    expect((out.features.find(f => f.properties!.id === 'fat1')!.geometry as GeoJSON.Point).coordinates[0]).toBe(3.3927);
    expect(patchFeatures(undefined, DELTA)).toBeUndefined();
  });

  it('an edit patches the cached map without refetching it', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    qc.setQueryData(designKeys.features('d1'), { type: 'FeatureCollection', features: [feat('fat1', 'asset'), feat('gone', 'cable')] });
    const res: DesignOpResult = {
      operation: { seq: 9, op: 'MOVE_ASSET', label: 'Move FAT-0014', rerouted: [] },
      history: { can_undo: true, can_redo: false, undo_label: 'Move FAT-0014', redo_label: null, applied: 9 },
      summary: SUMMARY, validation: { errors: 3, warnings: 0, info: 0 }, delta: DELTA,
    };
    api.operate.mockResolvedValue(res);
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
    const { result } = renderHook(() => useOperate('d1'), { wrapper });
    result.current.mutate({ op: 'MOVE_ASSET', id: 'fat1', lng: 3.3927, lat: 6.63 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const fc = qc.getQueryData<GeoJSON.FeatureCollection>(designKeys.features('d1'))!;
    expect(fc.features.map(f => f.properties!.id)).toEqual(['fat1']);
    expect(api.features).not.toHaveBeenCalled();
    expect(qc.getQueryData(designKeys.summary('d1'))).toEqual(SUMMARY);
    expect(useDesignMapStore.getState().change?.label).toBe('Move FAT-0014');
  });
});

describe('showing what changed', () => {
  it('puts the delta in words', () => {
    expect(describeDelta(DELTA)).toEqual(['Box to box cable +213 m', 'Drop cable +312 m', '3 new issues']);
    expect(describeDelta({ ...DELTA, boq: [{ ...DELTA.boq[0], unit: 'each', item: 'FAT', change: -1 }], issues: { new: [], resolved: [DELTA.issues.new[0]] } }))
      .toEqual(['FAT −1', '1 resolved']);
  });

  it('pulses the changed stat and shows the ribbon', () => {
    render(<SummaryStrip summary={SUMMARY} boq={undefined} onIssues={() => {}} onBoq={() => {}}
      change={{ seq: 7, label: 'Move FAT-0014', delta: DELTA }} />);
    expect(screen.getByText('650 m').closest('dd')).toHaveAttribute('data-pulse', 'true');
    expect(screen.getByText('2').closest('dd')).not.toHaveAttribute('data-pulse');
    expect(screen.getByRole('status')).toHaveTextContent('Move FAT-0014 · Box to box cable +213 m · Drop cable +312 m · 3 new issues');
  });

  it('lists the recalculated cables in the tool card', () => {
    api.operations.mockResolvedValue({ can_undo: true, can_redo: false, undo_label: 'x', redo_label: null, applied: 1, operations: [] });
    useDesignMapStore.setState({ change: { seq: 1, label: 'Move FAT-0014', delta: DELTA, rerouted: [
      { id: 'c1', code: 'B2B-0001', category: 'BOX_TO_BOX', route_method: 'ROAD_GRAPH', before_m: 97, after_m: 309.5 },
      { id: 'c2', code: 'DRP-0001', category: 'DROP', route_method: 'MANUAL_GEOMETRY', before_m: 8, after_m: 104,
        note: 'no road route from the new spot; ends moved, marked hand-drawn' },
    ] } });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><ManualToolbar designId="d1" busy={false} /></QueryClientProvider>);
    expect(screen.getByText('Recalculated 2 cables:')).toBeInTheDocument();
    expect(screen.getByText('97 → 310 m')).toBeInTheDocument();
    expect(screen.getByText(/no road route from the new spot/)).toBeInTheDocument();
  });
});
