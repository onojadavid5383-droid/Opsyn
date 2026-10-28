// ============================================================
// Network GIS Phase 8 — versions, compare, restore and history on the
// client: the audit trail in words, the compare overlay's features, the
// Versions drawer (save, view, compare, restore with confirmation,
// history of the design or one asset) and the compare card.
// ============================================================

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import type { AuditEntry, Design, DesignCompare, DesignVersionInfo } from '@shared';

vi.mock('../api/design.api', () => ({
  designApi: {
    versions: vi.fn(), saveVersion: vi.fn(), versionFeatures: vi.fn(), compare: vi.fn(), restore: vi.fn(),
    history: vi.fn(), entityHistory: vi.fn(),
  },
}));

import { designApi } from '../api/design.api';
import { describeAudit } from '../features/network-map/design/designFormat';
import { compareFeatures } from '../features/network-map/design/compareFeatures';
import { useDesignMapStore } from '../features/network-map/design/designStore';
import { VersionsDrawer } from '../features/network-map/design/VersionsDrawer';
import { ViewCard } from '../features/network-map/design/ViewCard';
import { INITIAL } from '../features/network-map/design/editMachine';

const api = vi.mocked(designApi);

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const DESIGN = {
  id: 'd1', project_id: 'p1', project_name: 'P', name: 'Versions', description: null, status: 'MODIFIED',
  boundary: null, bbox: null, engine_config: {}, current_version: { id: 'v3', version_no: 3, label: null, creation_method: 'MANUAL', created_at: '' },
  input_counts: { road: 5, homepass: 6, pole: 0, building: 0, pickup: 0, existing_structure: 0 }, created_at: '', updated_at: '',
} as Design;

const v = (no: number, over: Partial<DesignVersionInfo> = {}): DesignVersionInfo => ({
  id: `v${no}`, version_no: no, label: null, creation_method: 'MANUAL', created_at: new Date().toISOString(), created_by: 'Ada',
  is_current: false, frozen: true, frozen_at: null, parent_version_id: null,
  counts: { FDT: 1, FAT: 2, cable_m: 312.4, inputs: 11, assets: 3, cables: 2 }, validation: { errors: 0 }, ...over,
});
const VERSIONS = [v(3, { is_current: true, frozen: false }), v(2, { label: 'Before replacing homepasses' }), v(1, { label: 'Hand sketch', creation_method: 'INITIAL' })];

const entry = (over: Partial<AuditEntry>): AuditEntry => ({
  id: Math.random().toString(), entity_type: 'asset', entity_id: 'a1', entity_code: 'FAT-0002', action: 'update', actor: 'Ada',
  occurred_at: '2026-09-27T10:00:00Z', changed_fields: [], old: null, new: null, source: 'network', ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  useDesignMapStore.setState({ designId: 'd1', view: null, historyOf: null, manual: false, edit: INITIAL, drawer: 'versions' });
});

