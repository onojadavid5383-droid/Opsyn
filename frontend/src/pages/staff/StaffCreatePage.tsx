// ============================================================
// OPSYN — StaffCreatePage  (Stage 6 redesign)
// ============================================================

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import { staffApi, orgApi, rolesApi } from '../../api/index';
import type { CreateStaffRequest, StaffStatus } from '@shared';
import { useUIStore } from '../../store/ui.store';
import { Button, Input, Select } from '../../components/ui';
import type { ApiError } from '../../api/client';
import { ArrowLeft } from 'lucide-react';
import { PageHeader } from '../../components/layout/Page';

const toArr = (d: any): any[] => Array.isArray(d) ? d : (d?.items ?? []);

function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, message?: string) => addToast({ type: 'success', title, message }),
    error:   (title: string, message?: string) => addToast({ type: 'error',   title, message }),
  };
}

const STEPS = ['Basic Info', 'Organisation', 'Access Control', 'Operational', 'Review'];

export default function StaffCreatePage() {
  const toast    = useToast();
  const navigate = useNavigate();

  const [step, setStep] = useState(0);
  // Typed to the request contract: the fields below are unions on
  // CreateStaffRequest, and inferring them as plain `string` is what made
  // the argument mismatches on this page invisible.
  const [form, setForm] = useState<{
    first_name: string; last_name: string; email: string; phone: string;
    department_id: string; team_id: string; region_id: string;
    role_id: string; password: string;
    start_date: string; job_title: string; status: StaffStatus;
    invite_method: 'email' | 'password';
    scope_level: CreateStaffRequest['scope_level'];
    employment_type: 'permanent' | 'contract' | 'intern';
    approval_authority_level: number;
    allowed_dashboards: string[];
  }>({
    first_name: '', last_name: '', email: '', phone: '',
    department_id: '', team_id: '', region_id: '',
    role_id: '', invite_method: 'email', password: '',
    start_date: '', job_title: '',
    status: 'active',
    // Required access fields with safe defaults to prevent 422
    scope_level: 'department',
    approval_authority_level: 0,
    allowed_dashboards: [],
    employment_type: 'permanent',
  });

  const { data: depts }   = useQuery({ queryKey: ['departments'], queryFn: () => orgApi.getDepartments() });
  const { data: teams }   = useQuery({
    queryKey: ['teams', form.department_id],
    queryFn:  () => orgApi.getTeams(form.department_id),
    enabled:  !!form.department_id,
  });
  const { data: regions } = useQuery({ queryKey: ['regions'], queryFn: () => orgApi.getRegions() });
  const { data: roles }   = useQuery({
    queryKey: ['roles-assignable'],
    queryFn:  () => rolesApi.getRoles(true),
  });

  const create = useMutation({
    mutationFn: () => staffApi.create({
      ...form,
      // Coerce types to match backend schema expectations
      approval_authority_level: parseInt(String(form.approval_authority_level ?? 0), 10) || 0,
      allowed_dashboards: Array.isArray(form.allowed_dashboards) ? form.allowed_dashboards : [],
      scope_level: form.scope_level || 'department',
      employment_type: form.employment_type || 'permanent',
      username: form.email.split('@')[0],
      temporary_password: form.invite_method === 'password' ? form.password : undefined,
      joined_at: form.start_date || undefined,
      // Convert empty-string optional UUID fields to undefined so they are omitted from JSON
      team_id:          form.team_id          || undefined,
      region_id:        form.region_id        || undefined,
      phone:            form.phone            || undefined,
      job_title:        form.job_title        || undefined,
    }),
    onSuccess: () => { toast.success('Staff created', `${form.first_name} ${form.last_name} has been added`); navigate('/staff'); },
    onError: (e: ApiError) => {
      const detail = e?.response?.data?.detail;
      let msg: string;
      if (Array.isArray(detail)) {
        // Pydantic 422 validation errors — extract the first human-readable message
        msg = detail.map((d: any) => {
          const field = Array.isArray(d.loc) ? d.loc.slice(1).join('.') : '';
          return field ? `${field}: ${d.msg}` : d.msg;
        }).join(' · ');
      } else {
        msg = (typeof detail === 'string' ? detail : null) ?? e?.detail ?? e?.message ?? 'Unknown error';
      }
      toast.error('Failed to create staff', msg);
    },
  });

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }));

  const canNext = [
    !!(form.first_name && form.last_name && form.email),
    !!(form.department_id),
    !!(form.role_id && (form.invite_method === 'email' || form.password)),
    true,
  ];

  const deptList   = toArr(depts);
  const teamList   = toArr(teams);
  const regionList = toArr(regions);
  const roleList   = toArr(roles);

  return (
    <div style={{ overflow: 'auto', flex: 1, background: 'var(--color-surface)' }}>
      <div style={{ padding: '20px 24px', maxWidth: 640, margin: '0 auto' }}>

        {/* Header */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 20 }}>
          <div>
          <Button variant="ghost" size="sm" leftIcon={<ArrowLeft size={16} aria-hidden="true" />} onClick={() => navigate('/staff')}>
            Staff
          </Button>
          </div>
          <PageHeader title="Add staff member" lede="Create a profile, place them in the organisation and choose how they get access" />
        </div>

        {/* Step indicators */}
        <div style={{ display: 'flex', gap: 0, marginBottom: 28, background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-card)', overflow: 'hidden' }}>
          {STEPS.map((s, i) => {
            const active = i === step;
            const done   = i < step;
            return (
              <div
                key={s}
                style={{
                  flex: 1, padding: '10px 4px', textAlign: 'center',
                  fontSize: 10, fontWeight: 600,
                  color: active ? 'var(--color-teal)' : done ? 'var(--color-green)' : 'var(--color-text-muted)',
                  background: active ? 'rgba(0,194,168,.06)' : 'transparent',
                  borderBottom: active ? '2px solid var(--color-teal)' : done ? '2px solid var(--color-green)' : '2px solid transparent',
                  letterSpacing: '.04em',
                  textTransform: 'uppercase',
                  transition: 'all .15s',
                  cursor: done ? 'pointer' : 'default',
                }}
                onClick={() => { if (done) setStep(i); }}
              >
                {done ? '✓ ' : ''}{s}
              </div>
            );
          })}
        </div>

        {/* Step content */}
        <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-card)', padding: '20px 24px', marginBottom: 16 }}>

          {step === 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 4 }}>Basic Information</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Input label="First Name *" value={form.first_name} onChange={v => set('first_name', v)} placeholder="First name" />
                <Input label="Last Name *"  value={form.last_name}  onChange={v => set('last_name', v)}  placeholder="Last name" />
              </div>
              <Input label="Email Address *" value={form.email} onChange={v => set('email', v)} placeholder="email@company.com" />
              <Input label="Phone"           value={form.phone} onChange={v => set('phone', v)} placeholder="+44 20 1234 5678" />
              <Input label="Job Title"       value={form.job_title} onChange={v => set('job_title', v)} placeholder="e.g. Senior Engineer" />
            </div>
          )}

          {step === 1 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 4 }}>Organisation</div>
              <Select
                label="Department *"
                value={form.department_id}
                onChange={v => { set('department_id', v); set('team_id', ''); }}
                options={deptList.map((d: any) => ({ label: d.name, value: d.id }))}
              />
              {form.department_id && (
                <Select
                  label="Team"
                  value={form.team_id}
                  onChange={v => set('team_id', v)}
                  options={teamList.map((t: any) => ({ label: t.name, value: t.id }))}
                />
              )}
              <Select
                label="Region"
                value={form.region_id}
                onChange={v => set('region_id', v)}
                options={regionList.map((r: any) => ({ label: r.name, value: r.id }))}
              />
              <Input label="Start Date" value={form.start_date} onChange={v => set('start_date', v)} placeholder="YYYY-MM-DD" />
            </div>
          )}

          {step === 2 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 4 }}>Access Control</div>
              <Select
                label="Role *"
                value={form.role_id}
                onChange={v => set('role_id', v)}
                options={roleList.map((r: any) => ({ label: r.name, value: r.id }))}
              />
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text-muted)', marginBottom: 8, letterSpacing: '.04em', textTransform: 'uppercase' }}>
                  Invite Method
                </div>
                <div style={{ display: 'flex', gap: 10 }}>
                  {['email', 'password'].map(method => (
                    <label key={method} style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 12, color: 'var(--color-text-primary)' }}>
                      <input
                        type="radio"
                        name="invite_method"
                        value={method}
                        checked={form.invite_method === method}
                        onChange={() => set('invite_method', method)}
                        style={{ accentColor: 'var(--color-teal)' }}
                      />
                      {method === 'email' ? 'Send email invite' : 'Set password'}
                    </label>
                  ))}
                </div>
              </div>
              {form.invite_method === 'password' && (
                <Input label="Password *" type="password" value={form.password} onChange={v => set('password', v)} placeholder="Minimum 8 characters" />
              )}
            </div>
          )}

          {step === 3 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 4 }}>Operational Details</div>
              <Select
                label="Initial Status"
                value={form.status}
                onChange={v => set('status', v)}
                options={[
                  { label: 'Active',    value: 'active' },
                  { label: 'On Leave',  value: 'on_leave' },
                  { label: 'Inactive',  value: 'inactive' },
                ]}
              />
              <div style={{
                marginTop: 8, padding: '14px 16px',
                background: 'rgba(0,194,168,.04)',
                border: '1px solid rgba(0,194,168,.2)',
                borderRadius: 10,
              }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-teal)', marginBottom: 4 }}>Ready to create</div>
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
                  Confirm all details before creating the staff member. They will receive a welcome notification via the selected invite method.
                </div>
              </div>
            </div>
          )}

          {step === 4 && (
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 16 }}>Review & Confirm</div>
              {[
                ['Name',       `${form.first_name} ${form.last_name}`],
                ['Email',      form.email],
                ['Phone',      form.phone || '—'],
                ['Job Title',  form.job_title || '—'],
                ['Department', deptList.find((d: any) => d.id === form.department_id)?.name || '—'],
                ['Team',       teamList.find((t: any) => t.id === form.team_id)?.name   || '—'],
                ['Region',     regionList.find((r: any) => r.id === form.region_id)?.name || '—'],
                ['Role',       roleList.find((r: any) => r.id === form.role_id)?.name   || '—'],
                ['Invite',     form.invite_method],
                ['Start Date', form.start_date || '—'],
                ['Status',     form.status],
              ].map(([label, value]) => (
                <div key={label} style={{ display: 'flex', gap: 12, padding: '7px 0', borderBottom: '1px solid var(--color-border)' }}>
                  <span style={{ width: 110, fontSize: 11, color: 'var(--color-text-muted)', flexShrink: 0 }}>{label}</span>
                  <span style={{ fontSize: 12, color: 'var(--color-text-primary)', fontWeight: 500 }}>{value}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Navigation */}
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <Button variant="secondary" onClick={() => step === 0 ? navigate('/staff') : setStep(s => s - 1)}>
            {step === 0 ? 'Cancel' : '← Back'}
          </Button>
          {step < 4 ? (
            <Button variant="primary" onClick={() => setStep(s => s + 1)} disabled={!canNext[step]}>
              Next →
            </Button>
          ) : (
            <Button variant="primary" onClick={() => create.mutate()} disabled={create.isPending} loading={create.isPending}>
              Create Staff Member
            </Button>
          )}
        </div>

      </div>
    </div>
  );
}
