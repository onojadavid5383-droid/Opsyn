// ============================================================
// OPSYN MAP — inspector (glass drawer; a bottom sheet on phones)
// The selected asset or route: what it is, its state and why, its open
// incidents, and — for splitters — the upstream path.
// ============================================================

import { Copy, Crosshair, GitBranch } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import type {
  InfraMapCabinet, InfraMapOLT, InfraMapRoute, InfraMapSite, InfraMapSplitter, InfraUtilisationPoint,
} from '@shared';
import { GlassInspector } from '../../../components/glass';
import { StatusBadge } from '../../../components/ui';
import { useToast } from '../../../components/ui/Toast';
import type { MapPalette } from './mapIcons';
import { KIND_LABEL, routeState, type MapAsset, type TraceHop } from './mapModel';
import { AssetShape } from './ShapeIcon';
import s from './InfraMap.module.css';

export type Selection =
  | { type: 'asset'; asset: MapAsset }
  | { type: 'route'; route: InfraMapRoute; fromName?: string; toName?: string };

const STATE_TEXT = {
  normal: 'Normal', watch: 'Watch', critical: 'Critical', offline: 'Not in service',
} as const;

const ROUTE_TEXT = { normal: 'Active', watch: 'Degraded / maintenance', critical: 'Cut / down', unknown: 'Unknown' } as const;

function Coords({ lat, lng }: { lat: number; lng: number }) {
  return <span className={s.mono}>{lat.toFixed(6)}, {lng.toFixed(6)}</span>;
}

interface InspectorProps {
  selection: Selection | null;
  palette: MapPalette;
  util: Map<string, InfraUtilisationPoint>;
  cabinetSplitters: Map<string, number>;
  trace: { hops: TraceHop[]; stop: string } | null;
  onTrace: (splitterId: string) => void;
  onZoom: () => void;
  onClose: () => void;
}

/** Keeps the last selection on screen while the drawer animates closed. */
export default function MapInspector(props: InspectorProps) {
  const [shown, setShown] = useState(props.selection);
  if (props.selection && props.selection !== shown) setShown(props.selection);
  if (!shown) return null;
  return <InspectorBody {...props} selection={shown} open={props.selection !== null} />;
}

