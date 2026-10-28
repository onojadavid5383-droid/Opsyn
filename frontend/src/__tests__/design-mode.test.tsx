// ============================================================
// Network GIS Phase 4 — design mode UI.
// Pure helpers (boundary rules, issue framing, status wording) directly;
// the project tab, design panel, drawers, toolbar and strip against a
// mocked design API. The map layers and the draw tool need WebGL and are
// checked in a real browser (Playwright + Edge screenshots).
// ============================================================

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import type { Design, DesignBoq, DesignInputLayer, DesignIssue, DesignSummary } from '@shared';

vi.mock('../api/design.api', () => ({
  designApi: {
    list: vi.fn(), create: vi.fn(), get: vi.fn(), update: vi.fn(), remove: vi.fn(), boundaryFromInputs: vi.fn(),
    inputs: vi.fn(), inputFeatures: vi.fn(), uploadInputs: vi.fn(), removeInputs: vi.fn(), features: vi.fn(),
    summary: vi.fn(), boq: vi.fn(), validate: vi.fn(), validation: vi.fn(), route: vi.fn(),
  },
}));

import { designApi } from '../api/design.api';
import {
  DESIGN_STATUS_LABEL, EDITABLE, INPUT_LAYERS, boundaryProblem, designHref, draftFeatures, formatKm,
  geometryBounds, groupIssues, isEditable, isPointBox,
} from '../features/network-map/design/designFormat';
import { useDesignMapStore } from '../features/network-map/design/designStore';
import { ProjectDesigns } from '../features/network-map/design/ProjectDesigns';
import { DesignPanel } from '../features/network-map/design/DesignPanel';
import { BoqDrawer, ValidationPanel } from '../features/network-map/design/DesignDrawers';
import { DesignToolbar, SummaryStrip } from '../features/network-map/design/DesignToolbar';

const api = vi.mocked(designApi);

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

const COUNTS = { road: 8, homepass: 0, pole: 0, building: 0, pickup: 0, existing_structure: 0 };

const DESIGN: Design = {
  id: 'd1', project_id: 'p1', project_name: 'Allen Avenue FTTH', name: 'Phase 1', description: null, status: 'DRAFT',
  boundary: null, bbox: [3.35, 6.598, 3.353, 6.601], engine_config: {},
  current_version: { id: 'v1', version_no: 1, label: null, creation_method: 'INITIAL', created_at: '2026-09-26T10:00:00Z' },
  input_counts: COUNTS, created_at: '2026-09-26T10:00:00Z', updated_at: '2026-09-26T10:00:00Z',
};

const INPUTS: DesignInputLayer[] = INPUT_LAYERS.map(l => ({
  layer_key: l.key, label: l.label, feature_count: COUNTS[l.key],
  last_upload: l.key === 'road' ? { filename: 'roads.geojson', uploaded_at: '2026-09-26T10:00:00Z', mode: 'replace', feature_count: 8 } : null,
}));

const issue = (over: Partial<DesignIssue>): DesignIssue => ({
  id: 'i', severity: 'WARNING', code: 'DROP_TOO_LONG', rule: null, message: 'm', asset_id: null, cable_id: null,
  geometry: null, metadata: {}, created_at: '2026-09-26T10:00:00Z', ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  useDesignMapStore.setState({ designId: null, hiddenInputs: [], drawer: null, drawing: false, focusIssue: null });
});

// ── Pure helpers ─────────────────────────────────────────────

