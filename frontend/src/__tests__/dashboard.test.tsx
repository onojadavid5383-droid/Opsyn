// ============================================================
// Phase 5 — Command Center: data helpers (no invented numbers) and the
// page's key behaviours against mocked APIs.
// ============================================================

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { OutageIncident } from '@shared';
import { sparklinePath } from '../components/charts';
import {
  formatDuration, panelState, placeIncidents, seriesChange, slaStatus, sortIncidents,
} from '../pages/dashboard/dashboardData';

const NOW = Date.parse('2026-09-24T12:00:00Z');
const at = (min: number) => new Date(NOW + min * 60_000).toISOString();
const inc = (over: Partial<OutageIncident>): OutageIncident =>
  ({ id: Math.random().toString(), reference: 'OUT', title: 't', severity: 'low', status: 'active', created_at: at(-60), ...over });

describe('dashboard helpers', () => {
  it('formats durations compactly', () => {
    expect(formatDuration(45)).toBe('45m');
    expect(formatDuration(135)).toBe('2h 15m');
    expect(formatDuration(1500)).toBe('1d 1h');
  });

  it('orders incidents by severity, then longest-running, and drops resolved', () => {
    const list = sortIncidents([
      inc({ id: 'low-old', severity: 'low', created_at: at(-900) }),
      inc({ id: 'crit-new', severity: 'critical', created_at: at(-10) }),
      inc({ id: 'high-new', severity: 'high', created_at: at(-20) }),
      inc({ id: 'high-old', severity: 'high', created_at: at(-400) }),
      inc({ id: 'gone', severity: 'critical', status: 'resolved' }),
    ]);
    expect(list.map(o => o.id)).toEqual(['crit-new', 'high-old', 'high-new', 'low-old']);
  });

  it('describes SLA standing in words', () => {
    expect(slaStatus(inc({ breached_sla: true }), NOW)).toEqual({ text: 'Breached', tone: 'critical' });
    expect(slaStatus(inc({ sla_deadline: at(-20) }), NOW)).toEqual({ text: 'Overdue 20m', tone: 'critical' });
    expect(slaStatus(inc({ sla_deadline: at(17) }), NOW)).toEqual({ text: '17m left', tone: 'high' });
    expect(slaStatus(inc({ sla_deadline: at(95) }), NOW)).toEqual({ text: '1h 35m left', tone: 'neutral' });
    expect(slaStatus(inc({}), NOW)).toBeNull();
  });

  it('measures change only between real values', () => {
    expect(seriesChange([null, 97.1, null, 97.8, null])).toMatchObject({ from: 97.1, to: 97.8 });
    expect(seriesChange([null, 97.1, null])).toBeNull();   // one point is not a trend
  });

  it('explains a 403 as missing access, not an error', () => {
    expect(panelState({ isPending: false, isError: true, error: { status: 403 } }, false))
      .toEqual({ status: 'empty', message: 'You need Reports access to see this.' });
    expect(panelState({ isPending: false, isError: true, error: { status: 500 } }, false)).toEqual({ status: 'error' });
    expect(panelState({ isPending: false, isError: false }, false, 'Nothing yet')).toEqual({ status: 'empty', message: 'Nothing yet' });
  });

  it('places incidents on OLTs by reference and counts what it cannot place', () => {
    const { byOlt, unplaced } = placeIncidents(
      [inc({ olt_reference: 'olt-lag-03 ' }), inc({ olt_reference: 'OLT-NOWHERE' }), inc({})],
      [{ id: 'l1', name: 'OLT-LAG-03' }],
    );
    expect(byOlt.get('l1')).toHaveLength(1);
    expect(unplaced).toBe(2);
  });

  it('sparklines do not inflate small wobbles', () => {
    const tight = sparklinePath([97.1, 97.8], 100, 28);            // min–max: full height swing
    const spanned = sparklinePath([97.1, 97.8], 100, 28, 2, 5);    // at least a 5-point range
    const ys = (d: string) => d.split(/[ML]/).filter(Boolean).map(p => Number(p.trim().split(' ')[1]));
    const swing = (d: string) => Math.abs(ys(d)[0] - ys(d)[1]);
    expect(swing(tight)).toBeGreaterThan(20);
    expect(swing(spanned)).toBeLessThan(5);
  });
});

// ── The page ─────────────────────────────────────────────────

vi.mock('../components/charts/ChartCanvas', () => ({ default: () => <div data-testid="chart" /> }));
vi.mock('../pages/dashboard/MiniMap', () => ({ default: () => <div data-testid="mini-map" /> }));

