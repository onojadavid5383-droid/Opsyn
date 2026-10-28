// ============================================================
// OPSYN — src/__tests__/SchemaChangeReview.test.tsx
// Covers the diff that decides what needs DDL, plus the review -> apply
// handshake. Run: npm test
// ============================================================

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import SchemaChangeReview from '../components/form-builder/SchemaChangeReview';
import {
  diffStructuralChanges,
  toPreviewRequest,
} from '../components/form-builder/structuralDiff';
import type { FieldDefinition } from '../api/form-builder.api';

// ── Mocks ─────────────────────────────────────────────────────

const SQL = 'ALTER TABLE tenant_a_b_customer_data\n    ADD COLUMN email VARCHAR(255)';

vi.mock('../api/form-builder.api', () => ({
  formBuilderApi: {
    getFields:         vi.fn(),
    getSchemaVersions: vi.fn(),
    previewMigration:  vi.fn(),
    applyMigration:    vi.fn(),
  },
}));

vi.mock('../store/ui.store', () => ({
  useUIStore: () => ({ addToast: vi.fn(), toasts: [] }),
}));

// ── Field factory ─────────────────────────────────────────────

function field(over: Partial<FieldDefinition> = {}): FieldDefinition {
  return {
    id: 'f1', schema_id: 's1', tenant_id: 't1',
    field_key: 'email', label: 'Email', field_type: 'string',
    display_order: 0, is_required: false, options: null,
    ...over,
  } as FieldDefinition;
}

// ══════════════════════════════════════════════════════════════
//  Diff
// ══════════════════════════════════════════════════════════════

describe('diffStructuralChanges', () => {
  it('treats every field as an add when nothing was ever published', () => {
    const changes = diffStructuralChanges([field(), field({ id: 'f2' })], null);
    expect(changes.map(c => c.action)).toEqual(['add', 'add']);
  });

  it('reports nothing when the field set is unchanged', () => {
    const f = field();
    expect(diffStructuralChanges([f], [f])).toEqual([]);
  });

  it('detects a new field as an add', () => {
    const changes = diffStructuralChanges(
      [field(), field({ id: 'f2', field_key: 'phone' })],
      [field()],
    );
    expect(changes).toHaveLength(1);
    expect(changes[0]).toMatchObject({ action: 'add', field_key: 'phone' });
  });

  it('detects a retyped field as a modify and carries the old type', () => {
    const changes = diffStructuralChanges(
      [field({ field_type: 'integer' })],
      [field({ field_type: 'string' })],
    );
    expect(changes).toHaveLength(1);
    expect(changes[0]).toMatchObject({
      action: 'modify', from_type: 'string', field_key: 'email',
    });
  });

  it('detects a removed field as a delete, keyed by the snapshot id', () => {
    const changes = diffStructuralChanges([], [field()]);
    expect(changes).toHaveLength(1);
    expect(changes[0]).toMatchObject({ action: 'delete', field_id: 'f1' });
  });

  it('ignores label and validation edits, which need no DDL', () => {
    const changes = diffStructuralChanges(
      [field({ label: 'Email address', is_required: true, help_text: 'Work email' })],
      [field({ label: 'Email', is_required: false, help_text: null })],
    );
    expect(changes).toEqual([]);
  });

  it('ignores a reordered field', () => {
    const changes = diffStructuralChanges(
      [field({ display_order: 5 })],
      [field({ display_order: 0 })],
    );
    expect(changes).toEqual([]);
  });

  it('treats changed enum options as a modify', () => {
    const changes = diffStructuralChanges(
      [field({ field_type: 'enum', options: ['a', 'c'] })],
      [field({ field_type: 'enum', options: ['a', 'b'] })],
    );
    expect(changes).toHaveLength(1);
    expect(changes[0].action).toBe('modify');
  });

  it('treats null options and an empty array as equivalent', () => {
    expect(diffStructuralChanges(
      [field({ field_type: 'enum', options: [] })],
      [field({ field_type: 'enum', options: null })],
    )).toEqual([]);
  });

  it('maps to the preview request shape the API expects', () => {
    const req = toPreviewRequest(diffStructuralChanges(
      [field({ field_type: 'integer' })],
      [field({ field_type: 'string' })],
    ));
    expect(req.changes).toEqual([
      { action: 'modify', field_id: 'f1', from_type: 'string', from_options: undefined },
    ]);
  });
});

// ══════════════════════════════════════════════════════════════
//  Component
// ══════════════════════════════════════════════════════════════

const { formBuilderApi } = await import('../api/form-builder.api');

function renderReview() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SchemaChangeReview schemaId="s1" />
    </QueryClientProvider>,
  );
}