describe('design format', () => {
  it('refuses boundaries that are not areas and accepts a simple one', () => {
    expect(boundaryProblem([[0, 0], [1, 0]])).toMatch(/three corners/);
    expect(boundaryProblem([[0, 0], [1, 1], [1, 0], [0, 1]])).toMatch(/cross/);          // bow tie
    expect(boundaryProblem([[0, 0], [1, 1], [2, 2]])).toMatch(/in a line/);
    expect(boundaryProblem([[0, 0], [1, 0], [1, 1], [0, 1]])).toBeNull();
  });

  it('draws the draft as corners, edges and, from three points, an area', () => {
    const one = draftFeatures([[0, 0]], [1, 1]);
    expect(one.features.map(f => f.properties!.role)).toEqual(['first', 'edge']);
    const three = draftFeatures([[0, 0], [1, 0]], [1, 1]);
    const area = three.features.find(f => f.properties!.role === 'area')!;
    expect((area.geometry as GeoJSON.Polygon).coordinates[0]).toEqual([[0, 0], [1, 0], [1, 1], [0, 0]]);
  });

  it('frames any issue geometry', () => {
    expect(geometryBounds({ coordinates: [3.3, 6.6] })).toEqual([3.3, 6.6, 3.3, 6.6]);
    expect(isPointBox([3.3, 6.6, 3.3, 6.6])).toBe(true);
    expect(geometryBounds({ coordinates: [[[1, 2], [3, 4]], [[0, 5], [2, 1]]] })).toEqual([0, 1, 3, 5]);
    expect(geometryBounds(null)).toBeNull();
  });

  it('groups issues errors first and leaves empty groups out', () => {
    const groups = groupIssues([issue({ id: 'a' }), issue({ id: 'b', severity: 'ERROR' })]);
    expect(groups.map(g => g.severity)).toEqual(['ERROR', 'WARNING']);
  });

  it('matches the server: content is frozen from review onwards', () => {
    // backend app/modules/design/models.py LOCKED_STATUSES
    const locked = ['VALIDATING', 'UNDER_REVIEW', 'APPROVED', 'SUPERSEDED', 'DEPLOYED'];
    for (const st of Object.keys(DESIGN_STATUS_LABEL)) expect(isEditable(st as never)).toBe(!locked.includes(st));
    expect(EDITABLE).toContain('REJECTED');
  });

  it('formats cable length and the design link', () => {
    expect(formatKm(0)).toBe('0 km');
    expect(formatKm(0.4567)).toBe('457 m');
    expect(formatKm(3.14159)).toBe('3.14 km');
    expect(designHref('d1')).toBe('/network?mode=design&design=d1');
  });
});

describe('design store', () => {
  it('starts fresh on another design and drops the focused issue with the drawer', () => {
    const st = useDesignMapStore.getState();
    st.open('d1');
    st.toggleInput('road');
    st.setDrawer('validation');
    st.setFocusIssue(issue({}));
    useDesignMapStore.getState().setDrawer('boq');
    expect(useDesignMapStore.getState().focusIssue).toBeNull();
    useDesignMapStore.getState().open('d1');
    expect(useDesignMapStore.getState().hiddenInputs).toEqual(['road']);        // same design: kept
    useDesignMapStore.getState().open('d2');
    expect(useDesignMapStore.getState()).toMatchObject({ designId: 'd2', hiddenInputs: [], drawer: null });
  });
});

// ── Project tab ──────────────────────────────────────────────

describe('ProjectDesigns', () => {
  it('lists designs with status, inputs and a map link', async () => {
    api.list.mockResolvedValue([DESIGN]);
    wrap(<ProjectDesigns projectId="p1" />);
    const link = await screen.findByRole('link', { name: 'Phase 1' });
    expect(link).toHaveAttribute('href', '/network?mode=design&design=d1');
    expect(screen.getByText('Draft')).toBeInTheDocument();
    expect(screen.getByText('8 road segments')).toBeInTheDocument();
  });

  it('creates a design by name', async () => {
    api.list.mockResolvedValue([]);
    api.create.mockResolvedValue(DESIGN);
    wrap(<ProjectDesigns projectId="p1" />);
    await userEvent.click(await screen.findByRole('button', { name: /New design/ }));
    await userEvent.type(screen.getByLabelText('Design name'), '  Phase 1 ');
    await userEvent.click(screen.getByRole('button', { name: 'Create design' }));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith('p1', { name: 'Phase 1' }));
  });
});

// ── Design panel ─────────────────────────────────────────────

