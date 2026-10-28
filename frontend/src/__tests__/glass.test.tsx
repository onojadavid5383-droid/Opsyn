// ============================================================
// Phase 2 — glass layer: refraction math + behaviour of every component
// (focus, keyboard, ARIA, nesting). Visuals are checked in the preview page.
// ============================================================

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useRef, useState } from 'react';
import {
  GlassCommandPalette, GlassDrawer, GlassMenu, GlassModal, GlassSelect,
  GlassButton, GlassToolbar, scoreCommand, type PaletteCommand,
} from '../components/glass';
import {
  GLASS_PRESET, computeDisplacementField, decodeByte, encodeOffset,
  isRefractionSupported, resolveRadius,
} from '../components/glass/refraction';
import { useLiquidGlass } from '../hooks/useLiquidGlass';

// ── Refraction math ──────────────────────────────────────────

describe('refraction field', () => {
  const W = 200, H = 120, R = 12, PAGE_W = 1440, PAGE_H = 900;
  const field = computeDisplacementField(W, H, R, PAGE_W, PAGE_H, GLASS_PRESET);
  const at = (px: number, py: number) => {
    const i = py * field.bw + px;
    return Math.hypot(field.dx[i], field.dy[i]);
  };

  it('leaves the centre undistorted with warp off (text stays legible)', () => {
    expect(at(field.bw / 2, field.bh / 2)).toBeLessThan(0.01);
  });

  it('bends most at the rim', () => {
    const rim = at(field.bw / 2, 1);
    expect(rim).toBeGreaterThan(1);
    expect(rim).toBeGreaterThan(at(field.bw / 2, 20) * 10);
  });

  it('supersamples small panels 2x', () => {
    expect(field.bw).toBe(W * 2);
    expect(field.bh).toBe(H * 2);
  });

  it('keeps the neutral drift sub-pixel (bytes cannot encode exactly zero)', () => {
    const drift = Math.abs(decodeByte(encodeOffset(0, field.scale), field.scale));
    expect(drift).toBeLessThanOrEqual(field.scale / 510 + 1e-9);
    expect(drift).toBeLessThan(1);
  });

  it('resolves px and % radii', () => {
    expect(resolveRadius('12px', 200, 120)).toBe(12);
    expect(resolveRadius('50%', 200, 120)).toBe(60);
  });
});

describe('useLiquidGlass', () => {
  function Panel() {
    const ref = useRef<HTMLDivElement>(null);
    useLiquidGlass(ref);
    return <div ref={ref} data-testid="panel" className="liquid-glass" />;
  }

  it('is inert outside Chromium, leaving the CSS blur fallback', () => {
    expect(isRefractionSupported()).toBe(false);  // jsdom UA
    render(<Panel />);
    expect(screen.getByTestId('panel').style.getPropertyValue('backdrop-filter')).toBe('');
    expect(screen.getByTestId('panel').dataset.glassRefraction).toBeUndefined();
  });
});

// ── GlassModal ───────────────────────────────────────────────