function InspectorBody({
  selection, open, palette, util, cabinetSplitters, trace, onTrace, onZoom, onClose,
}: InspectorProps & { selection: Selection; open: boolean }) {
  const toast = useToast();

  if (selection.type === 'route') {
    const { route, fromName, toName } = selection;
    const st = routeState(route.status);
    return (
      <GlassInspector open={open} onOpenChange={o => { if (!o) onClose(); }} label="Route details" title={`${fromName ?? 'Unknown node'} → ${toName ?? 'Unknown node'}`} subtitle="Fiber route" width={320}>
        <dl className={s.kv}>
          <dt>Status</dt><dd style={{ color: palette.route[st] }}>{ROUTE_TEXT[st]}</dd>
          <dt>Cable</dt><dd>{route.cable_type ?? '—'}</dd>
          <dt>Length</dt><dd>{route.length_km != null ? `${route.length_km.toFixed(2)} km` : '—'}</dd>
          <dt>Capacity</dt><dd>{route.capacity_gbps != null ? `${route.capacity_gbps} Gbps` : '—'}</dd>
        </dl>
        <div className={s.actions}>
          <button type="button" className={s.action} onClick={onZoom}><Crosshair size={14} aria-hidden="true" /> Zoom to route</button>
        </div>
      </GlassInspector>
    );
  }

  const a = selection.asset;
  const copy = async () => {
    try { await navigator.clipboard.writeText(`${a.lat}, ${a.lng}`); toast.success('Coordinates copied', `${a.lat.toFixed(6)}, ${a.lng.toFixed(6)}`); }
    catch { toast.error("Couldn't copy coordinates", 'Your browser blocked clipboard access.'); }
  };
  const level = (a.raw as InfraMapSplitter).splitter_level;

  return (
    <GlassInspector
      open={open}
      onOpenChange={o => { if (!o) onClose(); }}
      label={`${KIND_LABEL[a.kind]} details`}
      title={<span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}><AssetShape kind={a.kind} color={palette.state[a.state]} outline={palette.outline} level={level} />{a.label}</span>}
      subtitle={a.sublabel}
      width={320}
    >
      <dl className={s.kv}>
        <dt>State</dt><dd style={{ color: a.state === 'normal' ? undefined : palette.state[a.state] }}>{STATE_TEXT[a.state]}</dd>

        {a.kind === 'site' && (() => {
          const site = a.raw as InfraMapSite;
          const u = util.get(site.id);
          return (
            <>
              <dt>Status</dt><dd>{site.status}</dd>
              <dt>Monitored</dt><dd>{site.is_monitored ? 'Yes' : 'No'}</dd>
              <dt>Capacity</dt>
              <dd>
                {u && u.total > 0 ? (
                  <>
                    {u.used.toLocaleString()} of {u.total.toLocaleString()} ports · {u.utilisation_pct}%
                    <div className={s.meter}><div className={s.meterFill} style={{ width: `${Math.min(100, u.utilisation_pct)}%`, background: palette.state[a.state === 'offline' ? 'normal' : a.state] }} /></div>
                  </>
                ) : 'No port capacity recorded'}
              </dd>
              {site.has_alert && <><dt>Alert</dt><dd style={{ color: palette.state.critical }}>Active capacity alert</dd></>}
            </>
          );
        })()}

        {a.kind === 'olt' && (() => {
          const olt = a.raw as InfraMapOLT;
          return (
            <>
              <dt>Location</dt><dd>{olt.location_description ?? '—'}</dd>
              <dt>ODF ports</dt><dd>{olt.number_of_odf ?? '—'}</dd>
            </>
          );
        })()}

        {a.kind === 'cabinet' && (() => {
          const cab = a.raw as InfraMapCabinet;
          return (
            <>
              <dt>Capacity</dt><dd>{cab.capacity}</dd>
              <dt>Trays</dt><dd>{cab.number_tray ?? '—'}</dd>
              <dt>Splitters housed</dt><dd>{cabinetSplitters.get(cab.id) ?? 0}</dd>
            </>
          );
        })()}

        {a.kind === 'splitter' && (() => {
          const sp = a.raw as InfraMapSplitter;
          return (
            <>
              <dt>Level</dt><dd>{sp.splitter_level}</dd>
              <dt>Type</dt><dd>{sp.splitter_type}</dd>
              <dt>Ratio</dt><dd>{sp.input_ports}:{sp.output_ports}</dd>
              <dt>Customers</dt><dd>{sp.number_customer ?? 0} of {sp.output_ports} outputs</dd>
            </>
          );
        })()}

        <dt>Position</dt><dd><Coords lat={a.lat} lng={a.lng} /></dd>
      </dl>

      {a.incidents.length > 0 && (
        <div className={s.section}>
          <h3 className={s.sectionTitle}>Open incidents ({a.incidents.length})</h3>
          <ul className={s.incidents}>
            {a.incidents.map(o => (
              <li key={o.id} className={s.incident}>
                <StatusBadge severity={o.severity} size="xs" />
                <Link to={`/outage/${o.id}`}>{o.title}</Link>
                <span className={s.mono}>{o.reference}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {a.kind === 'splitter' && trace && (
        <div className={s.section}>
          <h3 className={s.sectionTitle}>Upstream path</h3>
          <ol className={s.hops}>
            {trace.hops.map(h => (
              <li key={h.asset.key} className={s.hop}>
                <span className={s.hopIcon}>
                  <AssetShape kind={h.asset.kind} color={palette.select} outline={palette.outline} level={(h.asset.raw as InfraMapSplitter).splitter_level} size={16} />
                </span>
                <span>
                  <span className={s.mono}>{h.asset.label}</span>
                  <span className={s.muted} style={{ display: 'block' }}>{h.relation}</span>
                </span>
              </li>
            ))}
          </ol>
          {trace.stop && <p className={s.stop}>{trace.stop} The line on the map joins assets logically; it is not the cable's route.</p>}
        </div>
      )}

      <div className={s.actions}>
        {a.kind === 'splitter' && !trace && (
          <button type="button" className={`${s.action} ${s.primaryAction}`} onClick={() => onTrace(a.id)}>
            <GitBranch size={14} aria-hidden="true" /> Trace upstream path
          </button>
        )}
        <button type="button" className={s.action} onClick={onZoom}><Crosshair size={14} aria-hidden="true" /> Zoom to</button>
        <button type="button" className={s.action} onClick={copy}><Copy size={14} aria-hidden="true" /> Copy coordinates</button>
      </div>
    </GlassInspector>
  );
}
