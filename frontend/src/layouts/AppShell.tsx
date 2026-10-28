// ============================================================
// OPSYN APP SHELL — src/layouts/AppShell.tsx   (Phase 3 rebuild)
//
//   PrimarySidebar  solid, labelled, collapsible (remembered)      ≥1024px
//   TopBar          breadcrumbs · search (Ctrl K) · theme · notifications · account
//   HealthBar       open outages by severity · SLA risk · on call · freshness
//   SectionMenu     GLASS secondary sidebar for areas with sub-pages ≥1024px
//   SectionTabs     the same pages as a tab strip                  <1024px
//   NavDrawer       full navigation in a drawer                    <1024px
//   BottomNav       Home · Alarms · Map · Tasks · Menu             <768px
//   CommandPalette  every destination + shell actions
//
// Navigation data: ./navigation.ts. Page contract unchanged: <Outlet/> sits
// in a clipping flex column and each page owns its own scroll container.
// ============================================================

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { GlassCommandPalette, useCommandPaletteShortcut } from '../components/glass';
import ToastContainer from '../components/ui/Toast';
import { useShellLayout } from '../hooks/useMediaQuery';
import { useAuthStore } from '../store/auth.store';
import { useShellStore } from '../store/shell.store';
import { useThemeStore } from '../store/theme.store';
import BottomNav from './BottomNav';
import HealthBar from './HealthBar';
import NavDrawer from './NavDrawer';
import { resolveNav } from './navigation';
import PageBoundary from './PageBoundary';
import PrimarySidebar from './PrimarySidebar';
import { SectionMenu, SectionTabs } from './SectionMenu';
import { buildShellCommands } from './shellCommands';
import TopBar from './Topbar';
import { useShellData } from './useShellData';
import styles from './Shell.module.css';

export default function AppShell() {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const layout = useShellLayout();
  const active = useMemo(() => resolveNav(pathname, search), [pathname, search]);
  const data = useShellData();

  const { sidebar, setSidebar, sectionMenu, setSectionMenu } = useShellStore();
  const setTheme = useThemeStore(s => s.setPreference);
  const clearAuth = useAuthStore(s => s.clearAuth);

  const [navOpen, setNavOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  // No saved choice: expanded on desktop, collapsed on laptop
  const collapsed = sidebar ? sidebar === 'collapsed' : layout === 'laptop';
  const compact = layout === 'tablet' || layout === 'field';
  const toggleSidebar = useCallback(
    () => setSidebar(collapsed ? 'expanded' : 'collapsed'),
    [collapsed, setSidebar],
  );

  const area = active.area?.pages?.length ? { ...active.area, pages: active.area.pages } : null;
  const sectionDocked = !!area && !compact && sectionMenu;
  const criticalOpen = data.health.bySeverity.critical > 0;

  const openPalette = useCallback(() => setPaletteOpen(true), []);
  useCommandPaletteShortcut(openPalette);

  const commands = useMemo(() => buildShellCommands({
    navigate,
    setTheme,
    toggleSidebar: compact ? undefined : toggleSidebar,
    signOut: () => { clearAuth(); navigate('/login'); },
  }), [navigate, setTheme, compact, toggleSidebar, clearAuth]);

  // Browser tab names the page (and the open-alarm count when there is one)
  const title = active.crumbs[active.crumbs.length - 1]?.label ?? 'OpSyn';
  useEffect(() => {
    const alarms = data.health.open;
    document.title = `${alarms > 0 ? `(${alarms}) ` : ''}${title} · OpSyn`;
  }, [title, data.health.open]);

  // Route change: move focus to the new page's heading (or <main>) so screen
  // readers announce the page and keyboard users start from its top.
  // Skipped on first load and for query-only changes (tabs, filters), and
  // never pulls focus out of an open dialog.
  const mainRef = useRef<HTMLElement>(null);
  const firstPath = useRef(true);
  useEffect(() => {
    if (firstPath.current) { firstPath.current = false; return; }
    const main = mainRef.current;
    if (!main) return;
    main.scrollTop = 0;
    let frame = 0;
    let tries = 0;
    const focusPage = () => {
      const active = document.activeElement;
      if (active?.closest('[role="dialog"], [role="alertdialog"]')) return;
      const h1 = main.querySelector<HTMLElement>('h1');
      if (!h1 && tries++ < 30) { frame = requestAnimationFrame(focusPage); return; } // lazy route still loading
      const target = h1 ?? main;
      if (h1 && !h1.hasAttribute('tabindex')) h1.setAttribute('tabindex', '-1');
      target.focus({ preventScroll: true });
    };
    frame = requestAnimationFrame(focusPage);
    return () => cancelAnimationFrame(frame);
  }, [pathname]);

  return (
    <div
      className={`${styles.shell} liquid-glass-backdrop`}
      data-layout={layout}
      data-sidebar={collapsed ? 'collapsed' : 'expanded'}
    >
      <a href="#main" className={styles.skip}>Skip to content</a>

      <PrimarySidebar
        active={active}
        badges={data.badges}
        collapsed={collapsed}
        criticalOpen={criticalOpen}
        onToggle={toggleSidebar}
      />

      <TopBar
        active={active}
        layout={layout}
        unreadCount={data.unreadCount}
        onOpenNav={() => setNavOpen(true)}
        onOpenPalette={openPalette}
        sectionMenu={area && !compact ? { open: sectionMenu, onToggle: () => setSectionMenu(!sectionMenu) } : undefined}
      />

      <HealthBar
        health={data.health}
        onCall={data.onCall}
        updatedAt={data.updatedAt}
        stale={data.stale}
        loading={data.loading}
      />

      {area && compact && <SectionTabs area={area} active={active} />}

      <div className={styles.main} data-section-menu={sectionDocked || undefined}>
        {sectionDocked && area && (
          <div className={styles.sectionCell}>
            <SectionMenu
              area={area}
              active={active}
              badges={data.badges}
              open
              onOpenChange={setSectionMenu}
            />
          </div>
        )}
        <main id="main" ref={mainRef} tabIndex={-1} className={styles.page}>
          {/* Keyed by route: navigating away always clears a page error */}
          <PageBoundary key={pathname}>
            <Outlet />
          </PageBoundary>
        </main>
      </div>

      {layout === 'field' && (
        <BottomNav active={active} badges={data.badges} criticalOpen={criticalOpen} onOpenMenu={() => setNavOpen(true)} />
      )}

      <NavDrawer
        open={navOpen && compact}
        onOpenChange={setNavOpen}
        active={active}
        badges={data.badges}
        criticalOpen={criticalOpen}
      />

      <GlassCommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} commands={commands} />

      {/* Toast overlay — fixed, outside grid flow */}
      <ToastContainer />
    </div>
  );
}
