// ============================================================
// OPSYN CUSTOMER DETAIL PAGE — src/pages/customers/CustomerDetailPage.tsx
// Profile · payment · linked projects · stage field submission
// ============================================================

import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useCustomer, useCustomerFields, useSubmitCustomerFields } from '../../hooks/useCustomers';
import { useUIStore } from '../../store/ui.store';
import { formBuilderApi, type ContextSchema } from '../../api/form-builder.api';
import FormRenderer from '../../components/form-builder/FormRenderer';
import { GlassSelect } from '../../components/glass';

function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, msg?: string) => addToast({ type: 'success', title, message: msg }),
    error:   (title: string, msg?: string) => addToast({ type: 'error',   title, message: msg }),
  };
}

const STATUS_COLOR: Record<string, string> = {
  pending:   '#f59e0b',
  active:    '#16a34a',
  suspended: '#dc2626',
  churned:   '#94a3b8',
};
const PAYMENT_COLOR: Record<string, string> = {
  pending:  '#f59e0b',
  paid:     '#16a34a',
  expired:  '#dc2626',
  refunded: '#6366f1',
};

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', gap: 12, padding: '9px 0', borderBottom: '1px solid var(--color-border)' }}>
      <span style={{ width: 140, fontSize: 11, color: 'var(--color-text-muted)', flexShrink: 0 }}>{label}</span>
      <span style={{ fontSize: 12, color: 'var(--color-text-primary)', fontWeight: 500 }}>{value ?? '—'}</span>
    </div>
  );
}

// ── Stage Field Submission Panel ──────────────────────────────

