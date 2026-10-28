// ============================================================
// OPSYN — SchemaChangeReview
// src/components/form-builder/SchemaChangeReview.tsx
//
// The entry point into dynamic DDL. Structural edits are saved to the
// metadata tables as they are made, so by the time anyone thinks about the
// table there can be a backlog of pending changes. This surfaces that backlog
// as a count, and on demand plans it, shows the SQL, and applies it.
//
// Planning is deliberately a separate click from applying. Preview writes a
// `pending` row and returns the exact SQL; nothing executes until the user
// confirms, and what runs is the text they were shown.
// ============================================================

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  formBuilderApi,
  type FieldDefinition,
  type MigrationPlan,
} from '../../api/form-builder.api';
import type { ApiError } from '../../api/client';
import { useUIStore } from '../../store/ui.store';
import { Badge, Button, Spinner } from '../ui';
import { GlassModal } from '../glass';
import { Database, TriangleAlert } from 'lucide-react';
import {
  diffStructuralChanges,
  toPreviewRequest,
  type StructuralChange,
} from './structuralDiff';
import s from './SchemaChangeReview.module.css';

const KEY = 'form-builder';

function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, message?: string) => addToast({ type: 'success', title, message }),
    error:   (title: string, message?: string) => addToast({ type: 'error',   title, message }),
  };
}

function summarise(changes: StructuralChange[]): string {
  const count = (a: StructuralChange['action']) =>
    changes.filter(c => c.action === a).length;
  const parts: string[] = [];
  const added = count('add'), modified = count('modify'), removed = count('delete');
  if (added)    parts.push(`${added} column${added === 1 ? '' : 's'} to add`);
  if (modified) parts.push(`${modified} to retype`);
  if (removed)  parts.push(`${removed} to drop`);
  return parts.join(', ');
}

function PlanModal({
  plan, onClose, onApplied,
}: {
  plan:      MigrationPlan;
  onClose:   () => void;
  onApplied: () => void;
}) {
  const toast  = useToast();
  const qc     = useQueryClient();

  const applyMut = useMutation({
    mutationFn: () => formBuilderApi.applyMigration(plan.migration_id),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: [KEY, 'fields'] });
      qc.invalidateQueries({ queryKey: [KEY, 'migrations'] });
      toast.success(
        'Table updated',
        `${r.columns_added.length} column(s) added in ${r.execution_duration_ms} ms`,
      );
      onApplied();
    },
    onError: (e: ApiError) => toast.error('Could not apply', e?.detail),
  });

  return (
    <GlassModal
      open
      onClose={onClose}
      size="lg"
      ariaLabel="Review table changes"
      title="Review table changes"
      description={`${plan.change_type} on ${plan.table_name}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button
            variant={plan.is_destructive ? 'danger' : 'primary'}
            onClick={() => applyMut.mutate()}
            disabled={applyMut.isPending}
          >
            {applyMut.isPending ? 'Applying…' : 'Apply to table'}
          </Button>
        </>
      }
    >
      <div className={s.plan}>
        <dl className={s.facts}>
          <div><dt>Table</dt><dd className={s.mono}>{plan.table_name}</dd></div>
          <div><dt>Rows affected</dt><dd>{plan.affected_rows.toLocaleString()}</dd></div>
          <div><dt>Est. duration</dt><dd>{plan.estimated_duration}</dd></div>
          <div><dt>Reversible</dt><dd>{plan.reversible ? 'Yes' : 'No'}</dd></div>
        </dl>

        {plan.is_destructive && (
          <p className={s.danger}>
            <TriangleAlert size={14} aria-hidden="true" />
            <span>
              This drops or retypes existing columns. The stored values in them
              cannot be recovered, and the backend will refuse to revert it.
            </span>
          </p>
        )}

        {plan.warnings.length > 0 && (
          <ul className={s.warnings}>
            {plan.warnings.map((w, i) => (
              <li key={i}>
                <TriangleAlert size={13} aria-hidden="true" />
                <span>{w}</span>
              </li>
            ))}
          </ul>
        )}

        {plan.field_changes.length > 0 && (
          <table className={s.changes}>
            <thead>
              <tr><th>Action</th><th>Field</th><th>From</th><th>To</th></tr>
            </thead>
            <tbody>
              {plan.field_changes.map((fc, i) => (
                <tr key={`${fc.action}-${fc.field_key}-${i}`}>
                  <td>{fc.action}</td>
                  <td className={s.mono}>{fc.field_key}</td>
                  <td className={s.mono}>{fc.from_type ?? '—'}</td>
                  <td className={s.mono}>{fc.to_type || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className={s.sqlBlock}>
          <div className={s.sqlHead}>
            <Database size={13} aria-hidden="true" />
            SQL to be executed
          </div>
          <pre className={s.sql}>{plan.forward_sql}</pre>
        </div>
      </div>
    </GlassModal>
  );
}

export default function SchemaChangeReview({
  schemaId, enabled = true,
}: {
  schemaId: string;
  /** False for drafts with no published baseline yet. */
  enabled?:  boolean;
}) {
  const qc      = useQueryClient();
  const toast   = useToast();
  const [plan,  setPlan]  = useState<MigrationPlan | null>(null);

  const fieldsQ = useQuery({
    queryKey: [KEY, 'fields', schemaId],
    queryFn:  () => formBuilderApi.getFields(schemaId),
    enabled:  enabled && !!schemaId,
  });

  const versionsQ = useQuery({
    queryKey: [KEY, 'versions', schemaId],
    queryFn:  () => formBuilderApi.getSchemaVersions(schemaId),
    enabled:  enabled && !!schemaId,
  });

  const current = fieldsQ.data ?? [];
  const baseline = versionsQ.data?.find(v => v.is_current)?.field_snapshot ?? null;
  const changes  = diffStructuralChanges(
    current as FieldDefinition[],
    baseline as FieldDefinition[] | null,
  );

  const previewMut = useMutation({
    mutationFn: () => formBuilderApi.previewMigration(schemaId, toPreviewRequest(changes)),
    onSuccess: setPlan,
    onError: (e: ApiError) => toast.error('Could not plan these changes', e?.detail),
  });

  // Nothing structural pending: stay out of the way entirely.
  if (!enabled || changes.length === 0) return null;

  return (
    <>
      <div className={s.bar} data-testid="structural-change-bar">
        <Badge tone="review">{changes.length}</Badge>
        <span className={s.summary}>
          pending table change{changes.length === 1 ? '' : 's'} — {summarise(changes)}
        </span>
        <Button
          variant="secondary" size="sm"
          onClick={() => previewMut.mutate()}
          disabled={previewMut.isPending}
        >
          {previewMut.isPending ? 'Planning…' : 'Review & apply'}
        </Button>
      </div>

      {previewMut.isPending && <Spinner size="sm" />}

      {plan && (
        <PlanModal
          plan={plan}
          onClose={() => setPlan(null)}
          onApplied={() => {
            setPlan(null);
            // The pending plan is consumed; a fresh diff should now be empty.
            qc.invalidateQueries({ queryKey: [KEY, 'fields', schemaId] });
            qc.invalidateQueries({ queryKey: [KEY, 'versions', schemaId] });
          }}
        />
      )}
    </>
  );
}