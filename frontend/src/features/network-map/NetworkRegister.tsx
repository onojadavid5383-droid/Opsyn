// ============================================================
// OPSYN — network register (Infrastructure → Network tab).
// Every live asset and cable in net_assets / net_cables, filterable by
// type, status and code/name, paged on the server (GET /network/assets,
// /network/cables). Types and states come from the catalogue. "Show on
// map" opens /network?asset=<id> (or ?cable=) straight onto the object.
// ============================================================

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Map as MapIcon, Search } from 'lucide-react';
import type { NetAssetSummary, NetCableSummary } from '@shared';
import { DataTable, Input, Pagination, Select, type Column } from '../../components/ui';
import { useAssetPage, useCablePage, useCatalogue } from './queries';
import { markerDataUrl } from './markerImages';
import { LifecycleState } from './LifecycleState';
import { formatLength } from './mapMath';
import { LIFECYCLE_LABEL } from './symbology';
import s from './NetworkRegister.module.css';

type Kind = 'assets' | 'cables';

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function NetworkRegister() {
  const navigate = useNavigate();
  const catalogue = useCatalogue();
  const [kind, setKind] = useState<Kind>('assets');
  const [type, setType] = useState('');
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(25);
  const term = useDebounced(q.trim(), 250);

  const filters = { status: status || undefined, q: term || undefined, page, size };
  const assets = useAssetPage({ ...filters, type: kind === 'assets' ? type || undefined : undefined });
  const cables = useCablePage({ ...filters, category: kind === 'cables' ? type || undefined : undefined });
  const active = kind === 'assets' ? assets : cables;

  const typeOptions = useMemo(() => {
    const cat = catalogue.data;
    if (!cat) return [];
    return kind === 'assets'
      ? cat.asset_types.map(t => ({ label: t.label, value: t.code }))
      : cat.cable_categories.map(c => ({ label: c.label, value: c.code }));
  }, [catalogue.data, kind]);
  const typeLabel = useMemo(() => new Map(typeOptions.map(o => [o.value, o.label])), [typeOptions]);
  const statusOptions = (catalogue.data?.lifecycle_states ?? []).map(st => ({ label: LIFECYCLE_LABEL[st], value: st }));

  const reset = (fn: () => void) => { fn(); setPage(1); };

  const assetColumns: Column<NetAssetSummary>[] = [
    { key: 'asset_code', header: 'Code', sortable: false, mobile: 'title',
      render: (_v, r) => <span className={s.code}>{r.asset_code}</span> },
    { key: 'asset_type', header: 'Type',
      render: (_v, r) => (
        <span className={s.type}><img src={markerDataUrl(r.asset_type)} alt="" width={22} height={22} />{typeLabel.get(r.asset_type) ?? r.asset_type}</span>
      ) },
    { key: 'name', header: 'Name', render: (_v, r) => (r.name && r.name !== r.asset_code ? r.name : '') },
    { key: 'lifecycle_status', header: 'Status', render: (_v, r) => <LifecycleState status={r.lifecycle_status} /> },
    { key: 'map', header: '', align: 'right',
      render: (_v, r) => (
        <button type="button" className={s.mapBtn} onClick={e => { e.stopPropagation(); navigate(`/network?asset=${r.id}`); }}
          aria-label={`Show ${r.asset_code} on the map`}>
          <MapIcon size={14} aria-hidden /> Show on map
        </button>
      ) },
  ];

  const cableColumns: Column<NetCableSummary>[] = [
    { key: 'asset_code', header: 'Code', mobile: 'title', render: (_v, r) => <span className={s.code}>{r.asset_code}</span> },
    { key: 'cable_category', header: 'Category', render: (_v, r) => typeLabel.get(r.cable_category) ?? r.cable_category },
    { key: 'length_m', header: 'Length', numeric: true, render: (_v, r) => formatLength(r.length_m) },
    { key: 'fiber_count', header: 'Fibres', numeric: true, render: (_v, r) => r.fiber_count ?? <span className={s.muted}>–</span> },
    { key: 'lifecycle_status', header: 'Status', render: (_v, r) => <LifecycleState status={r.lifecycle_status} /> },
    { key: 'map', header: '', align: 'right',
      render: (_v, r) => (
        <button type="button" className={s.mapBtn} onClick={e => { e.stopPropagation(); navigate(`/network?cable=${r.id}`); }}
          aria-label={`Show ${r.asset_code} on the map`}>
          <MapIcon size={14} aria-hidden /> Show on map
        </button>
      ) },
  ];

  const total = active.data?.total ?? 0;
  const filtered = !!(type || status || term);

  return (
    <div className={s.register}>
      <div className={s.filters}>
        <div className={s.kinds} role="radiogroup" aria-label="Show">
          {(['assets', 'cables'] as const).map(k => (
            <button key={k} type="button" role="radio" aria-checked={kind === k} className={s.kind}
              onClick={() => reset(() => { setKind(k); setType(''); })}>
              {k === 'assets' ? 'Assets' : 'Cables'}
            </button>
          ))}
        </div>
        <div className={s.search}>
          <Input id="register-search" value={q} onChange={v => reset(() => setQ(v))}
            placeholder="Code or name" prefix={<Search size={14} aria-hidden="true" />} autoComplete="off" style={{ marginBottom: 0 }} />
        </div>
        <Select ariaLabel={kind === 'assets' ? 'Asset type' : 'Cable category'} value={type}
          onChange={v => reset(() => setType(v))}
          options={[{ label: kind === 'assets' ? 'All types' : 'All categories', value: '' }, ...typeOptions]}
          style={{ marginBottom: 0, minWidth: 180 }} />
        <Select ariaLabel="Status" value={status} onChange={v => reset(() => setStatus(v))}
          options={[{ label: 'Any status', value: '' }, ...statusOptions]} style={{ marginBottom: 0, minWidth: 160 }} />
        <span className={s.count} aria-live="polite">{active.isFetching && !active.data ? 'Loading…' : `${total} ${kind === 'assets' ? (total === 1 ? 'asset' : 'assets') : (total === 1 ? 'cable' : 'cables')}`}</span>
      </div>

      {kind === 'assets' ? (
        <DataTable<NetAssetSummary>
          caption="Network assets"
          columns={assetColumns}
          data={assets.data?.items ?? []}
          rowKey={r => r.id}
          rowLabel={r => r.asset_code}
          isLoading={assets.isLoading}
          onRowClick={r => navigate(`/network?asset=${r.id}`)}
          emptyTitle={filtered ? 'No assets match these filters' : 'No network assets yet'}
          emptyMessage={filtered
            ? 'Clear a filter or search for a different code.'
            : 'Upload poles, FATs, FDTs and other plant with Bulk upload, or sync the OLTs, cabinets and splitters already uploaded.'}
        />
      ) : (
        <DataTable<NetCableSummary>
          caption="Network cables"
          columns={cableColumns}
          data={cables.data?.items ?? []}
          rowKey={r => r.id}
          rowLabel={r => r.asset_code}
          isLoading={cables.isLoading}
          onRowClick={r => navigate(`/network?cable=${r.id}`)}
          emptyTitle={filtered ? 'No cables match these filters' : 'No network cables yet'}
          emptyMessage={filtered ? 'Clear a filter or search for a different code.' : 'Upload cables with their routes from Excel or GeoJSON with Bulk upload.'}
        />
      )}
      {active.isError && <p className={s.error} role="alert">Couldn't load the register. Check your connection and try again.</p>}

      {total > size && (
        <Pagination page={page} pageSize={size} total={total} onPage={setPage}
          onPageSize={n => reset(() => setSize(n))} pageSizes={[25, 50, 100]} />
      )}
    </div>
  );
}
