// ============================================================
// OPSYN SHIFT SCHEDULER — /shifts  (Stage 7 token update)
// Weekly calendar grid: staff rows × day columns
// Click empty → assign; click assigned → cancel/swap
// ============================================================

import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { shiftsApi } from '../../api/index';
import { staffApi } from '../../api/staff.api';
import { useToast } from '../../components/ui/Toast';
import type { ShiftAssignment, Shift } from '@shared';
import type { ApiError } from '../../api/client';
import { GlassModal, GlassSelect } from '../../components/glass';
import { PageHeader } from '../../components/layout/Page';

// ── Design primitives ─────────────────────────────────────────
const card = (extra?: React.CSSProperties): React.CSSProperties => ({
  background: 'var(--surface)', border: '1px solid var(--color-border)',
  borderRadius: 12, padding: 16, ...extra,
});

function Btn({ variant = 'ghost', onClick, children, style, disabled }: any) {
  const bg  = variant === 'brand' ? 'var(--brand)'
            : variant === 'rose'  ? 'rgba(220,38,38,.1)'
            : variant === 'jade'  ? 'rgba(22,163,74,.1)'
            : variant === 'amber' ? 'rgba(245,158,11,.1)'
            : 'rgba(100,116,139,.06)';
  const col = variant === 'brand' ? 'var(--brand-contrast)'
            : variant === 'rose'  ? 'var(--color-red)'
            : variant === 'jade'  ? 'var(--color-green)'
            : variant === 'amber' ? 'var(--color-amber)'
            : 'var(--color-text-primary)';
  return (
    <button disabled={disabled} onClick={onClick} style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '6px 13px', borderRadius: 8, fontSize: 12, fontWeight: 600,
      cursor: disabled ? 'not-allowed' : 'pointer', fontFamily: 'var(--font-body)',
      transition: 'all .15s', whiteSpace: 'nowrap', opacity: disabled ? 0.5 : 1,
      background: bg, color: col, border: variant === 'ghost' ? '1px solid var(--color-border)' : 'none', ...style,
    }}>{children}</button>
  );
}

function Sel({ label, value, onChange, options, id }: any) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label htmlFor={id || label} style={{ display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--color-text-muted)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.1em' }}>{label}</label>
      <GlassSelect value={String(value)} onChange={v => onChange(v)} options={[...options.map((o: any) => ({ value: String(o.value), label: String(o.label) }))]} placeholder={`— ${label} —`} id={id || label} />
    </div>
  );
}

