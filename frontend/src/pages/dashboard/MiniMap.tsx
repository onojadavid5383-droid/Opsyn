// ============================================================
// OPSYN — Command Center mini map (lazy: loads Leaflet)
// Where it's happening: OLTs and sites on the dark console basemap, with
// OLTs that have open incidents marked by severity SHAPE and colour — the
// same shapes as StatusBadge (⬣ ▲ ◆ ●), so colour is never the only cue.
// Overview only: no scroll-zoom; the full map is one click away.
// ============================================================

import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { useEffect, useMemo } from 'react';
import { CircleMarker, MapContainer, Marker, Tooltip, useMap } from 'react-leaflet';
import type { InfraMapOLT, InfraMapSite, OutageIncident, OutageSeverity } from '@shared';
import { SEVERITY_META } from '../../components/status/severity';
import { DEFAULT_BASEMAP } from '../../lib/basemap';
import { ResilientTileLayer } from '../../components/map/ResilientTileLayer';

export interface MiniMapProps {
  sites:        InfraMapSite[];
  olts:         InfraMapOLT[];
  /** Open incidents keyed by OLT id */
  incidentsByOlt: Map<string, OutageIncident[]>;
  /** Resolved colours from the console surface (Leaflet needs concrete values) */
  colors: Record<OutageSeverity | 'asset' | 'site' | 'siteAlert' | 'outline', string>;
}

const SHAPE_PATH: Record<OutageSeverity, string> = {
  critical: '<polygon points="7,1 15,1 21,7 21,15 15,21 7,21 1,15 1,7" />',
  high:     '<polygon points="11,1 21,20 1,20" />',
  warning:  '<polygon points="11,1 21,11 11,21 1,11" />',
  low:      '<circle cx="11" cy="11" r="9" />',
};

function severityIcon(sev: OutageSeverity, fill: string, outline: string) {
  return L.divIcon({
    className: '',
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    html: `<svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true"><g fill="${fill}" stroke="${outline}" stroke-width="2">${SHAPE_PATH[sev]}</g></svg>`,
  });
}

function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    map.fitBounds(L.latLngBounds(points), { padding: [24, 24], maxZoom: 13 });
  }, [map, points]);
  return null;
}

const worst = (list: OutageIncident[]): OutageSeverity =>
  (['critical', 'high', 'warning', 'low'] as OutageSeverity[]).find(s => list.some(o => o.severity === s)) ?? 'low';

export default function MiniMap({ sites, olts, incidentsByOlt, colors }: MiniMapProps) {
  const mapped = useMemo(() => ({
    sites: sites.filter(s => s.latitude != null && s.longitude != null),
    olts:  olts.filter(o => Number.isFinite(o.latitude) && Number.isFinite(o.longitude)),
  }), [sites, olts]);

  const points = useMemo<[number, number][]>(() => [
    ...mapped.sites.map(s => [s.latitude!, s.longitude!] as [number, number]),
    ...mapped.olts.map(o => [o.latitude, o.longitude] as [number, number]),
  ], [mapped]);

  const center: [number, number] = points[0] ?? [9.082, 8.6753];

  return (
    <MapContainer
      center={center}
      zoom={6}
      scrollWheelZoom={false}
      attributionControl
      style={{ position: 'absolute', inset: 0, background: '#0B1520' }}
    >
      <ResilientTileLayer basemap={DEFAULT_BASEMAP} />
      <FitBounds points={points} />

      {mapped.sites.map(site => (
        <CircleMarker
          key={site.id}
          center={[site.latitude!, site.longitude!]}
          radius={site.has_alert ? 6 : 4}
          pathOptions={{ color: colors.outline, weight: 1, fillColor: site.has_alert ? colors.siteAlert : colors.site, fillOpacity: 0.9 }}
        >
          <Tooltip>{site.name}{site.has_alert ? ' — site alert' : ''}</Tooltip>
        </CircleMarker>
      ))}

      {mapped.olts.map(olt => {
        const list = incidentsByOlt.get(olt.id);
        if (!list?.length) {
          return (
            <CircleMarker key={olt.id} center={[olt.latitude, olt.longitude]} radius={4}
              pathOptions={{ color: colors.outline, weight: 1, fillColor: colors.asset, fillOpacity: 0.9 }}>
              <Tooltip>{olt.name}</Tooltip>
            </CircleMarker>
          );
        }
        const sev = worst(list);
        return (
          <Marker
            key={olt.id}
            position={[olt.latitude, olt.longitude]}
            icon={severityIcon(sev, colors[sev], colors.outline)}
            zIndexOffset={1000}
            eventHandlers={{
              // Leaflet gives keyboard markers role=button but no name
              add: e => e.target.getElement()?.setAttribute('aria-label',
                `${olt.name}: ${list.length} open, worst ${SEVERITY_META[sev].label.toLowerCase()}`),
            }}
          >
            <Tooltip>
              {olt.name}: {list.length} open — {SEVERITY_META[sev].label.toLowerCase()} ({list.map(o => o.reference).join(', ')})
            </Tooltip>
          </Marker>
        );
      })}
    </MapContainer>
  );
}
