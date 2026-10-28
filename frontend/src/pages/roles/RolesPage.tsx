// ============================================================
// OPSYN — RolesPage  (Stage 6 redesign)
// ============================================================

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { rolesApi } from '../../api/index';
import { useUIStore } from '../../store/ui.store';
import { Button, Badge, Modal, Input, Select, Textarea } from '../../components/ui';
import type { ApiError } from '../../api/client';
import { Plus } from 'lucide-react';
import { Page, PageHeader } from '../../components/layout/Page';

function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, message?: string) => addToast({ type: 'success', title, message }),
    error:   (title: string, message?: string) => addToast({ type: 'error',   title, message }),
  };
}

const LC: Record<number, string> = {
  5: 'var(--color-red)',
  4: 'var(--color-amber)',
  3: 'var(--color-green)',
  2: 'var(--color-teal)',
  1: 'var(--color-text-muted)',
};

const LC_VARIANT: Record<number, any> = {
  5: 'critical',
  4: 'warning',
  3: 'resolved',
  2: 'info',
  1: 'info',
};

const LC_LABEL: Record<number, string> = {
  5: 'Super Admin',
  4: 'Manager',
  3: 'Senior',
  2: 'Standard',
  1: 'Viewer',
};

const PERM_MATRIX = [
  { permission: 'View Dashboard',         levels: [1, 2, 3, 4, 5] },
  { permission: 'View Staff',             levels: [2, 3, 4, 5] },
  { permission: 'Create Staff',           levels: [3, 4, 5] },
  { permission: 'Manage Staff',           levels: [4, 5] },
  { permission: 'View Tasks',             levels: [1, 2, 3, 4, 5] },
  { permission: 'Create Tasks',           levels: [2, 3, 4, 5] },
  { permission: 'Assign Tasks',           levels: [3, 4, 5] },
  { permission: 'View Outages',           levels: [1, 2, 3, 4, 5] },
  { permission: 'Create Outages',         levels: [2, 3, 4, 5] },
  { permission: 'Resolve Outages',        levels: [3, 4, 5] },
  { permission: 'View Projects',          levels: [1, 2, 3, 4, 5] },
  { permission: 'Create Projects',        levels: [3, 4, 5] },
  { permission: 'Manage Projects',        levels: [4, 5] },
  { permission: 'View Reports',           levels: [3, 4, 5] },
  { permission: 'Export Reports',         levels: [4, 5] },
  { permission: 'Onboarding Mgr Approve', levels: [4, 5] },
  { permission: 'Onboarding Admin Approve', levels: [5] },
  { permission: 'Manage Roles',           levels: [5] },
  { permission: 'Manage Settings',        levels: [5] },
  { permission: 'View Audit Logs',        levels: [4, 5] },
];

const LEVEL_OPTS = [
  { label: '1 — Viewer',      value: '1' },
  { label: '2 — Standard',    value: '2' },
  { label: '3 — Senior',      value: '3' },
  { label: '4 — Manager',     value: '4' },
  { label: '5 — Super Admin', value: '5' },
];

