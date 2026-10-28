// ============================================================
// OPSYN UI — EmptyState  (Phase 4)
// Emptiness is a moment for direction: say what would be here and offer
// the next step. Same props as before.
// ============================================================

import { Inbox } from 'lucide-react';
import React from 'react';
import { Button, type ButtonVariant } from './Button';
import styles from './EmptyState.module.css';

export interface EmptyStateAction {
  label:    string;
  onClick:  () => void;
  variant?: ButtonVariant;
}

export interface EmptyStateProps {
  icon?:     React.ReactNode;
  title:     string;
  message?:  string;
  action?:   EmptyStateAction;
  size?:     'sm' | 'md' | 'lg';
  style?:    React.CSSProperties;
}

const ICON: Record<'sm' | 'md' | 'lg', number> = { sm: 24, md: 32, lg: 40 };

export function EmptyState({ icon, title, message, action, size = 'md', style }: EmptyStateProps) {
  return (
    <div className={`${styles.empty} ${styles[size]}`} style={style}>
      <div className={styles.icon} aria-hidden="true">{icon ?? <Inbox size={ICON[size]} strokeWidth={1.5} />}</div>
      <p className={styles.title}>{title}</p>
      {message && <p className={styles.message}>{message}</p>}
      {action && (
        <Button variant={action.variant ?? 'secondary'} size="sm" onClick={action.onClick} style={{ marginTop: 'var(--space-4)' }}>
          {action.label}
        </Button>
      )}
    </div>
  );
}
