// ============================================================
// OPSYN — Page scaffold
//   <Page>                      scroll container + max-width content column
//   <PageHeader title lede      one heading per page, the same everywhere
//     primary={<Button/>}       the page's main action, always visible
//     secondary={[...]}         other actions: buttons on tablet+, folded
//   />                          into a "More actions" glass menu on phones
//   <PageStats items=[...]/>    compact solid summary line under the header
// Solid surfaces only — glass is for what floats (the overflow menu).
// ============================================================

import { MoreHorizontal } from 'lucide-react';
import type { ReactNode } from 'react';
import { GlassMenu, type GlassMenuEntry } from '../glass';
import { BREAKPOINTS, useMediaQuery } from '../../hooks/useMediaQuery';
import { Button } from '../ui/Button';
import s from './Page.module.css';

export function Page({ children, width = 'default', className }: {
  children: ReactNode;
  /** 'full' for workspaces (map, builders) that use every pixel */
  width?: 'default' | 'narrow' | 'full';
  className?: string;
}) {
  return (
    <div className={s.page}>
      <div className={[s.inner, s[width], className].filter(Boolean).join(' ')}>{children}</div>
    </div>
  );
}

export interface PageAction {
  id:        string;
  label:     string;
  icon?:     ReactNode;
  onSelect:  () => void;
  danger?:   boolean;
  disabled?: boolean;
}

export function PageHeader({ title, lede, primary, secondary = [], meta }: {
  title:      ReactNode;
  lede?:      ReactNode;
  /** The one main action — never hidden */
  primary?:   ReactNode;
  secondary?: PageAction[];
  /** Small status line beside the title (e.g. "Live · refreshes every 30s") */
  meta?:      ReactNode;
}) {
  const wide = useMediaQuery(BREAKPOINTS.tablet);
  const items: GlassMenuEntry[] = secondary.map(a => ({
    id: a.id, label: a.label, icon: a.icon, onSelect: a.onSelect, danger: a.danger, disabled: a.disabled,
  }));

  return (
    <header className={s.header}>
      <div className={s.headings}>
        <h1 className={s.h1}>{title}</h1>
        {lede && <p className={s.lede}>{lede}</p>}
      </div>
      {meta && <div className={s.meta}>{meta}</div>}
      {(primary || secondary.length > 0) && (
        <div className={s.actions}>
          {wide && secondary.map(a => (
            <Button key={a.id} variant={a.danger ? 'danger' : 'secondary'} size="sm" leftIcon={a.icon}
              onClick={a.onSelect} disabled={a.disabled}>
              {a.label}
            </Button>
          ))}
          {!wide && secondary.length > 0 && (
            <GlassMenu
              label="More actions"
              placement="bottom-end"
              items={items}
              renderTrigger={p => (
                <button {...p} type="button" className={s.more} aria-label="More actions">
                  <MoreHorizontal size={18} aria-hidden="true" />
                </button>
              )}
            />
          )}
          {primary}
        </div>
      )}
    </header>
  );
}

export interface PageStat { label: string; value: ReactNode; tone?: 'critical' | 'warning' | 'ok' }

export function PageStats({ items, children }: { items: PageStat[]; children?: ReactNode }) {
  return (
    <div className={s.stats}>
      <dl className={s.statList}>
        {items.map(it => (
          <div key={it.label} className={s.stat}>
            <dt>{it.label}</dt>
            <dd data-tone={it.tone}>{it.value}</dd>
          </div>
        ))}
      </dl>
      {children}
    </div>
  );
}
