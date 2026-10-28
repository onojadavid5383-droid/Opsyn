// ============================================================
// OPSYN FORM BUILDER — admin drag-and-drop schema builder
// Accessed via /settings/forms/:context
// Allows admins to add/edit/delete/reorder fields,
// manage conditional dependencies, and publish the schema.
// ============================================================

import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { formsApi } from '../../api/index';
import type { FormField, FormContext } from '@shared';
import type { ApiError } from '../../api/client';
import { GlassModal, GlassSelect } from '../../components/glass';

// ── Shared primitives ─────────────────────────────────────────

const INPUT_STYLE: React.CSSProperties = {
  width: '100%', background: 'var(--bg3)', border: '1px solid var(--wire2)',
  borderRadius: 8, padding: '8px 10px', color: 'var(--chalk)',
  fontFamily: 'var(--font)', fontSize: 12, outline: 'none',
};

const LABEL_STYLE: React.CSSProperties = {
  display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--chalk3)',
  marginBottom: 4, textTransform: 'uppercase', letterSpacing: '.1em',
};

function Btn({ onClick, children, variant = 'ghost', disabled, style }: any) {
  const bg = variant === 'brand' ? 'var(--brand)' : variant === 'rose' ? 'rgba(248,113,113,.12)' :
             variant === 'jade' ? 'rgba(74,222,128,.1)' : 'rgba(255,255,255,.04)';
  const col = variant === 'brand' ? '#050810' : variant === 'rose' ? 'var(--rose)' :
              variant === 'jade' ? 'var(--green)' : 'var(--chalk2)';
  return (
    <button onClick={onClick} disabled={disabled} type="button"
      style={{ display: 'inline-flex', alignItems: 'center', gap: 5,
               padding: '5px 12px', borderRadius: 8, fontSize: 11, fontWeight: 600,
               cursor: disabled ? 'not-allowed' : 'pointer', fontFamily: 'var(--font)',
               border: variant === 'ghost' ? '1px solid var(--wire2)' : 'none',
               background: bg, color: col, opacity: disabled ? 0.5 : 1,
               transition: 'all .12s', ...style }}>
      {children}
    </button>
  );
}

function Sel({ label, value, onChange, options }: any) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label style={LABEL_STYLE}>{label}</label>
      <GlassSelect value={String(value)} onChange={v => onChange(v)} options={[...options.map((o: any) => ({ value: String(o.value), label: String(o.label) }))]} ariaLabel={label} />
    </div>
  );
}

function Inp({ label, value, onChange, placeholder, type = 'text' }: any) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label style={LABEL_STYLE}>{label}</label>
      <input type={type} value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder} style={INPUT_STYLE} />
    </div>
  );
}

// ── Constants ─────────────────────────────────────────────────

const FIELD_TYPES = [
  { value: 'text',        label: 'Text' },
  { value: 'textarea',    label: 'Textarea' },
  { value: 'number',      label: 'Number' },
  { value: 'dropdown',    label: 'Dropdown' },
  { value: 'date',        label: 'Date' },
  { value: 'phone',       label: 'Phone' },
  { value: 'email',       label: 'Email' },
  { value: 'boolean',     label: 'Boolean (Toggle)' },
  { value: 'file',        label: 'File Upload' },
  { value: 'coordinates', label: 'Coordinates' },
];

const CONTEXTS: FormContext[] = ['lead', 'task', 'project', 'onboarding'];

const OPERATORS = [
  { value: 'eq',          label: 'equals' },
  { value: 'neq',         label: 'not equals' },
  { value: 'gt',          label: 'greater than' },
  { value: 'lt',          label: 'less than' },
  { value: 'contains',    label: 'contains' },
  { value: 'is_empty',    label: 'is empty' },
  { value: 'is_not_empty',label: 'is not empty' },
];

const ACTIONS = [
  { value: 'show',    label: 'Show target field' },
  { value: 'hide',    label: 'Hide target field' },
  { value: 'require', label: 'Make target required' },
];

