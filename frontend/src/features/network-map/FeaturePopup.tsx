// ============================================================
// OPSYN NETWORK MAP — popup for the clicked asset or cable.
// A real maplibregl.Popup (anchored, follows the map) whose content is
// React, portalled into the popup's own element. Values come straight
// from the tile feature; "Details" opens the inspector, which fetches the
// authoritative record.
// ============================================================

import { useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import maplibregl from 'maplibre-gl';
import { X } from 'lucide-react';
import type { NetAssetType, NetCableCategory } from '@shared';
import { useMapInstance } from './mapContext';
import { formatLength } from './mapMath';
import type { Picked } from './NetworkLayers';
import { markerDataUrl } from './markerImages';
import { LifecycleState } from './LifecycleState';
import s from './NetworkMap.module.css';

const ROUTE_SHORT: Record<string, string> = {
  ROAD_GRAPH: 'Follows the roads', IMPORTED: 'As built', MANUAL_GEOMETRY: 'Drawn by hand',
  DIRECT: 'Direct to the premises',
};

interface Props {
  picked:     Picked;
  typeLabel:  (t: NetAssetType) => string;
  cableLabel: (c: NetCableCategory) => string;
  /** Omitted for design features: the inspector reads the live network only */
  onDetails?: (id: string, kind: 'asset' | 'cable') => void;
  /** Design features (Phase 8): open this feature's audit trail */
  onHistory?: (id: string, code: string) => void;
  onClose:    () => void;
}

export function FeaturePopup({ picked, typeLabel, cableLabel, onDetails, onHistory, onClose }: Props) {
  const { map } = useMapInstance();
  const el = useMemo(() => document.createElement('div'), []);

  useEffect(() => {
    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,     // map clicks are handled by NetworkLayers (select / clear)
      maxWidth: '300px',
      offset: picked.kind === 'asset' ? 18 : 8,
      className: s.popup,
      focusAfterOpen: false,
    }).setLngLat(picked.lngLat).setDOMContent(el).addTo(map);
    return () => { popup.remove(); };
  }, [map, el, picked]);

  const title = picked.asset_code;
  return createPortal(
    <div className={s.popupBody} role="dialog" aria-label={title}>
      <div className={s.popupHead}>
        {picked.kind === 'asset' && <img src={markerDataUrl(picked.asset_type)} alt="" width={30} height={30} />}
        <div style={{ flex: 1, minWidth: 0 }}>
          <p className={s.popupCode}>{title}</p>
          <p className={s.popupType}>
            {picked.kind === 'asset' ? typeLabel(picked.asset_type) : `${cableLabel(picked.cable_category)} cable`}
          </p>
        </div>
        <button type="button" className={s.iconBtn} onClick={onClose} aria-label="Close">
          <X size={16} aria-hidden />
        </button>
      </div>

      <dl className={s.popupFacts}>
        <dt>Status</dt>
        <dd><LifecycleState status={picked.lifecycle_status} /></dd>
        {picked.kind === 'asset' && picked.name && picked.name !== picked.asset_code && (<>
          <dt>Name</dt><dd>{picked.name}</dd>
        </>)}
        {picked.kind === 'cable' && (<>
          <dt>Length</dt><dd>{formatLength(picked.length_m)}</dd>
          <dt>Fibres</dt><dd>{picked.fiber_count ?? 'Unknown'}</dd>
          <dt>Route</dt><dd>{ROUTE_SHORT[picked.route_method] ?? picked.route_method}</dd>
        </>)}
      </dl>

      {(onDetails || onHistory) && (
        <div className={s.popupActions}>
          {onDetails && <button type="button" className={s.primaryBtn} onClick={() => onDetails(picked.id, picked.kind)}>Show details</button>}
          {onHistory && <button type="button" className={s.primaryBtn} onClick={() => onHistory(picked.id, picked.asset_code)}>History</button>}
        </div>
      )}
    </div>,
    el,
  );
}
