// ============================================================
// OPSYN DESIGN — review on the map (Network GIS Phase 9).
//   ReviewPins     the open review's comments where they were pinned:
//                  amber open, grey resolved
//   CommentPicker  after "Pin on the map": the next click picks a device,
//                  a cable or the spot itself for the comment
// ============================================================

import { useEffect } from 'react';
import type { GeoJSONSource, MapMouseEvent } from 'maplibre-gl';
import type { ApprovalComment } from '@shared';
import { useMapInstance } from '../mapContext';
import { WS_ASSET_LAYER, WS_CABLE_LAYER } from './DesignLayers';
import { useDesignMapStore } from './designStore';

const SOURCE = 'design-review';
const LAYERS = ['design-review-pin', 'design-review-dot'];

export function ReviewPins({ comments }: { comments: ApprovalComment[] }) {
  const { map } = useMapInstance();
  useEffect(() => {
    map.addSource(SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({ id: 'design-review-pin', type: 'circle', source: SOURCE, paint: {
      'circle-radius': 11, 'circle-color': ['case', ['get', 'resolved'], '#94A3B8', '#E8A317'],
      'circle-stroke-color': '#FFFFFF', 'circle-stroke-width': 2.5, 'circle-translate': [12, -12],
    } });
    map.addLayer({ id: 'design-review-dot', type: 'circle', source: SOURCE, paint: {
      'circle-radius': 3, 'circle-color': '#FFFFFF', 'circle-translate': [12, -12],
    } });
    return () => {
      if (!map.getStyle()) return;
      for (const id of [...LAYERS].reverse()) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SOURCE)) map.removeSource(SOURCE);
    };
  }, [map]);
  useEffect(() => {
    (map.getSource(SOURCE) as GeoJSONSource | undefined)?.setData({
      type: 'FeatureCollection',
      features: comments.filter(c => c.lng !== null && c.lat !== null).map(c => ({
        type: 'Feature', properties: { id: c.id, resolved: c.resolved }, geometry: { type: 'Point', coordinates: [c.lng!, c.lat!] },
      })),
    });
  }, [map, comments]);
  return null;
}

export function CommentPicker() {
  const { map } = useMapInstance();
  const setCommentTarget = useDesignMapStore(s => s.setCommentTarget);
  useEffect(() => {
    const canvas = map.getCanvas();
    canvas.style.cursor = 'copy';
    const onClick = (e: MapMouseEvent) => {
      const { x, y } = e.point;
      const layers = [WS_ASSET_LAYER, WS_CABLE_LAYER].filter(l => map.getLayer(l));
      const hits = layers.length ? map.queryRenderedFeatures([[x - 6, y - 6], [x + 6, y + 6]], { layers }) : [];
      const f = hits.find(h => h.layer.id === WS_ASSET_LAYER) ?? hits[0];
      if (f) {
        const p = f.properties as Record<string, string>;
        setCommentTarget({ kind: f.layer.id === WS_ASSET_LAYER ? 'asset' : 'cable', id: String(p.id), code: String(p.asset_code) });
      } else {
        setCommentTarget({ kind: 'point', lng: e.lngLat.lng, lat: e.lngLat.lat });
      }
    };
    map.on('click', onClick);
    return () => { map.off('click', onClick); canvas.style.cursor = ''; };
  }, [map, setCommentTarget]);
  return null;
}
