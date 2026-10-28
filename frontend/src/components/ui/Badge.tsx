// ============================================================
// OPSYN UI — Badge  (Phase 4)
// A text label with a tone. Variant names are the existing API (many call
// sites compute them from data); each maps to a tone that matches meaning:
//   critical·danger·rose → critical   high·amber·coral → high
//   warning → warning (amber — was indigo, which read as "info")
//   info·blue·indigo·cyan → info      resolved·success·green → ok
//   default·draft·ghost → neutral     brand·teal → brand   violet → review
//   primary → solid brand
// For alarm severity with its shape, use StatusBadge; for workflow state,
// StateBadge (components/status).
// ============================================================

import React from 'react';
import styles from './Badge.module.css';

export type BadgeVariant =
  | 'critical' | 'high' | 'warning' | 'resolved' | 'draft'
  | 'primary' | 'danger' | 'success' | 'info'
  | 'default' | 'brand' | 'green' | 'cyan' | 'blue'
  | 'rose' | 'amber' | 'violet' | 'coral' | 'teal' | 'ghost' | 'indigo';

export type BadgeSize = 'xs' | 'sm' | 'md';

export type BadgeTone =
  | 'critical' | 'high' | 'warning' | 'info' | 'ok' | 'neutral' | 'brand' | 'review' | 'progress' | 'primary';

export interface BadgeProps {
  variant?:  BadgeVariant;
  /** Set the tone directly (new code) instead of a legacy variant name */
  tone?:     BadgeTone;
  size?:     BadgeSize;
  dot?:      boolean;
  children:  React.ReactNode;
  style?:    React.CSSProperties;
  className?: string;
}

const TONE: Record<BadgeVariant, BadgeTone> = {
  critical: 'critical', danger: 'critical', rose: 'critical',
  high: 'high', amber: 'high', coral: 'high',
  warning: 'warning',
  info: 'info', blue: 'info', indigo: 'info', cyan: 'info',
  resolved: 'ok', success: 'ok', green: 'ok',
  default: 'neutral', draft: 'neutral', ghost: 'neutral',
  brand: 'brand', teal: 'brand',
  violet: 'review',
  primary: 'primary',
};

function badgeTone(variant: BadgeVariant | undefined): BadgeTone {
  return (variant && TONE[variant]) ?? 'neutral';
}

export function Badge({ variant = 'default', tone, size = 'sm', dot = false, children, style, className }: BadgeProps) {
  return (
    <span
      className={[styles.badge, styles[tone ?? badgeTone(variant)], styles[size], className].filter(Boolean).join(' ')}
      style={style}
    >
      {dot && <span className={styles.dot} aria-hidden="true" />}
      {children}
    </span>
  );
}
