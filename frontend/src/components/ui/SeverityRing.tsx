// ============================================================
// OPSYN UI — SeverityRing  (Stage 3 new)
// SVG circle stroke-dashoffset progress ring.
// Colors by severity: critical=red, high=amber, medium=indigo, low=green, none=border
// Score: 0–100 (controls how much of the ring is filled)
// ============================================================

export type SeverityLevel = 'critical' | 'high' | 'medium' | 'low' | 'none';

export interface SeverityRingProps {
  score?:       number;          // 0–100
  severity?:    SeverityLevel;
  size?:        number;          // outer diameter in px (default 40)
  strokeWidth?: number;          // ring stroke width (default 4)
  label?:       string;          // centre label text (e.g. "72")
  style?:       React.CSSProperties;
}

const COLORS: Record<SeverityLevel, string> = {
  critical: 'var(--color-red)',
  high:     'var(--color-amber)',
  medium:   'var(--color-indigo)',
  low:      'var(--color-green)',
  none:     'var(--color-border)',
};

// ══ SEVERITY RING ═════════════════════════════════════════════
export function SeverityRing({
  score       = 0,
  severity    = 'none',
  size        = 40,
  strokeWidth = 4,
  label,
  style,
}: SeverityRingProps) {
  const radius      = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const clampedScore = Math.max(0, Math.min(100, score));
  const offset      = circumference * (1 - clampedScore / 100);
  const color       = COLORS[severity];
  const cx          = size / 2;
  const cy          = size / 2;

  return (
    <div style={{
      position: 'relative',
      display:  'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      width:    size,
      height:   size,
      flexShrink: 0,
      ...style,
    }}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        aria-hidden="true"
        style={{ transform: 'rotate(-90deg)', position: 'absolute', top: 0, left: 0 }}
      >
        {/* Track */}
        <circle
          cx={cx} cy={cy} r={radius}
          fill="none"
          stroke="var(--color-surface-2)"
          strokeWidth={strokeWidth}
        />
        {/* Progress arc */}
        <circle
          cx={cx} cy={cy} r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: 'stroke-dashoffset 500ms ease, stroke 300ms ease' }}
        />
      </svg>

      {/* Centre label */}
      {label !== undefined && (
        <span style={{
          fontFamily:  'var(--font-display)',
          fontSize:    size > 32 ? Math.round(size * 0.28) : 9,
          fontWeight:  700,
          color,
          lineHeight:  1,
          position:    'relative',
        }}>
          {label}
        </span>
      )}
    </div>
  );
}
