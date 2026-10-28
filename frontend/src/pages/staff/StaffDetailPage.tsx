// ============================================================
// OPSYN — StaffDetailPage  (Stage 6 redesign)
// ============================================================

import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { staffApi } from '../../api/index';
import type { StaffStatus } from '@shared';
import { useUIStore } from '../../store/ui.store';
import { Button, Badge } from '../../components/ui';
import type { ApiError } from '../../api/client';

function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, message?: string) => addToast({ type: 'success', title, message }),
    error:   (title: string, message?: string) => addToast({ type: 'error',   title, message }),
  };
}

const STATUS_VARIANT: Record<string, any> = {
  active:    'resolved',
  on_leave:  'warning',
  inactive:  'critical',
  suspended: 'critical',
};

const STATUS_LABEL: Record<string, string> = {
  active:    'Active',
  on_leave:  'On Leave',
  inactive:  'Inactive',
  suspended: 'Suspended',
};

const SCORE_COLOR = (v: number) =>
  v >= 80 ? 'var(--color-green)' : v >= 60 ? 'var(--color-amber)' : 'var(--color-red)';

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', gap: 12, padding: '9px 0', borderBottom: '1px solid var(--color-border)' }}>
      <span style={{ width: 130, fontSize: 11, color: 'var(--color-text-muted)', flexShrink: 0 }}>{label}</span>
      <span style={{ fontSize: 12, color: 'var(--color-text-primary)', fontWeight: 500, flex: 1 }}>{value ?? '—'}</span>
    </div>
  );
}

function MetricTile({ label, value, unit = '' }: { label: string; value: any; unit?: string }) {
  return (
    <div style={{ padding: '10px 12px', background: 'var(--color-surface)', borderRadius: 8, border: '1px solid var(--color-border)' }}>
      <div style={{ fontSize: 10, color: 'var(--color-text-muted)', fontWeight: 600, marginBottom: 4, letterSpacing: '.04em', textTransform: 'uppercase' }}>{label}</div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 20, fontWeight: 700, color: 'var(--color-text-primary)' }}>
        {value ?? '—'}{unit && <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--color-text-muted)', marginLeft: 2 }}>{unit}</span>}
      </div>
    </div>
  );
}