function FieldSubmissionPanel({ customerId }: { customerId: string }) {
  const toast = useToast();
  const [stageOrder, setStageOrder] = useState(1);
  const { data: fieldsData, isLoading } = useCustomerFields(customerId, stageOrder);
  const submit = useSubmitCustomerFields(customerId);

  const fields: any[] = (fieldsData as any)?.data ?? [];
  const [values, setValues] = useState<Record<string, string>>({});

  const setValue = (key: string, val: string) => setValues(p => ({ ...p, [key]: val }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const payload: Record<string, any> = {};
    fields.forEach((f: any) => {
      const v = values[f.key] ?? f.currentValue ?? '';
      if (v !== '') payload[f.key] = v;
    });
    try {
      await submit.mutateAsync({ fields: payload, stageOrder });
      toast.success(`Stage ${stageOrder} fields saved`);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      if (detail?.field_errors) {
        toast.error('Validation errors', Object.values(detail.field_errors).join(', '));
      } else {
        toast.error('Save failed', String(detail ?? e));
      }
    }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '7px 10px', borderRadius: 7, boxSizing: 'border-box',
    border: '1px solid var(--color-border)', background: 'var(--color-surface)',
    color: 'var(--color-text-primary)', fontFamily: 'var(--font-body)', fontSize: 12, outline: 'none',
  };

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 12, padding: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Pipeline Fields
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>Stage:</span>
          {[1, 2, 3, 4, 5].map(n => (
            <button key={n} onClick={() => setStageOrder(n)}
              style={{
                width: 28, height: 28, borderRadius: '50%', fontSize: 11, fontWeight: 700,
                cursor: 'pointer', fontFamily: 'var(--font-body)',
                border: stageOrder === n ? 'none' : '1px solid var(--color-border)',
                background: stageOrder === n ? '#0ea5e9' : 'transparent',
                color:      stageOrder === n ? 'white'   : 'var(--color-text-muted)',
              }}>
              {n}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)', padding: '20px 0' }}>Loading fields…</div>
      ) : fields.length === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)', padding: '16px 0' }}>
          No fields defined for stage {stageOrder}.
        </div>
      ) : (
        <form onSubmit={handleSubmit}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
            {fields.map((f: any) => {
              const current = values[f.key] ?? f.currentValue ?? '';
              return (
                <div key={f.key}>
                  <label style={{ fontSize: 10, fontWeight: 700, color: f.isRequired ? '#dc2626' : 'var(--color-text-muted)',
                    textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 4, display: 'block' }}>
                    {f.label}{f.isRequired && ' *'}
                  </label>
                  {f.fieldType === 'textarea' ? (
                    <textarea style={{ ...inputStyle, resize: 'vertical' }} rows={2}
                      value={current} onChange={e => setValue(f.key, e.target.value)} />
                  ) : f.fieldType === 'select' && f.validationRules?.options_list ? (
                    <GlassSelect value={String(current)} onChange={v => setValue(f.key, v)} options={[...f.validationRules.options_list.map((o: string) => ({ value: String(o), label: String(o) }))]} placeholder={'Select…'} ariaLabel={f.label} />
                  ) : (
                    <input style={inputStyle}
                      type={f.fieldType === 'email' ? 'email' : f.fieldType === 'number' ? 'number' : f.fieldType === 'date' ? 'date' : 'text'}
                      value={current}
                      onChange={e => setValue(f.key, e.target.value)}
                      placeholder={f.label}
                    />
                  )}
                  {f.isComplete === false && (
                    <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 2 }}>Incomplete</div>
                  )}
                </div>
              );
            })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button type="submit" disabled={submit.isPending}
              style={{ padding: '8px 18px', borderRadius: 8, fontSize: 12, fontWeight: 700,
                border: 'none', background: '#0ea5e9', color: 'white', cursor: 'pointer',
                fontFamily: 'var(--font-body)', opacity: submit.isPending ? 0.6 : 1 }}>
              {submit.isPending ? 'Saving…' : 'Save Fields'}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

// ── Dynamic Forms Panel (Form Builder integration — Phase 8) ──

function DynamicFormsPanel({ customerId }: { customerId: string }) {
  const [activeIdx, setActiveIdx] = useState(0);

  const contextQ = useQuery({
    queryKey: ['form-builder', 'context', 'module', customerId],
    queryFn:  () => formBuilderApi.getContextSchemas('module', customerId),
    staleTime: 60_000,
  });

  const schemas: ContextSchema[] = contextQ.data ?? [];

  if (contextQ.isLoading) return null;
  if (!schemas.length) return null;

  const active = schemas[activeIdx] ?? schemas[0];

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 12, padding: 20, marginTop: 16 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 12 }}>
        Dynamic Forms
      </div>

      {schemas.length > 1 && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
          {schemas.map((cs, i) => (
            <button
              key={cs.association.id}
              onClick={() => setActiveIdx(i)}
              style={{
                padding: '4px 12px', borderRadius: 6, fontSize: 11, fontWeight: 600,
                border: activeIdx === i ? 'none' : '1px solid var(--color-border)',
                background: activeIdx === i ? '#0ea5e9' : 'transparent',
                color:      activeIdx === i ? 'white'   : 'var(--color-text-muted)',
                cursor: 'pointer', fontFamily: 'var(--font-body)',
              }}
            >
              {cs.schema.name}
              {cs.schema.is_mandatory && (
                <span style={{ color: activeIdx === i ? 'rgba(255,255,255,.7)' : '#dc2626', marginLeft: 3 }}>*</span>
              )}
            </button>
          ))}
        </div>
      )}

      <FormRenderer
        schemaId={active.schema.id}
        entityType="module"
        entityId={customerId}
        associationId={active.association.id}
      />
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────

