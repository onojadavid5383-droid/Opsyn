// ============================================================
// OPSYN FORM FIELD RENDERER — 10 field types
// Used by DynamicForm to render each field.
// ============================================================

import CoordinatesField from './CoordinatesField';
import type { FormField } from '@shared';
import { GlassSelect } from '../../components/glass';

interface Props {
  field:    FormField;
  value:    unknown;
  onChange: (key: string, value: unknown) => void;
  error?:   string;
  disabled?: boolean;
}

const LABEL_STYLE: React.CSSProperties = {
  display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--chalk3)',
  marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.1em',
};

const INPUT_STYLE: React.CSSProperties = {
  width: '100%', background: 'var(--bg3)', border: '1px solid var(--wire2)',
  borderRadius: 8, padding: '9px 12px', color: 'var(--chalk)',
  fontFamily: 'var(--font)', fontSize: 12, outline: 'none',
};

const ERROR_STYLE: React.CSSProperties = {
  marginTop: 4, fontSize: 10, color: 'var(--rose)',
};

const HELP_STYLE: React.CSSProperties = {
  marginTop: 4, fontSize: 10, color: 'var(--chalk3)',
};

export default function FormFieldRenderer({ field, value, onChange, error, disabled }: Props) {
  const { field_key, field_type, label, placeholder, help_text, required, options } = field;
  const val = value ?? '';

  const wrapperStyle: React.CSSProperties = {
    marginBottom: 16,
    borderLeft: error ? '2px solid var(--rose)' : '2px solid transparent',
    paddingLeft: error ? 8 : 0,
    transition: 'all .15s',
  };

  const borderColor = error ? 'var(--rose)' : 'var(--wire2)';

  const labelNode = (
    <label style={LABEL_STYLE}>
      {label}
      {required && <span style={{ color: 'var(--rose)', marginLeft: 2 }}>*</span>}
    </label>
  );

  let inputNode: React.ReactNode = null;

  if (field_type === 'text') {
    inputNode = (
      <input
        type="text" value={String(val)} placeholder={placeholder ?? ''}
        disabled={disabled}
        onChange={e => onChange(field_key, e.target.value)}
        style={{ ...INPUT_STYLE, border: `1px solid ${borderColor}` }}
      />
    );
  }

  else if (field_type === 'textarea') {
    inputNode = (
      <textarea
        value={String(val)} placeholder={placeholder ?? ''}
        disabled={disabled} rows={3}
        onChange={e => onChange(field_key, e.target.value)}
        style={{ ...INPUT_STYLE, border: `1px solid ${borderColor}`, resize: 'vertical' }}
      />
    );
  }

  else if (field_type === 'number') {
    inputNode = (
      <input
        type="number" value={val === '' ? '' : String(val)} placeholder={placeholder ?? ''}
        disabled={disabled}
        onChange={e => onChange(field_key, e.target.value === '' ? '' : Number(e.target.value))}
        style={{ ...INPUT_STYLE, border: `1px solid ${borderColor}` }}
      />
    );
  }

  else if (field_type === 'dropdown') {
    const opts = options ?? [];
    inputNode = (
      <GlassSelect value={String(val)} onChange={v => onChange(field_key, v)} options={[...opts.map((o: any) => ({ value: String(o.value ?? o), label: String(o.label ?? o) }))]} placeholder={String(placeholder ?? 'Select an option…')} disabled={disabled} ariaLabel={label} />
    );
  }

  else if (field_type === 'date') {
    inputNode = (
      <input
        type="date" value={String(val)} disabled={disabled}
        onChange={e => onChange(field_key, e.target.value)}
        style={{ ...INPUT_STYLE, border: `1px solid ${borderColor}` }}
      />
    );
  }

  else if (field_type === 'phone') {
    inputNode = (
      <input
        type="tel" value={String(val)} placeholder={placeholder ?? '+2348012345678'}
        disabled={disabled}
        onChange={e => onChange(field_key, e.target.value)}
        style={{ ...INPUT_STYLE, border: `1px solid ${borderColor}`, fontFamily: 'var(--mono)' }}
      />
    );
  }

  else if (field_type === 'email') {
    inputNode = (
      <input
        type="email" value={String(val)} placeholder={placeholder ?? 'user@example.com'}
        disabled={disabled}
        onChange={e => onChange(field_key, e.target.value)}
        style={{ ...INPUT_STYLE, border: `1px solid ${borderColor}` }}
      />
    );
  }

  else if (field_type === 'boolean') {
    inputNode = (
      <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: disabled ? 'not-allowed' : 'pointer' }}>
        <div
          onClick={() => !disabled && onChange(field_key, !val)}
          style={{
            width: 36, height: 20, borderRadius: 10,
            background: val ? 'var(--green)' : 'var(--wire)',
            transition: 'background .2s', position: 'relative', flexShrink: 0,
            cursor: disabled ? 'not-allowed' : 'pointer',
            boxShadow: val ? '0 0 8px rgba(74,222,128,.3)' : 'none',
          }}>
          <div style={{
            width: 14, height: 14, borderRadius: '50%', background: 'var(--surface)',
            position: 'absolute', top: 3,
            left: val ? 19 : 3, transition: 'left .2s',
          }} />
        </div>
        <span style={{ fontSize: 12, color: 'var(--chalk2)' }}>
          {val ? 'Yes' : 'No'}
        </span>
      </label>
    );
  }

  else if (field_type === 'file') {
    const fileVal = val as any;
    inputNode = (
      <div>
        <input
          type="file" disabled={disabled}
          style={{ display: 'none' }}
          id={`file-${field_key}`}
          onChange={e => {
            const file = e.target.files?.[0];
            if (!file) return;
            onChange(field_key, {
              name:       file.name,
              size_bytes: file.size,
              mime_type:  file.type,
            });
          }}
        />
        <label
          htmlFor={`file-${field_key}`}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            padding: '8px 14px', borderRadius: 8, cursor: disabled ? 'not-allowed' : 'pointer',
            border: `1px dashed ${borderColor}`,
            background: 'var(--bg3)', color: 'var(--chalk2)', fontSize: 12,
          }}>
          {fileVal?.name ?? (placeholder ?? 'Choose file…')}
        </label>
        {fileVal?.name && (
          <div style={{ marginTop: 4, fontSize: 10, color: 'var(--chalk3)' }}>
            {fileVal.name} ({(fileVal.size_bytes / 1024).toFixed(1)} KB)
          </div>
        )}
      </div>
    );
  }

  else if (field_type === 'coordinates') {
    const coordVal = (val && typeof val === 'object') ? val as { lat: string; lng: string } : null;
    inputNode = (
      <CoordinatesField
        value={coordVal}
        onChange={v => onChange(field_key, v)}
        disabled={disabled}
      />
    );
  }

  return (
    <div style={wrapperStyle}>
      {labelNode}
      {inputNode}
      {help_text && !error && <div style={HELP_STYLE}>{help_text}</div>}
      {error && <div style={ERROR_STYLE}>{error}</div>}
    </div>
  );
}
