// ============================================================
// Phase 6 — Map / GIS: the asset model (positions, state, search, path
// trace, route styling) and the floating controls' key behaviours.
// ============================================================

import { fireEvent, render, screen } from '@testing-library/react';
import type { InfraMapData, OutageIncident } from '@shared';
import LayerPanel from '../pages/infrastructure/map/LayerPanel';
import { DEFAULT_LAYERS, type LayerCounts } from '../pages/infrastructure/map/layers';
import type { MapPalette } from '../pages/infrastructure/map/mapIcons';
import {
  buildAssetIndex, capacityState, nodePosition, routeState, routeStyle, searchAssets, traceSplitter, worstSeverity,
} from '../pages/infrastructure/map/mapModel';
import MapSearch from '../pages/infrastructure/map/MapSearch';

const inc = (over: Partial<OutageIncident>): OutageIncident =>
  ({ id: Math.random().toString(), reference: 'OUT-1', title: 'Fiber cut', severity: 'low', status: 'active', created_at: '2026-09-24T10:00:00Z', ...over });

const DATA: InfraMapData = {
  sites: [
    { id: 's1', name: 'Ikeja POP', site_type: 'POP', latitude: 6.6, longitude: 3.35, status: 'active', is_monitored: true, has_alert: false },
    { id: 's2', name: 'No coords', site_type: 'POP', status: 'active', is_monitored: false, has_alert: false },
    { id: 's3', name: 'Null island', site_type: 'POP', latitude: 0, longitude: 0, status: 'active', is_monitored: false, has_alert: false },
  ],
  nodes: [
    { id: 'n1', name: 'Core-1', node_type: 'OLT', site_id: 's1', status: 'active', utilisation: { used: 0, total: 0, pct: 0 }, has_alert: false },
    { id: 'n2', name: 'Orphan', node_type: 'OLT', status: 'active', utilisation: { used: 0, total: 0, pct: 0 }, has_alert: false },
  ],
  routes: [],
  olts: [{ id: 'o1', name: 'OLT-IKJ-01', latitude: 6.61, longitude: 3.36 }],
  cabinets: [{ id: 'c1', cabinet_id: 'CAB-104', latitude: 6.62, longitude: 3.37, capacity: 144 }],
  splitters: [
    { id: 'p1', box_id: 'SPL-L1-7', latitude: 6.63, longitude: 3.38, splitter_level: 'First-Level', splitter_type: 'PLC', input_ports: 1, output_ports: 8, cabinet_id: 'c1' },
    { id: 'p2', box_id: 'SPL-L2-71', latitude: 6.64, longitude: 3.39, splitter_level: 'Second-Level', splitter_type: 'PLC', input_ports: 1, output_ports: 8, number_customer: 8, parent_splitter_id: 'p1' },
    { id: 'p3', box_id: 'SPL-L2-99', latitude: 6.65, longitude: 3.4, splitter_level: 'Second-Level', splitter_type: 'PLC', input_ports: 1, output_ports: 8, parent_splitter_id: 'missing' },
    { id: 'p4', box_id: 'SPL-LOOP-A', latitude: 6.66, longitude: 3.41, splitter_level: 'Second-Level', splitter_type: 'PLC', input_ports: 1, output_ports: 8, parent_splitter_id: 'p5' },
    { id: 'p5', box_id: 'SPL-LOOP-B', latitude: 6.67, longitude: 3.42, splitter_level: 'First-Level', splitter_type: 'PLC', input_ports: 1, output_ports: 8, parent_splitter_id: 'p4' },
  ],
};

const PALETTE: MapPalette = {
  state: { normal: '#999', watch: '#fc0', critical: '#f33', offline: '#555' },
  severity: { critical: '#f33', high: '#f80', warning: '#fc0', low: '#6af' },
  outline: '#000', select: '#2fd', route: { normal: '#aaa', watch: '#fc0', critical: '#f33', unknown: '#888' },
};

