// ============================================================
// OPSYN — Form Renderer (Phase 7)
// src/components/form-builder/FormRenderer.tsx
//
// Reusable component that renders any published FormSchema
// for user input and handles the full submission lifecycle:
//   draft save → validate → submit
//
// Designed to be embedded in any module (customer detail,
// project pipeline, infrastructure, etc.) via Phase 8.
// ============================================================

import { useState, useCallback, useEffect, useRef } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  formBuilderApi,
  type FieldDefinition,
  type FormSubmission,
  type ValidationError,
  type ValidationWarning,
} from '../../api/form-builder.api';
import { GlassSelect } from '../../components/glass';
import { useAuthStore } from '../../store/auth.store';

// ── Types ─────────────────────────────────────────────────────

export interface FormRendererProps {
  schemaId:             string;
  entityType:           string;
  entityId?:            string;
  associationId?:       string;
  pipelineStageOrder?:  number;
  /** Pre-populate fields (e.g. editing a saved draft) */
  initialData?:         Record<string, unknown>;
  /** If provided, render in read-only view mode */
  viewSubmission?:      FormSubmission;
  onSubmitSuccess?:     (sub: FormSubmission) => void;
  onDraftSaved?:        (sub: FormSubmission) => void;
  onCancel?:            () => void;
}

// ── Width → CSS ───────────────────────────────────────────────

const WIDTH_CSS: Record<string, string> = {
  full:       '100%',
  half:       'calc(50% - 6px)',
  third:      'calc(33.33% - 8px)',
  two_thirds: 'calc(66.67% - 4px)',
  quarter:    'calc(25% - 9px)',
};

// ── Shared field input styles ─────────────────────────────────

const baseInput: React.CSSProperties = {
  width:        '100%',
  boxSizing:    'border-box',
  padding:      '8px 11px',
  borderRadius: 6,
  border:       '1px solid var(--color-border)',
  background:   'rgba(255,255,255,0.06)',
  color:        'var(--chalk1)',
  fontFamily:   'var(--font-display)',
  fontSize:     13,
  outline:      'none',
  transition:   'border-color 120ms',
};

const errorInput: React.CSSProperties = {
  ...baseInput,
  border: '1px solid rgba(255,80,80,0.60)',
};

// ── Conditional logic evaluator ───────────────────────────────

type Condition = { field_key?: string; field?: string; operator: string; value?: unknown };
type ConditionalLogic = { conditions?: Condition[]; action?: string; match?: 'all' | 'any' } | null;

function evalCondition(cond: Condition, vals: Record<string, unknown>): boolean {
  const fv  = vals[cond.field_key ?? cond.field ?? ''];
  const cv  = cond.value;
  switch (cond.operator) {
    case 'eq': case 'equals': return String(fv) === String(cv);
    case 'neq': case 'not_equals': return String(fv) !== String(cv);
    case 'gt': case 'greater_than': return Number(fv) > Number(cv);
    case 'lt': case 'less_than': return Number(fv) < Number(cv);
    case 'gte':           return Number(fv) >= Number(cv);
    case 'lte':           return Number(fv) <= Number(cv);
    case 'contains':    return Array.isArray(fv) ? fv.map(String).includes(String(cv)) : String(fv ?? '').includes(String(cv));
    case 'not_contains':return Array.isArray(fv) ? !fv.map(String).includes(String(cv)) : !String(fv ?? '').includes(String(cv));
    case 'is_empty':    return fv == null || fv === '' || (Array.isArray(fv) && fv.length === 0) || (typeof fv === 'object' && Object.keys(fv as object).length === 0);
    case 'is_not_empty':return fv != null && fv !== '' && !(Array.isArray(fv) && fv.length === 0) && !(typeof fv === 'object' && Object.keys(fv as object).length === 0);
    case 'in':          return Array.isArray(cv) && cv.includes(fv);
    case 'not_in':      return Array.isArray(cv) && !cv.includes(fv);
    default:            return true;
  }
}

function isFieldVisible(field: FieldDefinition, vals: Record<string, unknown>): boolean {
  if (field.is_hidden) return false;
  const logic = field.conditional_logic as ConditionalLogic;
  if (!logic?.conditions?.length) return true;
  const allMet = conditionsMatch(logic, vals);
  if (logic.action === 'show') return allMet;
  if (logic.action === 'hide') return !allMet;
  return true;  // 'require' / 'disable' — field is still shown
}

