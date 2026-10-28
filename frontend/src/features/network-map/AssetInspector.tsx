// ============================================================
// OPSYN NETWORK MAP — inspector for an asset or a cable.
//
// Reads the authoritative record (GET /network/assets|cables/{id}); the
// tile feature that was clicked only points at it. Sections:
//   asset  Status · Location · Capacity · <type section> · Housing · Connections · Details · Record
//   cable  Status · Route · Fibres · Details · Record
// Capacity, Connections and Fibres (Phase 3) live in TopologySections.tsx.
// Details are rendered and edited from the catalogue's attribute specs
// (AttributeFields.tsx). Type-specific sections plug into TYPE_SECTIONS.
// Writes go through PATCH; 403 (no network.edit), 409 (lifecycle) and 422
// (a field the server rejects) come back as sentences.
// ============================================================

import { useEffect, useState } from 'react';
import { format } from 'date-fns';
import { Crosshair, Pencil, X } from 'lucide-react';
import type {
  NetAsset, NetAssetType, NetCable, NetCableCategory, NetCatalogue, NetFieldSpec, NetLifecycleStatus,
  NetTraceDirection,
} from '@shared';
import type { ApiError } from '../../api/client';
import type { NetAssetPatch, NetCablePatch } from '../../api/network.api';
import { useAsset, useCable, useCatalogue, useUpdateAsset, useUpdateCable } from './queries';
import { markerDataUrl } from './markerImages';
import { LifecycleState } from './LifecycleState';
import { AttributeView, FactRow, FieldInput } from './AttributeFields';
import { mergeDraft, toDraft, type Draft } from './attributeFormat';
import { formatLength } from './mapMath';
import { ConnectionsSection, FibresSection, UtilisationSection } from './TopologySections';
import { CABLE_STYLE, CREATION_LABEL, LIFECYCLE_LABEL } from './symbology';
import { useEntityHistory } from './design/designQueries';
import { HistoryList } from './design/HistoryList';
import s from './NetworkMap.module.css';

export interface AssetRefTarget { id: string; code: string }

function when(iso: string): string {
  try { return format(new Date(iso), 'd MMM yyyy, HH:mm'); } catch { return iso; }
}

function errorMessage(err: unknown): string | null {
  if (!err) return null;
  const e = err as ApiError;
  if (e.status === 403) return "You don't have permission to change the live network. Ask an administrator for network editing access.";
  return e.detail ?? e.message ?? 'The change could not be saved.';
}

// ── Shared sections ──────────────────────────────────────────

interface Patchable {
  mutate:    (patch: Record<string, unknown>, opts?: { onSuccess?: () => void }) => void;
  isPending: boolean;
  error:     unknown;
}

function StatusSection({ status, allowed, save }: {
  status: NetLifecycleStatus; allowed: NetLifecycleStatus[]; save: Patchable;
}) {
  const [target, setTarget] = useState<NetLifecycleStatus | ''>('');
  const message = errorMessage(save.error);
  return (
    <section className={s.section} aria-labelledby="insp-status">
      <h3 id="insp-status" className={s.sectionTitle}>Status</h3>
      <LifecycleState status={status} />
      {allowed.length > 0 ? (
        <form className={s.transition} onSubmit={e => { e.preventDefault(); if (target) save.mutate({ lifecycle_status: target }); }}>
          <label className={s.srOnly} htmlFor="insp-transition">New status</label>
          <select id="insp-transition" value={target} onChange={e => setTarget(e.target.value as NetLifecycleStatus)}>
            <option value="">Change status to…</option>
            {allowed.map(t => <option key={t} value={t}>{LIFECYCLE_LABEL[t]}</option>)}
          </select>
          <button type="submit" className={s.primaryBtn} disabled={!target || save.isPending}>
            {save.isPending ? 'Saving…' : 'Change status'}
          </button>
        </form>
      ) : (
        <p className={s.muted}>This status is final.</p>
      )}
      {message && <p className={s.error} role="alert">{message}</p>}
    </section>
  );
}

interface CapacityEdit { label: string; capacity: number | null; used: number | null }

