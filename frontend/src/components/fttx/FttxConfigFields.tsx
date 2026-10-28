import { useId, useState } from 'react';
import { Input, Select } from '../ui';
import { ChevronDown } from 'lucide-react';
import { CASCADE_OPTIONS, DEPLOYMENT_OPTIONS, PON_OPTIONS, type FttxSettings } from './fttxSettings';
import styles from './FttxConfigFields.module.css';

interface Props {
  value: FttxSettings; onChange: (next: FttxSettings) => void; showProject?: boolean;
  unavailableDeployments?: string[]; deploymentNote?: string;
}

const LABELS: Record<string, string> = {
  b2b_routing_mode:'Aerial box-to-box path',
  allow_documented_b2b_exceptions:'Allow documented cable-length exceptions',
  coverage_pct:'Coverage (%)', growth_reserve_pct:'Growth reserve (%)', max_box_to_box_distance:'Maximum box-to-box distance (m)',
  max_box_to_customer_distance:'Maximum customer drop (m)', drop_length_tolerance:'Drop length tolerance (m)',
  snap_offset_distance:'Structure snap offset (m)', fat_offset_radius:'FAT placement radius (m)', splitter_pattern:'Splitter pattern',
  marker_interval_m:'Cable marker interval (m)', pole_max_spacing_m:'Maximum pole spacing (m)',
  pole_proposal_search_radius_m:'Pole proposal search radius (m)', ug_spacing_m:'Underground structure spacing (m)',
  ug_duct_diameter_mm:'Underground duct diameter (mm)', ug_duct_ways:'Underground duct ways', ug_spare_capacity_pct:'Spare duct capacity (%)',
  dr_spacing_m:'Drainage splitter spacing (m)', dr_duct_diameter_mm:'Drainage duct diameter (mm)', dr_duct_ways:'Drainage duct ways',
  hy_aerial_field:'Hybrid aerial zone field', hy_aerial_value:'Hybrid aerial zone value', olt_launch_power_dbm:'OLT launch power (dBm)',
  optical_splice_loss_db:'Splice loss (dB)', optical_connector_loss_db:'Connector loss (dB)',
  optical_engineering_margin_db:'Engineering margin (dB)', optical_margin_pass_db:'Pass margin threshold (dB)',
  optical_margin_marginal_db:'Marginal threshold (dB)', ug_existing_handholes_layer:'Existing handholes layer key',
  ug_existing_manholes_layer:'Existing manholes layer key', dr_channel_layer:'Drainage channel layer key', hy_boundary_layer:'Hybrid boundary layer key',
};
const GROUPS: [string, string[]][] = [
  ['Placement & coverage',['coverage_pct','growth_reserve_pct','max_box_to_box_distance','max_box_to_customer_distance','drop_length_tolerance','snap_offset_distance','fat_offset_radius','splitter_pattern','enable_closure_generation','fast_mode']],
  ['Aerial network',['b2b_routing_mode','marker_interval_m','allow_proposed_poles','pole_max_spacing_m','pole_proposal_search_radius_m']],
  ['Engineering exceptions',['allow_documented_b2b_exceptions']],
  ['Underground network',['ug_infrastructure_type','ug_spacing_m','ug_routing_mode','ug_duct_type','ug_duct_diameter_mm','ug_duct_ways','ug_installation_method','ug_spare_capacity_pct','ug_existing_handholes_layer','ug_existing_manholes_layer']],
  ['Drainage network',['dr_channel_layer','dr_spacing_m','dr_duct_type','dr_duct_diameter_mm','dr_duct_ways']],
  ['Hybrid deployment',['hy_boundary_layer','hy_aerial_field','hy_aerial_value']],
  ['Duct occupancy',['occupancy_enabled','occupancy_gpkg_path']],
  ['Optical budget',['optical_enabled','olt_launch_power_dbm','optical_budget_class','optical_splice_loss_db','optical_connector_loss_db','optical_engineering_margin_db','optical_margin_pass_db','optical_margin_marginal_db','optical_splitter_library','optical_fiber_atten_db_per_km','optical_trace_table_enabled']],
];
const CONFIG_TABS = ['Deployment', 'Network Layers', 'Parameters', 'Optical', 'Execution'] as const;
const NUMERIC = new Set(['coverage_pct','growth_reserve_pct','max_box_to_box_distance','max_box_to_customer_distance','drop_length_tolerance','snap_offset_distance','fat_offset_radius','marker_interval_m','pole_max_spacing_m','pole_proposal_search_radius_m','ug_spacing_m','ug_duct_diameter_mm','ug_duct_ways','ug_spare_capacity_pct','dr_spacing_m','dr_duct_diameter_mm','dr_duct_ways','olt_launch_power_dbm','optical_splice_loss_db','optical_connector_loss_db','optical_engineering_margin_db','optical_margin_pass_db','optical_margin_marginal_db']);
const NOT_APPLIED = new Set(['growth_reserve_pct','fast_mode','optical_trace_table_enabled']);
const OPTIONS: Record<string, {label:string;value:string}[]> = {
  ug_infrastructure_type:[{label:'Handhole',value:'handhole'},{label:'Manhole',value:'manhole'}],
  ug_routing_mode:[{label:'Assisted',value:'assisted'},{label:'Strict',value:'strict'}],
  ug_duct_type:[{label:'HDPE',value:'HDPE'},{label:'uPVC',value:'uPVC'},{label:'GI',value:'GI'},{label:'Microduct',value:'Microduct'}],
  dr_duct_type:[{label:'HDPE',value:'HDPE'},{label:'uPVC',value:'uPVC'},{label:'GI',value:'GI'},{label:'Microduct',value:'Microduct'}],
  ug_installation_method:[{label:'Direct buried',value:'direct_buried'},{label:'Duct',value:'duct'}],
  optical_budget_class:[{label:'B+',value:'B+'},{label:'C+',value:'C+'},{label:'D',value:'D'}],
};

