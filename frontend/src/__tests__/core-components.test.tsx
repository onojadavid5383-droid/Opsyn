// ============================================================
// Phase 4 — core components: compatibility of existing APIs + new behaviour
// ============================================================

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import {
  Badge, Button, Card, DataTable, Input, Modal, Pagination, Select, StateBadge, StatusBadge,
  ToastContainer, type Column,
} from '../components/ui';
import { ChartPanel, lineOption, barOption, readChartTheme, sparklinePath } from '../components/charts';
import { useUIStore } from '../store/ui.store';

vi.mock('../components/charts/ChartCanvas', () => ({ default: () => <div data-testid="chart-canvas" /> }));

/** Make every media query match (desktop layout) for table-mode tests */
function desktop() {
  return vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({
    matches: true, media: query, onchange: null,
    addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  }) as MediaQueryList);
}

// ── Button ───────────────────────────────────────────────────

describe('Button', () => {
  it('maps legacy variants onto the new set', () => {
    render(<>
      <Button variant="jade">Resolve</Button>
      <Button variant="rose">Delete</Button>
      <Button variant="outline">Export</Button>
    </>);
    expect(screen.getByRole('button', { name: 'Resolve' }).className).toMatch(/primary/);
    expect(screen.getByRole('button', { name: 'Delete' }).className).toMatch(/danger/);
    expect(screen.getByRole('button', { name: 'Export' }).className).toMatch(/secondary/);
  });

  it('still submits its form by default, as before', async () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    render(<form onSubmit={onSubmit}><Button variant="primary">Sign in</Button></form>);
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(onSubmit).toHaveBeenCalled();
  });

  it('is busy and disabled while loading', () => {
    render(<Button loading>Save</Button>);
    const b = screen.getByRole('button', { name: 'Save' });
    expect(b).toBeDisabled();
    expect(b).toHaveAttribute('aria-busy', 'true');
  });
});

// ── Badges ───────────────────────────────────────────────────

