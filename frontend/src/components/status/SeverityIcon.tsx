// ============================================================
// OPSYN — SeverityIcon: the severity's shape, in its colour.
// Decorative — always pair it with the text label (see ./severity.ts).
// ============================================================

import type { OutageSeverity } from '@shared';
import { SEVERITY_META } from './severity';

export function SeverityIcon({ severity, size = 14 }: { severity: OutageSeverity; size?: number }) {
  const { icon: Icon, fg } = SEVERITY_META[severity];
  return <Icon size={size} strokeWidth={2.25} color={fg} aria-hidden="true" style={{ flexShrink: 0 }} />;
}
