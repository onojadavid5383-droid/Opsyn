// ============================================================
// OPSYN — Customers  /customers
// Customer profiles and the onboarding pipeline. Status is a URL tab
// (?status=active), source a filter in the table toolbar; CSV export honours
// both. New customers are created in a glass dialog.
// ============================================================

import { Download, Plus } from 'lucide-react';
import { useId, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { customersApi } from '../../api/customers.api';
import { GlassSelect } from '../../components/glass';
import { Page, PageHeader } from '../../components/layout/Page';
import { Badge, Button, DataTable, Input, Modal, Select, Tabs, type BadgeTone, type Column } from '../../components/ui';
import { useToast } from '../../components/ui/Toast';
import { useCreateCustomer, useCustomers } from '../../hooks/useCustomers';
import { useUrlParam } from '../../hooks/useUrlTab';
import s from './Customers.module.css';

const STATUSES = ['all', 'pending', 'active', 'suspended', 'churned'] as const;
type StatusFilter = typeof STATUSES[number];

const STATUS_META: Record<string, { label: string; tone: BadgeTone }> = {
  pending:   { label: 'Pending',   tone: 'warning' },
  active:    { label: 'Active',    tone: 'ok' },
  suspended: { label: 'Suspended', tone: 'critical' },
  churned:   { label: 'Churned',   tone: 'neutral' },
};

const SOURCE_LABELS: Record<string, string> = {
  field_tech:       'Field tech',
  hr:               'HR',
  sales:            'Sales',
  coverage_checker: 'Coverage checker',
  manual:           'Manual',
};
const SOURCE_OPTIONS = Object.entries(SOURCE_LABELS).map(([value, label]) => ({ value, label }));

const PAGE_SIZE = 50;

// ── Create customer dialog ────────────────────────────────────

const EMPTY = { first_name: '', last_name: '', email: '', phone: '', address: '', source_app: 'manual', amount: '', currency: 'NGN' };

function CreateCustomerModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const create = useCreateCustomer();
  const formId = useId();
  const [form, setForm] = useState(EMPTY);
  const [tried, setTried] = useState(false);
  const set = (k: keyof typeof EMPTY, v: string) => setForm(p => ({ ...p, [k]: v }));

  const close = () => { setForm(EMPTY); setTried(false); onClose(); };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (!form.first_name.trim() || !form.last_name.trim()) return;
    try {
      await create.mutateAsync({
        first_name: form.first_name.trim(),
        last_name:  form.last_name.trim(),
        email:      form.email || undefined,
        phone:      form.phone || undefined,
        address:    form.address || undefined,
        source_app: form.source_app,
        amount:     form.amount ? parseFloat(form.amount) : 0,
        currency:   form.currency,
      });
      toast.success('Customer created');
      close();
    } catch (err: any) {
      toast.error("Couldn't create the customer", err?.response?.data?.detail ?? String(err));
    }
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title="New customer"
      footer={
        <>
          <Button variant="secondary" type="button" onClick={close}>Cancel</Button>
          <Button variant="primary" type="submit" form={formId} loading={create.isPending}>Create customer</Button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} className={s.form} noValidate>
        <div className={s.row2}>
          <Input label="First name" required value={form.first_name} onChange={v => set('first_name', v)} placeholder="Jane"
            error={tried && !form.first_name.trim() ? 'Enter a first name' : undefined} autoComplete="off" />
          <Input label="Last name" required value={form.last_name} onChange={v => set('last_name', v)} placeholder="Doe"
            error={tried && !form.last_name.trim() ? 'Enter a last name' : undefined} autoComplete="off" />
        </div>
        <div className={s.row2}>
          <Input label="Email" type="email" value={form.email} onChange={v => set('email', v)} placeholder="jane@example.com" autoComplete="off" />
          <Input label="Phone" type="tel" value={form.phone} onChange={v => set('phone', v)} placeholder="+234…" autoComplete="off" />
        </div>
        <Input label="Address" value={form.address} onChange={v => set('address', v)} placeholder="Street, city" autoComplete="off" />
        <div className={s.row3}>
          <Select label="Source" value={form.source_app} onChange={v => set('source_app', v)} options={SOURCE_OPTIONS} />
          <Input label="Amount" type="number" min="0" inputMode="decimal" value={form.amount} onChange={v => set('amount', v)} placeholder="0" />
          <Select label="Currency" value={form.currency} onChange={v => set('currency', v)}
            options={['NGN', 'USD', 'GBP'].map(c => ({ value: c, label: c }))} />
        </div>
      </form>
    </Modal>
  );
}

// ── Page ──────────────────────────────────────────────────────

interface CustomerRow {
  id: string; fullName?: string; firstName?: string; lastName?: string; externalRefId?: string;
  email?: string; phone?: string; status?: string; sourceApp?: string; createdAt?: string;
}

