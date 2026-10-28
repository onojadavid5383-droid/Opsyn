// ============================================================
// OPSYN NETWORK MAP STORE — Zustand, UI state only.
//
// Server data (layers, assets, search) lives in TanStack Query. This store
// holds what the viewer is doing:
//   selectedId     the asset shown in the popup / inspector
//   inspectorOpen  whether the details drawer is open for it
//   hidden         layer keys (asset types, cable categories) switched off
//   basemap        'light' | 'dark' | 'none'
//   panelOpen      the docked layer panel
//   trace          the asset being traced and the direction (Phase 3)
//   showCapacity   capacity rings on the map
// hidden / basemap / panelOpen are remembered per browser.
// ============================================================

import { create } from 'zustand';
import type { NetTraceDirection } from '@shared';

export type NetworkBasemap = 'light' | 'dark' | 'none';
export type SelectionKind = 'asset' | 'cable';
export const BASEMAPS: { id: NetworkBasemap; label: string }[] = [
  { id: 'light', label: 'Street map' },
  { id: 'dark', label: 'Night map' },
  { id: 'none', label: 'Network only' },
];

const KEY = 'opsyn-network-map';

interface Saved { hidden: string[]; basemap: NetworkBasemap; panelOpen: boolean; showCapacity: boolean }

function load(): Saved {
  const fallback: Saved = { hidden: [], basemap: 'light', panelOpen: true, showCapacity: false };
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Partial<Saved> | null;
    if (!raw) return fallback;
    return {
      hidden: Array.isArray(raw.hidden) ? raw.hidden.filter(h => typeof h === 'string') : [],
      basemap: BASEMAPS.some(b => b.id === raw.basemap) ? raw.basemap! : 'light',
      panelOpen: raw.panelOpen !== false,
      showCapacity: raw.showCapacity === true,
    };
  } catch {
    return fallback;
  }
}

function save(state: Saved) {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* storage blocked — session only */ }
}

interface NetworkMapState {
  selectedId:    string | null;
  inspectorOpen: boolean;
  hidden:        string[];
  basemap:       NetworkBasemap;
  panelOpen:     boolean;
  /** Narrow screens: the panel is a sheet over the map, closed on every visit */
  sheetOpen:     boolean;
  /** What selectedId points at — the inspector fetches accordingly */
  selectedKind:  SelectionKind;
  select:        (id: string | null, kind?: SelectionKind) => void;
  openInspector: (id: string, kind?: SelectionKind) => void;
  closeInspector: () => void;
  toggleLayer:   (key: string) => void;
  setLayers:     (keys: string[], visible: boolean) => void;
  setBasemap:    (b: NetworkBasemap) => void;
  setPanelOpen:  (open: boolean) => void;
  setSheetOpen:  (open: boolean) => void;
  /** The traced asset and direction, or null (Phase 3) */
  trace:         { assetId: string; direction: NetTraceDirection } | null;
  startTrace:    (assetId: string, direction: NetTraceDirection) => void;
  clearTrace:    () => void;
  /** Capacity rings on the map (remembered) */
  showCapacity:  boolean;
  setShowCapacity: (on: boolean) => void;
}

export const useNetworkMapStore = create<NetworkMapState>((set, get) => {
  const persist = () => {
    const { hidden, basemap, panelOpen, showCapacity } = get();
    save({ hidden, basemap, panelOpen, showCapacity });
  };
  return {
    ...load(),
    selectedId: null,
    inspectorOpen: false,
    sheetOpen: false,
    selectedKind: 'asset',
    // An open inspector follows the selection; clearing it closes the inspector
    select: (id, kind = 'asset') => set(s => ({ selectedId: id, selectedKind: kind, inspectorOpen: id !== null && s.inspectorOpen })),
    openInspector: (id, kind = 'asset') => set({ selectedId: id, selectedKind: kind, inspectorOpen: true }),
    closeInspector: () => set({ inspectorOpen: false }),
    toggleLayer: key => {
      set(s => ({ hidden: s.hidden.includes(key) ? s.hidden.filter(k => k !== key) : [...s.hidden, key] }));
      persist();
    },
    setLayers: (keys, visible) => {
      set(s => ({
        hidden: visible ? s.hidden.filter(k => !keys.includes(k)) : [...new Set([...s.hidden, ...keys])],
      }));
      persist();
    },
    setBasemap: basemap => { set({ basemap }); persist(); },
    setPanelOpen: panelOpen => { set({ panelOpen }); persist(); },
    setSheetOpen: sheetOpen => set({ sheetOpen }),
    trace: null,
    startTrace: (assetId, direction) => set({ trace: { assetId, direction } }),
    clearTrace: () => set({ trace: null }),
    setShowCapacity: showCapacity => { set({ showCapacity }); persist(); },
  };
});
