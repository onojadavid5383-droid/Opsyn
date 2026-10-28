// ============================================================
// OPSYN UI — Input + Textarea  (Phase 4)
// Same props as before (79 + 10 call sites), plus `unit` for telecom
// values. Sentence-case labels; hint/error announced with the field
// (aria-describedby); errors set aria-invalid; required is aria-required
// with a visual marker. `style` still wraps the field (default bottom
// spacing kept so existing forms don't reflow); `inputStyle` the control.
// ============================================================

import React, { useId } from 'react';
import styles from './Field.module.css';

export interface InputProps {
  label?:       string;
  ariaLabel?:   string;
  id?:          string;
  value:        string | number;
  onChange:     (value: string) => void;
  type?:        React.HTMLInputTypeAttribute;
  placeholder?: string;
  error?:       string;
  hint?:        string;
  required?:    boolean;
  disabled?:    boolean;
  readOnly?:    boolean;
  autoFocus?:   boolean;
  maxLength?:   number;
  min?:         number | string;
  max?:         number | string;
  prefix?:      React.ReactNode;
  suffix?:      React.ReactNode;
  /** Unit shown inside the field, e.g. "dBm", "km", "%" */
  unit?:        string;
  autoComplete?: string;
  inputMode?:   React.HTMLAttributes<HTMLInputElement>['inputMode'];
  style?:       React.CSSProperties;
  inputStyle?:  React.CSSProperties;
}

function useFieldIds(id: string | undefined, label: string | undefined) {
  const auto = useId();
  const fieldId = id ?? (label ? label.toLowerCase().replace(/\s+/g, '-') : `field-${auto.replace(/:/g, '')}`);
  return { fieldId, messageId: `${fieldId}-message` };
}

function FieldLabel({ htmlFor, required, children }: { htmlFor: string; required?: boolean; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className={styles.label}>
      {children}
      {required && <span className={styles.required} aria-hidden="true">*</span>}
    </label>
  );
}

function FieldMessage({ id, error, hint }: { id: string; error?: string; hint?: string }) {
  if (!error && !hint) return null;
  return (
    <div id={id} className={`${styles.message} ${error ? styles.error : ''}`}>
      {error ?? hint}
    </div>
  );
}

export function Input({
  label, ariaLabel, id, value, onChange, type = 'text', placeholder, error, hint,
  required, disabled, readOnly, autoFocus, maxLength, min, max,
  prefix, suffix, unit, autoComplete, inputMode, style, inputStyle,
}: InputProps) {
  const { fieldId, messageId } = useFieldIds(id, label);
  const trailing = unit ?? suffix;

  return (
    <div className={styles.field} style={style}>
      {label && <FieldLabel htmlFor={fieldId} required={required}>{label}</FieldLabel>}

      <div className={styles.control}>
        {prefix && <span className={`${styles.affix} ${styles.prefix}`}>{prefix}</span>}
        <input
          id={fieldId}
          name={fieldId}
          aria-label={ariaLabel}
          type={type}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          readOnly={readOnly}
          autoFocus={autoFocus}
          maxLength={maxLength}
          min={min}
          max={max}
          required={required}
          autoComplete={autoComplete}
          inputMode={inputMode}
          aria-invalid={error ? true : undefined}
          aria-describedby={error || hint || unit ? messageId : undefined}
          className={[styles.input, prefix && styles.hasPrefix, trailing && styles.hasSuffix].filter(Boolean).join(' ')}
          style={unit ? { paddingRight: `calc(${unit.length}ch + 28px)`, ...inputStyle } : inputStyle}
        />
        {unit
          ? <span className={styles.unit} aria-hidden="true">{unit}</span>
          : suffix && <span className={`${styles.affix} ${styles.suffix}`}>{suffix}</span>}
      </div>
      {/* The unit is part of the value's meaning — give it to screen readers too */}
      {unit && !hint && !error && <span id={messageId} className="sr-only">in {unit}</span>}

      <FieldMessage id={messageId} error={error} hint={hint ? `${hint}${unit ? ` (${unit})` : ''}` : undefined} />
    </div>
  );
}

export interface TextareaProps {
  label?:       string;
  id?:          string;
  value:        string;
  onChange:     (value: string) => void;
  placeholder?: string;
  rows?:        number;
  error?:       string;
  hint?:        string;
  required?:    boolean;
  disabled?:    boolean;
  maxLength?:   number;
  style?:       React.CSSProperties;
  onBlur?:      () => void;
  /** For dialogs that focus the field first (GlassModal initialFocus) */
  textareaRef?: React.Ref<HTMLTextAreaElement>;
}

export function Textarea({
  label, id, value, onChange, placeholder, rows = 3, error, hint, required, disabled, maxLength, style, onBlur, textareaRef,
}: TextareaProps) {
  const { fieldId, messageId } = useFieldIds(id, label);
  return (
    <div className={styles.field} style={style}>
      {label && <FieldLabel htmlFor={fieldId} required={required}>{label}</FieldLabel>}
      <textarea
        ref={textareaRef}
        id={fieldId}
        name={fieldId}
        value={value}
        onChange={e => onChange(e.target.value)}
        onBlur={onBlur}
        placeholder={placeholder}
        rows={rows}
        disabled={disabled}
        maxLength={maxLength}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? messageId : undefined}
        className={styles.input}
        style={{ minHeight: rows * 24 }}
      />
      <FieldMessage id={messageId} error={error} hint={hint} />
    </div>
  );
}
