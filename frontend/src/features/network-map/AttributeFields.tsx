// ============================================================
// OPSYN NETWORK MAP — attribute view + editor, driven by the catalogue.
// The field list, labels, units and choices all come from
// GET /network/catalogue (backend attributes.py), so the inspector never
// keeps its own copy of a type's schema. Values the spec doesn't know
// (engine output, upload extras) are shown under "Other details";
// upload-era references (legacy_*) are shown as links elsewhere.
// ============================================================

import { useId } from 'react';
import type { NetFieldSpec } from '@shared';
import { formatField, formatRaw, humaniseKey, humaniseOption, isHiddenKey } from './attributeFormat';
import s from './NetworkMap.module.css';

export function FactRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (<><dt>{label}</dt><dd>{children}</dd></>);
}

export function AttributeView({ specs, values }: { specs: NetFieldSpec[]; values: Record<string, unknown> }) {
  const known = new Set(specs.map(f => f.key));
  const recorded = specs.filter(f => values[f.key] !== undefined && values[f.key] !== null && values[f.key] !== '');
  const missing = specs.length - recorded.length;
  const extra = Object.entries(values).filter(([k]) => !known.has(k) && !isHiddenKey(k));
  return (
    <>
      {recorded.length > 0 ? (
        <dl className={s.facts}>
          {recorded.map(f => <FactRow key={f.key} label={f.label}>{formatField(f, values[f.key])}</FactRow>)}
        </dl>
      ) : (
        <p className={s.muted}>No details recorded yet.</p>
      )}
      {missing > 0 && recorded.length > 0 && (
        <p className={s.hint}>{missing} more {missing === 1 ? 'field' : 'fields'} not recorded.</p>
      )}
      {extra.length > 0 && (
        <>
          <h4 className={s.subTitle}>Other details</h4>
          <dl className={s.facts}>
            {extra.map(([k, v]) => <FactRow key={k} label={humaniseKey(k)}>{formatRaw(v)}</FactRow>)}
          </dl>
        </>
      )}
    </>
  );
}

export function FieldInput({ spec, value, onChange }: { spec: NetFieldSpec; value: string; onChange: (v: string) => void }) {
  const id = useId();
  const hint = [spec.unit && `In ${spec.unit}`, spec.help].filter(Boolean).join('. ');
  return (
    <div className={s.formRow}>
      <label htmlFor={id}>{spec.label}</label>
      {spec.kind === 'enum' || spec.kind === 'bool' ? (
        <select id={id} value={value} onChange={e => onChange(e.target.value)}>
          <option value="">Not recorded</option>
          {(spec.kind === 'bool' ? ['true', 'false'] : spec.options).map(o => (
            <option key={o} value={o}>{spec.kind === 'bool' ? (o === 'true' ? 'Yes' : 'No') : humaniseOption(o)}</option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          value={value}
          onChange={e => onChange(e.target.value)}
          inputMode={spec.kind === 'int' ? 'numeric' : spec.kind === 'number' ? 'decimal' : undefined}
          aria-describedby={hint ? `${id}-hint` : undefined}
          autoComplete="off"
        />
      )}
      {hint && <span id={`${id}-hint`} className={s.hint}>{hint}</span>}
    </div>
  );
}
