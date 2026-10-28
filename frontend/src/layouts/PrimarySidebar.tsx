// ============================================================
// OPSYN — PrimarySidebar (solid) + NavTree
// Persistent, labelled, click/keyboard/touch navigation. Replaces the
// hover-only PrimaryRail + FlyoutDrawer. Collapsible to an icon rail; the
// choice is remembered (shell.store).
// ============================================================

import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { Link } from 'react-router-dom';
import OpsynMark from '../components/brand/OpsynMark';
import { GlassTooltip } from '../components/glass';
import { NAV_SECTIONS, type ActiveNav, type BadgeKey, type NavArea } from './navigation';
import styles from './Shell.module.css';

export interface NavTreeProps {
  active:    ActiveNav;
  badges:    Record<BadgeKey, number>;
  collapsed?: boolean;
  /** A critical outage is open: the alarms count turns alarm-red */
  criticalOpen?: boolean;
  /** Called after a link is followed (the drawer closes itself) */
  onNavigate?: () => void;
}

const BADGE_TEXT: Record<BadgeKey, string> = {
  openOutages:       'open',
  overdueTasks:      'overdue',
  pendingOnboarding: 'pending',
};

function NavLinkItem({ area, current, count, alert, collapsed, onNavigate }: {
  area: NavArea; current: boolean; count: number; alert: boolean; collapsed: boolean; onNavigate?: () => void;
}) {
  const Icon = area.icon;
  const countText = count > 99 ? '99+' : String(count);
  const link = (
    <Link
      to={area.path}
      className={styles.navItem}
      aria-current={current ? 'page' : undefined}
      onClick={onNavigate}
    >
      <Icon size={18} className={styles.navIcon} aria-hidden="true" />
      <span className={collapsed ? 'sr-only' : styles.navLabel}>{area.label}</span>
      {count > 0 && area.badge && (
        <span className={`${styles.count} ${alert ? styles.countAlert : ''}`}>
          <span aria-hidden="true">{countText}</span>
          <span className="sr-only">, {count} {BADGE_TEXT[area.badge]}</span>
        </span>
      )}
    </Link>
  );
  return <li>{collapsed ? <GlassTooltip content={area.label} placement="right">{link}</GlassTooltip> : link}</li>;
}

export function NavTree({ active, badges, collapsed = false, onNavigate, criticalOpen = false }: NavTreeProps) {
  return (
    <nav aria-label="Main" className={styles.navScroll}>
      {NAV_SECTIONS.map(section => (
        <div key={section.id} className={styles.navGroup}>
          <div id={`nav-${section.id}`} className={styles.navHeading}>{section.label}</div>
          <ul className={styles.navList} aria-labelledby={`nav-${section.id}`}>
            {section.areas.map(area => (
              <NavLinkItem
                key={area.id}
                area={area}
                current={active.area?.id === area.id}
                count={area.badge ? badges[area.badge] : 0}
                alert={area.badge === 'openOutages' && criticalOpen}
                collapsed={collapsed}
                onNavigate={onNavigate}
              />
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

export default function PrimarySidebar({
  active, badges, collapsed, criticalOpen, onToggle,
}: NavTreeProps & { collapsed: boolean; onToggle: () => void }) {
  return (
    <aside className={styles.sidebar} aria-label="Primary">
      <Link to="/dashboard" className={styles.brand} aria-label="OpSyn — Command Center">
        <OpsynMark size={28} glow={false} />
        {!collapsed && <span className={styles.brandName}>OpSyn</span>}
      </Link>

      <NavTree active={active} badges={badges} collapsed={collapsed} criticalOpen={criticalOpen} />

      <div className={styles.sidebarFooter}>
        <button
          type="button"
          className={styles.collapseBtn}
          onClick={onToggle}
          aria-expanded={!collapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed
            ? <PanelLeftOpen size={18} aria-hidden="true" />
            : <><PanelLeftClose size={18} aria-hidden="true" /><span>Collapse</span></>}
        </button>
      </div>
    </aside>
  );
}
