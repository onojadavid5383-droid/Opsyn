// ============================================================
// OPSYN — InfrastructureAuditPage
// Phase 7: Filterable, paginated FTTH asset audit log
// ============================================================

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { infrastructureApi } from '../../api/index';
import { ErrorBoundary } from '../../components/ErrorBoundary';
import { Pagination } from '../../components/ui/Pagination';
import { GlassSelect } from '../../components/glass';
import { PageHeader } from '../../components/layout/Page';

// ── Inline style helpers ──────────────────────────────────────
const s = {
  page: {
    padding: 'clamp(16px, 4vw, 24px) clamp(16px, 4vw, 28px)',
    minWidth: 0,
    width: '100%',
    boxSizing: 'border-box',
    maxWidth: 1200,
    margin: '0 auto',
    fontFamily: 'var(--font)',
    color: 'var(--chalk)',
  } as React.CSSProperties,

  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 20,
    flexWrap: 'wrap' as const,
    gap: 12,
  } as React.CSSProperties,

  title: {
    fontSize: 18,
    fontWeight: 700,
    color: 'var(--chalk)',
    margin: 0,
  } as React.CSSProperties,

  card: {
    background: 'var(--bg2)',
    border: '1px solid var(--wire)',
    borderRadius: 12,
    padding: 20,
    marginBottom: 16,
  } as React.CSSProperties,

  filterRow: {
    display: 'flex',
    gap: 10,
    flexWrap: 'wrap' as const,
    alignItems: 'flex-end',
    marginBottom: 20,
  } as React.CSSProperties,

  filterGroup: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4,
    minWidth: 140,
    flex: '1 1 140px',
  } as React.CSSProperties,

  label: {
    fontSize: 9,
    fontWeight: 700,
    color: 'var(--chalk3)',
    textTransform: 'uppercase' as const,
    letterSpacing: '.1em',
  } as React.CSSProperties,

  input: {
    background: 'var(--bg3)',
    border: '1px solid var(--wire2)',
    borderRadius: 8,
    padding: '7px 10px',
    color: 'var(--chalk)',
    fontFamily: 'var(--font)',
    fontSize: 12,
    outline: 'none',
  } as React.CSSProperties,

  select: {
    background: 'var(--bg3)',
    border: '1px solid var(--wire2)',
    borderRadius: 8,
    padding: '7px 10px',
    color: 'var(--chalk)',
    fontFamily: 'var(--font)',
    fontSize: 12,
    outline: 'none',
  } as React.CSSProperties,

  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: 12,
  } as React.CSSProperties,

  th: {
    textAlign: 'left' as const,
    padding: '8px 10px',
    borderBottom: '1px solid var(--wire)',
    fontSize: 9,
    fontWeight: 700,
    color: 'var(--chalk3)',
    textTransform: 'uppercase' as const,
    letterSpacing: '.08em',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,

  td: {
    padding: '9px 10px',
    borderBottom: '1px solid var(--wire)',
    color: 'var(--chalk)',
    verticalAlign: 'top' as const,
  } as React.CSSProperties,

  mono: {
    fontFamily: 'monospace',
    fontSize: 11,
    color: 'var(--chalk2)',
  } as React.CSSProperties,

  empty: {
    textAlign: 'center' as const,
    padding: '32px 16px',
    color: 'var(--chalk3)',
    fontSize: 13,
  } as React.CSSProperties,
};

// ── Action badge colours ──────────────────────────────────────
function actionBadge(action: string) {
  const map: Record<string, { bg: string; color: string }> = {
    COMMITTED:     { bg: 'rgba(34,197,94,.15)',  color: 'var(--green)'  },
    DELETED:       { bg: 'rgba(244,63,94,.15)',  color: 'var(--rose)'   },
    ROLLED_BACK:   { bg: 'rgba(251,191,36,.15)', color: 'var(--amber)'  },
    CREATED:       { bg: 'rgba(99,102,241,.15)', color: 'var(--indigo)' },
    UPDATED:       { bg: 'rgba(14,165,233,.15)', color: 'var(--sky)'    },
    VALIDATED:     { bg: 'rgba(34,197,94,.10)',  color: 'var(--green)'  },
  };
  const c = map[action?.toUpperCase()] ?? { bg: 'var(--bg3)', color: 'var(--chalk3)' };
  return {
    display: 'inline-flex', alignItems: 'center', padding: '2px 8px',
    borderRadius: 20, fontSize: 10, fontWeight: 700, letterSpacing: '.06em',
    textTransform: 'uppercase' as const, background: c.bg, color: c.color,
  } as React.CSSProperties;
}

