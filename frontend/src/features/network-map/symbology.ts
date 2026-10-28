// ============================================================
// OPSYN NETWORK MAP — symbology, the map's one visual language.
//
//   Tier       → plate colour + plate shape (legible without colour)
//                core ▢ cobalt · distribution ◯ fibre green ·
//                civil ⬡ ochre · customer • plum
//   Type       → the white glyph on the plate (same lucide glyph as the
//                layer panel, so the legend IS the map key)
//   Lifecycle  → never colour alone: FAULTY adds a red ring AND a "!"
//                badge; VERIFIED (awaiting activation) a dashed ring
//   Cables     → colour by tier they serve, width by hierarchy, a white
//                casing so they read on any basemap; FAULTY turns red
//                and dashes
//
// Brand teal (#00C2A8) is reserved for selection — it never encodes data.
// Every expression here is a MapLibre style expression; the layer
// builder (NetworkLayers.tsx) only wires them up.
// ============================================================

import type { ExpressionSpecification } from 'maplibre-gl';
import {
  ArrowLeftRight, Blend, Building2, Container, DoorOpen, Disc, GitFork, Grid3x3,
  House, Landmark, Package, Pill, Router, Rows3, Server, Split, SquareDot,
  UtilityPole, Wifi, Workflow, type LucideIcon,
} from 'lucide-react';
import type { NetAssetType, NetCableCategory, NetConnectionType, NetLifecycleStatus, NetTier } from '@shared';

export const TIER_COLOR: Record<NetTier, string> = {
  core:         '#274690',  // cobalt — white glyph 9.3:1
  distribution: '#0B6E5B',  // deep fibre green — 6.3:1
  civil:        '#7E5F32',  // ochre / concrete — 6.1:1
  customer:     '#A42A63',  // plum — 6.9:1
};

export const TIER_SHAPE: Record<NetTier, 'square' | 'circle' | 'hexagon' | 'dot'> = {
  core: 'square', distribution: 'circle', civil: 'hexagon', customer: 'dot',
};

export const ASSET_TIER: Record<NetAssetType, NetTier> = {
  POP: 'core', SITE: 'core', OLT: 'core', ROOM: 'core', RACK: 'core',
  ROUTER: 'core', SWITCH: 'core', WDM: 'core', ODF: 'core',
  CABINET: 'distribution', FDT: 'distribution', FAT: 'distribution',
  SPLITTER: 'distribution', CLOSURE: 'distribution', ENCLOSURE: 'distribution',
  POLE: 'civil', MANHOLE: 'civil', HANDHOLE: 'civil',
  ONU: 'customer', CUSTOMER_ENDPOINT: 'customer',
};

export const ASSET_GLYPH: Record<NetAssetType, LucideIcon> = {
  POP: Building2, SITE: Landmark, OLT: Server, ROOM: DoorOpen, RACK: Rows3,
  ROUTER: Router, SWITCH: ArrowLeftRight, WDM: Blend, ODF: Grid3x3,
  CABINET: Container, FDT: Workflow, FAT: GitFork, SPLITTER: Split,
  CLOSURE: Pill, ENCLOSURE: Package,
  POLE: UtilityPole, MANHOLE: Disc, HANDHOLE: SquareDot,
  ONU: Wifi, CUSTOMER_ENDPOINT: House,
};

export const ASSET_TYPES = Object.keys(ASSET_TIER) as NetAssetType[];

/** Draw order: core on top of distribution on top of civil/customer. */
export const TIER_SORT: Record<NetTier, number> = { customer: 1, civil: 2, distribution: 3, core: 4 };

export const FAULT_COLOR = '#C8231A';
export const SELECT_COLOR = '#00C2A8';

export type IconVariant = 'ok' | 'fault' | 'verify';
export const ICON_VARIANTS: IconVariant[] = ['ok', 'fault', 'verify'];

export function iconVariant(status: NetLifecycleStatus): IconVariant {
  return status === 'FAULTY' ? 'fault' : status === 'VERIFIED' ? 'verify' : 'ok';
}

export function iconName(type: NetAssetType, variant: IconVariant): string {
  return `net-${type}-${variant}`;
}

// ── Cable styling ────────────────────────────────────────────

interface CableStyle { color: string; width: number }

export const CABLE_STYLE: Record<NetCableCategory, CableStyle> = {
  FEEDER:       { color: TIER_COLOR.core,         width: 4.5 },
  PICKUP:       { color: '#4A67B8',               width: 3 },
  CLOSURE_FDT:  { color: TIER_COLOR.core,         width: 3 },
  DISTRIBUTION: { color: TIER_COLOR.distribution, width: 3 },
  BOX_TO_BOX:   { color: '#2F8F7A',               width: 2.5 },
  DROP:         { color: TIER_COLOR.customer,     width: 1.5 },
  INTERNAL:     { color: '#5B6B7E',               width: 1.5 },
};

