// ============================================================
// OPSYN — AssignmentAnalyticsPage  (F.2.3)
// Workload & completion analytics for managers (roleLevel >= 3).
// Two tables: per-staff and per-department.
// ============================================================

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks.api';
import { useAuthStore } from '../../store/auth.store';
import { PageHeader } from '../../components/layout/Page';

// ── Table helpers ─────────────────────────────────────────────

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th style={{
      padding: '8px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700,
      color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '.06em',
      borderBottom: '1px solid var(--color-border)', background: 'var(--color-surface-2)',
    }}>
      {children}
    </th>
  );
}

function Td({ children, mono }: { children: React.ReactNode; mono?: boolean }) {
  return (
    <td style={{
      padding: '8px 12px', fontSize: 12, color: 'var(--color-text-primary)',
      borderBottom: '1px solid var(--color-border)',
      fontFamily: mono ? 'var(--font-mono)' : 'var(--font)',
    }}>
      {children}
    </td>
  );
}

// ── Date filter bar ───────────────────────────────────────────

function DateFilterBar({
  from, to,
  onFrom, onTo, onClear,
}: {
  from: string; to: string;
  onFrom: (v: string) => void;
  onTo:   (v: string) => void;
  onClear: () => void;
}) {
  const inputStyle: React.CSSProperties = {
    border: '1px solid var(--color-border)', borderRadius: 6,
    padding: '5px 8px', fontSize: 12, fontFamily: 'var(--font)',
    color: 'var(--color-text-primary)', background: 'var(--surface)', outline: 'none',
  };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
      <label style={{ fontSize: 11, color: 'var(--color-text-muted)', fontWeight: 600 }}>From</label>
      <input type="date" aria-label="From date" max={to || undefined} value={from} onChange={e => onFrom(e.target.value)} style={inputStyle} />
      <label style={{ fontSize: 11, color: 'var(--color-text-muted)', fontWeight: 600 }}>To</label>
      <input type="date" aria-label="To date" min={from || undefined} value={to}   onChange={e => onTo(e.target.value)}   style={inputStyle} />
      {(from || to) && (
        <button
          onClick={onClear}
          style={{
            padding: '4px 10px', borderRadius: 6, fontSize: 11, border: 'none',
            background: 'var(--color-surface-2)', color: 'var(--color-text-muted)',
            cursor: 'pointer', fontFamily: 'var(--font)',
          }}
        >
          Clear
        </button>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────

export default function AssignmentAnalyticsPage() {
  const roleLevel = useAuthStore((s: any) => s.roleLevel);
  const [from, setFrom] = useState('');
  const [to,   setTo]   = useState('');

  const params = {
    from_date: from || undefined,
    to_date:   to   || undefined,
  };

  const { data: staffData, isLoading: staffLoading } = useQuery({
    queryKey: ['analytics', 'assignments', from, to],
    queryFn:  () => tasksApi.getAssignmentAnalytics(params),
    enabled:  roleLevel >= 3,
    staleTime: 60 * 1000,
  });

  const { data: deptData, isLoading: deptLoading } = useQuery({
    queryKey: ['analytics', 'departments', from, to],
    queryFn:  () => tasksApi.getDepartmentAnalytics(params),
    enabled:  roleLevel >= 3,
    staleTime: 60 * 1000,
  });

  if (roleLevel < 3) {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', height: '100%', gap: 12,
        color: 'var(--color-text-muted)', fontSize: 13,
      }}>
        <div style={{ fontSize: 40 }}>🔒</div>
        <div style={{ fontWeight: 600 }}>Access Restricted</div>
        <div style={{ fontSize: 12 }}>Analytics is visible to managers and above.</div>
      </div>
    );
  }

  const cardStyle: React.CSSProperties = {
    background: 'var(--surface)', border: '1px solid var(--color-border)',
    borderRadius: 'var(--radius-card)', marginBottom: 28, overflow: 'hidden',
  };

  const tableStyle: React.CSSProperties = { width: '100%', borderCollapse: 'collapse' };

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', flex: 1,
      overflow: 'hidden', background: 'var(--color-surface)',
    }}>
      {/* Header */}
      <div style={{
        padding: '14px 24px', borderBottom: '1px solid var(--color-border)',
        background: 'var(--surface)', flexShrink: 0,
      }}>
        <PageHeader
          title="Assignment analytics"
          lede="Workload and completion metrics for staff and departments"
        />
      </div>

      {/* Body */}
      <div style={{ overflow: 'auto', flex: 1, padding: '20px 24px' }}>
        <DateFilterBar
          from={from} to={to}
          onFrom={setFrom} onTo={setTo}
          onClear={() => { setFrom(''); setTo(''); }}
        />

        {/* ── Staff table ── */}
        <div style={cardStyle}>
          <div style={{
            padding: '12px 16px', borderBottom: '1px solid var(--color-border)',
            fontWeight: 700, fontSize: 13, color: 'var(--color-text-primary)',
          }}>
            Staff Assignment Totals
          </div>
          {staffLoading ? (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 12 }}>
              Loading…
            </div>
          ) : !staffData?.length ? (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 12 }}>
              No data for the selected period.
            </div>
          ) : (
            <table style={tableStyle}>
              <thead>
                <tr>
                  <Th>Name</Th>
                  <Th>Assigned</Th>
                  <Th>Forwarded</Th>
                  <Th>Completed</Th>
                  <Th>Avg Days</Th>
                </tr>
              </thead>
              <tbody>
                {staffData.map(row => (
                  <tr key={row.user_id}>
                    <Td>{row.full_name}</Td>
                    <Td mono>{row.assignments_received}</Td>
                    <Td mono>{row.assignments_forwarded}</Td>
                    <Td mono>{row.tasks_completed}</Td>
                    <Td mono>{row.avg_completion_days}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* ── Department table ── */}
        <div style={cardStyle}>
          <div style={{
            padding: '12px 16px', borderBottom: '1px solid var(--color-border)',
            fontWeight: 700, fontSize: 13, color: 'var(--color-text-primary)',
          }}>
            Department Routing Totals
          </div>
          {deptLoading ? (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 12 }}>
              Loading…
            </div>
          ) : !deptData?.length ? (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 12 }}>
              No data for the selected period.
            </div>
          ) : (
            <table style={tableStyle}>
              <thead>
                <tr>
                  <Th>Department</Th>
                  <Th>Received</Th>
                  <Th>Completed</Th>
                  <Th>Pushed Back</Th>
                  <Th>Avg Days</Th>
                </tr>
              </thead>
              <tbody>
                {deptData.map(row => (
                  <tr key={row.department_id}>
                    <Td>{row.department_name}</Td>
                    <Td mono>{row.tasks_received}</Td>
                    <Td mono>{row.tasks_completed}</Td>
                    <Td mono>{row.tasks_pushed_back}</Td>
                    <Td mono>{row.avg_days_in_dept}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
