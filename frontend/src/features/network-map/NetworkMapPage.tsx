// ============================================================
// OPSYN NETWORK MAP — /network (Network GIS Phase 1, NETWORK mode).
//
// Data path: PostGIS net_assets/net_cables → /gis/tiles MVT → MapLibre
// vector source → click → selectedId + kind (store) → GET
// /network/assets|cables/{id} → inspector. Search: /network/search → fly to
// → same selection path. Deep links: /network?asset=<id> or ?cable=<id>
// (the Infrastructure register's "Show on map") open straight onto one.
// Trace (Phase 3): inspector buttons or right-click → store.trace →
// GET …/trace → TraceLayer (map, network dimmed) + TracePanel.
// Design mode (Phase 4): /network?mode=design&design=<id> swaps the layer
// panel for the DesignPanel, draws the design over the dimmed, non-clickable
// live network (design/DesignWorkspace) and frames the design.
// ============================================================

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { NetAssetSummary, NetAssetType, NetCableCategory, NetTraceDirection } from '@shared';
import { networkApi } from '../../api/network.api';
import { MapCanvas } from './MapCanvas';
import { MapInstanceProvider, type MapCtx } from './mapContext';
import { fitNetwork } from './mapMath';
import { NetworkLayers, type Picked } from './NetworkLayers';
import { LayerPanel } from './LayerPanel';
import { MapSearch } from './MapSearch';
import { FeaturePopup } from './FeaturePopup';
import { AssetInspector, type AssetRefTarget } from './AssetInspector';
import { ToolRail } from './ToolRail';
import { StatusBar } from './StatusBar';
import { networkKeys, useCatalogue, useLayerRegistry, useNetworkBounds, useTrace } from './queries';
import { TraceLayer } from './TraceLayer';
import { TracePanel } from './TracePanel';
import { MapContextMenu } from './MapContextMenu';
import { useNetworkMapStore } from './store';
import { useMediaQuery } from '../../hooks/useMediaQuery';
import { useDesign } from './design/designQueries';
import { useDesignMapStore } from './design/designStore';
import { DesignPanel } from './design/DesignPanel';
import { DesignMapContent, DesignOverlays } from './design/DesignWorkspace';
import { designError } from './design/designFormat';
import { fttxDesignerApi } from '../../api/fttx-designer.api';
import { FttxAttributeTable, FttxRelationshipPanel, FttxRunPreviewLayers, FttxRunPreviewPanel } from './FttxRunPreview';
import s from './NetworkMap.module.css';

