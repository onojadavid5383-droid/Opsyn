// ============================================================
// OPSYN NEW TASK MODAL — Phase 5 Workflow Engine
// Step 1: Scope selection (Internal / External)
// Step 2A: Internal task form (dept-scoped assignee)
// Step 2B: External task form (target department)
// Features: @archive reference, live assignee search,
//           success confirmation with project ticket number.
// ============================================================

import { useState, useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Building2, Network } from 'lucide-react';
import { tasksApi, type DeptStaffMember, type ArchiveSearchResult } from '../../../api/tasks.api';
import { orgApi } from '../../../api/index';
import { useUIStore } from '../../../store/ui.store';
import type { ApiError } from '../../../api/client';
import { GlassModal, GlassSelect } from '../../../components/glass';
import styles from './NewTaskModal.module.css';

const INPUT: React.CSSProperties = {
  width: '100%', background: 'var(--bg3)', border: '1px solid var(--wire2)',
  borderRadius: 8, padding: '9px 12px', color: 'var(--chalk)',
  fontFamily: 'var(--font)', fontSize: 12, outline: 'none', boxSizing: 'border-box',
};
const LABEL: React.CSSProperties = {
  display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--chalk3)',
  marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.1em',
};
const BTN = (primary?: boolean): React.CSSProperties => ({
  padding: '8px 20px', borderRadius: 8, border: 'none', cursor: 'pointer',
  fontFamily: 'var(--font)', fontSize: 12, fontWeight: 600,
  background: primary ? 'var(--color-teal)' : 'var(--bg3)',
  color: primary ? '#fff' : 'var(--chalk)',
});

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={LABEL}>{label}</label>
      {children}
    </div>
  );
}

interface Props {
  open:            boolean;
  onClose:         () => void;
  initialScope?:   'internal' | 'external';
}

type Step = 'scope' | 'form';

const EMPTY_INTERNAL = {
  title: '', description: '', deadline: '', priority: 'medium',
  assignee_user_id: '', tagsRaw: '',
};
const EMPTY_EXTERNAL = {
  title: '', description: '', deadline: '', priority: 'medium',
  department_id: '',
};

// ── Archive Search Popover ────────────────────────────────────

