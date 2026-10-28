import type { SelectOption } from '../ui/Select';

/** All runtime knobs accepted by the web FTTx engine. Values stay strings in
 * the form and are normalized to their engine types by settingsToConfig. */
export type FttxSettings = Record<string, string | boolean>;

export const DEFAULT_FTTX_SETTINGS: FttxSettings = {
  deployment_type:'aerial', cascade_architecture:'pcc', pon_architecture:'single_pon', coverage_pct:'100',
  b2b_routing_mode:'road',
  growth_reserve_pct:'0', project_name:'', project_abbreviation:'', max_box_to_box_distance:'250',
  max_box_to_customer_distance:'150', drop_length_tolerance:'1', snap_offset_distance:'1', fat_offset_radius:'0.5',
  splitter_pattern:'1x9,1x9,1x9,1x8', enable_closure_generation:true, fast_mode:false, marker_interval_m:'50',
  allow_proposed_poles:true, pole_max_spacing_m:'60', pole_proposal_search_radius_m:'80',
  allow_documented_b2b_exceptions:false,
  ug_infrastructure_type:'handhole', ug_spacing_m:'80', ug_routing_mode:'assisted', ug_duct_type:'HDPE',
  ug_duct_diameter_mm:'50', ug_duct_ways:'4', ug_installation_method:'direct_buried', ug_spare_capacity_pct:'20',
  ug_existing_handholes_layer:'', ug_existing_manholes_layer:'', dr_channel_layer:'', dr_spacing_m:'60',
  dr_duct_type:'HDPE', dr_duct_diameter_mm:'40', dr_duct_ways:'2', hy_boundary_layer:'', hy_aerial_field:'zone_type',
  hy_aerial_value:'aerial', occupancy_enabled:true, optical_enabled:true, olt_launch_power_dbm:'3',
  optical_budget_class:'B+', optical_splice_loss_db:'0.05', optical_connector_loss_db:'0.3',
  optical_engineering_margin_db:'2', optical_margin_pass_db:'3', optical_margin_marginal_db:'0',
  optical_trace_table_enabled:true,
  optical_splitter_library:'{"1x2":{"outputs":2,"roles":{"cascade":3.6}},"1x9":{"outputs":9,"local_ports":8,"roles":{"cascade":2.1,"local":16.3}},"1x8":{"outputs":8,"local_ports":8,"roles":{"local":10.5}}}',
  optical_fiber_atten_db_per_km:'{"1310":0.35,"1490":0.25}', occupancy_gpkg_path:'',
};

export const DEPLOYMENT_OPTIONS: SelectOption[] = [
  { label:'Aerial', value:'aerial' }, { label:'Underground', value:'underground' },
  { label:'Drainage', value:'drainage' }, { label:'Hybrid', value:'hybrid' },
];
export const CASCADE_OPTIONS: SelectOption[] = [
  { label:'PCC (box-to-box cascading)', value:'pcc' }, { label:'Legacy (sequential)', value:'legacy' },
];
export const PON_OPTIONS: SelectOption[] = [
  { label:'1 PON — 64 customers/FDT', value:'single_pon' }, { label:'2 PON — 128 customers/FDT', value:'dual_pon' },
];

const BOOL_KEYS = new Set(['enable_closure_generation','fast_mode','allow_proposed_poles','allow_documented_b2b_exceptions','occupancy_enabled','optical_enabled','optical_trace_table_enabled']);
const NUMBER_KEYS = new Set(['coverage_pct','growth_reserve_pct','max_box_to_box_distance','max_box_to_customer_distance','drop_length_tolerance','snap_offset_distance','fat_offset_radius','marker_interval_m','pole_max_spacing_m','pole_proposal_search_radius_m','ug_spacing_m','ug_duct_diameter_mm','ug_duct_ways','ug_spare_capacity_pct','dr_spacing_m','dr_duct_diameter_mm','dr_duct_ways','olt_launch_power_dbm','optical_splice_loss_db','optical_connector_loss_db','optical_engineering_margin_db','optical_margin_pass_db','optical_margin_marginal_db']);
const OBJECT_KEYS = new Set(['optical_splitter_library','optical_fiber_atten_db_per_km']);

export function settingsFromConfig(config: Record<string, unknown> | null | undefined): FttxSettings {
  const out = { ...DEFAULT_FTTX_SETTINGS };
  for (const [key, value] of Object.entries(config ?? {})) {
    if (BOOL_KEYS.has(key)) out[key] = value !== false;
    else if (value !== undefined && value !== null) out[key] = typeof value === 'object' ? JSON.stringify(value) : String(value);
  }
  return out;
}

export function settingsToConfig(settings: FttxSettings, base: Record<string, unknown> = {}): Record<string, unknown> {
  const out: Record<string, unknown> = { ...base };
  const managedOccupancyPath = base.occupancy_gpkg_path;
  for (const [key, value] of Object.entries(settings)) {
    if (BOOL_KEYS.has(key)) out[key] = Boolean(value);
    else if (NUMBER_KEYS.has(key)) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) out[key] = parsed;
      else {
        const fallback = Number(base[key] ?? DEFAULT_FTTX_SETTINGS[key]);
        out[key] = Number.isFinite(fallback) ? fallback : 0;
      }
    }
    else if (OBJECT_KEYS.has(key)) { try { out[key] = JSON.parse(String(value)); } catch { /* preserve base until valid JSON */ } }
    else if (key === 'splitter_pattern') {
      const raw = String(value).trim();
      if (raw.startsWith('[')) {
        try {
          const parsed: unknown = JSON.parse(raw);
          if (Array.isArray(parsed) && parsed.every(part => typeof part === 'string')) {
            out[key] = parsed.map(part => part.trim()).filter(Boolean);
            continue;
          }
        } catch { /* support the editable comma-separated form below */ }
      }
      out[key] = raw.split(',').map(part => part.trim()).filter(Boolean);
    }
    else out[key] = value;
  }
  if (settings.cascade_architecture === 'legacy') out.pon_architecture = 'single_pon';
  // Local filesystem paths cannot be supplied by the browser; uploaded layers
  // are referenced by layer key through the run API instead.
  if (managedOccupancyPath === undefined) delete out.occupancy_gpkg_path;
  else out.occupancy_gpkg_path = managedOccupancyPath;
  return out;
}
