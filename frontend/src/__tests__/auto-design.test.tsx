// ============================================================
// Network GIS Phase 5 — auto design UI: the shared FTTx settings (wizard
// and drawer), the Auto design drawer (run, confirm replace, progress,
// failure, result, import a run), the toolbar's run badge and the engine's
// findings in the validation drawer. Mocked design API; the real run is
// checked end to end against the backend (api-check + screenshots).
// ============================================================

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import type { Design, DesignGenerateStatus, DesignSummary } from '@shared';

vi.mock('../api/design.api', () => ({
  designApi: {
    generate: vi.fn(), generateStatus: vi.fn(), importableRuns: vi.fn(), importRun: vi.fn(),
  },
}));

import { designApi } from '../api/design.api';
import { settingsFromConfig, settingsToConfig } from '../components/fttx/fttxSettings';
import { FttxConfigFields } from '../components/fttx/FttxConfigFields';
import { AutoDesignDrawer } from '../features/network-map/design/AutoDesignDrawer';
import { DesignToolbar } from '../features/network-map/design/DesignToolbar';
import { ValidationPanel } from '../features/network-map/design/DesignDrawers';

const api = vi.mocked(designApi);

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const DESIGN: Design = {
  id: 'd1', project_id: 'p1', project_name: 'Allen Avenue FTTH', name: 'Phase 1', description: null, status: 'DRAFT',
  boundary: { type: 'MultiPolygon', coordinates: [] }, bbox: [3.35, 6.598, 3.353, 6.601],
  engine_config: { coverage_pct: 90, keep_me: 'yes' },
  current_version: { id: 'v1', version_no: 1, label: null, creation_method: 'INITIAL', created_at: '2026-09-26T10:00:00Z' },
  input_counts: { road: 8, homepass: 96, pole: 0, building: 0, pickup: 0, existing_structure: 0 },
  created_at: '2026-09-26T10:00:00Z', updated_at: '2026-09-26T10:00:00Z',
};

const EMPTY: DesignSummary = { homepasses: 96, customers: 120, fdt: 0, fat: 0, splitters: 0, closures: 0, poles: 0,
  cable_km: 0, errors: 0, warnings: 0, validated_at: null };
const FULL: DesignSummary = { ...EMPTY, fdt: 3, fat: 17, splitters: 17, closures: 1, cable_km: 4.2 };

const status = (over: Partial<DesignGenerateStatus>): DesignGenerateStatus => ({
  run_id: 'r1', status: 'running', progress_pct: 45, progress_message: 'Routing box-to-box cables', error_message: null,
  result_summary: null, design_version: null, created_at: null, started_at: null, completed_at: null, ...over,
});

beforeEach(() => vi.clearAllMocks());

describe('FTTx settings (shared by the wizard and the drawer)', () => {
  it('reads defaults and writes back, keeping unknown keys', () => {
    const s = settingsFromConfig({ coverage_pct: 80, extra: 1 });
    expect(s).toMatchObject({ deployment_type: 'aerial', cascade_architecture: 'pcc', pon_architecture: 'single_pon',
      coverage_pct: '80', optical_enabled: true });
    const cfg = settingsToConfig({ ...s, cascade_architecture: 'legacy', pon_architecture: 'dual_pon', coverage_pct: 'x' }, { extra: 1 });
    expect(cfg).toMatchObject({ extra: '1', pon_architecture: 'single_pon', coverage_pct: 100 });   // legacy forces 1 PON
  });

  it('round-trips a saved JSON splitter pattern without turning JSON tokens into splitter names', () => {
    const saved = { splitter_pattern: ['1x9', '1x9', '1x9', '1x8'] };
    const settings = settingsFromConfig(saved);
    const roundTripped = settingsToConfig(settings, saved);
    expect(roundTripped.splitter_pattern).toEqual(saved.splitter_pattern);
  });

  it('is a controlled form', async () => {
    const onChange = vi.fn();
    render(<FttxConfigFields value={settingsFromConfig({})} onChange={onChange} showProject={false} />);
    expect(screen.queryByLabelText('Project Name')).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Coverage (%)'), '5');
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ coverage_pct: '1005' }));
  });
});

