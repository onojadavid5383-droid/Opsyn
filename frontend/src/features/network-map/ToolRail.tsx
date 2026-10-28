// ============================================================
// OPSYN NETWORK MAP — tool rail (right edge, dark chrome).
// View tools: zoom, fit to network, my location, capacity rings (Phase 3),
// basemap, full screen, layer panel. Editing tools join in the design phases.
// ============================================================

import { useEffect, useRef, useState } from 'react';
import {
  Check, Gauge, LocateFixed, Map as MapIcon, Maximize, Minimize, Minus, PanelLeftOpen, Plus, ScanSearch,
} from 'lucide-react';
import type { GisBounds } from '@shared';
import { useMapInstance } from './mapContext';
import { fitNetwork } from './mapMath';
import { BASEMAPS, useNetworkMapStore } from './store';
import s from './NetworkMap.module.css';

interface Props {
  bounds:       GisBounds | undefined;
  workspace:    HTMLElement | null;
  onLocateError: (message: string) => void;
  panelShown:   boolean;
  onShowPanel:  () => void;
  showCapacity: boolean;
  onToggleCapacity: () => void;
}

export function ToolRail({ bounds, workspace, onLocateError, panelShown, onShowPanel, showCapacity, onToggleCapacity }: Props) {
  const { map } = useMapInstance();
  const { basemap, setBasemap } = useNetworkMapStore();
  const [menuOpen, setMenuOpen] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuBtn = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === workspace && !!workspace);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, [workspace]);

  useEffect(() => {
    if (!menuOpen) return;
    menuRef.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
    const onDown = (e: PointerEvent) => {
      if (!menuRef.current?.contains(e.target as Node) && e.target !== menuBtn.current) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setMenuOpen(false); menuBtn.current?.focus(); }
    };
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('pointerdown', onDown); document.removeEventListener('keydown', onKey); };
  }, [menuOpen]);

  const locate = () => {
    if (!navigator.geolocation) { onLocateError("This browser can't share your location."); return; }
    navigator.geolocation.getCurrentPosition(
      pos => map.flyTo({ center: [pos.coords.longitude, pos.coords.latitude], zoom: Math.max(map.getZoom(), 16) }),
      () => onLocateError('Location is blocked. Allow location access for OpSyn in your browser to use this.'),
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  };

  const toggleFullscreen = () => {
    if (!workspace) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void workspace.requestFullscreen?.();
  };

  const btn = (label: string, onClick: () => void, icon: React.ReactNode, extra: Record<string, unknown> = {}) => (
    <button type="button" className={s.railBtn} onClick={onClick} aria-label={label} title={label} {...extra}>{icon}</button>
  );

  return (
    <nav className={s.rail} aria-label="Map tools">
      {!panelShown && (<>
        {btn('Show layer panel', onShowPanel, <PanelLeftOpen size={20} aria-hidden />)}
        <span className={s.railRule} aria-hidden />
      </>)}
      <div className={s.railGroup}>
        {btn('Zoom in', () => map.zoomIn(), <Plus size={20} aria-hidden />)}
        {btn('Zoom out', () => map.zoomOut(), <Minus size={20} aria-hidden />)}
      </div>
      <span className={s.railRule} aria-hidden />
      <div className={s.railGroup}>
        {btn('Fit the whole network', () => fitNetwork(map, bounds), <ScanSearch size={20} aria-hidden />, { disabled: !bounds?.bbox })}
        {btn('Go to my location', locate, <LocateFixed size={20} aria-hidden />)}
        {btn(showCapacity ? 'Hide capacity rings' : 'Show capacity rings', onToggleCapacity, <Gauge size={20} aria-hidden />, { 'aria-pressed': showCapacity })}
      </div>
      <span className={s.railRule} aria-hidden />
      <div className={s.railGroup} style={{ position: 'relative' }}>
        <button
          ref={menuBtn}
          type="button"
          className={s.railBtn}
          aria-label="Basemap"
          title="Basemap"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen(o => !o)}
        >
          <MapIcon size={20} aria-hidden />
        </button>
        {menuOpen && (
          <div ref={menuRef} className={s.basemapMenu} role="menu" aria-label="Basemap" style={{ top: 0 }}>
            {BASEMAPS.map(b => (
              <button
                key={b.id}
                type="button"
                role="menuitemradio"
                aria-checked={basemap === b.id}
                className={s.basemapOption}
                onClick={() => { setBasemap(b.id); setMenuOpen(false); menuBtn.current?.focus(); }}
              >
                <span className={s.basemapTick}>{basemap === b.id && <Check size={16} aria-hidden />}</span>
                {b.label}
              </button>
            ))}
          </div>
        )}
        {btn(fullscreen ? 'Exit full screen' : 'Full screen', toggleFullscreen,
          fullscreen ? <Minimize size={20} aria-hidden /> : <Maximize size={20} aria-hidden />,
          { 'aria-pressed': fullscreen })}
      </div>
    </nav>
  );
}
