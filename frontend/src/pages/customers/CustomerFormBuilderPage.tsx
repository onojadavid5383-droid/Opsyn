// ============================================================
// OPSYN CUSTOMER FORM BUILDER — src/pages/customers/CustomerFormBuilderPage.tsx
// Admin UI: create/publish field schemas, manage field definitions
// ============================================================

import { useState } from 'react';
import {
  useFormSchemas, useFormSchema, useFieldDefs,
  useCreateFieldDef, useUpdateFieldDef, useDeleteFieldDef,
  usePublishFormSchema,
} from '../../hooks/useCustomers';
import { customersApi } from '../../api/customers.api';
import { useUIStore } from '../../store/ui.store';
import { useQueryClient } from '@tanstack/react-query';
import { GlassModal, GlassSelect } from '../../components/glass';

function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, msg?: string) => addToast({ type: 'success', title, message: msg }),
    error:   (title: string, msg?: string) => addToast({ type: 'error',   title, message: msg }),
  };
}

// ── Constants ─────────────────────────────────────────────────

const FIELD_TYPES = ['text', 'email', 'number', 'date', 'textarea', 'select'];

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '7px 10px', borderRadius: 7, boxSizing: 'border-box',
  border: '1px solid var(--color-border)', background: 'var(--color-surface)',
  color: 'var(--color-text-primary)', fontFamily: 'var(--font-body)', fontSize: 12, outline: 'none',
};

const labelStyle: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--color-text-muted)',
  textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 4, display: 'block',
};

// ── Field Definition Form ─────────────────────────────────────

interface FieldFormState {
  label:        string;
  key:          string;
  fieldType:    string;
  isRequired:   boolean;
  stageOrder:   number;
  isRequiredToAdvance: boolean;
  optionsList:  string;
  minValue:     string;
  maxValue:     string;
  pattern:      string;
}

const BLANK_FIELD: FieldFormState = {
  label: '', key: '', fieldType: 'text', isRequired: false,
  stageOrder: 1, isRequiredToAdvance: false,
  optionsList: '', minValue: '', maxValue: '', pattern: '',
};

function autoKey(label: string): string {
  return label.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
}

function buildPayload(f: FieldFormState) {
  const validationRules: Record<string, any> = {};
  if (f.fieldType === 'select' && f.optionsList.trim()) {
    validationRules.options_list = f.optionsList.split('\n').map(s => s.trim()).filter(Boolean);
  }
  if (f.minValue.trim()) validationRules.min_value = Number(f.minValue);
  if (f.maxValue.trim()) validationRules.max_value = Number(f.maxValue);
  if (f.pattern.trim())  validationRules.pattern   = f.pattern.trim();

  return {
    label:                  f.label,
    key:                    f.key,
    field_type:             f.fieldType,
    is_required:            f.isRequired,
    stage_order:            f.stageOrder,
    is_required_to_advance: f.isRequiredToAdvance,
    validation_rules:       Object.keys(validationRules).length ? validationRules : undefined,
  };
}

