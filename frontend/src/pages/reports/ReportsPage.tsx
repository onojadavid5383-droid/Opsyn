// ============================================================
// OPSYN — ReportsPage  (Stage 5 redesign)
// ============================================================

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { reportsApi } from '../../api/index';
import { Button } from '../../components/ui';
import { Page, PageHeader } from '../../components/layout/Page';

type TabKey = 'overview' | 'staff' | 'tasks' | 'projects' | 'outages' | 'infrastructure' | 'shifts' | 'sla';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overview',        label: 'Overview' },
  { key: 'staff',           label: 'Staff' },
  { key: 'tasks',           label: 'Tasks' },
  { key: 'projects',        label: 'Projects' },
  { key: 'outages',         label: 'Outages & MTTR' },
  { key: 'infrastructure',  label: 'Infrastructure' },
  { key: 'shifts',          label: 'Shifts' },
  { key: 'sla',             label: 'SLA Compliance' },
];

const TASK_STATUS_COLORS: Record<string, string> = {
  new:         'var(--color-text-muted)',
  assigned:    'var(--color-teal)',
  in_progress: 'var(--color-teal)',
  review:      'var(--color-indigo)',
  blocked:     'var(--color-red)',
  done:        'var(--color-green)',
  archived:    'var(--color-text-muted)',
};

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'var(--color-red)',
  major:    'var(--color-amber)',
  warning:  'var(--color-indigo)',
  info:     'var(--color-teal)',
};

const SEVERITY_BG: Record<string, string> = {
  critical: 'rgba(220,38,38,.1)',
  major:    'rgba(245,158,11,.1)',
  warning:  'rgba(79,70,229,.1)',
  info:     'rgba(0,194,168,.1)',
};

const PROJECT_TYPE_COLORS: Record<string, string> = {
  external:         'var(--color-teal)',
  internal:         'var(--color-indigo)',
  cable_upgrade:    'var(--color-amber)',
  olt_installation: 'var(--color-teal)',
  procurement:      'var(--color-green)',
};

function KpiTile({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--color-border)',
      borderRadius: 'var(--radius-card)', padding: '16px 18px',
      borderTop: `3px solid ${color}`,
    }}>
      <div style={{ fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 600, color: 'var(--color-text-muted)', letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 28, fontWeight: 700, color, lineHeight: 1 }}>
        {value}
      </div>
    </div>
  );
}

function BreakdownBar({ label, count, total, color = 'var(--color-teal)' }: { label: string; count: number; total: number; color?: string }) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 12, color: 'var(--color-text-primary)', fontWeight: 500 }}>{label}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-text-muted)' }}>
          {count} <span style={{ fontSize: 10 }}>({pct}%)</span>
        </span>
      </div>
      <div style={{ height: 6, background: 'var(--color-surface-2)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 3, transition: 'width .4s ease' }} />
      </div>
    </div>
  );
}

function Pbar({ pct, fill }: { pct: number; fill: string }) {
  return (
    <div style={{ background: 'var(--color-surface-2)', borderRadius: 3, height: 5, overflow: 'hidden', marginTop: 6 }}>
      <div style={{ width: `${Math.max(0, Math.min(100, pct))}%`, height: '100%', background: fill, borderRadius: 3, transition: 'width .8s ease' }} />
    </div>
  );
}

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-card)', padding: 16, ...style }}>
      {children}
    </div>
  );
}

function CardTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 13, color: 'var(--color-text-primary)', marginBottom: 14 }}>
      {children}
    </div>
  );
}

const TH: React.CSSProperties = {
  textAlign: 'left', fontSize: 9, fontWeight: 700, letterSpacing: '.1em',
  textTransform: 'uppercase', color: 'var(--color-text-muted)',
  padding: '9px 14px', borderBottom: '1px solid var(--color-border)',
};
const TD: React.CSSProperties = { padding: '9px 14px', borderBottom: '1px solid var(--color-border)' };