function isFieldDisabled(field: FieldDefinition, vals: Record<string, unknown>): boolean {
  const logic = field.conditional_logic as ConditionalLogic;
  if (!logic?.conditions?.length) return false;
  const allMet = conditionsMatch(logic, vals);
  return logic.action === 'disable' && allMet;
}

// TODO: conditional "require" logic is implemented but not yet wired into the
// renderer -- no caller applies it. Remove this helper or hook it up.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function isFieldRequired(field: FieldDefinition, vals: Record<string, unknown>): boolean {
  if (field.is_required) return true;
  const logic = field.conditional_logic as ConditionalLogic;
  if (!logic?.conditions?.length) return false;
  const allMet = conditionsMatch(logic, vals);
  return logic.action === 'require' && allMet;
}

function conditionsMatch(logic: NonNullable<ConditionalLogic>, vals: Record<string, unknown>): boolean {
  const results = (logic.conditions ?? []).map(c => evalCondition(c, vals));
  return logic.match === 'any' ? results.some(Boolean) : results.every(Boolean);
}

// ── Per-field input renderers ─────────────────────────────────

function RatingInput({
  value, onChange, disabled, max = 5,
}: {
  value:    unknown;
  onChange: (v: number) => void;
  disabled?: boolean;
  max?:     number;
}) {
  const current = Number(value) || 0;
  return (
    <div style={{ display: 'flex', gap: 4 }}>
      {Array.from({ length: max }, (_, i) => i + 1).map(star => (
        <button
          key={star}
          type="button"
          disabled={disabled}
          onClick={() => !disabled && onChange(star)}
          style={{
            background: 'none', border: 'none',
            cursor: disabled ? 'default' : 'pointer',
            fontSize: 22, padding: '0 1px',
            color: star <= current ? '#ffb400' : 'rgba(255,255,255,0.20)',
            transition: 'color 100ms',
          }}
        >
          ★
        </button>
      ))}
      {current > 0 && !disabled && (
        <button
          type="button"
          onClick={() => onChange(0)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            fontSize: 11, color: 'rgba(255,255,255,0.35)',
            fontFamily: 'var(--font-display)',
            alignSelf: 'center', padding: '0 4px',
          }}
        >
          clear
        </button>
      )}
    </div>
  );
}

function CoordinatesInput({
  value, onChange, disabled, style,
}: {
  value:     unknown;
  onChange:  (v: string) => void;
  disabled?: boolean;
  style?:    React.CSSProperties;
}) {
  const str = String(value ?? '');
  const parts = str.split(',');
  const lat = parts[0]?.trim() ?? '';
  const lon = parts[1]?.trim() ?? '';

  const update = (newLat: string, newLon: string) =>
    onChange(newLat || newLon ? `${newLat}, ${newLon}` : '');

  return (
    <div style={{ display: 'flex', gap: 8 }}>
      <input
        style={{ ...style, flex: 1 }}
        type="number"
        step="any"
        placeholder="Latitude"
        value={lat}
        disabled={disabled}
        onChange={e => update(e.target.value, lon)}
      />
      <input
        style={{ ...style, flex: 1 }}
        type="number"
        step="any"
        placeholder="Longitude"
        value={lon}
        disabled={disabled}
        onChange={e => update(lat, e.target.value)}
      />
    </div>
  );
}

function MultiSelectInput({
  options, value, onChange, disabled,
}: {
  options:   string[];
  value:     unknown;
  onChange:  (v: string[]) => void;
  disabled?: boolean;
  style?:    React.CSSProperties;
}) {
  const selected = Array.isArray(value) ? (value as string[]) : [];
  const toggle = (opt: string) => {
    if (disabled) return;
    const next = selected.includes(opt)
      ? selected.filter(s => s !== opt)
      : [...selected, opt];
    onChange(next);
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {options.map(opt => (
        <label
          key={opt}
          style={{
            display: 'flex', alignItems: 'center', gap: 8,
            cursor: disabled ? 'default' : 'pointer',
            fontFamily: 'var(--font-display)', fontSize: 13,
            color: 'var(--chalk2)',
          }}
        >
          <input
            type="checkbox"
            checked={selected.includes(opt)}
            onChange={() => toggle(opt)}
            disabled={disabled}
            style={{ accentColor: 'var(--color-teal)', width: 14, height: 14 }}
          />
          {opt}
        </label>
      ))}
      {options.length === 0 && (
        <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.30)', fontFamily: 'var(--font-display)' }}>
          No options configured
        </span>
      )}
    </div>
  );
}

