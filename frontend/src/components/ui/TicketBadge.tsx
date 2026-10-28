// ============================================================
// OPSYN UI — TicketBadge  (Stage 3 new)
// Displays TSK-YYYY-NNNN / PRJ-YYYY-NNNN identifiers.
// Click to copy to clipboard — teal flash + checkmark for 1.5s.
// Font: --font-mono (JetBrains Mono)
// ============================================================

import { useState } from 'react';

export interface TicketBadgeProps {
  id:      string;   // e.g. "TSK-2024-0042" or "PRJ-2024-0011"
  style?:  React.CSSProperties;
}

// ══ TICKET BADGE ══════════════════════════════════════════════
export function TicketBadge({ id, style }: TicketBadgeProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(id);
    } catch {
      // Fallback for environments without clipboard API
      const el = document.createElement('textarea');
      el.value = id;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      onClick={handleCopy}
      title={copied ? 'Copied!' : `Click to copy ${id}`}
      style={{
        display:        'inline-flex',
        alignItems:     'center',
        gap:            5,
        fontFamily:     'var(--font-mono)',
        fontSize:       12,
        fontWeight:     600,
        letterSpacing:  '0.02em',
        // Teal as text uses the contrast-safe accent (brand teal is 2.3:1 on white)
        color:          copied ? 'var(--accent-text)' : 'var(--text-secondary)',
        background:     copied ? 'var(--brand-tint)' : 'var(--surface-sunken)',
        border:         `1px solid ${copied ? 'var(--accent-text)' : 'var(--border)'}`,
        borderRadius:   'var(--radius-badge)',
        padding:        '2px 8px',
        cursor:         'pointer',
        transition:     'color 150ms, background 150ms, border-color 150ms',
        whiteSpace:     'nowrap',
        flexShrink:     0,
        ...style,
      }}
    >
      {/* Checkmark or ticket icon */}
      {copied ? (
        <svg width={11} height={11} viewBox="0 0 12 12" fill="none"
             stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M2 6l3 3 5-5" />
        </svg>
      ) : (
        <svg width={11} height={11} viewBox="0 0 12 12" fill="none"
             stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
          <rect x="1" y="2" width="10" height="8" rx="1" />
          <path d="M4 5h4M4 7h2" />
        </svg>
      )}
      {copied ? 'Copied' : id}
    </button>
  );
}
