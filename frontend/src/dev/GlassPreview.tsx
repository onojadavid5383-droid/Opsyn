// ============================================================
// DEV ONLY — glass system preview (/glass-preview.html).
// Every glass component over the busiest realistic backdrop: a solid, dense
// outage table. Sample rows are illustrative, not live data. Used for the
// Phase 2 visual review in both themes; never shipped.
// ============================================================

import {
  Cable, CheckCheck, Circle, Diamond, Ellipsis, Filter, FolderKanban, Forward,
  LayoutDashboard, Layers, ListChecks, LocateFixed, Map as MapIcon, Minus, Moon,
  Network, Octagon, Plus, Route, Ruler, Server, Sun, Trash2, Triangle, UserPlus, Users,
} from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import {
  GlassButton, GlassCommandPalette, GlassContextMenu, GlassInspector, GlassMenu,
  GlassModal, GlassPopover, GlassSelect, GlassSidebar, GlassToolbar,
  GlassToolbarDivider, useCommandPaletteShortcut, type GlassMenuEntry, type PaletteCommand,
} from '../components/glass';
import { useThemeStore } from '../store/theme.store';
import s from './GlassPreview.module.css';

type Severity = 'critical' | 'high' | 'warning' | 'low';

const SEVERITY_ICON = { critical: Octagon, high: Triangle, warning: Diamond, low: Circle } as const;
const SEVERITY_LABEL: Record<Severity, string> = { critical: 'Critical', high: 'High', warning: 'Warning', low: 'Low' };

const ROWS: { ref: string; title: string; asset: string; region: string; sev: Severity; subs: number; age: string }[] = [
  { ref: 'OUT-2026-0418', title: 'Feeder cut — Lekki Phase 1 duct',        asset: 'OLT-LAG-03/PON-7',  region: 'Lagos',         sev: 'critical', subs: 412, age: '1h 12m' },
  { ref: 'OUT-2026-0417', title: 'Splitter box offline',                   asset: 'FAT-LKJ-114',       region: 'Lagos',         sev: 'high',     subs: 32,  age: '2h 40m' },
  { ref: 'OUT-2026-0415', title: 'High optical loss on drop segment',      asset: 'FDT-ABJ-021',       region: 'Abuja',         sev: 'warning',  subs: 16,  age: '5h 03m' },
  { ref: 'OUT-2026-0414', title: 'Cabinet door alarm',                     asset: 'CAB-KAN-008',       region: 'Kano',          sev: 'low',      subs: 0,   age: '6h 21m' },
  { ref: 'OUT-2026-0412', title: 'ONU flapping on PON port',               asset: 'OLT-ABJ-01/PON-2',  region: 'Abuja',         sev: 'high',     subs: 64,  age: '9h 47m' },
  { ref: 'OUT-2026-0409', title: 'Power supply on battery',                asset: 'POP-PHC-02',        region: 'Port Harcourt', sev: 'warning',  subs: 0,   age: '11h 05m' },
  { ref: 'OUT-2026-0406', title: 'Closure water ingress reported',         asset: 'CLS-LAG-041',       region: 'Lagos',         sev: 'high',     subs: 128, age: '14h 30m' },
  { ref: 'OUT-2026-0402', title: 'Duct blockage — planned reroute',        asset: 'RTE-IKJ-12',        region: 'Lagos',         sev: 'low',      subs: 0,   age: '1d 2h' },
  { ref: 'OUT-2026-0399', title: 'Aerial span sag near junction',          asset: 'POLE-ABJ-2291',     region: 'Abuja',         sev: 'warning',  subs: 8,   age: '1d 6h' },
  { ref: 'OUT-2026-0391', title: 'Core uplink degraded',                   asset: 'AGG-LAG-01',        region: 'Lagos',         sev: 'critical', subs: 1904, age: '1d 9h' },
];

function SeverityCell({ sev }: { sev: Severity }) {
  const Icon = SEVERITY_ICON[sev];
  return (
    <span className={`${s.sev} ${s[sev]}`}>
      <Icon size={14} strokeWidth={2.25} aria-hidden="true" />
      {SEVERITY_LABEL[sev]}
    </span>
  );
}

