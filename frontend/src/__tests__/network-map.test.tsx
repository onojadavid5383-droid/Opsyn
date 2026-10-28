// ============================================================
// Network GIS Phase 1 — /network map UI.
// jsdom has no WebGL, so MapLibre itself is never started here: the pure
// parts (symbology expressions, scale, store, tile URL) are tested
// directly, the panels against a mocked network API, and the tool rail
// against a stand-in map object. Real rendering is checked in a browser
// (Playwright + Edge screenshots).
// ============================================================

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import type {
  GisLayerRegistry, NetAsset, NetAssetConnections, NetAssetSummary, NetCable, NetCatalogue, NetFieldSpec, NetFibre, NetTrace,
} from '@shared';

vi.mock('../api/network.api', async (orig) => {
  const actual = await orig<typeof import('../api/network.api')>();
  return {
    ...actual,
    networkApi: {
      layers: vi.fn(), bounds: vi.fn(), search: vi.fn(), list: vi.fn(),
      get: vi.fn(), update: vi.fn(), syncUploaded: vi.fn(),
      catalogue: vi.fn(), cables: vi.fn(), getCable: vi.fn(), updateCable: vi.fn(),
      connections: vi.fn(), trace: vi.fn(), utilisation: vi.fn(), createConnection: vi.fn(), deleteConnection: vi.fn(),
      fibres: vi.fn(), setFibre: vi.fn(),
      uploadTypes: vi.fn(), uploadTemplate: vi.fn(),
    },
  };
});

// The inspector's History section (Network GIS Phase 8) reads the audit trail
vi.mock('../api/design.api', () => ({ designApi: { entityHistory: vi.fn().mockResolvedValue([]) } }));

import { networkApi, tileUrlTemplate, isApiUrl } from '../api/network.api';
import {
  ASSET_GLYPH, ASSET_TIER, ASSET_TYPES, CABLE_CATEGORIES, CABLE_STYLE, TIER_COLOR,
  assetIconExpr, cableCasingWidthExpr, cableWidth, iconName, iconVariant,
} from '../features/network-map/symbology';
import { formatLength, scaleFor } from '../features/network-map/mapMath';
import { useNetworkMapStore } from '../features/network-map/store';
import { markerSvg } from '../features/network-map/markerImages';
import { LayerPanel } from '../features/network-map/LayerPanel';
import { MapSearch } from '../features/network-map/MapSearch';
import { AssetInspector } from '../features/network-map/AssetInspector';
import { ToolRail } from '../features/network-map/ToolRail';
import { MapInstanceProvider, type MapCtx } from '../features/network-map/mapContext';
import { AttributeView } from '../features/network-map/AttributeFields';
import { formatField, humaniseOption, mergeDraft, toDraft } from '../features/network-map/attributeFormat';
import { NetworkRegister } from '../features/network-map/NetworkRegister';
import { TracePanel } from '../features/network-map/TracePanel';
import { FibresSection } from '../features/network-map/TopologySections';
import { MapContextMenu } from '../features/network-map/MapContextMenu';

const api = vi.mocked(networkApi);

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const REGISTRY: GisLayerRegistry = {
  revision: 'abc123',
  tiles: {
    group: 'network', url_template: '/gis/tiles/network/{z}/{x}/{y}.mvt',
    min_zoom: 0, max_zoom: 20, source_layers: { assets: 'assets', cables: 'cables' },
  },
  contained_min_zoom: 18,
  live_states: ['ACTIVE', 'FAULTY', 'VERIFIED'],
  lifecycle_states: ['ACTIVE'],
  groups: [
    { key: 'core', label: 'Core and active equipment', kind: 'asset', layers: [
      { key: 'OLT', label: 'OLT', kind: 'asset', tier: 'core', min_zoom: 0, count: 2, source_layer: 'assets' },
      { key: 'POP', label: 'POP', kind: 'asset', tier: 'core', min_zoom: 0, count: 0, source_layer: 'assets' },
    ] },
    { key: 'distribution', label: 'Distribution', kind: 'asset', layers: [
      { key: 'SPLITTER', label: 'Splitter', kind: 'asset', tier: 'distribution', min_zoom: 12, count: 4, source_layer: 'assets' },
    ] },
    { key: 'cables', label: 'Cables', kind: 'cable', layers: [
      { key: 'FEEDER', label: 'Feeder', kind: 'cable', tier: 'cables', min_zoom: 0, count: 1, source_layer: 'cables' },
    ] },
  ],
};

beforeEach(() => {
  localStorage.clear();
  useNetworkMapStore.setState({ hidden: [], basemap: 'light', panelOpen: true, selectedId: null, inspectorOpen: false });
  vi.clearAllMocks();
});

// ── Symbology ────────────────────────────────────────────────

