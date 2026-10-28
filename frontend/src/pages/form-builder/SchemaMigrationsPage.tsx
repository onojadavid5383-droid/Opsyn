// ============================================================
// OPSYN — SchemaMigrationsPage
// Route: /form-builder/:schemaId/migrations
//
// The audit surface for a schema's dynamic table. Plans are created
// elsewhere (the builder previews a change); this page reviews what was
// planned, runs a pending plan, and reverts an applied one.
//
// Every DDL here runs server-side on the request's own transaction —
// nothing on this page writes a migration file.
// ============================================================

import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  formBuilderApi,
  type MigrationStatus,
  type SchemaMigration,
} from '../../api/form-builder.api';
import type { ApiError } from '../../api/client';
import { useUIStore } from '../../store/ui.store';
import { Button, Badge, DataTable, PageSpinner, type Column, type BadgeTone } from '../../components/ui';
import { Page, PageHeader, PageStats } from '../../components/layout/Page';
import { GlassModal, GlassSelect } from '../../components/glass';
import { ErrorBoundary } from '../../components/ErrorBoundary';
import { ArrowLeft, Database, TriangleAlert } from 'lucide-react';
import s from './SchemaMigrations.module.css';

const PAGE_SIZE = 25;

const STATUS_OPTIONS: { value: MigrationStatus | ''; label: string }[] = [
  { value: 'pending',     label: 'Pending'     },
  { value: 'applied',     label: 'Applied'     },
  { value: 'failed',      label: 'Failed'      },
  { value: 'rolled_back', label: 'Rolled back' },
  { value: 'in_progress', label: 'In progress' },
];

const STATUS_TONE: Record<MigrationStatus, BadgeTone> = {
  pending:     'review',
  in_progress: 'progress',
  applied:     'ok',
  failed:      'critical',
  rolled_back: 'neutral',
};

const STATUS_LABEL: Record<MigrationStatus, string> = {
  pending:     'Pending',
  in_progress: 'In progress',
  applied:     'Applied',
  failed:      'Failed',
  rolled_back: 'Rolled back',
};

function MigrationStatusBadge({ status }: { status?: MigrationStatus }) {
  if (!status) return <Badge tone="neutral">Unknown</Badge>;
  return <Badge tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Badge>;
}

function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, message?: string) => addToast({ type: 'success', title, message }),
    error:   (title: string, message?: string) => addToast({ type: 'error',   title, message }),
  };
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

