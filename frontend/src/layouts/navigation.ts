// ============================================================
// OPSYN NAVIGATION — the single source of truth.
// The primary sidebar, secondary (section) sidebar, breadcrumbs, page title,
// command palette and mobile bottom nav all read from this file.
//
//   section  → a group in the primary sidebar (Monitor, Operate, …)
//   area     → a primary destination (Tasks, Infrastructure, …)
//   page     → an area's sub-page, shown in the secondary glass sidebar
//
// Every destination appears exactly once. Every path is a route in App.tsx
// (query tabs are read by useUrlTab in the page).
// ============================================================

import {
  Activity, CalendarClock, ChartColumn, ClipboardList, Contact, FolderKanban,
  LayoutDashboard, ListChecks, Map as MapIcon, Network, ScrollText, Server,
  Settings, Siren, UserCog, Workflow, type LucideIcon,
} from 'lucide-react';

export type BadgeKey = 'overdueTasks' | 'pendingOnboarding' | 'openOutages';

export interface NavPage {
  id:        string;
  label:     string;
  /** Route, optionally with ?tab=… */
  path:      string;
  keywords?: string[];
  badge?:    BadgeKey;
}

export interface NavArea extends NavPage {
  icon:      LucideIcon;
  /** Sub-pages for the secondary sidebar. The first is the area's default. */
  pages?:    NavPage[];
  /** Extra route prefixes owned by this area (detail pages, editors) */
  owns?:     string[];
}

export interface NavSection {
  id:    string;
  label: string;
  areas: NavArea[];
}

export const NAV_SECTIONS: NavSection[] = [
  {
    id: 'monitor', label: 'Monitor',
    areas: [
      { id: 'command', label: 'Command Center', path: '/dashboard', icon: LayoutDashboard, keywords: ['dashboard', 'overview', 'noc'] },
      { id: 'alarms', label: 'Alarms & outages', path: '/outage', icon: Siren, badge: 'openOutages', keywords: ['incidents', 'outage', 'sla'] },
      { id: 'map', label: 'Network map', path: '/network', icon: MapIcon, keywords: ['gis', 'map', 'fiber routes', 'olt', 'fat', 'splitter'] },
    ],
  },
  {
    id: 'operate', label: 'Operate',
    areas: [
      {
        id: 'tasks', label: 'Tasks', path: '/tasks', icon: ListChecks, badge: 'overdueTasks',
        pages: [
          { id: 'tasks-all', label: 'All tasks', path: '/tasks' },
          { id: 'tasks-inbox', label: 'Department inbox', path: '/tasks/inbox', keywords: ['queue'] },
          { id: 'tasks-analytics', label: 'Assignment analytics', path: '/tasks/analytics' },
          { id: 'tasks-deleted', label: 'Deleted tasks', path: '/tasks/deleted', keywords: ['trash', 'restore'] },
        ],
      },
      { id: 'projects', label: 'Projects', path: '/projects', icon: FolderKanban, keywords: ['pipeline'] },
      { id: 'shifts', label: 'Shifts', path: '/shifts', icon: CalendarClock, keywords: ['on call', 'roster', 'noc shifts'] },
      {
        id: 'customers', label: 'Customers', path: '/customers', icon: Contact, keywords: ['crm', 'subscribers'],
        pages: [
          { id: 'customers-all', label: 'All customers', path: '/customers' },
          { id: 'customers-fields', label: 'Customer fields', path: '/customers/forms', keywords: ['field schemas'] },
        ],
      },
    ],
  },
  {
    id: 'engineer', label: 'Engineer',
    areas: [
      {
        id: 'infrastructure', label: 'Infrastructure', path: '/infrastructure', icon: Server,
        keywords: ['assets', 'olt', 'cabinet', 'splitter', 'registry'],
        pages: [
          { id: 'infra-registry', label: 'Asset registry', path: '/infrastructure' },
          { id: 'infra-upload', label: 'Bulk upload', path: '/infrastructure/upload', keywords: ['import'] },
          { id: 'infra-deletion', label: 'Bulk deletion', path: '/infrastructure/deletion' },
          { id: 'infra-audit', label: 'Change history', path: '/infrastructure/audit', keywords: ['audit'] },
          { id: 'infra-settings', label: 'Monitoring rules', path: '/infrastructure/settings', keywords: ['thresholds', 'capacity'] },
        ],
      },
      { id: 'fttx', label: 'FTTx Designer', path: '/fttx-designer', icon: Network, keywords: ['design runs', 'planning', 'boq'] },
    ],
  },
  {
    id: 'analyze', label: 'Analyze',
    areas: [
      { id: 'reports', label: 'Reports', path: '/reports', icon: ChartColumn, keywords: ['mttr', 'analytics'] },
      { id: 'activity', label: 'Activity', path: '/activity', icon: Activity, keywords: ['timeline', 'feed'] },
      { id: 'audit', label: 'Audit log', path: '/audit', icon: ScrollText, keywords: ['events'] },
    ],
  },
  {
    id: 'admin', label: 'Admin',
    areas: [
      {
        id: 'people', label: 'People', path: '/staff', icon: UserCog, badge: 'pendingOnboarding',
        keywords: ['staff', 'personnel'],
        pages: [
          { id: 'people-staff', label: 'Staff directory', path: '/staff' },
          { id: 'people-onboarding', label: 'Onboarding', path: '/onboarding', badge: 'pendingOnboarding' },
          { id: 'people-roles', label: 'Roles & access', path: '/roles', keywords: ['permissions'] },
        ],
      },
      { id: 'workflows', label: 'Workflows', path: '/org/workflows', icon: Workflow, keywords: ['department routing'] },
      { id: 'forms', label: 'Forms', path: '/form-builder', icon: ClipboardList, keywords: ['form builder', 'submissions'] },
      {
        id: 'settings', label: 'Settings', path: '/settings', icon: Settings, owns: ['/settings/forms'],
        pages: [
          { id: 'settings-org', label: 'Organisation', path: '/settings' },
          { id: 'settings-departments', label: 'Departments', path: '/settings?tab=departments' },
          { id: 'settings-roles', label: 'Roles', path: '/settings?tab=roles' },
          { id: 'settings-regions', label: 'Regions', path: '/settings?tab=regions' },
          { id: 'settings-pipelines', label: 'Pipelines', path: '/settings?tab=pipelines' },
          { id: 'settings-integrations', label: 'Integrations', path: '/settings?tab=integrations' },
          { id: 'settings-webhooks', label: 'Webhooks', path: '/settings?tab=webhooks' },
          { id: 'settings-rules', label: 'Notification rules', path: '/settings?tab=notification-rules' },
        ],
      },
    ],
  },
];

