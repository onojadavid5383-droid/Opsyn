// ============================================================
// OPSYN UI — Card (a.k.a. Panel)  (Phase 4)
// Flat solid surface: 1px border, 6px radius, no hover lift.
// Same props as before. A clickable card is now a real control: focusable,
// Enter/Space activate it, and it is announced as a button.
// ============================================================

import React from 'react';
import styles from './Card.module.css';

export type CardVariant = 'default' | 'elevated' | 'inset' | 'ghost';

export interface CardProps {
  variant?:     CardVariant;
  accent?:      boolean;
  accentColor?: string;
  padding?:     number | string;
  header?:      React.ReactNode;
  footer?:      React.ReactNode;
  children:     React.ReactNode;
  skeleton?:    boolean;
  style?:       React.CSSProperties;
  onClick?:     () => void;
  /** Accessible name when the whole card is clickable */
  'aria-label'?: string;
  className?:   string;
}

const px = (p: number | string) => (typeof p === 'number' ? `${p}px` : p);

export function Card({
  variant     = 'default',
  accent      = false,
  accentColor = 'var(--accent-text)',
  padding     = 16,
  header,
  footer,
  children,
  skeleton    = false,
  style,
  onClick,
  className,
  ...aria
}: CardProps) {
  const classes = [
    styles.card,
    variant !== 'default' && styles[variant],
    onClick && styles.clickable,
    className,
  ].filter(Boolean).join(' ');

  if (skeleton) {
    return (
      <div className={classes} style={{ padding: px(padding), ...style }} aria-busy="true">
        <div className={styles.skeletonLine} style={{ height: 16, width: '60%', marginBottom: 12 }} />
        <div className={styles.skeletonLine} style={{ height: 12, marginBottom: 8 }} />
        <div className={styles.skeletonLine} style={{ height: 12, width: '80%' }} />
      </div>
    );
  }

  const interactive = onClick
    ? {
        role: 'button' as const,
        tabIndex: 0,
        onClick,
        onKeyDown: (e: React.KeyboardEvent) => {
          if (e.target !== e.currentTarget) return;  // keys inside nested controls stay theirs
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); }
        },
      }
    : {};

  return (
    <div className={classes} style={style} {...interactive} {...aria}>
      {accent && <div className={styles.accent} style={{ background: accentColor }} aria-hidden="true" />}
      {header && <div style={{ padding: px(padding), paddingBottom: 0 }}>{header}</div>}
      <div style={{ padding: px(padding) }}>{children}</div>
      {footer && (
        <div className={styles.footer} style={{ padding: `${typeof padding === 'number' ? Math.round(padding * 0.75) : 12}px ${px(padding)}` }}>
          {footer}
        </div>
      )}
    </div>
  );
}

/** The design system's name for a Card */
export const Panel = Card;