function fmtDuration(ms: number | null): string {
  if (ms === null) return '—';
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`;
}

// ── Detail modal ───────────────────────────────────────────────

function MigrationDetailModal({
  migrationId, schemaId, onClose,
}: {
  migrationId: string;
  schemaId:   string;
  onClose:    () => void;
}) {
  const queryClient = useQueryClient();
  const toast       = useToast();
  const [confirmRollback, setConfirmRollback] = useState(false);

  const detailQ = useQuery({
    queryKey: ['form-builder', 'migration', migrationId],
    queryFn:  () => formBuilderApi.getMigration(migrationId),
  });
  const m = detailQ.data;

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['form-builder', 'migrations', schemaId] });

  const applyMut = useMutation({
    mutationFn: () => formBuilderApi.applyMigration(migrationId),
    onSuccess: (r) => {
      invalidate();
      toast.success(
        'Migration applied',
        `${r.columns_added.length} column(s) added in ${fmtDuration(r.execution_duration_ms)}`,
      );
      onClose();
    },
    onError: (e: ApiError) => toast.error('Could not apply migration', e?.detail),
  });

  const rollbackMut = useMutation({
    mutationFn: () => formBuilderApi.rollbackMigration(migrationId),
    onSuccess: () => {
      invalidate();
      toast.success('Migration reverted');
      onClose();
    },
    onError: (e: ApiError) => toast.error('Could not revert migration', e?.detail),
  });

  const canApply     = m?.status === 'pending';
  const canRollback  = m?.status === 'applied' && !m.is_destructive;
  const isBusy       = applyMut.isPending || rollbackMut.isPending;

  return (
    <GlassModal
      open
      onClose={onClose}
      size="lg"
      ariaLabel="Migration detail"
      title={m?.migration_name ?? 'Migration'}
      description={m?.table_name ?? undefined}
      eyebrow={<MigrationStatusBadge status={m?.status} />}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Close</Button>
          {canRollback && (
            confirmRollback ? (
              <div className={s.confirm}>
                <span className={s.confirmText}>
                  {m.is_destructive
                    ? 'This change cannot be reversed.'
                    : 'Revert this change?'}
                </span>
                {!m.is_destructive && (
                  <>
                    <Button variant="ghost" size="sm" onClick={() => setConfirmRollback(false)}>
                      Cancel
                    </Button>
                    <Button
                      variant="danger" size="sm"
                      onClick={() => rollbackMut.mutate()}
                      disabled={isBusy}
                    >
                      {rollbackMut.isPending ? 'Reverting…' : 'Confirm revert'}
                    </Button>
                  </>
                )}
              </div>
            ) : (
              <Button variant="secondary" onClick={() => setConfirmRollback(true)}>
                Revert
              </Button>
            )
          )}
          {canApply && (
            <Button
              variant={m.is_destructive ? 'danger' : 'primary'}
              onClick={() => applyMut.mutate()}
              disabled={isBusy}
            >
              {applyMut.isPending ? 'Applying…' : 'Apply'}
            </Button>
          )}
        </>
      }
    >
      {detailQ.isLoading && <PageSpinner />}

      {m && (
        <div className={s.detail}>
          <dl className={s.facts}>
            <div><dt>Plan hash</dt><dd className={s.mono}>{m.plan_hash.slice(0, 16)}…</dd></div>
            <div><dt>Change</dt><dd>{m.change_type}</dd></div>
            <div><dt>Created</dt><dd>{fmtDate(m.created_at)}</dd></div>
            <div><dt>Applied</dt><dd>{fmtDate(m.applied_at)}</dd></div>
            <div><dt>Duration</dt><dd className={s.numeric}>{fmtDuration(m.execution_duration_ms)}</dd></div>
            <div>
              <dt>Rolled back</dt>
              <dd>{m.rolled_back_at ? fmtDate(m.rolled_back_at) : '—'}</dd>
            </div>
          </dl>

          {m.is_destructive && (
            <p className={s.danger}>
              <TriangleAlert size={14} aria-hidden="true" />
              <span>
                Flagged destructive. Its rollback restores the column shape but not the
                values it held, so the backend refuses to revert it.
              </span>
            </p>
          )}

          {m.error_message && (
            <p className={s.danger}>
              <TriangleAlert size={14} aria-hidden="true" />
              <span className={s.mono}>{m.error_message}</span>
            </p>
          )}

          {m.field_changes.length > 0 && (
            <table className={s.changes}>
              <thead>
                <tr>
                  <th>Action</th><th>Field</th><th>From</th><th>To</th><th>Note</th>
                </tr>
              </thead>
              <tbody>
                {m.field_changes.map((fc) => (
                  <tr key={`${fc.action}-${fc.field_key}`}>
                    <td>{fc.action}</td>
                    <td className={s.mono}>{fc.field_key}</td>
                    <td className={s.mono}>{fc.from_type ?? '—'}</td>
                    <td className={s.mono}>{fc.to_type}</td>
                    <td className={s.note}>{fc.warning ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className={s.sqlBlock}>
            <div className={s.sqlHead}>
              <Database size={13} aria-hidden="true" />
              Forward SQL
            </div>
            <pre className={s.sql}>{m.forward_sql}</pre>
          </div>

          {m.rollback_sql && (
            <div className={s.sqlBlock}>
              <div className={s.sqlHead}>
                <Database size={13} aria-hidden="true" />
                Rollback SQL
              </div>
              <pre className={s.sql}>{m.rollback_sql}</pre>
            </div>
          )}
        </div>
      )}
    </GlassModal>
  );
}

// ── Page ───────────────────────────────────────────────────────

function SchemaMigrationsContent() {
  const { schemaId } = useParams<{ schemaId: string }>();
  const navigate     = useNavigate();

  const [status,  setStatus]  = useState<MigrationStatus | ''>('');
  const [page,    setPage]    = useState(1);
  const [openId,  setOpenId]  = useState<string | null>(null);

  const schemaQ = useQuery({
    queryKey: ['form-builder', 'schema', schemaId],
    queryFn:  () => formBuilderApi.getSchema(schemaId!),
    enabled:  !!schemaId,
  });

  const listQ = useQuery({
    queryKey: ['form-builder', 'migrations', schemaId, status, page],
    queryFn:  () => formBuilderApi.getMigrations({
      schema_id: schemaId!,
      status:    status || undefined,
      page,
      limit:     PAGE_SIZE,
    }),
    enabled:  !!schemaId,
  });

  const rows       = listQ.data?.migrations ?? [];
  const total      = listQ.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // Counts are for the whole schema, not the filtered page, so the strip
  // does not jump around as the filter changes.
  const statsQ = useQuery({
    queryKey: ['form-builder', 'migrations', schemaId, 'counts'],
    queryFn:  () => formBuilderApi.getMigrations({ schema_id: schemaId!, limit: 200 }),
    enabled:  !!schemaId,
  });

  const allRows     = statsQ.data?.migrations ?? [];
  const countOf     = (st: MigrationStatus) =>
    allRows.filter(r => r.status === st).length;

  const columns: Column<SchemaMigration>[] = [
    {
      key: 'migration_name', header: 'Migration', render: (_v, row) => (
        <div className={s.stackCell}>
          <span className={s.name}>{row.migration_name}</span>
          <span className={s.sub}>{row.change_type}</span>
        </div>
      ),
    },
    {
      key: 'table_name', header: 'Table', width: 240,
      mono: true, mobile: 'hidden',
      render: (_v, row) => <span className={s.sub}>{row.table_name ?? '—'}</span>,
    },
    {
      key: 'status', header: 'Status', width: 140,
      render: (_v, row) => <MigrationStatusBadge status={row.status} />,
    },
    {
      key: 'applied_at', header: 'Applied', width: 180, mobile: 'hidden',
      render: (_v, row) => <span className={s.sub}>{fmtDate(row.applied_at)}</span>,
    },
    {
      key: 'execution_duration_ms', header: 'Duration', width: 110,
      align: 'right', numeric: true, mobile: 'hidden',
      render: (_v, row) => fmtDuration(row.execution_duration_ms),
    },
    {
      key: 'actions', header: '', width: 120, align: 'right',
      render: (_v, row) => (
        <div className={s.rowActions}>
          {row.status === 'pending' && (
            <Button
              variant="secondary" size="xs"
              onClick={e => {
                e.stopPropagation();
                setOpenId(row.id);
              }}
            >
              Review
            </Button>
          )}
          {row.is_destructive && (
            <span className={s.destructiveTag} title="Cannot be reverted">
              destructive
            </span>
          )}
        </div>
      ),
    },
  ];

  if (!schemaId) return null;

  return (
    <Page>
      <PageHeader
        title="Schema migrations"
        lede={
          <>
            Structural changes to <span className={s.mono}>{schemaQ.data?.name ?? 'this schema'}</span>'s
            table. Plans run as a single transaction; applied changes are recorded here.
          </>
        }
        secondary={[
          {
            id: 'builder',
            label: 'Back to builder',
            icon: <ArrowLeft size={14} aria-hidden="true" />,
            onSelect: () => navigate(`/form-builder/${schemaId}`),
          },
        ]}
      />

      <PageStats
        items={[
          { label: 'Pending',   value: countOf('pending') },
          { label: 'Applied',   value: countOf('applied') },
          {
            label: 'Failed',
            value: countOf('failed'),
            tone: countOf('failed') > 0 ? 'critical' : undefined,
          },
          { label: 'Rolled back', value: countOf('rolled_back') },
        ]}
      />

      <div className={s.toolbar}>
        <GlassSelect
          label="Status"
          value={status}
          onChange={v => { setStatus(v as MigrationStatus | ''); setPage(1); }}
          options={STATUS_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
          placeholder="All statuses"
          compact
        />
        <span className={s.count}>{total} migration{total === 1 ? '' : 's'}</span>
      </div>

      {listQ.isLoading ? (
        <PageSpinner />
      ) : rows.length === 0 ? (
        <p className={s.empty}>
          {status ? `No ${status.replace(/_/g, ' ')} migrations.` : 'No migrations for this schema yet.'}
        </p>
      ) : (
        <DataTable
          caption="Schema migration history"
          columns={columns}
          data={rows}
          rowKey={r => r.id}
          onRowClick={row => setOpenId(row.id)}
        />
      )}

      {totalPages > 1 && (
        <nav className={s.pager} aria-label="Migration history pages">
          <Button
            variant="secondary" size="sm" disabled={page === 1}
            onClick={() => setPage(p => Math.max(1, p - 1))}
          >
            Previous
          </Button>
          <span className={s.count}>Page {page} of {totalPages}</span>
          <Button
            variant="secondary" size="sm" disabled={page === totalPages}
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
          >
            Next
          </Button>
        </nav>
      )}

      {openId && (
        <MigrationDetailModal
          migrationId={openId}
          schemaId={schemaId}
          onClose={() => setOpenId(null)}
        />
      )}
    </Page>
  );
}

export default function SchemaMigrationsPage() {
  return (
    <ErrorBoundary>
      <SchemaMigrationsContent />
    </ErrorBoundary>
  );
}
