// ============================================================
// OPSYN SHELL STORE — Zustand
// Remembered navigation preferences (per browser):
//   sidebar       'expanded' | 'collapsed' | null — null = decide by width
//                 (expanded ≥1280px, collapsed 1024–1279px)
//   sectionMenu   whether the secondary (section) sidebar is shown
// ============================================================

import { create } from 'zustand';

export type SidebarPref = 'expanded' | 'collapsed' | null;

const SIDEBAR_KEY = 'opsyn-sidebar';
const SECTION_MENU_KEY = 'opsyn-section-menu';

function read(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* storage blocked — preference lasts for this session only */ }
}

interface ShellState {
  sidebar:        SidebarPref;
  sectionMenu:    boolean;
  setSidebar:     (pref: SidebarPref) => void;
  setSectionMenu: (open: boolean) => void;
}

export const useShellStore = create<ShellState>(set => {
  const saved = read(SIDEBAR_KEY);
  return {
    sidebar:     saved === 'expanded' || saved === 'collapsed' ? saved : null,
    sectionMenu: read(SECTION_MENU_KEY) !== 'closed',
    setSidebar: pref => { write(SIDEBAR_KEY, pref); set({ sidebar: pref }); },
    setSectionMenu: open => { write(SECTION_MENU_KEY, open ? null : 'closed'); set({ sectionMenu: open }); },
  };
});