describe('symbology', () => {
  it('gives every asset type a tier, a glyph and three marker images', () => {
    for (const t of ASSET_TYPES) {
      expect(ASSET_TIER[t]).toBeDefined();
      expect(ASSET_GLYPH[t]).toBeDefined();
      for (const v of ['ok', 'fault', 'verify'] as const) {
        const svg = markerSvg(t, v);
        expect(svg).toContain(TIER_COLOR[ASSET_TIER[t]]);
        expect(svg).toMatch(/^<svg /);
      }
    }
    expect(iconName('FAT', 'fault')).toBe('net-FAT-fault');
  });

  it('marks faults with a badge as well as colour', () => {
    const ok = markerSvg('OLT', 'ok');
    const fault = markerSvg('OLT', 'fault');
    expect(fault.length).toBeGreaterThan(ok.length);
    expect(fault).toContain('<rect');                    // the "!" of the badge
    expect(markerSvg('OLT', 'verify')).toContain('stroke-dasharray');
  });

  it('maps lifecycle to marker variants', () => {
    expect(iconVariant('FAULTY')).toBe('fault');
    expect(iconVariant('VERIFIED')).toBe('verify');
    expect(iconVariant('ACTIVE')).toBe('ok');
    // the style expression uses the same naming as iconName()
    expect(JSON.stringify(assetIconExpr)).toContain('"net-"');
  });

  it('keeps zoom interpolation at the top level of every cable width', () => {
    for (const expr of [cableWidth(), cableWidth(0.6), cableWidth(1, 8), cableCasingWidthExpr]) {
      expect((expr as unknown[])[0]).toBe('interpolate');
      expect((expr as unknown[])[2]).toEqual(['zoom']);
      expect(JSON.stringify((expr as unknown[]).slice(3))).not.toContain('"zoom"');
    }
  });

  it('styles every cable category', () => {
    for (const c of CABLE_CATEGORIES) expect(CABLE_STYLE[c].width).toBeGreaterThan(0);
  });
});

// ── Pure helpers ─────────────────────────────────────────────

describe('map maths', () => {
  it('picks a round scale that fits', () => {
    const z16 = scaleFor(6.6, 16);
    expect(z16.label).toMatch(/^(1|2|5)0* m$/);
    expect(z16.px).toBeLessThanOrEqual(110);
    expect(scaleFor(6.6, 8).label).toMatch(/km$/);
  });

  it('formats cable lengths', () => {
    expect(formatLength(342.4)).toBe('342 m');
    expect(formatLength(1520)).toBe('1.52 km');
    expect(formatLength(null)).toBe('Unknown');
  });

  it('builds a tile URL with literal placeholders and the revision', () => {
    const url = tileUrlTemplate(REGISTRY);
    expect(url).toMatch(/\/gis\/tiles\/network\/\{z\}\/\{x\}\/\{y\}\.mvt\?rev=abc123$/);
    expect(isApiUrl(url)).toBe(true);
    expect(isApiUrl('https://tile.openstreetmap.org/1/0/0.png')).toBe(false);
  });
});

// ── Store ────────────────────────────────────────────────────

describe('network map store', () => {
  it('toggles and remembers layers', () => {
    useNetworkMapStore.getState().toggleLayer('OLT');
    expect(useNetworkMapStore.getState().hidden).toEqual(['OLT']);
    expect(JSON.parse(localStorage.getItem('opsyn-network-map')!).hidden).toEqual(['OLT']);
    useNetworkMapStore.getState().setLayers(['OLT', 'POP'], false);
    expect(useNetworkMapStore.getState().hidden.sort()).toEqual(['OLT', 'POP']);
    useNetworkMapStore.getState().setLayers(['OLT', 'POP'], true);
    expect(useNetworkMapStore.getState().hidden).toEqual([]);
  });

  it('keeps an open inspector on the new selection and closes it on clear', () => {
    const st = useNetworkMapStore.getState();
    st.openInspector('a');
    st.select('b');
    expect(useNetworkMapStore.getState()).toMatchObject({ selectedId: 'b', inspectorOpen: true });
    useNetworkMapStore.getState().select(null);
    expect(useNetworkMapStore.getState()).toMatchObject({ selectedId: null, inspectorOpen: false });
  });
});

// ── Layer panel ──────────────────────────────────────────────

