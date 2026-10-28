// ============================================================
// OPSYN — InfrastructureSettingsPage
// S4.3.2: Monitoring configs, alert rules, port inventory
// ============================================================

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { infrastructureApi } from '../../api/index';
import type { InfraMonitoringConfig, InfraAlertRule } from '@shared';
import { Modal as UiModal, Tabs } from '../../components/ui';
import { GlassSelect } from '../../components/glass';
import { Page, PageHeader } from '../../components/layout/Page';

// ── Shared primitives (inline to avoid cross-page imports) ───
const card = (extra?: React.CSSProperties): React.CSSProperties => ({
  background: 'var(--bg2)', border: '1px solid var(--wire)',
  borderRadius: 12, padding: 16, position: 'relative', overflow: 'hidden', ...extra,
});
const badge = (c: string, bg: string): React.CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 8px',
  borderRadius: 20, fontSize: 10, fontWeight: 700, letterSpacing: '.06em',
  textTransform: 'uppercase', color: c, background: bg, whiteSpace: 'nowrap',
});
const dot: React.CSSProperties = {
  width: 6, height: 6, borderRadius: '50%', background: 'currentColor',
};

function Btn({ children, variant, onClick, disabled, style }: any) {
  const base: React.CSSProperties = {
    padding: '7px 16px', borderRadius: 8, border: 'none', cursor: disabled ? 'not-allowed' : 'pointer',
    fontFamily: 'var(--font)', fontWeight: 700, fontSize: 12, transition: 'all .15s',
    opacity: disabled ? 0.5 : 1, ...style,
  };
  const colors: Record<string, React.CSSProperties> = {
    brand: { background: 'var(--brand)', color: 'var(--brand-contrast)' },
    ghost: { background: 'transparent', color: 'var(--chalk3)', border: '1px solid var(--wire)' },
    rose:  { background: 'rgba(244,63,94,.12)', color: 'var(--rose)', border: '1px solid rgba(244,63,94,.3)' },
    amber: { background: 'rgba(251,191,36,.12)', color: 'var(--amber)', border: '1px solid rgba(251,191,36,.3)' },
  };
  return <button style={{ ...base, ...(colors[variant] ?? colors.ghost) }} onClick={onClick} disabled={disabled}>{children}</button>;
}

function Inp({ label, value, onChange, placeholder, type = 'text' }: any) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--chalk3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.1em' }}>{label}</label>
      <input type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        style={{ width: '100%', background: 'var(--bg3)', border: '1px solid var(--wire2)', borderRadius: 8, padding: '9px 12px', color: 'var(--chalk)', fontFamily: 'var(--font)', fontSize: 12, outline: 'none', boxSizing: 'border-box' }} />
    </div>
  );
}

function Sel({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: { label: string; value: string }[] }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--chalk3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.1em' }}>{label}</label>
      <GlassSelect value={String(value)} onChange={v => onChange(v)} options={[...options.map((o) => ({ value: String(o.value), label: String(o.label) }))]} ariaLabel={label} />
    </div>
  );
}

/** Local alias kept for existing call sites — the shared glass dialog */
function Modal({ open, onClose, title, children, footer }: any) {
  return <UiModal open={open} onClose={onClose} title={title} footer={footer}>{children}</UiModal>;
}

// ── Toast (minimal inline) ────────────────────────────────────
function useToast() {
  return {
    success: (msg: string) => console.log('[ok]', msg),
    error:   (msg: string) => console.error('[err]', msg),
    info:    (msg: string) => console.info('[info]', msg),
  };
}

// ── CHANNELS available ────────────────────────────────────────
const ALL_CHANNELS = ['email', 'sms', 'in_app'];
const SEVERITIES   = ['warning', 'critical'];
const OPERATORS    = ['gt', 'gte', 'lt', 'lte', 'eq'];
const ACTIONS      = ['notify', 'create_task'];
const CONDITION_FIELDS = ['utilisation_pct', 'used_capacity', 'total_capacity'];
const ENTITY_TYPES = ['node', 'site'];