describe('audit trail in words', () => {
  it('says what changed', () => {
    expect(describeAudit(entry({ action: 'create' }))).toEqual({ verb: 'Added', detail: '' });
    expect(describeAudit(entry({ changed_fields: ['name', 'capacity'], old: { name: null, capacity: 8 }, new: { name: 'Corner', capacity: 16 } })))
      .toEqual({ verb: 'Changed', detail: 'Name: – → Corner; Capacity: 8 → 16' });
    expect(describeAudit(entry({ action: 'move', changed_fields: ['geom'],
      old: { geom: { type: 'Point', coordinates: [3.43, 6.67] } }, new: { geom: { type: 'Point', coordinates: [3.4302, 6.67] } } })))
      .toEqual({ verb: 'Moved', detail: '22 m' });
    expect(describeAudit(entry({ action: 'move', changed_fields: ['geom', 'length_m'], old: { geom: { type: 'LineString' }, length_m: 97.2 },
      new: { geom: { type: 'LineString' }, length_m: 140 } }))).toEqual({ verb: 'Rerouted', detail: '97 → 140 m' });
    expect(describeAudit(entry({ changed_fields: ['attributes'], old: { attributes: { wing: 'A' } },
      new: { attributes: { wing: 'A', parent_fdt_code: 'FDT-0001' } } }))).toEqual({ verb: 'Changed', detail: 'parent fdt code: – → FDT-0001' });
    expect(describeAudit(entry({ action: 'create', entity_type: 'connection', entity_code: null }))).toEqual({ verb: 'Connected', detail: '' });
    expect(describeAudit(entry({ action: 'upload' })).verb).toBe('Uploaded inputs');
    // An older infrastructure-log entry: whole records, no field list
    expect(describeAudit(entry({ source: 'infrastructure', old: { name: 'A', capacity: 8, updated_at: 1 }, new: { name: 'B', capacity: 8, updated_at: 2 } })))
      .toEqual({ verb: 'Changed', detail: 'Name: A → B' });
    expect(describeAudit(entry({ action: 'version_saved', new: { version_no: 1, label: 'Hand sketch' } })))
      .toEqual({ verb: 'Saved a version', detail: 'Version 1 “Hand sketch”' });
  });
});

describe('compare overlay features', () => {
  it('gives each change its role, with a ghost and an arrow for a move', () => {
    const c: DesignCompare = {
      from: 1, to: 2, counts: { added: 1, removed: 1, moved: 1, changed: 1 },
      added: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [3.44, 6.67] }, properties: { id: 'n', asset_code: 'FAT-3' } }],
      removed: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [3.43, 6.67] }, properties: { id: 'o', asset_code: 'FAT-1' } }],
      moved: [{ kind: 'asset', code: 'FDT-1', type: 'FDT', id: 'f', from: [3.43, 6.67], to: [3.4302, 6.67], distance_m: 22.1 }],
      changed: [{ kind: 'cable', code: 'B-1', id: 'c', fields: ['geometry'], before: {}, after: {}, length_before_m: 97, length_after_m: 140,
        geometry_before: { type: 'LineString', coordinates: [[3.43, 6.67], [3.44, 6.67]] } }],
    };
    const fc = compareFeatures(c);
    expect(fc.features.map(f => f.properties!.role)).toEqual(['removed', 'added', 'ghost', 'arrow', 'head', 'old']);
    const head = fc.features.find(f => f.properties!.role === 'head')!;
    expect(head.properties!.bearing).toBeCloseTo(90, 0);                 // due east
    expect((head.geometry as GeoJSON.Point).coordinates).toEqual([3.4302, 6.67]);
  });
});