export default function CustomerDetailPage() {
  const { id }    = useParams<{ id: string }>();
  const navigate  = useNavigate();
  const { data, isLoading, isError } = useCustomer(id!);

  if (isLoading) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: 'var(--color-text-muted)', fontSize: 13 }}>
        Loading customer…
      </div>
    );
  }

  if (isError || !(data as any)?.data) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', gap: 10, color: 'var(--color-text-muted)', fontSize: 13 }}>
        <div style={{ fontSize: 36 }}>👤</div>
        <div style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>Customer not found</div>
        <button onClick={() => navigate('/customers')}
          style={{ padding: '7px 16px', borderRadius: 8, fontSize: 12, fontWeight: 600,
            border: '1px solid var(--color-border)', background: 'var(--color-surface)',
            color: 'var(--color-text-primary)', cursor: 'pointer', fontFamily: 'var(--font-body)' }}>
          ← Back to Customers
        </button>
      </div>
    );
  }

  const customer  = (data as any).data;
  const payment   = customer.payment ?? null;
  const projects: any[] = customer.projects ?? [];

  const statusColor = STATUS_COLOR[customer.status] ?? '#94a3b8';

  return (
    <div style={{ overflow: 'auto', flex: 1, background: 'var(--color-surface)' }}>
      <div style={{ padding: '28px', maxWidth: 900, margin: '0 auto' }}>

        {/* Back + Header */}
        <button onClick={() => navigate('/customers')}
          style={{ marginBottom: 16, padding: '5px 12px', borderRadius: 7, fontSize: 11, fontWeight: 600,
            border: '1px solid var(--color-border)', background: 'transparent',
            color: 'var(--color-text-muted)', cursor: 'pointer', fontFamily: 'var(--font-body)' }}>
          ← Customers
        </button>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 800, color: 'var(--color-text-primary)', letterSpacing: '-.02em', margin: 0 }}>
              {customer.fullName ?? `${customer.firstName} ${customer.lastName}`}
            </h1>
            <div style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ padding: '2px 10px', borderRadius: 5, fontSize: 11, fontWeight: 700,
                background: `${statusColor}18`, color: statusColor }}>
                {customer.status?.toUpperCase()}
              </span>
              {customer.sourceApp && (
                <span style={{ padding: '2px 10px', borderRadius: 5, fontSize: 11, fontWeight: 600,
                  background: 'var(--color-surface-2)', color: 'var(--color-text-muted)' }}>
                  {customer.sourceApp}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Two-column layout */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>

          {/* Customer Profile */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 12, padding: 20 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-text-muted)',
              textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 12 }}>
              Profile
            </div>
            <InfoRow label="Email"    value={customer.email} />
            <InfoRow label="Phone"    value={customer.phone} />
            <InfoRow label="Address"  value={customer.address} />
            <InfoRow label="Ext. Ref" value={customer.externalRefId} />
            <InfoRow label="Created"  value={customer.createdAt
              ? new Date(customer.createdAt).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
              : undefined} />
          </div>

          {/* Payment */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 12, padding: 20 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-text-muted)',
              textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 12 }}>
              Payment
            </div>
            {payment ? (
              <>
                <InfoRow label="Amount"    value={`${payment.currency ?? 'NGN'} ${Number(payment.amount ?? 0).toLocaleString()}`} />
                <InfoRow label="Status"    value={
                  <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700,
                    background: `${PAYMENT_COLOR[payment.status] ?? '#94a3b8'}18`,
                    color: PAYMENT_COLOR[payment.status] ?? '#94a3b8' }}>
                    {payment.status?.toUpperCase()}
                  </span>
                } />
                <InfoRow label="Expires"   value={payment.expiresAt
                  ? new Date(payment.expiresAt).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
                  : undefined} />
                {payment.paymentLink && (
                  <div style={{ marginTop: 12 }}>
                    <a href={payment.paymentLink} target="_blank" rel="noreferrer"
                      style={{ fontSize: 11, color: '#0ea5e9', fontWeight: 600, textDecoration: 'none' }}>
                      Open Payment Link →
                    </a>
                  </div>
                )}
              </>
            ) : (
              <div style={{ fontSize: 12, color: 'var(--color-text-muted)', padding: '12px 0' }}>
                No payment request on file.
              </div>
            )}
          </div>
        </div>

        {/* Linked Projects */}
        {projects.length > 0 && (
          <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 12, padding: 20, marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-text-muted)',
              textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 12 }}>
              Linked Projects
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {projects.map((p: any) => (
                <div key={p.id}
                  onClick={() => navigate(`/projects/${p.id}/pipeline`)}
                  style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '10px 12px', borderRadius: 8, border: '1px solid var(--color-border)',
                    cursor: 'pointer', background: 'var(--color-surface)',
                    transition: 'background .12s' }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'rgba(14,165,233,.06)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'var(--color-surface)')}
                >
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-primary)' }}>
                      {p.name}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>{p.ticketNumber}</div>
                  </div>
                  <span style={{ padding: '2px 8px', borderRadius: 5, fontSize: 10, fontWeight: 700,
                    background: 'rgba(14,165,233,.1)', color: '#0ea5e9' }}>
                    {p.pipelineStatus?.replace(/_/g, ' ').toUpperCase()}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Field Submission */}
        <FieldSubmissionPanel customerId={id!} />

        {/* Dynamic Forms (Form Builder schemas attached to this customer) */}
        <DynamicFormsPanel customerId={id!} />
      </div>
    </div>
  );
}