describe('LayerPanel', () => {
  it('lists layers with live counts and a zoom hint', () => {
    wrap(<LayerPanel registry={REGISTRY} loading={false} error={false} zoom={10} onHide={vi.fn()} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Network map' })).toBeInTheDocument();
    expect(screen.getByText('6 assets and 1 cables in service')).toBeInTheDocument();
    const dist = screen.getByRole('region', { name: 'Distribution' });
    expect(within(dist).getByText('Zoom in to 12 to see')).toBeInTheDocument();
    expect(within(dist).getByLabelText('4 in service')).toBeInTheDocument();
  });

  it('folds types with nothing in service behind a toggle', async () => {
    const user = userEvent.setup();
    wrap(<LayerPanel registry={REGISTRY} loading={false} error={false} zoom={14} onHide={vi.fn()} />);
    const core = screen.getByRole('region', { name: 'Core and active equipment' });
    expect(within(core).queryByText('POP')).not.toBeInTheDocument();
    await user.click(within(core).getByRole('button', { name: 'Show 1 type' }));
    expect(within(core).getByText('POP')).toBeInTheDocument();
    expect(within(core).getByRole('button', { name: 'Hide types with nothing in service' })).toHaveAttribute('aria-expanded', 'true');
  });

  it('switches a layer and a whole group off', async () => {
    const user = userEvent.setup();
    wrap(<LayerPanel registry={REGISTRY} loading={false} error={false} zoom={14} onHide={vi.fn()} />);
    await user.click(screen.getByRole('checkbox', { name: /Splitter/ }));
    expect(useNetworkMapStore.getState().hidden).toEqual(['SPLITTER']);
    await user.click(screen.getByRole('checkbox', { name: 'Core and active equipment' }));
    expect(useNetworkMapStore.getState().hidden.sort()).toEqual(['OLT', 'POP', 'SPLITTER']);
  });

  it('syncs uploaded assets and reports the result', async () => {
    api.syncUploaded.mockResolvedValue({ mirrored: { olts: 2, cabinets: 3, splitter_boxes: 4 }, skipped: [] });
    const user = userEvent.setup();
    wrap(<LayerPanel registry={REGISTRY} loading={false} error={false} zoom={14} onHide={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Sync uploads' }));
    expect(await screen.findByText('Synced 9 uploaded assets.')).toBeInTheDocument();
  });
});

// ── Search ───────────────────────────────────────────────────

const OLT: NetAssetSummary = {
  id: '11111111-1111-1111-1111-111111111111', asset_code: 'OLT-IKJ-01', asset_type: 'OLT',
  name: 'Allen POP', lifecycle_status: 'ACTIVE', lng: 3.353, lat: 6.601,
};

describe('MapSearch', () => {
  it('searches by the chosen field and flies to the chosen result', async () => {
    api.search.mockResolvedValue([OLT]);
    const onChoose = vi.fn();
    const user = userEvent.setup();
    wrap(<MapSearch typeLabel={t => t} onChoose={onChoose} />);
    await user.selectOptions(screen.getByLabelText('Search by'), 'code');
    await user.type(screen.getByRole('combobox', { name: 'Find an asset' }), 'OLT-IKJ');
    const option = await screen.findByRole('option', { name: /OLT-IKJ-01/ });
    expect(api.search).toHaveBeenLastCalledWith('OLT-IKJ', 'code', undefined);
    expect(option).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{Enter}');
    expect(onChoose).toHaveBeenCalledWith(OLT);
  });

  it('explains an empty result', async () => {
    api.search.mockResolvedValue([]);
    const user = userEvent.setup();
    wrap(<MapSearch typeLabel={t => t} onChoose={vi.fn()} />);
    await user.type(screen.getByRole('combobox', { name: 'Find an asset' }), 'ZZZ');
    expect(await screen.findByText(/No asset in service matches "ZZZ"/)).toBeInTheDocument();
  });
});

// ── Inspector ────────────────────────────────────────────────

const ASSET: NetAsset = {
  id: OLT.id, asset_code: 'SPL-ALN-02', asset_type: 'SPLITTER', name: 'SPL-ALN-02', description: null,
  lifecycle_status: 'ACTIVE', creation_method: 'IMPORTED',
  geometry: { type: 'Point', coordinates: [3.3572, 6.6051] }, lng: 3.3572, lat: 6.6051,
  attributes: {
    split_ratio: '1:16', splitter_level: 'Second-Level',
    legacy_cabinet_asset_id: 'cab-id', legacy_cabinet_code: 'CAB-ALN-01',
  },
  capacity: 16, used_capacity: null, parent: null, children_count: 0,
  project_id: null, design_id: null, lineage_id: 'l', source_table: 'splitter_boxes',
  allowed_transitions: ['FAULTY', 'RETIRED'],
  created_at: '2026-09-25T10:00:00Z', updated_at: '2026-09-25T10:00:00Z',
};

const spec = (key: string, label: string, kind: NetFieldSpec['kind'], extra: Partial<NetFieldSpec> = {}): NetFieldSpec =>
  ({ key, label, kind, unit: null, options: [], min: null, help: null, ...extra });

const CATALOGUE = {
  tiers: [], lifecycle_states: ['ACTIVE', 'FAULTY', 'RETIRED'], live_states: ['ACTIVE'],
  transitions: {}, creation_methods: [], route_methods: [], installation_types: [],
  asset_types: [
    { code: 'SPLITTER', label: 'Splitter', tier: 'distribution', min_zoom: 12, code_prefix: 'SPL', code_example: 'SPL-0001',
      capacity_label: 'Output ports', attributes: [
        spec('split_ratio', 'Split ratio', 'enum', { options: ['1:8', '1:16'] }),
        spec('splitter_level', 'Level', 'enum', { options: ['First-Level', 'Second-Level'] }),
        spec('number_customer', 'Customers served', 'int', { min: 0 }),
      ] },
    { code: 'POLE', label: 'Pole', tier: 'civil', min_zoom: 13, code_prefix: 'POLE', code_example: 'POLE-0001',
      capacity_label: null, attributes: [
        spec('height_m', 'Height', 'number', { unit: 'm', min: 0 }),
        spec('material', 'Material', 'enum', { options: ['CONCRETE', 'CAST_IRON'] }),
        spec('existing', 'Existing structure', 'bool'),
      ] },
  ],
  cable_categories: [
    { code: 'DROP', label: 'Drop', min_zoom: 15, code_prefix: 'DRP', code_example: 'DRP-0001',
      attributes: [spec('cable_type', 'Cable type', 'enum', { options: ['FLAT_DROP', 'ADSS'] })] },
  ],
} as unknown as NetCatalogue;

const inspectorProps = {
  typeLabel: () => 'Splitter', cableLabel: () => 'Drop',
  onClose: vi.fn(), onZoomTo: vi.fn(), onFitBounds: vi.fn(), onGoTo: vi.fn(), onTrace: vi.fn(),
};

const CONNECTIONS: NetAssetConnections = {
  upstream: [{
    id: 'k1', connection_type: 'SPLIT', lifecycle_status: 'ACTIVE', derived_from: 'attr:parent_splitter',
    peer: { id: 'spl1', asset_code: 'SPL-ALN-01', asset_type: 'SPLITTER', name: null }, via_cable: null,
  }],
  downstream: [{
    id: 'k2', connection_type: 'DROP', lifecycle_status: 'ACTIVE', derived_from: null,
    peer: { id: 'onu1', asset_code: 'ONU-0001', asset_type: 'ONU', name: null },
    via_cable: { id: 'd1', asset_code: 'DRP-0001', cable_category: 'DROP', length_m: 42 },
  }],
};

describe('AssetInspector', () => {
  beforeEach(() => {
    api.catalogue.mockResolvedValue({ ...CATALOGUE, connection_types: ['FEED', 'SPLIT', 'DROP'] });
    api.connections.mockResolvedValue(CONNECTIONS);
    api.utilisation.mockResolvedValue({ capacity: 16, used: 1, available: 15, pct: 6.3, state: 'ok', basis: 'connections', capacity_label: 'Output ports' });
  });

  it('shows the authoritative record, typed details, capacity and connections', async () => {
    api.get.mockResolvedValue(ASSET);
    const onGoTo = vi.fn();
    const onTrace = vi.fn();
    const user = userEvent.setup();
    wrap(<AssetInspector kind="asset" id={ASSET.id} {...inspectorProps} onGoTo={onGoTo} onTrace={onTrace} />);
    expect(await screen.findByRole('heading', { name: 'SPL-ALN-02' })).toBeInTheDocument();
    expect(screen.getByText('In service')).toBeInTheDocument();
    expect(await screen.findByText('Split ratio')).toBeInTheDocument();       // label from the catalogue
    expect(screen.getByText('1:16')).toBeInTheDocument();
    expect(await screen.findByText('Output ports')).toBeInTheDocument();      // capacity meaning for the type
    expect(screen.getByText('Counted from the assets it feeds.')).toBeInTheDocument();   // where the number comes from
    expect(screen.getByText('Room to grow')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /0 of 16 output ports/ })).toBeInTheDocument();  // splitter section
    expect(screen.queryByText(/legacy/i)).not.toBeInTheDocument();

    // Connections from the topology API: derived ones explain themselves and cannot be removed here
    expect(await screen.findByText('From the upload: parent splitter')).toBeInTheDocument();
    expect(screen.getByText('Drop via DRP-0001, 42 m')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Remove the link with SPL-ALN-01' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove the link with ONU-0001' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'SPL-ALN-01' }));
    expect(onGoTo).toHaveBeenCalledWith({ id: 'spl1', code: 'SPL-ALN-01' });
    await user.click(screen.getByRole('button', { name: 'Trace to OLT' }));
    expect(onTrace).toHaveBeenCalledWith(ASSET.id, 'upstream');
  });

  it('adds a connection in the chosen direction', async () => {
    api.get.mockResolvedValue(ASSET);
    api.search.mockResolvedValue([{ ...OLT, id: 'cab9', asset_code: 'CAB-ALN-09', asset_type: 'CABINET' }]);
    api.createConnection.mockResolvedValue(CONNECTIONS.upstream[0]);
    const user = userEvent.setup();
    wrap(<AssetInspector kind="asset" id={ASSET.id} {...inspectorProps} />);
    await user.click(await screen.findByRole('button', { name: 'Add connection' }));
    const form = screen.getByRole('form', { name: 'Add a connection' });
    await user.click(within(form).getByLabelText('SPL-ALN-02 feeds'));
    await user.type(within(form).getByLabelText('Asset'), 'CAB-ALN');
    await user.click(await within(form).findByRole('button', { name: /CAB-ALN-09/ }));
    await user.selectOptions(within(form).getByLabelText('Link'), 'SPLIT');
    await user.click(within(form).getByRole('button', { name: 'Add connection' }));
    await waitFor(() => expect(api.createConnection).toHaveBeenCalled());
    expect(api.createConnection.mock.calls[0][0]).toEqual({ source_asset_id: ASSET.id, dest_asset_id: 'cab9', connection_type: 'SPLIT' });
  });

  it('offers only allowed transitions and explains a refusal', async () => {
    api.get.mockResolvedValue(ASSET);
    api.update.mockRejectedValue(Object.assign(new Error('Forbidden'), { status: 403, detail: 'Forbidden' }));
    const user = userEvent.setup();
    wrap(<AssetInspector kind="asset" id={ASSET.id} {...inspectorProps} />);
    const select = await screen.findByLabelText('New status');
    expect(within(select).getAllByRole('option').map(o => o.textContent)).toEqual(['Change status to…', 'Faulty', 'Retired']);
    await user.selectOptions(select, 'FAULTY');
    await user.click(screen.getByRole('button', { name: 'Change status' }));
    expect(api.update).toHaveBeenCalledWith(ASSET.id, { lifecycle_status: 'FAULTY' });
    expect(await screen.findByRole('alert')).toHaveTextContent(/don't have permission/);
  });

  it('edits details from the catalogue and keeps what it does not know', async () => {
    api.get.mockResolvedValue(ASSET);
    api.update.mockResolvedValue({ ...ASSET, attributes: { ...ASSET.attributes, number_customer: '9' } });
    const user = userEvent.setup();
    wrap(<AssetInspector kind="asset" id={ASSET.id} {...inspectorProps} />);
    await user.click(await screen.findByRole('button', { name: 'Edit details' }));
    const form = screen.getByRole('form', { name: 'Edit details' });
    await user.type(within(form).getByLabelText('Customers served'), '9');
    await user.clear(within(form).getByLabelText('In use'));
    await user.type(within(form).getByLabelText('In use'), '9');
    await user.click(within(form).getByRole('button', { name: 'Save details' }));
    expect(api.update).toHaveBeenCalledWith(ASSET.id, {
      name: 'SPL-ALN-02', description: null, capacity: 16, used_capacity: 9,
      attributes: {
        split_ratio: '1:16', splitter_level: 'Second-Level', number_customer: '9',
        legacy_cabinet_asset_id: 'cab-id', legacy_cabinet_code: 'CAB-ALN-01',
      },
    });
  });

  it('checks capacity before sending', async () => {
    api.get.mockResolvedValue(ASSET);
    const user = userEvent.setup();
    wrap(<AssetInspector kind="asset" id={ASSET.id} {...inspectorProps} />);
    await user.click(await screen.findByRole('button', { name: 'Edit details' }));
    await user.type(screen.getByLabelText('In use'), '40');
    await user.click(screen.getByRole('button', { name: 'Save details' }));
    expect(screen.getByRole('alert')).toHaveTextContent('In use cannot be more than output ports');
    expect(api.update).not.toHaveBeenCalled();
  });

  it('says so when the asset is gone', async () => {
    api.get.mockRejectedValue(Object.assign(new Error('Not found'), { status: 404 }));
    wrap(<AssetInspector kind="asset" id="x" {...inspectorProps} />);
    expect(await screen.findByRole('alert')).toHaveTextContent(/no longer in the live network/);
  });
});