function RadioInput({
  options, value, onChange, disabled,
}: {
  options:   string[];
  value:     unknown;
  onChange:  (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {options.map(opt => (
        <label
          key={opt}
          style={{
            display: 'flex', alignItems: 'center', gap: 8,
            cursor: disabled ? 'default' : 'pointer',
            fontFamily: 'var(--font-display)', fontSize: 13,
            color: 'var(--chalk2)',
          }}
        >
          <input
            type="radio"
            checked={value === opt}
            onChange={() => !disabled && onChange(opt)}
            disabled={disabled}
            style={{ accentColor: 'var(--color-teal)', width: 14, height: 14 }}
          />
          {opt}
        </label>
      ))}
    </div>
  );
}

// ── Single field renderer ─────────────────────────────────────

function FieldInput({
  field, value, onChange, error, disabled,
}: {
  field:     FieldDefinition;
  value:     unknown;
  onChange:  (v: unknown) => void;
  error?:    string;
  disabled?: boolean;
}) {
  const s     = error ? errorInput : baseInput;
  const opts  = field.options ?? [];
  const rules = (field.validation_rules ?? {}) as Record<string, unknown>;

  switch (field.field_type) {
    case 'string':
      return (
        <input
          style={s} type="text"
          value={String(value ?? '')}
          placeholder={field.placeholder ?? ''}
          maxLength={rules.max_length ? Number(rules.max_length) : undefined}
          disabled={disabled}
          onChange={e => onChange(e.target.value)}
        />
      );

    case 'text':
      return (
        <textarea
          style={{ ...s, minHeight: 80, resize: 'vertical' as const }}
          value={String(value ?? '')}
          placeholder={field.placeholder ?? ''}
          maxLength={rules.max_length ? Number(rules.max_length) : undefined}
          disabled={disabled}
          onChange={e => onChange(e.target.value)}
        />
      );

    case 'integer':
      return (
        <input
          style={s} type="number" step="1"
          value={value == null ? '' : String(value)}
          placeholder={field.placeholder ?? ''}
          min={rules.min_value != null ? Number(rules.min_value) : undefined}
          max={rules.max_value != null ? Number(rules.max_value) : undefined}
          disabled={disabled}
          onChange={e => onChange(e.target.value === '' ? null : parseInt(e.target.value, 10))}
        />
      );

    case 'float':
    case 'currency':
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {field.field_type === 'currency' && (
            <span style={{
              fontSize: 13, color: 'rgba(255,255,255,0.50)',
              fontFamily: 'var(--font-display)',
            }}>
              $
            </span>
          )}
          <input
            style={{ ...s, flex: 1 }} type="number"
            step={rules.decimal_places ? `0.${'0'.repeat(Number(rules.decimal_places) - 1)}1` : 'any'}
            value={value == null ? '' : String(value)}
            placeholder={field.placeholder ?? ''}
            min={rules.min_value != null ? Number(rules.min_value) : undefined}
            max={rules.max_value != null ? Number(rules.max_value) : undefined}
            disabled={disabled}
            onChange={e => onChange(e.target.value === '' ? null : parseFloat(e.target.value))}
          />
        </div>
      );

    case 'boolean':
      return (
        <label style={{
          display: 'flex', alignItems: 'center', gap: 10,
          cursor: disabled ? 'default' : 'pointer',
          fontFamily: 'var(--font-display)', fontSize: 13, color: 'var(--chalk2)',
        }}>
          <div
            onClick={() => !disabled && onChange(!value)}
            style={{
              width: 36, height: 20, borderRadius: 10,
              background: value ? 'var(--color-teal)' : 'rgba(255,255,255,0.15)',
              position: 'relative', transition: 'background 150ms', flexShrink: 0,
              cursor: disabled ? 'default' : 'pointer',
            }}
          >
            <div style={{
              position: 'absolute', top: 3,
              left: value ? 18 : 3,
              width: 14, height: 14, borderRadius: 7,
              background: 'var(--surface)', transition: 'left 150ms',
            }} />
          </div>
          {value ? 'Yes' : 'No'}
        </label>
      );

    case 'date':
      return (
        <input
          style={s} type="date"
          value={String(value ?? '')}
          min={rules.min_date ? String(rules.min_date) : undefined}
          max={rules.max_date ? String(rules.max_date) : undefined}
          disabled={disabled}
          onChange={e => onChange(e.target.value || null)}
        />
      );

    case 'datetime':
      return (
        <input
          style={s} type="datetime-local"
          value={String(value ?? '')}
          disabled={disabled}
          onChange={e => onChange(e.target.value || null)}
        />
      );

    case 'time':
      return (
        <input
          style={s} type="time"
          value={String(value ?? '')}
          disabled={disabled}
          onChange={e => onChange(e.target.value || null)}
        />
      );

    case 'email':
      return (
        <input
          style={s} type="email"
          value={String(value ?? '')}
          placeholder={field.placeholder ?? 'user@example.com'}
          disabled={disabled}
          onChange={e => onChange(e.target.value)}
        />
      );

    case 'phone':
      return (
        <input
          style={s} type="tel"
          value={String(value ?? '')}
          placeholder={field.placeholder ?? '+1 555 000 0000'}
          disabled={disabled}
          onChange={e => onChange(e.target.value)}
        />
      );

    case 'url':
      return (
        <input
          style={s} type="url"
          value={String(value ?? '')}
          placeholder={field.placeholder ?? 'https://'}
          disabled={disabled}
          onChange={e => onChange(e.target.value)}
        />
      );

    case 'enum':
      return (
        <GlassSelect value={String(value ?? '')} onChange={v => onChange(v || null)} options={[...opts.map((o) => ({ value: String(o), label: String(o) }))]} placeholder={String(field.placeholder ?? '— Select —')} disabled={disabled} ariaLabel={field.label} />
      );

    case 'multiselect':
      return (
        <MultiSelectInput
          options={opts} value={value} onChange={onChange} disabled={disabled} style={s}
        />
      );

    case 'radio':
      return (
        <RadioInput options={opts} value={value} onChange={onChange} disabled={disabled} />
      );

    case 'rating':
      return (
        <RatingInput
          value={value}
          onChange={onChange}
          disabled={disabled}
          max={rules.max_rating ? Number(rules.max_rating) : 5}
        />
      );

    case 'coordinates':
      return (
        <CoordinatesInput value={value} onChange={onChange} disabled={disabled} style={s} />
      );

    case 'address':
      return (
        <textarea
          style={{ ...s, minHeight: 72, resize: 'vertical' as const }}
          value={String(value ?? '')}
          placeholder={field.placeholder ?? 'Street, City, Country'}
          disabled={disabled}
          onChange={e => onChange(e.target.value)}
        />
      );

    case 'file':
    case 'image':
      return (
        <div>
          <input
            style={s} type="file"
            accept={field.field_type === 'image' ? 'image/*' : undefined}
            disabled={disabled}
            onChange={e => onChange(e.target.files?.[0]?.name ?? null)}
          />
          <div style={{
            fontSize: 10, color: 'rgba(255,255,255,0.30)',
            fontFamily: 'var(--font-display)', marginTop: 4,
          }}>
            File upload integration available in Phase 8
          </div>
        </div>
      );

    case 'signature':
      return (
        <textarea
          style={{ ...s, minHeight: 60, fontFamily: 'cursive', fontSize: 16 }}
          value={String(value ?? '')}
          placeholder="Type your signature"
          disabled={disabled}
          onChange={e => onChange(e.target.value)}
        />
      );

    case 'lookup':
      return (
        <input
          style={s} type="text"
          value={String(value ?? '')}
          placeholder={field.placeholder ?? 'Search…'}
          disabled={disabled}
          onChange={e => onChange(e.target.value)}
        />
      );

    case 'computed':
      return (
        <input
          style={{ ...s, opacity: 0.6, cursor: 'not-allowed' }}
          type="text"
          value={String(value ?? '(computed)')}
          readOnly
        />
      );

    default:
      return (
        <input
          style={s} type="text"
          value={String(value ?? '')}
          placeholder={field.placeholder ?? ''}
          disabled={disabled}
          onChange={e => onChange(e.target.value)}
        />
      );
  }
}

