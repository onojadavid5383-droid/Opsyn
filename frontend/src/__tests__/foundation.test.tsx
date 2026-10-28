// ============================================================
// Phase 1 foundation: theme preference store + overlay portal
// ============================================================

import { render, screen } from '@testing-library/react';
import { OverlayPortal, OVERLAY_ROOT_ID } from '../components/overlay/OverlayPortal';
import { THEME_STORAGE_KEY, resolveTheme, useThemeStore } from '../store/theme.store';

describe('theme store', () => {
  afterEach(() => {
    localStorage.clear();
    useThemeStore.getState().setPreference('light');
  });

  it('defaults to light', () => {
    expect(resolveTheme('light')).toBe('light');
    expect(useThemeStore.getState().resolved).toBe('light');
  });

  it('applies, persists and resolves an explicit dark preference', () => {
    useThemeStore.getState().setPreference('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
    expect(useThemeStore.getState()).toMatchObject({ preference: 'dark', resolved: 'dark' });
  });

  it('resolves system against the OS setting (light in jsdom)', () => {
    useThemeStore.getState().setPreference('system');
    expect(useThemeStore.getState().resolved).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('still applies the theme when storage is unavailable', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    useThemeStore.getState().setPreference('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    setItem.mockRestore();
  });
});

describe('OverlayPortal', () => {
  it('renders into #overlay-root, outside the component tree', () => {
    const root = document.createElement('div');
    root.id = OVERLAY_ROOT_ID;
    document.body.appendChild(root);

    const { container } = render(<div><OverlayPortal><span>floating</span></OverlayPortal></div>);
    expect(root).toContainElement(screen.getByText('floating'));
    expect(container).not.toContainElement(screen.getByText('floating'));

    root.remove();
  });

  it('falls back to <body> when #overlay-root is absent', () => {
    render(<OverlayPortal><span>fallback</span></OverlayPortal>);
    expect(screen.getByText('fallback').parentElement).toBe(document.body);
  });
});
