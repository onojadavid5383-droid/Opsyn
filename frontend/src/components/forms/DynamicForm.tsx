// ============================================================
// OPSYN DYNAMIC FORM — user-facing renderer
// Resolves field visibility + required status from dependencies.
// Calls onSubmit with validated data; onCancel to dismiss.
// ============================================================

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import FormFieldRenderer from './FormFieldRenderer';
import { formsApi } from '../../api/index';
import type { FormSchema, FormField, FormFieldDependency, FormData } from '@shared';
import type { ApiError } from '../../api/client';

interface Props {
  schema:      FormSchema;
  entityType?: string;
  entityId?:   string;
  onSuccess?:  (submissionId: string) => void;
  onCancel?:   () => void;
  submitLabel?: string;
}

// ── Dependency resolution ────────────────────────────────────

type FieldState = { visible: boolean; required: boolean };

function resolveStates(
  fields:       FormField[],
  deps:         FormFieldDependency[],
  data:         FormData,
): Record<string, FieldState> {
  const states: Record<string, FieldState> = {};
  for (const f of fields) {
    states[f.field_key] = { visible: true, required: f.required };
  }

  for (const dep of deps) {
    const srcVal = data[dep.source_field_key];
    const condVal = dep.condition_value ?? '';
    let condMet = false;

    switch (dep.condition_operator) {
      case 'eq':           condMet = String(srcVal ?? '') === condVal; break;
      case 'neq':          condMet = String(srcVal ?? '') !== condVal; break;
      case 'gt':           condMet = Number(srcVal) >  Number(condVal); break;
      case 'lt':           condMet = Number(srcVal) <  Number(condVal); break;
      case 'contains':     condMet = String(srcVal ?? '').toLowerCase().includes(condVal.toLowerCase()); break;
      case 'is_empty':     condMet = srcVal === undefined || srcVal === null || srcVal === ''; break;
      case 'is_not_empty': condMet = srcVal !== undefined && srcVal !== null && srcVal !== ''; break;
    }

    if (!condMet) continue;

    const target = states[dep.target_field_key];
    if (!target) continue;

    if (dep.action === 'show')    target.visible  = true;
    if (dep.action === 'hide')    target.visible  = false;
    if (dep.action === 'require') target.required = true;
  }

  return states;
}

// ── Validate client-side (basic required + visible check) ────

function clientValidate(
  fields:  FormField[],
  states:  Record<string, FieldState>,
  data:    FormData,
): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const f of fields) {
    const st = states[f.field_key];
    if (!st?.visible) continue;
    if (st.required) {
      const v = data[f.field_key];
      if (v === undefined || v === null || v === '') {
        errors[f.field_key] = 'This field is required.';
      }
    }
  }
  return errors;
}

// ── Component ────────────────────────────────────────────────

export default function DynamicForm({
  schema, entityType, entityId, onSuccess, onCancel, submitLabel = 'Submit',
}: Props) {
  const [data, setData]     = useState<FormData>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  const fields  = schema.fields  ?? [];
  const deps    = schema.dependencies ?? [];
  const states  = resolveStates(fields, deps, data);
  const visible = fields.filter(f => states[f.field_key]?.visible !== false);

  const handleChange = (key: string, value: unknown) => {
    setData(prev => ({ ...prev, [key]: value }));
    if (errors[key]) setErrors(prev => { const e = { ...prev }; delete e[key]; return e; });
  };

  const submitMutation = useMutation({
    mutationFn: () => formsApi.submit({
      context:        schema.context,
      entity_type:    entityType,
      entity_id:      entityId,
      submitted_data: data,
    }),
    onSuccess: res => onSuccess?.(res.id),
    onError: (e: ApiError) => {
      // Handle 422 field-level errors from backend
      const detail = e?.response?.data?.detail;
      if (detail?.errors) {
        const fieldErrors: Record<string, string> = {};
        for (const err of detail.errors as { field: string; message: string }[]) {
          fieldErrors[err.field] = err.message;
        }
        setErrors(fieldErrors);
      }
    },
  });

  const handleSubmit = () => {
    const clientErrors = clientValidate(fields, states, data);
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      return;
    }
    submitMutation.mutate();
  };

  const hasErrors = Object.keys(errors).length > 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {/* Schema title */}
      {schema.title && (
        <div style={{
          marginBottom: 16, paddingBottom: 12,
          borderBottom: '1px solid var(--wire)',
        }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--chalk)' }}>{schema.title}</div>
          {schema.description && (
            <div style={{ fontSize: 11, color: 'var(--chalk3)', marginTop: 3 }}>{schema.description}</div>
          )}
        </div>
      )}

      {/* Fields */}
      {visible.length === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--chalk3)', padding: '16px 0' }}>
          No fields to display.
        </div>
      ) : (
        visible.map(field => (
          <FormFieldRenderer
            key={field.id}
            field={{ ...field, required: states[field.field_key]?.required ?? field.required }}
            value={data[field.field_key]}
            onChange={handleChange}
            error={errors[field.field_key]}
            disabled={submitMutation.isPending}
          />
        ))
      )}

      {/* Error summary */}
      {hasErrors && (
        <div style={{
          padding: '8px 12px', borderRadius: 8, marginBottom: 12,
          background: 'rgba(248,113,113,.08)', border: '1px solid rgba(248,113,113,.25)',
          fontSize: 11, color: 'var(--rose)',
        }}>
          Please correct the errors above before submitting.
        </div>
      )}

      {/* Actions */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
        {onCancel && (
          <button
            type="button" onClick={onCancel} disabled={submitMutation.isPending}
            style={{
              padding: '6px 14px', borderRadius: 8, border: '1px solid var(--wire2)',
              background: 'transparent', color: 'var(--chalk2)',
              fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'var(--font)',
            }}>
            Cancel
          </button>
        )}
        <button
          type="button" onClick={handleSubmit}
          disabled={submitMutation.isPending || visible.length === 0}
          style={{
            padding: '6px 14px', borderRadius: 8, border: 'none',
            background: 'var(--brand)', color: '#050810',
            fontSize: 12, fontWeight: 700, cursor: 'pointer', fontFamily: 'var(--font)',
            boxShadow: '0 0 12px rgba(6,182,212,.25)',
            opacity: submitMutation.isPending ? 0.6 : 1,
          }}>
          {submitMutation.isPending ? 'Submitting…' : submitLabel}
        </button>
      </div>
    </div>
  );
}