const CABLE: NetCable = {
  id: 'c1', asset_code: 'DRP-0007', cable_category: 'DROP', name: null, description: null,
  lifecycle_status: 'ACTIVE', creation_method: 'IMPORTED', route_method: 'IMPORTED', installation_type: 'AERIAL',
  fiber_count: 2, length_m: 70.81, geometry: { type: 'LineString', coordinates: [[3.3538, 6.5992], [3.3542, 6.5987]] },
  midpoint: [3.354, 6.599], bbox: [3.3538, 6.5987, 3.3542, 6.5992],
  source: { id: 'fat', asset_code: 'FAT-0014', asset_type: 'FAT', name: null }, dest: null,
  attributes: { cable_type: 'FLAT_DROP' }, project_id: null, design_id: null, lineage_id: 'l', source_table: null,
  allowed_transitions: ['FAULTY', 'RETIRED'], created_at: '2026-09-25T10:00:00Z', updated_at: '2026-09-25T10:00:00Z',
};

describe('Cable inspector', () => {
  it('shows the route, endpoints and typed details', async () => {
    api.catalogue.mockResolvedValue(CATALOGUE);
    api.getCable.mockResolvedValue(CABLE);
    api.fibres.mockResolvedValue([]);
    const onGoTo = vi.fn();
    const onFitBounds = vi.fn();
    const user = userEvent.setup();
    wrap(<AssetInspector kind="cable" id="c1" {...inspectorProps} onGoTo={onGoTo} onFitBounds={onFitBounds} />);
    expect(await screen.findByRole('heading', { name: 'DRP-0007' })).toBeInTheDocument();
    expect(screen.getByText('Drop cable')).toBeInTheDocument();
    expect(screen.getByText('71 m')).toBeInTheDocument();
    expect(screen.getByText('As built (imported survey)')).toBeInTheDocument();
    expect(await screen.findByText('Flat drop')).toBeInTheDocument();
    expect(screen.getByText('Not linked')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'FAT-0014' }));
    expect(onGoTo).toHaveBeenCalledWith({ id: 'fat', code: 'FAT-0014' });
    await user.click(screen.getByRole('button', { name: /Zoom to cable/ }));
    expect(onFitBounds).toHaveBeenCalledWith(CABLE.bbox);
  });
});