describe('map model', () => {
  it('places only assets with real coordinates (missing and 0,0 are skipped)', () => {
    const assets = buildAssetIndex(DATA, [], []);
    expect(assets.filter(a => a.kind === 'site').map(a => a.id)).toEqual(['s1']);
    expect(assets).toHaveLength(1 + 1 + 1 + 5);
  });

  it('derives state from capacity, alerts and service status', () => {
    expect(capacityState(50, false)).toBe('normal');
    expect(capacityState(70, false)).toBe('watch');
    expect(capacityState(90, false)).toBe('critical');
    expect(capacityState(10, true)).toBe('critical');
    expect(capacityState(95, true, 'inactive')).toBe('offline');
  });

  it('marks a full splitter as watch', () => {
    const assets = buildAssetIndex(DATA, [], []);
    expect(assets.find(a => a.id === 'p2')?.state).toBe('watch');
    expect(assets.find(a => a.id === 'p1')?.state).toBe('normal');
  });

  it('attaches open incidents to OLTs by reference (case-insensitive) and ignores resolved ones', () => {
    const assets = buildAssetIndex(DATA, [], [
      inc({ olt_reference: ' olt-ikj-01 ', severity: 'high' }),
      inc({ olt_reference: 'OLT-IKJ-01', severity: 'critical', status: 'resolved' }),
      inc({ olt_reference: 'OLT-ELSEWHERE' }),
    ]);
    const olt = assets.find(a => a.kind === 'olt')!;
    expect(olt.incidents).toHaveLength(1);
    expect(olt.state).toBe('critical');
    expect(worstSeverity(olt.incidents)).toBe('high');
  });

  it('ranks search: exact, then prefix, then substring, then sublabel', () => {
    const assets = buildAssetIndex(DATA, [], []);
    expect(searchAssets(assets, 'spl-l2-71')[0].id).toBe('p2');
    expect(searchAssets(assets, 'SPL-L2').map(a => a.id)).toEqual(['p2', 'p3']);
    expect(searchAssets(assets, 'cabinet')[0].id).toBe('c1');
    expect(searchAssets(assets, '   ')).toEqual([]);
  });

  it('traces a splitter upstream to its cabinet and says where the record ends', () => {
    const assets = buildAssetIndex(DATA, [], []);
    const t = traceSplitter('p2', DATA, assets);
    expect(t.hops.map(h => h.asset.id)).toEqual(['p2', 'p1', 'c1']);
    expect(t.stop).toMatch(/not linked to an OLT/);
  });

  it('stops a trace honestly at a missing parent and at a loop', () => {
    const assets = buildAssetIndex(DATA, [], []);
    expect(traceSplitter('p3', DATA, assets).stop).toMatch(/no mapped position/);
    const loop = traceSplitter('p4', DATA, assets);
    expect(loop.hops.map(h => h.asset.id)).toEqual(['p4', 'p5']);
    expect(loop.stop).toMatch(/loops back/);
  });

  it('styles routes by state with a dash pattern, not colour alone', () => {
    expect(routeState('Active')).toBe('normal');
    expect(routeState('maintenance')).toBe('watch');
    expect(routeState('cut')).toBe('critical');
    expect(routeState('planned')).toBe('unknown');
    expect(routeStyle({ status: 'cut', cable_type: 'Trunk 96F' })).toEqual({ weight: 4, state: 'critical', dashArray: '2 6' });
    expect(routeStyle({ status: 'active', cable_type: 'drop' })).toEqual({ weight: 2, state: 'normal', dashArray: undefined });
  });

  it('positions a node through its site, or not at all', () => {
    const sites = new Map(DATA.sites.map(x => [x.id, x]));
    expect(nodePosition(DATA.nodes[0], sites)).toEqual([6.6, 3.35]);
    expect(nodePosition(DATA.nodes[1], sites)).toBeNull();
  });
});

describe('map controls', () => {
  it('search is a combobox: typing lists matches, Enter picks the top one', () => {
    const onPick = vi.fn();
    render(<MapSearch assets={buildAssetIndex(DATA, [], [])} palette={PALETTE} onPick={onPick} />);
    const box = screen.getByRole('combobox', { name: 'Search assets' });
    fireEvent.change(box, { target: { value: 'CAB' } });
    expect(screen.getByRole('option', { name: /CAB-104/ })).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: 'c1' }));
  });

  it('search says so when nothing matches', () => {
    render(<MapSearch assets={buildAssetIndex(DATA, [], [])} palette={PALETTE} onPick={() => {}} />);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'zzz' } });
    expect(screen.getByText(/No mapped asset matches/)).toBeInTheDocument();
  });

  it('layer panel toggles layers and lists on-call staff without placing them', () => {
    const counts: LayerCounts = {
      sites: 1, olts: 1, cabinets: 1, splitterL1: 2, splitterL2: 3, routes: 0, subscribers: 0,
      alarmsBySeverity: { critical: 0, high: 1, warning: 0, low: 0 }, alarmsUnplaced: 2,
    };
    const onToggle = vi.fn();
    render(<LayerPanel layers={DEFAULT_LAYERS} onToggle={onToggle} counts={counts} palette={PALETTE} onCall={['Ada Obi']} onClose={() => {}} />);
    expect(screen.getByRole('region', { name: 'Map layers' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /Cabinets/ }));
    expect(onToggle).toHaveBeenCalledWith('cabinets');
    expect(screen.getByRole('checkbox', { name: /Site utilisation/ })).not.toBeChecked();
    expect(screen.getByText('2 without a mapped OLT')).toBeInTheDocument();
    expect(screen.getByText('Ada Obi')).toBeInTheDocument();
    expect(screen.getByText(/aren't placed on the map/)).toBeInTheDocument();
  });
});