function DetailsSection({ specs, record, capacity, save }: {
  specs:     NetFieldSpec[];
  record:    { name: string | null; description: string | null; attributes: Record<string, unknown> };
  capacity?: CapacityEdit;
  save:      Patchable;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>({});
  const [base, setBase] = useState({ name: '', description: '', capacity: '', used: '' });
  const [localError, setLocalError] = useState<string | null>(null);

  const start = () => {
    setDraft(toDraft(specs, record.attributes));
    setBase({
      name: record.name ?? '', description: record.description ?? '',
      capacity: capacity?.capacity?.toString() ?? '', used: capacity?.used?.toString() ?? '',
    });
    setLocalError(null);
    setEditing(true);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const num = (v: string, what: string): number | null | undefined => {
      if (v.trim() === '') return null;
      const n = Number(v);
      if (!Number.isInteger(n) || n < 0) { setLocalError(`${what} must be a whole number of 0 or more.`); return undefined; }
      return n;
    };
    const patch: Record<string, unknown> = {
      name: base.name.trim() || null,
      description: base.description.trim() || null,
      attributes: mergeDraft(specs, record.attributes, draft),
    };
    if (capacity) {
      const c = num(base.capacity, capacity.label);
      const u = num(base.used, 'In use');
      if (c === undefined || u === undefined) return;
      if (c !== null && u !== null && u > c) { setLocalError(`In use cannot be more than ${capacity.label.toLowerCase()}.`); return; }
      patch.capacity = c;
      patch.used_capacity = u;
    }
    setLocalError(null);
    save.mutate(patch, { onSuccess: () => setEditing(false) });
  };

  const message = localError ?? (editing ? errorMessage(save.error) : null);

  return (
    <section className={s.section} aria-labelledby="insp-details">
      <div className={s.sectionHead}>
        <h3 id="insp-details" className={s.sectionTitle}>Details</h3>
        {!editing && (
          <button type="button" className={s.textBtn} onClick={start}>
            <Pencil size={13} aria-hidden /> Edit details
          </button>
        )}
      </div>
      {!editing ? (
        <>
          {(record.name || record.description) && (
            <dl className={s.facts} style={{ marginBottom: 8 }}>
              {record.name && <FactRow label="Name">{record.name}</FactRow>}
              {record.description && <FactRow label="Description">{record.description}</FactRow>}
            </dl>
          )}
          <AttributeView specs={specs} values={record.attributes} />
        </>
      ) : (
        <form className={s.form} onSubmit={submit} aria-label="Edit details">
          <div className={s.formRow}>
            <label htmlFor="insp-name">Name</label>
            <input id="insp-name" value={base.name} onChange={e => setBase({ ...base, name: e.target.value })} maxLength={200} />
          </div>
          <div className={s.formRow}>
            <label htmlFor="insp-desc">Description</label>
            <textarea id="insp-desc" rows={2} value={base.description} onChange={e => setBase({ ...base, description: e.target.value })} />
          </div>
          {capacity && (
            <div className={s.formPair}>
              <div className={s.formRow}>
                <label htmlFor="insp-cap">{capacity.label}</label>
                <input id="insp-cap" inputMode="numeric" value={base.capacity} onChange={e => setBase({ ...base, capacity: e.target.value })} />
              </div>
              <div className={s.formRow}>
                <label htmlFor="insp-used">In use</label>
                <input id="insp-used" inputMode="numeric" value={base.used} onChange={e => setBase({ ...base, used: e.target.value })} />
              </div>
            </div>
          )}
          {specs.map(f => (
            <FieldInput key={f.key} spec={f} value={draft[f.key] ?? ''} onChange={v => setDraft({ ...draft, [f.key]: v })} />
          ))}
          {message && <p className={s.error} role="alert">{message}</p>}
          <div className={s.formActions}>
            <button type="button" className={s.linkBtn} onClick={() => setEditing(false)} disabled={save.isPending}>Cancel</button>
            <button type="submit" className={s.primaryBtn} disabled={save.isPending}>
              {save.isPending ? 'Saving…' : 'Save details'}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

function RecordSection({ creation, created, updated }: { creation: string; created: string; updated: string }) {
  return (
    <section className={s.section} aria-labelledby="insp-record">
      <h3 id="insp-record" className={s.sectionTitle}>Record</h3>
      <dl className={s.facts}>
        <dt>Origin</dt><dd>{CREATION_LABEL[creation] ?? creation}</dd>
        <dt>Added</dt><dd>{when(created)}</dd>
        <dt>Last changed</dt><dd>{when(updated)}</dd>
      </dl>
    </section>
  );
}

/** Every recorded change to this asset or cable (Phase 8 audit trail) */
function HistorySection({ entityId }: { entityId: string }) {
  const trail = useEntityHistory(entityId);
  return (
    <section className={s.section} aria-labelledby="insp-history">
      <h3 id="insp-history" className={s.sectionTitle}>History</h3>
      <HistoryList entries={trail.data?.slice(0, 20)} loading={trail.isLoading} error={trail.error} showCode={false}
        empty="No changes recorded since the audit trail began." />
    </section>
  );
}

// ── Type-specific sections (inspector registry) ──────────────

/** A splitter as ports: one input fanning out to its outputs, customers filled in. */
function SplitterSection({ asset }: { asset: NetAsset }) {
  const at = asset.attributes as Record<string, unknown>;
  const outputs = Number(at.output_ports ?? asset.capacity ?? 0);
  const served = Number(at.number_customer ?? asset.used_capacity ?? 0);
  if (!outputs || outputs > 128) return null;
  return (
    <section className={s.section} aria-labelledby="insp-split">
      <h3 id="insp-split" className={s.sectionTitle}>Split</h3>
      <p className={s.muted} style={{ marginTop: 0 }}>
        1 input to {outputs} outputs{served ? `, ${served} serving customers` : ''}.
      </p>
      <div className={s.ports} role="img" aria-label={`${served} of ${outputs} output ports serving customers`}>
        {Array.from({ length: outputs }, (_, i) => (
          <span key={i} className={s.port} data-used={i < served} />
        ))}
      </div>
    </section>
  );
}

const TYPE_SECTIONS: Partial<Record<NetAssetType, (p: { asset: NetAsset }) => React.ReactNode>> = {
  SPLITTER: SplitterSection,
};

// ── Asset body ───────────────────────────────────────────────

function AssetBody({ asset, catalogue, onZoomTo, onGoTo, onTrace }: {
  asset: NetAsset; catalogue: NetCatalogue | undefined;
  onZoomTo: (lng: number, lat: number) => void; onGoTo: (ref: AssetRefTarget) => void;
  onTrace: (assetId: string, direction: NetTraceDirection) => void;
}) {
  // One mutation per section, so an error shows only where it happened
  const statusSave = useUpdateAsset(asset.id);
  const detailsSave = useUpdateAsset(asset.id);
  const typeSpec = catalogue?.asset_types.find(t => t.code === asset.asset_type);
  const capacityLabel = typeSpec?.capacity_label ?? null;
  const TypeSection = TYPE_SECTIONS[asset.asset_type];
  const asPatchable = (m: typeof statusSave): Patchable => ({
    mutate: (p, o) => m.mutate(p as NetAssetPatch, o), isPending: m.isPending, error: m.error,
  });

  return (<>
    <StatusSection key={`${asset.id}:${asset.lifecycle_status}`} status={asset.lifecycle_status} allowed={asset.allowed_transitions} save={asPatchable(statusSave)} />

    <section className={s.section} aria-labelledby="insp-location">
      <h3 id="insp-location" className={s.sectionTitle}>Location</h3>
      <dl className={s.facts}>
        <dt>Latitude</dt><dd className={s.mono}>{asset.lat.toFixed(6)}</dd>
        <dt>Longitude</dt><dd className={s.mono}>{asset.lng.toFixed(6)}</dd>
      </dl>
      <div className={s.transition}>
        <button type="button" className={s.linkBtn} onClick={() => onZoomTo(asset.lng, asset.lat)}>
          <Crosshair size={14} aria-hidden /> Zoom to asset
        </button>
      </div>
      {catalogue && !catalogue.live_states.includes(asset.lifecycle_status) && (
        <p className={s.hint}>
          Not drawn on this map: it shows the network in service, and this asset is {LIFECYCLE_LABEL[asset.lifecycle_status].toLowerCase()}.
        </p>
      )}
    </section>

    {capacityLabel && <UtilisationSection assetId={asset.id} capacityLabel={capacityLabel} />}

    {TypeSection && <TypeSection asset={asset} />}

    {(asset.parent || asset.children_count > 0) && (
      <section className={s.section} aria-labelledby="insp-housing">
        <h3 id="insp-housing" className={s.sectionTitle}>Housing</h3>
        <dl className={s.facts}>
          {asset.parent && (
            <FactRow label="Housed in">
              <button type="button" className={s.refBtn} onClick={() => onGoTo({ id: asset.parent!.id, code: asset.parent!.asset_code })}>
                {asset.parent.asset_code}
              </button>
            </FactRow>
          )}
          {asset.children_count > 0 && <FactRow label="Houses">{asset.children_count} assets</FactRow>}
        </dl>
      </section>
    )}

    <ConnectionsSection
      assetId={asset.id}
      assetCode={asset.asset_code}
      types={catalogue?.connection_types ?? ['FEED']}
      onGoTo={(id, code) => onGoTo({ id, code })}
      onTrace={direction => onTrace(asset.id, direction)}
    />

    <DetailsSection
      key={asset.id}
      specs={typeSpec?.attributes ?? []}
      record={asset}
      capacity={capacityLabel ? { label: capacityLabel, capacity: asset.capacity, used: asset.used_capacity } : undefined}
      save={asPatchable(detailsSave)}
    />
    <RecordSection creation={asset.creation_method} created={asset.created_at} updated={asset.updated_at} />
    <HistorySection entityId={asset.id} />
  </>);
}

// ── Cable body ───────────────────────────────────────────────

const ROUTE_LABEL: Record<string, string> = {
  ROAD_GRAPH: 'Follows the roads (routed)',
  IMPORTED: 'As built (imported survey)',
  MANUAL_GEOMETRY: 'Drawn by hand',
  DIRECT: 'Straight to the premises (drop)',
};

function CableBody({ cable, catalogue, onFitBounds, onGoTo }: {
  cable: NetCable; catalogue: NetCatalogue | undefined;
  onFitBounds: (bbox: [number, number, number, number]) => void; onGoTo: (ref: AssetRefTarget) => void;
}) {
  const statusSave = useUpdateCable(cable.id);
  const detailsSave = useUpdateCable(cable.id);
  const specs = catalogue?.cable_categories.find(c => c.code === cable.cable_category)?.attributes ?? [];
  const asPatchable = (m: typeof statusSave): Patchable => ({
    mutate: (p, o) => m.mutate(p as NetCablePatch, o), isPending: m.isPending, error: m.error,
  });
  const end = (label: string, ref: NetCable['source']) => (
    <FactRow label={label}>
      {ref
        ? <button type="button" className={s.refBtn} onClick={() => onGoTo({ id: ref.id, code: ref.asset_code })}>{ref.asset_code}</button>
        : 'Not linked'}
    </FactRow>
  );

  return (<>
    <StatusSection key={`${cable.id}:${cable.lifecycle_status}`} status={cable.lifecycle_status} allowed={cable.allowed_transitions} save={asPatchable(statusSave)} />

    <section className={s.section} aria-labelledby="insp-route">
      <h3 id="insp-route" className={s.sectionTitle}>Route</h3>
      <dl className={s.facts}>
        <dt>Length</dt><dd>{formatLength(cable.length_m)}</dd>
        <dt>Fibres</dt><dd>{cable.fiber_count ?? 'Not recorded'}</dd>
        <dt>Installed</dt><dd>{cable.installation_type ? cable.installation_type.charAt(0) + cable.installation_type.slice(1).toLowerCase().replace(/_/g, ' ') : 'Not recorded'}</dd>
        <dt>Geometry</dt><dd>{ROUTE_LABEL[cable.route_method] ?? cable.route_method}</dd>
        {end('From', cable.source)}
        {end('To', cable.dest)}
      </dl>
      <div className={s.transition}>
        <button type="button" className={s.linkBtn} onClick={() => onFitBounds(cable.bbox)}>
          <Crosshair size={14} aria-hidden /> Zoom to cable
        </button>
      </div>
    </section>

    <FibresSection cableId={cable.id} statuses={catalogue?.fiber_statuses ?? ['FREE', 'USED', 'RESERVED', 'FAULTY', 'DARK']} />

    <DetailsSection key={cable.id} specs={specs} record={cable} save={asPatchable(detailsSave)} />
    <RecordSection creation={cable.creation_method} created={cable.created_at} updated={cable.updated_at} />
    <HistorySection entityId={cable.id} />
  </>);
}

// ── Shell ────────────────────────────────────────────────────

interface Props {
  kind:        'asset' | 'cable';
  id:          string;
  typeLabel:   (t: NetAssetType) => string;
  cableLabel:  (c: NetCableCategory) => string;
  onClose:     () => void;
  onZoomTo:    (lng: number, lat: number) => void;
  onFitBounds: (bbox: [number, number, number, number]) => void;
  onGoTo:      (ref: AssetRefTarget) => void;
  onTrace:     (assetId: string, direction: NetTraceDirection) => void;
}

export function AssetInspector({ kind, id, typeLabel, cableLabel, onClose, onZoomTo, onFitBounds, onGoTo, onTrace }: Props) {
  const catalogue = useCatalogue();
  const asset = useAsset(kind === 'asset' ? id : null);
  const cable = useCable(kind === 'cable' ? id : null);
  const q = kind === 'asset' ? asset : cable;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  const notFound = (q.error as ApiError | null)?.status === 404;
  const code = kind === 'asset' ? asset.data?.asset_code : cable.data?.asset_code;
  const sub = kind === 'asset'
    ? asset.data && `${typeLabel(asset.data.asset_type)}${asset.data.name && asset.data.name !== asset.data.asset_code ? `, ${asset.data.name}` : ''}`
    : cable.data && `${cableLabel(cable.data.cable_category)} cable${cable.data.name ? `, ${cable.data.name}` : ''}`;

  return (
    <aside className={s.inspector} aria-label={kind === 'asset' ? 'Asset details' : 'Cable details'}>
      <div className={s.inspHead}>
        {kind === 'asset' && asset.data && <img className={s.inspPlate} src={markerDataUrl(asset.data.asset_type)} alt="" />}
        {kind === 'cable' && cable.data && (
          <svg className={s.inspPlate} viewBox="0 0 40 40" aria-hidden="true">
            <path d="M5 30 C 15 30, 20 10, 35 10" fill="none" stroke="#FFFFFF" strokeWidth={CABLE_STYLE[cable.data.cable_category].width * 2 + 4} strokeLinecap="round" />
            <path d="M5 30 C 15 30, 20 10, 35 10" fill="none" stroke={CABLE_STYLE[cable.data.cable_category].color} strokeWidth={CABLE_STYLE[cable.data.cable_category].width * 2} strokeLinecap="round" />
          </svg>
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <h2 className={s.inspTitle}>{code ?? (q.isLoading ? 'Loading…' : kind === 'asset' ? 'Asset' : 'Cable')}</h2>
          {sub && <p className={s.inspSub}>{sub}</p>}
        </div>
        <button type="button" className={s.iconBtn} onClick={onClose} aria-label="Close details">
          <X size={18} aria-hidden />
        </button>
      </div>

      <div className={s.inspBody}>
        {q.isLoading && [0, 1, 2, 3, 4].map(i => <div key={i} className={s.skeleton} />)}
        {q.isError && (
          <p className={s.error} role="alert">
            {notFound
              ? `This ${kind} is no longer in the live network. It may have been retired or removed.`
              : `Couldn't load this ${kind}. Check your connection and try again.`}
          </p>
        )}
        {asset.data && kind === 'asset' && <AssetBody asset={asset.data} catalogue={catalogue.data} onZoomTo={onZoomTo} onGoTo={onGoTo} onTrace={onTrace} />}
        {cable.data && kind === 'cable' && <CableBody cable={cable.data} catalogue={catalogue.data} onFitBounds={onFitBounds} onGoTo={onGoTo} />}
      </div>
    </aside>
  );
}