describe('badges', () => {
  it('Badge "warning" is the warning tone (it used to render indigo)', () => {
    render(<Badge variant="warning">Pending</Badge>);
    expect(screen.getByText('Pending').className).toMatch(/warning/);
  });

  it('StatusBadge shows the severity as text with its shape', () => {
    const { container } = render(<StatusBadge severity="critical" count={3} />);
    expect(screen.getByText('Critical')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it('StateBadge names workflow states readably', () => {
    render(<><StateBadge state="in_progress" /><StateBadge state="review" /><StateBadge state="some_custom_state" /></>);
    expect(screen.getByText('In progress')).toBeInTheDocument();
    expect(screen.getByText('In review')).toBeInTheDocument();
    expect(screen.getByText('Some custom state')).toBeInTheDocument();
  });
});

// ── Card ─────────────────────────────────────────────────────

describe('Card', () => {
  it('a clickable card is a keyboard-operable button', async () => {
    const onClick = vi.fn();
    render(<Card onClick={onClick} aria-label="Active projects">9 active</Card>);
    const card = screen.getByRole('button', { name: 'Active projects' });
    card.focus();
    await userEvent.keyboard('{Enter}');
    await userEvent.keyboard(' ');
    expect(onClick).toHaveBeenCalledTimes(2);
  });

  it('a plain card is not interactive', () => {
    render(<Card>Static</Card>);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});

// ── Fields ───────────────────────────────────────────────────

describe('Input', () => {
  it('links its label, hint and error to the control', () => {
    const { rerender } = render(<Input label="Splice loss" value="" onChange={() => {}} hint="Per splice" required />);
    const input = screen.getByRole('textbox', { name: /Splice loss/ });
    expect(input).toBeRequired();
    expect(input).toHaveAccessibleDescription('Per splice');

    rerender(<Input label="Splice loss" value="x" onChange={() => {}} error="Enter a number" />);
    expect(screen.getByRole('textbox', { name: /Splice loss/ })).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('textbox', { name: /Splice loss/ })).toHaveAccessibleDescription('Enter a number');
  });

  it('shows a unit and tells screen readers about it', () => {
    render(<Input label="Optical budget" value="28" onChange={() => {}} unit="dB" />);
    expect(screen.getByText('dB')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Optical budget' })).toHaveAccessibleDescription('in dB');
  });
});

describe('Select (now a glass listbox)', () => {
  it('keeps its props API and reports the chosen value', async () => {
    function S() {
      const [v, setV] = useState('');
      return <Select label="Region" value={v} onChange={setV} placeholder="All regions"
        options={[{ label: 'Lagos', value: 'lagos' }, { label: 'Abuja', value: 'abuja' }]} />;
    }
    render(<S />);
    await userEvent.click(screen.getByRole('combobox', { name: /Region/ }));
    await userEvent.click(await screen.findByRole('option', { name: 'Abuja' }));
    expect(screen.getByRole('combobox', { name: 'Region Abuja' })).toBeInTheDocument();
  });
});

describe('Modal (now a GlassModal)', () => {
  it('keeps its props API: title, footer, Escape closes', async () => {
    const onClose = vi.fn();
    render(<Modal open onClose={onClose} title="Log outage" footer={<button>Save</button>}><p>Body</p></Modal>);
    const dialog = await screen.findByRole('dialog', { name: 'Log outage' });
    expect(within(dialog).getByRole('button', { name: 'Save' })).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? dialog, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});

// ── DataTable ────────────────────────────────────────────────

interface Olt { id: string; name: string; ports: number | null; region: string }
const OLTS: Olt[] = [
  { id: '1', name: 'OLT-LAG-10', ports: 16, region: 'Lagos' },
  { id: '2', name: 'OLT-LAG-2', ports: 128, region: 'Lagos' },
  { id: '3', name: 'OLT-ABJ-1', ports: null, region: 'Abuja' },
];
const COLS: Column<Olt>[] = [
  { key: 'name', header: 'Name', sortable: true, mono: true, mobile: 'title' },
  { key: 'ports', header: 'Ports', sortable: true, numeric: true },
  { key: 'region', header: 'Region' },
];

describe('DataTable', () => {
  let mm: ReturnType<typeof desktop>;
  beforeEach(() => { mm = desktop(); localStorage.clear(); });
  afterEach(() => mm.mockRestore());

  const names = () => screen.getAllByRole('row').slice(1).map(r => within(r).getAllByRole('cell')[0].textContent);

  it('sorts from keyboard-reachable headers, numerically, blanks last', async () => {
    render(<DataTable columns={COLS} data={OLTS} rowKey={r => r.id} />);
    const portsHeader = screen.getByRole('columnheader', { name: /Ports/ });
    expect(portsHeader).toHaveAttribute('aria-sort', 'none');

    await userEvent.click(within(portsHeader).getByRole('button'));
    expect(portsHeader).toHaveAttribute('aria-sort', 'ascending');
    expect(names()).toEqual(['OLT-LAG-10', 'OLT-LAG-2', 'OLT-ABJ-1']);  // 16, 128, blank

    await userEvent.click(within(portsHeader).getByRole('button'));
    expect(portsHeader).toHaveAttribute('aria-sort', 'descending');

    const nameHeader = screen.getByRole('columnheader', { name: /Name/ });
    await userEvent.click(within(nameHeader).getByRole('button'));
    expect(names()).toEqual(['OLT-ABJ-1', 'OLT-LAG-2', 'OLT-LAG-10']);  // natural order: 2 before 10
  });

  it('hands sorting to the server when onSortChange is given', async () => {
    const onSortChange = vi.fn();
    render(<DataTable columns={COLS} data={OLTS} rowKey={r => r.id} sort={null} onSortChange={onSortChange} />);
    await userEvent.click(within(screen.getByRole('columnheader', { name: /Name/ })).getByRole('button'));
    expect(onSortChange).toHaveBeenCalledWith({ key: 'name', dir: 'asc' });
    expect(names()).toEqual(['OLT-LAG-10', 'OLT-LAG-2', 'OLT-ABJ-1']);  // untouched locally
  });

  it('opens a row with Enter as well as a click', async () => {
    const onRowClick = vi.fn();
    render(<DataTable columns={COLS} data={OLTS} rowKey={r => r.id} onRowClick={onRowClick} />);
    const row = screen.getAllByRole('row')[1];
    row.focus();
    await userEvent.keyboard('{Enter}');
    expect(onRowClick).toHaveBeenCalledWith(OLTS[0]);
  });

  it('selects rows and offers bulk actions in a floating bar', async () => {
    const ack = vi.fn();
    render(<DataTable columns={COLS} data={OLTS} rowKey={r => r.id} selectable rowLabel={r => r.name}
      bulkActions={(rows, clear) => <button onClick={() => { ack(rows); clear(); }}>Acknowledge</button>} />);

    await userEvent.click(screen.getByRole('checkbox', { name: 'Select OLT-LAG-2' }));
    const bar = screen.getByRole('toolbar', { name: 'Bulk actions' });
    expect(within(bar).getByText('1 selected')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('checkbox', { name: 'Select all rows' }));
    expect(within(bar).getByText('3 selected')).toBeInTheDocument();

    await userEvent.click(within(bar).getByRole('button', { name: 'Acknowledge' }));
    expect(ack.mock.calls[0][0]).toHaveLength(3);
    expect(screen.queryByRole('toolbar', { name: 'Bulk actions' })).not.toBeInTheDocument();
  });

  it('hides columns from the chooser and remembers the view', async () => {
    const { unmount } = render(<DataTable columns={COLS} data={OLTS} rowKey={r => r.id} columnChooser viewKey="olts" />);
    await userEvent.click(screen.getByRole('button', { name: /Columns/ }));
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Region' }));
    expect(screen.queryByRole('columnheader', { name: 'Region' })).not.toBeInTheDocument();
    unmount();

    render(<DataTable columns={COLS} data={OLTS} rowKey={r => r.id} columnChooser viewKey="olts" />);
    expect(screen.queryByRole('columnheader', { name: 'Region' })).not.toBeInTheDocument();
  });

  it('explains an empty table', () => {
    render(<DataTable columns={COLS} data={[]} rowKey={r => r.id} emptyTitle="No OLTs uploaded" emptyMessage="Use Bulk Upload." />);
    expect(screen.getByText('No OLTs uploaded')).toBeInTheDocument();
  });
});

describe('DataTable on a phone', () => {
  it('renders each row as a card with labelled fields', () => {
    render(<DataTable columns={COLS} data={OLTS} rowKey={r => r.id} />);  // jsdom: no media query matches
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    const cards = screen.getAllByRole('listitem');
    expect(cards).toHaveLength(3);
    expect(within(cards[1]).getByText('OLT-LAG-2')).toBeInTheDocument();
    expect(within(cards[1]).getByText('Ports')).toBeInTheDocument();
    expect(within(cards[1]).getByText('128')).toBeInTheDocument();
  });
});

// ── Pagination & toasts ──────────────────────────────────────

describe('Pagination', () => {
  it('marks the current page and bounds navigation', async () => {
    const onPage = vi.fn();
    render(<Pagination page={3} pageSize={20} total={60} onPage={onPage} />);
    expect(screen.getByRole('button', { name: 'Page 3' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled();
    expect(screen.getByText('41–60 of 60')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Previous page' }));
    expect(onPage).toHaveBeenCalledWith(2);
  });
});

describe('Toasts', () => {
  it('announce errors assertively and others politely', () => {
    render(<ToastContainer />);
    act(() => {
      useUIStore.getState().addToast({ type: 'error', title: 'Upload failed', message: 'Row 14: missing latitude' });
      useUIStore.getState().addToast({ type: 'success', title: 'Outage logged' });
    });
    expect(screen.getByRole('alert')).toHaveTextContent('Upload failed');
    expect(screen.getByRole('status')).toHaveTextContent('Outage logged');
  });
});

// ── Charts ───────────────────────────────────────────────────

describe('charts', () => {
  it('sparklines break at missing data instead of dropping to zero', () => {
    const d = sparklinePath([1, 2, null, 4], 100, 20);
    expect(d.match(/M/g)).toHaveLength(2);
    expect(sparklinePath([null, null], 100, 20)).toBe('');
  });

  it('line charts keep gaps and draw a labelled target line', () => {
    const theme = readChartTheme();
    type LineSeries = { connectNulls: boolean; markLine: { data: { yAxis: number }[]; label: { formatter: string } } };
    const opt = lineOption(theme, { categories: ['a', 'b'], series: [{ name: 'Uptime', data: [99.2, null] }], unit: '%', target: { value: 99.5, label: 'SLA 99.5%' } }) as unknown as { series: LineSeries[] };
    expect(opt.series[0].connectNulls).toBe(false);
    expect(opt.series[0].markLine.data[0].yAxis).toBe(99.5);
    expect(opt.series[0].markLine.label.formatter).toBe('SLA 99.5%');
  });

  it('horizontal bars put categories on the y axis', () => {
    const opt = barOption(readChartTheme(), { categories: ['Field Operations'], series: [{ name: 'Tasks', data: [12] }], horizontal: true }) as unknown as { xAxis: { type: string }; yAxis: { type: string } };
    expect(opt.yAxis.type).toBe('category');
    expect(opt.xAxis.type).toBe('value');
  });

  it('ChartPanel explains loading, errors and empty data', async () => {
    const retry = vi.fn();
    const { rerender } = render(<ChartPanel title="Outages opened" status="loading" />);
    expect(screen.getByLabelText('Outages opened: loading')).toHaveAttribute('aria-busy', 'true');

    rerender(<ChartPanel title="Outages opened" status="error" onRetry={retry} />);
    await userEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Try again' }));
    expect(retry).toHaveBeenCalled();

    rerender(<ChartPanel title="Outages opened" status="empty" emptyMessage="No outages in the last 30 days." />);
    expect(screen.getByText('No outages in the last 30 days.')).toBeInTheDocument();
  });

  it('ChartPanel offers the data as a table', async () => {
    render(
      <ChartPanel
        title="MTTR by severity"
        subtitle="Last 90 days"
        status="ready"
        option={t => barOption(t, { categories: ['Critical'], series: [{ name: 'MTTR', data: [3.2] }] })}
        table={{ columns: [{ key: 'sev', label: 'Severity' }, { key: 'h', label: 'Hours', numeric: true }], rows: [{ sev: 'Critical', h: 3.2 }] }}
      />,
    );
    expect(screen.getByRole('img', { name: /MTTR by severity, Last 90 days/ })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('chart-canvas')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Table' }));
    expect(screen.getByRole('table', { name: 'MTTR by severity' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: '3.2' })).toBeInTheDocument();
  });
});
