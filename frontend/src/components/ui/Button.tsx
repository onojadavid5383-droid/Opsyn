// ============================================================
// OPSYN UI — Button  (Phase 4)
// Variants: primary · secondary · ghost · danger · danger-solid
// Legacy names still accepted (186 call sites): brand/cyan/jade → primary,
// outline/amber → secondary, rose → danger.
// Sizes: xs 28 · sm 32 · md 36 · lg 44 (text ≥12px; ≥44px on touch).
// Hover/focus are CSS; onMouseEnter/Leave props still pass through.
// ============================================================

import React from 'react';
import styles from './Button.module.css';

export type ButtonVariant =
  | 'primary' | 'secondary' | 'danger' | 'ghost' | 'danger-solid'
  | 'brand' | 'rose' | 'jade' | 'amber' | 'outline' | 'cyan';

export type ButtonSize = 'xs' | 'sm' | 'md' | 'lg';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?:   ButtonVariant;
  size?:      ButtonSize;
  loading?:   boolean;
  fullWidth?: boolean;
  leftIcon?:  React.ReactNode;
  rightIcon?: React.ReactNode;
}

type Canonical = 'primary' | 'secondary' | 'ghost' | 'danger' | 'dangerSolid';

function canonicalVariant(v: ButtonVariant): Canonical {
  switch (v) {
    case 'brand': case 'cyan': case 'jade': return 'primary';
    case 'outline': case 'amber':           return 'secondary';
    case 'rose':                            return 'danger';
    case 'danger-solid':                    return 'dangerSolid';
    default:                                return v;
  }
}

export function Button({
  variant   = 'ghost',
  size      = 'md',
  loading   = false,
  fullWidth = false,
  leftIcon,
  rightIcon,
  disabled,
  children,
  className,
  ...rest
}: ButtonProps) {
  const isDisabled = disabled || loading;
  return (
    // No default `type`, deliberately: the old Button had none, so inside a
    // <form> it submits (the HTML default) and existing forms rely on that.
    <button
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className={[
        styles.btn,
        styles[canonicalVariant(variant)],
        styles[size],
        fullWidth && styles.full,
        className,
      ].filter(Boolean).join(' ')}
      {...rest}
    >
      {loading ? <span className={styles.spinner} aria-hidden="true" /> : leftIcon}
      {children}
      {!loading && rightIcon}
    </button>
  );
}