export default function NetworkMapPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const registry = useLayerRegistry();
  const bounds = useNetworkBounds();
  const {
    hidden, basemap, panelOpen, sheetOpen, setPanelOpen, setSheetOpen,
    selectedId, selectedKind, inspectorOpen, select, openInspector, closeInspector,
    trace, startTrace, clearTrace, showCapacity, setShowCapacity,
  } = useNetworkMapStore();
  const catalogue = useCatalogue();
  const traceQ = useTrace(trace?.assetId ?? null, trace?.direction ?? 'upstream');
  const [menu, setMenu] = useState<{ picked: Picked; x: number; y: number } | null>(null);
  // Same breakpoint as the stylesheet: below it the panel is a sheet over the map
  const narrow = useMediaQuery('(max-width: 900px)');
  const panelShown = narrow ? sheetOpen : panelOpen;
  const showPanel = () => (narrow ? setSheetOpen(true) : setPanelOpen(true));
  const hidePanel = () => (narrow ? setSheetOpen(false) : setPanelOpen(false));

  const [mapCtx, setMapCtx] = useState<MapCtx | null>(null);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [tilesFailed, setTilesFailed] = useState(false);
  const [zoom, setZoom] = useState(10);
  const [notice, setNotice] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<HTMLDivElement | null>(null);
  const framed = useRef(false);
  const [params] = useSearchParams();
  const designId = params.get('design');
  const fttxRunId = params.get('fttxRun');
  const fttxResults = useQuery({
    queryKey: ['fttx-designer', 'run', fttxRunId, 'results'],
    queryFn: () => fttxDesignerApi.getResults(fttxRunId!),
    enabled: !!fttxRunId,
  });
  const fttxInputLayers = useQuery({
    queryKey: ['fttx-designer', 'run', fttxRunId, 'layers'],
    queryFn: () => fttxDesignerApi.listLayers(fttxRunId!),
    enabled: !!fttxRunId,
  });
  const [fttxVisible, setFttxVisible] = useState<Record<string, boolean>>({});
  const [fttxTableKey, setFttxTableKey] = useState<string | null>(null);
  const [fttxOrder, setFttxOrder] = useState<string[]>([]);
  const [fttxLabelFields, setFttxLabelFields] = useState<Record<string,string>>({});
  const [fttxSelected, setFttxSelected] = useState<{layer:string;properties:Record<string,unknown>}|null>(null);
  const fttxInitializedRun = useRef<string|null>(null);
  useEffect(() => {
    if (!fttxResults.data || !fttxRunId || fttxInitializedRun.current === fttxRunId) return;
    fttxInitializedRun.current = fttxRunId;
    const available = Object.keys(fttxResults.data.output_layers).filter(k=>['fdt','fat','closure','pole_output','pickup_point','b2b','b2c','feeder','closure_cable'].includes(k));
    const pointLayers = ['fdt','fat','closure','pole_output','pickup_point'];
    setFttxOrder([...available.filter(k=>pointLayers.includes(k)), ...available.filter(k=>!pointLayers.includes(k))]);
    setFttxLabelFields({});
    setFttxSelected(null);
  }, [fttxRunId, fttxResults.data]);
  const moveFttxLayer = useCallback((key:string,direction:-1|1) => setFttxOrder(current => {
    const keys = [...(fttxResults.data ? Object.keys(fttxResults.data.output_layers).filter(k=>['fdt','fat','closure','pole_output','pickup_point','b2b','b2c','feeder','closure_cable'].includes(k)) : []), ...current].filter((k,i,a)=>a.indexOf(k)===i);
    const index=keys.indexOf(key), target=index+direction;
    if(index<0||target<0||target>=keys.length) return keys;
    [keys[index],keys[target]]=[keys[target],keys[index]]; return keys;
  }),[fttxResults.data]);
  const designQ = useDesign(designId);
  const design = designQ.data;
  const openDesign = useDesignMapStore(st => st.open);
  const openHistory = useCallback((id: string, code: string) => {
    const st = useDesignMapStore.getState();
    st.setHistoryOf({ id, code });
    st.setDrawer('versions');
  }, []);
  const designFramed = useRef<string | null>(null);
  useEffect(() => { if (designId) openDesign(designId); }, [designId, openDesign]);
  const deepLink = useRef<{ kind: 'asset' | 'cable'; id: string } | null>(
    params.get('asset') ? { kind: 'asset', id: params.get('asset')! }
    : params.get('cable') ? { kind: 'cable', id: params.get('cable')! }
    : null,
  );

  const labels = useMemo(() => {
    const m = new Map<string, string>();
    for (const g of registry.data?.groups ?? []) for (const l of g.layers) m.set(l.key, l.label);
    return m;
  }, [registry.data]);
  const typeLabel = useCallback((t: NetAssetType) => labels.get(t) ?? t, [labels]);
  const cableLabel = useCallback((c: NetCableCategory) => labels.get(c) ?? c, [labels]);

  // Zoom for the panel's "zoom in to see" hints
  useEffect(() => {
    if (!mapCtx) return;
    const { map } = mapCtx;
    const onZoom = () => setZoom(map.getZoom());
    onZoom();
    map.on('zoomend', onZoom);
    return () => { map.off('zoomend', onZoom); };
  }, [mapCtx]);

  // First load: frame the whole live network once it is known
  useEffect(() => {
    if (!mapCtx || framed.current || !bounds.data || deepLink.current || designId || fttxRunId) return;
    framed.current = true;
    fitNetwork(mapCtx.map, bounds.data, false);
  }, [mapCtx, bounds.data, designId, fttxRunId]);

  // Design mode: frame the design (boundary, inputs, working set) once per design;
  // an empty design falls back to the live network
  useEffect(() => {
    if (!mapCtx || !design || designFramed.current === design.id) return;
    const box = design.bbox ?? bounds.data?.bbox ?? null;
    if (!design.bbox && !bounds.data) return;
    designFramed.current = design.id;
    framed.current = true;
    if (box) mapCtx.map.fitBounds([[box[0], box[1]], [box[2], box[3]]], { padding: 80, maxZoom: 17, duration: 0 });
  }, [mapCtx, design, bounds.data]);

  const onPick = useCallback((p: Picked | null) => {
    setPicked(p);
    select(p?.id ?? null, p?.kind ?? 'asset');
  }, [select]);

  const clearSelection = useCallback(() => { setPicked(null); select(null); }, [select]);

  const flyAndPick = useCallback((a: NetAssetSummary) => {
    mapCtx?.map.flyTo({ center: [a.lng, a.lat], zoom: Math.max(mapCtx.map.getZoom(), 17), duration: 700 });
    setPicked({
      kind: 'asset', id: a.id, asset_code: a.asset_code, asset_type: a.asset_type,
      name: a.name ?? '', lifecycle_status: a.lifecycle_status, lngLat: [a.lng, a.lat],
    });
    select(a.id, 'asset');
  }, [mapCtx, select]);

  const goTo = useCallback(async (ref: AssetRefTarget) => {
    try {
      const a = await qc.fetchQuery({ queryKey: networkKeys.asset(ref.id), queryFn: () => networkApi.get(ref.id) });
      flyAndPick(a);
      setPicked(null);                 // the inspector shows it; no popup on top
      openInspector(a.id, 'asset');
    } catch {
      setNotice(`${ref.code} isn't in the live network any more.`);
    }
  }, [qc, flyAndPick, openInspector]);

  const fitBox = useCallback((bbox: [number, number, number, number]) => {
    mapCtx?.map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: 96, maxZoom: 18, duration: 600 });
  }, [mapCtx]);

  const onTrace = useCallback((assetId: string, direction: NetTraceDirection) => {
    setPicked(null);
    startTrace(assetId, direction);
  }, [startTrace]);

  const onContextMenu = useCallback((p: Picked, point: { x: number; y: number }) => {
    setPicked(null);
    setMenu({ picked: p, x: point.x, y: point.y });
  }, []);

  // Deep link: open straight onto one asset or cable, once the map is ready
  useEffect(() => {
    const link = deepLink.current;
    if (!mapCtx || !link) return;
    deepLink.current = null;
    framed.current = true;
    if (link.kind === 'asset') {
      void goTo({ id: link.id, code: 'This asset' });
      return;
    }
    qc.fetchQuery({ queryKey: networkKeys.cable(link.id), queryFn: () => networkApi.getCable(link.id) })
      .then(c => { fitBox(c.bbox); openInspector(c.id, 'cable'); })
      .catch(() => setNotice("This cable isn't in the live network any more."));
  }, [mapCtx, goTo, qc, fitBox, openInspector]);

  // Esc on the map clears the selection (the inspector handles its own Esc)
  useEffect(() => {
    if (inspectorOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.target instanceof HTMLInputElement) return;
      if (picked) clearSelection();
      else if (trace) clearTrace();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [picked, inspectorOpen, clearSelection, trace, clearTrace]);

  useEffect(() => {
    if (!notice) return;
    const t = window.setTimeout(() => setNotice(null), 6000);
    return () => window.clearTimeout(t);
  }, [notice]);

  const empty = !designId && !fttxRunId && registry.data && bounds.data && !bounds.data.bbox;
  const fitDesign = () => { if (design?.bbox) fitBox(design.bbox); };

  return (
    <div ref={setWorkspace} className={s.workspace} data-panel={panelShown ? 'open' : 'closed'}>
      {fttxRunId ? (
        <FttxRunPreviewPanel
          runId={fttxRunId}
          results={fttxResults.data}
          error={fttxResults.error}
          inputLayers={fttxInputLayers.data}
          visible={fttxVisible}
          tableKey={fttxTableKey}
          order={fttxOrder}
          labelFields={fttxLabelFields}
          onMove={moveFttxLayer}
          onLabelField={(key,field)=>setFttxLabelFields(current=>({...current,[key]:field}))}
          onToggle={(key, checked) => setFttxVisible(current => ({ ...current, [key]: checked }))}
          onOpenTable={setFttxTableKey}
          onBack={() => navigate(`/fttx-designer/runs/${fttxRunId}`)}
        />
      ) : designId ? (
        design ? <DesignPanel design={design} onHide={hidePanel} onFit={fitDesign} /> : (
          <aside className={s.panel} aria-label="Design">
            <div className={s.panelHead}>
              <div>
                <h1 className={s.title} tabIndex={-1}>Design</h1>
                <p className={s.summary}>
                  {designQ.isError ? designError(designQ.error, "Couldn't open this design.") : 'Opening the design…'}
                </p>
              </div>
            </div>
          </aside>
        )
      ) : (
        <LayerPanel
          registry={registry.data}
          loading={registry.isLoading}
          error={registry.isError}
          zoom={zoom}
          onHide={hidePanel}
        />
      )}

      <div className={s.mapCell}>
        <MapCanvas className={s.canvas} basemap={basemap} label="Network map" onMapChange={setMapCtx}>
          {registry.data && (
            <NetworkLayers
              registry={registry.data}
              hidden={hidden}
              selectedId={selectedId}
              onPick={onPick}
              onTileError={setTilesFailed}
              dimmed={!!trace || !!designId || !!fttxRunId}
              interactive={!designId && !fttxRunId}
              showCapacity={showCapacity}
              thresholds={catalogue.data?.utilisation_thresholds}
              onContextMenu={onContextMenu}
            />
          )}
          {trace && <TraceLayer trace={traceQ.data} />}
          {design && <DesignMapContent design={design} onPick={onPick} />}
          {fttxRunId && <FttxRunPreviewLayers runId={fttxRunId} results={fttxResults.data} visible={fttxVisible} order={fttxOrder} labelFields={fttxLabelFields} onSelect={(layer,properties)=>setFttxSelected({layer,properties})} />}
          {picked && (
            <FeaturePopup
              picked={picked}
              typeLabel={typeLabel}
              cableLabel={cableLabel}
              onDetails={designId ? undefined : (id, kind) => { setPicked(null); openInspector(id, kind); }}
              onHistory={designId ? (id, code) => { setPicked(null); openHistory(id, code); } : undefined}
              onClose={clearSelection}
            />
          )}
        </MapCanvas>

        <MapSearch typeLabel={typeLabel} onChoose={flyAndPick} />

        {fttxRunId && fttxTableKey && (
          <FttxAttributeTable
            key={`${fttxRunId}:${fttxTableKey}`}
            runId={fttxRunId}
            layerKey={fttxTableKey}
            results={fttxResults.data}
            inputLayers={fttxInputLayers.data}
            onClose={() => setFttxTableKey(null)}
          />
        )}
        {fttxRunId && <FttxRelationshipPanel selected={fttxSelected} results={fttxResults.data} onClose={()=>setFttxSelected(null)} />}

        {design && <DesignOverlays design={design} onFit={fitBox} />}

        {inspectorOpen && selectedId && (
          <AssetInspector
            key={`${selectedKind}:${selectedId}`}
            kind={selectedKind}
            id={selectedId}
            typeLabel={typeLabel}
            cableLabel={cableLabel}
            onClose={closeInspector}
            onZoomTo={(lng, lat) => mapCtx?.map.flyTo({ center: [lng, lat], zoom: Math.max(mapCtx.map.getZoom(), 18) })}
            onFitBounds={fitBox}
            onGoTo={goTo}
            onTrace={onTrace}
          />
        )}

        {trace && (
          <TracePanel
            trace={traceQ.data}
            loading={traceQ.isLoading}
            error={traceQ.isError}
            startCode={traceQ.data?.hops.find(h => h.depth === 0)?.asset.asset_code ?? '…'}
            direction={trace.direction}
            typeLabel={typeLabel}
            cableLabel={c => cableLabel(c as NetCableCategory)}
            onOpen={id => void goTo({ id, code: 'This asset' })}
            onClose={clearTrace}
          />
        )}

        {menu && (
          <MapContextMenu
            title={menu.picked.asset_code}
            x={menu.x}
            y={menu.y}
            onClose={() => setMenu(null)}
            actions={[
              { id: 'details', label: 'Show details', icon: 'details', run: () => openInspector(menu.picked.id, 'asset') },
              { id: 'up', label: 'Trace to OLT', icon: 'up', run: () => onTrace(menu.picked.id, 'upstream') },
              { id: 'down', label: 'Trace what it feeds', icon: 'down', run: () => onTrace(menu.picked.id, 'downstream') },
              { id: 'copy', label: 'Copy code', icon: 'copy', run: () => { void navigator.clipboard?.writeText(menu.picked.asset_code); } },
            ]}
          />
        )}

        {empty && (
          <div className={s.notice} role="status">
            <h2>No network in service yet</h2>
            <p>
              Upload OLTs, cabinets and splitters under Infrastructure, bulk upload. Then use
              Sync uploads in the layer panel to place them on this map.
            </p>
          </div>
        )}
        {notice && <div className={s.notice} role="status"><p style={{ margin: 0 }}>{notice}</p></div>}
      </div>

      {mapCtx ? (
        <MapInstanceProvider value={mapCtx}>
          <ToolRail
            bounds={bounds.data}
            workspace={workspace}
            onLocateError={setNotice}
            panelShown={panelShown}
            onShowPanel={showPanel}
            showCapacity={showCapacity}
            onToggleCapacity={() => setShowCapacity(!showCapacity)}
          />
          <StatusBar tilesFailed={tilesFailed} showCapacity={showCapacity} thresholds={catalogue.data?.utilisation_thresholds} />
        </MapInstanceProvider>
      ) : (
        <>
          <nav className={s.rail} aria-label="Map tools" />
          <footer className={s.status}>Loading map…</footer>
        </>
      )}
    </div>
  );
}