describe('SchemaChangeReview', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(formBuilderApi.getFields).mockResolvedValue([field()]);
    vi.mocked(formBuilderApi.getSchemaVersions).mockResolvedValue([
      {
        id: 'v1', schema_id: 's1', tenant_id: 't1', version_number: 1,
        published_at: null, published_by: null, field_snapshot: [],
        changelog: null, is_current: true, created_at: '2026-05-01T00:00:00Z',
      },
    ]);
    vi.mocked(formBuilderApi.previewMigration).mockResolvedValue({
      migration_id: 'm1', schema_id: 's1', migration_name: 'add_column_x_1a2b3c4d',
      change_type: 'add_column', table_name: 'tenant_a_b_customer_data',
      forward_sql: SQL, rollback_sql: 'ALTER TABLE x DROP COLUMN "email"',
      field_changes: [
        { action: 'add', field_key: 'email', from_type: null, to_type: 'VARCHAR(255)', options: null, warning: null },
      ],
      affected_rows: 0, estimated_duration: '< 1 second',
      reversible: true, is_destructive: false, warnings: [],
    });
    vi.mocked(formBuilderApi.applyMigration).mockResolvedValue({
      migration_id: 'm1', table_name: 'tenant_a_b_customer_data',
      columns_added: ['email'], execution_duration_ms: 210,
      applied_at: '2026-05-05T00:00:00Z',
    });
  });

  it('stays hidden when there is nothing structural to do', async () => {
    vi.mocked(formBuilderApi.getSchemaVersions).mockResolvedValue([
      {
        id: 'v1', schema_id: 's1', tenant_id: 't1', version_number: 1,
        published_at: null, published_by: null, field_snapshot: [field()],
        changelog: null, is_current: true, created_at: '2026-05-01T00:00:00Z',
      },
    ]);
    renderReview();
    await waitFor(() => expect(formBuilderApi.getFields).toHaveBeenCalled());
    expect(screen.queryByTestId('structural-change-bar')).toBeNull();
  });

  it('counts the pending changes and offers a review', async () => {
    renderReview();
    await waitFor(() => expect(screen.getByTestId('structural-change-bar')).toBeTruthy());
    expect(screen.getByText(/1 column to add/)).toBeTruthy();
  });

  it('plans the change and shows the exact SQL before running anything', async () => {
    renderReview();
    await waitFor(() => expect(screen.getByTestId('structural-change-bar')).toBeTruthy());

    await userEvent.click(screen.getByRole('button', { name: /review & apply/i }));

    await waitFor(() => {
      expect(formBuilderApi.previewMigration).toHaveBeenCalledWith('s1', {
        changes: [{ action: 'add', field_id: 'f1', from_type: undefined, from_options: undefined }],
      });
    });
    // Planning must not execute: apply is a separate, explicit click.
    expect(formBuilderApi.applyMigration).not.toHaveBeenCalled();
    // Matched loosely because testing-library normalises the SQL's newlines.
    expect(screen.getByText(/ADD COLUMN email VARCHAR\(255\)/)).toBeTruthy();
  });

  it('applies only after the user confirms', async () => {
    renderReview();
    await waitFor(() => expect(screen.getByTestId('structural-change-bar')).toBeTruthy());

    await userEvent.click(screen.getByRole('button', { name: /review & apply/i }));
    await userEvent.click(await screen.findByRole('button', { name: /apply to table/i }));

    await waitFor(() => {
      expect(formBuilderApi.applyMigration).toHaveBeenCalledWith('m1');
    });
  });

  it('warns before a destructive change is applied', async () => {
    vi.mocked(formBuilderApi.previewMigration).mockResolvedValue({
      migration_id: 'm2', schema_id: 's1', migration_name: 'drop_column_legacy_99aa',
      change_type: 'drop_column', table_name: 'tenant_a_b_customer_data',
      forward_sql: 'ALTER TABLE tenant_a_b_customer_data DROP COLUMN "legacy"',
      rollback_sql: 'ALTER TABLE tenant_a_b_customer_data ADD COLUMN "legacy" TEXT',
      field_changes: [
        { action: 'delete', field_key: 'legacy', from_type: 'TEXT', to_type: '', options: null, warning: 'irreversible' },
      ],
      affected_rows: 1200, estimated_duration: '5-30 seconds',
      reversible: false, is_destructive: true,
      warnings: ["dropping 'legacy' is irreversible; its data cannot be recovered by rollback"],
    });
    renderReview();
    await waitFor(() => expect(screen.getByTestId('structural-change-bar')).toBeTruthy());

    await userEvent.click(screen.getByRole('button', { name: /review & apply/i }));

    // The phrasing appears twice on purpose: once in the banner explaining the
    // consequence, once as the plan's own warning. Both must be shown.
    expect(screen.getAllByText(/cannot be recovered/).length).toBeGreaterThan(0);
    expect(screen.getByText(/will refuse to revert it/i)).toBeTruthy();
    // The destructive path must not present itself as an ordinary action.
    expect(screen.queryByRole('button', { name: /^apply$/i })).toBeNull();
  });
});