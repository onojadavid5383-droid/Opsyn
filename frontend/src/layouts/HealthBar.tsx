// ============================================================
// OPSYN — HealthBar (replaces IntelStrip)
// Operational state only: open outages by severity, SLA risk, who is on
// call, and whether the numbers are fresh. Admin counts (onboarding etc.)
// live on the navigation badges instead.
//
// Severity = shape + label + count, never colour alone. Brand teal never
// appears here — it is not a status. Only a live critical moves.
// ============================================================

import { Clock, PhoneCall, TimerOff } from 'lucide-react';
import { Link } from 'react-router-dom';
import { SEVERITY_META, SEVERITY_ORDER } from '../components/status/severity';
import { SeverityIcon } from '../components/status/SeverityIcon';
import { SLA_RISK_WINDOW_MIN, type HealthSummary } from './useShellData';
import styles from './Shell.module.css';

export interface HealthBarProps {
  health:    HealthSummary;
  onCall:    number | null;
  updatedAt: number | null;
  stale:     boolean;
  loading:   boolean;
}

const hhmm = (t: number) => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

export default function HealthBar({ health, onCall, updatedAt, stale, loading }: HealthBarProps) {
  const { bySeverity, slaAtRisk, slaBreached } = health;

  return (
    // Console surface: dark in both themes, so status colours take their
    // dark-surface values. A region, not a live region — re-announcing every
    // 30 s poll would drown a screen reader.
    <section data-surface="console" className={styles.health} aria-label="Network health">
      {SEVERITY_ORDER.map(sev => {
        const n = bySeverity[sev];
        const live = sev === 'critical' && n > 0;
        return (
          <Link
            key={sev}
            to={`/outage?severity=${sev}`}
            className={styles.healthItem}
            data-zero={n === 0 || undefined}
            aria-label={`${n} ${SEVERITY_META[sev].label.toLowerCase()} outage${n === 1 ? '' : 's'} open`}
          >
            <span className={live ? styles.criticalLive : undefined} style={{ display: 'inline-flex' }}>
              <SeverityIcon severity={sev} />
            </span>
            <span className={styles.healthCount}>{loading ? '–' : n}</span>
            <span>{SEVERITY_META[sev].label}</span>
          </Link>
        );
      })}

      <span className={styles.healthDivider} aria-hidden="true" />

      <Link
        to="/outage?view=sla"
        className={styles.healthItem}
        data-zero={slaAtRisk === 0 || undefined}
        title={`Open outages within ${SLA_RISK_WINDOW_MIN} minutes of their SLA deadline`}
      >
        <Clock size={14} aria-hidden="true" color={slaAtRisk ? 'var(--status-high-fg)' : undefined} />
        <span className={styles.healthCount}>{loading ? '–' : slaAtRisk}</span>
        <span>SLA at risk</span>
      </Link>
      {slaBreached > 0 && (
        <Link to="/outage?view=sla" className={styles.healthItem}>
          <TimerOff size={14} aria-hidden="true" color="var(--status-critical-fg)" />
          <span className={styles.healthCount}>{slaBreached}</span>
          <span>SLA breached</span>
        </Link>
      )}

      <span className={styles.healthDivider} aria-hidden="true" />

      <Link to="/shifts" className={styles.healthItem} data-zero={onCall === 0 || undefined}>
        <PhoneCall size={14} aria-hidden="true" />
        <span className={styles.healthCount}>{onCall ?? '–'}</span>
        <span>On call</span>
      </Link>

      <span className={`${styles.fresh} ${stale ? styles.freshStale : ''}`} role={stale ? 'status' : undefined}>
        <span className={styles.freshDot} aria-hidden="true" />
        {stale
          ? `Live updates paused${updatedAt ? ` · last ${hhmm(updatedAt)}` : ''}`
          : updatedAt ? `Updated ${hhmm(updatedAt)}` : 'Connecting…'}
      </span>
    </section>
  );
}
