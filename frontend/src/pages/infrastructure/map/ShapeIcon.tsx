// ============================================================
// OPSYN MAP — asset / severity shapes outside the map (legend, list,
// search results, inspector). Same SVG source as the map markers, so the
// shapes can never drift apart.
//
// The only innerHTML in the map code: the markup is built exclusively from
// the fixed shape table in mapIcons.ts and theme colours read from CSS —
// no user or API content ever reaches it.
// ============================================================

import type { OutageSeverity } from '@shared';
import { assetShapeSvg, severityShapeSvg } from './mapIcons';
import type { AssetKind } from './mapModel';

export function AssetShape({ kind, color, outline, level, size = 18 }: {
  kind: AssetKind; color: string; outline: string; level?: string; size?: number;
}) {
  return <span aria-hidden="true" style={{ display: 'inline-flex' }} dangerouslySetInnerHTML={{ __html: assetShapeSvg(kind, color, outline, level, size) }} />;
}

export function AlarmShape({ severity, color, outline, size = 16 }: {
  severity: OutageSeverity; color: string; outline: string; size?: number;
}) {
  return <span aria-hidden="true" style={{ display: 'inline-flex' }} dangerouslySetInnerHTML={{ __html: severityShapeSvg(severity, color, outline, size) }} />;
}
