// ============================================================
// OPSYN NETWORK MAP — right-click menu on an asset (Phase 3).
// Also design mode's edit menu (Phase 6), which passes its own icons.
// A WAI-ARIA menu: focus starts on the first item, ↑/↓ move, Enter or
// click chooses, Esc or a click elsewhere closes.
// ============================================================

import { useEffect, useRef } from 'react';
import { ArrowDownFromLine, ArrowUpToLine, Copy, PanelRightOpen, type LucideIcon } from 'lucide-react';
import s from './NetworkMap.module.css';

export interface MenuAction { id: string; label: string; icon: 'details' | 'up' | 'down' | 'copy' | LucideIcon; run: () => void }

const ICONS = { details: PanelRightOpen, up: ArrowUpToLine, down: ArrowDownFromLine, copy: Copy };

export function MapContextMenu({ title, x, y, actions, onClose }: {
  title: string; x: number; y: number; actions: MenuAction[]; onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    const onDown = (e: PointerEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [onClose]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    const items = [...(ref.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])];
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length]?.focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length]?.focus(); }
    else if (e.key === 'Escape') { e.preventDefault(); onClose(); }
  };

  return (
    <div ref={ref} className={s.contextMenu} role="menu" aria-label={title} style={{ left: x, top: y }} onKeyDown={onKeyDown}>
      <div className={s.contextTitle} aria-hidden="true">{title}</div>
      {actions.map(a => {
        const Icon = typeof a.icon === 'string' ? ICONS[a.icon] : a.icon;
        return (
          <button key={a.id} type="button" role="menuitem" className={s.contextItem} onClick={() => { a.run(); onClose(); }}>
            <Icon size={15} aria-hidden /> {a.label}
          </button>
        );
      })}
    </div>
  );
}