// ─────────────────────────────────────────────────────────────
export default function InfrastructureSettingsPage() {
  const [tab, setTab] = useState<'monitoring' | 'rules' | 'ports'>('monitoring');
  const toast = useToast();
  const qc    = useQueryClient();

  // ── Monitoring configs ────────────────────────────────────
  const { data: configs = [], isLoading: configsLoading } = useQuery<InfraMonitoringConfig[]>({
    queryKey: ['infra', 'monitoring-configs'],
    queryFn: () => infrastructureApi.listMonitoringConfigs() as any,
  });

  const [configModal, setConfigModal]     = useState(false);
  const [editConfig, setEditConfig]       = useState<InfraMonitoringConfig | null>(null);
  const [configForm, setConfigForm]       = useState({
    entity_type: 'node', entity_id: '',
    warn_threshold_pct: '70', critical_threshold_pct: '90',
    check_interval_minutes: '15',
    alert_channels: ['email'] as string[],
    assigned_role_level: '2',
    is_active: true,
  });

  const openNewConfig = () => {
    setEditConfig(null);
    setConfigForm({ entity_type: 'node', entity_id: '', warn_threshold_pct: '70', critical_threshold_pct: '90', check_interval_minutes: '15', alert_channels: ['email'], assigned_role_level: '2', is_active: true });
    setConfigModal(true);
  };
  const openEditConfig = (c: InfraMonitoringConfig) => {
    setEditConfig(c);
    setConfigForm({
      entity_type: c.entity_type, entity_id: c.entity_id,
      warn_threshold_pct: String(c.warn_threshold_pct),
      critical_threshold_pct: String(c.critical_threshold_pct),
      check_interval_minutes: String(c.check_interval_minutes),
      alert_channels: c.alert_channels ?? ['email'],
      assigned_role_level: String(c.assigned_role_level),
      is_active: c.is_active,
    });
    setConfigModal(true);
  };
  const toggleChannel = (ch: string) =>
    setConfigForm(f => ({
      ...f,
      alert_channels: f.alert_channels.includes(ch)
        ? f.alert_channels.filter(x => x !== ch)
        : [...f.alert_channels, ch],
    }));

  const saveConfig = useMutation({
    mutationFn: () => {
      const payload = {
        ...configForm,
        warn_threshold_pct:     parseInt(configForm.warn_threshold_pct),
        critical_threshold_pct: parseInt(configForm.critical_threshold_pct),
        check_interval_minutes: parseInt(configForm.check_interval_minutes),
        assigned_role_level:    parseInt(configForm.assigned_role_level),
      };
      return editConfig
        ? (infrastructureApi.updateMonitoringConfig as any)(editConfig.id, payload)
        : (infrastructureApi.createMonitoringConfig as any)(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['infra', 'monitoring-configs'] });
      setConfigModal(false);
      toast.success(editConfig ? 'Config updated' : 'Config created');
    },
    onError: () => toast.error('Failed to save config'),
  });

  const deleteConfig = useMutation({
    mutationFn: (id: string) => (infrastructureApi.deleteMonitoringConfig as any)(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['infra', 'monitoring-configs'] }); toast.info('Config deleted'); },
    onError: () => toast.error('Failed to delete config'),
  });

  // ── Alert rules ───────────────────────────────────────────
  const { data: rules = [], isLoading: rulesLoading } = useQuery<InfraAlertRule[]>({
    queryKey: ['infra', 'alert-rules'],
    queryFn: () => infrastructureApi.listAlertRules() as any,
  });

  const [ruleModal, setRuleModal]   = useState(false);
  const [editRule, setEditRule]     = useState<InfraAlertRule | null>(null);
  const [ruleForm, setRuleForm]     = useState({
    name: '', condition_field: 'utilisation_pct', operator: 'gte',
    threshold_value: '80', severity: 'warning', action_type: 'notify',
    action_params: '{}', is_active: true,
  });

  const openNewRule = () => {
    setEditRule(null);
    setRuleForm({ name: '', condition_field: 'utilisation_pct', operator: 'gte', threshold_value: '80', severity: 'warning', action_type: 'notify', action_params: '{}', is_active: true });
    setRuleModal(true);
  };
  const openEditRule = (r: InfraAlertRule) => {
    setEditRule(r);
    setRuleForm({
      name: r.name, condition_field: r.condition_field, operator: r.operator,
      threshold_value: String(r.threshold_value), severity: r.severity,
      action_type: r.action_type, action_params: JSON.stringify(r.action_params ?? {}, null, 2),
      is_active: r.is_active,
    });
    setRuleModal(true);
  };

  const saveRule = useMutation({
    mutationFn: () => {
      let params: any = {};
      try { params = JSON.parse(ruleForm.action_params); } catch (_) { params = {}; }
      const payload = {
        ...ruleForm,
        threshold_value: parseFloat(ruleForm.threshold_value),
        action_params: params,
      };
      return editRule
        ? (infrastructureApi.updateAlertRule as any)(editRule.id, payload)
        : (infrastructureApi.createAlertRule as any)(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['infra', 'alert-rules'] });
      setRuleModal(false);
      toast.success(editRule ? 'Rule updated' : 'Rule created');
    },
    onError: () => toast.error('Failed to save rule'),
  });

  const deleteRule = useMutation({
    mutationFn: (id: string) => (infrastructureApi.deleteAlertRule as any)(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['infra', 'alert-rules'] }); toast.info('Rule deleted'); },
    onError: () => toast.error('Failed to delete rule'),
  });

  // ── Port inventory ────────────────────────────────────────
  const [selectedNodeId, setSelectedNodeId] = useState<string>('');
  const { data: nodesData } = useQuery({
    queryKey: ['infra', 'nodes'],
    queryFn: () => infrastructureApi.listNodes({ size: 200 }) as any,
  });
  const nodes: any[] = (nodesData as any)?.items ?? nodesData ?? [];

  const { data: ports = [], isLoading: portsLoading } = useQuery<any[]>({
    queryKey: ['infra', 'ports', selectedNodeId],
    queryFn: () => selectedNodeId ? infrastructureApi.listPorts(selectedNodeId) : Promise.resolve([]),
    enabled: !!selectedNodeId,
  });

  const syncPorts = useMutation({
    mutationFn: () => infrastructureApi.triggerSyncPorts(),
    onSuccess: () => toast.success('Port sync enqueued — updates in ~15 min'),
    onError:   () => toast.error('Failed to enqueue sync'),
  });

  const SEV_COLOR = (s: string) => s === 'critical' ? 'var(--rose)' : 'var(--amber)';
  const TH: React.CSSProperties = { textAlign: 'left', fontSize: 9, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--chalk3)', padding: '9px 14px', borderBottom: '1px solid var(--wire)' };
  const TD: React.CSSProperties = { padding: '10px 14px', borderBottom: '1px solid var(--wire)', fontSize: 12 };

  return (
    <Page>
        <PageHeader title="Infrastructure settings" lede="Monitoring configs · alert rules · port inventory" />
        <Tabs
          label="Settings sections"
          idPrefix="infra-settings"
          value={tab}
          onChange={setTab}
          items={[
            { value: 'monitoring', label: 'Monitoring configs' },
            { value: 'rules',      label: 'Alert rules' },
            { value: 'ports',      label: 'Port inventory' },
          ]}
        />

        <div role="tabpanel" id="infra-settings-panel" aria-labelledby={`infra-settings-tab-${tab}`}>
        {/* ── MONITORING CONFIGS ── */}
        {tab === 'monitoring' && (
          <>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
              <Btn variant="brand" onClick={openNewConfig} style={{ fontSize: 11, padding: '5px 12px' }}>+ New Config</Btn>
            </div>
            <div style={card({ padding: 0 })}>
              <div style={{ overflowX: 'auto' }} tabIndex={0} role="region" aria-label="Monitoring configs">
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr>
                    {['Entity Type', 'Entity ID', 'Warn %', 'Critical %', 'Interval', 'Channels', 'Active', 'Actions'].map(h => <th key={h} style={TH}>{h}</th>)}
                  </tr></thead>
                  <tbody>
                    {configsLoading
                      ? <tr><td colSpan={8} style={{ ...TD, textAlign: 'center', padding: 40, color: 'var(--chalk3)' }}>Loading…</td></tr>
                      : (configs as InfraMonitoringConfig[]).length === 0
                        ? <tr><td colSpan={8} style={{ ...TD, textAlign: 'center', padding: 40, color: 'var(--chalk3)' }}>No monitoring configs yet</td></tr>
                        : (configs as InfraMonitoringConfig[]).map(c => (
                          <tr key={c.id}>
                            <td style={{ ...TD, color: 'var(--chalk)' }}><span style={badge('var(--cyan)', 'rgba(6,182,212,.1)')}>{c.entity_type}</span></td>
                            <td style={{ ...TD, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--chalk3)' }}>{c.entity_id.slice(0, 12)}…</td>
                            <td style={{ ...TD, color: 'var(--amber)', fontWeight: 700 }}>{c.warn_threshold_pct}%</td>
                            <td style={{ ...TD, color: 'var(--rose)', fontWeight: 700 }}>{c.critical_threshold_pct}%</td>
                            <td style={{ ...TD, color: 'var(--chalk3)' }}>{c.check_interval_minutes} min</td>
                            <td style={TD}>{(c.alert_channels ?? []).map(ch => <span key={ch} style={{ ...badge('var(--violet)', 'rgba(139,92,246,.1)'), marginRight: 4 }}>{ch}</span>)}</td>
                            <td style={TD}><span style={dot && badge(c.is_active ? 'var(--green)' : 'var(--chalk3)', c.is_active ? 'rgba(74,222,128,.1)' : 'rgba(148,163,184,.1)')}><span style={dot} />{c.is_active ? 'on' : 'off'}</span></td>
                            <td style={{ ...TD, display: 'flex', gap: 6 }}>
                              <Btn variant="ghost" onClick={() => openEditConfig(c)} style={{ fontSize: 11, padding: '3px 8px' }}>Edit</Btn>
                              <Btn variant="rose"  onClick={() => deleteConfig.mutate(c.id)} disabled={deleteConfig.isPending} style={{ fontSize: 11, padding: '3px 8px' }}>Delete</Btn>
                            </td>
                          </tr>
                        ))
                    }
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}

        {/* ── ALERT RULES ── */}
        {tab === 'rules' && (
          <>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
              <Btn variant="brand" onClick={openNewRule} style={{ fontSize: 11, padding: '5px 12px' }}>+ New Rule</Btn>
            </div>
            <div style={card({ padding: 0 })}>
              <div style={{ overflowX: 'auto' }} tabIndex={0} role="region" aria-label="Alert rules">
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr>
                    {['Name', 'Condition', 'Threshold', 'Severity', 'Action', 'Active', 'Actions'].map(h => <th key={h} style={TH}>{h}</th>)}
                  </tr></thead>
                  <tbody>
                    {rulesLoading
                      ? <tr><td colSpan={7} style={{ ...TD, textAlign: 'center', padding: 40, color: 'var(--chalk3)' }}>Loading…</td></tr>
                      : (rules as InfraAlertRule[]).length === 0
                        ? <tr><td colSpan={7} style={{ ...TD, textAlign: 'center', padding: 40, color: 'var(--chalk3)' }}>No alert rules yet</td></tr>
                        : (rules as InfraAlertRule[]).map(r => (
                          <tr key={r.id}>
                            <td style={{ ...TD, fontWeight: 600, color: 'var(--chalk)' }}>{r.name}</td>
                            <td style={{ ...TD, fontFamily: 'var(--mono)', fontSize: 11 }}>{r.condition_field} {r.operator}</td>
                            <td style={{ ...TD, fontFamily: 'var(--mono)', fontWeight: 700, color: 'var(--cyan)' }}>{Number(r.threshold_value).toFixed(1)}</td>
                            <td style={TD}><span style={badge(SEV_COLOR(r.severity), `${SEV_COLOR(r.severity)}1a`)}>{r.severity}</span></td>
                            <td style={TD}><span style={badge('var(--violet)', 'rgba(139,92,246,.1)')}>{r.action_type}</span></td>
                            <td style={TD}><span style={badge(r.is_active ? 'var(--green)' : 'var(--chalk3)', r.is_active ? 'rgba(74,222,128,.1)' : 'rgba(148,163,184,.1)')}><span style={dot} />{r.is_active ? 'on' : 'off'}</span></td>
                            <td style={{ ...TD, display: 'flex', gap: 6 }}>
                              <Btn variant="ghost" onClick={() => openEditRule(r)} style={{ fontSize: 11, padding: '3px 8px' }}>Edit</Btn>
                              <Btn variant="rose"  onClick={() => deleteRule.mutate(r.id)} disabled={deleteRule.isPending} style={{ fontSize: 11, padding: '3px 8px' }}>Delete</Btn>
                            </td>
                          </tr>
                        ))
                    }
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}

        {/* ── PORT INVENTORY ── */}
        {tab === 'ports' && (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <GlassSelect value={String(selectedNodeId)} onChange={v => setSelectedNodeId(v)} options={[...nodes.map((n: any) => ({ value: String(n.id), label: `${n.name} (${n.node_type})` }))]} placeholder={'— Select a node —'} ariaLabel="Node" compact />
              <Btn variant="amber" onClick={() => syncPorts.mutate()} disabled={syncPorts.isPending} style={{ fontSize: 11, padding: '5px 12px' }}>
                {syncPorts.isPending ? 'Queuing…' : 'Sync Ports Now'}
              </Btn>
            </div>

            {!selectedNodeId ? (
              <div style={{ ...card(), textAlign: 'center', padding: 40, color: 'var(--chalk3)', fontSize: 13 }}>
                Select a node above to view its port inventory
              </div>
            ) : (
              <div style={card({ padding: 0 })}>
                <div style={{ overflowX: 'auto' }} tabIndex={0} role="region" aria-label="Port inventory">
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead><tr>
                      {['Port #', 'Type', 'Used', 'Total', 'Utilisation', 'Status', 'Last Synced'].map(h => <th key={h} style={TH}>{h}</th>)}
                    </tr></thead>
                    <tbody>
                      {portsLoading
                        ? <tr><td colSpan={7} style={{ ...TD, textAlign: 'center', padding: 40, color: 'var(--chalk3)' }}>Loading ports…</td></tr>
                        : (ports as any[]).length === 0
                          ? <tr><td colSpan={7} style={{ ...TD, textAlign: 'center', padding: 40, color: 'var(--chalk3)' }}>No ports found for this node</td></tr>
                          : (ports as any[]).map(p => {
                            const pct  = p.utilisation_pct ?? 0;
                            const barC = pct >= 90 ? 'var(--rose)' : pct >= 70 ? 'var(--amber)' : 'var(--green)';
                            return (
                              <tr key={p.id}>
                                <td style={{ ...TD, fontFamily: 'var(--mono)', color: 'var(--chalk)' }}>{p.port_number}</td>
                                <td style={TD}><span style={badge('var(--cyan)', 'rgba(6,182,212,.1)')}>{p.port_type}</span></td>
                                <td style={{ ...TD, fontFamily: 'var(--mono)', color: 'var(--chalk2)' }}>{p.used_capacity}</td>
                                <td style={{ ...TD, fontFamily: 'var(--mono)', color: 'var(--chalk3)' }}>{p.total_capacity}</td>
                                <td style={{ ...TD, minWidth: 140 }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <div style={{ flex: 1, height: 6, background: 'var(--wire)', borderRadius: 3, overflow: 'hidden' }}>
                                      <div style={{ width: `${pct}%`, height: '100%', background: barC, borderRadius: 3, transition: 'width .3s' }} />
                                    </div>
                                    <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: barC, minWidth: 34, textAlign: 'right' }}>{pct}%</span>
                                  </div>
                                </td>
                                <td style={TD}><span style={badge(p.status === 'active' ? 'var(--green)' : 'var(--rose)', p.status === 'active' ? 'rgba(74,222,128,.1)' : 'rgba(244,63,94,.1)')}><span style={dot} />{p.status}</span></td>
                                <td style={{ ...TD, fontSize: 11, color: 'var(--chalk3)' }}>
                                  {p.last_synced_at ? new Date(p.last_synced_at).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'}
                                </td>
                              </tr>
                            );
                          })
                      }
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
        </div>

      {/* ── MONITORING CONFIG MODAL ── */}
      <Modal open={configModal} onClose={() => setConfigModal(false)} title={editConfig ? 'Edit Monitoring Config' : 'New Monitoring Config'}
        footer={<><Btn onClick={() => setConfigModal(false)}>Cancel</Btn><Btn variant="brand" onClick={() => saveConfig.mutate()} disabled={!configForm.entity_id || saveConfig.isPending}>{saveConfig.isPending ? 'Saving…' : editConfig ? 'Update' : 'Create'}</Btn></>}>
        <Sel label="Entity Type" value={configForm.entity_type} onChange={v => setConfigForm(f => ({ ...f, entity_type: v }))} options={ENTITY_TYPES.map(t => ({ label: t.charAt(0).toUpperCase() + t.slice(1), value: t }))} />
        <Inp label="Entity ID (UUID)" value={configForm.entity_id} onChange={(v: string) => setConfigForm(f => ({ ...f, entity_id: v }))} placeholder="paste node or site UUID" />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Inp label="Warn Threshold %" type="number" value={configForm.warn_threshold_pct} onChange={(v: string) => setConfigForm(f => ({ ...f, warn_threshold_pct: v }))} placeholder="70" />
          <Inp label="Critical Threshold %" type="number" value={configForm.critical_threshold_pct} onChange={(v: string) => setConfigForm(f => ({ ...f, critical_threshold_pct: v }))} placeholder="90" />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Inp label="Check Interval (min)" type="number" value={configForm.check_interval_minutes} onChange={(v: string) => setConfigForm(f => ({ ...f, check_interval_minutes: v }))} placeholder="15" />
          <Inp label="Notify Role Level (≥)" type="number" value={configForm.assigned_role_level} onChange={(v: string) => setConfigForm(f => ({ ...f, assigned_role_level: v }))} placeholder="2" />
        </div>
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--chalk3)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '.1em' }}>Alert Channels</label>
          <div style={{ display: 'flex', gap: 8 }}>
            {ALL_CHANNELS.map(ch => (
              <button key={ch} onClick={() => toggleChannel(ch)}
                style={{ padding: '5px 12px', borderRadius: 20, border: '1px solid', cursor: 'pointer', fontFamily: 'var(--font)', fontSize: 11, fontWeight: 700, transition: 'all .15s', borderColor: configForm.alert_channels.includes(ch) ? 'var(--brand)' : 'var(--wire)', background: configForm.alert_channels.includes(ch) ? 'rgba(99,102,241,.15)' : 'transparent', color: configForm.alert_channels.includes(ch) ? 'var(--brand)' : 'var(--chalk3)' }}>
                {ch.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <input type="checkbox" id="cfg-active" checked={configForm.is_active} onChange={e => setConfigForm(f => ({ ...f, is_active: e.target.checked }))} />
          <label htmlFor="cfg-active" style={{ fontSize: 12, color: 'var(--chalk2)', cursor: 'pointer' }}>Active (monitoring enabled)</label>
        </div>
      </Modal>

      {/* ── ALERT RULE MODAL ── */}
      <Modal open={ruleModal} onClose={() => setRuleModal(false)} title={editRule ? 'Edit Alert Rule' : 'New Alert Rule'}
        footer={<><Btn onClick={() => setRuleModal(false)}>Cancel</Btn><Btn variant="brand" onClick={() => saveRule.mutate()} disabled={!ruleForm.name || saveRule.isPending}>{saveRule.isPending ? 'Saving…' : editRule ? 'Update' : 'Create'}</Btn></>}>
        <Inp label="Rule Name *" value={ruleForm.name} onChange={(v: string) => setRuleForm(f => ({ ...f, name: v }))} placeholder="e.g. High OLT utilisation" />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
          <Sel label="Field" value={ruleForm.condition_field} onChange={v => setRuleForm(f => ({ ...f, condition_field: v }))} options={CONDITION_FIELDS.map(x => ({ label: x, value: x }))} />
          <Sel label="Operator" value={ruleForm.operator} onChange={v => setRuleForm(f => ({ ...f, operator: v }))} options={OPERATORS.map(o => ({ label: o, value: o }))} />
          <Inp label="Threshold" type="number" value={ruleForm.threshold_value} onChange={(v: string) => setRuleForm(f => ({ ...f, threshold_value: v }))} placeholder="80" />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Sel label="Severity" value={ruleForm.severity} onChange={v => setRuleForm(f => ({ ...f, severity: v }))} options={SEVERITIES.map(s => ({ label: s.charAt(0).toUpperCase() + s.slice(1), value: s }))} />
          <Sel label="Action" value={ruleForm.action_type} onChange={v => setRuleForm(f => ({ ...f, action_type: v }))} options={ACTIONS.map(a => ({ label: a, value: a }))} />
        </div>
        {ruleForm.action_type === 'create_task' && (
          <div style={{ marginBottom: 14 }}>
            <label style={{ display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--chalk3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.1em' }}>Task Params (JSON)</label>
            <textarea value={ruleForm.action_params} onChange={e => setRuleForm(f => ({ ...f, action_params: e.target.value }))} rows={4} placeholder={'{"title": "Fix capacity", "task_type": "maintenance", "priority": "high"}'}
              style={{ width: '100%', background: 'var(--bg3)', border: '1px solid var(--wire2)', borderRadius: 8, padding: '9px 12px', color: 'var(--chalk)', fontFamily: 'var(--mono)', fontSize: 11, outline: 'none', resize: 'vertical', boxSizing: 'border-box' }} />
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <input type="checkbox" id="rule-active" checked={ruleForm.is_active} onChange={e => setRuleForm(f => ({ ...f, is_active: e.target.checked }))} />
          <label htmlFor="rule-active" style={{ fontSize: 12, color: 'var(--chalk2)', cursor: 'pointer' }}>Active</label>
        </div>
      </Modal>
    </Page>
  );
}