describe('GlassModal', () => {
  it('is a labelled modal dialog that takes focus and closes on Escape', async () => {
    const onClose = vi.fn();
    render(
      <GlassModal open onClose={onClose} title="Forward task" description="Pick a colleague">
        <button>Forward</button>
      </GlassModal>,
    );
    const dialog = await screen.findByRole('dialog', { name: 'Forward task' });
    expect(dialog).toHaveAccessibleDescription('Pick a colleague');
    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement));

    fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes from its close button', async () => {
    const onClose = vi.fn();
    render(<GlassModal open onClose={onClose} title="Block task"><p>Body</p></GlassModal>);
    await userEvent.click(await screen.findByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('Escape inside a menu opened from the modal closes only the menu', async () => {
    const onClose = vi.fn();
    render(
      <GlassModal open onClose={onClose} title="Task TSK-2026-0142">
        <GlassMenu
          label="Task actions"
          items={[{ id: 'fwd', label: 'Forward', onSelect: () => {} }]}
          renderTrigger={p => <button {...p}>Actions</button>}
        />
      </GlassModal>,
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Actions' }));
    const menu = await screen.findByRole('menu', { name: 'Task actions' });

    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(menu).not.toBeInTheDocument());
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});

// ── GlassMenu ────────────────────────────────────────────────

describe('GlassMenu', () => {
  it('opens on click, runs an item, and closes', async () => {
    const onForward = vi.fn();
    const onDelete = vi.fn();
    render(
      <GlassMenu
        label="Task actions"
        items={[
          { id: 'fwd', label: 'Forward', onSelect: onForward },
          { type: 'separator' },
          { id: 'del', label: 'Delete task', danger: true, disabled: true, onSelect: onDelete },
        ]}
        renderTrigger={p => <button {...p}>Actions</button>}
      />,
    );
    const trigger = screen.getByRole('button', { name: 'Actions' });
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');

    await userEvent.click(trigger);
    const menu = await screen.findByRole('menu');
    expect(within(menu).getAllByRole('menuitem')).toHaveLength(2);

    await userEvent.click(within(menu).getByRole('menuitem', { name: 'Delete task' }));
    expect(onDelete).not.toHaveBeenCalled();  // disabled

    await userEvent.click(within(menu).getByRole('menuitem', { name: 'Forward' }));
    expect(onForward).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
  });
});

// ── GlassSelect ──────────────────────────────────────────────

describe('GlassSelect', () => {
  function Harness({ onChange }: { onChange: (v: string) => void }) {
    const [value, setValue] = useState('lagos');
    return (
      <GlassSelect
        label="Region"
        placeholder="All regions"
        value={value}
        onChange={v => { setValue(v); onChange(v); }}
        options={[
          { label: 'Lagos', value: 'lagos' },
          { label: 'Abuja', value: 'abuja' },
          { label: 'Kano',  value: 'kano', disabled: true },
        ]}
        hint="Outages in this region only"
      />
    );
  }

  it('names the trigger by label and current value, like a native select', () => {
    render(<Harness onChange={() => {}} />);
    const trigger = screen.getByRole('combobox', { name: 'Region Lagos' });
    expect(trigger).toHaveAttribute('aria-haspopup', 'listbox');
    expect(trigger).toHaveAccessibleDescription('Outages in this region only');
  });

  it('selects an option and reports the new value', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.click(screen.getByRole('combobox', { name: /Region/ }));
    const listbox = await screen.findByRole('listbox', { name: 'Region' });

    expect(within(listbox).getByRole('option', { name: 'Lagos' })).toHaveAttribute('aria-selected', 'true');
    expect(within(listbox).getByRole('option', { name: 'All regions' })).toBeInTheDocument();

    await userEvent.click(within(listbox).getByRole('option', { name: 'Abuja' }));
    expect(onChange).toHaveBeenCalledWith('abuja');
    expect(screen.getByRole('combobox', { name: 'Region Abuja' })).toBeInTheDocument();
  });

  it('ignores disabled options', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.click(screen.getByRole('combobox', { name: /Region/ }));
    await userEvent.click(await screen.findByRole('option', { name: 'Kano' }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('exposes errors to assistive tech', () => {
    render(
      <GlassSelect label="Severity" value="" onChange={() => {}} options={[]} error="Choose a severity" />,
    );
    const trigger = screen.getByRole('combobox', { name: /Severity/ });
    expect(trigger).toHaveAttribute('aria-invalid', 'true');
    expect(trigger).toHaveAccessibleDescription('Choose a severity');
  });
});

// ── GlassCommandPalette ──────────────────────────────────────

describe('GlassCommandPalette', () => {
  const make = (id: string, label: string, group: string, onSelect = vi.fn(), keywords?: string[]): PaletteCommand =>
    ({ id, label, group, onSelect, keywords });

  it('ranks label prefixes above other matches', () => {
    const outage = make('o', 'Outages', 'Pages');
    const map = make('m', 'Network map', 'Pages', vi.fn(), ['outages on map']);
    expect(scoreCommand(outage, 'out')).toBeGreaterThan(scoreCommand(map, 'out'));
    expect(scoreCommand(make('x', 'Settings', 'Pages'), 'zzz')).toBe(0);
  });

  it('filters as you type and runs the active result on Enter', async () => {
    const openTasks = vi.fn();
    const onClose = vi.fn();
    render(
      <GlassCommandPalette
        open
        onClose={onClose}
        commands={[
          make('dash', 'Command Center', 'Pages'),
          make('tasks', 'Tasks', 'Pages', openTasks),
          make('map', 'Network map', 'Pages'),
        ]}
      />,
    );
    const input = await screen.findByRole('combobox', { name: 'Search commands' });
    await waitFor(() => expect(input).toHaveFocus());

    await userEvent.type(input, 'tas');
    expect(screen.getAllByRole('option')).toHaveLength(1);
    expect(input).toHaveAttribute('aria-activedescendant', screen.getByRole('option').id);

    await userEvent.keyboard('{Enter}');
    expect(openTasks).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalled();
  });

  it('explains an empty result', async () => {
    render(<GlassCommandPalette open onClose={() => {}} commands={[make('a', 'Audit', 'Pages')]} />);
    await userEvent.type(await screen.findByRole('combobox'), 'qqqq');
    expect(screen.getByText(/No matches for “qqqq”/)).toBeInTheDocument();
  });
});

// ── GlassToolbar / GlassButton ───────────────────────────────

describe('GlassToolbar', () => {
  it('is one tab stop with arrow-key navigation', async () => {
    render(
      <GlassToolbar label="Map controls">
        <GlassButton shape="icon" aria-label="Zoom in" icon="+" />
        <GlassButton shape="icon" aria-label="Zoom out" icon="−" />
        <GlassButton shape="icon" aria-label="Layers" icon="≡" />
      </GlassToolbar>,
    );
    const toolbar = screen.getByRole('toolbar', { name: 'Map controls' });
    const [zoomIn, zoomOut, layers] = within(toolbar).getAllByRole('button');
    expect(zoomIn).toHaveAttribute('tabindex', '0');
    expect(zoomOut).toHaveAttribute('tabindex', '-1');

    act(() => zoomIn.focus());
    fireEvent.keyDown(zoomIn, { key: 'ArrowRight' });
    expect(zoomOut).toHaveFocus();
    fireEvent.keyDown(zoomOut, { key: 'End' });
    expect(layers).toHaveFocus();
    fireEvent.keyDown(layers, { key: 'ArrowRight' });
    expect(zoomIn).toHaveFocus();  // wraps
  });

  it('toolbar buttons carry no glass surface of their own (no nested blur)', () => {
    render(
      <GlassToolbar label="Bulk actions">
        <GlassButton>Acknowledge</GlassButton>
      </GlassToolbar>,
    );
    expect(screen.getByRole('button', { name: 'Acknowledge' })).not.toHaveClass('liquid-glass-chip');
  });
});

// ── GlassDrawer ──────────────────────────────────────────────

describe('GlassDrawer (docked)', () => {
  it('is a named landmark that closes on Escape from inside', async () => {
    const onOpenChange = vi.fn();
    render(
      <GlassDrawer open onOpenChange={onOpenChange} side="right" as="aside" label="Asset inspector" title="OLT-LAG-03">
        <button>Trace path</button>
      </GlassDrawer>,
    );
    const panel = screen.getByRole('complementary', { name: 'OLT-LAG-03' });
    fireEvent.keyDown(within(panel).getByRole('button', { name: 'Trace path' }), { key: 'Escape' });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
