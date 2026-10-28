// ============================================================
// OPSYN DESIGN — the manual tools on the map (Phase 6).
// Turns map clicks into EditTargets for the state machine (designStore
// .send): a device or cable of the design under the pointer, a device in
// service (cable ends, feeding), otherwise the server's snap
// (POST /designs/{id}/snap: pole, homepass, pickup, cable vertex, beside
// the nearest road). Draws the preview: the rubber band from the first
// pick to the pointer, redraw / measure paths, and a ring on what a click
// would snap to. Right-click opens the edit menu for what is under it.
// ============================================================

import { useCallback, useEffect, useRef, useState } from 'react';
import type { GeoJSONSource, MapGeoJSONFeature, MapMouseEvent } from 'maplibre-gl';
import {
  Cable, GitFork, Move, Plus, Radius, Scissors, Spline, Trash2, Waypoints, type LucideIcon,
} from 'lucide-react';
import { designApi } from '../../../api/design.api';
import { useMapInstance } from '../mapContext';
import { ASSET_LAYER } from '../NetworkLayers';
import { MapContextMenu, type MenuAction } from '../MapContextMenu';
import { SELECT_COLOR } from '../symbology';
import { WS_ASSET_LAYER, WS_CABLE_LAYER } from './DesignLayers';
import { EDITING, snapTargets, wantFor, type EditState, type EditTarget, type EditTool } from './editMachine';
import { useDesignMapStore } from './designStore';

const SOURCE = 'design-edit';
const LAYERS = ['design-edit-line', 'design-edit-point', 'design-edit-ring'];
const INK = '#0B1520';
const HOVER_PX = 8;
const INPUT_POINT_LAYERS = ['design-in-homepass-point', 'design-in-pole-point', 'design-in-existing_structure-point', 'design-in-pickup-point'];

function assetFrom(f: MapGeoJSONFeature, live: boolean): EditTarget {
  const p = f.properties as Record<string, string>;
  const [lng, lat] = (f.geometry as GeoJSON.Point).coordinates;
  return { kind: 'asset', id: String(p.id), code: String(p.asset_code), assetType: String(p.asset_type), lng, lat, live };
}