export function FttxConfigFields({ value, onChange, showProject = true, unavailableDeployments = [], deploymentNote }: Props) {
  const idPrefix = useId();
  const [activeTab, setActiveTab] = useState<(typeof CONFIG_TABS)[number]>('Deployment');
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set());
  const routeModeUnavailable = value.deployment_type !== 'aerial' || value.cascade_architecture === 'legacy';
  const toggleGroup = (title: string) => setCollapsedGroups(current => {
    const next = new Set(current);
    if (next.has(title)) next.delete(title);
    else next.add(title);
    return next;
  });
  const set = (key: string, next: string | boolean) => {
    const updated = { ...value, [key]: next };
    if (key === 'deployment_type' || key === 'cascade_architecture') {
      if (updated.deployment_type !== 'aerial' || updated.cascade_architecture === 'legacy') {
        updated.b2b_routing_mode = 'road';
      }
    }
    onChange(updated);
  };
  const renderField = (key: string) => {
    const label = LABELS[key] ?? key.replaceAll('_',' ').replace(/^./, c => c.toUpperCase());
    if (key === 'b2b_routing_mode') {
      const disabled = routeModeUnavailable;
      return <fieldset key={key} className={styles.routeField} disabled={disabled}>
        <legend>{label}</legend>
        <div className={styles.routeOptions}>
          <label className={styles.routeOption} data-selected={value.b2b_routing_mode === 'road'}>
            <input type="radio" name="b2b-routing-mode" value="road" checked={value.b2b_routing_mode === 'road'} onChange={() => set(key, 'road')} />
            <span><strong>Road network</strong><small>Follow the existing road route between devices.</small></span>
          </label>
          <label className={styles.routeOption} data-selected={value.b2b_routing_mode === 'pole_to_pole'}>
            <input type="radio" name="b2b-routing-mode" value="pole_to_pole" checked={value.b2b_routing_mode === 'pole_to_pole'} onChange={() => set(key, 'pole_to_pole')} />
            <span><strong>Pole to pole</strong><small>Route over snapped poles and connected support spans.</small></span>
          </label>
        </div>
        {!disabled && <p className={styles.routeNote}>Pole-to-pole needs connected poles in the uploaded layer. Unroutable hops are reported; the engine will not silently switch back to roads.</p>}
        {disabled && <p className={styles.routeNote}>Available for aerial PCC designs. Road routing remains active for this configuration.</p>}
      </fieldset>;
    }
    if (typeof value[key] === 'boolean') return <label key={key} title={NOT_APPLIED.has(key) ? 'Saved for compatibility; not applied by the web design engine.' : undefined} style={{display:'flex',alignItems:'center',gap:9,minHeight:38,color:'var(--chalk2)',fontSize:13,opacity:NOT_APPLIED.has(key) ? 0.62 : 1}}><input type="checkbox" checked={Boolean(value[key])} disabled={NOT_APPLIED.has(key)} onChange={e=>set(key,e.target.checked)}/>{label}{NOT_APPLIED.has(key)&&<small>(not active in web engine)</small>}</label>;
    const options = OPTIONS[key];
    if (options) return <Select key={key} label={label} value={String(value[key] ?? '')} onChange={v=>set(key,v)} options={options}/>;
    const isJson = key.startsWith('optical_') && (key.includes('library') || key.includes('atten'));
    if(key==='occupancy_gpkg_path') return <Input key={key} label={label} value="Managed by the server deployment" onChange={()=>{}} disabled hint="Browser runs cannot select or send a local GeoPackage path."/>;
    return <Input key={key} label={label} type={isJson||!NUMERIC.has(key) ? 'text' : 'number'} value={String(value[key] ?? '')} onChange={v=>set(key,v)} disabled={NOT_APPLIED.has(key)} placeholder={isJson ? 'Valid JSON object' : key==='splitter_pattern' ? '1x9,1x9,1x8' : undefined} hint={isJson ? 'Edit as JSON. Invalid JSON is not sent.' : NOT_APPLIED.has(key) ? 'This option is accepted and saved but currently has no effect in the web engine.' : undefined}/>;
  };
  const renderGroup = (title: string, content: React.ReactNode) => {
    const expanded = !collapsedGroups.has(title);
    const contentId = `${idPrefix}-${title.toLowerCase().replaceAll(/[^a-z0-9]+/g, '-')}`;
    return <section key={title} className={styles.configGroup}>
      <button type="button" className={styles.groupToggle} onClick={() => toggleGroup(title)} aria-expanded={expanded} aria-controls={contentId}>
        <span>{title}</span>
        <ChevronDown size={16} className={expanded ? styles.groupChevronExpanded : styles.groupChevron} aria-hidden="true" />
      </button>
      <div id={contentId} className={styles.groupContent} hidden={!expanded}>{content}</div>
    </section>;
  };
  const unavailable = unavailableDeployments.length > 0;
  const renderGroupByTitle = (title: string) => {
    const group = GROUPS.find(([groupTitle]) => groupTitle === title);
    if (!group) return null;
    const [groupTitle, keys] = group;
    return renderGroup(groupTitle, <>
      <div className="fttx-config-grid">{keys.map(renderField)}</div>
      {title==='Duct occupancy' && <p className="fttx-config-note">Occupancy needs a GeoPackage path; browser runs use uploaded layers and cannot read a local file path.</p>}
      {title==='Engineering exceptions' && <p className="fttx-config-note">Only enable this when long hops are confirmed to be geographically unavoidable. The design will complete with each over-limit cable flagged, its excess length and estimated cost recorded, and engineering sign-off still required.</p>}
    </>);
  };
  const tabContent: Record<(typeof CONFIG_TABS)[number], React.ReactNode> = {
    Deployment: <>
      {renderGroup('Deployment Type', <div className="fttx-config-grid"><Select label="Deployment Type" value={String(value.deployment_type)} onChange={v=>set('deployment_type',v)} options={DEPLOYMENT_OPTIONS.map(o=>({...o,disabled:unavailableDeployments.includes(o.value)}))} hint={deploymentNote}/></div>)}
      {renderGroup('Accessory Settings', <div className="fttx-config-grid">{['marker_interval_m'].map(renderField)}</div>)}
      {renderGroupByTitle('Duct occupancy')}
      {unavailable && <p className="fttx-config-note">This web engine currently runs aerial designs only. Other deployment settings can be saved for a compatible engine but cannot be run here yet.</p>}
    </>,
    'Network Layers': <>
      {renderGroup('Network Input Layers', <div className="fttx-config-grid">{['homepass_field_name','ug_existing_handholes_layer','ug_existing_manholes_layer','dr_channel_layer','hy_boundary_layer'].map(renderField)}</div>)}
      {renderGroup('Hybrid Zone', <div className="fttx-config-grid">{['hy_aerial_field','hy_aerial_value'].map(renderField)}</div>)}
    </>,
    Parameters: <>
      {showProject && renderGroup('Project identity', <div className="fttx-config-grid">
      <Input label="Project Name" value={String(value.project_name ?? '')} onChange={v=>set('project_name',v)} placeholder="DED report title"/>
      <Input label="Project Abbreviation" value={String(value.project_abbreviation ?? '')} onChange={v=>set('project_abbreviation',v)} placeholder="e.g. KKO" maxLength={10}/>
      </div>)}
      {renderGroup('Architecture', <>
      <div className="fttx-config-grid">
      <Select label="Cascade Architecture" value={String(value.cascade_architecture)} onChange={v=>set('cascade_architecture',v)} options={CASCADE_OPTIONS}/>
      {value.cascade_architecture !== 'legacy' && <Select label="PON Architecture" value={String(value.pon_architecture)} onChange={v=>set('pon_architecture',v)} options={PON_OPTIONS}/ >}
      </div>
      </>)}
      {renderGroup('Placement & coverage', <div className="fttx-config-grid">{['coverage_pct','growth_reserve_pct','max_box_to_box_distance','max_box_to_customer_distance','drop_length_tolerance','snap_offset_distance','fat_offset_radius','splitter_pattern','enable_closure_generation'].map(renderField)}</div>)}
      {renderGroup('Aerial network', <div className="fttx-config-grid">{['b2b_routing_mode','allow_proposed_poles','pole_max_spacing_m','pole_proposal_search_radius_m'].map(renderField)}</div>)}
      {renderGroup('Underground network', <div className="fttx-config-grid">{['ug_infrastructure_type','ug_spacing_m','ug_routing_mode','ug_duct_type','ug_duct_diameter_mm','ug_duct_ways','ug_installation_method','ug_spare_capacity_pct'].map(renderField)}</div>)}
      {renderGroup('Drainage network', <div className="fttx-config-grid">{['dr_spacing_m','dr_duct_type','dr_duct_diameter_mm','dr_duct_ways'].map(renderField)}</div>)}
    </>,
    Optical: renderGroupByTitle('Optical budget'),
    Execution: <>
      {renderGroup('Engineering exceptions', <>
        <div className="fttx-config-grid">{['allow_documented_b2b_exceptions'].map(renderField)}</div>
        <p className="fttx-config-note">Only enable this when long hops are confirmed to be geographically unavoidable. The design will complete with each over-limit cable flagged, its excess length and estimated cost recorded, and engineering sign-off still required.</p>
      </>)}
      {renderGroup('Execution options', <div className="fttx-config-grid">{['fast_mode'].map(renderField)}</div>)}
    </>,
  };
  return <div className="fttx-config">
    <div className="fttx-config-tabs" role="tablist" aria-label="Configuration categories">{CONFIG_TABS.map(tab => <button key={tab} type="button" role="tab" id={`${idPrefix}-tab-${tab.toLowerCase().replaceAll(' ','-')}`} aria-selected={activeTab===tab} aria-controls={`${idPrefix}-panel`} className={activeTab===tab?'fttx-config-tab fttx-config-tab-active':'fttx-config-tab'} onClick={()=>setActiveTab(tab)}>{tab}</button>)}</div>
    <div role="tabpanel" id={`${idPrefix}-panel`} aria-labelledby={`${idPrefix}-tab-${activeTab.toLowerCase().replaceAll(' ','-')}`} className="fttx-config-panel">{tabContent[activeTab]}</div>
    <style>{`.fttx-config{display:grid;gap:18px}.fttx-config-tabs{display:flex;gap:4px;overflow-x:auto;border-bottom:1px solid var(--border);scrollbar-width:thin}.fttx-config-tab{flex:0 0 auto;padding:10px 14px;border:1px solid transparent;border-bottom:0;border-radius:7px 7px 0 0;background:transparent;color:var(--text-secondary);font:inherit;font-size:13px;cursor:pointer}.fttx-config-tab:hover{color:var(--text-primary);background:var(--surface2)}.fttx-config-tab-active{color:var(--text-primary);background:var(--surface);border-color:var(--border);font-weight:600;position:relative;margin-bottom:-1px}.fttx-config-tab:focus-visible{outline:2px solid var(--accent-text);outline-offset:-2px}.fttx-config-panel{min-width:0}.fttx-config-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 14px}.fttx-config-note{font-size:12px;color:var(--text-secondary);margin:8px 0 0}@media(max-width:700px){.fttx-config-grid{grid-template-columns:1fr}}`}</style>
  </div>;
}
