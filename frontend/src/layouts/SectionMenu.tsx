// ============================================================
// OPSYN — the secondary (section) navigation
// SectionMenu  desktop/laptop: a docked GLASS sidebar listing the current
//              area's pages — floating, visibly distinct from the solid
//              primary sidebar. Only for areas that have sub-pages.
// SectionTabs  tablet/field: the same pages as a scrollable tab strip.
// ============================================================

import { Link } from 'react-router-dom';
import { GlassSidebar } from '../components/glass';
import type { ActiveNav, BadgeKey, NavArea } from './navigation';
import styles from './Shell.module.css';

interface Props {
  area:    NavArea & { pages: NonNullable<NavArea['pages']> };
  active:  ActiveNav;
  badges:  Record<BadgeKey, number>;
}

export function SectionMenu({ area, active, badges, open, onOpenChange }: Props & {
  open: boolean; onOpenChange: (open: boolean) => void;
}) {
  return (
    <GlassSidebar
      open={open}
      onOpenChange={onOpenChange}
      label={`${area.label} pages`}
      title={area.label}
      className={styles.sectionMenu}
      hideClose
    >
      <ul style={{ listStyle: 'none' }}>
        {area.pages.map(page => {
          const count = page.badge ? badges[page.badge] : 0;
          return (
            <li key={page.id}>
              <Link
                to={page.path}
                className={`liquid-glass-item ${styles.sectionLink}`}
                aria-current={active.page?.id === page.id ? 'page' : undefined}
              >
                <span style={{ flex: 1 }}>{page.label}</span>
                {count > 0 && (
                  <span className={`${styles.count} ${styles.countAlert}`}>
                    <span aria-hidden="true">{count}</span>
                    <span className="sr-only">, {count} pending</span>
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </GlassSidebar>
  );
}

export function SectionTabs({ area, active }: Omit<Props, 'badges'>) {
  return (
    <nav className={styles.tabs} aria-label={`${area.label} pages`}>
      {area.pages.map(page => (
        <Link
          key={page.id}
          to={page.path}
          className={styles.tab}
          aria-current={active.page?.id === page.id ? 'page' : undefined}
        >
          {page.label}
        </Link>
      ))}
    </nav>
  );
}
