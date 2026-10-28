// ============================================================
// OPSYN — OnboardingPage  (Stage 5 redesign)
// ============================================================

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { onboardingApi, rolesApi, orgApi } from '../../api/index';
import { useAuthStore } from '../../store/auth.store';
import { useUIStore } from '../../store/ui.store';
import { Button, Badge, Modal, Input, Select, Textarea, DataTable, type Column } from '../../components/ui';
import type { ApiError } from '../../api/client';
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

const STATUS_VARIANT: Record<string, any> = {
  pending_manager: 'warning',
  pending_admin:   'info',
  approved:        'resolved',
  rejected:        'critical',
};

const STATUS_LABEL: Record<string, string> = {
  pending_manager: 'Awaiting Manager',
  pending_admin:   'Awaiting Admin',
  approved:        'Approved',
  rejected:        'Rejected',
};

function KpiTile({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--color-border)',
      borderRadius: 'var(--radius-card)', padding: '16px 18px',
      borderTop: `3px solid ${color}`,
    }}>
      <div style={{ fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 600, color: 'var(--color-text-muted)', letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 28, fontWeight: 700, color, lineHeight: 1 }}>
        {value}
      </div>
    </div>
  );
}

export default function OnboardingPage() {
  const toast     = useToast();
  const qc        = useQueryClient();
  const roleLevel = useAuthStore((s: any) => s.roleLevel ?? 1);

  const [submitModal, setSubmitModal]   = useState(false);
  const [rejectModal, setRejectModal]   = useState<{ id: string } | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [form, setForm] = useState({
    proposed_first_name: '', proposed_last_name: '',
    proposed_email: '', proposed_role_id: '',
    department_id: '', justification: '',
  });

  const { data, isLoading } = useQuery({ queryKey: ['onboarding'],    queryFn: () => onboardingApi.list() });
  const { data: roles }     = useQuery({ queryKey: ['roles'],         queryFn: () => rolesApi.getRoles() });
  const { data: depts }     = useQuery({ queryKey: ['departments'],   queryFn: () => orgApi.getDepartments() });

  const mgrApprove = useMutation({
    mutationFn: (id: string) => onboardingApi.managerApprove(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['onboarding'] }); toast.success('Phase 1 approved', 'Forwarded to admin for final approval'); },
    onError: (e: ApiError) => toast.error('Failed', e?.response?.data?.detail ?? e?.message),
  });
  const approve = useMutation({
    mutationFn: (id: string) => onboardingApi.approve(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['onboarding'] }); toast.success('Request approved', 'Account provisioned on Opsyn'); },
    onError: (e: ApiError) => toast.error('Failed', e?.response?.data?.detail ?? e?.message),
  });
  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) => onboardingApi.reject(id, reason),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['onboarding'] }); setRejectModal(null); setRejectReason(''); toast.info('Request rejected'); },
    onError: (e: ApiError) => toast.error('Failed', e?.response?.data?.detail ?? e?.message),
  });
  const submit = useMutation({
    mutationFn: () => onboardingApi.submit(form as any),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['onboarding'] });
      setSubmitModal(false);
      setForm({ proposed_first_name: '', proposed_last_name: '', proposed_email: '', proposed_role_id: '', department_id: '', justification: '' });
      toast.success('Request submitted', 'Pending manager approval');
    },
    onError: (e: ApiError) => toast.error('Failed', e?.response?.data?.detail ?? e?.message),
  });

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }));

  const items      = (data as any)?.items ?? [];
  const deptList   = toArr(depts);
  const awaitingMgr   = items.filter((r: any) => r.approval_status === 'pending_manager').length;
  const awaitingAdmin = items.filter((r: any) => r.approval_status === 'pending_admin').length;

  const columns: Column[] = [
    {
      key: 'proposed_first_name', header: 'Proposed Personnel',
      render: (_v: any, row: any) => (
        <div style={{ fontWeight: 500, color: 'var(--color-text-primary)', fontSize: 12 }}>
          {row.proposed_first_name} {row.proposed_last_name}
        </div>
      ),
    },
    {
      key: 'proposed_email', header: 'Email',
      render: (_v: any, row: any) => (
        <span style={{ fontSize: 11, color: 'var(--color-teal)' }}>{row.proposed_email}</span>
      ),
    },
    {
      key: 'department_id', header: 'Department', width: 140,
      render: (_v: any, row: any) => (
        <span style={{ fontSize: 12, color: 'var(--color-text-primary)' }}>
          {deptList.find((d: any) => d.id === row.department_id)?.name ?? row.department_id?.slice(0, 8) ?? '—'}
        </span>
      ),
    },
    {
      key: 'created_at', header: 'Submitted', width: 100,
      render: (_v: any, row: any) => (
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
          {new Date(row.created_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}
        </span>
      ),
    },
    {
      key: 'approval_status', header: 'Status', width: 140,
      render: (_v: any, row: any) => (
        <Badge variant={STATUS_VARIANT[row.approval_status] ?? 'info'} size="sm">
          {STATUS_LABEL[row.approval_status] ?? row.approval_status}
        </Badge>
      ),
    },
    {
      key: 'id', header: 'Actions', width: 200,
      render: (_v: any, row: any) => (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }} onClick={(e: React.MouseEvent) => e.stopPropagation()}>
          {row.approval_status === 'pending_manager' && roleLevel >= 4 && (
            <Button variant="jade" size="xs" onClick={() => mgrApprove.mutate(row.id)} disabled={mgrApprove.isPending}>
              Mgr Approve
            </Button>
          )}
          {row.approval_status === 'pending_admin' && roleLevel >= 5 && (
            <Button variant="jade" size="xs" onClick={() => approve.mutate(row.id)} disabled={approve.isPending}>
              Final Approve
            </Button>
          )}
          {(row.approval_status === 'pending_manager' || row.approval_status === 'pending_admin') && (
            <Button variant="danger" size="xs" onClick={() => { setRejectModal({ id: row.id }); setRejectReason(''); }}>
              Reject
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <Page>

        {/* Header */}
        <PageHeader
        title="Onboarding Requests"
        lede={<>{awaitingMgr} awaiting manager · {awaitingAdmin} awaiting admin · Two-phase approval</>}
        primary={<Button variant="primary" size="sm" onClick={() => setSubmitModal(true)} leftIcon={<Plus size={16} aria-hidden="true" />}>Submit Request</Button>}
      />

        {/* KPI row */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 20 }}>
          <KpiTile label="Awaiting Manager" value={awaitingMgr}                                                    color="var(--color-amber)" />
          <KpiTile label="Awaiting Admin"   value={awaitingAdmin}                                                  color="var(--color-indigo)" />
          <KpiTile label="Approved"         value={items.filter((r: any) => r.approval_status === 'approved').length}  color="var(--color-green)" />
          <KpiTile label="Rejected"         value={items.filter((r: any) => r.approval_status === 'rejected').length}  color="var(--color-red)" />
        </div>

        <DataTable
          columns={columns}
          data={items}
          rowKey={(row: any) => row.id}
          isLoading={isLoading}
          emptyTitle="No onboarding requests"
          emptyMessage="Submit a request to onboard a new team member."
        />
      

      {/* Submit request modal */}
      <Modal
        open={submitModal}
        onClose={() => setSubmitModal(false)}
        title="Submit Onboarding Request"
        footer={
          <>
            <Button variant="secondary" onClick={() => setSubmitModal(false)}>Cancel</Button>
            <Button
              variant="primary"
              onClick={() => submit.mutate()}
              disabled={!form.proposed_first_name || !form.proposed_email || !form.proposed_role_id || !form.department_id || submit.isPending}
              loading={submit.isPending}
            >
              Submit Request
            </Button>
          </>
        }
      >
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Input label="First Name *" value={form.proposed_first_name} onChange={v => set('proposed_first_name', v)} placeholder="First name" />
          <Input label="Last Name *"  value={form.proposed_last_name}  onChange={v => set('proposed_last_name', v)}  placeholder="Last name" />
        </div>
        <Input label="Email Address *" value={form.proposed_email} onChange={v => set('proposed_email', v)} placeholder="candidate@email.com" />
        <Select label="Proposed Role *" value={form.proposed_role_id} onChange={v => set('proposed_role_id', v)} options={toArr(roles).map((r: any) => ({ label: r.name, value: r.id }))} />
        <Select label="Department *"    value={form.department_id}    onChange={v => set('department_id', v)}    options={toArr(depts).map((d: any) => ({ label: d.name, value: d.id }))} />
        <Textarea label="Justification" value={form.justification} onChange={v => set('justification', v)} placeholder="Why is this person needed?" rows={3} />
      </Modal>

      {/* Reject reason modal */}
      <Modal
        open={!!rejectModal}
        onClose={() => setRejectModal(null)}
        title="Reject Onboarding Request"
        footer={
          <>
            <Button variant="secondary" onClick={() => setRejectModal(null)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={() => rejectModal && reject.mutate({ id: rejectModal.id, reason: rejectReason || undefined })}
              disabled={reject.isPending}
              loading={reject.isPending}
            >
              Reject Request
            </Button>
          </>
        }
      >
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 14, lineHeight: 1.5 }}>
          Optionally provide a reason for rejecting this request.
        </p>
        <Textarea label="Reason (optional)" value={rejectReason} onChange={v => setRejectReason(v)} placeholder="Reason for rejection…" rows={3} />
      </Modal>
    </Page>
  );
}