export function EditLayer({ designId, editable }: { designId: string; editable: boolean }) {
  const { map } = useMapInstance();
  const { edit, send, setNote } = useDesignMapStore();
  const [cursor, setCursor] = useState<[number, number] | null>(null);
  const [hover, setHover] = useState<[number, number] | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; title: string; actions: MenuAction[] } | null>(null);
  const editRef = useRef(edit);
  useEffect(() => { editRef.current = edit; }, [edit]);
  const active = EDITING(edit.tool);

  // ── Preview source ───────────────────────────────────────
  useEffect(() => {
    map.addSource(SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({ id: 'design-edit-line', type: 'line', source: SOURCE, filter: ['==', ['geometry-type'], 'LineString'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': INK, 'line-width': 2.5, 'line-dasharray': [2, 1.5] } });
    map.addLayer({ id: 'design-edit-point', type: 'circle', source: SOURCE, filter: ['==', ['get', 'role'], 'point'],
      paint: { 'circle-radius': 5, 'circle-color': '#FFFFFF', 'circle-stroke-color': INK, 'circle-stroke-width': 2.5 } });
    map.addLayer({ id: 'design-edit-ring', type: 'circle', source: SOURCE, filter: ['==', ['get', 'role'], 'ring'],
      paint: { 'circle-radius': 17, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': SELECT_COLOR, 'circle-stroke-width': 3 } });
    return () => {
      if (!map.getStyle()) return;
      for (const id of [...LAYERS].reverse()) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SOURCE)) map.removeSource(SOURCE);
    };
  }, [map]);

  useEffect(() => {
    const feats: GeoJSON.Feature[] = [];
    const first = edit.picks[0];
    const path: [number, number][] =
      edit.tool === 'measure' || (edit.tool === 'redraw' && first) ? [...edit.points] : first ? [[first.lng, first.lat]] : [];
    if (active && cursor && path.length) path.push(cursor);
    if (path.length >= 2) feats.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: path } });
    for (const p of edit.picks) feats.push({ type: 'Feature', properties: { role: 'ring' }, geometry: { type: 'Point', coordinates: [p.lng, p.lat] } });
    for (const p of edit.points) feats.push({ type: 'Feature', properties: { role: 'point' }, geometry: { type: 'Point', coordinates: p } });
    if (active && hover) feats.push({ type: 'Feature', properties: { role: 'ring' }, geometry: { type: 'Point', coordinates: hover } });
    (map.getSource(SOURCE) as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features: feats });
  }, [map, edit, cursor, hover, active]);

  // ── Resolving a click ────────────────────────────────────
  const near = useCallback((e: MapMouseEvent, layers: string[]) => {
    const { x, y } = e.point;
    const present = layers.filter(l => map.getLayer(l));
    return present.length ? map.queryRenderedFeatures([[x - HOVER_PX, y - HOVER_PX], [x + HOVER_PX, y + HOVER_PX]], { layers: present }) : [];
  }, [map]);

  const resolve = useCallback(async (e: MapMouseEvent, s: EditState): Promise<EditTarget | null> => {
    const want = wantFor(s);
    const click: [number, number] = [e.lngLat.lng, e.lngLat.lat];
    if (want.includes('asset')) {
      const own = near(e, [WS_ASSET_LAYER]).sort((a, b) => Number(a.properties.asset_type === 'SPLITTER') - Number(b.properties.asset_type === 'SPLITTER'));
      if (own[0]) return assetFrom(own[0], false);
      const live = near(e, [ASSET_LAYER]);
      if (live[0] && (s.tool === 'cable' || s.tool === 'connect')) return assetFrom(live[0], true);
    }
    if (want.includes('cable')) {
      const c = near(e, [WS_CABLE_LAYER])[0];
      if (c) {
        const p = c.properties as Record<string, string>;
        return { kind: 'cable', id: String(p.id), code: String(p.asset_code), category: String(p.cable_category), lng: click[0], lat: click[1] };
      }
    }
    if (!want.includes('point')) return null;
    const targets = snapTargets(s);
    if (!targets) return { kind: 'point', lng: click[0], lat: click[1] };
    try {
      const radius = Math.max(8, 40 / 2 ** Math.max(0, map.getZoom() - 16));       // ~a finger's width on screen
      const snap = await designApi.snap(designId, { lng: click[0], lat: click[1], radius_m: radius, targets });
      if (!snap.snapped) return { kind: 'point', lng: click[0], lat: click[1] };
      if (snap.kind === 'asset' || snap.kind === 'live_asset') {
        return { kind: 'asset', id: snap.id, code: snap.code, assetType: snap.sub, lng: snap.lng, lat: snap.lat, live: snap.kind === 'live_asset' };
      }
      return { kind: 'point', lng: snap.lng, lat: snap.lat, snappedTo: `${snap.kind === 'road' ? 'beside ' : ''}${snap.code}` };
    } catch {
      return { kind: 'point', lng: click[0], lat: click[1] };           // snapping is a help, never a blocker
    }
  }, [designId, map, near]);

  // ── Map events while a tool is on ────────────────────────
  useEffect(() => {
    if (!active || !editable) return;
    const canvas = map.getCanvas();
    canvas.style.cursor = 'crosshair';
    map.doubleClickZoom.disable();
    let busy = false;
    const onClick = async (e: MapMouseEvent) => {
      if (busy) return;
      busy = true;
      try {
        const s = editRef.current;
        const t = await resolve(e, s);
        if (t) send({ type: 'CLICK', target: t });
        else setNote({ tone: 'error', text: wantFor(s).includes('cable') ? 'Click on a cable of this design' : 'Click on a device of this design' });
      } finally {
        busy = false;
      }
    };
    const onMove = (e: MapMouseEvent) => {
      setCursor([e.lngLat.lng, e.lngLat.lat]);
      const s = editRef.current;
      const want = wantFor(s);
      const f = (want.includes('asset') ? near(e, [WS_ASSET_LAYER, ...INPUT_POINT_LAYERS]) : [])[0]
        ?? (want.includes('point') && snapTargets(s)?.some(k => k !== 'road') ? near(e, INPUT_POINT_LAYERS)[0] : undefined);
      setHover(f && f.geometry.type === 'Point' ? (f.geometry.coordinates as [number, number]) : null);
    };
    const onDbl = (e: MapMouseEvent) => {
      if (editRef.current.tool === 'redraw' || editRef.current.tool === 'measure') { e.preventDefault(); send({ type: 'FINISH' }); }
    };
    map.on('click', onClick);
    map.on('mousemove', onMove);
    map.on('dblclick', onDbl);
    return () => {
      map.off('click', onClick);
      map.off('mousemove', onMove);
      map.off('dblclick', onDbl);
      canvas.style.cursor = '';
      map.doubleClickZoom.enable();
      setCursor(null);
      setHover(null);
    };
  }, [map, active, editable, resolve, near, send, setNote]);

  // ── Right-click: edit what is under the pointer ──────────
  useEffect(() => {
    if (!editable) return;
    const onMenu = (e: MapMouseEvent) => {
      e.preventDefault();
      const tool = (t: EditTool, start?: EditTarget, subtype?: string | null) => () => send({ type: 'TOOL', tool: t, start, subtype });
      const act = (id: string, label: string, icon: LucideIcon, run: () => void): MenuAction => ({ id, label, icon, run });
      const asset = near(e, [WS_ASSET_LAYER]).find(f => f.properties.asset_type !== 'SPLITTER');
      const cable = near(e, [WS_CABLE_LAYER])[0];
      const at: EditTarget = { kind: 'point', lng: e.lngLat.lng, lat: e.lngLat.lat };
      if (asset) {
        const a = assetFrom(asset, false);
        setMenu({ x: e.point.x, y: e.point.y, title: a.kind === 'asset' ? a.code : '', actions: [
          act('move', 'Move', Move, tool('move', a)),
          act('cable', 'Draw a cable from here', Cable, tool('cable', a, 'BOX_TO_BOX')),
          act('drop', 'Draw a drop from here', Spline, tool('cable', a, 'DROP')),
          act('connect', 'Feeds…', GitFork, tool('connect', a)),
          act('delete', 'Delete', Trash2, () => { send({ type: 'TOOL', tool: 'delete' }); send({ type: 'CLICK', target: a }); }),
        ] });
      } else if (cable) {
        const p = cable.properties as Record<string, string>;
        const c: EditTarget = { kind: 'cable', id: String(p.id), code: String(p.asset_code), category: String(p.cable_category), lng: at.lng, lat: at.lat };
        setMenu({ x: e.point.x, y: e.point.y, title: String(p.asset_code), actions: [
          act('split', 'Split here', Scissors, () => { send({ type: 'TOOL', tool: 'split' }); send({ type: 'CLICK', target: c }); }),
          act('closure', 'Split here with a closure', Scissors,
            () => { send({ type: 'TOOL', tool: 'split', subtype: 'CLOSURE' }); send({ type: 'CLICK', target: c }); }),
          act('extend', 'Extend', Waypoints, tool('extend', c)),
          act('redraw', 'Redraw the line', Spline, tool('redraw', c)),
          act('delete', 'Delete', Trash2, () => { send({ type: 'TOOL', tool: 'delete' }); send({ type: 'CLICK', target: c }); }),
        ] });
      } else {
        const add = (type: string, label: string) => act(`add-${type}`, `Add ${label} here`, Plus, async () => {
          send({ type: 'TOOL', tool: 'add', subtype: type });
          const t = await resolve(e, { ...editRef.current, tool: 'add', subtype: type, picks: [] });
          if (t) send({ type: 'CLICK', target: t });
        });
        setMenu({ x: e.point.x, y: e.point.y, title: 'Here', actions: [
          add('FDT', 'an FDT'), add('FAT', 'a FAT'), add('CLOSURE', 'a closure'), add('POLE', 'a pole'),
          act('measure', 'Measure from here', Radius, () => { send({ type: 'TOOL', tool: 'measure' }); send({ type: 'CLICK', target: at }); }),
        ] });
      }
    };
    map.on('contextmenu', onMenu);
    return () => { map.off('contextmenu', onMenu); };
  }, [map, editable, near, send, resolve]);

  return menu ? <MapContextMenu title={menu.title} x={menu.x} y={menu.y} actions={menu.actions} onClose={() => setMenu(null)} /> : null;
}
