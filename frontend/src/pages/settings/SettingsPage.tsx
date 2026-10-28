// ============================================================
// OPSYN — SettingsPage  (Stage 5 redesign)
// ============================================================

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { settingsApi, webhooksApi } from '../../api/index';
import type { OutageNotificationRule } from '@shared';
import { useUIStore } from '../../store/ui.store';
import { Button, Badge, Modal, Input, Select } from '../../components/ui';
import type { ApiError } from '../../api/client';
import { useUrlTab } from '../../hooks/useUrlTab';
import { Page, PageHeader } from '../../components/layout/Page';
import { GlassModal, GlassSelect } from '../../components/glass';

function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, message?: string) => addToast({ type: 'success', title, message }),
    error:   (title: string, message?: string) => addToast({ type: 'error',   title, message }),
    info:    (title: string, message?: string) => addToast({ type: 'info',    title, message }),
  };
}

type SettingsTab = 'org' | 'departments' | 'roles' | 'regions' | 'pipelines' | 'integrations' | 'webhooks' | 'notification-rules';

// Config field definitions for the 4 configurable integrations
const INTEGRATION_FIELDS: Record<string, { label: string; field: string; type?: string; placeholder?: string }[]> = {
  slack:      [{ label: 'Webhook URL', field: 'webhook_url', placeholder: 'https://hooks.slack.com/services/…' }, { label: 'Default Channel', field: 'channel', placeholder: '#alerts' }],
  teams:      [{ label: 'Webhook URL', field: 'webhook_url', placeholder: 'https://outlook.office.com/webhook/…' }],
  pagerduty:  [{ label: 'API Key', field: 'api_key', type: 'password', placeholder: 'pd_api_key_…' }, { label: 'Service ID', field: 'service_id', placeholder: 'P1234AB' }],
  email_smtp: [
    { label: 'SMTP Host', field: 'host', placeholder: 'smtp.example.com' },
    { label: 'SMTP Port', field: 'port', placeholder: '587' },
    { label: 'Username', field: 'username', placeholder: 'alerts@example.com' },
    { label: 'Password', field: 'password', type: 'password', placeholder: '••••••••' },
    { label: 'From Email', field: 'from_email', placeholder: 'noreply@example.com' },
  ],
};

const TABS: { key: SettingsTab; label: string }[] = [
  { key: 'org',                label: 'Organisation' },
  { key: 'departments',        label: 'Departments' },
  { key: 'roles',              label: 'Roles' },
  { key: 'regions',            label: 'Regions' },
  { key: 'pipelines',          label: 'Pipelines' },
  { key: 'integrations',       label: 'Integrations' },
  { key: 'webhooks',           label: 'Webhooks' },
  { key: 'notification-rules', label: 'Notification rules' },
];

const SECTION_LEDE: Record<SettingsTab, string> = {
  'org':                'Tenant profile, branding and time zone',
  'departments':        'Department structure and what each department can use',
  'roles':              'Roles and their access levels',
  'regions':            'Operating regions for sites, staff and reporting',
  'pipelines':          'Task and project pipelines and their stages',
  'integrations':       'SmartOLT, email and other connected services',
  'webhooks':           'Outgoing webhooks and signing secrets',
  'notification-rules': 'Who is notified about which events',
};

const ROLE_LEVEL_VARIANT: Record<number, any> = {
  5: 'critical',
  4: 'warning',
  3: 'resolved',
  2: 'info',
  1: 'info',
};

const INTEGRATION_CAT_COLOR: Record<string, string> = {
  messaging:  'var(--color-teal)',
  project:    'var(--color-indigo)',
  alerting:   'var(--color-red)',
  email:      'var(--color-amber)',
  auth:       'var(--color-green)',
  automation: 'var(--color-text-primary)',
};

const INTEGRATION_CAT_BG: Record<string, string> = {
  messaging:  'rgba(0,194,168,.1)',
  project:    'rgba(79,70,229,.1)',
  alerting:   'rgba(220,38,38,.1)',
  email:      'rgba(245,158,11,.1)',
  auth:       'rgba(22,163,74,.1)',
  automation: 'rgba(13,27,42,.06)',
};

const TH: React.CSSProperties = {
  textAlign: 'left', fontSize: 9, fontWeight: 700, letterSpacing: '.1em',
  textTransform: 'uppercase', color: 'var(--color-text-muted)',
  padding: '9px 16px', borderBottom: '1px solid var(--color-border)',
};
const TD: React.CSSProperties = { padding: '11px 16px', borderBottom: '1px solid var(--color-border)' };

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-card)', padding: 16, ...style }}>
      {children}
    </div>
  );
}

function SectionHeader({ title, sub, action, onAction }: { title: string; sub?: string; action?: string; onAction?: () => void }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
      <div>
        <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 14, color: 'var(--color-text-primary)' }}>{title}</div>
        {sub && <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 2 }}>{sub}</div>}
      </div>
      {action && onAction && (
        <Button variant="ghost" size="xs" onClick={onAction}>{action}</Button>
      )}
    </div>
  );
}

