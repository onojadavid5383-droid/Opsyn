// ============================================================
// OPSYN — alarm severity: one definition for the whole app.
// Levels are the backend's own (critical · high · warning · low).
// Every severity is shown as shape + colour + text, never colour alone:
//   critical ⬣ octagon · high ▲ triangle · warning ◆ diamond · low ● circle
// Component: ./SeverityIcon.tsx
// ============================================================

import { Circle, Diamond, Octagon, Triangle, type LucideIcon } from 'lucide-react';
import type { OutageSeverity } from '@shared';

export const SEVERITY_ORDER: readonly OutageSeverity[] = ['critical', 'high', 'warning', 'low'];

export const SEVERITY_META: Record<OutageSeverity, { label: string; icon: LucideIcon; fg: string; fill: string; onFill: string; bg: string }> = {
  critical: { label: 'Critical', icon: Octagon,  fg: 'var(--status-critical-fg)', fill: 'var(--status-critical-fill)', onFill: 'var(--status-critical-on-fill)', bg: 'var(--status-critical-bg)' },
  high:     { label: 'High',     icon: Triangle, fg: 'var(--status-high-fg)',     fill: 'var(--status-high-fill)',     onFill: 'var(--status-high-on-fill)',     bg: 'var(--status-high-bg)' },
  warning:  { label: 'Warning',  icon: Diamond,  fg: 'var(--status-warning-fg)',  fill: 'var(--status-warning-fill)',  onFill: 'var(--status-warning-on-fill)',  bg: 'var(--status-warning-bg)' },
  low:      { label: 'Low',      icon: Circle,   fg: 'var(--status-low-fg)',      fill: 'var(--status-low-fill)',      onFill: 'var(--status-low-on-fill)',      bg: 'var(--status-low-bg)' },
};

export function isSeverity(value: unknown): value is OutageSeverity {
  return typeof value === 'string' && value in SEVERITY_META;
}