export default function GlassPreview() {
  const { resolved, setPreference } = useThemeStore();
  const [modal, setModal] = useState<null | 'task' | 'dialog'>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [region, setRegion] = useState('');
  const [taskStatus, setTaskStatus] = useState('in_progress');
  const [layersOn, setLayersOn] = useState(true);

  const openPalette = useCallback(() => setPaletteOpen(true), []);
  useCommandPaletteShortcut(openPalette);

  const rowActions: GlassMenuEntry[] = [
    { id: 'ack', label: 'Acknowledge', icon: <CheckCheck size={16} />, onSelect: () => {} },
    { id: 'assign', label: 'Assign to…', icon: <UserPlus size={16} />, onSelect: () => {} },
    { id: 'open', label: 'Open task', icon: <ListChecks size={16} />, shortcut: 'Enter', onSelect: () => setModal('task') },
    { type: 'separator' },
    { id: 'del', label: 'Close as duplicate', icon: <Trash2 size={16} />, danger: true, onSelect: () => setModal('dialog') },
  ];

  const commands = useMemo<PaletteCommand[]>(() => [
    { id: 'p-dash',  group: 'Pages',  label: 'Command Center',        detail: '/dashboard',     icon: <LayoutDashboard size={16} />, onSelect: () => {} },
    { id: 'p-out',   group: 'Pages',  label: 'Alarms & outages',      detail: '/outage',        icon: <Octagon size={16} />,        onSelect: () => {} },
    { id: 'p-map',   group: 'Pages',  label: 'Network map',           detail: '/infrastructure', icon: <MapIcon size={16} />,        onSelect: () => {} },
    { id: 'p-tasks', group: 'Pages',  label: 'Tasks',                 detail: '/tasks',         icon: <ListChecks size={16} />,     onSelect: () => {} },
    { id: 'p-fttx',  group: 'Pages',  label: 'FTTx Designer',         detail: '/fttx-designer', icon: <Network size={16} />,        onSelect: () => {} },
    { id: 't-142',   group: 'Tasks',  label: 'Replace drop cable at FAT-LKJ-114', hint: 'TSK-2026-0142', icon: <ListChecks size={16} />, onSelect: () => setModal('task') },
    { id: 'a-olt',   group: 'Assets', label: 'OLT-LAG-03',            detail: 'OLT · Lekki POP', keywords: ['olt lagos'],  icon: <Server size={16} />,  onSelect: () => {} },
    { id: 'a-rte',   group: 'Assets', label: 'RTE-IKJ-12',            detail: 'Route · 4.2 km',  keywords: ['route ikeja'], icon: <Route size={16} />,   onSelect: () => {} },
  ], []);

  return (
    <div className={`${s.page} liquid-glass-backdrop`}>
      <header className={s.bar}>
        <h1>Glass system preview</h1>
        <p>Dev only · sample data · Ctrl K opens the command palette</p>
        <button className={s.barBtn} onClick={() => setModal('task')}>Open task popup</button>
        <button className={s.barBtn} onClick={() => setModal('dialog')}>Open dialog</button>
        <button className={s.barBtn} onClick={openPalette}>Command palette</button>
        <button className={s.barBtn} onClick={() => setSidebarOpen(o => !o)}>Toggle sidebar</button>
        <button className={s.barBtn} onClick={() => setInspectorOpen(o => !o)}>Toggle inspector</button>
        <button
          className={s.barBtn}
          aria-label={`Switch to ${resolved === 'dark' ? 'light' : 'dark'} theme`}
          onClick={() => setPreference(resolved === 'dark' ? 'light' : 'dark')}
        >
          {resolved === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </header>

      <main className={s.stage}>
        <GlassSidebar open={sidebarOpen} onOpenChange={setSidebarOpen} label="Operations" title="Operations" width={280}>
          <div className={s.navGroup}>
            <div className={s.navGroupLabel}>Monitor</div>
            <button className={`liquid-glass-item ${s.navItem}`}><LayoutDashboard size={16} aria-hidden="true" />Command Center</button>
            <button className={`liquid-glass-item ${s.navItem}`} aria-current="page"><Octagon size={16} aria-hidden="true" />Alarms &amp; outages<span className={s.badge}>2</span></button>
            <button className={`liquid-glass-item ${s.navItem}`}><MapIcon size={16} aria-hidden="true" />Network map</button>
          </div>
          <div className={s.navGroup}>
            <div className={s.navGroupLabel}>Operate</div>
            <button className={`liquid-glass-item ${s.navItem}`}><ListChecks size={16} aria-hidden="true" />Tasks</button>
            <button className={`liquid-glass-item ${s.navItem}`}><FolderKanban size={16} aria-hidden="true" />Projects</button>
            <button className={`liquid-glass-item ${s.navItem}`}><Users size={16} aria-hidden="true" />Customers</button>
          </div>
        </GlassSidebar>

        <section className={s.panel} aria-label="Active outages">
          <div className={s.panelHead}>
            <h2>Active outages <span className={s.count}>· 10</span></h2>
            <GlassSelect
              ariaLabel="Region"
              placeholder="All regions"
              value={region}
              onChange={setRegion}
              compact
              style={{ width: 180 }}
              options={[
                { label: 'Lagos', value: 'lagos' },
                { label: 'Abuja', value: 'abuja' },
                { label: 'Kano', value: 'kano' },
                { label: 'Port Harcourt', value: 'phc' },
              ]}
            />
            <GlassPopover
              title="Filter outages"
              renderTrigger={p => <button {...p} className={s.filterBtn}><Filter size={14} aria-hidden="true" />Filters</button>}
            >
              {({ close }) => (
                <>
                  <GlassSelect label="Severity" value="high" onChange={() => {}} options={[
                    { label: 'Critical', value: 'critical' }, { label: 'High and above', value: 'high' },
                    { label: 'Warning and above', value: 'warning' }, { label: 'All', value: 'low' },
                  ]} />
                  <GlassSelect label="Age" value="24h" onChange={() => {}} options={[
                    { label: 'Last hour', value: '1h' }, { label: 'Last 24 hours', value: '24h' }, { label: 'Last 7 days', value: '7d' },
                  ]} />
                  <button className={`${s.footerBtn} ${s.primary}`} onClick={close}>Apply filters</button>
                </>
              )}
            </GlassPopover>
          </div>

          <table className={s.table}>
            <thead>
              <tr>
                <th scope="col">Severity</th>
                <th scope="col">Reference</th>
                <th scope="col">Summary</th>
                <th scope="col">Asset</th>
                <th scope="col">Region</th>
                <th scope="col" className={s.num}>Subscribers</th>
                <th scope="col" className={s.num}>Age</th>
                <th scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map(r => (
                <GlassContextMenu key={r.ref} label={`Actions for ${r.ref}`} items={rowActions}>
                  {bind => (
                    <tr tabIndex={0} {...bind}>
                      <td><SeverityCell sev={r.sev} /></td>
                      <td className={s.mono}>{r.ref}</td>
                      <td>{r.title}</td>
                      <td className={s.mono}>{r.asset}</td>
                      <td>{r.region}</td>
                      <td className={s.num}>{r.subs.toLocaleString()}</td>
                      <td className={s.num}>{r.age}</td>
                      <td>
                        <GlassMenu
                          label={`Actions for ${r.ref}`}
                          placement="bottom-end"
                          items={rowActions}
                          renderTrigger={p => (
                            <button {...p} className={s.rowMenu} aria-label={`Actions for ${r.ref}`}>
                              <Ellipsis size={16} aria-hidden="true" />
                            </button>
                          )}
                        />
                      </td>
                    </tr>
                  )}
                </GlassContextMenu>
              ))}
            </tbody>
          </table>
        </section>

        <div className={s.mapControls}>
          <GlassToolbar label="Map controls" orientation="vertical">
            <GlassButton shape="icon" aria-label="Zoom in" icon={<Plus size={16} />} />
            <GlassButton shape="icon" aria-label="Zoom out" icon={<Minus size={16} />} />
            <GlassToolbarDivider />
            <GlassButton shape="icon" aria-label="Layers" aria-pressed={layersOn} onClick={() => setLayersOn(v => !v)} icon={<Layers size={16} />} />
            <GlassButton shape="icon" aria-label="Measure distance" icon={<Ruler size={16} />} />
            <GlassButton shape="icon" aria-label="Locate me" icon={<LocateFixed size={16} />} />
          </GlassToolbar>
        </div>

        <GlassInspector
          open={inspectorOpen}
          onOpenChange={setInspectorOpen}
          label="Asset inspector"
          title="FAT-LKJ-114"
          subtitle="Splitter box · 1:16 · Lekki"
          width={300}
        >
          <dl className={s.kv}>
            <dt>State</dt><dd><SeverityCell sev="high" /></dd>
            <dt>Parent FDT</dt><dd className={s.mono}>FDT-LKJ-009</dd>
            <dt>Feeder</dt><dd className={s.mono}>OLT-LAG-03/PON-7</dd>
            <dt>Ports used</dt>
            <dd>14 of 16<div className={s.meter}><span style={{ width: '87.5%' }} /></div></dd>
          </dl>
          <div className={s.inspectorSection}>
            <h3>Path to OLT</h3>
            <dl className={s.kv}>
              <dt>Hops</dt><dd>3</dd>
              <dt>Fiber length</dt><dd>2.84 km</dd>
              <dt>Budget margin</dt><dd>4.1 dB</dd>
            </dl>
          </div>
        </GlassInspector>

        <GlassToolbar label="Bulk actions" className={s.bulkBar}>
          <strong>3 selected</strong>
          <GlassButton icon={<CheckCheck size={16} />}>Acknowledge</GlassButton>
          <GlassButton icon={<UserPlus size={16} />}>Assign</GlassButton>
          <GlassButton icon={<Cable size={16} />}>Create task</GlassButton>
        </GlassToolbar>
      </main>

      {/* Task popup — the workspace variant */}
      <GlassModal
        open={modal === 'task'}
        onClose={() => setModal(null)}
        size="workspace"
        eyebrow={<span className={s.ticket}>TSK-2026-0142</span>}
        title="Replace damaged drop cable at FAT-LKJ-114"
        description="Opened from OUT-2026-0417 · Field Operations · due today 18:00"
        footer={
          <>
            <GlassMenu
              label="More task actions"
              placement="top-start"
              items={[
                { id: 'fwd', label: 'Forward to…', icon: <Forward size={16} />, onSelect: () => {} },
                { id: 'esc', label: 'Escalate', icon: <Triangle size={16} />, onSelect: () => {} },
                { type: 'separator' },
                { id: 'del', label: 'Delete task', icon: <Trash2 size={16} />, danger: true, onSelect: () => {} },
              ]}
              renderTrigger={p => <button {...p} className={s.footerBtn}>More actions</button>}
            />
            <button className={s.footerBtn} onClick={() => setModal(null)}>Close</button>
            <button className={`${s.footerBtn} ${s.primary}`} onClick={() => setModal(null)}>Mark done</button>
          </>
        }
      >
        <div className={s.taskGrid}>
          <div className={s.taskMain}>
            <p>
              Drop cable to customer premises LKJ-114-07 cut during road works. Splice at the FAT,
              replace 60 m of drop, and confirm ONU light levels at the premises before closing.
            </p>
            <ol className={s.timeline}>
              <li><time>Today 09:14</time>Created from outage OUT-2026-0417 by NOC — Adaeze O.</li>
              <li><time>Today 09:31</time>Assigned to Field Team B</li>
              <li><time>Today 11:02</time>Started — crew on site, 60 m drop required</li>
            </ol>
          </div>
          <div>
            <GlassSelect label="Status" value={taskStatus} onChange={setTaskStatus} options={[
              { label: 'New', value: 'new' }, { label: 'In progress', value: 'in_progress' },
              { label: 'In review', value: 'review' }, { label: 'Blocked', value: 'blocked' },
            ]} />
            <GlassSelect label="Assignee" value="team-b" onChange={() => {}} options={[
              { label: 'Field Team A', value: 'team-a' }, { label: 'Field Team B', value: 'team-b' },
            ]} />
            <dl className={s.kv}>
              <dt>Priority</dt><dd><SeverityCell sev="high" /></dd>
              <dt>Asset</dt><dd className={s.mono}>FAT-LKJ-114</dd>
              <dt>Estimate</dt><dd>3 h</dd>
            </dl>
          </div>
        </div>
      </GlassModal>

      {/* Ordinary dialog */}
      <GlassModal
        open={modal === 'dialog'}
        onClose={() => setModal(null)}
        role="alertdialog"
        size="sm"
        title="Close OUT-2026-0417 as a duplicate?"
        description="It will be linked to OUT-2026-0418 and removed from the active list."
        footer={
          <>
            <button className={s.footerBtn} onClick={() => setModal(null)}>Keep open</button>
            <button className={`${s.footerBtn} ${s.primary}`} onClick={() => setModal(null)}>Close as duplicate</button>
          </>
        }
      >
        <GlassSelect label="Duplicate of" value="0418" onChange={() => {}} options={[
          { label: 'OUT-2026-0418 — Feeder cut, Lekki', value: '0418' },
          { label: 'OUT-2026-0406 — Closure water ingress', value: '0406' },
        ]} />
      </GlassModal>

      <GlassCommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} commands={commands} />
    </div>
  );
}