function ArchiveSearchPopover({
  onSelect,
  onClose,
}: {
  onSelect: (r: ArchiveSearchResult) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState('');
  const { data: results = [], isLoading } = useQuery({
    queryKey: ['archive-search', q],
    queryFn: () => (q.length >= 2 ? tasksApi.searchArchive(q, 10) : Promise.resolve([])),
    enabled: q.length >= 2,
    staleTime: 30_000,
  });

  return (
    <div style={{
      position: 'absolute', zIndex: 1000, top: '110%', left: 0, right: 0,
      background: 'var(--bg2)', border: '1px solid var(--wire2)',
      borderRadius: 10, padding: 12, boxShadow: '0 8px 24px rgba(0,0,0,.4)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--chalk3)' }}>@ARCHIVE SEARCH</span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--chalk3)', cursor: 'pointer', fontSize: 14 }}>×</button>
      </div>
      <input
        autoFocus
        value={q}
        onChange={e => setQ(e.target.value)}
        placeholder="Search archived tasks & projects..."
        style={{ ...INPUT, marginBottom: 10 }}
      />
      {isLoading && <div style={{ fontSize: 11, color: 'var(--chalk3)', textAlign: 'center' }}>Searching…</div>}
      {!isLoading && q.length >= 2 && results.length === 0 && (
        <div style={{ fontSize: 11, color: 'var(--chalk3)', textAlign: 'center' }}>No archived items match your search.</div>
      )}
      {results.map(r => (
        <div
          key={r.id}
          onClick={() => onSelect(r)}
          style={{
            padding: '8px 10px', borderRadius: 6, cursor: 'pointer', marginBottom: 4,
            background: 'var(--bg3)', display: 'flex', justifyContent: 'space-between',
          }}
          onMouseOver={e => (e.currentTarget.style.background = 'var(--bg4)')}
          onMouseOut={e => (e.currentTarget.style.background = 'var(--bg3)')}
        >
          <div>
            <span style={{ fontSize: 10, color: 'var(--color-teal)', fontWeight: 700 }}>{r.ticket_number}</span>
            <span style={{ fontSize: 11, color: 'var(--chalk)', marginLeft: 8 }}>{r.title}</span>
          </div>
          <span style={{ fontSize: 10, color: 'var(--chalk3)', background: 'var(--bg2)', padding: '2px 6px', borderRadius: 4 }}>
            {r.type}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Main Modal ────────────────────────────────────────────────

/** Every screen of the wizard shares one glass dialog (focus trap, Escape, scrim) */
function Frame({ label, onClose, children, size = 'md' }: { label: string; onClose: () => void; children: React.ReactNode; size?: 'md' | 'lg' }) {
  return (
    <GlassModal open onClose={onClose} ariaLabel={label} size={size}>
      {children}
    </GlassModal>
  );
}

export default function NewTaskModal({ open, onClose, initialScope }: Props) {
  const [step, setStep]       = useState<Step>(initialScope ? 'form' : 'scope');
  const [scope, setScope]     = useState<'internal' | 'external'>(initialScope ?? 'internal');
  const [iForm, setIForm]     = useState({ ...EMPTY_INTERNAL });
  const [eForm, setEForm]     = useState({ ...EMPTY_EXTERNAL });
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [archiveRefs, setArchiveRefs] = useState<ArchiveSearchResult[]>([]);
  const [assigneeSearch, setAssigneeSearch] = useState('');
  const [assigneeOpen, setAssigneeOpen]     = useState(false);
  const [deptSearch, setDeptSearch]         = useState('');
  const [successData, setSuccessData]       = useState<{ ticket?: string; name?: string } | null>(null);
  const qc = useQueryClient();
  const { addToast } = useUIStore();

  // Reset when modal opens
  useEffect(() => {
    if (open) {
      // Reset-on-open. Keyed on `open` deliberately -- depending on the form
      // // values would wipe the user's input as they type.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setStep(initialScope ? 'form' : 'scope');
      setScope(initialScope ?? 'internal');
      setIForm({ ...EMPTY_INTERNAL });
      setEForm({ ...EMPTY_EXTERNAL });
      setArchiveRefs([]);
      setSuccessData(null);
    }
  }, [open, initialScope]);

  // Dept staff for internal assignee search
  const { data: deptStaff = [] } = useQuery<DeptStaffMember[]>({
    queryKey: ['dept-staff', assigneeSearch],
    queryFn: () => tasksApi.getDeptStaff(assigneeSearch || undefined, 50),
    enabled: scope === 'internal' && step === 'form',
    staleTime: 60_000,
  });

  // Departments for external task
  const { data: depts = [] } = useQuery<any[]>({
    queryKey: ['departments'],
    queryFn:  () => orgApi.getDepartments().then((d: any) => (Array.isArray(d) ? d : d?.data ?? [])),
    enabled:  scope === 'external' && step === 'form',
    staleTime: 300_000,
  });

  const createMut = useMutation({
    mutationFn: (payload: any) => tasksApi.create(payload),
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ['tasks'] });
      if (data?.project) {
        setSuccessData({ ticket: data.project.ticket_number, name: data.project.name });
      } else {
        addToast({ type: 'success', title: 'Task created successfully.' });
        onClose();
      }
    },
    onError: (err: ApiError) => {
      addToast({ type: 'error', title: 'Failed to create task', message: err?.response?.data?.detail ?? err.message });
    },
  });

  const handleSubmitInternal = () => {
    if (!iForm.title.trim()) return addToast({ type: 'error', title: 'Task title is required.' });
    if (!iForm.description.trim()) return addToast({ type: 'error', title: 'Description is required.' });
    if (!iForm.deadline) return addToast({ type: 'error', title: 'Deadline is required.' });

    createMut.mutate({
      task_scope: 'internal',
      title: iForm.title,
      description: iForm.description,
      deadline: iForm.deadline,
      priority: iForm.priority,
      assignee_user_id: iForm.assignee_user_id || null,
      tags: iForm.tagsRaw ? iForm.tagsRaw.split(',').map(t => t.trim()).filter(Boolean) : [],
      archive_refs: archiveRefs.filter(r => r.type === 'task').map(r => r.id),
    });
  };

  const handleSubmitExternal = () => {
    if (!eForm.title.trim()) return addToast({ type: 'error', title: 'Task title is required.' });
    if (!eForm.description.trim()) return addToast({ type: 'error', title: 'Description is required.' });
    if (!eForm.deadline) return addToast({ type: 'error', title: 'Deadline is required.' });
    if (!eForm.department_id) return addToast({ type: 'error', title: 'Target department is required.' });

    createMut.mutate({
      task_scope: 'external',
      title: eForm.title,
      description: eForm.description,
      deadline: eForm.deadline,
      priority: eForm.priority,
      department_id: eForm.department_id,
      archive_refs: archiveRefs.filter(r => r.type === 'task').map(r => r.id),
    });
  };

  if (!open) return null;

  // ── Success screen ────────────────────────────────────────
  if (successData) {
    return (
      <Frame onClose={onClose} label="Task created">
          <div style={{ textAlign: 'center', padding: '20px 0' }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>✓</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--chalk)', marginBottom: 8 }}>External Task Created</div>
            <div style={{ fontSize: 13, color: 'var(--chalk3)', marginBottom: 4 }}>
              Project <strong style={{ color: 'var(--color-teal)' }}>{successData.ticket}</strong> automatically generated
            </div>
            <div style={{ fontSize: 12, color: 'var(--chalk3)', marginBottom: 24 }}>
              Assigned to: {successData.name}
            </div>
            <button style={BTN(true)} onClick={onClose}>Done</button>
          </div>
      </Frame>
    );
  }

  // ── Step 1: Scope selection ───────────────────────────────
  if (step === 'scope') {
    return (
      <Frame onClose={onClose} label="Create new task" size="lg">
        <section className={styles.scope}>
          <div className={styles.scopeEyebrow}><span /> TASK SETUP <span className={styles.step}>STEP 01 / 02</span></div>
          <h1 className={styles.scopeTitle}>Where should this work live?</h1>
          <p className={styles.scopeDescription}>Choose how the task will be assigned. You can add the details next.</p>

          <div className={styles.scopeOptions}>
            <button className={styles.scopeOption} type="button" onClick={() => { setScope('internal'); setStep('form'); }}>
              <span className={styles.scopeIcon}><Building2 size={21} strokeWidth={1.7} aria-hidden="true" /></span>
              <span className={styles.scopeCopy}>
                <span className={styles.scopeLabel}>Within my department</span>
                <span className={styles.scopeSubtitle}>Assign to someone on your team.</span>
              </span>
              <ArrowRight className={styles.scopeArrow} size={18} aria-hidden="true" />
            </button>
            <button className={styles.scopeOption} type="button" onClick={() => { setScope('external'); setStep('form'); }}>
              <span className={styles.scopeIcon}><Network size={21} strokeWidth={1.7} aria-hidden="true" /></span>
              <span className={styles.scopeCopy}>
                <span className={styles.scopeLabel}>With another department</span>
                <span className={styles.scopeSubtitle}>Route the work across teams and create a project.</span>
              </span>
              <ArrowRight className={styles.scopeArrow} size={18} aria-hidden="true" />
            </button>
          </div>

          <div className={styles.scopeFooter}>
            <span>Choose a route to continue</span>
            <button className={styles.cancelButton} type="button" onClick={onClose}>Cancel</button>
          </div>
        </section>
      </Frame>
    );
  }

  // ── Step 2A: Internal Task Form ───────────────────────────
  if (scope === 'internal') {
    const selectedAssignee = deptStaff.find(s => s.user_id === iForm.assignee_user_id);
    const filtered = deptStaff.filter(s =>
      !assigneeSearch ||
      s.full_name.toLowerCase().includes(assigneeSearch.toLowerCase()) ||
      s.staff_code.toLowerCase().includes(assigneeSearch.toLowerCase())
    );

    return (
      <Frame onClose={onClose} label="New internal task">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--chalk)' }}>Internal Task</div>
              <div style={{ fontSize: 11, color: 'var(--color-teal)', fontWeight: 600, marginTop: 2 }}>
                INTERNAL — Assign within your department
              </div>
            </div>
            <button onClick={() => setStep('scope')} style={{ background: 'none', border: 'none', color: 'var(--chalk3)', cursor: 'pointer', fontSize: 12 }}>← Back</button>
          </div>

          <Field label="Task Name *">
            <input style={INPUT} value={iForm.title} onChange={e => setIForm(p => ({ ...p, title: e.target.value }))} placeholder="Enter task name (min 3 chars)" />
          </Field>

          <Field label="Description *">
            <textarea
              style={{ ...INPUT, minHeight: 80, resize: 'vertical' }}
              value={iForm.description}
              onChange={e => setIForm(p => ({ ...p, description: e.target.value }))}
              placeholder="Describe the task in detail (min 10 chars)"
            />
          </Field>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Field label="Deadline *">
              <input type="date" style={INPUT} value={iForm.deadline} onChange={e => setIForm(p => ({ ...p, deadline: e.target.value }))} />
            </Field>
            <Field label="Priority">
              <GlassSelect value={String(iForm.priority)} onChange={v => setIForm(p => ({ ...p, priority: v }))} options={[{ value: 'critical', label: 'Critical' }, { value: 'high', label: 'High' }, { value: 'medium', label: 'Medium' }, { value: 'low', label: 'Low' }]} ariaLabel="Priority" />
            </Field>
          </div>

          <Field label="Assignee (Department Staff)">
            <div style={{ position: 'relative' }}>
              <input
                style={INPUT}
                value={selectedAssignee ? `${selectedAssignee.full_name} (${selectedAssignee.staff_code})` : assigneeSearch}
                onChange={e => { setAssigneeSearch(e.target.value); setAssigneeOpen(true); setIForm(p => ({ ...p, assignee_user_id: '' })); }}
                onFocus={() => setAssigneeOpen(true)}
                placeholder="Search by name or staff code..."
              />
              {assigneeOpen && filtered.length > 0 && (
                <div style={{
                  position: 'absolute', zIndex: 100, top: '110%', left: 0, right: 0,
                  background: 'var(--bg2)', border: '1px solid var(--wire2)', borderRadius: 8,
                  boxShadow: '0 4px 16px rgba(0,0,0,.3)', maxHeight: 200, overflowY: 'auto',
                }}>
                  {filtered.map(s => (
                    <div
                      key={s.user_id}
                      onClick={() => {
                        setIForm(p => ({ ...p, assignee_user_id: s.user_id }));
                        setAssigneeSearch('');
                        setAssigneeOpen(false);
                      }}
                      style={{ padding: '8px 12px', cursor: 'pointer', fontSize: 12 }}
                      onMouseOver={e => (e.currentTarget.style.background = 'var(--bg3)')}
                      onMouseOut={e => (e.currentTarget.style.background = '')}
                    >
                      <strong style={{ color: 'var(--chalk)' }}>{s.full_name}</strong>
                      <span style={{ color: 'var(--chalk3)', marginLeft: 8 }}>{s.staff_code}</span>
                      {s.job_title && <span style={{ color: 'var(--chalk3)', marginLeft: 8 }}>· {s.job_title}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Field>

          <Field label="Tags (comma-separated)">
            <input style={INPUT} value={iForm.tagsRaw} onChange={e => setIForm(p => ({ ...p, tagsRaw: e.target.value }))} placeholder="e.g. urgent, network, review" />
          </Field>

          {/* @archive reference */}
          <Field label="@Archive References">
            <div style={{ position: 'relative' }}>
              <button
                type="button"
                onClick={() => setArchiveOpen(v => !v)}
                style={{ ...BTN(), fontSize: 11, marginBottom: 6 }}
              >
                + Add @archive reference
              </button>
              {archiveOpen && (
                <ArchiveSearchPopover
                  onSelect={r => {
                    setArchiveRefs(prev => prev.find(x => x.id === r.id) ? prev : [...prev, r]);
                    setArchiveOpen(false);
                  }}
                  onClose={() => setArchiveOpen(false)}
                />
              )}
              {archiveRefs.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                  {archiveRefs.map(r => (
                    <span key={r.id} style={{
                      background: 'var(--bg3)', border: '1px solid var(--wire2)',
                      borderRadius: 12, padding: '3px 10px', fontSize: 11,
                      display: 'flex', alignItems: 'center', gap: 6,
                    }}>
                      <span style={{ color: 'var(--color-teal)' }}>{r.ticket_number}</span>
                      <button
                        onClick={() => setArchiveRefs(prev => prev.filter(x => x.id !== r.id))}
                        style={{ background: 'none', border: 'none', color: 'var(--chalk3)', cursor: 'pointer', padding: 0 }}
                      >×</button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </Field>

          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
            <button style={BTN()} onClick={onClose}>Cancel</button>
            <button style={BTN(true)} onClick={handleSubmitInternal} disabled={createMut.isPending}>
              {createMut.isPending ? 'Creating…' : 'Create Internal Task'}
            </button>
          </div>
      </Frame>
    );
  }

  // ── Step 2B: External Task Form ───────────────────────────
  const filteredDepts = depts.filter((d: any) =>
    !deptSearch || d.name.toLowerCase().includes(deptSearch.toLowerCase())
  );
  const selectedDept = depts.find((d: any) => d.id === eForm.department_id);

  return (
    <Frame onClose={onClose} label="New external task">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--chalk)' }}>External Task</div>
            <div style={{ fontSize: 11, color: 'var(--color-indigo, #6366f1)', fontWeight: 600, marginTop: 2 }}>
              EXTERNAL — Routes to another department · Creates a project automatically
            </div>
          </div>
          <button onClick={() => setStep('scope')} style={{ background: 'none', border: 'none', color: 'var(--chalk3)', cursor: 'pointer', fontSize: 12 }}>← Back</button>
        </div>

        <Field label="Task Name * (becomes project name)">
          <input style={INPUT} value={eForm.title} onChange={e => setEForm(p => ({ ...p, title: e.target.value }))} placeholder="Enter task name" />
        </Field>

        <Field label="Target Department *">
          <div style={{ position: 'relative' }}>
            <input
              style={INPUT}
              value={selectedDept ? selectedDept.name : deptSearch}
              onChange={e => { setDeptSearch(e.target.value); setEForm(p => ({ ...p, department_id: '' })); }}
              onFocus={() => setAssigneeOpen(true)}
              placeholder="Search department..."
            />
            {assigneeOpen && filteredDepts.length > 0 && (
              <div style={{
                position: 'absolute', zIndex: 100, top: '110%', left: 0, right: 0,
                background: 'var(--bg2)', border: '1px solid var(--wire2)', borderRadius: 8,
                boxShadow: '0 4px 16px rgba(0,0,0,.3)', maxHeight: 200, overflowY: 'auto',
              }}>
                {filteredDepts.map((d: any) => (
                  <div
                    key={d.id}
                    onClick={() => {
                      setEForm(p => ({ ...p, department_id: d.id }));
                      setDeptSearch('');
                      setAssigneeOpen(false);
                    }}
                    style={{ padding: '8px 12px', cursor: 'pointer', fontSize: 12, color: 'var(--chalk)' }}
                    onMouseOver={e => (e.currentTarget.style.background = 'var(--bg3)')}
                    onMouseOut={e => (e.currentTarget.style.background = '')}
                  >
                    {d.name}
                  </div>
                ))}
              </div>
            )}
          </div>
        </Field>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Field label="Deadline * (sets project due date)">
            <input type="date" style={INPUT} value={eForm.deadline} onChange={e => setEForm(p => ({ ...p, deadline: e.target.value }))} />
          </Field>
          <Field label="Priority">
            <GlassSelect value={String(eForm.priority)} onChange={v => setEForm(p => ({ ...p, priority: v }))} options={[{ value: 'critical', label: 'Critical' }, { value: 'high', label: 'High' }, { value: 'medium', label: 'Medium' }, { value: 'low', label: 'Low' }]} ariaLabel="Priority" />
          </Field>
        </div>

        <Field label="Description *">
          <textarea
            style={{ ...INPUT, minHeight: 80, resize: 'vertical' }}
            value={eForm.description}
            onChange={e => setEForm(p => ({ ...p, description: e.target.value }))}
            placeholder="Describe the task/project in detail (min 10 chars)"
          />
        </Field>

        <Field label="@Archive References">
          <div style={{ position: 'relative' }}>
            <button type="button" onClick={() => setArchiveOpen(v => !v)} style={{ ...BTN(), fontSize: 11, marginBottom: 6 }}>
              + Add @archive reference
            </button>
            {archiveOpen && (
              <ArchiveSearchPopover
                onSelect={r => {
                  setArchiveRefs(prev => prev.find(x => x.id === r.id) ? prev : [...prev, r]);
                  setArchiveOpen(false);
                }}
                onClose={() => setArchiveOpen(false)}
              />
            )}
            {archiveRefs.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                {archiveRefs.map(r => (
                  <span key={r.id} style={{ background: 'var(--bg3)', border: '1px solid var(--wire2)', borderRadius: 12, padding: '3px 10px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ color: 'var(--color-teal)' }}>{r.ticket_number}</span>
                    <button onClick={() => setArchiveRefs(prev => prev.filter(x => x.id !== r.id))} style={{ background: 'none', border: 'none', color: 'var(--chalk3)', cursor: 'pointer', padding: 0 }}>×</button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </Field>

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
          <button style={BTN()} onClick={onClose}>Cancel</button>
          <button style={BTN(true)} onClick={handleSubmitExternal} disabled={createMut.isPending}>
            {createMut.isPending ? 'Creating…' : 'Create External Task'}
          </button>
        </div>
    </Frame>
  );
}
