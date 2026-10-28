// ============================================================
// Phase 3 — app shell: navigation model, health summary, URL tabs, and a
// render of the whole shell (field layout in jsdom, where no media query matches).
// ============================================================

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import appSource from '../App.tsx?raw';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import type { OutageIncident } from '@shared';
import { NAV_SECTIONS, EXTRA_PAGES, allDestinations, resolveNav } from '../layouts/navigation';
import { summariseOutages, SLA_RISK_WINDOW_MIN } from '../layouts/useShellData';
import { useUrlTab } from '../hooks/useUrlTab';

// ── Navigation model ─────────────────────────────────────────

describe('navigation', () => {
  const crumbs = (path: string) => {
    const [p, q = ''] = path.split('?');
    return resolveNav(p, q ? `?${q}` : '').crumbs.map(c => c.label);
  };

  it('resolves areas, sub-pages and record pages to breadcrumbs', () => {
    expect(crumbs('/dashboard')).toEqual(['Monitor', 'Command Center']);
    expect(crumbs('/tasks')).toEqual(['Operate', 'Tasks']);
    expect(crumbs('/tasks/inbox')).toEqual(['Operate', 'Tasks', 'Department inbox']);
    expect(crumbs('/projects/abc-123')).toEqual(['Operate', 'Projects', 'Details']);
    expect(crumbs('/projects/abc-123/pipeline')).toEqual(['Operate', 'Projects', 'Details', 'Pipeline']);
    expect(crumbs('/customers/forms')).toEqual(['Operate', 'Customers', 'Customer fields']);
    expect(crumbs('/customers/9f2')).toEqual(['Operate', 'Customers', 'Details']);
    expect(crumbs('/settings/forms/customer')).toEqual(['Admin', 'Settings', 'Form']);
    expect(crumbs('/notifications')).toEqual(['Notifications']);
  });

  it('keeps the network map and the asset registry apart', () => {
    expect(resolveNav('/network', '').area?.id).toBe('map');
    // The legacy map tab stays inside Infrastructure (decision D4, revised)
    expect(resolveNav('/infrastructure', '?tab=map').area?.id).toBe('infrastructure');
    expect(resolveNav('/infrastructure', '?tab=olts').area?.id).toBe('infrastructure');
    expect(resolveNav('/infrastructure', '').area?.id).toBe('infrastructure');
    expect(resolveNav('/infrastructure/upload', '').page?.id).toBe('infra-upload');
  });

  it('marks the right settings tab', () => {
    expect(resolveNav('/settings', '?tab=webhooks').page?.id).toBe('settings-webhooks');
    expect(resolveNav('/settings', '').page?.id).toBe('settings-org');
  });

  it('lists every destination exactly once', () => {
    const paths = allDestinations().map(d => d.page.path);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it('only links to routes that exist in App.tsx', () => {
    const routes = new Set([...appSource.matchAll(/path="([^"]+)"/g)].map(m => '/' + m[1].replace(/^\//, '')));
    const navPaths = [
      ...NAV_SECTIONS.flatMap(s => s.areas.flatMap(a => [a.path, ...(a.pages ?? []).map(p => p.path)])),
      ...EXTRA_PAGES.map(p => p.path),
    ].map(p => p.split('?')[0]);
    for (const p of navPaths) expect(routes, `no route for ${p}`).toContain(p);
  });
});

// ── Health summary ───────────────────────────────────────────

describe('summariseOutages', () => {
  const NOW = Date.parse('2026-09-24T12:00:00Z');
  const o = (severity: OutageIncident['severity'], extra: Partial<OutageIncident> = {}): OutageIncident =>
    ({ id: Math.random().toString(), reference: 'OUT', title: 't', severity, status: 'active', created_at: '2026-09-24T10:00:00Z', ...extra });
  const inMin = (m: number) => new Date(NOW + m * 60_000).toISOString();

  it('counts open outages by severity and ignores resolved ones', () => {
    const s = summariseOutages([o('critical'), o('high'), o('high'), o('low', { status: 'resolved' })], NOW);
    expect(s.bySeverity).toEqual({ critical: 1, high: 2, warning: 0, low: 0 });
    expect(s.open).toBe(3);
  });

  it(`flags outages within ${SLA_RISK_WINDOW_MIN} minutes of their SLA deadline`, () => {
    const s = summariseOutages([
      o('high', { sla_deadline: inMin(10) }),                        // at risk
      o('high', { sla_deadline: inMin(-5) }),                        // past due, not yet flagged → at risk
      o('warning', { sla_deadline: inMin(240) }),                    // fine
      o('critical', { sla_deadline: inMin(-60), breached_sla: true }), // breached, not "at risk"
      o('low'),                                                      // no SLA
    ], NOW);
    expect(s.slaAtRisk).toBe(2);
    expect(s.slaBreached).toBe(1);
  });
});

// ── useUrlTab ────────────────────────────────────────────────

describe('useUrlTab', () => {
  function Tabs() {
    const [tab, setTab] = useUrlTab(['org', 'webhooks'] as const, 'org');
    const loc = useLocation();
    return (
      <>
        <p>tab:{tab}</p>
        <p>url:{loc.search}</p>
        <button onClick={() => setTab('webhooks')}>webhooks</button>
        <button onClick={() => setTab('org')}>org</button>
      </>
    );
  }
  const at = (url: string) => render(<MemoryRouter initialEntries={[url]}><Tabs /></MemoryRouter>);

  it('reads the tab from the URL and falls back for unknown values', () => {
    at('/settings?tab=webhooks');
    expect(screen.getByText('tab:webhooks')).toBeInTheDocument();
  });

  it('falls back to the default for an unknown tab', () => {
    at('/settings?tab=bogus');
    expect(screen.getByText('tab:org')).toBeInTheDocument();
  });

  it('writes the tab to the URL, omitting the default', async () => {
    at('/settings');
    await userEvent.click(screen.getByRole('button', { name: 'webhooks' }));
    expect(screen.getByText('url:?tab=webhooks')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'org' }));
    expect(screen.getByText('tab:org')).toBeInTheDocument();
    expect(screen.queryByText(/url:\?tab/)).not.toBeInTheDocument();
  });
});

// ── The shell ────────────────────────────────────────────────

vi.mock('../api/index', () => ({
  outageApi: {
    getLive: vi.fn().mockResolvedValue([
      { id: '1', reference: 'OUT-1', title: 'Feeder cut', severity: 'critical', status: 'active', created_at: '2026-09-24T10:00:00Z' },
      { id: '2', reference: 'OUT-2', title: 'Splitter offline', severity: 'high', status: 'monitoring', created_at: '2026-09-24T09:00:00Z' },
    ]),
  },
  reportsApi: { getIntelStrip: vi.fn().mockResolvedValue({ tasks_overdue: 7, staff_on_call: 4, active_outages: 2, avg_mttr_mins: null, pending_onboarding: 0 }) },
  notificationsApi: { getUnreadCount: vi.fn().mockResolvedValue(3), list: vi.fn().mockResolvedValue([]) },
  onboardingApi: { list: vi.fn().mockResolvedValue({ items: [] }) },
}));

// The first test loads the whole shell module graph cold (~4 s on a busy
// machine) — too close to vitest's 5 s default to be reliable.
describe('AppShell', { timeout: 20_000 }, () => {
  async function renderShellAt(path: string) {
    const { default: AppShell } = await import('../layouts/AppShell');
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="*" element={<p>page body</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it('shows where you are: breadcrumb, current nav item, section tabs', async () => {
    await renderShellAt('/tasks/inbox');
    expect(screen.getByText('page body')).toBeInTheDocument();
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(within(crumbs).getByText('Department inbox')).toHaveAttribute('aria-current', 'page');

    const tabs = screen.getByRole('navigation', { name: 'Tasks pages' });
    expect(within(tabs).getByRole('link', { name: 'Department inbox' })).toHaveAttribute('aria-current', 'page');

    const quick = screen.getByRole('navigation', { name: 'Quick navigation' });
    expect(within(quick).getByRole('link', { name: /Tasks/ })).toHaveAttribute('aria-current', 'page');
  });

  it('reports open outages by severity, with text, not colour alone', async () => {
    await renderShellAt('/dashboard');
    const health = screen.getByRole('region', { name: 'Network health' });
    await waitFor(() => expect(within(health).getByRole('link', { name: '1 critical outage open' })).toBeInTheDocument());
    expect(within(health).getByRole('link', { name: '1 high outage open' })).toBeInTheDocument();
    expect(within(health).getByRole('link', { name: '0 warning outages open' })).toBeInTheDocument();
    expect(within(health).getByText('On call')).toBeInTheDocument();
  });

  it('opens the command palette with Ctrl+K and navigates', async () => {
    await renderShellAt('/dashboard');
    await userEvent.keyboard('{Control>}k{/Control}');
    const input = await screen.findByRole('combobox', { name: 'Search commands' });
    await userEvent.type(input, 'fttx');
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(within(screen.getByRole('navigation', { name: 'Breadcrumb' })).getByText('FTTx Designer')).toBeInTheDocument());
  });

  it('keeps the shell usable when a page crashes', async () => {
    const { default: AppShell } = await import('../layouts/AppShell');
    const Boom = () => { throw new Error('deptArr.filter is not a function'); };
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/settings']}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="*" element={<Boom />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole('alert')).toHaveTextContent("This page couldn't be displayed");
    expect(screen.getByRole('navigation', { name: 'Quick navigation' })).toBeInTheDocument();
    spy.mockRestore();
  });

  it('moves focus to the new page heading after navigation, not on first load', async () => {
    const { default: AppShell } = await import('../layouts/AppShell');
    const PageWithHeading = () => <h1>Page at {useLocation().pathname}</h1>;
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/dashboard']}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="*" element={<PageWithHeading />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByRole('heading', { level: 1, name: 'Page at /dashboard' });
    expect(document.activeElement).toBe(document.body);

    const quick = screen.getByRole('navigation', { name: 'Quick navigation' });
    await userEvent.click(within(quick).getByRole('link', { name: /Tasks/ }));
    const heading = await screen.findByRole('heading', { level: 1, name: 'Page at /tasks' });
    await waitFor(() => expect(heading).toHaveFocus());
  });

  it('opens the navigation drawer from the bottom nav on small screens', async () => {
    await renderShellAt('/dashboard');
    await userEvent.click(screen.getByRole('button', { name: 'Menu' }));
    const drawer = await screen.findByRole('dialog', { name: 'Navigation' });
    expect(within(drawer).getByRole('link', { name: /Infrastructure/ })).toBeInTheDocument();
  });
});
