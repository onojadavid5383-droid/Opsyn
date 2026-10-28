// ============================================================
// OPSYN GLASS — GlassCommandPalette
// Ctrl/⌘+K: jump to any page or record. This component is the UI and the
// keyboard model; the shell (Phase 3) supplies the commands — routes now,
// entity search (asset ID, ticket number, customer) as data sources allow.
// Model + shortcut hook: ./commandPalette.ts
//
// ARIA combobox pattern: focus stays in the input; ↑↓ move the active option
// (aria-activedescendant), Enter runs it, Escape closes.
// ============================================================

import { Search } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type MutableRefObject } from 'react';
import { GlassModal } from './GlassModal';
import { scoreCommand, type PaletteCommand } from './commandPalette';
import { cx } from './shared';
import styles from './GlassCommandPalette.module.css';

export interface GlassCommandPaletteProps {
  open:         boolean;
  onClose:      () => void;
  commands:     PaletteCommand[];
  placeholder?: string;
  /** Max results shown per group */
  perGroup?:    number;
}

export function GlassCommandPalette({
  open, onClose, commands, placeholder = 'Search pages, tasks, assets…', perGroup = 8,
}: GlassCommandPaletteProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  return (
    <GlassModal
      open={open}
      onClose={onClose}
      ariaLabel="Command palette"
      align="top"
      hideClose
      initialFocus={inputRef}
      className={styles.panel}
      flush
    >
      {/* Mounted only while open, so the query starts empty every time */}
      <PaletteBody
        inputRef={inputRef}
        commands={commands}
        placeholder={placeholder}
        perGroup={perGroup}
        onClose={onClose}
      />
    </GlassModal>
  );
}

function PaletteBody({
  inputRef, commands, placeholder, perGroup, onClose,
}: {
  inputRef:    MutableRefObject<HTMLInputElement | null>;
  commands:    PaletteCommand[];
  placeholder: string;
  perGroup:    number;
  onClose:     () => void;
}) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const listId = useId();

  const groups = useMemo(() => {
    const ranked = commands
      .map(cmd => ({ cmd, score: scoreCommand(cmd, query) }))
      .filter(r => r.score > 0)
      .sort((a, b) => b.score - a.score);
    const byGroup = new Map<string, PaletteCommand[]>();
    for (const { cmd } of ranked) {
      const list = byGroup.get(cmd.group) ?? [];
      if (list.length < perGroup) list.push(cmd);
      byGroup.set(cmd.group, list);
    }
    return Array.from(byGroup, ([name, items]) => ({ name, items }));
  }, [commands, query, perGroup]);

  const flat = useMemo(() => groups.flatMap(g => g.items), [groups]);
  const activeIndex = Math.min(active, Math.max(flat.length - 1, 0));
  const optionId = (i: number) => `${listId}-opt-${i}`;

  // Keep the active option in view while arrowing (DOM sync, no state)
  useEffect(() => {
    document.getElementById(`${listId}-opt-${activeIndex}`)?.scrollIntoView?.({ block: 'nearest' });
  }, [listId, activeIndex]);

  const run = (cmd: PaletteCommand | undefined) => {
    if (!cmd) return;
    onClose();
    cmd.onSelect();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    const count = Math.max(flat.length, 1);
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((activeIndex + 1) % count); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((activeIndex - 1 + count) % count); }
    else if (e.key === 'Home' && e.ctrlKey) { e.preventDefault(); setActive(0); }
    else if (e.key === 'End' && e.ctrlKey) { e.preventDefault(); setActive(flat.length - 1); }
    else if (e.key === 'Enter') { e.preventDefault(); run(flat[activeIndex]); }
  };

  let index = -1;
  return (
    <>
      <div className={styles.search}>
        <Search size={18} className={styles.searchIcon} aria-hidden="true" />
        <input
          ref={inputRef}
          className={styles.input}
          role="combobox"
          aria-expanded={flat.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={flat.length ? optionId(activeIndex) : undefined}
          aria-label="Search commands"
          placeholder={placeholder}
          value={query}
          onChange={e => { setQuery(e.target.value); setActive(0); }}
          onKeyDown={onKeyDown}
          autoComplete="off"
          spellCheck={false}
        />
        <kbd className={styles.esc}>Esc</kbd>
      </div>

      <div id={listId} role="listbox" aria-label="Results" className={styles.results}>
        {flat.length === 0 && (
          <p className={styles.empty}>No matches for “{query}”. Try a page name, ticket number or asset ID.</p>
        )}
        {groups.map(group => (
          <div key={group.name} role="group" aria-label={group.name} className={styles.group}>
            <div className={styles.groupLabel} aria-hidden="true">{group.name}</div>
            {group.items.map(cmd => {
              const i = ++index;
              const isActive = i === activeIndex;
              return (
                <div
                  key={cmd.id}
                  id={optionId(i)}
                  role="option"
                  aria-selected={isActive}
                  data-active={isActive ? 'true' : undefined}
                  className={cx('liquid-glass-item', styles.option)}
                  onMouseMove={() => { if (!isActive) setActive(i); }}
                  // mousedown, not click: keep focus in the input
                  onMouseDown={e => { e.preventDefault(); run(cmd); }}
                >
                  {cmd.icon && <span className={styles.optionIcon} aria-hidden="true">{cmd.icon}</span>}
                  <span className={styles.optionText}>
                    <span className={styles.optionLabel}>{cmd.label}</span>
                    {cmd.detail && <span className={styles.optionDetail}>{cmd.detail}</span>}
                  </span>
                  {cmd.hint && <span className={styles.optionHint}>{cmd.hint}</span>}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div className={styles.footer} aria-hidden="true">
        <span><kbd>↑</kbd> <kbd>↓</kbd> to move</span>
        <span><kbd>Enter</kbd> to open</span>
        <span><kbd>Esc</kbd> to close</span>
      </div>
    </>
  );
}