// ── Field wrapper (label + input + error/help) ─────────────────

function FieldWrapper({
  field, value, onChange, error, warning, disabled, viewMode, required,
}: {
  field:     FieldDefinition;
  value:     unknown;
  onChange:  (v: unknown) => void;
  error?:    string;
  warning?:  string;
  disabled?: boolean;
  viewMode?: boolean;
  required?: boolean;
}) {
  const width  = WIDTH_CSS[field.width] ?? '100%';
  const isSectionHeader = field.field_type === 'section_header';

  if (isSectionHeader) {
    return (
      <div style={{ width: '100%', marginTop: 12, marginBottom: 4 }}>
        <div style={{
          fontSize: 11, fontWeight: 700,
          fontFamily: 'var(--font-display)',
          color: 'rgba(255,255,255,0.50)',
          letterSpacing: '0.10em', textTransform: 'uppercase' as const,
          paddingBottom: 6,
          borderBottom: '1px solid var(--color-border)',
        }}>
          {field.label}
        </div>
        {field.help_text && (
          <div style={{
            fontSize: 11, color: 'rgba(255,255,255,0.35)',
            fontFamily: 'var(--font-display)', marginTop: 4,
          }}>
            {field.help_text}
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{ width, flexShrink: 0 }}>
      <label style={{
        display: 'block', fontSize: 11, fontWeight: 600,
        fontFamily: 'var(--font-display)',
        color: 'rgba(255,255,255,0.65)',
        marginBottom: 5, letterSpacing: '0.04em',
      }}>
        {field.label}
        {required && !viewMode && (
          <span style={{ color: '#ff5a5a', marginLeft: 3 }}>*</span>
        )}
      </label>

      {viewMode ? (
        <div style={{
          padding: '7px 11px', borderRadius: 6,
          border: '1px solid var(--color-border)',
          background: 'rgba(255,255,255,0.04)',
          fontFamily: 'var(--font-display)', fontSize: 13,
          color: 'var(--chalk1)', minHeight: 36,
          wordBreak: 'break-word' as const,
        }}>
          {formatViewValue(field, value)}
        </div>
      ) : (
        <FieldInput
          field={field} value={value} onChange={onChange}
          error={error} disabled={disabled}
        />
      )}

      {field.help_text && !error && (
        <div style={{
          fontSize: 10, color: 'rgba(255,255,255,0.32)',
          fontFamily: 'var(--font-display)', marginTop: 4,
        }}>
          {field.help_text}
        </div>
      )}
      {error && (
        <div style={{
          fontSize: 11, color: '#ff5a5a',
          fontFamily: 'var(--font-display)', marginTop: 4,
        }}>
          {error}
        </div>
      )}
      {!error && warning && (
        <div style={{
          fontSize: 11, color: '#ffb400',
          fontFamily: 'var(--font-display)', marginTop: 4,
        }}>
          {warning}
        </div>
      )}
    </div>
  );
}

function formatViewValue(field: FieldDefinition, value: unknown): string {
  if (value == null || value === '') return '—';
  if (field.field_type === 'boolean') return value ? 'Yes' : 'No';
  if (field.field_type === 'rating')  return `${'★'.repeat(Number(value))} (${value}/5)`;
  if (Array.isArray(value))           return (value as string[]).join(', ');
  return String(value);
}

// ══ FORM RENDERER ════════════════════════════════════════════

export default function FormRenderer({
  schemaId, entityType, entityId, associationId,
  pipelineStageOrder = 0,
  initialData, viewSubmission,
  onSubmitSuccess, onDraftSaved, onCancel,
}: FormRendererProps) {
  const [values,      setValues]      = useState<Record<string, unknown>>(
    viewSubmission?.data ?? initialData ?? {},
  );
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [fieldWarns,  setFieldWarns]  = useState<Record<string, string>>({});
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [draftId,     setDraftId]     = useState<string | null>(null);
  const [submitted,   setSubmitted]   = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [draftInitialized, setDraftInitialized] = useState(!!(viewSubmission || initialData));
  const [draftRestored, setDraftRestored] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const roleName = useAuthStore(s => s.user?.role?.name?.toLowerCase() ?? '');
  const draftInitializedRef = useRef(draftInitialized);
  draftInitializedRef.current = draftInitialized;

  const viewMode = !!viewSubmission;

  const configQ = useQuery({
    queryKey:  ['form-renderer', schemaId],
    queryFn:   () => formBuilderApi.getRendererConfig(schemaId),
    staleTime: 60_000,
  });

  const fields = configQ.data?.fields ?? [];
  const schema = configQ.data?.schema ?? null;

  const draftQ = useQuery({
    queryKey: ['form-renderer-draft', schemaId, entityType, entityId, associationId],
    queryFn: () => formBuilderApi.getLatestDraft({ schema_id: schemaId, entity_type: entityType, entity_id: entityId, association_id: associationId }),
    enabled: !!schema && !viewMode && !initialData,
    staleTime: 0,
  });

  useEffect(() => {
    if (viewMode || initialData || !draftQ.isSuccess) return;
    if (!draftInitializedRef.current) {
      if (draftQ.data) {
        setValues(draftQ.data.draft_data ?? draftQ.data.data ?? {});
        setDraftId(draftQ.data.id);
        setDraftRestored(true);
      }
      setDraftInitialized(true);
    }
  }, [draftQ.data, draftQ.isSuccess, viewMode, initialData]);

  // NOTE: there used to be an effect here that re-set `values` from
  // `initialData`. Its dependency array was empty, so it only ever ran on
  // mount -- re-applying the value useState had already seeded on the line
  // above. It never did what its comment claimed. Giving it real
  // dependencies would reset the form every time the parent re-rendered
  // with a fresh object literal, throwing away in-progress user input, so
  // it is removed rather than "fixed". Remount with a key if a genuine
  // re-seed is ever needed.

  const applyServerErrors = useCallback((
    errors:   ValidationError[],
    warnings: ValidationWarning[],
  ) => {
    const errs: Record<string, string> = {};
    const warns: Record<string, string> = {};
    for (const e of errors)   errs[e.field_key]  = e.message;
    for (const w of warnings) warns[w.field_key] = w.message;
    setFieldErrors(errs);
    setFieldWarns(warns);
  }, []);

  const validateMut = useMutation({
    mutationFn: () => formBuilderApi.validateSubmission({
      schema_id:             schemaId,
      data:                  values,
      is_draft:              true,
      pipeline_stage_order:  pipelineStageOrder,
    }),
    onSuccess: result => {
      applyServerErrors(result.errors, result.warnings);
      setGlobalError(null);
    },
    onError: () => setGlobalError('Validation request failed.'),
  });

  const draftMut = useMutation({
    mutationFn: () => formBuilderApi.saveDraft({
      schema_id:             schemaId,
      entity_type:           entityType,
      entity_id:             entityId,
      association_id:        associationId,
      data:                  values,
      draft_id:              draftId ?? undefined,
      pipeline_stage_order:  pipelineStageOrder,
    }),
    onSuccess: sub => {
      setDraftId(sub.id);
      setIsDirty(false);
      setLastSavedAt(new Date());
      setGlobalError(null);
      setFieldErrors({});
      onDraftSaved?.(sub);
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: { errors?: ValidationError[] } } } })
        ?.response?.data?.detail;
      if (detail?.errors) applyServerErrors(detail.errors, []);
      else setGlobalError('Failed to save draft.');
    },
  });

  useEffect(() => {
    if (!isDirty || !draftInitialized || viewMode || !schema || submitted || draftMut.isPending) return;
    const timer = window.setTimeout(() => draftMut.mutate(), 30_000);
    return () => window.clearTimeout(timer);
  }, [values, isDirty, draftInitialized, viewMode, schema, submitted, draftMut.isPending]);

  const submitMut = useMutation({
    mutationFn: async () => {
      // dry-run first
      const vr = await formBuilderApi.validateSubmission({
        schema_id:            schemaId,
        data:                 values,
        is_draft:             false,
        pipeline_stage_order: pipelineStageOrder,
      });
      if (!vr.is_valid) {
        applyServerErrors(vr.errors, vr.warnings);
        throw new Error('validation_failed');
      }
      return formBuilderApi.submitForm({
        schema_id:             schemaId,
        entity_type:           entityType,
        entity_id:             entityId,
        association_id:        associationId,
        data:                  values,
        draft_id:              draftId ?? undefined,
        pipeline_stage_order:  pipelineStageOrder,
      });
    },
    onSuccess: sub => {
      setSubmitted(true);
      setGlobalError(null);
      setFieldErrors({});
      onSubmitSuccess?.(sub);
    },
    onError: (err: unknown) => {
      if ((err as Error).message === 'validation_failed') {
        setGlobalError('Please fix the highlighted fields before submitting.');
        return;
      }
      const detail = (err as { response?: { data?: { detail?: { errors?: ValidationError[] } } } })
        ?.response?.data?.detail;
      if (detail?.errors) {
        applyServerErrors(detail.errors, []);
        setGlobalError('Please fix the highlighted fields before submitting.');
      } else {
        setGlobalError('Submission failed. Please try again.');
      }
    },
  });

  const setValue = (key: string, val: unknown) => {
    setValues(v => {
      const next = { ...v, [key]: val };
      for (const field of fields) {
        const logic = field.conditional_logic as ConditionalLogic;
        if (logic?.action === 'clear' && logic.conditions?.length && conditionsMatch(logic, next)) delete next[field.field_key];
      }
      return next;
    });
    setIsDirty(true);
    // clear per-field error on change
    if (fieldErrors[key]) setFieldErrors(e => { const n = { ...e }; delete n[key]; return n; });
  };

  // ── Loading / error states ──────────────────────────────────

  if (configQ.isLoading) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '40px 0', color: 'rgba(255,255,255,0.30)',
        fontFamily: 'var(--font-display)', fontSize: 13,
      }}>
        Loading form…
      </div>
    );
  }

  if (configQ.isError || !schema) {
    return (
      <div style={{
        padding: '24px', borderRadius: 8,
        border: '1px solid rgba(255,80,80,0.30)',
        background: 'rgba(255,80,80,0.07)',
        color: '#ff5a5a', fontFamily: 'var(--font-display)', fontSize: 13,
      }}>
        Failed to load form schema.
      </div>
    );
  }

  if (schema.status !== 'published' && !viewMode) {
    return (
      <div style={{
        padding: '24px', borderRadius: 8,
        border: '1px solid rgba(255,180,0,0.30)',
        background: 'rgba(255,180,0,0.08)',
        color: '#ffb400', fontFamily: 'var(--font-display)', fontSize: 13,
      }}>
        This schema is not published yet. Publish it before accepting submissions.
      </div>
    );
  }

  if (submitted) {
    return (
      <div style={{
        padding: '32px 24px', textAlign: 'center',
        border: '1px solid rgba(0,194,168,0.30)',
        borderRadius: 10,
        background: 'rgba(0,194,168,0.06)',
      }}>
        <div style={{
          fontSize: 32, marginBottom: 12, color: 'var(--color-teal)',
        }}>
          ✓
        </div>
        <div style={{
          fontSize: 16, fontWeight: 700,
          fontFamily: 'var(--font-display)', color: 'var(--chalk1)',
          marginBottom: 6,
        }}>
          Form Submitted
        </div>
        <div style={{
          fontSize: 13, color: 'var(--chalk3)', fontFamily: 'var(--font-display)',
        }}>
          Your response has been recorded successfully.
        </div>
      </div>
    );
  }

  // ── Visible fields filtered by conditional logic ────────────

  const visibleFields = fields.filter(f => {
    if (!isFieldVisible(f, values)) return false;
    if (f.role_visibility?.length && !f.role_visibility.some(r => r.toLowerCase() === roleName)) return false;
    return f.stage_visible_from == null || pipelineStageOrder >= f.stage_visible_from;
  });

  const busy = draftMut.isPending || submitMut.isPending || validateMut.isPending;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {/* Schema header */}
      {!viewMode && (
        <div style={{ marginBottom: 20 }}>
          <div style={{
            fontSize: 16, fontWeight: 700,
            fontFamily: 'var(--font-display)', color: 'var(--chalk1)',
            marginBottom: 4,
          }}>
            {schema.name}
          </div>
          {schema.description && (
            <div style={{
              fontSize: 12, color: 'rgba(255,255,255,0.45)',
              fontFamily: 'var(--font-display)',
            }}>
              {schema.description}
            </div>
          )}
        </div>
      )}

      {/* Global error */}
      {globalError && (
        <div style={{
          padding: '10px 14px', borderRadius: 6, marginBottom: 16,
          border: '1px solid rgba(255,80,80,0.30)',
          background: 'rgba(255,80,80,0.08)',
          color: '#ff5a5a', fontFamily: 'var(--font-display)', fontSize: 12,
        }}>
          {globalError}
        </div>
      )}

      {/* View mode: submission metadata banner */}
      {viewMode && viewSubmission && (
        <div style={{
          padding: '10px 14px', borderRadius: 8, marginBottom: 20,
          border: '1px solid var(--color-border)',
          background: 'rgba(255,255,255,0.03)',
          display: 'flex', gap: 20, flexWrap: 'wrap' as const,
        }}>
          <MetaItem label="Status">
            <StatusPill status={viewSubmission.status} />
          </MetaItem>
          <MetaItem label="Submitted">
            {new Date(viewSubmission.submitted_at).toLocaleString()}
          </MetaItem>
          {viewSubmission.entity_type && (
            <MetaItem label="Entity">{viewSubmission.entity_type}</MetaItem>
          )}
          {viewSubmission.rejection_reason && (
            <MetaItem label="Rejection reason" wide>
              {viewSubmission.rejection_reason}
            </MetaItem>
          )}
        </div>
      )}

      {/* Field grid */}
      <div style={{ display: 'flex', flexWrap: 'wrap' as const, gap: 14 }}>
        {visibleFields.map(field => (
          <FieldWrapper
            key={field.id}
            field={field}
            value={values[field.field_key] ?? ''}
            onChange={val => setValue(field.field_key, val)}
            error={fieldErrors[field.field_key]}
            warning={fieldWarns[field.field_key]}
            required={isFieldRequired(field, values) && (field.stage_required_at == null || pipelineStageOrder >= field.stage_required_at)}
            disabled={isFieldDisabled(field, values) || viewMode || busy || !!(field.role_editable?.length && !field.role_editable.some(r => r.toLowerCase() === roleName))}
            viewMode={viewMode}
          />
        ))}
      </div>

      {visibleFields.length === 0 && !viewMode && (
        <div style={{
          textAlign: 'center', padding: '40px 0',
          color: 'rgba(255,255,255,0.25)',
          fontFamily: 'var(--font-display)', fontSize: 13,
        }}>
          This form has no visible fields.
        </div>
      )}

      {/* Action bar */}
      {!viewMode && (
        <>
        <div aria-live="polite" style={{ marginTop: 18, color: 'var(--text-muted)', fontFamily: 'var(--font-display)', fontSize: 10 }}>
          {draftMut.isPending ? 'Saving draft…' : isDirty ? 'Unsaved changes · auto-save in 30 seconds' : lastSavedAt ? `Draft saved at ${lastSavedAt.toLocaleTimeString()}` : draftRestored ? 'Saved draft restored' : ''}
        </div>
        <div style={{
          display: 'flex', gap: 10, justifyContent: 'flex-end',
          marginTop: 24, paddingTop: 16,
          borderTop: '1px solid var(--color-border)',
        }}>
          <button
            type="button"
            onClick={() => validateMut.mutate()}
            disabled={busy}
            style={ghostBtnStyle(busy)}
          >
            Validate
          </button>
          <button
            type="button"
            onClick={() => draftMut.mutate()}
            disabled={busy}
            style={ghostBtnStyle(busy)}
          >
            {draftMut.isPending ? 'Saving…' : draftId ? 'Update Draft' : 'Save Draft'}
          </button>
          {onCancel && (
            <button type="button" onClick={onCancel} style={ghostBtnStyle(false)}>
              Cancel
            </button>
          )}
          <button
            type="button"
            onClick={() => submitMut.mutate()}
            disabled={busy}
            style={primaryBtnStyle(busy)}
          >
            {submitMut.isPending ? 'Submitting…' : 'Submit'}
          </button>
        </div>
        </>
      )}
    </div>
  );
}