// ── Asset-type chip ───────────────────────────────────────────
function assetChip(_assetType: string) {
  return {
    display: 'inline-block', padding: '2px 7px',
    borderRadius: 6, fontSize: 10, fontWeight: 600,
    background: 'var(--bg3)', color: 'var(--chalk2)',
    border: '1px solid var(--wire)',
    textTransform: 'uppercase' as const,
  } as React.CSSProperties;
}

// ── Snapshot expander ─────────────────────────────────────────
function SnapshotPanel({ entryId, onClose }: { entryId: string; onClose: () => void }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['infra-audit-entry', entryId],
    queryFn: () => infrastructureApi.getAuditEntry(entryId),
  });

  const pre: React.CSSProperties = {
    background: 'var(--bg1)', border: '1px solid var(--wire)',
    borderRadius: 8, padding: '10px 12px', fontSize: 11,
    fontFamily: 'monospace', color: 'var(--chalk2)',
    overflowX: 'auto', maxHeight: 240, margin: 0,
    whiteSpace: 'pre-wrap' as const, wordBreak: 'break-all' as const,
  };

  return (
    <tr>
      <td colSpan={8} style={{ padding: '0 10px 12px', background: 'var(--bg1)', borderBottom: '1px solid var(--wire)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, paddingTop: 10 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--chalk2)' }}>Data snapshots</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--chalk3)', fontSize: 14, padding: '2px 6px' }}>✕</button>
        </div>
        {isLoading && <div style={{ color: 'var(--chalk3)', fontSize: 12, padding: '8px 0' }}>Loading…</div>}
        {isError  && <div style={{ color: 'var(--rose)',   fontSize: 12, padding: '8px 0' }}>Failed to load snapshots.</div>}
        {data && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--chalk3)', letterSpacing: '.1em', textTransform: 'uppercase', marginBottom: 5 }}>Before</div>
              <pre style={pre}>{data.old_data ? JSON.stringify(data.old_data, null, 2) : '(none)'}</pre>
            </div>
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--chalk3)', letterSpacing: '.1em', textTransform: 'uppercase', marginBottom: 5 }}>After</div>
              <pre style={pre}>{data.new_data ? JSON.stringify(data.new_data, null, 2) : '(none)'}</pre>
            </div>
          </div>
        )}
      </td>
    </tr>
  );
}

