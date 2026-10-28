// ============================================================
// OPSYN — command palette contents for the shell.
// Every destination in navigation.ts (grouped by section), plus shell
// actions. Record search (ticket numbers, asset IDs, customers) plugs in
// here as searchable endpoints become available.
// ============================================================

import { createElement } from 'react';
import { Bell, LogOut, Monitor, Moon, PanelLeft, Sun } from 'lucide-react';
import type { PaletteCommand } from '../components/glass';
import type { ThemePreference } from '../store/theme.store';
import { allDestinations } from './navigation';

export interface ShellActions {
  navigate:       (path: string) => void;
  setTheme:       (pref: ThemePreference) => void;
  toggleSidebar?: () => void;
  signOut:        () => void;
}

const icon = (c: typeof Bell) => createElement(c, { size: 16 });

export function buildShellCommands(actions: ShellActions): PaletteCommand[] {
  const pages: PaletteCommand[] = allDestinations().map(({ page, area, section }) => ({
    id:       `go-${page.id}`,
    label:    area && page !== area ? `${area.label}: ${page.label}` : page.label,
    group:    section?.label ?? 'Pages',
    detail:   page.path,
    keywords: [...(page.keywords ?? []), ...(area && page !== area ? area.keywords ?? [] : [])],
    icon:     area ? icon(area.icon) : icon(Bell),
    onSelect: () => actions.navigate(page.path),
  }));

  const act: PaletteCommand[] = [
    { id: 'theme-light', group: 'Actions', label: 'Use light theme',        icon: icon(Sun),     keywords: ['appearance'], onSelect: () => actions.setTheme('light') },
    { id: 'theme-dark',  group: 'Actions', label: 'Use dark theme',         icon: icon(Moon),    keywords: ['appearance', 'night', 'noc'], onSelect: () => actions.setTheme('dark') },
    { id: 'theme-sys',   group: 'Actions', label: 'Match system theme',     icon: icon(Monitor), keywords: ['appearance'], onSelect: () => actions.setTheme('system') },
    ...(actions.toggleSidebar
      ? [{ id: 'sidebar', group: 'Actions', label: 'Collapse or expand sidebar', icon: icon(PanelLeft), onSelect: actions.toggleSidebar }]
      : []),
    { id: 'signout',     group: 'Actions', label: 'Sign out',               icon: icon(LogOut),  keywords: ['log out'], onSelect: actions.signOut },
  ];

  return [...pages, ...act];
}