// ── Attribute helpers ────────────────────────────────────────

describe('attribute format', () => {
  const pole = CATALOGUE.asset_types[1].attributes;

  it('humanises vocabulary without mangling ratios or codes', () => {
    expect(humaniseOption('CAST_IRON')).toBe('Cast iron');
    expect(humaniseOption('1:16')).toBe('1:16');
    expect(humaniseOption('First-Level')).toBe('First-Level');
    expect(humaniseOption('ADSS')).toBe('ADSS');
    expect(humaniseOption('SC_APC')).toBe('SC APC');
    expect(humaniseOption('FLAT_DROP')).toBe('Flat drop');
    expect(formatField(pole[0], 9)).toBe('9 m');
    expect(formatField(pole[2], false)).toBe('No');
  });

  it('merges a draft: blank removes, untouched keeps the stored value, unknown keys survive', () => {
    const stored = { height_m: 9, material: 'CONCRETE', engine_ref: 'x' };
    const draft = { ...toDraft(pole, stored), material: '', existing: 'true' };
    expect(mergeDraft(pole, stored, draft)).toEqual({ height_m: 9, engine_ref: 'x', existing: true });
  });

  it('shows known fields by label and extras separately', () => {
    render(<AttributeView specs={pole} values={{ material: 'CAST_IRON', drum: 'D-12', legacy_x: 'hidden' }} />);
    expect(screen.getByText('Cast iron')).toBeInTheDocument();
    expect(screen.getByText('2 more fields not recorded.')).toBeInTheDocument();
    expect(screen.getByText('Other details')).toBeInTheDocument();
    expect(screen.getByText('Drum')).toBeInTheDocument();
    expect(screen.queryByText('hidden')).not.toBeInTheDocument();
  });
});