// ── Field type badge colours ──────────────────────────────────
const TYPE_COLORS: Record<string, string> = {
  text: 'var(--cyan)', textarea: 'var(--cyan)', number: 'var(--amber)',
  dropdown: 'var(--violet)', date: 'var(--green)', phone: 'var(--green)',
  email: 'var(--green)', boolean: 'var(--rose)', file: 'var(--amber)',
  coordinates: 'var(--cyan)',
};

// ── Field add/edit form ───────────────────────────────────────

const BLANK_FIELD = {
  field_key: '', field_type: 'text', label: '', placeholder: '',
  help_text: '', required: false, field_order: 0,
  options_raw: '',  // comma-separated for dropdown
};

type FieldDraft = typeof BLANK_FIELD;

// ── Main page ─────────────────────────────────────────────────

export default function FormBuilderPage() {
  const { context = 'task' } = useParams<{ context: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [activeCtx, setActiveCtx] = useState<string>(context);
  const [addOpen, setAddOpen] = useState(false);
  const [editField, setEditField] = useState<FormField | null>(null);
  const [draft, setDraft] = useState<FieldDraft>({ ...BLANK_FIELD });
  const [draftErr, setDraftErr] = useState('');
  const [depOpen, setDepOpen] = useState(false);
  const [dep, setDep] = useState({ source: '', target: '', operator: 'eq', value: '', action: 'show' });
  const [depErr, setDepErr] = useState('');

  const { data: schema, isLoading, error } = useQuery({
    queryKey: ['form-schema', activeCtx],
    queryFn: () => formsApi.getSchema(activeCtx),
    retry: false,
  });

  const fields  = schema?.fields       ?? [];
  const deps    = schema?.dependencies ?? [];

  // ── Mutations ─────────────────────────────────────────────

  const addField = useMutation({
    mutationFn: () => {
      const opts = draft.field_type === 'dropdown'
        ? draft.options_raw.split(',').map(s => s.trim()).filter(Boolean).map(v => ({ label: v, value: v }))
        : undefined;
      return formsApi.addField(activeCtx, {
        field_key:   draft.field_key.trim().toLowerCase().replace(/\s+/g, '_'),
        field_type:  draft.field_type,
        label:       draft.label.trim(),
        placeholder: draft.placeholder || undefined,
        help_text:   draft.help_text   || undefined,
        required:    draft.required,
        field_order: fields.length,
        options:     opts,
      });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['form-schema', activeCtx] }); setAddOpen(false); setDraft({ ...BLANK_FIELD }); setDraftErr(''); },
    onError: (e: ApiError) => setDraftErr(e?.response?.data?.detail || 'Failed to add field.'),
  });

  const updateField = useMutation({
    mutationFn: () => {
      if (!editField) return Promise.reject();
      const opts = draft.field_type === 'dropdown'
        ? draft.options_raw.split(',').map(s => s.trim()).filter(Boolean).map(v => ({ label: v, value: v }))
        : undefined;
      return formsApi.updateField(activeCtx, editField.id, {
        label:       draft.label.trim(),
        placeholder: draft.placeholder || undefined,
        help_text:   draft.help_text   || undefined,
        required:    draft.required,
        options:     opts,
      });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['form-schema', activeCtx] }); setEditField(null); setDraft({ ...BLANK_FIELD }); setDraftErr(''); },
    onError: (e: ApiError) => setDraftErr(e?.response?.data?.detail || 'Failed to update field.'),
  });

  const deleteField = useMutation({
    mutationFn: (id: string) => formsApi.deleteField(activeCtx, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['form-schema', activeCtx] }),
  });

  const moveField = useMutation({
    mutationFn: ({ id, dir }: { id: string; dir: 'up' | 'down' }) => {
      const sorted = [...fields].sort((a, b) => a.field_order - b.field_order);
      const idx = sorted.findIndex(f => f.id === id);
      if (dir === 'up' && idx === 0) return Promise.resolve(schema!);
      if (dir === 'down' && idx === sorted.length - 1) return Promise.resolve(schema!);
      const newIdx = dir === 'up' ? idx - 1 : idx + 1;
      const order = sorted.map(f => f.id);
      const tmp = order[idx]; order[idx] = order[newIdx]; order[newIdx] = tmp;
      return formsApi.reorderFields(activeCtx, order);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['form-schema', activeCtx] }),
  });

  const publish = useMutation({
    mutationFn: () => formsApi.publishSchema(activeCtx),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['form-schema', activeCtx] }),
  });

  const addDep = useMutation({
    mutationFn: () => formsApi.addDependency(activeCtx, {
      source_field_key:   dep.source,
      target_field_key:   dep.target,
      condition_operator: dep.operator,
      condition_value:    dep.value || undefined,
      action:             dep.action,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['form-schema', activeCtx] }); setDepOpen(false); setDep({ source: '', target: '', operator: 'eq', value: '', action: 'show' }); setDepErr(''); },
    onError: (e: ApiError) => setDepErr(e?.response?.data?.detail || 'Failed to add dependency.'),
  });

  const deleteDep = useMutation({
    mutationFn: (id: string) => formsApi.deleteDependency(activeCtx, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['form-schema', activeCtx] }),
  });

  // ── Helpers ────────────────────────────────────────────────

  const openEdit = (f: FormField) => {
    setEditField(f);
    const optsRaw = Array.isArray(f.options) ? f.options.map((o: any) => o.value ?? o).join(', ') : '';
    setDraft({
      field_key:   f.field_key,
      field_type:  f.field_type,
      label:       f.label,
      placeholder: f.placeholder ?? '',
      help_text:   f.help_text   ?? '',
      required:    f.required,
      field_order: f.field_order,
      options_raw: optsRaw,
    });
    setDraftErr('');
  };

  const validateDraft = () => {
    if (!draft.label.trim())     { setDraftErr('Label is required.'); return false; }
    if (!editField && !draft.field_key.trim()) { setDraftErr('Field key is required.'); return false; }
    if (!editField && !/^[a-z0-9_-]+$/.test(draft.field_key)) { setDraftErr('Field key: lowercase letters, numbers, _ and - only.'); return false; }
    if (draft.field_type === 'dropdown' && !draft.options_raw.trim()) { setDraftErr('Dropdown requires at least one option.'); return false; }
    return true;
  };

  const handleSave = () => {
    setDraftErr('');
    if (!validateDraft()) return;
    if (editField) { updateField.mutate(); } else { addField.mutate(); }
  };

  const isBusy = addField.isPending || updateField.isPending;

  const sorted = [...fields].sort((a, b) => a.field_order - b.field_order);

  // ── Render ────────────────────────────────────────────────

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        padding: '12px 20px', borderBottom: '1px solid var(--wire)',
        background: 'var(--bg2)', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0,
      }}>
        <button type="button" onClick={() => navigate('/settings')} style={{
          background: 'none', border: 'none', color: 'var(--chalk3)', cursor: 'pointer',
          fontSize: 11, fontFamily: 'var(--font)', display: 'flex', alignItems: 'center', gap: 4,
        }}>← Settings</button>
        <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--chalk)' }}>Form Builder</div>
        {schema?.is_published ? (
          <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 5,
                         background: 'rgba(74,222,128,.12)', color: 'var(--green)',
                         boxShadow: 'inset 0 0 0 1px rgba(74,222,128,.3)' }}>
            PUBLISHED v{schema.version}
          </span>
        ) : (
          <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 5,
                         background: 'rgba(251,191,36,.1)', color: 'var(--amber)',
                         boxShadow: 'inset 0 0 0 1px rgba(251,191,36,.25)' }}>
            DRAFT
          </span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          {!schema?.is_published && fields.length > 0 && (
            <Btn variant="jade" onClick={() => publish.mutate()} disabled={publish.isPending}>
              {publish.isPending ? 'Publishing…' : 'Publish Schema'}
            </Btn>
          )}
          <Btn variant="brand" onClick={() => { setAddOpen(true); setEditField(null); setDraft({ ...BLANK_FIELD, field_order: fields.length }); setDraftErr(''); }}>
            + Add Field
          </Btn>
        </div>
      </div>

      {/* Context tabs */}
      <div style={{
        display: 'flex', gap: 2, padding: '8px 20px',
        borderBottom: '1px solid var(--wire)', background: 'var(--bg2)', flexShrink: 0,
      }}>
        {CONTEXTS.map(ctx => (
          <button key={ctx} type="button"
            onClick={() => { setActiveCtx(ctx); navigate(`/settings/forms/${ctx}`, { replace: true }); }}
            style={{
              padding: '5px 14px', borderRadius: 8, fontSize: 11, fontWeight: 600,
              cursor: 'pointer', border: 'none', fontFamily: 'var(--font)',
              background: activeCtx === ctx ? 'rgba(6,182,212,.15)' : 'transparent',
              color: activeCtx === ctx ? 'var(--cyan)' : 'var(--chalk3)',
              boxShadow: activeCtx === ctx ? 'inset 0 0 0 1px rgba(6,182,212,.3)' : 'none',
            }}>
            {ctx.charAt(0).toUpperCase() + ctx.slice(1)}
          </button>
        ))}
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflow: 'auto', padding: 20, display: 'flex', gap: 20 }}>

        {/* Fields panel */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 12, color: 'var(--chalk2)', marginBottom: 12, letterSpacing: '.05em' }}>
            FIELDS ({sorted.length})
          </div>

          {isLoading && (
            <div style={{ color: 'var(--chalk3)', fontSize: 12 }}>Loading schema…</div>
          )}
          {!isLoading && error && (
            <div style={{ padding: 12, borderRadius: 8, background: 'rgba(248,113,113,.08)',
                          border: '1px solid rgba(248,113,113,.2)', fontSize: 12, color: 'var(--rose)' }}>
              Schema not found for context "{activeCtx}". It may need to be seeded.
            </div>
          )}
          {!isLoading && !error && sorted.length === 0 && (
            <div style={{ padding: 20, borderRadius: 8, border: '1px dashed var(--wire2)',
                          color: 'var(--chalk3)', fontSize: 12, textAlign: 'center' }}>
              No fields yet. Click "+ Add Field" to get started.
            </div>
          )}

          {sorted.map((f, idx) => (
            <div key={f.id} style={{
              padding: '10px 14px', borderRadius: 8, background: 'var(--bg2)',
              border: '1px solid var(--wire)', marginBottom: 8,
              display: 'flex', alignItems: 'center', gap: 10,
            }}>
              {/* Reorder buttons */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2, flexShrink: 0 }}>
                <button type="button" disabled={idx === 0 || moveField.isPending}
                  onClick={() => moveField.mutate({ id: f.id, dir: 'up' })}
                  style={{ width: 18, height: 18, border: 'none', borderRadius: 4,
                           background: 'var(--bg3)', color: 'var(--chalk3)',
                           cursor: idx === 0 ? 'not-allowed' : 'pointer', fontSize: 9,
                           display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  ▲
                </button>
                <button type="button" disabled={idx === sorted.length - 1 || moveField.isPending}
                  onClick={() => moveField.mutate({ id: f.id, dir: 'down' })}
                  style={{ width: 18, height: 18, border: 'none', borderRadius: 4,
                           background: 'var(--bg3)', color: 'var(--chalk3)',
                           cursor: idx === sorted.length - 1 ? 'not-allowed' : 'pointer', fontSize: 9,
                           display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  ▼
                </button>
              </div>

              {/* Type badge */}
              <span style={{
                fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 4,
                background: `${TYPE_COLORS[f.field_type] ?? 'var(--chalk3)'}18`,
                color: TYPE_COLORS[f.field_type] ?? 'var(--chalk3)',
                boxShadow: `inset 0 0 0 1px ${TYPE_COLORS[f.field_type] ?? 'var(--chalk3)'}40`,
                fontFamily: 'var(--mono)', flexShrink: 0,
              }}>
                {f.field_type.toUpperCase()}
              </span>

              {/* Label + key */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--chalk)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {f.label}
                  {f.required && <span style={{ color: 'var(--rose)', marginLeft: 3 }}>*</span>}
                </div>
                <div style={{ fontSize: 10, color: 'var(--chalk3)', fontFamily: 'var(--mono)' }}>
                  {f.field_key}
                </div>
              </div>

              {/* Actions */}
              <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                <Btn onClick={() => openEdit(f)}>Edit</Btn>
                <Btn variant="rose" onClick={() => deleteField.mutate(f.id)} disabled={deleteField.isPending}>×</Btn>
              </div>
            </div>
          ))}
        </div>

        {/* Dependencies panel */}
        <div style={{ width: 320, flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={{ fontWeight: 700, fontSize: 12, color: 'var(--chalk2)', letterSpacing: '.05em' }}>
              DEPENDENCIES ({deps.length})
            </div>
            {fields.length >= 2 && (
              <Btn onClick={() => { setDepOpen(true); setDep({ source: '', target: '', operator: 'eq', value: '', action: 'show' }); setDepErr(''); }}>
                + Add
              </Btn>
            )}
          </div>

          {deps.length === 0 ? (
            <div style={{ padding: 14, borderRadius: 8, border: '1px dashed var(--wire2)',
                          color: 'var(--chalk3)', fontSize: 11, textAlign: 'center' }}>
              No conditional rules yet.
            </div>
          ) : (
            deps.map(d => (
              <div key={d.id} style={{
                padding: '8px 12px', borderRadius: 8, background: 'var(--bg2)',
                border: '1px solid var(--wire)', marginBottom: 6, fontSize: 10,
              }}>
                <div style={{ color: 'var(--chalk2)', marginBottom: 3 }}>
                  <span style={{ fontFamily: 'var(--mono)', color: 'var(--cyan)' }}>{d.source_field_key}</span>
                  {' '}<span style={{ color: 'var(--chalk3)' }}>{d.condition_operator}</span>
                  {d.condition_value && <span style={{ fontFamily: 'var(--mono)', color: 'var(--amber)' }}> "{d.condition_value}"</span>}
                </div>
                <div style={{ color: 'var(--chalk3)' }}>
                  → <span style={{ color: d.action === 'hide' ? 'var(--rose)' : d.action === 'require' ? 'var(--amber)' : 'var(--green)' }}>{d.action}</span>
                  {' '}<span style={{ fontFamily: 'var(--mono)', color: 'var(--cyan)' }}>{d.target_field_key}</span>
                </div>
                <button type="button" onClick={() => deleteDep.mutate(d.id)}
                  style={{ marginTop: 4, fontSize: 9, color: 'var(--rose)', background: 'none',
                           border: 'none', cursor: 'pointer', fontFamily: 'var(--font)', padding: 0 }}>
                  Remove
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* ── Field add/edit drawer ── */}
      {(addOpen || editField) && (
        <GlassModal open onClose={() => { setAddOpen(false); setEditField(null); }} ariaLabel="Field editor" size="sm">
            <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--chalk)', marginBottom: 16 }}>
              {editField ? 'Edit Field' : 'Add Field'}
            </div>

            {!editField && (
              <Inp label="Field Key *" value={draft.field_key}
                onChange={(v: string) => setDraft(d => ({ ...d, field_key: v.toLowerCase().replace(/[^a-z0-9_-]/g, '_') }))}
                placeholder="e.g. customer_name" />
            )}

            {!editField && (
              <Sel label="Field Type *" value={draft.field_type}
                onChange={(v: string) => setDraft(d => ({ ...d, field_type: v }))}
                options={FIELD_TYPES} />
            )}
            {editField && (
              <div style={{ marginBottom: 12, padding: '6px 10px', borderRadius: 6,
                            background: 'var(--bg3)', fontSize: 11, color: 'var(--chalk3)' }}>
                Type: <span style={{ color: TYPE_COLORS[editField.field_type] ?? 'var(--chalk2)', fontWeight: 600 }}>
                  {editField.field_type}
                </span>
              </div>
            )}

            <Inp label="Label *" value={draft.label} onChange={(v: string) => setDraft(d => ({ ...d, label: v }))} placeholder="Displayed label" />
            <Inp label="Placeholder" value={draft.placeholder} onChange={(v: string) => setDraft(d => ({ ...d, placeholder: v }))} placeholder="Input hint…" />
            <Inp label="Help Text" value={draft.help_text} onChange={(v: string) => setDraft(d => ({ ...d, help_text: v }))} placeholder="Extra guidance for users" />

            {(draft.field_type === 'dropdown' || editField?.field_type === 'dropdown') && (
              <Inp label="Options (comma-separated)" value={draft.options_raw}
                onChange={(v: string) => setDraft(d => ({ ...d, options_raw: v }))}
                placeholder="Option A, Option B, Option C" />
            )}

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--chalk2)', flex: 1 }}>Required field</div>
              <div onClick={() => setDraft(d => ({ ...d, required: !d.required }))}
                style={{
                  width: 34, height: 18, borderRadius: 9,
                  background: draft.required ? 'var(--green)' : 'var(--wire)',
                  position: 'relative', cursor: 'pointer', transition: 'background .2s',
                }}>
                <div style={{
                  width: 12, height: 12, borderRadius: '50%', background: 'var(--surface)',
                  position: 'absolute', top: 3,
                  left: draft.required ? 19 : 3, transition: 'left .2s',
                }} />
              </div>
            </div>

            {draftErr && (
              <div style={{ marginBottom: 10, fontSize: 11, color: 'var(--rose)', padding: '6px 10px',
                            borderRadius: 6, background: 'rgba(248,113,113,.08)' }}>
                {draftErr}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <Btn onClick={() => { setAddOpen(false); setEditField(null); setDraftErr(''); }}>Cancel</Btn>
              <Btn variant="brand" onClick={handleSave} disabled={isBusy}>
                {isBusy ? 'Saving…' : editField ? 'Save Changes' : 'Add Field'}
              </Btn>
            </div>
          </GlassModal>
      )}

      {/* ── Dependency add drawer ── */}
      {depOpen && (
        <GlassModal open onClose={() => setDepOpen(false)} ariaLabel="Add dependency" size="sm">
            <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--chalk)', marginBottom: 16 }}>
              Add Conditional Rule
            </div>
            <Sel label="Source Field" value={dep.source}
              onChange={(v: string) => setDep(d => ({ ...d, source: v }))}
              options={[{ value: '', label: 'Select field…' }, ...fields.map(f => ({ value: f.field_key, label: f.label }))]} />
            <Sel label="Operator" value={dep.operator}
              onChange={(v: string) => setDep(d => ({ ...d, operator: v }))}
              options={OPERATORS} />
            {!['is_empty', 'is_not_empty'].includes(dep.operator) && (
              <Inp label="Value" value={dep.value} onChange={(v: string) => setDep(d => ({ ...d, value: v }))} placeholder="Compare against…" />
            )}
            <Sel label="Target Field" value={dep.target}
              onChange={(v: string) => setDep(d => ({ ...d, target: v }))}
              options={[{ value: '', label: 'Select field…' }, ...fields.map(f => ({ value: f.field_key, label: f.label }))]} />
            <Sel label="Action" value={dep.action}
              onChange={(v: string) => setDep(d => ({ ...d, action: v }))}
              options={ACTIONS} />

            {depErr && (
              <div style={{ marginBottom: 10, fontSize: 11, color: 'var(--rose)', padding: '6px 10px',
                            borderRadius: 6, background: 'rgba(248,113,113,.08)' }}>
                {depErr}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <Btn onClick={() => setDepOpen(false)}>Cancel</Btn>
              <Btn variant="brand" onClick={() => { setDepErr(''); addDep.mutate(); }} disabled={addDep.isPending || !dep.source || !dep.target}>
                {addDep.isPending ? 'Adding…' : 'Add Rule'}
              </Btn>
            </div>
          </GlassModal>
      )}
    </div>
  );
}