vi.mock('../api/index', () => {
  const now = Date.now();
  const iso = (m: number) => new Date(now + m * 60_000).toISOString();
  const trend = (has: boolean) => ({ metric: 'x', unit: 'count', bucket: 'day', days: 30, has_data: has, points: [{ t: iso(-1440), value: has ? 1 : 0 }, { t: iso(0), value: has ? 2 : 0 }], breakdown: { critical: [0, 1], high: [1, 1], warning: [0, 0], low: [0, 0] } });
  const forbidden = () => Promise.reject(Object.assign(new Error('Forbidden'), { status: 403 }));
  return {
    outageApi: { getLive: vi.fn().mockResolvedValue([
      { id: 'o2', reference: 'OUT-2', title: 'Splitter box offline', severity: 'high', status: 'active', olt_reference: 'OLT-A', affected_subscribers: 32, sla_deadline: iso(95), created_at: iso(-160) },
      { id: 'o1', reference: 'OUT-1', title: 'Feeder cut', severity: 'critical', status: 'active', olt_reference: 'OLT-A', affected_subscribers: 412, sla_deadline: iso(18), created_at: iso(-72) },
    ]) },
    dashboardApi: { getSummary: vi.fn().mockResolvedValue({ tasks: { open: 57, overdue: 7, today: 5 }, infrastructure: { total_nodes: 0, active_nodes: 0 } }) },
    infrastructureApi: {
      getUtilisation: vi.fn().mockResolvedValue([{ site_id: 's', name: 'Lekki POP', used: 482, total: 512, utilisation_pct: 94 }]),
      getMap: vi.fn().mockResolvedValue({ sites: [], olts: [{ id: 'l1', name: 'OLT-A', latitude: 6.4, longitude: 3.4 }], nodes: [], routes: [], cabinets: [], splitters: [] }),
    },
    reportsApi: {
      getTrends: vi.fn().mockImplementation(({ metric }: { metric: string }) => Promise.resolve(trend(metric === 'outages_opened'))),
      getOutageMttr: vi.fn().mockImplementation(forbidden),
      getTasksBreakdown: vi.fn().mockImplementation(forbidden),
      getProjectsBreakdown: vi.fn().mockImplementation(forbidden),
    },
    activityApi: { getGlobalFeed: vi.fn().mockResolvedValue({ items: [] }) },
  };
});
vi.mock('../api/tasks.api', () => ({ tasksApi: { getBoard: vi.fn().mockResolvedValue({ overdue: [], today: [], this_week: [], backlog: [] }) } }));

describe('Command Center', { timeout: 20_000 }, () => {
  async function renderPage() {
    const { default: DashboardPage } = await import('../pages/dashboard/DashboardPage');
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><DashboardPage /></MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it('leads with open incidents, most severe first', async () => {
    await renderPage();
    const panel = screen.getByRole('region', { name: /Open incidents/ });
    await waitFor(() => expect(within(panel).getByText('Feeder cut')).toBeInTheDocument());
    const titles = within(panel).getAllByText(/Feeder cut|Splitter box offline/).map(e => e.textContent);
    expect(titles).toEqual(['Feeder cut', 'Splitter box offline']);
    // SLA in words, in the same order: the critical one is near its deadline
    const sla = within(panel).getAllByText(/left$/, { selector: 'span' }).map(e => e.textContent);
    expect(sla).toHaveLength(2);
    expect(sla[0]).toMatch(/^1[78]m left$/);
    expect(sla[1]).toMatch(/^1h 3[45]m left$/);
  });

  it('never reports a made-up availability when there are no nodes', async () => {
    await renderPage();
    await waitFor(() => expect(screen.getByText('No nodes registered yet')).toBeInTheDocument());
    expect(screen.queryByText(/100(\.0)?/)).not.toBeInTheDocument();
  });

  it('explains missing Reports access instead of failing', async () => {
    await renderPage();
    await waitFor(() => expect(screen.getAllByText('You need Reports access to see this.').length).toBeGreaterThanOrEqual(2));
    expect(screen.getByText('Needs Reports access')).toBeInTheDocument();  // MTTR KPI
  });

  it('places incidents on the map and says so', async () => {
    await renderPage();
    await waitFor(() => expect(screen.getByTestId('mini-map')).toBeInTheDocument());
    expect(screen.getByText(/1 critical/)).toBeInTheDocument();
  });
});
