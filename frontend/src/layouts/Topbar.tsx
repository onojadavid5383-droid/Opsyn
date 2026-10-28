// ============================================================
// OPSYN — TopBar
// Breadcrumbs + page title · command palette · theme · notifications ·
// profile. Every menu here is a glass surface rendered in #overlay-root.
// ============================================================

import { Check, LogOut, Menu, Monitor, Moon, PanelLeft, Search, Settings, Sun, User } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { GlassMenu, type GlassMenuEntry } from '../components/glass';
import { usePermissions } from '../hooks/usePermissions';
import type { ShellLayout } from '../hooks/useMediaQuery';
import { useAuthStore } from '../store/auth.store';
import { useThemeStore, type ThemePreference } from '../store/theme.store';
import type { ActiveNav } from './navigation';
import NotificationsPopover from './NotificationsPopover';
import styles from './Shell.module.css';

export interface TopBarProps {
  active:             ActiveNav;
  layout:             ShellLayout;
  unreadCount:        number;
  onOpenNav:          () => void;
  onOpenPalette:      () => void;
  sectionMenu?:       { open: boolean; onToggle: () => void };
}

const THEME_ICON = { light: Sun, dark: Moon, system: Monitor } as const;
const THEME_LABEL: Record<ThemePreference, string> = { light: 'Light', dark: 'Dark', system: 'Match system' };

export default function TopBar({ active, layout, unreadCount, onOpenNav, onOpenPalette, sectionMenu }: TopBarProps) {
  const navigate = useNavigate();
  const { user, clearAuth } = useAuthStore();
  const { userName, userInitials } = usePermissions();
  const { preference, resolved, setPreference } = useThemeStore();
  const compact = layout === 'tablet' || layout === 'field';
  const roleName = user?.role?.name ?? '';

  const trail = active.crumbs.slice(0, -1);
  const current = active.crumbs[active.crumbs.length - 1];

  const themeItems: GlassMenuEntry[] = (['light', 'dark', 'system'] as const).map(p => ({
    id: `theme-${p}`,
    label: THEME_LABEL[p],
    icon: preference === p ? <Check size={16} /> : <span style={{ width: 16 }} />,
    hint: preference === p ? 'Current' : undefined,
    onSelect: () => setPreference(p),
  }));

  const profileItems: GlassMenuEntry[] = [
    { id: 'profile', label: 'My profile', icon: <User size={16} />, onSelect: () => navigate('/staff') },
    { id: 'settings', label: 'Settings', icon: <Settings size={16} />, onSelect: () => navigate('/settings') },
    { type: 'separator' },
    { id: 'signout', label: 'Sign out', icon: <LogOut size={16} />, danger: true, onSelect: () => { clearAuth(); navigate('/login'); } },
  ];

  const ThemeIcon = THEME_ICON[preference === 'system' ? 'system' : resolved];

  return (
    <header className={styles.topbar}>
      {compact && (
        <button type="button" className={styles.iconBtn} onClick={onOpenNav} aria-label="Open navigation">
          <Menu size={20} aria-hidden="true" />
        </button>
      )}

      {sectionMenu && !compact && (
        <button
          type="button"
          className={styles.iconBtn}
          onClick={sectionMenu.onToggle}
          aria-pressed={sectionMenu.open}
          aria-label={`${active.area?.label ?? 'Section'} menu`}
        >
          <PanelLeft size={18} aria-hidden="true" />
        </button>
      )}

      <nav aria-label="Breadcrumb" className={styles.crumbs}>
        <ol className={styles.crumbList}>
          {!compact && trail.map((c, i) => (
            <li key={i}>
              {c.path ? <Link to={c.path} className={styles.crumb}>{c.label}</Link> : <span className={styles.crumb}>{c.label}</span>}
            </li>
          ))}
          <li>
            <span className={styles.crumbCurrent} aria-current="page">{current?.label}</span>
          </li>
        </ol>
      </nav>

      {layout === 'desktop' ? (
        <button type="button" className={styles.search} onClick={onOpenPalette} aria-label="Search pages and commands (Ctrl K)">
          <Search size={16} aria-hidden="true" />
          <span className={styles.searchText}>Search</span>
          <kbd className={styles.kbd} aria-hidden="true">Ctrl K</kbd>
        </button>
      ) : (
        <button type="button" className={styles.iconBtn} onClick={onOpenPalette} aria-label="Search pages and commands">
          <Search size={18} aria-hidden="true" />
        </button>
      )}

      {layout !== 'field' && (
        <GlassMenu
          label="Theme"
          placement="bottom-end"
          items={themeItems}
          renderTrigger={p => (
            <button {...p} type="button" className={styles.iconBtn} aria-label={`Theme: ${THEME_LABEL[preference]}`}>
              <ThemeIcon size={18} aria-hidden="true" />
            </button>
          )}
        />
      )}

      <NotificationsPopover unreadCount={unreadCount} />

      <GlassMenu
        label="Account"
        placement="bottom-end"
        items={layout === 'field' ? [...themeItems, { type: 'separator' }, ...profileItems] : profileItems}
        header={
          <div className={styles.menuHeader}>
            <div className={styles.menuHeaderName}>{userName || 'Signed in'}</div>
            {roleName && <div className={styles.menuHeaderRole}>{roleName}</div>}
          </div>
        }
        renderTrigger={p => (
          <button {...p} type="button" className={styles.avatarBtn} aria-label={`Account: ${userName || 'signed in'}`}>
            <span className={styles.avatar} aria-hidden="true">{userInitials || '•'}</span>
            {layout === 'desktop' && (
              <span className={styles.who} aria-hidden="true">
                <span className={styles.whoName}>{userName}</span>
                {roleName && <span className={styles.whoRole}>{roleName}</span>}
              </span>
            )}
          </button>
        )}
      />
    </header>
  );
}
