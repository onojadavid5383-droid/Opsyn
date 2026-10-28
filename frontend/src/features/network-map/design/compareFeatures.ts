// ============================================================
// OPSYN DESIGN — the compare overlay's data (pure): the colour key and
// the comparison turned into one FeatureCollection with a role per feature.
// Drawn by CompareLayer; keyed by ViewCard. Tested in versions.test.tsx.
// ============================================================

import type { DesignCompare } from '@shared';

export const CMP = { added: '#16A34A', removed: '#C8231A', moved: '#0B1520', rerouted: '#C77700', ghost: '#76879B' };

function bearing(a: [number, number], b: [number, number]): number {
  const r = Math.PI / 180;
  const y = Math.sin((b[0] - a[0]) * r) * Math.cos(b[1] * r);
  const x = Math.cos(a[1] * r) * Math.sin(b[1] * r) - Math.sin(a[1] * r) * Math.cos(b[1] * r) * Math.cos((b[0] - a[0]) * r);
  return (Math.atan2(y, x) * 180) / Math.PI;
}

/** The comparison as one FeatureCollection with a role per feature (pure) */
export function compareFeatures(c: DesignCompare): GeoJSON.FeatureCollection {
  const feats: GeoJSON.Feature[] = [];
  for (const f of c.removed) feats.push({ ...f, properties: { ...f.properties, role: 'removed' } });
  for (const f of c.added) feats.push({ ...f, properties: { ...f.properties, role: 'added' } });
  for (const m of c.moved) {
    feats.push({ type: 'Feature', properties: { role: 'ghost', code: m.code }, geometry: { type: 'Point', coordinates: m.from } });
    feats.push({ type: 'Feature', properties: { role: 'arrow', code: m.code }, geometry: { type: 'LineString', coordinates: [m.from, m.to] } });
    feats.push({ type: 'Feature', properties: { role: 'head', bearing: bearing(m.from, m.to) }, geometry: { type: 'Point', coordinates: m.to } });
  }
  for (const ch of c.changed) {
    if (ch.kind === 'cable' && ch.geometry_before) {
      feats.push({ type: 'Feature', properties: { role: 'old', code: ch.code }, geometry: ch.geometry_before });
    }
  }
  return { type: 'FeatureCollection', features: feats };
}
