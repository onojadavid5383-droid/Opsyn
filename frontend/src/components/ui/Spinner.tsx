// ============================================================
// OPSYN UI — Spinner
// Loading spinner with size and color variants
// ============================================================

import React from 'react';

export type SpinnerSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl';

export interface SpinnerProps {
  size?:   SpinnerSize;
  color?:  string;
  style?:  React.CSSProperties;
  center?: boolean;
}

const DIMS: Record<SpinnerSize, number> = {
  xs: 12,
  sm: 16,
  md: 22,
  lg: 32,
  xl: 48,
};

const BORDERS: Record<SpinnerSize, number> = {
  xs: 2,
  sm: 2,
  md: 2,
  lg: 3,
  xl: 3,
};

export function Spinner({ size = 'md', color = 'var(--accent-text)', style, center }: SpinnerProps) {
  const dim    = DIMS[size];
  const border = BORDERS[size];

  const spinner = (
    <span role="status" aria-label="Loading" style={{
      display:        'inline-block',
      width:          dim,
      height:         dim,
      borderRadius:   '50%',
      // Track visible on both themes (was translucent white — invisible on light)
      border:         `${border}px solid var(--border)`,
      borderTopColor: color,
      animation:      'spin .6s linear infinite',
      flexShrink:     0,
      ...style,
    }} />
  );

  if (center) {
    return (
      <div style={{
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        padding:        20,
        width:          '100%',
      }}>
        {spinner}
      </div>
    );
  }

  return spinner;
}

export function PageSpinner() {
  return (
    <div style={{
      display:        'flex',
      alignItems:     'center',
      justifyContent: 'center',
      flex:           1,
      minHeight:      200,
    }}>
      <Spinner size="lg" />
    </div>
  );
}