export default function RolesPage() {
  const toast = useToast();
  const qc    = useQueryClient();

  const [addModal, setAddModal] = useState(false);
  const [form, setForm] = useState({ name: '', level: '2', description: '' });

  const { data, isLoading } = useQuery({ queryKey: ['roles'], queryFn: () => rolesApi.getRoles() });

  const create = useMutation({
    mutationFn: () => rolesApi.createRole({ name: form.name, level: parseInt(form.level), description: form.description }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['roles'] });
      setAddModal(false);
      setForm({ name: '', level: '2', description: '' });
      toast.success('Role created');
    },
    onError: (e: ApiError) => toast.error('Failed', e?.response?.data?.detail ?? e?.message),
  });

  const set  = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }));
  const roles = Array.isArray(data) ? data : (data as any)?.items ?? [];

  return (
    <Page>

        {/* Header */}
        <PageHeader
        title={<>Roles & Permissions</>}
        lede={<>{roles.length} role{roles.length !== 1 ? 's' : ''} defined · Level-based access control</>}
        primary={<Button variant="primary" size="sm" onClick={() => setAddModal(true)} leftIcon={<Plus size={16} aria-hidden="true" />}>Add Role</Button>}
      />

        <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: 20 }}>

          {/* Defined Roles */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-card)', overflow: 'hidden' }}>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--color-border)', background: 'var(--color-surface)' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text-muted)', letterSpacing: '.06em', textTransform: 'uppercase' }}>
                Defined Roles
              </span>
            </div>
            {isLoading ? (
              <div style={{ padding: 24, textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 12 }}>Loading…</div>
            ) : roles.length === 0 ? (
              <div style={{ padding: 24, textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 12 }}>No roles yet</div>
            ) : roles.map((r: any) => (
              <div key={r.id} style={{ padding: '12px 16px', borderBottom: '1px solid var(--color-border)', display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{
                  width: 32, height: 32, borderRadius: 8,
                  background: `${LC[r.level] ?? 'var(--color-teal)'}18`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700,
                  color: LC[r.level] ?? 'var(--color-teal)',
                  flexShrink: 0,
                }}>
                  {r.level}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-primary)' }}>{r.name}</div>
                  {r.description && (
                    <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 1,
                      overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
                      {r.description}
                    </div>
                  )}
                </div>
                <Badge variant={LC_VARIANT[r.level] ?? 'info'} size="sm">
                  {LC_LABEL[r.level] ?? `L${r.level}`}
                </Badge>
              </div>
            ))}
          </div>

          {/* Permission Matrix */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-card)', overflow: 'hidden' }}>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--color-border)', background: 'var(--color-surface)' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text-muted)', letterSpacing: '.06em', textTransform: 'uppercase' }}>
                Permission Matrix
              </span>
            </div>
            <div style={{ overflowX: 'auto' }} tabIndex={0} role="region" aria-label="Roles table">
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                <thead>
                  <tr style={{ background: 'var(--color-surface)' }}>
                    <th style={{ padding: '8px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--color-text-muted)', borderBottom: '1px solid var(--color-border)', fontSize: 10, letterSpacing: '.04em' }}>
                      Permission
                    </th>
                    {[1, 2, 3, 4, 5].map(l => (
                      <th key={l} style={{ padding: '8px 12px', textAlign: 'center', fontWeight: 700, color: LC[l], borderBottom: '1px solid var(--color-border)', fontSize: 10, whiteSpace: 'nowrap' }}>
                        L{l}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {PERM_MATRIX.map((row, i) => (
                    <tr key={row.permission} style={{ background: i % 2 === 0 ? 'var(--surface)' : 'var(--color-surface)' }}>
                      <td style={{ padding: '7px 16px', color: 'var(--color-text-primary)', fontWeight: 500, borderBottom: '1px solid var(--color-border)', fontSize: 11 }}>
                        {row.permission}
                      </td>
                      {[1, 2, 3, 4, 5].map(l => (
                        <td key={l} style={{ padding: '7px 12px', textAlign: 'center', borderBottom: '1px solid var(--color-border)' }}>
                          {row.levels.includes(l) ? (
                            <span style={{ color: LC[l], fontSize: 14 }}>✓</span>
                          ) : (
                            <span style={{ color: 'var(--color-border)', fontSize: 12 }}>—</span>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

        </div>
      

      {/* Add Role modal */}
      <Modal
        open={addModal}
        onClose={() => setAddModal(false)}
        title="Add Role"
        footer={
          <>
            <Button variant="secondary" onClick={() => setAddModal(false)}>Cancel</Button>
            <Button
              variant="primary"
              onClick={() => create.mutate()}
              disabled={!form.name || create.isPending}
              loading={create.isPending}
            >
              Create Role
            </Button>
          </>
        }
      >
        <Input label="Role Name *" value={form.name} onChange={v => set('name', v)} placeholder="e.g. Senior Engineer" />
        <Select label="Access Level *" value={form.level} onChange={v => set('level', v)} options={LEVEL_OPTS} />
        <Textarea label="Description" value={form.description} onChange={v => set('description', v)} placeholder="Role responsibilities…" rows={2} />
      </Modal>
    </Page>
  );
}
