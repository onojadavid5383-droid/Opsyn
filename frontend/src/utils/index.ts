// ============================================================
// OPSYN FRONTEND UTILITIES
// formatDate · classNames · download · errorParser · colors
// ============================================================

// ── formatDate.ts ─────────────────────────────────────────────
export function toRelative(isoString: string): string {
  const date  = new Date(isoString);
  const now   = Date.now();
  const diff  = now - date.getTime();
  const mins  = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days  = Math.floor(diff / 86400000);

  if (mins < 1)   return 'just now';
  if (mins < 60)  return `${mins} min ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days === 1) return 'yesterday';
  if (days < 7)   return `${days} days ago`;
  return toShort(isoString);
}

export function toShort(isoString: string): string {
  return new Date(isoString).toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
  });
}

export function toDateTime(isoString: string): string {
  return new Date(isoString).toLocaleString('en-GB', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  });
}

export function toISO(date: Date): string {
  return date.toISOString();
}

export function isOverdue(isoString: string): boolean {
  return new Date(isoString).getTime() < Date.now();
}

export function isToday(isoString: string): boolean {
  const d   = new Date(isoString);
  const now = new Date();
  return d.getFullYear() === now.getFullYear()
      && d.getMonth()    === now.getMonth()
      && d.getDate()     === now.getDate();
}

// ── classNames.ts ─────────────────────────────────────────────
export function cx(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(' ');
}

// ── errorParser.ts ────────────────────────────────────────────
export function parseApiError(error: unknown): string {
  if (!error) return 'An unknown error occurred';
  const e = error as any;

  // Already normalised by our client interceptor
  if (typeof e.detail === 'string') return e.detail;

  // Pydantic 422 array
  if (Array.isArray(e.detail)) {
    return e.detail.map((d: any) => `${d.field ? d.field + ': ' : ''}${d.message}`).join('; ');
  }

  // Axios error
  if (e.response?.data?.detail) {
    return typeof e.response.data.detail === 'string'
      ? e.response.data.detail
      : JSON.stringify(e.response.data.detail);
  }

  if (e.message) return e.message;
  return 'Request failed. Please try again.';
}

// ── download.ts ───────────────────────────────────────────────
export function triggerDownload(blob: Blob, filename: string): void {
  const url  = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href     = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

// ── roleLevel.ts ──────────────────────────────────────────────
const ROLE_LEVELS: Record<string, number> = {
  'Staff':             1,
  'NOC Operator':      2,
  'MEC Reviewer':      2,
  'Executive Viewer':  2,
  'Team Lead':         3,
  'Manager':           4,
  'Admin':             5,
};

export function getRoleLevel(roleName: string): number {
  return ROLE_LEVELS[roleName] ?? 0;
}

export function getRoleBadgeColor(roleName: string): { color: string; bg: string } {
  const level = getRoleLevel(roleName);
  const map: Record<number, { color: string; bg: string }> = {
    5: { color: 'var(--rose)',   bg: 'rgba(248,113,113,.1)' },
    4: { color: 'var(--coral)',  bg: 'rgba(251,146,60,.1)'  },
    3: { color: 'var(--green)',  bg: 'rgba(74,222,128,.1)'  },
    2: { color: 'var(--violet)', bg: 'rgba(167,139,250,.1)' },
    1: { color: 'var(--blue)',   bg: 'rgba(96,165,250,.1)'  },
  };
  return map[level] ?? { color: 'var(--chalk3)', bg: 'var(--bg4)' };
}

// ── colors.ts — Opsyn semantic color tokens ───────────────────
export const colors = {
  brand:  'linear-gradient(135deg, #4ade80 0%, #22d3a0 30%, #06b6d4 65%, #3b82f6 100%)',
  green:  '#4ade80',
  teal:   '#2dd4bf',
  cyan:   '#22d3ee',
  blue:   '#60a5fa',
  rose:   '#f87171',
  amber:  '#fbbf24',
  violet: '#a78bfa',
  coral:  '#fb923c',
  bg:     '#050810',
  bg2:    '#080c18',
  bg3:    '#0c1220',
  chalk:  '#e2e8f6',
  chalk2: '#8b97b0',
  chalk3: '#4a5670',
} as const;

export type ColorToken = keyof typeof colors;
