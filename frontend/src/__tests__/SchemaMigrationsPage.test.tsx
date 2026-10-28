// ============================================================
// OPSYN — src/__tests__/SchemaMigrationsPage.test.tsx
// Covers the migration history surface: rendering, the SQL review
// modal, and the gating rules around apply/revert.
// Run: npm test
// ============================================================

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import SchemaMigrationsPage from '../pages/form-builder/SchemaMigrationsPage';

// ── Mocks ─────────────────────────────────────────────────────
// vi.mock factories are hoisted, so all mock data is inlined.

const PENDING_SQL = 'ALTER TABLE tenant_acme_forms_data ADD COLUMN "new_field" TEXT';

vi.mock('../api/form-builder.api', () => ({
  formBuilderApi: {
    getSchema: vi.fn().mockResolvedValue({
      id: 'schema-1', tenant_id: 'tenant-1', name: 'Site Survey',
      machine_name: 'site_survey', module: 'forms', status: 'published',
      current_version: 3, description: null, icon: null, color: null,
      created_by: null, created_at: '2026-05-01T09:00:00Z', updated_at: '2026-05-01T09:00:00Z',
    }),
    getMigrations: vi.fn().mockResolvedValue({
      migrations: [
        {
          id: 'm-pending', schema_id: 'schema-1', migration_name: 'add new_field',
          plan_hash: 'a'.repeat(64), change_type: 'add_column', status: 'pending',
          table_name: 'tenant_acme_forms_data', is_destructive: false,
          field_changes: [{ action: 'add', field_key: 'new_field', from_type: null, to_type: 'TEXT', options: null, warning: null }],
          applied_by: null, applied_at: null, rolled_back_at: null,
          error_message: null, execution_duration_ms: null,
          created_at: '2026-05-02T11:00:00Z',
        },
        {
          id: 'm-applied', schema_id: 'schema-1', migration_name: 'drop legacy_field',
          plan_hash: 'b'.repeat(64), change_type: 'drop_column', status: 'applied',
          table_name: 'tenant_acme_forms_data', is_destructive: true,
          field_changes: [{ action: 'delete', field_key: 'legacy_field', from_type: 'TEXT', to_type: '', options: null, warning: 'Values are not recoverable' }],
          applied_by: 'u1', applied_at: '2026-05-03T12:00:00Z', rolled_back_at: null,
          error_message: null, execution_duration_ms: 1450,
          created_at: '2026-05-03T11:59:00Z',
        },
      ],
      total: 2, page: 1, limit: 25,
    }),
    getMigration: vi.fn().mockImplementation(async (id: string) => {
      if (id === 'm-applied') {
        return {
          id: 'm-applied', schema_id: 'schema-1', migration_name: 'drop legacy_field',
          plan_hash: 'b'.repeat(64), change_type: 'drop_column', status: 'applied',
          table_name: 'tenant_acme_forms_data', is_destructive: true,
          field_changes: [{ action: 'delete', field_key: 'legacy_field', from_type: 'TEXT', to_type: '', options: null, warning: 'Values are not recoverable' }],
          applied_by: 'u1', applied_at: '2026-05-03T12:00:00Z', rolled_back_at: null,
          error_message: null, execution_duration_ms: 1450,
          created_at: '2026-05-03T11:59:00Z',
          forward_sql: 'ALTER TABLE tenant_acme_forms_data DROP COLUMN "legacy_field"',
          rollback_sql: 'ALTER TABLE tenant_acme_forms_data ADD COLUMN "legacy_field" TEXT',
        };
      }
      return {
        id: 'm-pending', schema_id: 'schema-1', migration_name: 'add new_field',
        plan_hash: 'a'.repeat(64), change_type: 'add_column', status: 'pending',
        table_name: 'tenant_acme_forms_data', is_destructive: false,
        field_changes: [{ action: 'add', field_key: 'new_field', from_type: null, to_type: 'TEXT', options: null, warning: null }],
        applied_by: null, applied_at: null, rolled_back_at: null,
        error_message: null, execution_duration_ms: null,
        created_at: '2026-05-02T11:00:00Z',
        forward_sql: PENDING_SQL,
        rollback_sql: 'ALTER TABLE tenant_acme_forms_data DROP COLUMN "new_field"',
      };
    }),
    applyMigration:     vi.fn().mockResolvedValue({
      migration_id: 'm-pending', table_name: 'tenant_acme_forms_data',
      columns_added: ['new_field'], execution_duration_ms: 320,
      applied_at: '2026-05-04T08:00:00Z',
    }),
    rollbackMigration:  vi.fn().mockResolvedValue({
      migration_id: 'm-applied', rolled_back_at: '2026-05-04T08:05:00Z',
    }),
  },
}));

