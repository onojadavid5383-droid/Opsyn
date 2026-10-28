// ============================================================
// OPSYN — StaffListPage  (Stage 5 redesign)
// Light theme · DataTable · Pagination · Badge · Modal
// ============================================================

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { staffApi } from '../../api/staff.api';
import { rolesApi, orgApi } from '../../api/index';
import { useUIStore } from '../../store/ui.store';
import { useAuthStore } from '../../store/auth.store';
import { Button, Badge, Modal, DataTable, Pagination, type Column } from '../../components/ui';
import type { ApiError } from '../../api/client';
import { GlassSelect } from '../../components/glass';
import { Plus } from 'lucide-react';
import { Page, PageHeader } from '../../components/layout/Page';

const toArr = (d: any): any[] => Array.isArray(d) ? d : (d?.items ?? []);

function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, message?: string) => addToast({ type: 'success', title, message }),
    error:   (title: string, message?: string) => addToast({ type: 'error',   title, message }),
    info:    (title: string, message?: string) => addToast({ type: 'info',    title, message }),
  };
}

const statusVariant = (s: string): any =>
  s === 'active' ? 'resolved' : s === 'suspended' ? 'critical' : 'warning';

export default function StaffListPage() {
  const navigate  = useNavigate();
  const toast     = useToast();
  const qc        = useQueryClient();

  const [search, setSearch]           = useState('');
  const [deptFilter, setDept]         = useState('');
  const [roleFilter, setRole]         = useState('');
  const [statusFilter, setStatus]     = useState('');
  const [page, setPage]               = useState(1);
  const [deactivateTarget, setDeact]  = useState<any>(null);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const roleLevel = useAuthStore(s => s.roleLevel);
  const isAdmin   = roleLevel >= 5;

  const { data, isLoading } = useQuery({
    queryKey: ['staff', 'list', { search, deptFilter, roleFilter, statusFilter, page }],
    queryFn:  () => staffApi.list({ search: search || undefined, dept_id: deptFilter || undefined, role_id: roleFilter || undefined, status: statusFilter || undefined, page, size: 20 }),
  });
  const { data: depts } = useQuery({ queryKey: ['departments'], queryFn: () => orgApi.getDepartments() });
  const { data: roles } = useQuery({ queryKey: ['roles'],       queryFn: () => rolesApi.getRoles() });

  const deactivate = useMutation({
    mutationFn: (id: string) => staffApi.updateStatus(id, 'inactive'),
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['staff'] }); setDeact(null); toast.success('Staff deactivated'); },
    onError: (e: ApiError) => toast.error('Failed', e?.detail),
  });
  const activate = (id: string) =>
    staffApi.updateStatus(id, 'active').then(() => { qc.invalidateQueries({ queryKey: ['staff'] }); toast.success('Reactivated'); });

  const deleteStaff = useMutation({
    mutationFn: (id: string) => staffApi.delete(id),
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['staff'] }); setDeleteTarget(null); toast.success('Staff member deleted'); },
    onError: (e: ApiError) => toast.error('Delete failed', e?.response?.data?.detail ?? e?.detail ?? e?.message),
  });

  const items      = (data as any)?.items ?? [];
  const total      = (data as any)?.total ?? 0;

  const columns: Column[] = [
    {
      key: 'username', header: 'Personnel',
      render: (_v: any, row: any) => {
        const p = row.staff_profile;
        const initials = p ? `${p.first_name?.[0] ?? ''}${p.last_name?.[0] ?? ''}` : row.username?.slice(0, 2).toUpperCase();
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 28, height: 28, borderRadius: '50%',
              background: 'var(--brand)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 11, fontWeight: 700, color: 'var(--color-navy)', flexShrink: 0,
            }}>
              {initials}
            </div>
            <div>
              <div style={{ fontWeight: 500, color: 'var(--color-text-primary)', fontSize: 12 }}>
                {p ? `${p.first_name} ${p.last_name}` : row.username}
              </div>
              <div style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>
                {p?.staff_code} · {row.email}
              </div>
            </div>
          </div>
        );
      },
    },
    {
      key: 'role', header: 'Role', width: 130,
      render: (_v: any, row: any) => (
        <Badge variant="info" size="sm">{row.role?.name ?? '—'}</Badge>
      ),
    },
    {
      key: 'department', header: 'Department', width: 140,
      render: (_v: any, row: any) => (
        <span style={{ fontSize: 12, color: 'var(--color-text-primary)', fontWeight: 500 }}>
          {row.staff_profile?.department?.name ?? '—'}
        </span>
      ),
    },
    {
      key: 'team', header: 'Team', width: 120,
      render: (_v: any, row: any) => (
        <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{row.staff_profile?.team?.name ?? '—'}</span>
      ),
    },
    {
      key: 'region', header: 'Region', width: 110,
      render: (_v: any, row: any) => (
        <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{row.staff_profile?.region?.name ?? '—'}</span>
      ),
    },
    {
      key: 'last_login_at', header: 'Last Active', width: 110,
      render: (_v: any, row: any) => (
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
          {row.last_login_at ? new Date(row.last_login_at).toLocaleDateString('en-GB') : '—'}
        </span>
      ),
    },
    {
      key: 'status', header: 'Status', width: 100,
      render: (_v: any, row: any) => {
        const s = row.staff_profile?.status ?? 'active';
        return <Badge variant={statusVariant(s)} size="sm">{s}</Badge>;
      },
    },
    {
      key: 'id', header: 'Actions', width: isAdmin ? 180 : 140,
      render: (_v: any, row: any) => (
        <div style={{ display: 'flex', gap: 4 }} onClick={(e: React.MouseEvent) => e.stopPropagation()}>
          <Button variant="secondary" size="xs" onClick={() => navigate(`/staff/${row.id}`)}>View</Button>
          {row.staff_profile?.status === 'active'
            ? <Button variant="danger" size="xs" onClick={() => setDeact(row)}>Deactivate</Button>
            : <Button variant="jade"   size="xs" onClick={() => activate(row.id)}>Activate</Button>
          }
          {isAdmin && (
            <Button variant="danger" size="xs" onClick={() => setDeleteTarget(row)}>Delete</Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <Page>

        {/* Header */}
        <PageHeader
        title="Personnel Directory"
        lede={<>{total} total staff members</>}
        primary={<><Button variant="secondary" size="sm">Export CSV</Button><Button variant="primary" size="sm" onClick={() => navigate('/staff/new')} leftIcon={<Plus size={16} aria-hidden="true" />}>Add Personnel</Button></>}
      />

        {/* Filters */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
          <label style={{
            display: 'flex', alignItems: 'center', gap: 8,
            background: 'var(--surface)', border: '1px solid var(--color-border)',
            borderRadius: 8, padding: '7px 12px', flex: '1 1 220px', maxWidth: 320, minWidth: 0, cursor: 'text',
          }}>
            <svg width="13" height="13" viewBox="0 0 13 13" fill="var(--color-text-muted)">
              <circle cx="5.5" cy="5.5" r="4" fill="none" stroke="currentColor" strokeWidth="1.4"/>
              <path d="M9 9l3 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
            </svg>
            <input
              type="search"
              aria-label="Search staff"
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1); }}
              placeholder="Name, email, staff ID…"
              style={{ background: 'none', border: 'none', outline: 'none', color: 'var(--color-text-primary)', fontFamily: 'var(--font-body)', fontSize: 12, width: '100%', minHeight: 24 }}
            />
          </label>
          {[
            { val: deptFilter, set: setDept,   opts: toArr(depts).map((d: any) => ({ label: d.name, value: d.id })),  placeholder: 'All Departments' },
            { val: roleFilter, set: setRole,   opts: toArr(roles).map((r: any) => ({ label: r.name, value: r.id })),  placeholder: 'All Roles' },
            { val: statusFilter, set: setStatus, opts: [{ label: 'Active', value: 'active' }, { label: 'Inactive', value: 'inactive' }, { label: 'Suspended', value: 'suspended' }], placeholder: 'All Statuses' },
          ].map((f, i) => (
            <GlassSelect key={i} value={String(f.val)} onChange={v => { f.set(v); setPage(1); }} options={[...f.opts.map((o: any) => ({ value: String(o.value), label: String(o.label) }))]} placeholder={String(f.placeholder)} ariaLabel={f.placeholder} compact />
          ))}
        </div>

        <DataTable
          columns={columns}
          data={items}
          rowKey={(row: any) => row.id}
          isLoading={isLoading}
          emptyTitle="No staff members found"
          emptyMessage="Adjust your filters or add a new staff member."
          onRowClick={(row: any) => navigate(`/staff/${row.id}`)}
        />

        <div style={{ marginTop: 12 }}>
          <Pagination page={page} pageSize={20} total={total} onPage={setPage} />
        </div>
      

      {/* Deactivate confirmation */}
      <Modal
        open={!!deactivateTarget}
        onClose={() => setDeact(null)}
        title="Confirm Deactivation"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeact(null)}>Cancel</Button>
            <Button variant="danger" onClick={() => deactivate.mutate(deactivateTarget.id)} disabled={deactivate.isPending} loading={deactivate.isPending}>
              Deactivate
            </Button>
          </>
        }
      >
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
          Are you sure you want to deactivate{' '}
          <strong style={{ color: 'var(--color-text-primary)' }}>
            {deactivateTarget?.staff_profile?.first_name} {deactivateTarget?.staff_profile?.last_name}
          </strong>? They will lose access immediately.
        </p>
      </Modal>

      {/* Delete confirmation — admin only */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Staff Member"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button variant="danger" onClick={() => deleteStaff.mutate(deleteTarget.id)} disabled={deleteStaff.isPending} loading={deleteStaff.isPending}>
              Permanently Delete
            </Button>
          </>
        }
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{
            padding: '10px 14px', borderRadius: 8,
            background: 'rgba(239,68,68,.06)', border: '1px solid rgba(239,68,68,.25)',
            fontSize: 12, color: 'var(--color-text-muted)', lineHeight: 1.6,
          }}>
            This action is irreversible. The account will be permanently disabled and removed from all staff lists.
          </div>
          <p style={{ fontSize: 13, color: 'var(--color-text-muted)', lineHeight: 1.6, margin: 0 }}>
            Delete{' '}
            <strong style={{ color: 'var(--color-text-primary)' }}>
              {deleteTarget?.staff_profile?.first_name} {deleteTarget?.staff_profile?.last_name}
            </strong>
            {deleteTarget?.email ? ` (${deleteTarget.email})` : ''}?
          </p>
        </div>
      </Modal>
    </Page>
  );
}