function FieldForm({
  initial, onSave, onCancel, isPending,
}: {
  initial:   FieldFormState;
  onSave:    (payload: any) => void;
  onCancel:  () => void;
  isPending: boolean;
}) {
  const [f, setF] = useState<FieldFormState>(initial);
  const set = (k: keyof FieldFormState, v: any) => setF(p => ({ ...p, [k]: v }));

  return (
    <form onSubmit={e => { e.preventDefault(); onSave(buildPayload(f)); }}
      style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label style={labelStyle}>Label *</label>
          <input style={inputStyle} value={f.label} required
            onChange={e => { set('label', e.target.value); if (!f.key) set('key', autoKey(e.target.value)); }} />
        </div>
        <div>
          <label style={labelStyle}>Key *</label>
          <input style={inputStyle} value={f.key} required
            onChange={e => set('key', autoKey(e.target.value))} />
        </div>
        <div>
          <label style={labelStyle}>Field Type</label>
          <GlassSelect value={String(f.fieldType)} onChange={v => set('fieldType', v)} options={[...FIELD_TYPES.map((t) => ({ value: String(t), label: String(t) }))]} ariaLabel="Field type" />
        </div>
        <div>
          <label style={labelStyle}>Stage Order (1–5)</label>
          <input style={inputStyle} type="number" min={1} max={5} value={f.stageOrder}
            onChange={e => set('stageOrder', Number(e.target.value))} />
        </div>
      </div>

      {f.fieldType === 'select' && (
        <div>
          <label style={labelStyle}>Options (one per line)</label>
          <textarea style={{ ...inputStyle, resize: 'vertical' }} rows={3}
            value={f.optionsList} onChange={e => set('optionsList', e.target.value)}
            placeholder="Option A&#10;Option B&#10;Option C" />
        </div>
      )}

      {(f.fieldType === 'number') && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div>
            <label style={labelStyle}>Min Value</label>
            <input style={inputStyle} type="number" value={f.minValue}
              onChange={e => set('minValue', e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>Max Value</label>
            <input style={inputStyle} type="number" value={f.maxValue}
              onChange={e => set('maxValue', e.target.value)} />
          </div>
        </div>
      )}

      {(f.fieldType === 'text' || f.fieldType === 'email') && (
        <div>
          <label style={labelStyle}>Regex Pattern (optional)</label>
          <input style={inputStyle} value={f.pattern} onChange={e => set('pattern', e.target.value)}
            placeholder="e.g. ^[A-Z]{2}\d{6}$" />
        </div>
      )}

      <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12, cursor: 'pointer' }}>
          <input type="checkbox" checked={f.isRequired} onChange={e => set('isRequired', e.target.checked)} />
          Required field
        </label>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12, cursor: 'pointer' }}>
          <input type="checkbox" checked={f.isRequiredToAdvance}
            onChange={e => set('isRequiredToAdvance', e.target.checked)} />
          Required to advance stage
        </label>
      </div>

      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
        <button type="button" onClick={onCancel}
          style={{ padding: '7px 14px', borderRadius: 7, fontSize: 12, fontWeight: 600,
            border: '1px solid var(--color-border)', background: 'transparent',
            color: 'var(--color-text-muted)', cursor: 'pointer', fontFamily: 'var(--font-body)' }}>
          Cancel
        </button>
        <button type="submit" disabled={isPending}
          style={{ padding: '7px 14px', borderRadius: 7, fontSize: 12, fontWeight: 700,
            border: 'none', background: '#0ea5e9', color: 'white', cursor: 'pointer',
            fontFamily: 'var(--font-body)', opacity: isPending ? 0.6 : 1 }}>
          {isPending ? 'Saving…' : 'Save Field'}
        </button>
      </div>
    </form>
  );
}

// ── Schema Panel (right side) ─────────────────────────────────