export default function CustomersPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [status, setStatus] = useUrlParam<StatusFilter>('status', STATUSES, 'all');
  const [sourceApp, setSourceApp] = useState('');
  const [page, setPage] = useState(1);
  const [showCreate, setShowCreate] = useState(false);
  const [exporting, setExporting] = useState(false);

  const filters = { status: status === 'all' ? undefined : status, source_app: sourceApp || undefined };
  const { data, isLoading, isError } = useCustomers({ ...filters, page, page_size: PAGE_SIZE });
  const customers: CustomerRow[] = (data as { data?: CustomerRow[] } | undefined)?.data ?? [];
  const hasMore = customers.length === PAGE_SIZE;

  const exportCsv = async () => {
    setExporting(true);
    try {
      const res = await customersApi.exportCsv(filters);
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'customers.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Couldn't export customers");
    } finally {
      setExporting(false);
    }
  };

  const columns = useMemo<Column<CustomerRow>[]>(() => [
    {
      key: 'fullName', header: 'Customer', mobile: 'title', hideable: false,
      render: (_v, c) => (
        <span className={s.stackCell}>
          <span className={s.name}>{c.fullName ?? `${c.firstName ?? ''} ${c.lastName ?? ''}`.trim()}</span>
          {c.externalRefId && <span className={s.sub}>Ref <span className={s.mono}>{c.externalRefId}</span></span>}
        </span>
      ),
    },
    {
      key: 'email', header: 'Contact',
      render: (_v, c) => (
        <span className={s.stackCell}>
          <span>{c.email ?? '—'}</span>
          {c.phone && <span className={s.sub}>{c.phone}</span>}
        </span>
      ),
    },
    {
      key: 'status', header: 'Status', width: 130,
      render: (_v, c) => {
        const m = STATUS_META[c.status ?? ''];
        return m ? <Badge tone={m.tone} size="sm" dot>{m.label}</Badge> : (c.status ?? '—');
      },
    },
    { key: 'sourceApp', header: 'Source', width: 160, render: (_v, c) => SOURCE_LABELS[c.sourceApp ?? ''] ?? c.sourceApp ?? '—' },
    {
      key: 'createdAt', header: 'Created', width: 130, numeric: true,
      render: (_v, c) => (c.createdAt ? new Date(c.createdAt).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'),
    },
  ], []);

  return (
    <Page>
      <PageHeader
        title="Customers"
        lede="Customer profiles and the onboarding pipeline"
        primary={<Button variant="primary" size="sm" leftIcon={<Plus size={16} aria-hidden="true" />} onClick={() => setShowCreate(true)}>New customer</Button>}
        secondary={[{ id: 'export', label: exporting ? 'Exporting…' : 'Export CSV', icon: <Download size={16} aria-hidden="true" />, onSelect: exportCsv, disabled: exporting }]}
      />

      <Tabs
        label="Customer status"
        value={status}
        onChange={v => { setStatus(v); setPage(1); }}
        idPrefix="customer-status"
        items={STATUSES.map(v => ({ value: v, label: v === 'all' ? 'All' : STATUS_META[v].label }))}
      />

      <div role="tabpanel" id="customer-status-panel" aria-labelledby={`customer-status-tab-${status}`}>
        <DataTable
          caption="Customers"
          columns={columns}
          data={customers}
          rowKey={c => c.id}
          rowLabel={c => c.fullName ?? `${c.firstName ?? ''} ${c.lastName ?? ''}`}
          isLoading={isLoading}
          onRowClick={c => navigate(`/customers/${c.id}`)}
          viewKey="customers"
          toolbar={
            <GlassSelect
              ariaLabel="Filter by source"
              compact
              value={sourceApp}
              onChange={v => { setSourceApp(v); setPage(1); }}
              options={[{ value: '', label: 'All sources' }, ...SOURCE_OPTIONS]}
              style={{ width: 190 }}
            />
          }
          emptyTitle={isError ? "Customers couldn't load" : 'No customers found'}
          emptyMessage={isError ? 'Check your connection and try again.' : 'Change the filters, or add a new customer.'}
        />
      </div>

      {!isLoading && (hasMore || page > 1) && (
        <nav className={s.pager} aria-label="Customer pages">
          <Button variant="secondary" size="sm" disabled={page === 1} onClick={() => setPage(p => p - 1)}>Previous</Button>
          <span className={s.sub} aria-current="page">Page {page}</span>
          <Button variant="secondary" size="sm" disabled={!hasMore} onClick={() => setPage(p => p + 1)}>Next</Button>
        </nav>
      )}

      <CreateCustomerModal open={showCreate} onClose={() => setShowCreate(false)} />
    </Page>
  );
}
