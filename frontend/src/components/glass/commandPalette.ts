// ============================================================
// OPSYN GLASS — command palette model (no components)
// ============================================================

import { useEffect, type ReactNode } from 'react';

export interface PaletteCommand {
  id:        string;
  label:     string;
  /** Grouping heading, e.g. "Pages", "Actions", "Tasks" */
  group:     string;
  /** Secondary line, e.g. a route or record summary */
  detail?:   string;
  /** Extra search terms that don't appear in the label */
  keywords?: string[];
  icon?:     ReactNode;
  /** Right-aligned hint, e.g. a ticket number or shortcut */
  hint?:     string;
  onSelect:  () => void;
}

/**
 * Rank a command against the query: prefix of the label > word prefix >
 * substring > in-order characters across label and keywords. 0 = no match.
 */
export function scoreCommand(cmd: PaletteCommand, query: string): number {
  const q = query.trim().toLowerCase();
  if (!q) return 1;
  const label = cmd.label.toLowerCase();
  const hay = [label, cmd.detail ?? '', cmd.hint ?? '', ...(cmd.keywords ?? [])].join(' ').toLowerCase();

  if (label.startsWith(q)) return 100;
  if (label.split(/[\s/-]+/).some(w => w.startsWith(q))) return 80;
  if (hay.includes(q)) return 60;

  let at = 0;
  for (const ch of q.replace(/\s+/g, '')) {
    at = hay.indexOf(ch, at);
    if (at < 0) return 0;
    at++;
  }
  return 20;
}

/** Global Ctrl/⌘+K binding for the shell. */
export function useCommandPaletteShortcut(onOpen: () => void) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        onOpen();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onOpen]);
}