// ── Register ─────────────────────────────────────────────────

describe('NetworkRegister', () => {
  it('lists assets, filters on the server and links to the map', async () => {
    api.catalogue.mockResolvedValue(CATALOGUE);
    api.list.mockResolvedValue({ items: [{ ...OLT, asset_type: 'POLE', asset_code: 'POLE-0001' }], total: 1, page: 1, size: 25, total_pages: 1 });
    api.cables.mockResolvedValue({ items: [], total: 0, page: 1, size: 25, total_pages: 1 });
    const user = userEvent.setup();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/infrastructure']}>
          <Routes>
            <Route path="/infrastructure" element={<NetworkRegister />} />
            <Route path="/network" element={<LocationProbe />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findAllByText('POLE-0001')).not.toHaveLength(0);
    await user.click(screen.getByRole('combobox', { name: 'Asset type' }));   // the app's listbox select
    await user.click(await screen.findByRole('option', { name: 'Pole' }));
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'POLE', page: 1 })));
    await user.click(screen.getAllByRole('button', { name: 'Show POLE-0001 on the map' })[0]);
    expect(await screen.findByTestId('location')).toHaveTextContent(`/network?asset=${OLT.id}`);
  });

  it('switches to cables', async () => {
    api.catalogue.mockResolvedValue(CATALOGUE);
    api.list.mockResolvedValue({ items: [], total: 0, page: 1, size: 25, total_pages: 1 });
    api.cables.mockResolvedValue({ items: [], total: 0, page: 1, size: 25, total_pages: 1 });
    const user = userEvent.setup();
    wrap(<MemoryRouter><NetworkRegister /></MemoryRouter>);
    await user.click(screen.getByRole('radio', { name: 'Cables' }));
    expect(await screen.findByText('No network cables yet')).toBeInTheDocument();
  });
});