// ── Main page ─────────────────────────────────────────────────
function AuditPageInner() {
  const navigate = useNavigate();

  const [page,    setPage]    = useState(1);
  const [size,    setSize]    = useState(50);
  const [assetType, setAssetType] = useState('');
  const [action,  setAction]  = useState('');
  const [assetKey, setAssetKey] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);

  // Debounced filter: only pass non-empty values
  const params = {
    page, size,
    ...(assetType  ? { asset_type: assetType }   : {}),
    ...(action     ? { action }                   : {}),
    ...(assetKey   ? { asset_key: assetKey }      : {}),
    ...(sessionId  ? { session_id: sessionId }    : {}),
  };

  const { data, isLoading, isError } = useQuery({
    queryKey: ['infra-audit', params],
    queryFn:  () => infrastructureApi.listAuditLog(params),
    staleTime: 30_000,
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  function handleReset() {
    setAssetType('');
    setAction('');
    setAssetKey('');
    setSessionId('');
    setPage(1);
  }

  function toggleRow(id: string) {
    setExpanded(prev => (prev === id ? null : id));
  }

  return (
    <div style={s.page}>
      {/* ── Header ── */}
      <PageHeader
        title="Infrastructure Audit Log"
        lede="Full history of uploads, deletions and changes to FTTH assets"
        primary={<button
          onClick={() => navigate('/infrastructure')}
          style={{
            padding: '7px 16px', borderRadius: 8, border: '1px solid var(--wire)',
            background: 'transparent', color: 'var(--chalk3)', cursor: 'pointer',
            fontFamily: 'var(--font)', fontSize: 12, fontWeight: 600,
          }}
        >
          ← Back to Infrastructure
        </button>}
      />

      {/* ── Filters ── */}
      <div style={s.card}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--chalk2)', marginBottom: 14 }}>Filter</div>
        <div style={s.filterRow}>
          <div style={s.filterGroup}>
            <span style={s.label}>Asset Type</span>
            <GlassSelect value={String(assetType)} onChange={v => { setAssetType(v); setPage(1); }} options={[{ value: 'splitter', label: 'Splitter' }, { value: 'cabinet', label: 'Cabinet' }, { value: 'olt', label: 'OLT' }]} placeholder={'All types'} ariaLabel="Filter by asset type" compact />
          </div>

          <div style={s.filterGroup}>
            <span style={s.label}>Action</span>
            <GlassSelect value={String(action)} onChange={v => { setAction(v); setPage(1); }} options={[{ value: 'COMMITTED', label: 'Committed' }, { value: 'DELETED', label: 'Deleted' }, { value: 'ROLLED_BACK', label: 'Rolled back' }, { value: 'CREATED', label: 'Created' }, { value: 'UPDATED', label: 'Updated' }, { value: 'VALIDATED', label: 'Validated' }]} placeholder={'All actions'} ariaLabel="Filter by action" compact />
          </div>

          <div style={s.filterGroup}>
            <span style={s.label}>Asset Key</span>
            <input
              value={assetKey}
              onChange={e => { setAssetKey(e.target.value); setPage(1); }}
              placeholder="e.g. SPL-001"
              style={s.input}
            />
          </div>

          <div style={{ ...s.filterGroup, flex: '2 1 220px' }}>
            <span style={s.label}>Session ID</span>
            <input
              value={sessionId}
              onChange={e => { setSessionId(e.target.value); setPage(1); }}
              placeholder="UUID"
              style={s.input}
            />
          </div>

          <button
            onClick={handleReset}
            style={{
              padding: '7px 14px', borderRadius: 8, border: '1px solid var(--wire)',
              background: 'transparent', color: 'var(--chalk3)', cursor: 'pointer',
              fontFamily: 'var(--font)', fontSize: 12, alignSelf: 'flex-end',
            }}
          >
            Reset
          </button>
        </div>
      </div>

      {/* ── Table ── */}
      <div style={s.card}>
        {isLoading && (
          <div style={s.empty}>Loading audit log…</div>
        )}
        {isError && (
          <div style={{ ...s.empty, color: 'var(--rose)' }}>Failed to load audit log.</div>
        )}
        {!isLoading && !isError && (
          <>
            <div style={{ overflowX: 'auto' }} tabIndex={0} role="region" aria-label="Audit entries">
            <table style={s.table}>
              <thead>
                <tr>
                  <th style={s.th}>Timestamp</th>
                  <th style={s.th}>Asset Type</th>
                  <th style={s.th}>Asset Key</th>
                  <th style={s.th}>Action</th>
                  <th style={s.th}>Actor</th>
                  <th style={s.th}>Session</th>
                  <th style={{ ...s.th, width: 50 }}></th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 && (
                  <tr>
                    <td colSpan={7} style={s.empty}>No audit entries match the current filters.</td>
                  </tr>
                )}
                {items.map((item: any) => (
                  <>
                    <tr
                      key={item.id}
                      style={{ cursor: 'pointer', background: expanded === item.id ? 'var(--bg1)' : 'transparent' }}
                      onClick={() => toggleRow(item.id)}
                    >
                      <td style={s.td}>
                        <span style={s.mono}>{item.timestamp ? new Date(item.timestamp).toLocaleString() : '—'}</span>
                      </td>
                      <td style={s.td}>
                        <span style={assetChip(item.asset_type)}>{item.asset_type ?? '—'}</span>
                      </td>
                      <td style={s.td}>
                        <span style={s.mono}>{item.asset_key ?? '—'}</span>
                      </td>
                      <td style={s.td}>
                        <span style={actionBadge(item.action)}>{item.action ?? '—'}</span>
                      </td>
                      <td style={s.td}>{item.actor_label ?? '—'}</td>
                      <td style={{ ...s.td, maxWidth: 160 }}>
                        {item.session_id
                          ? <span style={{ ...s.mono, fontSize: 10 }}>{item.session_id.slice(0, 8)}…</span>
                          : '—'}
                      </td>
                      <td style={{ ...s.td, color: 'var(--chalk3)', textAlign: 'center' }}>
                        {expanded === item.id ? '▲' : '▼'}
                      </td>
                    </tr>
                    {expanded === item.id && (
                      <SnapshotPanel
                        key={`snap-${item.id}`}
                        entryId={item.id}
                        onClose={() => setExpanded(null)}
                      />
                    )}
                  </>
                ))}
              </tbody>
            </table>
            </div>

            <div style={{ marginTop: 16 }}>
              <Pagination
                page={page}
                pageSize={size}
                total={total}
                onPage={setPage}
                onPageSize={newSize => { setSize(newSize); setPage(1); }}
                pageSizes={[25, 50, 100, 200]}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function InfrastructureAuditPage() {
  return (
    <ErrorBoundary>
      <AuditPageInner />
    </ErrorBoundary>
  );
}
