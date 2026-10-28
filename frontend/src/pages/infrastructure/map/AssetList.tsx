// ============================================================
// OPSYN MAP — list view
// The accessible, searchable equivalent of the map: every mapped asset as a
// sortable table (solid, not glass). Selecting a row shows it on the map.
// ============================================================

import { useMemo } from 'react';
import { DataTable, type Column } from '../../../components/ui/DataTable';
import type { LayerState } from './layers';
import type { MapPalette } from './mapIcons';
import { KIND_LABEL, worstSeverity, type AssetKind, type MapAsset } from './mapModel';
import { AssetShape } from './ShapeIcon';
import s from './InfraMap.module.css';

const STATE_ORDER = { critical: 0, watch: 1, normal: 2, offline: 3 } as const;
const STATE_TEXT = { normal: 'Normal', watch: 'Watch', critical: 'Critical', offline: 'Not in service' } as const;
const LAYER_OF: Record<AssetKind, keyof LayerState> = { site: 'sites', olt: 'olts', cabinet: 'cabinets', splitter: 'splitters' };

export default function AssetList({ assets, layers, palette, onShow }: {
  assets: MapAsset[];
  layers: LayerState;
  palette: MapPalette;
  onShow: (a: MapAsset) => void;
}) {
  // Same filter as the map: a layer hidden there is hidden here
  const rows = useMemo(() => assets.filter(a => layers[LAYER_OF[a.kind]]), [assets, layers]);

  const columns = useMemo<Column<MapAsset>[]>(() => [
    {
      key: 'label', header: 'Asset', sortable: true, mono: true, mobile: 'title', hideable: false,
      render: (_v, a) => (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <AssetShape kind={a.kind} color={palette.state[a.state]} outline={palette.outline} level={(a.raw as { splitter_level?: string }).splitter_level} size={16} />
          {a.label}
        </span>
      ),
    },
    { key: 'kind', header: 'Type', sortable: true, render: (_v, a) => KIND_LABEL[a.kind] },
    { key: 'sublabel', header: 'Details', render: (_v, a) => a.sublabel.replace(/^[^·]+·\s*/, '') },
    {
      key: 'state', header: 'State', sortable: true,
      sortValue: a => STATE_ORDER[a.state],
      render: (_v, a) => <span style={{ color: a.state === 'normal' ? undefined : palette.state[a.state] }}>{STATE_TEXT[a.state]}</span>,
    },
    {
      key: 'incidents', header: 'Open incidents', numeric: true, sortable: true,
      sortValue: a => a.incidents.length,
      render: (_v, a) => {
        if (!a.incidents.length) return '—';
        const worst = worstSeverity(a.incidents);
        return <span style={{ color: worst ? palette.severity[worst] : undefined }}>{a.incidents.length}</span>;
      },
    },
    {
      key: 'coords', header: 'Coordinates', mono: true, defaultHidden: true,
      render: (_v, a) => `${a.lat.toFixed(5)}, ${a.lng.toFixed(5)}`,
    },
  ], [palette]);

  return (
    <div className={s.list}>
      <DataTable
        caption="Mapped network assets"
        columns={columns}
        data={rows}
        rowKey={a => a.key}
        rowLabel={a => `${KIND_LABEL[a.kind]} ${a.label}`}
        onRowClick={onShow}
        defaultSort={{ key: 'state', dir: 'asc' }}
        columnChooser
        viewKey="infra-map-list"
        emptyTitle="No assets to list"
        emptyMessage="No mapped assets match the layers that are switched on."
      />
    </div>
  );
}