function LocationProbe() {
  const loc = useLocation();
  return <span data-testid="location">{loc.pathname + loc.search}</span>;
}

// ── Tool rail ────────────────────────────────────────────────

describe('ToolRail', () => {
  function fakeMap() {
    return {
      zoomIn: vi.fn(), zoomOut: vi.fn(), fitBounds: vi.fn(), flyTo: vi.fn(), getZoom: () => 12,
    };
  }

  it('zooms, fits the network and switches basemap', async () => {
    const map = fakeMap();
    const user = userEvent.setup();
    render(
      <MapInstanceProvider value={{ map, basemapHealth: 'ok' } as unknown as MapCtx}>
        <ToolRail bounds={{ bbox: [3.34, 6.59, 3.37, 6.61], feature_count: 9 }} workspace={null} onLocateError={vi.fn()} panelShown onShowPanel={vi.fn()} showCapacity={false} onToggleCapacity={vi.fn()} />
      </MapInstanceProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(map.zoomIn).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Fit the whole network' }));
    expect(map.fitBounds).toHaveBeenCalledWith([[3.34, 6.59], [3.37, 6.61]], expect.objectContaining({ maxZoom: 17 }));
    await user.click(screen.getByRole('button', { name: 'Basemap' }));
    await user.click(screen.getByRole('menuitemradio', { name: 'Night map' }));
    expect(useNetworkMapStore.getState().basemap).toBe('dark');
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
  });

  it('cannot fit an empty network', () => {
    render(
      <MapInstanceProvider value={{ map: fakeMap(), basemapHealth: 'ok' } as unknown as MapCtx}>
        <ToolRail bounds={{ bbox: null, feature_count: 0 }} workspace={null} onLocateError={vi.fn()} panelShown onShowPanel={vi.fn()} showCapacity={false} onToggleCapacity={vi.fn()} />
      </MapInstanceProvider>,
    );
    expect(screen.getByRole('button', { name: 'Fit the whole network' })).toBeDisabled();
  });
});

// ── Trace (Phase 3) ──────────────────────────────────────────

type Hop = NetTrace['hops'][number];
const hop = (id: string, code: string, type: Hop['asset']['asset_type'], depth: number, from: string | null,
  via: Hop['via_cable'] = null, conn: Hop['connection_type'] = null): Hop => ({
  asset: { id, asset_code: code, asset_type: type, name: null, lifecycle_status: 'ACTIVE', lng: 3.35, lat: 6.6 },
  depth, from_id: from, connection_type: conn, via_cable: via,
});

const UP: NetTrace = {
  direction: 'upstream', start_id: 's2',
  hops: [
    hop('s2', 'SPL-ALN-02', 'SPLITTER', 0, null),
    hop('s1', 'SPL-ALN-01', 'SPLITTER', 1, 's2', null, 'SPLIT'),
    hop('c1', 'CAB-ALN-01', 'CABINET', 2, 's1', null, 'PATCH'),
    hop('o1', 'OLT-IKJ-01', 'OLT', 3, 'c1', { id: 'f1', asset_code: 'FDR-IKJ-01', cable_category: 'FEEDER', length_m: 377.9 }, 'FEED'),
  ],
  path_ids: ['s2', 's1', 'c1', 'o1'], root: null, reached_root: true, path_length_m: 377.9,
  counts_by_type: {}, customers: 0, truncated: false, geometry: { type: 'FeatureCollection', features: [] },
};

describe('TracePanel', () => {
  const props = {
    loading: false, error: false, typeLabel: (t: string) => t,
    cableLabel: (c: string) => (c === 'FEEDER' ? 'Feeder' : c), onOpen: vi.fn(), onClose: vi.fn(),
  };

  it('lists the path to the OLT with what links each step', async () => {
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(<TracePanel {...props} onOpen={onOpen} trace={UP} startCode="SPL-ALN-02" direction="upstream" />);
    expect(screen.getByRole('heading', { name: 'Path from SPL-ALN-02 to the OLT' })).toBeInTheDocument();
    expect(screen.getByText('3 steps, 378 m of cable')).toBeInTheDocument();
    expect(screen.getByText('Splitter output, no cable recorded')).toBeInTheDocument();
    expect(screen.getByText('FDR-IKJ-01 (feeder, 378 m)')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(4);
    await user.click(screen.getByRole('button', { name: /OLT-IKJ-01/ }));
    expect(onOpen).toHaveBeenCalledWith('o1');
    expect(screen.queryByText(/No OLT reached/)).not.toBeInTheDocument();
  });

  it('says where the chain stops when no OLT is reached', () => {
    const short: NetTrace = { ...UP, hops: UP.hops.slice(0, 3), path_ids: ['s2', 's1', 'c1'], reached_root: false, path_length_m: null };
    render(<TracePanel {...props} trace={short} startCode="SPL-ALN-02" direction="upstream" />);
    expect(screen.getByRole('status')).toHaveTextContent('No OLT reached. The chain stops at CAB-ALN-01');
  });

  it('counts what is fed downstream', () => {
    const down: NetTrace = { ...UP, direction: 'downstream', path_ids: [], customers: 3, counts_by_type: { SPLITTER: 2, FAT: 1, ONU: 3 } };
    render(<TracePanel {...props} trace={down} startCode="OLT-IKJ-01" direction="downstream" />);
    expect(screen.getByText('3 customers served, 3 assets in all')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem').map(li => li.textContent)).toEqual(['FAT1', 'SPLITTER2', 'ONU3']);
  });
});

// ── Fibres ───────────────────────────────────────────────────

const fibre = (n: number, status: NetFibre['status'] = 'FREE'): NetFibre => ({
  fiber_no: n, tube_no: Math.ceil(n / 12), position: ((n - 1) % 12) + 1,
  colour: n % 12 === 1 ? 'Blue' : 'Orange', colour_hex: '#1F5FD8',
  tube_colour: n > 12 ? 'Orange' : 'Blue', tube_colour_hex: '#F28A1E',
  status, recorded: status !== 'FREE',
});

describe('FibresSection', () => {
  it('shows fibres by tube and records a status', async () => {
    api.fibres.mockResolvedValue(Array.from({ length: 24 }, (_, i) => fibre(i + 1, i === 12 ? 'USED' : 'FREE')));
    api.setFibre.mockResolvedValue(fibre(2, 'FAULTY'));
    const user = userEvent.setup();
    wrap(<FibresSection cableId="c1" statuses={['FREE', 'USED', 'RESERVED', 'FAULTY', 'DARK']} />);
    expect(await screen.findByText('24 fibres, 1 in use. Choose a fibre to record its status.')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Tube 2' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Fibre 2, orange, free' }));
    await user.selectOptions(screen.getByLabelText('Status of fibre 2'), 'FAULTY');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(api.setFibre).toHaveBeenCalledWith('c1', 2, 'FAULTY');
  });

  it('explains a cable with no fibre count', async () => {
    api.fibres.mockResolvedValue([]);
    wrap(<FibresSection cableId="c1" statuses={['FREE']} />);
    expect(await screen.findByText('No fibre count recorded for this cable.')).toBeInTheDocument();
  });
});

// ── Context menu, trace state, capacity toggle ───────────────

describe('MapContextMenu', () => {
  it('is a keyboard menu that runs and closes', async () => {
    const trace = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<MapContextMenu title="FAT-0014" x={10} y={10} onClose={onClose} actions={[
      { id: 'details', label: 'Show details', icon: 'details', run: vi.fn() },
      { id: 'up', label: 'Trace to OLT', icon: 'up', run: trace },
    ]} />);
    expect(screen.getByRole('menuitem', { name: 'Show details' })).toHaveFocus();
    await user.keyboard('{ArrowDown}{Enter}');
    expect(trace).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});

describe('trace state', () => {
  it('starts and clears a trace; remembers the capacity view', () => {
    useNetworkMapStore.getState().startTrace('a1', 'downstream');
    expect(useNetworkMapStore.getState().trace).toEqual({ assetId: 'a1', direction: 'downstream' });
    useNetworkMapStore.getState().clearTrace();
    expect(useNetworkMapStore.getState().trace).toBeNull();
    useNetworkMapStore.getState().setShowCapacity(true);
    expect(JSON.parse(localStorage.getItem('opsyn-network-map')!).showCapacity).toBe(true);
  });

  it('toggles capacity rings from the rail', async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();
    const map = { zoomIn: vi.fn(), zoomOut: vi.fn(), fitBounds: vi.fn(), flyTo: vi.fn(), getZoom: () => 12 };
    render(
      <MapInstanceProvider value={{ map, basemapHealth: 'ok' } as unknown as MapCtx}>
        <ToolRail bounds={undefined} workspace={null} onLocateError={vi.fn()} panelShown onShowPanel={vi.fn()}
          showCapacity onToggleCapacity={onToggle} />
      </MapInstanceProvider>,
    );
    const btn = screen.getByRole('button', { name: 'Hide capacity rings' });
    expect(btn).toHaveAttribute('aria-pressed', 'true');
    await user.click(btn);
    expect(onToggle).toHaveBeenCalled();
  });
});
