// ============================================================
// OPSYN — Command Center: where it's happening.
// Places open incidents on the network by matching their OLT reference to
// the OLTs on the map. Incidents that can't be placed are counted, not
// guessed at.
// ============================================================

import { useQuery } from '@tanstack/react-query';
import { lazy, Suspense, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { InfraMapSite, InfraMapOLT, OutageIncident, OutageSeverity } from '@shared';
import { infrastructureApi, outageApi } from '../../api/index';
import { SEVERITY_META, SEVERITY_ORDER } from '../../components/status/severity';
import { SeverityIcon } from '../../components/status/SeverityIcon';
import { placeIncidents, toArr } from './dashboardData';
import type { MiniMapProps } from './MiniMap';
import s from './Dashboard.module.css';

const MiniMap = lazy(() => import('./MiniMap'));

/** Leaflet needs concrete colours: read them from the console-surface element
 *  (a pure read, derived when the element is attached — no effect needed). */
function useConsoleColors(el: HTMLElement | null): MiniMapProps['colors'] | null {
  return useMemo(() => {
    if (!el) return null;
    const cs = getComputedStyle(el);
    const v = (n: string, f: string) => cs.getPropertyValue(n).trim() || f;
    return {
      critical: v('--status-critical-fg', '#FF6B6B'),
      high:     v('--status-high-fg', '#FF8A3D'),
      warning:  v('--status-warning-fg', '#FFC53D'),
      low:      v('--status-low-fg', '#6AA8FF'),
      asset:    v('--chart-5', '#9AAABB'),
      site:     v('--text-muted', '#8C9DAF'),
      siteAlert: v('--status-warning-fg', '#FFC53D'),
      outline:  v('--canvas', '#0B1520'),
    };
  }, [el]);
}

export default function MapPanel() {
  const map = useQuery({ queryKey: ['infrastructure', 'dashboard-map'], queryFn: () => infrastructureApi.getDashboardMap(), staleTime: 5 * 60_000 });
  const outages = useQuery({ queryKey: ['outages', 'live'], queryFn: () => outageApi.getLive(), refetchInterval: 30_000 });
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const colors = useConsoleColors(box);

  const data = map.data as { sites: InfraMapSite[]; olts: InfraMapOLT[] } | undefined;
  const sites = useMemo(() => data?.sites ?? [], [data]);
  const olts = useMemo(() => data?.olts ?? [], [data]);
  const open = useMemo(
    () => toArr<OutageIncident>(outages.data).filter(o => o.status !== 'resolved'),
    [outages.data],
  );
  const { byOlt, unplaced } = useMemo(() => placeIncidents(open, olts), [open, olts]);

  const placedBySev = useMemo(() => {
    const counts = Object.fromEntries(SEVERITY_ORDER.map(sv => [sv, 0])) as Record<OutageSeverity, number>;
    byOlt.forEach(list => list.forEach(o => { counts[o.severity]++; }));
    return counts;
  }, [byOlt]);

  const hasAssets = sites.some(x => x.latitude != null) || olts.length > 0;

  return (
    <section className={`${s.panel} ${s.map}`} aria-labelledby="cc-map">
      <header className={s.panelHead}>
        <h2 id="cc-map" className={s.panelTitle}>
          Network map
          <span className={s.panelSub}>{olts.length} OLTs · {sites.length} sites</span>
        </h2>
        <Link to="/network" className={s.link}>Open full map</Link>
      </header>

      <div
        ref={setBox}
        data-surface="console"
        className={s.mapBox}
        role="region"
        aria-label={`Map of ${olts.length} OLTs and ${sites.length} sites. ${open.length - unplaced} open incidents placed on the map.`}
      >
        {map.isPending && <p className={s.empty}>Loading map…</p>}
        {map.isError && <p className={s.empty}>The network map couldn't be loaded.</p>}
        {!map.isPending && !map.isError && !hasAssets && (
          <p className={s.mapMessage}>No mapped assets yet. Upload OLTs and sites to see them here.</p>
        )}
        {colors && (
          <Suspense fallback={<p className={s.empty}>Loading map…</p>}>
            <MiniMap sites={sites} olts={olts} incidentsByOlt={byOlt} colors={colors} />
          </Suspense>
        )}
      </div>

      <div className={s.mapLegend}>
        {SEVERITY_ORDER.filter(sv => placedBySev[sv] > 0).map(sv => (
          <span key={sv} className={s.legendItem}>
            <SeverityIcon severity={sv} size={12} /> {placedBySev[sv]} {SEVERITY_META[sv].label.toLowerCase()}
          </span>
        ))}
        {open.length > 0 && Object.values(placedBySev).every(n => n === 0) && <span>No open incidents could be placed on the map</span>}
        {open.length === 0 && <span>No open incidents</span>}
        {unplaced > 0 && <span>{unplaced} without a mapped OLT</span>}
      </div>
    </section>
  );
}
