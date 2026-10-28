// ============================================================
// OPSYN NETWORK MAP — layer panel. The legend is the control:
// each row shows the exact plate (or cable stroke) drawn on the map, the
// live count from /gis/layers, and switches that layer on or off. Rows
// whose layer only appears further in say so, instead of looking broken.
// ============================================================

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { PanelLeftClose, RefreshCw } from 'lucide-react';
import type { GisLayer, GisLayerGroup, GisLayerRegistry, NetAssetType, NetCableCategory, NetTier } from '@shared';
import { markerDataUrl } from './markerImages';
import { CABLE_STYLE, TIER_COLOR } from './symbology';
import { useNetworkMapStore } from './store';
import { useSyncUploaded } from './queries';
import s from './NetworkMap.module.css';

function CableSwatch({ category }: { category: NetCableCategory }) {
  const { color, width } = CABLE_STYLE[category];
  return (
    <svg className={s.swatch} viewBox="0 0 26 26" aria-hidden="true">
      <path d="M3 19 C 9 19, 12 7, 23 7" fill="none" stroke="#FFFFFF" strokeWidth={width + 3} strokeLinecap="round" />
      <path d="M3 19 C 9 19, 12 7, 23 7" fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" />
    </svg>
  );
}

function LayerRow({ layer, zoom, hidden, onToggle }: {
  layer: GisLayer; zoom: number; hidden: boolean; onToggle: () => void;
}) {
  const id = useId();
  const tooFar = zoom < layer.min_zoom;
  return (
    <li>
      <label className={s.row} htmlFor={id} data-empty={layer.count === 0}>
        {layer.kind === 'asset'
          ? <img className={s.swatch} src={markerDataUrl(layer.key as NetAssetType)} alt="" />
          : <CableSwatch category={layer.key as NetCableCategory} />}
        <span className={s.rowLabel}>
          {layer.label}
          {tooFar && layer.count > 0 && <span className={s.rowHint}>Zoom in to {layer.min_zoom} to see</span>}
        </span>
        <span className={s.rowCount} aria-label={`${layer.count} in service`}>{layer.count}</span>
        <input id={id} type="checkbox" checked={!hidden} onChange={onToggle} />
      </label>
    </li>
  );
}

function GroupHeader({ group, hidden, onSet }: {
  group: GisLayerGroup; hidden: string[]; onSet: (visible: boolean) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const keys = group.layers.map(l => l.key as string);
  const shown = keys.filter(k => !hidden.includes(k)).length;
  const total = group.layers.reduce((n, l) => n + l.count, 0);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = shown > 0 && shown < keys.length;
  }, [shown, keys.length]);
  return (
    <div className={s.groupHead}>
      <label>
        <input ref={ref} type="checkbox" checked={shown === keys.length} onChange={e => onSet(e.target.checked)} />
        {group.label}
      </label>
      <span className={s.groupCount}>{total}</span>
    </div>
  );
}

/**
 * One tier. Layers with nothing in service are folded away behind a
 * toggle — a list of twenty mostly-zero rows buries the ones that matter.
 */
function LayerGroup({ group, zoom }: { group: GisLayerGroup; zoom: number }) {
  const { hidden, toggleLayer, setLayers } = useNetworkMapStore();
  const [showEmpty, setShowEmpty] = useState(false);
  const empty = group.layers.filter(l => l.count === 0).length;
  const rows = showEmpty ? group.layers : group.layers.filter(l => l.count > 0);
  return (
    <section className={s.group} aria-label={group.label}>
      <GroupHeader
        group={group}
        hidden={hidden}
        onSet={visible => setLayers(group.layers.map(l => l.key), visible)}
      />
      {rows.length > 0 && (
        <ul
          className={s.rows}
          style={{ ['--tier' as string]: group.key === 'cables' ? 'var(--border-strong)' : TIER_COLOR[group.key as NetTier] }}
        >
          {rows.map(layer => (
            <LayerRow
              key={layer.key}
              layer={layer}
              zoom={zoom}
              hidden={hidden.includes(layer.key)}
              onToggle={() => toggleLayer(layer.key)}
            />
          ))}
        </ul>
      )}
      {empty > 0 && (
        <button type="button" className={s.moreBtn} aria-expanded={showEmpty} onClick={() => setShowEmpty(v => !v)}>
          {showEmpty
            ? 'Hide types with nothing in service'
            : `${rows.length ? 'Show' : 'None in service yet. Show'} ${empty} ${empty === 1 ? 'type' : 'types'}`}
        </button>
      )}
    </section>
  );
}

interface Props {
  registry: GisLayerRegistry | undefined;
  loading:  boolean;
  error:    boolean;
  zoom:     number;
  onHide:   () => void;
}

export function LayerPanel({ registry, loading, error, zoom, onHide }: Props) {
  const sync = useSyncUploaded();

  const totals = useMemo(() => {
    let assets = 0;
    let cables = 0;
    for (const g of registry?.groups ?? []) for (const l of g.layers) {
      if (l.kind === 'asset') assets += l.count; else cables += l.count;
    }
    return { assets, cables };
  }, [registry]);

  const synced = sync.data
    ? Object.values(sync.data.mirrored).reduce((a, b) => a + b, 0)
    : null;

  return (
    <aside className={s.panel} aria-label="Map layers">
      <div className={s.panelHead}>
        <div>
          <h1 className={s.title} tabIndex={-1}>Network map</h1>
          <p className={s.summary}>
            {loading ? 'Loading the network…'
              : error ? 'Layer list unavailable'
              : `${totals.assets} assets and ${totals.cables} cables in service`}
          </p>
        </div>
        <button type="button" className={s.iconBtn} onClick={onHide} aria-label="Hide layer panel" title="Hide layer panel">
          <PanelLeftClose size={18} aria-hidden />
        </button>
      </div>

      <div className={s.modes} role="group" aria-label="Map mode">
        <button type="button" className={s.mode} aria-pressed="true">Network</button>
        <button type="button" className={s.mode} aria-pressed="false" disabled aria-describedby="nm-mode-note">Design</button>
        <button type="button" className={s.mode} aria-pressed="false" disabled aria-describedby="nm-mode-note">Deployment</button>
      </div>
      <p id="nm-mode-note" className={s.modeNote}>Showing the network in service. Open a design from its project's Network designs tab; deployment view is coming.</p>

      <div className={s.groups}>
        {loading && [0, 1, 2, 3].map(i => <div key={i} className={s.skeleton} style={{ margin: '14px 16px' }} />)}
        {error && <p className={s.muted} style={{ padding: '12px 16px' }}>Couldn't load the layer list. Check your connection and reload the page.</p>}
        {registry?.groups.map(group => <LayerGroup key={group.key} group={group} zoom={zoom} />)}
      </div>

      <div className={s.panelFoot}>
        <p>Uploaded OLTs, cabinets or splitters missing from the map?</p>
        <button type="button" className={s.linkBtn} onClick={() => sync.mutate()} disabled={sync.isPending}>
          <RefreshCw size={14} aria-hidden />
          {sync.isPending ? 'Syncing uploads…' : 'Sync uploads'}
        </button>
        <p className={s.syncResult} role="status">
          {synced !== null && `Synced ${synced} uploaded assets${sync.data!.skipped.length ? `; ${sync.data!.skipped.length} skipped because their code is already used` : ''}.`}
          {sync.isError && <span className={s.error}>{(sync.error as Error).message}</span>}
        </p>
      </div>
    </aside>
  );
}
