// ============================================================
// OPSYN THEME STORE — Zustand
// The user's light/dark preference. Light is the default; 'system' follows
// the OS. public/theme-boot.js applies the saved choice before first paint;
// this store owns every change after that. Keep the storage key and values
// in sync with that file.
// ============================================================

import { create } from 'zustand';

export type ThemePreference = 'light' | 'dark' | 'system';
export type ResolvedTheme   = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'opsyn-theme';

const isPreference = (v: unknown): v is ThemePreference =>
  v === 'light' || v === 'dark' || v === 'system';

function readPreference(): ThemePreference {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    return isPreference(saved) ? saved : 'light';
  } catch {
    return 'light';  // storage blocked (private mode, policy) — use the default
  }
}

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

export function resolveTheme(pref: ThemePreference): ResolvedTheme {
  if (pref === 'system') return systemPrefersDark() ? 'dark' : 'light';
  return pref;
}

function applyTheme(theme: ResolvedTheme) {
  document.documentElement.dataset.theme = theme;
}

interface ThemeState {
  preference: ThemePreference;
  resolved:   ResolvedTheme;
  setPreference: (pref: ThemePreference) => void;
}

export const useThemeStore = create<ThemeState>(set => {
  const preference = readPreference();
  const resolved   = resolveTheme(preference);
  if (typeof document !== 'undefined') applyTheme(resolved);

  // Follow OS changes live while the preference is 'system'
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', () => {
      const { preference: current } = useThemeStore.getState();
      if (current !== 'system') return;
      const next = resolveTheme('system');
      applyTheme(next);
      set({ resolved: next });
    });
  }

  return {
    preference,
    resolved,
    setPreference: pref => {
      try { localStorage.setItem(THEME_STORAGE_KEY, pref); } catch { /* not persisted; still applied */ }
      const next = resolveTheme(pref);
      applyTheme(next);
      set({ preference: pref, resolved: next });
    },
  };
});