describe('VersionsDrawer', () => {
  it('lists versions with what they held; the current one has no actions', async () => {
    api.versions.mockResolvedValue(VERSIONS);
    wrap(<VersionsDrawer design={DESIGN} onClose={() => {}} />);
    const items = await screen.findAllByRole('listitem');
    expect(within(items[0]).getByText('Current')).toBeInTheDocument();
    expect(within(items[0]).queryByRole('button', { name: /Restore/ })).not.toBeInTheDocument();
    expect(within(items[2]).getByText('Hand sketch')).toBeInTheDocument();
    expect(within(items[2]).getByText('1 FDT · 2 FAT · 312 m · 11 inputs · 0 errors')).toBeInTheDocument();
  });

  it('saves the current state under a name', async () => {
    api.versions.mockResolvedValue(VERSIONS);
    api.saveVersion.mockResolvedValue({ saved: v(3, { label: 'Before splitting' }), versions: VERSIONS });
    wrap(<VersionsDrawer design={DESIGN} onClose={() => {}} />);
    await userEvent.type(screen.getByLabelText('Save the current state as a version'), 'Before splitting');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.saveVersion).toHaveBeenCalledWith('d1', 'Before splitting'));
    expect(await screen.findByText('Saved as version 3.')).toBeInTheDocument();
  });

  it('views, compares and restores (after confirming)', async () => {
    api.versions.mockResolvedValue(VERSIONS);
    api.restore.mockResolvedValue({ version_no: 4, restored_from: 1, kept_as: 3, inputs_restored: true, validation: { errors: 0, warnings: 0, info: 0 } });
    wrap(<VersionsDrawer design={DESIGN} onClose={() => {}} />);
    const items = await screen.findAllByRole('listitem');
    await userEvent.click(within(items[2]).getByRole('button', { name: 'View' }));
    expect(useDesignMapStore.getState().view).toEqual({ mode: 'version', no: 1 });
    await userEvent.click(within(items[2]).getByRole('button', { name: 'Compare with current' }));
    expect(useDesignMapStore.getState().view).toEqual({ mode: 'compare', from: 1, to: 3 });
    await userEvent.click(within(items[2]).getByRole('button', { name: 'Restore' }));
    expect(api.restore).not.toHaveBeenCalled();
    const dialog = screen.getByRole('alertdialog', { name: 'Restore version 1?' });
    expect(within(dialog).getByText(/kept as version 3/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Restore version 1' }));
    await waitFor(() => expect(api.restore).toHaveBeenCalledWith('d1', 1));
    expect(await screen.findByText(/Version 1 is back as version 4; the state before is version 3/)).toBeInTheDocument();
    expect(useDesignMapStore.getState().view).toBeNull();
  });

  it("shows the design's history, or one asset's", async () => {
    api.versions.mockResolvedValue(VERSIONS);
    api.history.mockResolvedValue([entry({ action: 'create', entity_code: 'FDT-0001' })]);
    api.entityHistory.mockResolvedValue([entry({ action: 'move', changed_fields: ['geom'],
      old: { geom: { type: 'Point', coordinates: [3.43, 6.67] } }, new: { geom: { type: 'Point', coordinates: [3.4302, 6.67] } } })]);
    const { unmount } = wrap(<VersionsDrawer design={DESIGN} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('tab', { name: /History/ }));
    expect(await screen.findByText('FDT-0001')).toBeInTheDocument();
    unmount();
    useDesignMapStore.setState({ historyOf: { id: 'a1', code: 'FAT-0002' } });
    wrap(<VersionsDrawer design={DESIGN} onClose={() => {}} />);
    expect(screen.getByRole('tab', { name: /History/ })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText(/22 m/)).toBeInTheDocument();
    await waitFor(() => expect(api.entityHistory).toHaveBeenCalledWith('a1'));
  });
});

describe('ViewCard', () => {
  it('keys the comparison and goes to a moved device', async () => {
    const onGo = vi.fn();
    const c = { from: 1, to: 3, counts: { added: 0, removed: 2, moved: 1, changed: 0 }, added: [], removed: [], changed: [],
      moved: [{ kind: 'asset', code: 'FDT-1', type: 'FDT', id: 'f', from: [3.43, 6.67], to: [3.4302, 6.67], distance_m: 22.1 }] } as DesignCompare;
    render(<ViewCard view={{ mode: 'compare', from: 1, to: 3 }} label={null} compare={c} loading={false} error={false} canRestore
      onBack={() => {}} onCompare={() => {}} onRestore={() => {}} onGo={onGo} />);
    expect(screen.getByText('Version 1 → version 3')).toBeInTheDocument();
    expect(screen.getByText('2 removed')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /FDT-1 moved 22 m/ }));
    expect(onGo).toHaveBeenCalledWith(3.4302, 6.67);
  });

  it('says a version is read-only', () => {
    render(<ViewCard view={{ mode: 'version', no: 1 }} label="Hand sketch" compare={undefined} loading={false} error={false}
      canRestore={false} onBack={() => {}} onCompare={() => {}} onRestore={() => {}} onGo={() => {}} />);
    expect(screen.getByText('read-only')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Restore/ })).not.toBeInTheDocument();
  });
});