describe('AutoDesignDrawer', () => {
  const props = { onClose: () => {}, onIssues: () => {} };

  it('runs straight away on an empty design, with the chosen settings', async () => {
    api.generate.mockResolvedValue({ ...status({ status: 'queued', progress_pct: 0 }), notes: ['1 homepass outside the boundary was left out'] });
    wrap(<AutoDesignDrawer design={DESIGN} summary={EMPTY} status={null} {...props} />);
    expect(screen.getByText('8 road segments')).toBeInTheDocument();
    expect(screen.getByText('96 homepasses, 120 customers')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Design automatically' }));
    await waitFor(() => expect(api.generate).toHaveBeenCalledWith('d1', {
      engine_config: expect.objectContaining({ coverage_pct: 90, keep_me: 'yes', deployment_type: 'aerial' }), replace: false,
    }));
    expect(await screen.findByText('1 homepass outside the boundary was left out')).toBeInTheDocument();
  });

  it('asks before replacing a design that has content, and says the old one is kept', async () => {
    api.generate.mockResolvedValue(status({ status: 'queued' }));
    wrap(<AutoDesignDrawer design={DESIGN} summary={FULL} status={null} {...props} />);
    await userEvent.click(screen.getByRole('button', { name: 'Redesign automatically' }));
    const dialog = screen.getByRole('alertdialog', { name: /Replace the current design/ });
    expect(within(dialog).getByText(/kept as version 1/)).toBeInTheDocument();
    expect(api.generate).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Replace and design' }));
    await waitFor(() => expect(api.generate).toHaveBeenCalledWith('d1', expect.objectContaining({ replace: true })));
  });

  it('shows progress while the engine runs and cannot start another', () => {
    wrap(<AutoDesignDrawer design={DESIGN} summary={EMPTY} status={status({})} {...props} />);
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '45');
    expect(screen.getByText('45% · Routing box-to-box cables')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Designing…' })).toBeDisabled();
  });

  it('explains a failed run and that nothing changed', () => {
    const { unmount } = wrap(<AutoDesignDrawer design={DESIGN} summary={EMPTY}
      status={status({ status: 'failed', error_message: 'Drop cable length exceeded: FAT-01A-03 -> Customer_19 is 200.06m (max 151.00m)' })} {...props} />);
    const alert = screen.getByRole('alert');
    expect(within(alert).getByText(/Drop cable length exceeded/)).toBeInTheDocument();
    expect(within(alert).getByText('Nothing in the design was changed.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /documented B2B exceptions/i })).not.toBeInTheDocument();
    unmount();
    wrap(<AutoDesignDrawer design={DESIGN} summary={EMPTY}
      status={status({ status: 'failed', error_message: '[B2B_ROUTING_FAILED] 71 box-to-box hops could not be routed' })} {...props} />);
    expect(screen.queryByRole('button', { name: /documented B2B exceptions/i })).not.toBeInTheDocument();
  });

  it('only offers B2B exception completion for the B2B hop-limit failure', async () => {
    api.generate.mockResolvedValue(status({ status: 'queued' }));
    wrap(<AutoDesignDrawer design={DESIGN} summary={EMPTY}
      status={status({ status: 'failed', error_message: '[CABLE_LENGTH_EXCEEDED] 2 box-to-box cables exceed their hop limit' })} {...props} />);

    await userEvent.click(screen.getByRole('button', { name: 'Complete design with documented B2B exceptions' }));

    await waitFor(() => expect(api.generate).toHaveBeenCalledWith('d1', {
      engine_config: expect.objectContaining({ allow_documented_b2b_exceptions: true }),
      replace: false,
    }));
  });

  it('confirms replacement before retrying an existing design with B2B exceptions', async () => {
    api.generate.mockResolvedValue(status({ status: 'queued' }));
    wrap(<AutoDesignDrawer design={DESIGN} summary={FULL}
      status={status({ status: 'failed', error_message: '[CABLE_LENGTH_EXCEEDED] 1 box-to-box cable exceeds its hop limit' })} {...props} />);

    await userEvent.click(screen.getByRole('button', { name: 'Complete design with documented B2B exceptions' }));
    const dialog = screen.getByRole('alertdialog', { name: /B2B exceptions/ });
    expect(within(dialog).getByText(/flagged and costed for engineering sign-off/)).toBeInTheDocument();
    expect(api.generate).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Replace and complete with exceptions' }));

    await waitFor(() => expect(api.generate).toHaveBeenCalledWith('d1', {
      engine_config: expect.objectContaining({ allow_documented_b2b_exceptions: true }),
      replace: true,
    }));
  });

  it('summarises the finished run', async () => {
    const onIssues = vi.fn();
    wrap(<AutoDesignDrawer design={DESIGN} summary={FULL} onClose={() => {}} onIssues={onIssues}
      status={status({ status: 'completed', progress_pct: 100, design_version: { id: 'v2', version_no: 2 },
        completed_at: new Date().toISOString(),
        result_summary: { design: { version_no: 2, counts: { FDT: 3, FAT: 17, DROP: 120 }, warnings: [],
          validation: { errors: 0, warnings: 2, info: 0 } } } })} />);
    expect(screen.getByText(/Version 2 designed/)).toBeInTheDocument();
    expect(screen.getByText('3 FDTs · 17 FATs · 120 drops')).toBeInTheDocument();
    expect(screen.getByText('Checked: 0 errors, 2 warnings.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'See the issues' }));
    expect(onIssues).toHaveBeenCalled();
  });

  it('will not run without roads, or on a design in review', () => {
    const { unmount } = wrap(<AutoDesignDrawer design={{ ...DESIGN, input_counts: { ...DESIGN.input_counts, road: 0 } }}
      summary={EMPTY} status={null} {...props} />);
    expect(screen.getByText(/Upload the roads first/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Design automatically' })).toBeDisabled();
    unmount();
    wrap(<AutoDesignDrawer design={{ ...DESIGN, status: 'UNDER_REVIEW' }} summary={EMPTY} status={null} {...props} />);
    expect(screen.getByText(/under review; it can't be redesigned/)).toBeInTheDocument();
  });

  it('imports a completed run from the FTTx Designer', async () => {
    api.importableRuns.mockResolvedValue([{ id: 'run9', name: 'Kokona phase 1', completed_at: null, from_this_design: false,
      fdt_count: 3, fat_count: 17, homepass_count: 96, deployment_type: 'aerial', pon_architecture: 'single_pon' }]);
    api.importRun.mockResolvedValue({ version_no: 2, counts: {}, warnings: [], validation: { errors: 0, warnings: 0, info: 0 },
      inputs_copied: ['road', 'homepass'] });
    wrap(<AutoDesignDrawer design={DESIGN} summary={EMPTY} status={null} {...props} />);
    await userEvent.click(screen.getByRole('button', { name: /Import an existing run/ }));
    expect(await screen.findByText('Kokona phase 1')).toBeInTheDocument();
    expect(screen.getByText('3 FDTs · 17 FATs · 96 homepasses')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Import' }));
    await waitFor(() => expect(api.importRun).toHaveBeenCalledWith('d1', 'run9', false));
    expect(await screen.findByText('Imported as version 2; copied its road, homepass inputs.')).toBeInTheDocument();
  });
});

describe('toolbar and validation drawer', () => {
  it('shows the run on the Auto design button; manual design still arrives next', () => {
    render(<DesignToolbar editable validating={false} drawer={null} issueCount={null} onValidate={() => {}}
      onDrawer={() => {}} onAutoDesign={() => {}} autoProgress={62} />);
    expect(screen.getByLabelText('designing, 62%')).toHaveTextContent('62%');
    expect(screen.getByRole('button', { name: /Auto design/ })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Manual design' })).toBeDisabled();
    expect(screen.getByText('Manual design arrives next')).toBeInTheDocument();
  });

  it("lists the engine's own findings for an auto-designed version", async () => {
    render(<ValidationPanel validation={{ issues: [], summary: { errors: 0, warnings: 0, info: 0 } }} loading={false}
      error={null} validating={false} validateError={null} validatedAt="2026-09-27T10:00:00Z" focusId={null}
      engineFindings={[{ severity: 'WARNING', category: 'B2B_LENGTH_EXCEPTION', message: '2 box-to-box cables exceed their hop limit' }]}
      onValidate={() => {}} onView={() => {}} onClose={() => {}} />);
    await userEvent.click(screen.getByText('From the engine run'));
    expect(screen.getByText('2 box-to-box cables exceed their hop limit')).toBeVisible();
    expect(screen.getByText('Warning · B2B_LENGTH_EXCEPTION')).toBeInTheDocument();
  });
});
