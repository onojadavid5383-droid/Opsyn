// ============================================================
// OPSYN — BottomNav (field mode, <768px)
// The four destinations a field technician needs one-handed, plus the full
// menu. 56px targets, visible labels, current page marked.
// ============================================================

import { LayoutDashboard, ListChecks, Map as MapIcon, Menu, Siren } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { ActiveNav, BadgeKey } from './navigation';
import styles from './Shell.module.css';

const ITEMS = [
  { areaId: 'command', label: 'Home',   path: '/dashboard',               icon: LayoutDashboard },
  { areaId: 'alarms',  label: 'Alarms', path: '/outage',                  icon: Siren,      badge: 'openOutages' as BadgeKey },
  { areaId: 'map',     label: 'Map',    path: '/network',  icon: MapIcon },
  { areaId: 'tasks',   label: 'Tasks',  path: '/tasks',                   icon: ListChecks, badge: 'overdueTasks' as BadgeKey },
];

export default function BottomNav({ active, badges, criticalOpen, onOpenMenu }: {
  active: ActiveNav; badges: Record<BadgeKey, number>; criticalOpen: boolean; onOpenMenu: () => void;
}) {
  return (
    <nav className={styles.bottomNav} aria-label="Quick navigation">
      {ITEMS.map(({ areaId, label, path, icon: Icon, badge }) => {
        const count = badge ? badges[badge] : 0;
        return (
          <Link key={areaId} to={path} className={styles.bottomItem} aria-current={active.area?.id === areaId ? 'page' : undefined}>
            <Icon size={20} aria-hidden="true" />
            {label}
            {count > 0 && (
              <span className={`${styles.count} ${badge === 'openOutages' && criticalOpen ? styles.countAlert : ''}`}>
                <span aria-hidden="true">{count > 99 ? '99+' : count}</span>
                <span className="sr-only">, {count} {badge === 'openOutages' ? 'open' : 'overdue'}</span>
              </span>
            )}
          </Link>
        );
      })}
      <button type="button" className={styles.bottomItem} onClick={onOpenMenu}>
        <Menu size={20} aria-hidden="true" />
        Menu
      </button>
    </nav>
  );
}