export default function StaffDetailPage() {
  const toast    = useToast();
  const navigate = useNavigate();
  const qc       = useQueryClient();

  const id = window.location.pathname.split('/').pop() ?? '';

  const { data: staff,  isLoading } = useQuery({ queryKey: ['staff', id],             queryFn: () => staffApi.get(id),              enabled: !!id });
  const { data: perf }              = useQuery({ queryKey: ['staff-perf', id],        queryFn: () => staffApi.getPerformance(id),   enabled: !!id, staleTime: 3600000 });

  const updateStatus = useMutation({
    mutationFn: (status: StaffStatus) => staffApi.updateStatus(id, status),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['staff', id] }); toast.success('Status updated'); },
    onError:   (e: ApiError) => toast.error('Failed', e?.response?.data?.detail ?? e?.message),
  });

  if (isLoading) return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-muted)', fontSize: 12 }}>
      Loading…
    </div>
  );

  if (!staff) return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-muted)', fontSize: 13 }}>
      Staff member not found.
    </div>
  );

  const s           = staff as any;
  const p           = perf  as any;
  const score       = p?.efficiency_score ?? 0;
  const scoreColor  = SCORE_COLOR(score);
  const deg         = Math.round((score / 100) * 360);
  const initials    = `${s.first_name?.[0] ?? ''}${s.last_name?.[0] ?? ''}`.toUpperCase();

  return (
    <div style={{ overflow: 'auto', flex: 1, background: 'var(--color-surface)' }}>
      <div style={{ padding: '20px 24px' }}>

        {/* Back + Header */}
        <div style={{ marginBottom: 20 }}>
          <button
            onClick={() => navigate('/staff')}
            style={{ background: 'none', border: 'none', color: 'var(--color-text-muted)', fontSize: 12, cursor: 'pointer', padding: 0, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 4 }}
          >
            ← Back to Staff
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div style={{
              width: 52, height: 52, borderRadius: 14,
              background: 'var(--brand)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 800, color: 'var(--brand-contrast)',
              flexShrink: 0,
            }}>
              {initials}
            </div>
            <div>
              <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 800, color: 'var(--color-text-primary)', letterSpacing: '-.03em', margin: 0 }}>
                {s.first_name} {s.last_name}
              </h1>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                <Badge variant={STATUS_VARIANT[s.status] ?? 'info'} size="sm">{STATUS_LABEL[s.status] ?? s.status}</Badge>
                {s.job_title && <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{s.job_title}</span>}
              </div>
            </div>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>

          {/* Left: Profile info */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-card)', padding: '16px 18px' }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text-muted)', letterSpacing: '.06em', textTransform: 'uppercase', marginBottom: 4 }}>
              Profile
            </div>
            <InfoRow label="Email"      value={<a href={`mailto:${s.email}`} style={{ color: 'var(--color-teal)' }}>{s.email}</a>} />
            <InfoRow label="Phone"      value={s.phone} />
            <InfoRow label="Department" value={s.department?.name ?? s.department_id} />
            <InfoRow label="Team"       value={s.team?.name ?? s.team_id} />
            <InfoRow label="Region"     value={s.region?.name ?? s.region_id} />
            <InfoRow label="Role"       value={s.role?.name ?? s.role_id} />
            <InfoRow label="Start Date" value={s.start_date ? new Date(s.start_date).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : undefined} />

            {/* Status actions */}
            <div style={{ marginTop: 14, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {s.status !== 'active' && (
                <Button variant="jade" size="xs" onClick={() => updateStatus.mutate('active')} disabled={updateStatus.isPending}>
                  Set Active
                </Button>
              )}
              {s.status !== 'on_leave' && (
                <Button variant="secondary" size="xs" onClick={() => updateStatus.mutate('on_leave')} disabled={updateStatus.isPending}>
                  Set On Leave
                </Button>
              )}
              {s.status !== 'inactive' && (
                <Button variant="danger" size="xs" onClick={() => updateStatus.mutate('inactive')} disabled={updateStatus.isPending}>
                  Deactivate
                </Button>
              )}
            </div>
          </div>

          {/* Right: Operational + Efficiency */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

            {/* Account info */}
            <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-card)', padding: '16px 18px' }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text-muted)', letterSpacing: '.06em', textTransform: 'uppercase', marginBottom: 4 }}>
                Account
              </div>
              <InfoRow label="Staff ID"    value={<span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{s.id?.slice(0, 16)}…</span>} />
              <InfoRow label="Created"     value={s.created_at ? new Date(s.created_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : undefined} />
              <InfoRow label="Last Active" value={s.last_active_at ? new Date(s.last_active_at).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : undefined} />
            </div>

            {/* Efficiency score */}
            {p && (
              <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-card)', padding: '16px 18px' }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text-muted)', letterSpacing: '.06em', textTransform: 'uppercase', marginBottom: 12 }}>
                  Efficiency Score
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 18, marginBottom: 14 }}>
                  {/* Conic-gradient ring */}
                  <div style={{
                    width: 72, height: 72, borderRadius: '50%', flexShrink: 0,
                    background: `conic-gradient(${scoreColor} 0deg ${deg}deg, var(--color-border) ${deg}deg 360deg)`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    position: 'relative',
                  }}>
                    <div style={{
                      width: 54, height: 54, borderRadius: '50%',
                      background: 'var(--surface)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontFamily: 'var(--font-mono)', fontSize: 17, fontWeight: 800,
                      color: scoreColor,
                    }}>
                      {score}
                    </div>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
                    Composite score based on task completion rate, SLA adherence, and average resolution time.
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <MetricTile label="Completion Rate"  value={p.completion_rate  != null ? `${p.completion_rate}` : null}  unit="%" />
                  <MetricTile label="SLA Adherence"    value={p.sla_adherence    != null ? `${p.sla_adherence}` : null}    unit="%" />
                  <MetricTile label="Avg Resolution"   value={p.avg_resolution_hours != null ? `${p.avg_resolution_hours}` : null} unit="h" />
                  <MetricTile label="Open Tasks"       value={p.open_tasks} />
                </div>
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