export default function ReportsPage() {
  const [tab, setTab]           = useState<TabKey>('overview');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo]     = useState('');
  const params = { date_from: dateFrom || undefined, date_to: dateTo || undefined };

  const { data: summary,   isLoading: sumLoading }    = useQuery({ queryKey: ['reports', 'summary', dateFrom, dateTo],      queryFn: () => reportsApi.getSummary(params) });
  const { data: staffBd,   isLoading: staffLoading }  = useQuery({ queryKey: ['reports', 'staff-breakdown'],               queryFn: () => reportsApi.getStaffBreakdown(),       enabled: tab === 'staff' });
  const { data: tasksBd,   isLoading: tasksLoading }  = useQuery({ queryKey: ['reports', 'tasks-breakdown'],               queryFn: () => reportsApi.getTasksBreakdown(),       enabled: tab === 'tasks' });
  const { data: projBd,    isLoading: projLoading }   = useQuery({ queryKey: ['reports', 'projects-breakdown'],            queryFn: () => reportsApi.getProjectsBreakdown(),    enabled: tab === 'projects' });
  const { data: mttr,      isLoading: mttrLoading }   = useQuery({ queryKey: ['reports', 'mttr', dateFrom, dateTo],        queryFn: () => reportsApi.getOutageMttr(params),     enabled: tab === 'outages' });
  const { data: infraRpt,  isLoading: infraLoading }  = useQuery({ queryKey: ['reports', 'infrastructure'],               queryFn: () => reportsApi.getInfrastructureReport(), enabled: tab === 'infrastructure' });
  const { data: shiftsRpt, isLoading: shiftsLoading } = useQuery({ queryKey: ['reports', 'shifts'],                       queryFn: () => reportsApi.getShiftsReport(),          enabled: tab === 'shifts' });
  const { data: slaRpt,    isLoading: slaLoading }    = useQuery({ queryKey: ['reports', 'sla'],                          queryFn: () => reportsApi.getSlaReport(),              enabled: tab === 'sla' });

  const d:  any = summary   ?? {};
  const sb: any = staffBd   ?? {};
  const tb: any = tasksBd   ?? {};
  const pb: any = projBd    ?? {};
  const mt: any = mttr      ?? {};
  const ir: any = infraRpt  ?? {};
  const sr: any = shiftsRpt ?? {};
  const sl: any = slaRpt    ?? {};

  const exportCSV = () =>
    reportsApi.exportCSV(params)
      .then((blob: any) => {
        const url = URL.createObjectURL(blob);
        const a   = document.createElement('a');
        a.href = url; a.download = 'opsyn-staff-report.csv'; a.click();
        URL.revokeObjectURL(url);
      })
      .catch(() => {});

  const Loading = () => <div style={{ color: 'var(--color-text-muted)', fontSize: 12, padding: 20 }}>Loading…</div>;

  return (
    <Page>

        {/* Header */}
        <PageHeader
        title="Operational Intelligence"
        lede={<>Workforce &amp; Network Analytics · Live Data</>}
        primary={<><input type="date" aria-label="From date" max={dateTo || undefined} value={dateFrom} onChange={e => setDateFrom(e.target.value)}
              style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 8, padding: '6px 10px', color: 'var(--color-text-primary)', fontFamily: 'var(--font-body)', fontSize: 12, outline: 'none' }} /><span aria-hidden="true" style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>→</span><input type="date" aria-label="To date" min={dateFrom || undefined} value={dateTo} onChange={e => setDateTo(e.target.value)}
              style={{ background: 'var(--surface)', border: '1px solid var(--color-border)', borderRadius: 8, padding: '6px 10px', color: 'var(--color-text-primary)', fontFamily: 'var(--font-body)', fontSize: 12, outline: 'none' }} /><Button variant="secondary" size="sm" onClick={exportCSV}>Export CSV</Button></>}
      />

        {/* Tab bar */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 20, flexWrap: 'wrap' }}>
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              style={{
                padding: '6px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600,
                cursor: 'pointer', fontFamily: 'var(--font-body)',
                border:      tab === t.key ? '1px solid rgba(0,194,168,.3)' : '1px solid var(--color-border)',
                background:  tab === t.key ? 'rgba(0,194,168,.08)' : 'var(--surface)',
                color:       tab === t.key ? 'var(--color-teal)' : 'var(--color-text-muted)',
                transition:  'all .15s',
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Overview ── */}
        {tab === 'overview' && (sumLoading ? <Loading /> : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 14 }}>
              <KpiTile label="Total Personnel"  value={d.staff_total ?? 0}      color="var(--color-teal)" />
              <KpiTile label="Active Personnel" value={d.staff_active ?? 0}     color="var(--color-green)" />
              <KpiTile label="Outages Resolved" value={d.outages_resolved ?? 0} color="var(--color-red)" />
              <KpiTile label="Tasks Completed"  value={d.tasks_completed ?? 0}  color="var(--color-indigo)" />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 18 }}>
              <KpiTile label="Staff Added"    value={d.staff_added ?? 0}                                         color="var(--color-amber)" />
              <KpiTile label="Avg MTTR (hrs)" value={d.avg_mttr_hours != null ? `${d.avg_mttr_hours}h` : 'N/A'} color="var(--color-teal)" />
              <KpiTile label="Active Sites"   value={d.active_sites ?? 0}                                        color="var(--color-text-primary)" />
              <KpiTile label="Network Nodes"  value={d.active_network_nodes ?? 0}                                color="var(--color-text-primary)" />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <Card>
                <CardTitle>Workforce Snapshot</CardTitle>
                <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
                  {[
                    { label: 'Total',  val: d.staff_total ?? 0,       c: 'var(--color-teal)' },
                    { label: 'Active', val: d.staff_active ?? 0,      c: 'var(--color-green)' },
                    { label: 'Added',  val: `+${d.staff_added ?? 0}`, c: 'var(--color-amber)' },
                  ].map(s => (
                    <div key={s.label} style={{ flex: 1, padding: 10, background: 'var(--color-surface-2)', borderRadius: 8, textAlign: 'center' }}>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 20, fontWeight: 600, color: s.c }}>{s.val}</div>
                      <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 2 }}>{s.label}</div>
                    </div>
                  ))}
                </div>
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                  Active rate: <span style={{ color: 'var(--color-green)', fontWeight: 600 }}>
                    {d.staff_total > 0 ? Math.round((d.staff_active / d.staff_total) * 100) : 0}%
                  </span>
                </div>
                <Pbar fill="var(--color-green)" pct={d.staff_total > 0 ? Math.round((d.staff_active / d.staff_total) * 100) : 0} />
              </Card>
              <Card>
                <CardTitle>Task Completion Rate</CardTitle>
                <div style={{ textAlign: 'center', padding: '16px 0' }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 48, fontWeight: 700, color: 'var(--color-teal)' }}>
                    {Math.round((d.task_completion_rate ?? 0) * 100)}%
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 4 }}>{d.tasks_completed ?? 0} tasks completed</div>
                </div>
                <Pbar fill="var(--color-teal)" pct={Math.round((d.task_completion_rate ?? 0) * 100)} />
                {d.avg_mttr_hours != null && (
                  <div style={{ marginTop: 14, padding: '8px 12px', background: 'var(--color-surface-2)', borderRadius: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>Mean Time to Resolution</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--color-teal)', fontSize: 13 }}>{d.avg_mttr_hours}h</span>
                  </div>
                )}
              </Card>
            </div>
          </>
        ))}

        {/* ── Staff ── */}
        {tab === 'staff' && (staffLoading ? <Loading /> : (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <Card>
              <CardTitle>By Department</CardTitle>
              {(sb.by_department ?? []).length === 0 ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>No data</div>
                : (sb.by_department ?? []).map((r: any) => <BreakdownBar key={r.name} label={r.name} count={r.count} total={sb.total ?? 1} color="var(--color-teal)" />)}
            </Card>
            <Card>
              <CardTitle>By Region</CardTitle>
              {(sb.by_region ?? []).length === 0 ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>No data</div>
                : (sb.by_region ?? []).map((r: any) => <BreakdownBar key={r.name} label={r.name} count={r.count} total={sb.total ?? 1} color="var(--color-indigo)" />)}
            </Card>
            <Card>
              <CardTitle>By Employment Type</CardTitle>
              {(sb.by_employment_type ?? []).length === 0 ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>No data</div>
                : (sb.by_employment_type ?? []).map((r: any) => <BreakdownBar key={r.type} label={r.type} count={r.count} total={sb.total ?? 1} color="var(--color-amber)" />)}
            </Card>
            <Card>
              <CardTitle>By Status</CardTitle>
              {(sb.by_status ?? []).length === 0 ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>No data</div>
                : (sb.by_status ?? []).map((r: any) => (
                  <BreakdownBar key={r.status} label={r.status} count={r.count} total={sb.total ?? 1}
                    color={r.status === 'active' ? 'var(--color-green)' : r.status === 'terminated' ? 'var(--color-red)' : 'var(--color-text-muted)'}
                  />
                ))}
            </Card>
          </div>
        ))}

        {/* ── Tasks ── */}
        {tab === 'tasks' && (tasksLoading ? <Loading /> : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginBottom: 14 }}>
              <KpiTile label="Total Tasks" value={tb.total ?? 0}    color="var(--color-text-primary)" />
              <KpiTile label="Overdue"     value={tb.overdue ?? 0}  color="var(--color-red)" />
              <KpiTile label="Completion"
                value={tb.total > 0 ? `${Math.round(((tb.by_status ?? []).find((s: any) => s.status === 'done')?.count ?? 0) / tb.total * 100)}%` : '0%'}
                color="var(--color-green)"
              />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <Card>
                <CardTitle>By Status</CardTitle>
                {(tb.by_status ?? []).map((r: any) => (
                  <BreakdownBar key={r.status} label={r.status} count={r.count} total={tb.total ?? 1} color={TASK_STATUS_COLORS[r.status] ?? 'var(--color-teal)'} />
                ))}
              </Card>
              <Card>
                <CardTitle>By Department</CardTitle>
                {(tb.by_department ?? []).length === 0
                  ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>Tasks not yet assigned to depts</div>
                  : (tb.by_department ?? []).map((r: any) => <BreakdownBar key={r.name} label={r.name} count={r.count} total={tb.total ?? 1} color="var(--color-teal)" />)}
              </Card>
            </div>
          </>
        ))}

        {/* ── Projects ── */}
        {tab === 'projects' && (projLoading ? <Loading /> : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 14, marginBottom: 14 }}>
              <KpiTile label="Total Projects" value={pb.total ?? 0} color="var(--color-indigo)" />
              <KpiTile label="Active"         value={(pb.by_status ?? []).find((s: any) => s.status === 'active')?.count ?? 0} color="var(--color-green)" />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <Card>
                <CardTitle>By Type</CardTitle>
                {(pb.by_type ?? []).length === 0 ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>No projects yet</div>
                  : (pb.by_type ?? []).map((r: any) => <BreakdownBar key={r.type} label={r.type} count={r.count} total={pb.total ?? 1} color={PROJECT_TYPE_COLORS[r.type] ?? 'var(--color-teal)'} />)}
              </Card>
              <Card>
                <CardTitle>Pipeline Status</CardTitle>
                {(pb.by_pipeline_status ?? []).length === 0 ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>No data</div>
                  : (pb.by_pipeline_status ?? []).map((r: any) => <BreakdownBar key={r.status} label={r.status} count={r.count} total={pb.total ?? 1} color="var(--color-indigo)" />)}
              </Card>
            </div>
          </>
        ))}

        {/* ── Outages & MTTR ── */}
        {tab === 'outages' && (mttrLoading ? <Loading /> : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 14, marginBottom: 14 }}>
              <KpiTile label="Total Resolved"   value={mt.total_resolved ?? 0}                                               color="var(--color-green)" />
              <KpiTile label="Overall Avg MTTR" value={mt.overall_mttr_hours != null ? `${mt.overall_mttr_hours}h` : 'N/A'} color="var(--color-teal)" />
            </div>
            <Card>
              <CardTitle>MTTR by Severity</CardTitle>
              {Object.keys(mt.by_severity ?? {}).length === 0
                ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>No resolved outages in this period</div>
                : (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
                    {Object.entries(mt.by_severity ?? {}).map(([sev, data]: any) => (
                      <div key={sev} style={{ padding: 14, background: 'var(--color-surface-2)', borderRadius: 10, border: `1px solid ${SEVERITY_BG[sev] ?? 'rgba(100,116,139,.1)'}` }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
                          <div style={{ width: 8, height: 8, borderRadius: '50%', background: SEVERITY_COLORS[sev] ?? 'var(--color-text-muted)' }} />
                          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary)', textTransform: 'capitalize' }}>{sev}</span>
                          <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 4, background: SEVERITY_BG[sev] ?? 'rgba(100,116,139,.1)', color: SEVERITY_COLORS[sev] ?? 'var(--color-text-muted)' }}>
                            {data.count} incident{data.count !== 1 ? 's' : ''}
                          </span>
                        </div>
                        <div style={{ display: 'flex', gap: 12 }}>
                          <div style={{ textAlign: 'center' }}>
                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 600, color: SEVERITY_COLORS[sev] ?? 'var(--color-text-primary)' }}>{data.avg_hours}h</div>
                            <div style={{ fontSize: 9, color: 'var(--color-text-muted)' }}>Avg MTTR</div>
                          </div>
                          <div style={{ textAlign: 'center' }}>
                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 600, color: 'var(--color-text-muted)' }}>{data.max_hours}h</div>
                            <div style={{ fontSize: 9, color: 'var(--color-text-muted)' }}>Max MTTR</div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )
              }
            </Card>
          </>
        ))}

        {/* ── Infrastructure ── */}
        {tab === 'infrastructure' && (infraLoading ? <Loading /> : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginBottom: 14 }}>
              <KpiTile label="Sites"             value={(ir.sites ?? []).length}                                                              color="var(--color-teal)" />
              <KpiTile label="Unresolved Alerts" value={Object.values(ir.alert_summary ?? {}).reduce((a: any, b: any) => a + b, 0) as number} color="var(--color-red)" />
              <KpiTile label="Critical Alerts"   value={(ir.alert_summary ?? {})['critical'] ?? 0}                                           color="var(--color-red)" />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <Card style={{ padding: 0 }}>
                <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 13, color: 'var(--color-text-primary)', padding: '12px 14px 0' }}>
                  Site Utilisation
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr>{['Site', 'Type', 'Used/Total', 'Utilisation'].map(h => <th key={h} style={TH}>{h}</th>)}</tr></thead>
                  <tbody>
                    {(ir.sites ?? []).length === 0
                      ? <tr><td colSpan={4} style={{ textAlign: 'center', padding: 30, color: 'var(--color-text-muted)', fontSize: 12 }}>No sites yet</td></tr>
                      : (ir.sites ?? []).map((s: any) => {
                        const pct  = s.utilisation_pct ?? 0;
                        const barC = pct >= 90 ? 'var(--color-red)' : pct >= 70 ? 'var(--color-amber)' : 'var(--color-green)';
                        return (
                          <tr key={s.id}>
                            <td style={{ ...TD, fontWeight: 600, color: 'var(--color-text-primary)', fontSize: 12 }}>{s.name}</td>
                            <td style={TD}>
                              <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 4, background: 'rgba(0,194,168,.1)', color: 'var(--color-teal)', fontWeight: 600 }}>{s.site_type}</span>
                            </td>
                            <td style={{ ...TD, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-text-muted)' }}>{s.used}/{s.total}</td>
                            <td style={{ ...TD, minWidth: 100 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                <div style={{ flex: 1, height: 5, background: 'var(--color-border)', borderRadius: 3, overflow: 'hidden' }}>
                                  <div style={{ width: `${pct}%`, height: '100%', background: barC, borderRadius: 3 }} />
                                </div>
                                <span style={{ fontSize: 10, color: barC, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{pct}%</span>
                              </div>
                            </td>
                          </tr>
                        );
                      })
                    }
                  </tbody>
                </table>
              </Card>
              <Card>
                <CardTitle>Recent Capacity Alerts</CardTitle>
                {(ir.recent_alerts ?? []).length === 0
                  ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>No active alerts</div>
                  : (ir.recent_alerts ?? []).slice(0, 8).map((a: any) => (
                    <div key={a.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '7px 0', borderBottom: '1px solid var(--color-border)' }}>
                      <div>
                        <div style={{ fontSize: 11, color: 'var(--color-text-primary)', fontWeight: 500 }}>{a.site_name ?? a.node_name ?? 'Unknown'}</div>
                        <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 2 }}>{a.message}</div>
                      </div>
                      <span style={{
                        fontSize: 10, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
                        background: a.severity === 'critical' ? 'rgba(220,38,38,.1)' : 'rgba(245,158,11,.1)',
                        color:      a.severity === 'critical' ? 'var(--color-red)' : 'var(--color-amber)',
                      }}>
                        {a.severity}
                      </span>
                    </div>
                  ))
                }
              </Card>
            </div>
          </>
        ))}

        {/* ── Shifts ── */}
        {tab === 'shifts' && (shiftsLoading ? <Loading /> : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginBottom: 14 }}>
              <KpiTile label="Shift Types"    value={(sr.coverage ?? []).length}                                                               color="var(--color-indigo)" />
              <KpiTile label="Swap Requests"  value={Object.values(sr.swap_requests ?? {}).reduce((a: any, b: any) => a + b, 0) as number}     color="var(--color-amber)" />
              <KpiTile label="Approved Swaps" value={(sr.swap_requests ?? {})['approved'] ?? 0}                                                color="var(--color-green)" />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <Card>
                <CardTitle>On-Call Load (30 days)</CardTitle>
                {(sr.oncall_load ?? []).length === 0
                  ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>No on-call shifts recorded</div>
                  : (sr.oncall_load ?? []).map((r: any, i: number) => (
                    <BreakdownBar key={i} label={r.staff_name} count={r.oncall_shifts}
                      total={(sr.oncall_load ?? []).reduce((a: any, x: any) => a + x.oncall_shifts, 0) || 1}
                      color="var(--color-indigo)"
                    />
                  ))
                }
              </Card>
              <Card>
                <CardTitle>Swap Request Status</CardTitle>
                {Object.entries(sr.swap_requests ?? {}).length === 0
                  ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>No swap requests in 30 days</div>
                  : Object.entries(sr.swap_requests ?? {}).map(([status, count]: any) => (
                    <div key={status} style={{ display: 'flex', justifyContent: 'space-between', padding: '7px 0', borderBottom: '1px solid var(--color-border)' }}>
                      <span style={{ fontSize: 12, color: 'var(--color-text-primary)', textTransform: 'capitalize' }}>{status}</span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--color-amber)', fontSize: 13 }}>{count}</span>
                    </div>
                  ))
                }
              </Card>
            </div>
          </>
        ))}

        {/* ── SLA Compliance ── */}
        {tab === 'sla' && (slaLoading ? <Loading /> : (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <Card>
              <CardTitle>Breach Rate by Severity (90 days)</CardTitle>
              {(sl.by_severity ?? []).length === 0
                ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>No outage SLA data yet</div>
                : (sl.by_severity ?? []).map((r: any) => (
                  <div key={r.severity} style={{ marginBottom: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-primary)', textTransform: 'capitalize' }}>{r.severity}</span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: r.breach_rate_pct >= 50 ? 'var(--color-red)' : 'var(--color-green)', fontWeight: 700 }}>
                        {r.breach_rate_pct}% breached
                      </span>
                    </div>
                    <div style={{ height: 6, background: 'var(--color-surface-2)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{ width: `${r.breach_rate_pct}%`, height: '100%', background: r.breach_rate_pct >= 50 ? 'var(--color-red)' : 'var(--color-amber)', borderRadius: 3 }} />
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 3 }}>
                      {r.breached}/{r.total} incidents · {r.avg_mins_to_breach != null ? `avg ${r.avg_mins_to_breach} min to breach` : 'n/a'}
                    </div>
                  </div>
                ))
              }
            </Card>
            <Card>
              <CardTitle>Worst OLTs (breach rate)</CardTitle>
              {(sl.worst_olts ?? []).length === 0
                ? <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>No OLT data yet</div>
                : (sl.worst_olts ?? []).map((r: any, i: number) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: '1px solid var(--color-border)' }}>
                    <div>
                      <div style={{ fontSize: 12, color: 'var(--color-text-primary)', fontWeight: 500, fontFamily: 'var(--font-mono)' }}>{r.olt_reference}</div>
                      <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 1 }}>{r.total_outages} outages · avg {r.avg_mttr_hours}h MTTR</div>
                    </div>
                    <span style={{
                      fontSize: 11, padding: '2px 8px', borderRadius: 4, fontWeight: 700,
                      background: r.breach_rate_pct >= 50 ? 'rgba(220,38,38,.1)' : 'rgba(245,158,11,.1)',
                      color:      r.breach_rate_pct >= 50 ? 'var(--color-red)' : 'var(--color-amber)',
                    }}>
                      {r.breach_rate_pct}%
                    </span>
                  </div>
                ))
              }
            </Card>
          </div>
        ))}

      
    </Page>
  );
}