function SchemaPanel({ schemaId }: { schemaId: string }) {
  const toast = useToast();
  const { data: schemaData }  = useFormSchema(schemaId);
  const { data: fieldsData, isLoading } = useFieldDefs(schemaId);
  const createField  = useCreateFieldDef(schemaId);
  const updateField  = useUpdateFieldDef(schemaId);
  const deleteField  = useDeleteFieldDef(schemaId);
  const publishMut   = usePublishFormSchema();

  const schema = (schemaData as any)?.data ?? (schemaData as any);
  const fields: any[] = (fieldsData as any)?.data ?? (Array.isArray(fieldsData) ? fieldsData : []);

  const [addingField,  setAddingField]  = useState(false);
  const [editingField, setEditingField] = useState<any | null>(null);

  const handleCreate = async (payload: any) => {
    try {
      await createField.mutateAsync(payload);
      toast.success('Field created');
      setAddingField(false);
    } catch (e: any) {
      toast.error('Failed to create field', String(e?.response?.data?.detail ?? e));
    }
  };

  const handleUpdate = async (payload: any) => {
    try {
      await updateField.mutateAsync({ fieldId: editingField.id, payload });
      toast.success('Field updated');
      setEditingField(null);
    } catch (e: any) {
      toast.error('Failed to update field', String(e?.response?.data?.detail ?? e));
    }
  };

  const handleDelete = async (fieldId: string) => {
    if (!confirm('Delete this field definition?')) return;
    try {
      await deleteField.mutateAsync(fieldId);
      toast.success('Field deleted');
    } catch (e: any) {
      toast.error('Failed to delete field', String(e?.response?.data?.detail ?? e));
    }
  };

  const handlePublish = async () => {
    if (!confirm('Publish this schema? It will become the active pipeline schema for its department.')) return;
    try {
      await publishMut.mutateAsync(schemaId);
      toast.success('Schema published');
    } catch (e: any) {
      toast.error('Failed to publish', String(e?.response?.data?.detail ?? e));
    }
  };

  const fieldToFormState = (f: any): FieldFormState => ({
    label:        f.label ?? '',
    key:          f.key   ?? '',
    fieldType:    f.fieldType ?? f.field_type ?? 'text',
    isRequired:   f.isRequired ?? f.is_required ?? false,
    stageOrder:   f.stageOrder ?? f.stage_order ?? 1,
    isRequiredToAdvance: f.isRequiredToAdvance ?? f.is_required_to_advance ?? false,
    optionsList:  (f.validationRules?.options_list ?? f.validation_rules?.options_list ?? []).join('\n'),
    minValue:     String(f.validationRules?.min_value ?? f.validation_rules?.min_value ?? ''),
    maxValue:     String(f.validationRules?.max_value ?? f.validation_rules?.max_value ?? ''),
    pattern:      f.validationRules?.pattern ?? f.validation_rules?.pattern ?? '',
  });

  const byStage = fields.reduce<Record<number, any[]>>((acc, f) => {
    const s = f.stageOrder ?? f.stage_order ?? 1;
    (acc[s] = acc[s] ?? []).push(f);
    return acc;
  }, {});

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
      {/* Schema header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--color-text-primary)' }}>
            {schema?.name ?? 'Schema'}
          </div>
          {schema?.description && (
            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 2 }}>
              {schema.description}
            </div>
          )}
          <div style={{ marginTop: 6, display: 'flex', gap: 8, alignItems: 'center' }}>
            {schema?.isActive && (
              <span style={{ padding: '2px 8px', borderRadius: 5, fontSize: 10, fontWeight: 700,
                background: '#16a34a18', color: '#16a34a' }}>PUBLISHED</span>
            )}
            {schema?.departmentId && (
              <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                Dept: {schema.departmentId}
              </span>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {!schema?.isActive && (
            <button onClick={handlePublish} disabled={publishMut.isPending}
              style={{ padding: '7px 14px', borderRadius: 7, fontSize: 12, fontWeight: 700,
                border: 'none', background: '#16a34a', color: 'white', cursor: 'pointer',
                fontFamily: 'var(--font-body)', opacity: publishMut.isPending ? 0.6 : 1 }}>
              {publishMut.isPending ? 'Publishing…' : 'Publish Schema'}
            </button>
          )}
          <button onClick={() => { setEditingField(null); setAddingField(true); }}
            style={{ padding: '7px 14px', borderRadius: 7, fontSize: 12, fontWeight: 700,
              border: 'none', background: '#0ea5e9', color: 'white', cursor: 'pointer',
              fontFamily: 'var(--font-body)' }}>
            + Add Field
          </button>
        </div>
      </div>

      {/* Add field form */}
      {addingField && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 12,
          padding: 20, marginBottom: 20 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary)', marginBottom: 16 }}>
            New Field Definition
          </div>
          <FieldForm initial={BLANK_FIELD} onSave={handleCreate} onCancel={() => setAddingField(false)}
            isPending={createField.isPending} />
        </div>
      )}

      {/* Fields by stage */}
      {isLoading ? (
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Loading fields…</div>
      ) : fields.length === 0 && !addingField ? (
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)', padding: '20px 0' }}>
          No field definitions yet. Click "+ Add Field" to start.
        </div>
      ) : (
        [1, 2, 3, 4, 5].map(stage => {
          const stageFields = byStage[stage] ?? [];
          if (stageFields.length === 0) return null;
          return (
            <div key={stage} style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--color-text-muted)',
                textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 8,
                display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ background: '#0ea5e9', color: 'white', borderRadius: '50%',
                  width: 20, height: 20, display: 'inline-flex', alignItems: 'center',
                  justifyContent: 'center', fontSize: 11, fontWeight: 700 }}>{stage}</span>
                Stage {stage}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {stageFields.map((f: any) => (
                  <div key={f.id}>
                    {editingField?.id === f.id ? (
                      <div style={{ background: 'var(--surface)', border: '1px solid #0ea5e9',
                        borderRadius: 10, padding: 16 }}>
                        <FieldForm initial={fieldToFormState(f)} onSave={handleUpdate}
                          onCancel={() => setEditingField(null)}
                          isPending={updateField.isPending} />
                      </div>
                    ) : (
                      <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)',
                        borderRadius: 10, padding: '12px 14px',
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span style={{ padding: '2px 7px', borderRadius: 4, fontSize: 10, fontWeight: 700,
                            background: 'rgba(14,165,233,.1)', color: '#0ea5e9' }}>
                            {f.fieldType ?? f.field_type}
                          </span>
                          <div>
                            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-primary)' }}>
                              {f.label}
                            </div>
                            <div style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>
                              key: <code style={{ fontFamily: 'monospace' }}>{f.key}</code>
                              {(f.isRequired ?? f.is_required) && (
                                <span style={{ marginLeft: 6, color: '#dc2626' }}>required</span>
                              )}
                              {(f.isRequiredToAdvance ?? f.is_required_to_advance) && (
                                <span style={{ marginLeft: 6, color: '#f59e0b' }}>advance-gate</span>
                              )}
                            </div>
                          </div>
                        </div>
                        <div style={{ display: 'flex', gap: 6 }}>
                          <button onClick={() => { setAddingField(false); setEditingField(f); }}
                            style={{ padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600,
                              border: '1px solid var(--color-border)', background: 'transparent',
                              color: 'var(--color-text-muted)', cursor: 'pointer', fontFamily: 'var(--font-body)' }}>
                            Edit
                          </button>
                          <button onClick={() => handleDelete(f.id)}
                            style={{ padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600,
                              border: '1px solid #dc262630', background: 'transparent',
                              color: '#dc2626', cursor: 'pointer', fontFamily: 'var(--font-body)' }}>
                            Delete
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}

// ── Schema List (left sidebar) ────────────────────────────────

function autoContext(title: string): string {
  return title.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '').slice(0, 48);
}

function CreateSchemaModal({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const qc    = useQueryClient();
  const [title,   setTitle]   = useState('');
  const [context, setContext] = useState('');
  const [desc,    setDesc]    = useState('');
  const [busy,    setBusy]    = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const ctx = context.trim() || autoContext(title);
      await customersApi.createFormSchema({ title, context: ctx, description: desc || undefined });
      qc.invalidateQueries({ queryKey: ['customer-form-schemas'] });
      toast.success('Schema created');
      onClose();
    } catch (e: any) {
      toast.error('Failed', String(e?.response?.data?.detail ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <GlassModal open onClose={onClose} ariaLabel="Create form schema" size="sm">
        <div style={{ fontSize: 14, fontWeight: 800, color: 'var(--color-text-primary)', marginBottom: 20 }}>
          New Field Schema
        </div>
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label style={labelStyle}>Title *</label>
            <input style={inputStyle} value={title} required
              onChange={e => { setTitle(e.target.value); if (!context) setContext(autoContext(e.target.value)); }}
              placeholder="e.g. ISP Onboarding Fields" />
          </div>
          <div>
            <label style={labelStyle}>Context Key *</label>
            <input style={inputStyle} value={context} required
              onChange={e => setContext(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
              placeholder="e.g. isp_onboarding" />
            <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 3 }}>
              Machine-readable identifier — auto-filled from title
            </div>
          </div>
          <div>
            <label style={labelStyle}>Description</label>
            <textarea style={{ ...inputStyle, resize: 'vertical' }} rows={2} value={desc}
              onChange={e => setDesc(e.target.value)} />
          </div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
            <button type="button" onClick={onClose}
              style={{ padding: '7px 14px', borderRadius: 7, fontSize: 12, fontWeight: 600,
                border: '1px solid var(--color-border)', background: 'transparent',
                color: 'var(--color-text-muted)', cursor: 'pointer', fontFamily: 'var(--font-body)' }}>
              Cancel
            </button>
            <button type="submit" disabled={busy}
              style={{ padding: '7px 16px', borderRadius: 7, fontSize: 12, fontWeight: 700,
                border: 'none', background: '#0ea5e9', color: 'white', cursor: 'pointer',
                fontFamily: 'var(--font-body)', opacity: busy ? 0.6 : 1 }}>
              {busy ? 'Creating…' : 'Create'}
            </button>
          </div>
        </form>
      </GlassModal>
  );
}

// ── Main Page ─────────────────────────────────────────────────

export default function CustomerFormBuilderPage() {
  const { data: schemasData, isLoading } = useFormSchemas();
  const schemas: any[] = (schemasData as any)?.data ?? (Array.isArray(schemasData) ? schemasData : []);

  const [selectedId,    setSelectedId]    = useState<string | null>(null);
  const [showCreateModal, setShowCreate]  = useState(false);

  const selected = schemas.find((s: any) => s.id === selectedId);

  return (
    <div style={{ display: 'flex', flex: 1, overflow: 'hidden', background: 'var(--color-surface)' }}>
      <h1 className="sr-only">Customer forms</h1>
      {showCreateModal && <CreateSchemaModal onClose={() => setShowCreate(false)} />}

      {/* Left: schema list */}
      <div style={{ width: 240, borderRight: '1px solid var(--color-border)', display: 'flex',
        flexDirection: 'column', overflow: 'hidden', background: 'var(--surface)' }}>
        <div style={{ padding: '16px 14px 12px', display: 'flex', justifyContent: 'space-between',
          alignItems: 'center', borderBottom: '1px solid var(--color-border)' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-text-muted)',
            textTransform: 'uppercase', letterSpacing: '.08em' }}>
            Field Schemas
          </div>
          <button onClick={() => setShowCreate(true)}
            style={{ width: 24, height: 24, borderRadius: 6, fontSize: 16, fontWeight: 700,
              border: 'none', background: '#0ea5e918', color: '#0ea5e9', cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}>
            +
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
          {isLoading ? (
            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', padding: '12px 14px' }}>
              Loading…
            </div>
          ) : schemas.length === 0 ? (
            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', padding: '12px 14px' }}>
              No schemas yet.
            </div>
          ) : (
            schemas.map((s: any) => (
              <button key={s.id} onClick={() => setSelectedId(s.id)}
                style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%',
                  padding: '9px 14px', border: 'none', background: selectedId === s.id
                    ? 'rgba(14,165,233,.08)' : 'transparent',
                  borderLeft: selectedId === s.id ? '3px solid #0ea5e9' : '3px solid transparent',
                  cursor: 'pointer', textAlign: 'left', fontFamily: 'var(--font-body)',
                  transition: 'background .12s' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-primary)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.name}
                  </div>
                  {s.isActive && (
                    <div style={{ fontSize: 10, color: '#16a34a', fontWeight: 600, marginTop: 1 }}>
                      Published
                    </div>
                  )}
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Right: schema detail / field editor */}
      {selectedId && selected ? (
        <SchemaPanel schemaId={selectedId} />
      ) : (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexDirection: 'column', gap: 10, color: 'var(--color-text-muted)' }}>
          <div style={{ fontSize: 32 }}>📋</div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-primary)' }}>
            Select a schema to manage its fields
          </div>
          <div style={{ fontSize: 12 }}>
            Or create a new schema with the <strong>+</strong> button above.
          </div>
        </div>
      )}
    </div>
  );
}
