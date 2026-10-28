// ============================================================
// OPSYN BRAND COMPONENTS
// OpsynMark · OpsynWordmark · PoweredBy
// ============================================================

import { useId } from 'react';

// ── OpsynMark.tsx — SVG logo mark (swirl + node icon) ────────
// The gradient id is unique per instance: with a shared id, every mark
// paints from the FIRST one's gradient — and if that copy is display:none
// (the sidebar on tablet), the others render blank.
export default function OpsynMark({ size = 32, glow = true }: { size?: number; glow?: boolean }) {
  const gid = `om-g-${useId().replace(/:/g, '')}`;
  const g = `url(#${gid})`;
  return (
    <svg
      width={size} height={size} viewBox="0 0 48 48" fill="none"
      style={{ flexShrink: 0, filter: glow ? 'drop-shadow(0 0 6px rgba(6,182,212,0.45))' : 'none' }}
      role="img"
      aria-label="Opsyn logo mark"
    >
      <defs>
        <linearGradient id={gid} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%"   stopColor="#4ade80" />
          <stop offset="35%"  stopColor="#22d3a0" />
          <stop offset="65%"  stopColor="#06b6d4" />
          <stop offset="100%" stopColor="#3b82f6" />
        </linearGradient>
      </defs>
      {/* Outer swirl ring */}
      <circle cx="24" cy="24" r="21" stroke={g} strokeWidth="3.5"
              strokeDasharray="112 24" strokeLinecap="round" opacity=".92" />
      {/* Inner swirl ring */}
      <circle cx="24" cy="24" r="15" stroke={g} strokeWidth="2"
              strokeDasharray="72 22" strokeLinecap="round" opacity=".45"
              transform="rotate(60 24 24)" />
      {/* Center node */}
      <circle cx="24" cy="24" r="4" fill={g} />
      {/* Arms */}
      <line x1="24" y1="20" x2="24" y2="13" stroke={g} strokeWidth="2.2" strokeLinecap="round" />
      <circle cx="24" cy="12" r="2.2" fill={g} />
      <line x1="20" y1="24" x2="14" y2="20" stroke={g} strokeWidth="2.2" strokeLinecap="round" />
      <circle cx="13" cy="19" r="2.2" fill={g} />
      <line x1="28" y1="24" x2="34" y2="20" stroke={g} strokeWidth="2.2" strokeLinecap="round" />
      <circle cx="35" cy="19" r="2.2" fill={g} opacity=".65" />
      <line x1="24" y1="28" x2="24" y2="35" stroke={g} strokeWidth="2" strokeLinecap="round" opacity=".5" />
      <line x1="21" y1="26" x2="16" y2="32" stroke={g} strokeWidth="1.5" strokeLinecap="round" opacity=".4" />
    </svg>
  );
}

// ── PoweredBy.tsx ─────────────────────────────────────────────
export function PoweredBy({ variant = 'inline' }: { variant?: 'inline' | 'footer' }) {
  // Own gradient (it used to borrow OpsynMark's by id and went blank without one on the page)
  const gid = `pb-g-${useId().replace(/:/g, '')}`;
  const g = `url(#${gid})`;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 4,
      fontSize: variant === 'footer' ? 11 : 9,
      color: 'var(--chalk3)', letterSpacing: '.06em',
      whiteSpace: 'nowrap',
    }}>
      <span>powered by</span>
      <span style={{
        background: 'var(--brand)',
        WebkitBackgroundClip: 'text',
        WebkitTextFillColor: 'transparent',
        backgroundClip: 'text',
        fontWeight: 700, letterSpacing: '.04em',
      }}>SlimTech</span>
      {variant === 'inline' && (
        <svg width="10" height="10" viewBox="0 0 48 48" fill="none" aria-hidden="true">
          <defs>
            <linearGradient id={gid} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#4ade80" />
              <stop offset="100%" stopColor="#3b82f6" />
            </linearGradient>
          </defs>
          <circle cx="24" cy="24" r="21" stroke={g} strokeWidth="5"
                  strokeDasharray="112 24" strokeLinecap="round" opacity=".6" />
          <circle cx="24" cy="24" r="4" fill={g} />
        </svg>
      )}
    </div>
  );
}

// ── OpsynWordmark.tsx ─────────────────────────────────────────
export function OpsynWordmark({ size = 17 }: { size?: number }) {
  return (
    <span style={{
      fontFamily: 'var(--font)', fontWeight: 800,
      fontSize: size, letterSpacing: '-.01em',
      background: 'var(--brand)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      backgroundClip: 'text',
    }}>
      Opsyn
    </span>
  );
}

// ── BrandGradientText.tsx ─────────────────────────────────────
export function BrandText({ children, size }: { children: React.ReactNode; size?: number }) {
  return (
    <span style={{
      background: 'var(--brand)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      backgroundClip: 'text',
      fontWeight: 700,
      fontSize: size,
    }}>
      {children}
    </span>
  );
}