/** Reachable routes that aren't in the sidebar (still in breadcrumbs/palette). */
export const EXTRA_PAGES: NavPage[] = [
  { id: 'notifications', label: 'Notifications', path: '/notifications', keywords: ['inbox', 'alerts'] },
];

/** Readable names for the segment after a record id (/projects/:id/pipeline). */
const DETAIL_SEGMENTS: Record<string, string> = {
  pipeline: 'Pipeline', preview: 'Preview', submissions: 'Submissions', new: 'New',
};


// ── Resolution ────────────────────────────────────────────────

export interface ActiveNav {
  section: NavSection | null;
  area:    NavArea | null;
  page:    NavPage | null;
  /** Breadcrumb trail, last item = current page title */
  crumbs:  { label: string; path?: string }[];
}

function splitPath(path: string): { pathname: string; tab: string | null } {
  const [pathname, query = ''] = path.split('?');
  return { pathname, tab: new URLSearchParams(query).get('tab') };
}

/**
 * How well a nav path matches the current location. Exact path + same tab
 * beats a prefix match; a nav path with a ?tab only matches that tab.
 * Returns 0 for no match; higher is better.
 */
export function matchScore(navPath: string, pathname: string, tab: string | null): number {
  const nav = splitPath(navPath);
  if (nav.tab !== null && nav.tab !== tab) return 0;
  if (pathname === nav.pathname) return 1000 + nav.pathname.length + (nav.tab !== null ? 1 : 0);
  if (pathname.startsWith(nav.pathname + '/')) return nav.pathname.length;
  return 0;
}

export function resolveNav(pathname: string, search: string): ActiveNav {
  const tab = new URLSearchParams(search).get('tab');
  let best: { score: number; section: NavSection; area: NavArea; page: NavPage | null } | null = null;

  for (const section of NAV_SECTIONS) {
    for (const area of section.areas) {
      const candidates: { path: string; page: NavPage | null }[] = [
        { path: area.path, page: null },
        ...(area.owns ?? []).map(path => ({ path, page: null })),
        ...(area.pages ?? []).map(page => ({ path: page.path, page })),
      ];
      for (const c of candidates) {
        const score = matchScore(c.path, pathname, tab);
        if (score > 0 && (!best || score > best.score)) best = { score, section, area, page: c.page };
      }
    }
  }

  if (!best) {
    const extra = EXTRA_PAGES.find(p => matchScore(p.path, pathname, tab) > 0);
    return {
      section: null, area: null, page: extra ?? null,
      crumbs: [{ label: extra?.label ?? 'OpSyn' }],
    };
  }

  const { section, area } = best;
  // An area with sub-pages always has an active page (its default when on the area path)
  const page = best.page ?? (area.pages ? area.pages[0] : null);
  const crumbs: ActiveNav['crumbs'] = [{ label: section.label }, { label: area.label, path: area.path }];
  if (page && area.pages && page !== area.pages[0]) crumbs.push({ label: page.label, path: page.path });

  // Record pages: /area/<id>[/<segment>]
  const base = splitPath(page?.path ?? area.path).pathname;
  const rest = pathname.startsWith(base + '/') ? pathname.slice(base.length + 1).split('/') : [];
  if (rest.length && !area.owns?.some(o => pathname.startsWith(o))) {
    const [first, second] = rest;
    crumbs.push({ label: DETAIL_SEGMENTS[first] ?? 'Details' });
    if (second) crumbs.push({ label: DETAIL_SEGMENTS[second] ?? second });
  } else if (area.owns?.some(o => pathname.startsWith(o))) {
    crumbs.push({ label: 'Form' });
  }

  return { section, area, page, crumbs };
}

/** Flat list of every destination, for the command palette. */
export function allDestinations(): { page: NavPage; area?: NavArea; section?: NavSection }[] {
  const out: { page: NavPage; area?: NavArea; section?: NavSection }[] = [];
  for (const section of NAV_SECTIONS) {
    for (const area of section.areas) {
      out.push({ page: area, area, section });
      for (const page of area.pages?.slice(1) ?? []) out.push({ page, area, section });
    }
  }
  for (const page of EXTRA_PAGES) out.push({ page });
  return out;
}
