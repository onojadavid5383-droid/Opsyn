// ============================================================
// OPSYN GLASS — GlassPanel
// A refracting panel-tier surface for one-off floating UI (map legend,
// floating filter bar, onboarding hint). Not for page sections, KPI tiles,
// tables or forms — those stay solid.
// ============================================================

import { forwardRef, useCallback, useRef, type HTMLAttributes } from 'react';
import { useLiquidGlass } from '../../hooks/useLiquidGlass';
import { cx } from './shared';

export interface GlassPanelProps extends HTMLAttributes<HTMLDivElement> {
  /** Add a reading floor so body text never depends on the backdrop */
  readable?:   boolean;
  /** Turn refraction off (the frosted CSS fallback remains) */
  refraction?: boolean;
}

export const GlassPanel = forwardRef<HTMLDivElement, GlassPanelProps>(function GlassPanel(
  { readable = false, refraction = true, className, ...rest },
  forwardedRef,
) {
  const localRef = useRef<HTMLDivElement | null>(null);
  useLiquidGlass(localRef, { enabled: refraction });

  const setRef = useCallback((node: HTMLDivElement | null) => {
    localRef.current = node;
    if (typeof forwardedRef === 'function') forwardedRef(node);
    else if (forwardedRef) forwardedRef.current = node;
  }, [forwardedRef]);

  return (
    <div
      ref={setRef}
      className={cx('liquid-glass', readable && 'liquid-glass--solid-read', className)}
      {...rest}
    />
  );
});