export const CABLE_CATEGORIES = Object.keys(CABLE_STYLE) as NetCableCategory[];

// ── Expressions ──────────────────────────────────────────────

export const assetIconExpr: ExpressionSpecification = [
  'concat', 'net-', ['get', 'asset_type'], '-',
  ['match', ['get', 'lifecycle_status'], 'FAULTY', 'fault', 'VERIFIED', 'verify', 'ok'],
];

export const assetSortExpr: ExpressionSpecification = [
  'match', ['get', 'asset_type'],
  ...ASSET_TYPES.flatMap(t => [t, TIER_SORT[ASSET_TIER[t]]]),
  0,
] as unknown as ExpressionSpecification;

/** Plates shrink when zoomed out so a dense street stays readable. */
export const assetIconSizeExpr: ExpressionSpecification = [
  'interpolate', ['linear'], ['zoom'], 8, 0.55, 13, 0.8, 16, 1,
];

export const cableColorExpr: ExpressionSpecification = [
  'case',
  ['==', ['get', 'lifecycle_status'], 'FAULTY'], FAULT_COLOR,
  ['match', ['get', 'cable_category'],
    ...CABLE_CATEGORIES.flatMap(c => [c, CABLE_STYLE[c].color]),
    '#5B6B7E'],
] as unknown as ExpressionSpecification;

const cableBaseWidth = [
  'match', ['get', 'cable_category'],
  ...CABLE_CATEGORIES.flatMap(c => [c, CABLE_STYLE[c].width]),
  2,
];

/**
 * Cable width by zoom, optionally scaled and padded. `zoom` may only appear
 * in a top-level interpolate, so derived widths (casing, halo, fault dash)
 * are built here instead of wrapping cableWidthExpr in arithmetic.
 */
export function cableWidth(scale = 1, pad = 0): ExpressionSpecification {
  const at = (k: number) => ['+', pad, ['*', k * scale, cableBaseWidth]];
  return ['interpolate', ['linear'], ['zoom'], 10, at(0.6), 16, at(1), 19, at(1.6)] as unknown as ExpressionSpecification;
}

export const cableWidthExpr = cableWidth();
export const cableCasingWidthExpr = cableWidth(1, 3);

export function inListFilter(prop: string, values: string[]): ExpressionSpecification {
  return ['in', ['get', prop], ['literal', values]];
}

// ── Labels (UI copy) ─────────────────────────────────────────

export const LIFECYCLE_LABEL: Record<NetLifecycleStatus, string> = {
  DRAFT: 'Draft', PLANNED: 'Planned', DESIGNED: 'Designed', UNDER_REVIEW: 'Under review',
  APPROVED: 'Approved', CONSTRUCTION: 'In construction', INSTALLED: 'Installed',
  TESTING: 'Testing', VERIFIED: 'Verified', ACTIVE: 'In service', FAULTY: 'Faulty',
  RETIRED: 'Retired', REJECTED: 'Rejected',
};

/** Mark colour next to the lifecycle label (the label and mark shape carry the meaning). */
export const LIFECYCLE_COLOR: Record<NetLifecycleStatus, string> = {
  DRAFT: '#94A3B8', PLANNED: '#76879B', DESIGNED: '#76879B', UNDER_REVIEW: '#6A5ACD',
  APPROVED: '#3B6FB6', CONSTRUCTION: '#B7791F', INSTALLED: '#B7791F', TESTING: '#B7791F',
  VERIFIED: '#2F7D8C', ACTIVE: '#1F8A4C', FAULTY: FAULT_COLOR, RETIRED: '#94A3B8', REJECTED: '#94A3B8',
};

/** A connection named as a noun: "Patch, no cable recorded", "Feed via FDR-0001" */
export const CONNECTION_LABEL: Record<NetConnectionType, string> = {
  FEED: 'Feed', SPLIT: 'Splitter output', SPLICE: 'Splice', PATCH: 'Patch', DROP: 'Drop', UPLINK: 'Uplink',
};

/** Why a derived connection exists (net_connections.source_table) */
export const DERIVED_LABEL: Record<string, string> = {
  net_cables: "From the cable's endpoints",
  'attr:parent_splitter': 'From the upload: parent splitter',
  'attr:cabinet': 'From the upload: cabinet',
  'attr:parent_fdt': "From the FAT's parent FDT code",
};

export const CREATION_LABEL: Record<string, string> = {
  AUTO: 'Generated by auto design', MANUAL: 'Drawn by hand',
  IMPORTED: 'Imported from upload', FIELD: 'Captured in the field',
};