// ── Small helper components ───────────────────────────────────

function MetaItem({
  label, children, wide,
}: {
  label:    string;
  children: React.ReactNode;
  wide?:    boolean;
}) {
  return (
    <div style={{ minWidth: wide ? '100%' : 'auto' }}>
      <div style={{
        fontSize: 9, fontWeight: 700,
        fontFamily: 'var(--font-display)',
        color: 'rgba(255,255,255,0.35)',
        letterSpacing: '0.10em', textTransform: 'uppercase' as const,
        marginBottom: 2,
      }}>
        {label}
      </div>
      <div style={{
        fontSize: 12, fontFamily: 'var(--font-display)', color: 'var(--chalk2)',
      }}>
        {children}
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, { bg: string; color: string }> = {
    draft:     { bg: 'rgba(255,180,0,0.15)',   color: '#ffb400'             },
    submitted: { bg: 'rgba(0,140,255,0.15)',   color: '#4da6ff'             },
    approved:  { bg: 'rgba(0,194,168,0.15)',   color: 'var(--color-teal)'   },
    rejected:  { bg: 'rgba(255,80,80,0.15)',   color: '#ff5a5a'             },
  };
  const c = map[status] ?? map.draft;
  return (
    <span style={{
      padding: '2px 8px', borderRadius: 4,
      fontSize: 10, fontWeight: 700,
      fontFamily: 'var(--font-display)',
      textTransform: 'uppercase' as const, letterSpacing: '0.08em',
      background: c.bg, color: c.color,
    }}>
      {status}
    </span>
  );
}

// ── Button styles ─────────────────────────────────────────────

function ghostBtnStyle(disabled: boolean): React.CSSProperties {
  return {
    padding: '8px 18px', borderRadius: 6,
    border: '1px solid var(--color-border)',
    background: 'rgba(255,255,255,0.07)',
    color: 'var(--chalk2)',
    fontFamily: 'var(--font-display)',
    fontSize: 13, fontWeight: 600,
    cursor: disabled ? 'default' : 'pointer',
    opacity: disabled ? 0.5 : 1,
  };
}

function primaryBtnStyle(disabled: boolean): React.CSSProperties {
  return {
    padding: '8px 22px', borderRadius: 6,
    border: 'none',
    background: 'var(--brand)',
    color: 'var(--color-navy)',
    fontFamily: 'var(--font-display)',
    fontSize: 13, fontWeight: 700,
    cursor: disabled ? 'default' : 'pointer',
    opacity: disabled ? 0.5 : 1,
  };
}
