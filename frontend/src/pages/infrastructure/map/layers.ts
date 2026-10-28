// ============================================================
// OPSYN MAP — layer keys, defaults and counts (shared by the map,
// the layer panel and the list view)
// ============================================================

import type { OutageSeverity } from '@shared';

export type LayerKey = 'alarms' | 'sites' | 'olts' | 'cabinets' | 'splitters' | 'routes' | 'heat' | 'subscribers';
export type LayerState = Record<LayerKey, boolean>;

export const DEFAULT_LAYERS: LayerState = {
  alarms: true, sites: true, olts: true, cabinets: true, splitters: true, routes: true,
  // Off by default: dense overlays that bury the network at a glance
  heat: false, subscribers: false,
};

export interface LayerCounts {
  sites: number; olts: number; cabinets: number; splitterL1: number; splitterL2: number;
  routes: number; subscribers: number;
  alarmsBySeverity: Record<OutageSeverity, number>;
  alarmsUnplaced: number;
}
