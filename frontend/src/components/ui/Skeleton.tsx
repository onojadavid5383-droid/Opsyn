// ============================================================
// OPSYN UI — Skeleton  (Stage 3 new)
// Uses @keyframes shimmer from global.css.
// Variants: text, circle, rect (default)
// ============================================================

import React from 'react';

export interface SkeletonProps {
  variant?:  'rect' | 'text' | 'circle';
  width?:    number | string;
  height?:   number | string;
  radius?:   number | string;
  lines?:    number;          // for variant="text": number of text lines
  style?:    React.CSSProperties;
}

const SHIMMER: React.CSSProperties = {
  background:     'linear-gradient(90deg, var(--color-surface-2) 25%, var(--color-border) 50%, var(--color-surface-2) 75%)',
  backgroundSize: '200% 100%',
  animation:      'shimmer 1.5s ease-in-out infinite',
};

// ══ SKELETON ══════════════════════════════════════════════════
export function Skeleton({
  variant = 'rect',
  width,
  height,
  radius,
  lines   = 1,
  style,
}: SkeletonProps) {
  // Circle variant
  if (variant === 'circle') {
    const d = height ?? width ?? 40;
    return (
      <div style={{
        ...SHIMMER,
        width:        d,
        height:       d,
        borderRadius: '50%',
        flexShrink:   0,
        ...style,
      }} />
    );
  }

  // Text variant — N lines, last line 60% width
  if (variant === 'text') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, ...style }}>
        {Array.from({ length: lines }).map((_, i) => (
          <div key={i} style={{
            ...SHIMMER,
            height:       height ?? 14,
            width:        i === lines - 1 && lines > 1 ? '60%' : (width ?? '100%'),
            borderRadius: radius ?? 4,
          }} />
        ))}
      </div>
    );
  }

  // Default: rect
  return (
    <div style={{
      ...SHIMMER,
      width:        width ?? '100%',
      height:       height ?? 16,
      borderRadius: radius ?? 6,
      flexShrink:   0,
      ...style,
    }} />
  );
}

// ── Card skeleton convenience ──────────────────────────────────
export function SkeletonCard({ style }: { style?: React.CSSProperties }) {
  return (
    <div style={{
      background:   'var(--surface)',
      border:       '1px solid var(--color-border)',
      borderRadius: 'var(--radius-card)',
      padding:      16,
      ...style,
    }}>
      <Skeleton variant="text" lines={1} height={18} width="50%" style={{ marginBottom: 12 }} />
      <Skeleton variant="text" lines={3} height={13} />
    </div>
  );
}
