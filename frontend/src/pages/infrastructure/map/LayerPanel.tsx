// ============================================================
// OPSYN MAP — layer panel (glass, floating over the map)
// Toggles and legend in one place: each layer shows its shape, its count,
// and what its colours mean. On-call staff are listed here — they have no
// recorded location, so they are not drawn on the map.
// ============================================================

import { X } from 'lucide-react';
import { GlassPanel } from '../../../components/glass';
import { SEVERITY_META, SEVERITY_ORDER } from '../../../components/status/severity';
import type { LayerCounts, LayerKey, LayerState } from './layers';
import type { MapPalette } from './mapIcons';
import { AlarmShape, AssetShape } from './ShapeIcon';
import s from './InfraMap.module.css';

function Row({ k, label, count, layers, onToggle, icon }: {
  k: LayerKey; label: string; count?: number; layers: LayerState; onToggle: (k: LayerKey) => void; icon?: React.ReactNode;
}) {
  return (
    <label className={s.layerRow}>
      <input type="checkbox" className={s.check} checked={layers[k]} onChange={() => onToggle(k)} />
      <span className={s.swatch}>{icon}</span>
      <span className={s.layerName}>{label}</span>
      {count !== undefined && <span className={s.count}>{count.toLocaleString()}</span>}
    </label>
  );
}

export default function LayerPanel({ layers, onToggle, counts, palette, onCall, onClose }: {
  layers: LayerState;
  onToggle: (k: LayerKey) => void;
  counts: LayerCounts;
  palette: MapPalette;
  onCall: string[] | null;
  onClose: () => void;
}) {
  const p = palette;
  const alarmsTotal = SEVERITY_ORDER.reduce((n, sv) => n + counts.alarmsBySeverity[sv], 0);

  return (
    <GlassPanel readable className={s.layers} role="region" aria-label="Map layers">
      <div className={s.layersHead}>
        Layers
        <button type="button" className={`liquid-glass-item ${s.action}`} style={{ height: 28, padding: '0 6px', border: 0 }} onClick={onClose} aria-label="Hide layers">
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <div className={s.layersBody}>
        <div className={s.group}>
          <Row k="alarms" label="Open incidents" count={alarmsTotal} layers={layers} onToggle={onToggle}
            icon={<AlarmShape severity="critical" color={p.severity.critical} outline={p.outline} />} />
          {layers.alarms && SEVERITY_ORDER.filter(sv => counts.alarmsBySeverity[sv] > 0).map(sv => (
            <div key={sv} className={s.legendRow}>
              <AlarmShape severity={sv} color={p.severity[sv]} outline={p.outline} size={12} />
              {counts.alarmsBySeverity[sv]} {SEVERITY_META[sv].label.toLowerCase()}
            </div>
          ))}
          {layers.alarms && counts.alarmsUnplaced > 0 && (
            <div className={s.legendRow}>{counts.alarmsUnplaced} without a mapped OLT</div>
          )}
        </div>

        <div className={s.group}>
          <div className={s.groupTitle}>Network assets</div>
          <Row k="sites" label="Sites" count={counts.sites} layers={layers} onToggle={onToggle}
            icon={<AssetShape kind="site" color={p.state.normal} outline={p.outline} />} />
          <Row k="olts" label="OLTs" count={counts.olts} layers={layers} onToggle={onToggle}
            icon={<AssetShape kind="olt" color={p.state.normal} outline={p.outline} />} />
          <Row k="cabinets" label="Cabinets" count={counts.cabinets} layers={layers} onToggle={onToggle}
            icon={<AssetShape kind="cabinet" color={p.state.normal} outline={p.outline} />} />
          <Row k="splitters" label="Splitters" count={counts.splitterL1 + counts.splitterL2} layers={layers} onToggle={onToggle}
            icon={<AssetShape kind="splitter" color={p.state.normal} outline={p.outline} />} />
          {layers.splitters && (
            <>
              <div className={s.legendRow}><AssetShape kind="splitter" color={p.state.normal} outline={p.outline} size={14} /> First level · {counts.splitterL1}</div>
              <div className={s.legendRow}><AssetShape kind="splitter" level="Second-Level" color={p.state.normal} outline={p.outline} size={14} /> Second level · {counts.splitterL2}</div>
            </>
          )}
        </div>

        <div className={s.group}>
          <div className={s.groupTitle}>Asset state (colour)</div>
          {([
            ['normal', 'Normal'],
            ['watch', 'Watch — capacity ≥70%, full splitter, or an open incident'],
            ['critical', 'Critical — capacity ≥90%, alert, or high/critical incident'],
            ['offline', 'Not in service'],
          ] as const).map(([k, text]) => (
            <div key={k} className={s.legendRow} style={{ paddingLeft: 4 }}>
              <span className={s.stateDot} style={{ background: p.state[k] }} aria-hidden="true" /> {text}
            </div>
          ))}
        </div>

        <div className={s.group}>
          <Row k="routes" label="Fiber routes" count={counts.routes} layers={layers} onToggle={onToggle}
            icon={<span className={s.dash} style={{ borderTop: `2px solid ${p.route.normal}` }} />} />
          {layers.routes && (
            <>
              <div className={s.legendRow}><span className={s.dash} style={{ borderTop: `2px dashed ${p.route.watch}` }} aria-hidden="true" /> Degraded / maintenance</div>
              <div className={s.legendRow}><span className={s.dash} style={{ borderTop: `2px dotted ${p.route.critical}` }} aria-hidden="true" /> Cut / down</div>
            </>
          )}
        </div>

        <div className={s.group}>
          <div className={s.groupTitle}>Analysis</div>
          <Row k="heat" label="Site utilisation" layers={layers} onToggle={onToggle} />
          {/* Fetched only while switched on — no count until then, rather than a false 0 */}
          <Row k="subscribers" label="Coverage demand" count={layers.subscribers ? counts.subscribers : undefined} layers={layers} onToggle={onToggle} />
        </div>

        <div className={s.group}>
          <div className={s.groupTitle}>On call today</div>
          {onCall === null && <p className={s.muted}>Loading…</p>}
          {onCall?.length === 0 && <p className={s.muted}>No one is on call today.</p>}
          {onCall && onCall.length > 0 && <ul className={s.people}>{onCall.map(n => <li key={n}>{n}</li>)}</ul>}
          <p className={s.muted} style={{ marginTop: 4 }}>Staff have no recorded location, so they aren't placed on the map.</p>
        </div>
      </div>
    </GlassPanel>
  );
}