describe('DesignPanel', () => {
  const file = new File(['{}'], 'hp.geojson', { type: 'application/geo+json' });

  it('shows the header and every input with its count', async () => {
    api.inputs.mockResolvedValue(INPUTS);
    wrap(<DesignPanel design={DESIGN} onHide={() => {}} onFit={() => {}} />);
    expect(screen.getByRole('heading', { name: 'Phase 1' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Allen Avenue FTTH/ })).toHaveAttribute('href', '/projects/p1');
    expect(screen.getByText('Version 1')).toBeInTheDocument();
    expect(await screen.findByText('roads.geojson')).toBeInTheDocument();
    expect(screen.getByLabelText('8 features')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Design' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('uploads into an empty layer straight away', async () => {
    api.inputs.mockResolvedValue(INPUTS);
    api.uploadInputs.mockResolvedValue({ status: 'saved', layer_key: 'homepass', feature_count: 6, errors: [], warnings: ['1 homepasses had no customer count and were counted as 1'], upload_id: 'u' });
    const { container } = wrap(<DesignPanel design={DESIGN} onHide={() => {}} onFit={() => {}} />);
    const inputs = container.querySelectorAll('input[type=file]');
    await userEvent.upload(inputs[1] as HTMLInputElement, file);                  // homepass row
    await waitFor(() => expect(api.uploadInputs).toHaveBeenCalledWith('d1', 'homepass', file, 'replace'));
    expect(await screen.findByText('Saved 6 features.')).toBeInTheDocument();
    expect(screen.getByText(/counted as 1/)).toBeInTheDocument();
  });

  it('asks whether to replace or add when the layer has features, and reports a rejected file', async () => {
    api.inputs.mockResolvedValue(INPUTS);
    api.uploadInputs.mockResolvedValue({ status: 'rejected', layer_key: 'road', feature_count: 0,
      errors: [{ row: 2, field: 'geometry', error: 'Roads must be LineString or MultiLineString (got Point)' }], warnings: [], upload_id: null });
    const { container } = wrap(<DesignPanel design={DESIGN} onHide={() => {}} onFit={() => {}} />);
    await userEvent.upload(container.querySelectorAll('input[type=file]')[0] as HTMLInputElement, file);
    const choice = screen.getByRole('group', { name: /What to do with hp.geojson/ });
    expect(api.uploadInputs).not.toHaveBeenCalled();
    await userEvent.click(within(choice).getByRole('button', { name: 'Add to them' }));
    await waitFor(() => expect(api.uploadInputs).toHaveBeenCalledWith('d1', 'road', file, 'append'));
    expect(await screen.findByText(/Nothing was saved: 1 problem/)).toBeInTheDocument();
    expect(screen.getByText(/Feature 2: Roads must be LineString/)).toBeInTheDocument();
  });

  it('removes a layer only after confirming', async () => {
    api.inputs.mockResolvedValue(INPUTS);
    api.removeInputs.mockResolvedValue({ removed: 8 });
    wrap(<DesignPanel design={DESIGN} onHide={() => {}} onFit={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: 'Remove roads' }));
    expect(api.removeInputs).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(api.removeInputs).toHaveBeenCalledWith('d1', 'road'));
  });

  it('switches drawing and takes the boundary from the inputs', async () => {
    api.inputs.mockResolvedValue(INPUTS);
    api.boundaryFromInputs.mockResolvedValue({ ...DESIGN, boundary: { type: 'MultiPolygon', coordinates: [] } });
    wrap(<DesignPanel design={DESIGN} onHide={() => {}} onFit={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /^Draw$/ }));
    expect(useDesignMapStore.getState().drawing).toBe(true);
    await userEvent.click(screen.getByRole('button', { name: /From inputs/ }));
    await waitFor(() => expect(api.boundaryFromInputs).toHaveBeenCalledWith('d1'));
  });

  it('offers no changes once the design is in review', async () => {
    api.inputs.mockResolvedValue(INPUTS);
    wrap(<DesignPanel design={{ ...DESIGN, status: 'UNDER_REVIEW' }} onHide={() => {}} onFit={() => {}} />);
    expect(screen.queryByRole('button', { name: /Upload/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Draw$/ })).not.toBeInTheDocument();
    expect(screen.getByText(/under review; its inputs can't be changed/)).toBeInTheDocument();
  });
});

// ── Drawers ──────────────────────────────────────────────────