export default function SettingsPage() {
  const qc    = useQueryClient();
  const toast = useToast();

  // In the URL (?tab=…) so navigation links like /settings?tab=webhooks open the right tab
  const [tab]                                 = useUrlTab<SettingsTab>(TABS.map(t => t.key), 'org');
  const [expandedDept, setExpandedDept]       = useState<string | null>(null);
  const [deptModal, setDeptModal]             = useState(false);
  const [roleModal, setRoleModal]             = useState(false);
  const [regionModal, setRegionModal]         = useState(false);
  const [pipelineModal, setPipelineModal]     = useState(false);
  const [deptForm, setDeptForm]               = useState({ name: '', parent_id: '' });
  const [roleForm, setRoleForm]               = useState({ name: '', level: '2', description: '' });
  const [regionForm, setRegionForm]           = useState({ name: '', code: '', parent_id: '' });
  const [pipelineForm, setPipelineForm]       = useState({ name: '', description: '' });
  const [orgForm, setOrgForm]                 = useState({ name: '', timezone: '' });
  const [orgEditMode, setOrgEditMode]         = useState(false);
  const [featureMinLevel] = useState<Record<string, number>>({});
  const [webhookKeyModal, setWebhookKeyModal] = useState(false);
  const [webhookApp, setWebhookApp]           = useState('sales');
  const [createdSecret, setCreatedSecret]     = useState<{ app_name: string; secret_key: string } | null>(null);
  const [secretCopied, setSecretCopied]       = useState(false);
  const [ruleModal, setRuleModal]             = useState(false);
  const [editRule, setEditRule]               = useState<any | null>(null);
  const [configModal, setConfigModal]         = useState<{ key: string; name: string } | null>(null);
  const [configForm, setConfigForm]           = useState<Record<string, string>>({});
  const [ruleForm, setRuleForm]               = useState<{
    name: string;
    min_severity: OutageNotificationRule['min_severity'];
    min_subscribers: string;
    channels: OutageNotificationRule['channels'];
    message_template: string;
    is_auto: boolean;
    is_active: boolean;
  }>({
    name: '', min_severity: 'warning', min_subscribers: '0',
    channels: [], message_template: '', is_auto: true, is_active: true,
  });

  const { data: existingConfig }  = useQuery({
    queryKey: ['settings', 'integration-config', configModal?.key],
    queryFn:  () => settingsApi.getIntegrationConfig(configModal!.key),
    enabled:  !!configModal?.key && !!INTEGRATION_FIELDS[configModal.key],
  });

  const { data: org,          isLoading: orgLoading }          = useQuery({ queryKey: ['settings', 'org'],                queryFn: () => settingsApi.getOrg() });
  const { data: depts = [] }                                   = useQuery({ queryKey: ['settings', 'departments'],        queryFn: () => settingsApi.getDepartments() });
  const { data: roles = [],   isLoading: rolesLoading }        = useQuery({ queryKey: ['settings', 'roles'],              queryFn: () => settingsApi.getRoles() });
  const { data: regions = [], isLoading: regionsLoading }      = useQuery({ queryKey: ['settings', 'regions'],            queryFn: () => settingsApi.getRegions() });
  const { data: allFeatures = [] }                             = useQuery({ queryKey: ['settings', 'feature-permissions'], queryFn: () => settingsApi.getFeaturePermissions() });
  const { data: pipelines = [], isLoading: pipelinesLoading }  = useQuery({ queryKey: ['settings', 'pipelines'],          queryFn: () => settingsApi.getPipelines(),          enabled: tab === 'pipelines' });
  const { data: integrations = [], isLoading: integrationsLoading, isError: integrationsError, refetch: refetchIntegrations } = useQuery({ queryKey: ['settings', 'integrations'], queryFn: () => settingsApi.getIntegrations(), enabled: tab === 'integrations', retry: 1 });
  const { data: webhookKeys = [], isLoading: webhookKeysLoading }   = useQuery({ queryKey: ['settings', 'webhook-keys'], queryFn: () => webhooksApi.listKeys(),               enabled: tab === 'webhooks' });
  const { data: notifRules = [], isLoading: notifRulesLoading }     = useQuery({ queryKey: ['settings', 'notification-rules'], queryFn: () => settingsApi.getNotificationRules(), enabled: tab === 'notification-rules' });
  const { data: deptFeatures = [] }                            = useQuery({
    queryKey: ['settings', 'dept-features', expandedDept],
    queryFn:  () => expandedDept ? settingsApi.getDeptFeatures(expandedDept) : Promise.resolve([]),
    enabled:  !!expandedDept,
  });

  const updateOrg = useMutation({
    mutationFn: () => settingsApi.updateOrg({ name: orgForm.name || undefined, timezone: orgForm.timezone || undefined }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings', 'org'] }); toast.success('Organisation updated'); setOrgEditMode(false); },
    onError: () => toast.error('Failed to update organisation'),
  });
  const createDept = useMutation({
    mutationFn: () => settingsApi.createDepartment({ name: deptForm.name, parent_id: deptForm.parent_id || undefined }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings', 'departments'] }); toast.success('Department created'); setDeptModal(false); setDeptForm({ name: '', parent_id: '' }); },
    onError: () => toast.error('Failed to create department'),
  });
  const deleteDept = useMutation({
    mutationFn: (id: string) => settingsApi.deleteDepartment(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings', 'departments'] }); toast.success('Department removed'); },
    onError: (e: ApiError) => toast.error('Cannot delete', e?.response?.data?.detail ?? 'Department may have active staff'),
  });
  const grantFeature = useMutation({
    mutationFn: ({ deptId, key, level }: { deptId: string; key: string; level: number }) => settingsApi.grantDeptFeature(deptId, key, level),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings', 'dept-features', expandedDept] }); toast.success('Feature updated'); },
    onError: () => toast.error('Failed to update feature'),
  });
  const revokeFeature = useMutation({
    mutationFn: ({ deptId, key }: { deptId: string; key: string }) => settingsApi.revokeDeptFeature(deptId, key),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings', 'dept-features', expandedDept] }); toast.success('Feature revoked'); },
    onError: () => toast.error('Failed to revoke feature'),
  });
  const createRole = useMutation({
    mutationFn: () => settingsApi.createRole({ name: roleForm.name, level: Number(roleForm.level), description: roleForm.description || undefined }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings', 'roles'] }); toast.success('Role created'); setRoleModal(false); setRoleForm({ name: '', level: '2', description: '' }); },
    onError: () => toast.error('Failed to create role'),
  });
  const createRegion = useMutation({
    mutationFn: () => settingsApi.createRegion({ name: regionForm.name, code: regionForm.code, parent_id: regionForm.parent_id || undefined }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings', 'regions'] }); toast.success('Region created'); setRegionModal(false); setRegionForm({ name: '', code: '', parent_id: '' }); },
    onError: () => toast.error('Failed to create region'),
  });
  const createPipeline = useMutation({
    mutationFn: () => settingsApi.createPipeline({ name: pipelineForm.name, description: pipelineForm.description || undefined }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings', 'pipelines'] }); toast.success('Pipeline template created'); setPipelineModal(false); setPipelineForm({ name: '', description: '' }); },
    onError: () => toast.error('Failed to create pipeline'),
  });
  const createWebhookKey = useMutation({
    mutationFn: () => webhooksApi.createKey(webhookApp),
    onSuccess: (data: any) => { qc.invalidateQueries({ queryKey: ['settings', 'webhook-keys'] }); setWebhookKeyModal(false); setCreatedSecret({ app_name: data.app_name, secret_key: data.secret_key }); setSecretCopied(false); },
    onError: () => toast.error('Failed to create webhook key'),
  });
  const deactivateWebhookKey = useMutation({
    mutationFn: (keyId: string) => webhooksApi.deactivateKey(keyId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings', 'webhook-keys'] }); toast.success('Webhook key revoked'); },
    onError: () => toast.error('Failed to revoke key'),
  });

  const openNewRule = () => { setEditRule(null); setRuleForm({ name: '', min_severity: 'warning', min_subscribers: '0', channels: [], message_template: '', is_auto: true, is_active: true }); setRuleModal(true); };
  const openEditRule = (r: any) => { setEditRule(r); setRuleForm({ name: r.name, min_severity: r.min_severity, min_subscribers: String(r.min_subscribers), channels: r.channels ?? [], message_template: r.message_template ?? '', is_auto: r.is_auto, is_active: r.is_active }); setRuleModal(true); };
  const toggleChannel = (ch: OutageNotificationRule['channels'][number]) => setRuleForm(f => ({ ...f, channels: f.channels.includes(ch) ? f.channels.filter(c => c !== ch) : [...f.channels, ch] }));

  const saveRule = useMutation({
    mutationFn: () => {
      const payload = { name: ruleForm.name, min_severity: ruleForm.min_severity, min_subscribers: Number(ruleForm.min_subscribers), channels: ruleForm.channels, message_template: ruleForm.message_template || undefined, is_auto: ruleForm.is_auto, is_active: ruleForm.is_active };
      return editRule ? settingsApi.updateNotificationRule(editRule.id, payload) : settingsApi.createNotificationRule(payload);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings', 'notification-rules'] }); toast.success(editRule ? 'Rule updated' : 'Rule created'); setRuleModal(false); },
    onError: () => toast.error('Failed to save rule'),
  });
  const deleteRule = useMutation({
    mutationFn: (id: string) => settingsApi.deleteNotificationRule(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings', 'notification-rules'] }); toast.success('Rule deleted'); },
    onError: () => toast.error('Failed to delete rule'),
  });
  const testRule = useMutation({
    mutationFn: (id: string) => settingsApi.testNotificationRule(id),
    onSuccess: () => toast.success('Test notification sent'),
    onError: () => toast.error('Test failed — check rule configuration'),
  });

  const saveConfig = useMutation({
    mutationFn: () => settingsApi.saveIntegrationConfig(configModal!.key, configForm),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings', 'integrations'] });
      qc.invalidateQueries({ queryKey: ['settings', 'integration-config', configModal?.key] });
      toast.success(`${configModal?.name} configured`);
      setConfigModal(null);
    },
    onError: () => toast.error('Failed to save configuration'),
  });

  const openConfig = (integration: any) => {
    setConfigModal({ key: integration.key, name: integration.name });
    setConfigForm({});
  };

  const grantedMap: Record<string, number> = Object.fromEntries((deptFeatures as any[]).map((f: any) => [f.feature_key, f.min_role_level]));
  const o = org as any;

  const deptArr   = depts as any[];
  const rootDepts = deptArr.filter((d: any) => !d.parent_id);
  const childDepts = (parentId: string) => deptArr.filter((d: any) => d.parent_id === parentId);

  const featuresByModule = (): Record<string, any[]> => {
    const grouped: Record<string, any[]> = {};
    (allFeatures as any[]).forEach((f: any) => {
      const mod = f.module ?? 'Other';
      if (!grouped[mod]) grouped[mod] = [];
      grouped[mod].push(f);
    });
    return grouped;
  };

  const SEV_COLOR: Record<string, string> = { critical: 'var(--color-red)', high: 'var(--color-amber)', warning: 'var(--color-teal)', low: 'var(--color-text-muted)' };

  return (
    <Page>
      {/* Sections are switched from the section menu (or the section tabs on
          tablets and phones), so the page names where you are instead of
          repeating the same list as a second tab bar */}
      <PageHeader
        title={TABS.find(x => x.key === tab)?.label ?? 'Settings'}
        lede={SECTION_LEDE[tab]}
      />

      {/* ── Organisation ── */}
      {tab === 'org' && (
        <div style={{ maxWidth: 560 }}>
          <Card style={{ padding: 20 }}>
            <SectionHeader
              title="Organisation Profile"
              sub="Tenant-level settings and branding"
              action={orgEditMode ? undefined : 'Edit'}
              onAction={() => { setOrgForm({ name: o?.name ?? '', timezone: o?.settings?.timezone ?? '' }); setOrgEditMode(true); }}
            />
            {orgLoading ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>Loading…</div> : (
              orgEditMode ? (
                <>
                  <Input label="Organisation Name" value={orgForm.name} onChange={v => setOrgForm(f => ({ ...f, name: v }))} placeholder={o?.name} />
                  <Input label="Timezone" value={orgForm.timezone} onChange={v => setOrgForm(f => ({ ...f, timezone: v }))} placeholder="e.g. Africa/Lagos" />
                  <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                    <Button variant="secondary" onClick={() => setOrgEditMode(false)}>Cancel</Button>
                    <Button variant="primary" onClick={() => updateOrg.mutate()} disabled={updateOrg.isPending} loading={updateOrg.isPending}>Save Changes</Button>
                  </div>
                </>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {[
                    { label: 'Name',      value: o?.name },
                    { label: 'Slug',      value: o?.slug },
                    { label: 'Plan',      value: o?.plan },
                    { label: 'Max Users', value: String(o?.max_users ?? '—') },
                    { label: 'Status',    value: o?.is_active ? 'Active' : 'Suspended' },
                    { label: 'Timezone',  value: o?.settings?.timezone ?? 'UTC' },
                    { label: 'Logo URL',  value: o?.settings?.brand?.logo_url ?? o?.settings?.logo_url ?? '—' },
                  ].map(row => (
                    <div key={row.label} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0', borderBottom: '1px solid var(--color-border)' }}>
                      <span style={{ fontSize: 11, color: 'var(--color-text-muted)', width: 96, flexShrink: 0 }}>{row.label}</span>
                      <span style={{ fontSize: 12, color: 'var(--color-text-primary)', fontWeight: 500 }}>{row.value ?? '—'}</span>
                    </div>
                  ))}
                </div>
              )
            )}
          </Card>
        </div>
      )}

      {/* ── Departments ── */}
      {tab === 'departments' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 14, color: 'var(--color-text-primary)' }}>
              Departments <span style={{ fontSize: 11, color: 'var(--color-text-muted)', fontWeight: 400 }}>({deptArr.length})</span>
            </div>
            <Button variant="primary" size="sm" onClick={() => setDeptModal(true)}>+ New Department</Button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {rootDepts.length === 0 && deptArr.length === 0 && (
              <div style={{ textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 12, padding: 32 }}>
                No departments yet. Create your first department.
              </div>
            )}
            {rootDepts.map((d: any) => {
              const children = childDepts(d.id);
              const isExp    = expandedDept === d.id;
              const grouped  = isExp ? featuresByModule() : {};
              return (
                <div key={d.id} style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-card)', overflow: 'hidden' }}>
                  <div
                    style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', cursor: 'pointer' }}
                    onClick={() => setExpandedDept(isExp ? null : d.id)}
                  >
                    <div style={{ fontSize: 16, color: 'var(--color-text-muted)', transform: isExp ? 'rotate(90deg)' : 'none', transition: 'transform .2s', userSelect: 'none' }}>›</div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--color-text-primary)' }}>{d.name}</div>
                      {children.length > 0 && <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 1 }}>{children.length} sub-department{children.length !== 1 ? 's' : ''}</div>}
                    </div>
                    <Button variant="danger" size="xs"
                      onClick={(e: any) => { e.stopPropagation(); deleteDept.mutate(d.id); }}
                      disabled={deleteDept.isPending}
                    >
                      Remove
                    </Button>
                  </div>

                  {isExp && children.map((c: any) => (
                    <div key={c.id} style={{ marginLeft: 32, borderTop: '1px solid var(--color-border)', padding: '8px 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div style={{ fontSize: 11, color: 'var(--color-text-muted)', fontWeight: 500 }}>↳ {c.name}</div>
                      <Button variant="danger" size="xs" onClick={() => deleteDept.mutate(c.id)} disabled={deleteDept.isPending} style={{ marginLeft: 'auto' }}>Remove</Button>
                    </div>
                  ))}

                  {isExp && (
                    <div style={{ borderTop: '1px solid var(--color-border)', padding: '12px 16px' }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-text-muted)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '.08em' }}>
                        Feature Access
                      </div>
                      {Object.keys(grouped).length === 0
                        ? <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>No features defined</div>
                        : Object.entries(grouped).map(([mod, features]) => (
                          <div key={mod} style={{ marginBottom: 14 }}>
                            <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-teal)', textTransform: 'uppercase', letterSpacing: '.12em', marginBottom: 6 }}>{mod}</div>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                              {(features as any[]).map((f: any) => {
                                const grantedLevel = grantedMap[f.feature_key];
                                const granted      = grantedLevel !== undefined;
                                const minLevel     = featureMinLevel[f.feature_key] ?? 1;
                                return (
                                  <div key={f.feature_key} style={{
                                    display: 'flex', alignItems: 'center', gap: 4,
                                    padding: '4px 8px', borderRadius: 6, fontSize: 11,
                                    background: granted ? 'rgba(22,163,74,.1)' : 'var(--color-surface-2)',
                                    border: `1px solid ${granted ? 'rgba(22,163,74,.3)' : 'var(--color-border)'}`,
                                  }}>
                                    <button
                                      onClick={() => granted
                                        ? revokeFeature.mutate({ deptId: d.id, key: f.feature_key })
                                        : grantFeature.mutate({ deptId: d.id, key: f.feature_key, level: minLevel })
                                      }
                                      title={f.description ?? f.feature_label}
                                      style={{
                                        background: 'none', border: 'none', cursor: 'pointer',
                                        color: granted ? 'var(--color-green)' : 'var(--color-text-muted)',
                                        fontWeight: 600, fontSize: 11, fontFamily: 'var(--font-body)', padding: 0,
                                      }}
                                    >
                                      {granted ? '✓ ' : ''}{f.feature_label}
                                    </button>
                                    {granted && (
                                      <GlassSelect value={String(grantedLevel)} onChange={v => { const l = Number(v); grantFeature.mutate({ deptId: d.id, key: f.feature_key, level: l }); }} options={[...[1, 2, 3, 4, 5].map((l) => ({ value: String(l), label: `L${l}+` }))]} ariaLabel={`Minimum role level for ${f.feature_label}`} compact />
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        ))
                      }
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Roles ── */}
      {tab === 'roles' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 14, color: 'var(--color-text-primary)' }}>
              Roles <span style={{ fontSize: 11, color: 'var(--color-text-muted)', fontWeight: 400 }}>({(roles as any[]).length})</span>
            </div>
            <Button variant="primary" size="sm" onClick={() => setRoleModal(true)}>+ New Role</Button>
          </div>
          {rolesLoading ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>Loading…</div> : (
            <Card style={{ padding: 0 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr>{['Role Name', 'Level', 'Type', 'Description'].map(h => <th key={h} style={TH}>{h}</th>)}</tr></thead>
                <tbody>
                  {(roles as any[]).map((r: any) => (
                    <tr key={r.id}>
                      <td style={{ ...TD, fontWeight: 600, fontSize: 12, color: 'var(--color-text-primary)' }}>{r.name}</td>
                      <td style={TD}>
                        <Badge variant={ROLE_LEVEL_VARIANT[r.level as number] ?? 'info'} size="sm">{r.level}</Badge>
                      </td>
                      <td style={TD}>
                        <Badge variant={r.is_system_role ? 'info' : 'warning'} size="sm">{r.is_system_role ? 'System' : 'Custom'}</Badge>
                      </td>
                      <td style={{ ...TD, fontSize: 11, color: 'var(--color-text-muted)' }}>{r.description ?? '—'}</td>
                    </tr>
                  ))}
                  {(roles as any[]).length === 0 && (
                    <tr><td colSpan={4} style={{ textAlign: 'center', padding: 40, color: 'var(--color-text-muted)', fontSize: 12 }}>No roles defined</td></tr>
                  )}
                </tbody>
              </table>
            </Card>
          )}
        </div>
      )}

      {/* ── Regions ── */}
      {tab === 'regions' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 14, color: 'var(--color-text-primary)' }}>
              Regions <span style={{ fontSize: 11, color: 'var(--color-text-muted)', fontWeight: 400 }}>({(regions as any[]).length})</span>
            </div>
            <Button variant="primary" size="sm" onClick={() => setRegionModal(true)}>+ New Region</Button>
          </div>
          {regionsLoading ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>Loading…</div> : (
            <Card style={{ padding: 0 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr>{['Region Name', 'Code', 'Parent', ''].map(h => <th key={h} style={TH}>{h}</th>)}</tr></thead>
                <tbody>
                  {(regions as any[]).map((r: any) => {
                    const parent = (regions as any[]).find((x: any) => x.id === r.parent_id);
                    return (
                      <tr key={r.id}>
                        <td style={{ ...TD, fontWeight: 600, fontSize: 12, color: 'var(--color-text-primary)' }}>{r.name}</td>
                        <td style={TD}><span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-teal)' }}>{r.code}</span></td>
                        <td style={{ ...TD, fontSize: 11, color: 'var(--color-text-muted)' }}>{parent?.name ?? '—'}</td>
                        <td style={TD} />
                      </tr>
                    );
                  })}
                  {(regions as any[]).length === 0 && (
                    <tr><td colSpan={4} style={{ textAlign: 'center', padding: 40, color: 'var(--color-text-muted)', fontSize: 12 }}>No regions defined</td></tr>
                  )}
                </tbody>
              </table>
            </Card>
          )}
        </div>
      )}

      {/* ── Pipelines ── */}
      {tab === 'pipelines' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 14, color: 'var(--color-text-primary)' }}>
              Pipeline Templates <span style={{ fontSize: 11, color: 'var(--color-text-muted)', fontWeight: 400 }}>({(pipelines as any[]).length})</span>
            </div>
            <Button variant="primary" size="sm" onClick={() => setPipelineModal(true)}>+ New Pipeline</Button>
          </div>
          {pipelinesLoading ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>Loading…</div> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {(pipelines as any[]).map((p: any) => (
                <Card key={p.id} style={{ padding: 16 }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--color-text-primary)' }}>{p.name}</div>
                      {p.description && <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 2 }}>{p.description}</div>}
                    </div>
                    <Badge variant={p.is_active ? 'resolved' : 'warning'} size="sm">{p.is_active ? 'Active' : 'Inactive'}</Badge>
                  </div>
                  {p.stages?.length > 0 && (
                    <div style={{ marginTop: 12, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {p.stages.map((s: any, i: number) => (
                        <span key={s.id} style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, background: 'rgba(0,194,168,.08)', border: '1px solid rgba(0,194,168,.15)', color: 'var(--color-text-primary)' }}>
                          {i + 1}. {s.stage_name}
                        </span>
                      ))}
                    </div>
                  )}
                </Card>
              ))}
              {(pipelines as any[]).length === 0 && (
                <div style={{ textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 12, padding: 32 }}>
                  No pipeline templates. Create one to apply to projects.
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Integrations ── */}
      {tab === 'integrations' && (
        <div>
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 14, color: 'var(--color-text-primary)', marginBottom: 14 }}>
            Available Integrations
          </div>
          {integrationsLoading ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>Loading…</div> : integrationsError ? (
            <div style={{ padding: 20, background: 'rgba(220,38,38,.06)', border: '1px solid rgba(220,38,38,.15)', borderRadius: 10 }}>
              <div style={{ color: 'var(--color-red)', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Unable to load integrations</div>
              <div style={{ color: 'var(--color-text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.5 }}>
                The server could not be reached or returned an error. If this persists after restarting the backend, check server logs.
              </div>
              <button
                onClick={() => refetchIntegrations()}
                style={{
                  padding: '7px 16px', borderRadius: 7, fontSize: 12, fontWeight: 600,
                  border: '1px solid rgba(220,38,38,.3)', background: 'transparent',
                  color: 'var(--color-red)', cursor: 'pointer', fontFamily: 'var(--font-body)',
                }}
              >
                Retry
              </button>
            </div>
          ) : !integrationsLoading && (integrations as any[]).length === 0 ? (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 13, padding: 24, textAlign: 'center' }}>
              No integrations available for this tenant.
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
              {(integrations as any[]).map((i: any) => (
                <Card key={i.key} style={{ padding: 16, opacity: i.status === 'coming_soon' ? 0.6 : 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                    <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--color-text-primary)' }}>{i.name}</div>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      {i.status === 'coming_soon' && (
                        <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 4, background: 'var(--color-surface-2)', color: 'var(--color-text-muted)', fontWeight: 600 }}>Soon</span>
                      )}
                      <span style={{
                        fontSize: 10, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
                        background: INTEGRATION_CAT_BG[i.category] ?? 'rgba(100,116,139,.08)',
                        color:      INTEGRATION_CAT_COLOR[i.category] ?? 'var(--color-text-muted)',
                      }}>
                        {i.category}
                      </span>
                    </div>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--color-text-muted)', lineHeight: 1.5, marginBottom: 12 }}>{i.description}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: i.enabled ? 'var(--color-green)' : 'var(--color-border)' }} />
                    <span style={{ fontSize: 11, color: i.enabled ? 'var(--color-green)' : 'var(--color-text-muted)' }}>{i.enabled ? 'Connected' : 'Not connected'}</span>
                    {i.status !== 'coming_soon' && INTEGRATION_FIELDS[i.key] && (
                      <Button variant="primary" size="xs" style={{ marginLeft: 'auto' }} onClick={() => openConfig(i)}>
                        {i.enabled ? 'Reconfigure' : 'Configure'}
                      </Button>
                    )}
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Webhooks ── */}
      {tab === 'webhooks' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <div>
              <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 14, color: 'var(--color-text-primary)' }}>Webhook API Keys</div>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 2 }}>
                HMAC-SHA256 signed receiver at{' '}
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-teal)' }}>POST /api/v1/webhooks/receive</span>
              </div>
            </div>
            <Button variant="primary" size="sm" onClick={() => setWebhookKeyModal(true)}>+ New Key</Button>
          </div>
          {webhookKeysLoading ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>Loading…</div> : (
            <Card style={{ padding: 0 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr>{['App', 'Created', 'Status', ''].map(h => <th key={h} style={TH}>{h}</th>)}</tr></thead>
                <tbody>
                  {(webhookKeys as any[]).filter((k: any) => k.is_active).map((k: any) => (
                    <tr key={k.id}>
                      <td style={TD}><Badge variant="info" size="sm">{k.app_name}</Badge></td>
                      <td style={{ ...TD, fontSize: 11, color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>{new Date(k.created_at).toLocaleDateString()}</td>
                      <td style={TD}><Badge variant="resolved" size="sm">Active</Badge></td>
                      <td style={{ ...TD, textAlign: 'right' }}>
                        <Button variant="danger" size="xs"
                          onClick={() => { if (confirm(`Revoke ${k.app_name} key?`)) deactivateWebhookKey.mutate(k.id); }}
                          disabled={deactivateWebhookKey.isPending}
                        >
                          Revoke
                        </Button>
                      </td>
                    </tr>
                  ))}
                  {(webhookKeys as any[]).filter((k: any) => k.is_active).length === 0 && (
                    <tr><td colSpan={4} style={{ textAlign: 'center', padding: 40, color: 'var(--color-text-muted)', fontSize: 12 }}>No active webhook keys. Create one to integrate external apps.</td></tr>
                  )}
                </tbody>
              </table>
            </Card>
          )}
          <div style={{ marginTop: 20, padding: 16, background: 'rgba(0,194,168,.05)', borderRadius: 10, border: '1px solid rgba(0,194,168,.15)' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-teal)', marginBottom: 8 }}>Supported Apps</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {['hr', 'finance', 'sales', 'field_tech', 'coverage'].map(a => (
                <span key={a} style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, background: 'var(--color-surface-2)', color: 'var(--color-text-muted)', fontWeight: 600 }}>{a}</span>
              ))}
            </div>
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 10, lineHeight: 1.6 }}>
              Each key is HMAC-SHA256 signed. Send{' '}
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-text-primary)' }}>X-Webhook-App</span>,{' '}
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-text-primary)' }}>X-Webhook-Tenant</span>, and{' '}
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-text-primary)' }}>X-Webhook-Signature: sha256=…</span>{' '}
              headers with every request.
            </div>
          </div>
        </div>
      )}

      {/* ── Notification Rules ── */}
      {tab === 'notification-rules' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
            <div>
              <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 14, color: 'var(--color-text-primary)' }}>Outage Notification Rules</div>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 2 }}>Auto-fire SMS, Email, or WhatsApp alerts when outages match thresholds</div>
            </div>
            <Button variant="primary" size="sm" onClick={openNewRule}>+ New Rule</Button>
          </div>
          {notifRulesLoading ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>Loading…</div> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {(notifRules as any[]).length === 0 && (
                <div style={{ textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 12, padding: 40 }}>
                  No notification rules yet. Create one to auto-alert customers during outages.
                </div>
              )}
              {(notifRules as any[]).map((r: any) => {
                const sc = SEV_COLOR[r.min_severity] ?? 'var(--color-text-muted)';
                return (
                  <Card key={r.id} style={{ padding: 16, opacity: r.is_active ? 1 : 0.55 }}>
                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                          <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--color-text-primary)' }}>{r.name}</span>
                          {r.is_auto && <Badge variant="resolved" size="sm">Auto</Badge>}
                          <Badge variant={r.is_active ? 'resolved' : 'warning'} size="sm">{r.is_active ? 'Active' : 'Inactive'}</Badge>
                        </div>
                        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 11, color: 'var(--color-text-muted)' }}>
                          <span>Min severity: <span style={{ color: sc, fontWeight: 600 }}>{r.min_severity}</span></span>
                          <span>Min subscribers: <span style={{ color: 'var(--color-text-primary)', fontWeight: 600 }}>{r.min_subscribers}</span></span>
                          <span>Channels: {(r.channels ?? []).map((ch: string) => (
                            <Badge key={ch} variant="info" size="sm" style={{ marginLeft: 4 }}>{ch}</Badge>
                          ))}</span>
                        </div>
                        {r.message_template && (
                          <div style={{ marginTop: 8, fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--color-text-muted)', background: 'var(--color-surface-2)', borderRadius: 6, padding: '6px 10px', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
                            {r.message_template}
                          </div>
                        )}
                      </div>
                      <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                        <Button variant="secondary" size="xs" onClick={() => testRule.mutate(r.id)} disabled={testRule.isPending}>Test</Button>
                        <Button variant="secondary" size="xs" onClick={() => openEditRule(r)}>Edit</Button>
                        <Button variant="danger" size="xs" onClick={() => { if (confirm(`Delete rule "${r.name}"?`)) deleteRule.mutate(r.id); }} disabled={deleteRule.isPending}>Delete</Button>
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── Created-secret overlay ── */}
      {createdSecret && (
        <GlassModal open onClose={() => setCreatedSecret(null)} ariaLabel="API key created" size="md">
            <div style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: 16, color: 'var(--color-text-primary)', marginBottom: 4 }}>Webhook Key Created</div>
            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 20 }}>
              App: <Badge variant="info" size="sm">{createdSecret.app_name}</Badge>
            </div>
            <div style={{ padding: 14, background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.25)', borderRadius: 8, marginBottom: 16, fontSize: 11, color: 'var(--color-amber)', lineHeight: 1.5 }}>
              ⚠ Store this secret immediately — it will not be shown again.
            </div>
            <div style={{ fontWeight: 700, fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '.08em' }}>Secret Key</div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'stretch', marginBottom: 20 }}>
              <div style={{ flex: 1, fontFamily: 'var(--font-mono)', fontSize: 12, padding: '10px 12px', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 8, color: 'var(--color-text-primary)', wordBreak: 'break-all', lineHeight: 1.6 }}>
                {createdSecret.secret_key}
              </div>
              <Button variant="secondary" onClick={() => { navigator.clipboard.writeText(createdSecret.secret_key).then(() => setSecretCopied(true)); }}>
                {secretCopied ? 'Copied ✓' : 'Copy'}
              </Button>
            </div>
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 20, lineHeight: 1.6 }}>
              Use as <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-text-primary)' }}>X-Webhook-Signature: sha256=HMAC_SHA256(secret, body)</span> in your integration.
            </div>
            <Button variant="primary" onClick={() => setCreatedSecret(null)} style={{ width: '100%' }}>
              Done — I've saved the secret
            </Button>
          </GlassModal>
      )}

      {/* Modals */}
      <Modal open={deptModal} onClose={() => setDeptModal(false)} title="New Department"
        footer={<><Button variant="secondary" onClick={() => setDeptModal(false)}>Cancel</Button><Button variant="primary" onClick={() => createDept.mutate()} disabled={!deptForm.name || createDept.isPending} loading={createDept.isPending}>Create Department</Button></>}>
        <Input label="Department Name *" value={deptForm.name} onChange={v => setDeptForm(f => ({ ...f, name: v }))} placeholder="e.g. Field Operations" />
        <Select label="Parent Department (optional)" value={deptForm.parent_id} onChange={v => setDeptForm(f => ({ ...f, parent_id: v }))}
          options={[{ label: '— None (root department) —', value: '' }, ...rootDepts.map((d: any) => ({ label: d.name, value: d.id }))]} />
      </Modal>

      <Modal open={roleModal} onClose={() => setRoleModal(false)} title="New Custom Role"
        footer={<><Button variant="secondary" onClick={() => setRoleModal(false)}>Cancel</Button><Button variant="primary" onClick={() => createRole.mutate()} disabled={!roleForm.name || createRole.isPending} loading={createRole.isPending}>Create Role</Button></>}>
        <Input label="Role Name *" value={roleForm.name} onChange={v => setRoleForm(f => ({ ...f, name: v }))} placeholder="e.g. Network Technician" />
        <Select label="Level (1–4)" value={roleForm.level} onChange={v => setRoleForm(f => ({ ...f, level: v }))}
          options={[{ label: '1 — Basic Staff', value: '1' }, { label: '2 — Standard', value: '2' }, { label: '3 — Team Lead', value: '3' }, { label: '4 — Manager', value: '4' }]} />
        <Input label="Description" value={roleForm.description} onChange={v => setRoleForm(f => ({ ...f, description: v }))} placeholder="Optional description" />
      </Modal>

      <Modal open={regionModal} onClose={() => setRegionModal(false)} title="New Region"
        footer={<><Button variant="secondary" onClick={() => setRegionModal(false)}>Cancel</Button><Button variant="primary" onClick={() => createRegion.mutate()} disabled={!regionForm.name || !regionForm.code || createRegion.isPending} loading={createRegion.isPending}>Create Region</Button></>}>
        <Input label="Region Name *" value={regionForm.name} onChange={v => setRegionForm(f => ({ ...f, name: v }))} placeholder="e.g. South-West Zone" />
        <Input label="Region Code *" value={regionForm.code} onChange={v => setRegionForm(f => ({ ...f, code: v.toUpperCase() }))} placeholder="e.g. SWZ" />
        <Select label="Parent Region (optional)" value={regionForm.parent_id} onChange={v => setRegionForm(f => ({ ...f, parent_id: v }))}
          options={[{ label: '— None —', value: '' }, ...(regions as any[]).map((r: any) => ({ label: `${r.name} (${r.code})`, value: r.id }))]} />
      </Modal>

      <Modal open={pipelineModal} onClose={() => setPipelineModal(false)} title="New Pipeline Template"
        footer={<><Button variant="secondary" onClick={() => setPipelineModal(false)}>Cancel</Button><Button variant="primary" onClick={() => createPipeline.mutate()} disabled={!pipelineForm.name || createPipeline.isPending} loading={createPipeline.isPending}>Create Pipeline</Button></>}>
        <Input label="Pipeline Name *" value={pipelineForm.name} onChange={v => setPipelineForm(f => ({ ...f, name: v }))} placeholder="e.g. Cable Upgrade Workflow" />
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--color-text-muted)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.1em' }}>Description</label>
          <textarea value={pipelineForm.description} onChange={e => setPipelineForm(f => ({ ...f, description: e.target.value }))} rows={2}
            placeholder="Optional description of this pipeline template…"
            style={{ width: '100%', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 8, padding: '9px 12px', color: 'var(--color-text-primary)', fontFamily: 'var(--font-body)', fontSize: 12, outline: 'none', resize: 'vertical' }} />
        </div>
      </Modal>

      <Modal open={webhookKeyModal} onClose={() => setWebhookKeyModal(false)} title="New Webhook Key"
        footer={<><Button variant="secondary" onClick={() => setWebhookKeyModal(false)}>Cancel</Button><Button variant="primary" onClick={() => createWebhookKey.mutate()} disabled={createWebhookKey.isPending} loading={createWebhookKey.isPending}>Generate Key</Button></>}>
        <Select label="App *" value={webhookApp} onChange={v => setWebhookApp(v)}
          options={[
            { label: 'HR — staff lifecycle events',     value: 'hr' },
            { label: 'Finance — project budget events', value: 'finance' },
            { label: 'Sales — lead events',             value: 'sales' },
            { label: 'Field Tech — outage signals',     value: 'field_tech' },
            { label: 'Coverage — network events',       value: 'coverage' },
          ]} />
        <div style={{ padding: '10px 12px', background: 'rgba(0,194,168,.05)', borderRadius: 8, fontSize: 11, color: 'var(--color-text-muted)', lineHeight: 1.5 }}>
          A unique HMAC-SHA256 secret will be generated. You will only see it once — store it securely in your integration.
        </div>
      </Modal>

      {/* Integration config modal */}
      {configModal && INTEGRATION_FIELDS[configModal.key] && (
        <Modal
          open={!!configModal}
          onClose={() => setConfigModal(null)}
          title={`Configure ${configModal.name}`}
          footer={
            <>
              <Button variant="secondary" onClick={() => setConfigModal(null)}>Cancel</Button>
              <Button variant="primary" onClick={() => saveConfig.mutate()} disabled={saveConfig.isPending} loading={saveConfig.isPending}>Save Configuration</Button>
            </>
          }
        >
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 14, lineHeight: 1.5 }}>
            Credentials are stored encrypted in your tenant settings. Sensitive fields will not be shown after saving.
          </div>
          {INTEGRATION_FIELDS[configModal.key].map(f => (
            <div key={f.field} style={{ marginBottom: 12 }}>
              <label style={{ display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--color-text-muted)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.1em' }}>
                {f.label}
              </label>
              <input
                type={f.type === 'password' ? 'password' : 'text'}
                value={configForm[f.field] ?? (existingConfig as any)?.[f.field] ?? ''}
                onChange={e => setConfigForm(prev => ({ ...prev, [f.field]: e.target.value }))}
                placeholder={f.placeholder}
                style={{
                  width: '100%', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)',
                  borderRadius: 8, padding: '9px 12px', color: 'var(--color-text-primary)',
                  fontFamily: 'var(--font-body)', fontSize: 12, outline: 'none', boxSizing: 'border-box',
                }}
              />
            </div>
          ))}
        </Modal>
      )}

      <Modal open={ruleModal} onClose={() => setRuleModal(false)} title={editRule ? 'Edit Notification Rule' : 'New Notification Rule'}
        footer={<><Button variant="secondary" onClick={() => setRuleModal(false)}>Cancel</Button><Button variant="primary" onClick={() => saveRule.mutate()} disabled={!ruleForm.name || ruleForm.channels.length === 0 || saveRule.isPending} loading={saveRule.isPending}>{editRule ? 'Save Changes' : 'Create Rule'}</Button></>}>
        <Input label="Rule Name *" value={ruleForm.name} onChange={v => setRuleForm(f => ({ ...f, name: v }))} placeholder="e.g. Critical Alert — All Channels" />
        <Select label="Min Severity" value={ruleForm.min_severity} onChange={v => setRuleForm(f => ({ ...f, min_severity: v as OutageNotificationRule['min_severity'] }))}
          options={[{ label: 'Critical', value: 'critical' }, { label: 'High', value: 'high' }, { label: 'Warning', value: 'warning' }, { label: 'Low', value: 'low' }]} />
        <Input label="Min Subscribers" value={ruleForm.min_subscribers} onChange={v => setRuleForm(f => ({ ...f, min_subscribers: v }))} placeholder="0" />
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '.1em' }}>Channels *</div>
          <div style={{ display: 'flex', gap: 8 }}>
            {(['sms', 'email', 'whatsapp'] as const).map(ch => (
              <div key={ch} onClick={() => toggleChannel(ch)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, cursor: 'pointer', fontSize: 12, fontWeight: 600, transition: 'all .15s',
                  background: ruleForm.channels.includes(ch) ? 'rgba(0,194,168,.12)' : 'var(--color-surface-2)',
                  border:     `1px solid ${ruleForm.channels.includes(ch) ? 'rgba(0,194,168,.35)' : 'var(--color-border)'}`,
                  color:      ruleForm.channels.includes(ch) ? 'var(--color-teal)' : 'var(--color-text-muted)',
                }}
              >
                {ruleForm.channels.includes(ch) && <span style={{ fontSize: 10 }}>✓</span>}
                {ch.toUpperCase()}
              </div>
            ))}
          </div>
        </div>
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--color-text-muted)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.1em' }}>Message Template</label>
          <textarea value={ruleForm.message_template} onChange={e => setRuleForm(f => ({ ...f, message_template: e.target.value }))} rows={3}
            placeholder="Outage {reference}: {title} ({severity}). Status: {status}. Subs affected: {subscribers}."
            style={{ width: '100%', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 8, padding: '9px 12px', color: 'var(--color-text-primary)', fontFamily: 'var(--font-mono)', fontSize: 11, outline: 'none', resize: 'vertical', lineHeight: 1.6 }} />
          <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 4 }}>
            Variables: <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-text-primary)' }}>&#123;reference&#125; &#123;title&#125; &#123;severity&#125; &#123;status&#125; &#123;olt&#125; &#123;subscribers&#125;</span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 16, marginBottom: 4 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 12, color: 'var(--color-text-primary)' }}>
            <input type="checkbox" checked={ruleForm.is_auto} onChange={e => setRuleForm(f => ({ ...f, is_auto: e.target.checked }))}
              style={{ accentColor: 'var(--color-teal)', width: 14, height: 14 }} />
            Auto-fire on new outages
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 12, color: 'var(--color-text-primary)' }}>
            <input type="checkbox" checked={ruleForm.is_active} onChange={e => setRuleForm(f => ({ ...f, is_active: e.target.checked }))}
              style={{ accentColor: 'var(--color-teal)', width: 14, height: 14 }} />
            Rule active
          </label>
        </div>
      </Modal>
    </Page>
  );
}