vi.mock('../store/ui.store', () => ({
  useUIStore: () => ({ addToast: vi.fn(), toasts: [] }),
}));

// ── Helpers ───────────────────────────────────────────────────

const SCHEMA_ID = 'schema-1';

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/form-builder/${SCHEMA_ID}/migrations`]}>
        <Routes>
          <Route path="/form-builder/:schemaId/migrations" element={<SchemaMigrationsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// ══════════════════════════════════════════════════════════════
//  History table
// ══════════════════════════════════════════════════════════════

describe('SchemaMigrationsPage — history', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('renders the schema name and a row per migration', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Site Survey')).toBeTruthy();
    });
    expect(screen.getByText('add new_field')).toBeTruthy();
    expect(screen.getByText('drop legacy_field')).toBeTruthy();
  });

  it('summarises counts by status', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Pending')).toBeTruthy();
    });
    expect(screen.getByText('Rolled back')).toBeTruthy();
  });

  it('passes the status filter through to the API', async () => {
    const { formBuilderApi } = await import('../api/form-builder.api');
    renderPage();
    await waitFor(() => expect(formBuilderApi.getMigrations).toHaveBeenCalled());

    await userEvent.click(screen.getByRole('combobox'));
    await userEvent.click(await screen.findByRole('option', { name: 'Pending' }));

    await waitFor(() => {
      expect(formBuilderApi.getMigrations).toHaveBeenCalledWith(
        expect.objectContaining({ schema_id: SCHEMA_ID, status: 'pending' }),
      );
    });
  });
});

// ══════════════════════════════════════════════════════════════
//  Detail modal
// ══════════════════════════════════════════════════════════════

describe('SchemaMigrationsPage — detail modal', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('shows the exact forward SQL for a pending plan', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('add new_field')).toBeTruthy());

    await userEvent.click(screen.getByText('Review'));
    await waitFor(() => expect(screen.getByText(PENDING_SQL)).toBeTruthy());
  });

  it('offers Apply for a pending migration', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('add new_field')).toBeTruthy());

    await userEvent.click(screen.getByText('Review'));
    await waitFor(() => expect(screen.getByRole('button', { name: /^apply$/i })).toBeTruthy());
  });

  it('applies a pending plan when confirmed', async () => {
    const { formBuilderApi } = await import('../api/form-builder.api');
    renderPage();
    await waitFor(() => expect(screen.getByText('add new_field')).toBeTruthy());

    await userEvent.click(screen.getByText('Review'));
    await userEvent.click(await screen.findByRole('button', { name: /^apply$/i }));

    await waitFor(() => {
      expect(formBuilderApi.applyMigration).toHaveBeenCalledWith('m-pending');
    });
  });

  it('warns that a destructive migration cannot be reverted', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('drop legacy_field')).toBeTruthy());

    await userEvent.click(screen.getByText('drop legacy_field'));
    await waitFor(() => {
      expect(screen.getByText(/refuses to revert it/i)).toBeTruthy();
    });
  });

  it('withholds Revert for a destructive migration', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('drop legacy_field')).toBeTruthy());

    await userEvent.click(screen.getByText('drop legacy_field'));
    // Wait on the modal's own SQL, which is unique, rather than the name —
    // the name now appears in both the table row and the dialog title.
    await waitFor(() => {
      expect(
        screen.getByText('ALTER TABLE tenant_acme_forms_data DROP COLUMN "legacy_field"'),
      ).toBeTruthy();
    });

    expect(screen.queryByRole('button', { name: /^revert$/i })).toBeNull();
  });

  it('renders the error message for a failed migration', async () => {
    const { formBuilderApi } = await import('../api/form-builder.api');
    vi.mocked(formBuilderApi.getMigration).mockResolvedValueOnce({
      id: 'm-pending', schema_id: SCHEMA_ID, migration_name: 'add new_field',
      plan_hash: 'c'.repeat(64), change_type: 'add_column', status: 'failed',
      table_name: 'tenant_acme_forms_data', is_destructive: false,
      field_changes: [],
      applied_by: null, applied_at: null, rolled_back_at: null,
      error_message: 'column "new_field" already exists',
      execution_duration_ms: 12,
      created_at: '2026-05-02T11:00:00Z',
      forward_sql: PENDING_SQL, rollback_sql: null,
    });

    renderPage();
    await waitFor(() => expect(screen.getByText('add new_field')).toBeTruthy());

    await userEvent.click(screen.getByText('Review'));
    await waitFor(() => {
      expect(screen.getByText(/already exists/i)).toBeTruthy();
    });
  });
});