describe('ValidationPanel', () => {
  const noop = () => {};
  it('lists issues by severity and shows one on the map', async () => {
    const onView = vi.fn();
    const err = issue({ id: 'e', severity: 'ERROR', code: 'FAT_OVER_CAPACITY', message: 'FAT-0003 serves 11 customers; the limit is 8',
      rule: 'MAX_CUSTOMERS_PER_FAT = 8', geometry: { type: 'Point', coordinates: [3.35, 6.6] } });
    const warn = issue({ id: 'w', message: 'No boundary drawn' });
    render(<ValidationPanel validation={{ issues: [warn, err], summary: { errors: 1, warnings: 1, info: 0 } }}
      loading={false} error={null} validating={false} validateError={null} validatedAt="2026-09-26T10:00:00Z"
      focusId={null} onValidate={noop} onView={onView} onClose={noop} />);
    const groups = screen.getAllByRole('region');
    expect(groups.map(g => g.getAttribute('aria-label'))).toEqual(['Errors', 'Warnings']);
    expect(within(groups[0]).getByText('MAX_CUSTOMERS_PER_FAT = 8', { exact: false })).toBeInTheDocument();
    expect(within(groups[1]).queryByRole('button', { name: /View on map/ })).not.toBeInTheDocument();   // no geometry
    await userEvent.click(within(groups[0]).getByRole('button', { name: /View on map/ }));
    expect(onView).toHaveBeenCalledWith(err);
  });

  it('says so when a checked design has no issues, and asks for a first check', () => {
    const props = { loading: false, error: null, validating: false, validateError: null, focusId: null,
      onValidate: noop, onView: noop, onClose: noop };
    const { rerender } = render(<ValidationPanel {...props} validation={{ issues: [], summary: { errors: 0, warnings: 0, info: 0 } }} validatedAt="2026-09-26T10:00:00Z" />);
    expect(screen.getByText(/passes every check/)).toBeInTheDocument();
    rerender(<ValidationPanel {...props} validation={{ issues: [], summary: { errors: 0, warnings: 0, info: 0 } }} validatedAt={null} />);
    expect(screen.queryByText(/passes every check/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Validate now' })).toBeInTheDocument();
  });
});

describe('BoqDrawer', () => {
  it('shows devices, cable runs and only the street columns the engine filled', () => {
    const boq: DesignBoq = {
      quantities: [
        { group: 'Devices', item: 'FAT', code: 'FAT', quantity: 3, unit: 'each' },
        { group: 'Cable', item: 'Distribution cable, 24 fibres', code: 'DISTRIBUTION', quantity: 412.36, unit: 'm', pieces: 3, fiber_count: 24 },
      ],
      streets: [{ street_name: 'Street 0', total_fat: 3, total_homepass: 6, total_poles: null }],
      street_boq_available: true, notes: ['No homepasses uploaded: the street BOQ counts no customers.'], engine_findings: [],
    };
    render(<BoqDrawer boq={boq} loading={false} error={null} onClose={() => {}} />);
    expect(screen.getByText('412.4 m')).toBeInTheDocument();
    expect(screen.getByText('3 runs')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Homepasses' })).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Poles' })).not.toBeInTheDocument();
    expect(screen.getByText(/counts no customers/)).toBeInTheDocument();
  });
});

// ── Toolbar and strip ────────────────────────────────────────

describe('DesignToolbar and SummaryStrip', () => {
  it('shows auto and manual design as equal entry points, both coming', async () => {
    const onDrawer = vi.fn();
    render(<DesignToolbar editable validating={false} drawer={null} issueCount={4} onValidate={() => {}} onDrawer={onDrawer} />);
    expect(screen.getByRole('button', { name: 'Auto design' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Manual design' })).toBeDisabled();
    expect(screen.getByText('Auto and manual design arrive next')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Issues/ }));
    expect(onDrawer).toHaveBeenCalledWith('validation');
  });

  it('enables a track once it is wired in', async () => {
    const onAuto = vi.fn();
    render(<DesignToolbar editable validating={false} drawer={null} issueCount={null} onValidate={() => {}} onDrawer={() => {}} onAutoDesign={onAuto} />);
    await userEvent.click(screen.getByRole('button', { name: 'Auto design' }));
    expect(onAuto).toHaveBeenCalled();
    expect(screen.getByText('Manual design arrives next')).toBeInTheDocument();
  });

  it('summarises the design and opens the drawers', async () => {
    const summary: DesignSummary = { homepasses: 7, customers: 16, fdt: 1, fat: 3, splitters: 0, closures: 1, poles: 2,
      cable_km: 1.2345, errors: 2, warnings: 1, validated_at: null };
    const onIssues = vi.fn();
    render(<SummaryStrip summary={summary} boq={undefined} onIssues={onIssues} onBoq={() => {}} />);
    expect(screen.getByText('1.23 km')).toBeInTheDocument();
    expect(screen.getByText('Not checked yet')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /2 errors/ }));
    expect(onIssues).toHaveBeenCalled();
  });
});