// ── Week navigation helpers ───────────────────────────────────
function getMondayOf(d: Date): Date {
  const day  = d.getDay();
  const diff = (day === 0 ? -6 : 1 - day);
  const mon  = new Date(d);
  mon.setDate(d.getDate() + diff);
  mon.setHours(0, 0, 0, 0);
  return mon;
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

function fmt(d: Date): string { return d.toISOString().slice(0, 10); }

function dayLabel(d: Date): string {
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short' });
}

// ── Main Page ─────────────────────────────────────────────────
export default function ShiftSchedulerPage() {
  const qc    = useQueryClient();
  const toast = useToast();
  const [weekStart, setWeekStart] = useState<Date>(() => getMondayOf(new Date()));
  const [modal, setModal]         = useState<{ type: 'assign' | 'detail'; userId?: string; date?: string; assignment?: ShiftAssignment } | null>(null);
  const [assignShiftId, setAssignShiftId] = useState('');
  const [assignNotes, setAssignNotes]     = useState('');

  const weekKey = fmt(weekStart);

  const { data: weekData, isLoading } = useQuery({
    queryKey: ['shifts', 'weekly', weekKey],
    queryFn:  () => shiftsApi.getWeekly(weekKey),
    refetchInterval: 60000,
  });

  const { data: shiftsData } = useQuery({
    queryKey: ['shifts', 'list'],
    queryFn:  () => shiftsApi.list(),
  });

  const { data: staffData } = useQuery({
    queryKey: ['staff', 'active'],
    queryFn:  () => staffApi.list({ status: 'active', size: 200 }),
  });

  const createAssignment = useMutation({
    mutationFn: (p: { shift_id: string; user_id: string; date: string; notes?: string }) => shiftsApi.createAssignment(p),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['shifts', 'weekly', weekKey] });
      setModal(null); setAssignShiftId(''); setAssignNotes('');
      toast.success('Shift assigned');
    },
    onError: (e: ApiError) => toast.error('Conflict', e?.response?.data?.detail || 'Already assigned'),
  });

  const cancelAssignment = useMutation({
    mutationFn: (id: string) => shiftsApi.updateAssignmentStatus(id, 'cancelled'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['shifts', 'weekly', weekKey] });
      setModal(null);
      toast.info('Assignment cancelled');
    },
  });

  // Memoised: the `?? []` fallback allocated a new array every render,
  // which invalidated the useMemo below it on every pass.
  const assignments: ShiftAssignment[] = useMemo(
    () => (weekData as any)?.assignments ?? [],
    [weekData],
  );
  const shifts: Shift[]                = Array.isArray(shiftsData) ? shiftsData : [];
  const staff: any[]                   = (staffData as any)?.items ?? (Array.isArray(staffData) ? staffData : []);

  const lookup = useMemo(() => {
    const m: Record<string, ShiftAssignment> = {};
    for (const a of assignments) {
      if (a.status !== 'cancelled') m[`${a.user_id}__${a.date}`] = a;
    }
    return m;
  }, [assignments]);

  const weekDays = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));

  const openAssign = (userId: string, date: string) => { setAssignShiftId(''); setAssignNotes(''); setModal({ type: 'assign', userId, date }); };
  const openDetail = (assignment: ShiftAssignment)  => { setModal({ type: 'detail', assignment }); };

  return (
    <div style={{ overflow: 'auto', flex: 1, background: 'var(--color-surface)' }}>

      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px', borderBottom: '1px solid var(--color-border)', background: 'var(--surface)' }}>
        <PageHeader
          title="NOC shift scheduler"
          lede={`Week of ${weekStart.toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' })}`}
          primary={<>
          <Btn onClick={() => setWeekStart(w => addDays(w, -7))}>← Prev</Btn>
          <Btn onClick={() => setWeekStart(getMondayOf(new Date()))}>This Week</Btn>
          <Btn onClick={() => setWeekStart(w => addDays(w, 7))}>Next →</Btn>
          </>}
        />
      </div>

      <div style={{ padding: 20 }}>
        {/* ── Stats bar ── */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          {[
            { label: 'Shifts This Week', val: assignments.filter(a => a.status !== 'cancelled').length, color: 'var(--color-teal)' },
            { label: 'Staff Covered',    val: new Set(assignments.filter(a => a.status !== 'cancelled').map(a => a.user_id)).size, color: 'var(--color-green)' },
            { label: 'Shift Templates',  val: shifts.length, color: 'var(--color-indigo)' },
          ].map(s => (
            <div key={s.label} style={{ ...card({ padding: '10px 16px', flex: 1 }), display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 20, color: s.color }}>{s.val}</span>
              <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{s.label}</span>
            </div>
          ))}
        </div>

        {/* ── Weekly Grid ── */}
        <div style={{ ...card({ padding: 0, overflowX: 'auto' }) }} tabIndex={0} role="region" aria-label="Weekly rota">
          {isLoading ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 12 }}>Loading schedule…</div>
          ) : staff.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 12 }}>No active staff found.</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 700 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', fontSize: 9, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--color-text-muted)', padding: '10px 14px', borderBottom: '1px solid var(--color-border)', minWidth: 140, position: 'sticky', left: 0, background: 'var(--surface)', zIndex: 1 }}>
                    Staff Member
                  </th>
                  {weekDays.map((d, i) => (
                    <th key={i} style={{ textAlign: 'center', fontSize: 9, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', color: fmt(d) === fmt(new Date()) ? 'var(--color-teal)' : 'var(--color-text-muted)', padding: '10px 8px', borderBottom: '1px solid var(--color-border)', minWidth: 100, borderLeft: '1px solid var(--color-border)' }}>
                      {dayLabel(d)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {staff.map((s: any) => {
                  const sp   = s.profile || s;
                  const name = sp.first_name ? `${sp.first_name} ${sp.last_name}` : s.email;
                  return (
                    <tr key={s.id}>
                      <td style={{ padding: '8px 14px', borderBottom: '1px solid var(--color-border)', position: 'sticky', left: 0, background: 'var(--surface)', zIndex: 1 }}>
                        <div style={{ fontWeight: 500, fontSize: 12, color: 'var(--color-text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 130 }}>{name}</div>
                        <div style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>{sp.role_name ?? ''}</div>
                      </td>
                      {weekDays.map((d, di) => {
                        const dateStr    = fmt(d);
                        const assignment = lookup[`${s.id}__${dateStr}`];
                        const isToday    = dateStr === fmt(new Date());
                        return (
                          <td key={di} style={{ padding: 4, borderBottom: '1px solid var(--color-border)', borderLeft: '1px solid var(--color-border)', textAlign: 'center', background: isToday ? 'rgba(0,194,168,.03)' : 'transparent' }}>
                            {assignment ? (
                              <div
                                onClick={() => openDetail(assignment)}
                                style={{
                                  background: (assignment.shift as any)?.color ?? 'rgba(0,194,168,.15)',
                                  border: `1px solid ${(assignment.shift as any)?.color ?? 'var(--color-teal)'}`,
                                  borderRadius: 6, padding: '4px 6px', cursor: 'pointer',
                                  fontSize: 10, fontWeight: 600, color: 'var(--color-text-primary)',
                                  transition: 'opacity .15s',
                                }}>
                                {(assignment.shift as any)?.name ?? '—'}
                                <div style={{ fontSize: 9, fontWeight: 400, color: 'var(--color-text-muted)', marginTop: 1 }}>
                                  {(assignment.shift as any)?.start_time}–{(assignment.shift as any)?.end_time}
                                </div>
                              </div>
                            ) : (
                              <div
                                onClick={() => openAssign(s.id, dateStr)}
                                style={{
                                  height: 46, borderRadius: 6, border: '1px dashed var(--color-border)',
                                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                                  cursor: 'pointer', color: 'var(--color-text-muted)', fontSize: 14,
                                  transition: 'all .15s',
                                }}
                                title="Click to assign shift">
                                +
                              </div>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* ── Shift legend ── */}
        {shifts.length > 0 && (
          <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
            {shifts.map((s: Shift) => (
              <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', borderRadius: 6, border: `1px solid ${s.color}`, fontSize: 11, color: 'var(--color-text-primary)' }}>
                <div style={{ width: 8, height: 8, borderRadius: 2, background: s.color }} />
                {s.name} ({s.start_time}–{s.end_time})
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Assign Modal ── */}
      {modal?.type === 'assign' && (
        <GlassModal open onClose={() => setModal(null)} ariaLabel="Assign shift" size="sm">
            <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--color-text-primary)', marginBottom: 16 }}>Assign Shift</div>
            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 12 }}>
              Date: <span style={{ color: 'var(--color-teal)', fontFamily: 'var(--font-mono)' }}>{modal.date}</span>
            </div>
            <Sel label="Shift Template" value={assignShiftId} onChange={setAssignShiftId}
              options={shifts.map((s: Shift) => ({ label: `${s.name} (${s.start_time}–${s.end_time})`, value: s.id }))}
            />
            <div style={{ marginBottom: 14 }}>
              <label style={{ display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--color-text-muted)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.1em' }}>Notes</label>
              <input value={assignNotes} onChange={e => setAssignNotes(e.target.value)} placeholder="Optional notes…"
                style={{ width: '100%', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 8, padding: '9px 12px', color: 'var(--color-text-primary)', fontFamily: 'var(--font-body)', fontSize: 12, outline: 'none', boxSizing: 'border-box' }} />
            </div>
            {shifts.length === 0 && (
              <div style={{ fontSize: 11, color: 'var(--color-amber)', marginBottom: 12 }}>
                No shift templates defined. Create shift templates in Settings first.
              </div>
            )}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <Btn onClick={() => setModal(null)}>Cancel</Btn>
              <Btn variant="brand"
                disabled={!assignShiftId || createAssignment.isPending}
                onClick={() => createAssignment.mutate({
                  shift_id: assignShiftId,
                  user_id:  modal.userId!,
                  date:     modal.date!,
                  notes:    assignNotes || undefined,
                })}>
                {createAssignment.isPending ? 'Saving…' : 'Assign'}
              </Btn>
            </div>
          </GlassModal>
      )}

      {/* ── Detail Modal ── */}
      {modal?.type === 'detail' && modal.assignment && (
        <GlassModal open onClose={() => setModal(null)} ariaLabel="Shift assignment" size="sm">
            <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--color-text-primary)', marginBottom: 12 }}>Shift Assignment</div>
            {[
              ['Shift',  (modal.assignment.shift as any)?.name ?? '—'],
              ['Date',   modal.assignment.date],
              ['Time',   `${(modal.assignment.shift as any)?.start_time ?? '?'} – ${(modal.assignment.shift as any)?.end_time ?? '?'}`],
              ['Status', modal.assignment.status],
              ['Notes',  modal.assignment.notes ?? '—'],
            ].map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '7px 0', borderBottom: '1px solid var(--color-border)' }}>
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{k}</span>
                <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--color-text-primary)' }}>{v}</span>
              </div>
            ))}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
              <Btn onClick={() => setModal(null)}>Close</Btn>
              {modal.assignment.status !== 'cancelled' && (
                <Btn variant="rose"
                  disabled={cancelAssignment.isPending}
                  onClick={() => cancelAssignment.mutate(modal.assignment!.id)}>
                  {cancelAssignment.isPending ? 'Cancelling…' : 'Cancel Shift'}
                </Btn>
              )}
            </div>
          </GlassModal>
      )}
    </div>
  );
}
