"""Port of the cable-routing stage from
``FTTx Designer — dual PON integrated.py``: ``_QuietLogger``,
``audit_road_layer_noding``, ``build_noded_routing_layer``, ``CableRouter``,
``_anchor_point_for_device``, ``_line_vertices``, ``_enforce_exact_cable_endpoints``.

``audit_road_layer_noding`` and ``build_noded_routing_layer`` are verbatim
ports (only the QGIS types changed) — ``build_noded_routing_layer`` in
particular needed no real rewrite at all, since its one load-bearing
operation, ``QgsGeometry.unaryUnion()``, was already implemented in Phase 1
on top of Shapely's own ``unary_union``.

``CableRouter`` is NOT a verbatim port. Its ``build_master_graph()`` /
``find_shortest_path_points()`` relied on
``QgsVectorLayerDirector.makeGraph(builder, points)`` — the one QGIS API the
integration plan (§4.2) explicitly decided not to shim, precisely because
doing so would mean re-deriving its point-tying/edge-splitting behavior
anyway, just hidden behind a fake API instead of an honest rewrite. That
rewrite is ``_build_tied_graph()`` below: given the already-noded road
linework (from ``build_noded_routing_layer``, so every true crossing
already shares an exact vertex) and a list of arbitrary device points, it
builds a ``QgsGraph`` with each device point spliced in as an exact graph
vertex on its nearest road segment — chaining multiple device points that
land on the SAME original segment in projected order along it (not each
independently wired back to that segment's two endpoints, which would
insert a spurious detour through the nearest junction for any two devices
sharing one block face — exactly the "over-traversal" class of defect
CLAUDE.md and this file's own comments already document
``RoadTopologyEngine.weighted_shortest_path`` as having, that this master
graph exists specifically to replace).

``NetworkDistanceOracle`` is a verbatim port with one deliberate, documented
adaptation: its unreachability check (``base < 0``) assumes real QGIS's
``QgsGraphAnalyzer.dijkstra`` marks an unreachable vertex's cost with a
negative sentinel. This port's own ``QgsGraphAnalyzer.dijkstra`` (built in
Phase 1, already exercised through Phases 2a-2i) uses ``float('inf')``
instead — every OTHER call site in the source only ever reads the
``tree``/predecessor array for reachability (``tree[v] == -1``, which this
shim reproduces exactly), never the numeric cost, so this is the only place
the sentinel choice is externally visible. Changing the shim's sentinel
this late to match undocumented QGIS C++ behavior would be a wider, riskier
change than adapting the one call site that actually depends on it to the
shim's own documented, already-verified contract — so the check here reads
``base == float('inf')`` instead of ``base < 0``. Observable pipeline
behavior (whether a path exists) is identical either way.

``route_fdt_to_fats`` and ``route_fat_to_homepasses`` are verbatim ports.

``route_legacy_fdt_to_fats_by_road`` (added in the closures.py sub-phase,
once ``CableRouter`` existed to depend on) is also a verbatim port — the
Legacy-cascade counterpart to ``route_fdt_to_fats``'s PCC hop-by-hop
routing: one road-grouped 8-core cable per FDT-road branch (chunked by
``MAX_FAT_PER_WING`` if a road carries more FATs than one cable's tap
budget), routed via the same ``find_shortest_path_points`` /
``_enforce_exact_cable_endpoints`` pair every other routing function here
already uses.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from itertools import permutations
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import runtime_config as rc
from .config import (
    CAPACITY_PROFILES,
    MAX_DEVICE_ROAD_ANCHOR_DISTANCE,
    MASTER_GRAPH_TOPOLOGY_TOLERANCE,
    MAX_FAT_PER_WING,
    NODE_ROADS_FOR_ROUTING,
    NODING_AUDIT_GAP_TOL,
    WING_TO_PON,
    CapacityProfile,
    PONArchitecture,
)
from .domain import FAT, FDT, CableSegment, Homepass
from .errors import ValidationError
from .hop_limits import _b2b_endpoint, b2b_hop_limit
from .pole_routing import build_pole_graph, route_between_supports
from .geometry_compat import (
    QgsFeature,
    QgsGeometry,
    QgsGraph,
    QgsGraphAnalyzer,
    QgsPointXY,
    QgsSpatialIndex,
    QgsVectorLayer,
    QgsWkbTypes,
)
from .perf_logger import PerformanceLogger
from .spatial_utils import DistanceCalculator
from .topology import RoadTopologyEngine, _dedupe_points, _road_vertices


class _QuietLogger:
    """No-op logger shim for call sites that have no logger in scope."""

    def log(self, *_a, **_k) -> None:
        pass

    def error(self, *_a, **_k) -> None:
        pass


def audit_road_layer_noding(road_layer: QgsVectorLayer,
                            dist_calc: 'DistanceCalculator',
                            logger: 'PerformanceLogger',
                            gap_tol: float = NODING_AUDIT_GAP_TOL,
                            max_report: int = 40) -> List[Dict]:
    """Locate every place the road linework fails to node.

    Two defect classes are reported, both of which cut the routing graph:

      NEAR_MISS   a line endpoint sits within *gap_tol* of another line but
                  that line already carries a vertex there — healable by
                  MASTER_GRAPH_TOPOLOGY_TOLERANCE
      T_UNNODED   a line endpoint lies on another line's interior and that
                  line has NO vertex there — only line noding closes this,
                  and it is the class that produces block-perimeter detours

    Emits a WKT point per defect so the coordinate can be pasted straight
    into the QGIS locator bar. Purely diagnostic; changes nothing.
    """
    feats: List[Tuple[int, QgsGeometry]] = []
    for f in road_layer.getFeatures():
        g = f.geometry()
        if g and not g.isEmpty():
            feats.append((f.id(), g))
    if not feats:
        logger.log('NODING-AUDIT: road layer is empty')
        return []

    # Endpoint registry keyed on exact rounded coordinate. Anything whose
    # key is shared by two features is already properly noded.
    endpoints: List[Tuple[int, QgsPointXY]] = []
    exact: Dict[Tuple[float, float], Set[int]] = defaultdict(set)
    for fid, g in feats:
        if g.isMultipart():
            parts = g.asMultiPolyline()
        else:
            parts = [g.asPolyline()]
        for part in parts:
            if not part or len(part) < 2:
                continue
            for p in (part[0], part[-1]):
                endpoints.append((fid, p))
                exact[(round(p.x(), 6), round(p.y(), 6))].add(fid)

    idx = QgsSpatialIndex()
    geoms: Dict[int, QgsGeometry] = {}
    for fid, g in feats:
        geoms[fid] = g
        ft = QgsFeature(fid)
        ft.setGeometry(g)
        idx.addFeature(ft)

    defects: List[Dict] = []
    for fid, p in endpoints:
        key = (round(p.x(), 6), round(p.y(), 6))
        if len(exact.get(key, ())) > 1:
            continue                       # already shares a node
        p_geom = QgsGeometry.fromPointXY(p)
        try:
            neighbours = idx.nearestNeighbor(p, 6)
        except Exception:
            continue
        for other in neighbours:
            if other == fid:
                continue
            og = geoms.get(other)
            if og is None:
                continue
            try:
                d = og.distance(p_geom)
            except Exception:
                continue
            if d > gap_tol:
                continue
            # Does the other line already carry a vertex at this spot?
            try:
                nearest_v = og.closestVertex(p)[0]
            except Exception:
                continue
            v_gap = dist_calc.distance_points(p, nearest_v)
            kind = 'NEAR_MISS' if v_gap <= gap_tol else 'T_UNNODED'
            defects.append({
                'kind':       kind,
                'fid':        fid,
                'other_fid':  other,
                'gap_m':      round(d, 3),
                'vertex_gap': round(v_gap, 3),
                'x':          p.x(),
                'y':          p.y(),
            })
            break

    n_near = sum(1 for d in defects if d['kind'] == 'NEAR_MISS')
    n_tee  = sum(1 for d in defects if d['kind'] == 'T_UNNODED')
    logger.log(
        f'NODING-AUDIT: {len(defects)} unnoded endpoint(s) — '
        f'{n_near} NEAR_MISS (healed by topologyTolerance), '
        f'{n_tee} T_UNNODED (healed by build_noded_routing_layer)'
    )
    # T_UNNODED first: those are the perimeter-detour causes.
    defects.sort(key=lambda d: (d['kind'] != 'T_UNNODED', d['gap_m']))
    for d in defects[:max_report]:
        logger.log(
            f"  {d['kind']:<10} fid {d['fid']} vs {d['other_fid']} "
            f"gap={d['gap_m']}m vertex_gap={d['vertex_gap']}m  "
            f"POINT({d['x']:.2f} {d['y']:.2f})"
        )
    return defects


def build_noded_routing_layer(road_layer: QgsVectorLayer,
                              logger,
                              topology_engine=None) -> QgsVectorLayer:
    """Return an in-memory line layer with fully noded road linework.

    GEOS unaryUnion on a linework set splits every line at every crossing
    and inserts the shared vertex, which is exactly the T_UNNODED case
    MASTER_GRAPH_TOPOLOGY_TOLERANCE cannot reach.

    Falls back to *road_layer* unchanged on any failure, so routing can
    never end up worse off than before this patch.

    The returned layer carries no attributes — this port's
    ``QgsVectorLayer`` has no direction-field concept at all (every graph
    build in this file is effectively DirectionBoth, undirected-by-pair),
    so that part of the original docstring's caveat doesn't apply here.
    """
    if not NODE_ROADS_FOR_ROUTING:
        return road_layer
    try:
        geoms = [f.geometry() for f in road_layer.getFeatures()
                 if f.geometry() and not f.geometry().isEmpty()]
        # Keep the small gap-healing links from RoadTopologyEngine in the
        # graph used by CableRouter too. Otherwise its master graph sees
        # disconnected components and silently falls back to another router.
        connector_pairs = set()
        if topology_engine is not None:
            for node_id, links in topology_engine.adj.items():
                for neighbor_id, road_id, _weight in links:
                    if road_id >= 0 or node_id == neighbor_id:
                        continue
                    pair = tuple(sorted((node_id, neighbor_id)))
                    if pair in connector_pairs:
                        continue
                    a = topology_engine.node_points.get(pair[0])
                    b = topology_engine.node_points.get(pair[1])
                    if a is None or b is None:
                        continue
                    connector_pairs.add(pair)
                    geoms.append(QgsGeometry.fromPolylineXY([a, b]))
        if not geoms:
            return road_layer

        _t0 = time.time()
        merged = QgsGeometry.unaryUnion(geoms)
        if merged is None or merged.isEmpty():
            logger.log('WARNING [NODING]: unaryUnion returned empty; '
                       'routing on the raw road layer')
            return road_layer

        if merged.isMultipart():
            parts = merged.asMultiPolyline()
        else:
            parts = [merged.asPolyline()]
        parts = [p for p in parts if p and len(p) >= 2]
        if not parts:
            logger.log('WARNING [NODING]: unaryUnion produced no usable '
                       'linework; routing on the raw road layer')
            return road_layer

        noded = QgsVectorLayer.from_records(
            [{"geometry": QgsGeometry.fromPolylineXY(part)} for part in parts],
            crs=road_layer.crs(),
            layer_id="roads_noded_routing",
        )

        logger.log(
            f'Topology: routing linework noded — '
            f'{road_layer.featureCount()} road feature(s), '
            f'{len(connector_pairs)} healed connector(s) -> '
            f'{len(parts)} noded segment(s) in {time.time() - _t0:.1f}s'
        )
        return noded
    except Exception as exc:
        try:
            logger.error(f'Road noding failed ({exc}); routing on the raw layer')
        except Exception:
            pass
        return road_layer


# =============================================================================
# Point-tied graph construction — replaces QgsVectorLayerDirector.makeGraph()
# =============================================================================

def _build_tied_graph(
    line_layer: QgsVectorLayer,
    tie_points: Sequence[QgsPointXY] = (),
    tolerance: float = MASTER_GRAPH_TOPOLOGY_TOLERANCE,
) -> Tuple[QgsGraph, List[int]]:
    """Build a QgsGraph from noded road linework, splicing every point in
    ``tie_points`` in as an exact graph vertex on its nearest road segment.

    Returns ``(graph, vertex_ids)`` where ``vertex_ids[i]`` is the graph
    vertex id ``tie_points[i]`` was tied to (or -1 if the road network is
    empty). Multiple tie points landing on the same original road segment
    are chained together in projected order along it — see the module
    docstring for why that matters (it is the one detail that makes this a
    real replacement for ``QgsVectorLayerDirector.makeGraph()`` rather than
    a naive "snap each point to its nearest segment's endpoints").
    """
    graph = QgsGraph()
    node_idx = QgsSpatialIndex()
    node_feats: Dict[int, QgsPointXY] = {}

    def _get_or_create_node(pt: QgsPointXY) -> int:
        if node_feats:
            candidates = node_idx.nearestNeighbor(pt, 1)
            if candidates:
                nid = candidates[0]
                existing = node_feats[nid]
                if ((existing.x() - pt.x()) ** 2 + (existing.y() - pt.y()) ** 2) ** 0.5 <= tolerance:
                    return nid
        nid = graph._add_vertex(pt)
        node_feats[nid] = pt
        feat = QgsFeature(nid)
        feat.setGeometry(QgsGeometry.fromPointXY(pt))
        node_idx.addFeature(feat)
        return nid

    # ── Pass 1: base segments (one per consecutive vertex pair per line) ──
    # segments[i] = (from_nid, to_nid, from_pt, to_pt, length)
    segments: List[Tuple[int, int, QgsPointXY, QgsPointXY, float]] = []
    segment_geoms: List[QgsGeometry] = []
    for feat in line_layer.getFeatures():
        geom = feat.geometry()
        if not geom or geom.isEmpty():
            continue
        verts = _road_vertices(geom)
        for i in range(len(verts) - 1):
            a, b = verts[i], verts[i + 1]
            na = _get_or_create_node(a)
            nb = _get_or_create_node(b)
            seg_geom = QgsGeometry.fromPolylineXY([a, b])
            length = seg_geom.length()
            segments.append((na, nb, a, b, length))
            segment_geoms.append(seg_geom)

    # ── Pass 2: assign each tie point to its nearest base segment ─────────
    tie_points = list(tie_points)
    tied_vertex_ids: List[int] = [-1] * len(tie_points)
    by_segment: Dict[int, List[Tuple[int, float]]] = defaultdict(list)  # seg_idx -> [(tie_idx, chainage)]

    for tie_idx, pt in enumerate(tie_points):
        if not segments:
            continue
        pt_geom = QgsGeometry.fromPointXY(pt)
        best_seg_idx, best_dist = -1, float('inf')
        for seg_idx, seg_geom in enumerate(segment_geoms):
            d = seg_geom.distance(pt_geom)
            if d < best_dist:
                best_dist, best_seg_idx = d, seg_idx
        if best_seg_idx < 0:
            continue
        seg_geom = segment_geoms[best_seg_idx]
        chainage = seg_geom.lineLocatePoint(pt_geom)
        by_segment[best_seg_idx].append((tie_idx, chainage))

    # ── Pass 3: emit edges — plain pass-through segments, and segments
    # with tie points chained in projected order (endpoint -> tie(s) -> endpoint).
    for seg_idx, (na, nb, a, b, length) in enumerate(segments):
        tied_here = by_segment.get(seg_idx)
        if not tied_here:
            graph._add_edge(na, nb, length)
            graph._add_edge(nb, na, length)
            continue

        tied_here.sort(key=lambda t: t[1])
        seg_geom = segment_geoms[seg_idx]
        chain_nids: List[int] = [na]
        for tie_idx, chainage in tied_here:
            proj = seg_geom.interpolate(chainage).asPoint()
            existing = None
            # Reuse `na`/`nb` (or an already-created node here) if the tie
            # point projects essentially onto it — avoids a near-duplicate
            # vertex a few nanometres from a real junction.
            for cand_nid in (na, nb):
                cand_pt = node_feats[cand_nid]
                if ((cand_pt.x() - proj.x()) ** 2 + (cand_pt.y() - proj.y()) ** 2) ** 0.5 <= 1e-6:
                    existing = cand_nid
                    break
            nid = existing if existing is not None else graph._add_vertex(proj)
            if existing is None:
                node_feats[nid] = proj
            tied_vertex_ids[tie_idx] = nid
            if nid != chain_nids[-1]:
                chain_nids.append(nid)
        if chain_nids[-1] != nb:
            chain_nids.append(nb)

        for i in range(len(chain_nids) - 1):
            p1 = node_feats[chain_nids[i]]
            p2 = node_feats[chain_nids[i + 1]]
            seg_len = QgsGeometry.fromPolylineXY([p1, p2]).length()
            graph._add_edge(chain_nids[i], chain_nids[i + 1], seg_len)
            graph._add_edge(chain_nids[i + 1], chain_nids[i], seg_len)

    return graph, tied_vertex_ids


class CableRouter:
    """Handles cable routing along road network.

    Cable endpoints are tied to the road graph by their coordinates. Road
    IDs are metadata and do not select routing anchors.
    """

    def __init__(self, road_layer: QgsVectorLayer, dist_calc: DistanceCalculator,
                 roads: Optional[Dict[int, 'RoadSegment']] = None,
                 road_index: Optional[QgsSpatialIndex] = None,
                 topology_engine: Optional['RoadTopologyEngine'] = None,
                 max_device_road_anchor_distance: float = MAX_DEVICE_ROAD_ANCHOR_DISTANCE):
        self.road_layer      = road_layer
        # [B2B detour fix] Routing runs on NODED linework. self.road_layer
        # stays the user's layer; graph routing reads routing_layer.
        self.routing_layer   = road_layer
        self._routing_layer_ready = False
        self.dist_calc       = dist_calc
        self.roads           = roads or {}
        self.road_index      = road_index
        self.topology_engine = topology_engine   # weighted graph for routing
        self.max_device_road_anchor_distance = max_device_road_anchor_distance
        self._logger         = None  # Optional; routing must work without a logger.
        self.graph_builder   = None
        self.graph           = None
        self._vertex_index: Optional[QgsSpatialIndex] = None
        # ── Master shared-graph cache (perf) ─────────────────────────────
        # See build_master_graph() / _shortest_path_via_master(). Avoids
        # rebuilding the whole road graph on every find_shortest_path_points()
        # call — that used to be the dominant cost of a full run.
        self._master_graph  = None
        self._master_lookup: Dict[Tuple[float, float], int] = {}
        self._master_vcount = 0
        self._master_ecount = 0
        self.route_stats = {'master': 0, 'temp_graph': 0, 'fallback': 0}
        self.route_failures: List[str] = []
        self.route_anchor_misses: List[str] = []
        self.anchor_errors: Dict[Tuple[float, float], str] = {}
        # [Fix 1] Dijkstra tree cache, keyed by source vertex. Invalidated
        # whenever build_master_graph() replaces the graph.
        self._master_tree_cache: Dict[int, Any] = {}
        self.b2b_routing_mode = "road"
        self._support_poles = []
        self._support_adjacency: Dict[int, Dict[int, float]] = {}
        self._support_edge_paths: Dict[Tuple[int, int], List[QgsPointXY]] = {}
        self._support_max_span_m = 60.0
        self.last_support_route_diagnostic: Dict[str, object] = {}
        self.support_component_ids: Dict[int, int] = {}

    def build_support_graph(self, structures, roads, max_junction_span_m=60.0) -> int:
        """Build the optional aerial cable graph from snapped support poles."""
        self._support_max_span_m = max_junction_span_m
        self._support_edge_paths = {}
        self._support_poles, self._support_adjacency = build_pole_graph(
            structures, roads, self.dist_calc,
            topology=self.topology_engine,
            max_junction_span_m=max_junction_span_m,
            edge_paths=self._support_edge_paths,
        )
        self.support_component_ids = {}
        component_id = 0
        for seed in range(len(self._support_poles)):
            if seed in self.support_component_ids:
                continue
            stack = [seed]
            self.support_component_ids[seed] = component_id
            while stack:
                current = stack.pop()
                for neighbor in self._support_adjacency.get(current, {}):
                    if neighbor not in self.support_component_ids:
                        self.support_component_ids[neighbor] = component_id
                        stack.append(neighbor)
            component_id += 1
        return sum(len(neighbors) for neighbors in self._support_adjacency.values()) // 2

    def find_support_path_points(
        self,
        start: QgsPointXY,
        end: QgsPointXY,
        start_anchor: Optional[QgsPointXY],
        end_anchor: Optional[QgsPointXY],
        start_name: Optional[str] = None,
        end_name: Optional[str] = None,
        start_road_id: Optional[int] = None,
        end_road_id: Optional[int] = None,
    ) -> Tuple[QgsGeometry, float]:
        """Route a box-to-box hop over connected support structures."""
        self.last_support_route_diagnostic = {}
        geometry = route_between_supports(
            self._support_poles,
            self._support_adjacency,
            self.dist_calc,
            start,
            end,
            start_anchor,
            end_anchor,
            start_name,
            end_name,
            max_direct_span_m=self._support_max_span_m,
            edge_paths=self._support_edge_paths,
            diagnostic=self.last_support_route_diagnostic,
        )
        if geometry is None or geometry.isEmpty():
            return QgsGeometry(), 0.0
        points = geometry.asPolyline()
        length = sum(
            self.dist_calc.distance_points(left, right)
            for left, right in zip(points, points[1:])
        )
        straight = self.dist_calc.distance_points(start, end)
        if (straight > 0.01 and length >= 120.0 and length / straight >= 2.5):
            # Support graphs can be disconnected too. For suspect pole routes,
            # compare with the road graph's road-ID-aware recovery path.
            road_geom, road_length = self.find_shortest_path_points(
                start, end, start_road_id=start_road_id,
                end_road_id=end_road_id,
            )
            if (road_geom is not None and not road_geom.isEmpty()
                    and 0 < road_length < length):
                return road_geom, road_length
        return geometry, length

    def _ensure_routing_layer(self, logger=None) -> QgsVectorLayer:
        """Build (once) the noded layer every graph director should use.

        Lazy because noding costs one unaryUnion over the whole road layer
        and several call sites never build a graph at all. *logger* is
        optional: build_master_graph() has no logger in scope, so a no-op
        shim is used there and the noding line is logged by whichever site
        does have one.
        """
        if self._routing_layer_ready:
            return self.routing_layer
        self.routing_layer = build_noded_routing_layer(
            self.road_layer, logger if logger is not None else _QuietLogger(),
            topology_engine=self.topology_engine)
        self._routing_layer_ready = True
        return self.routing_layer

    def _road_snap(self, device_point: QgsPointXY,
                   road_id: Optional[int]) -> QgsPointXY:
        """Project device point onto its assigned road's geometry.

        FATs and FDTs are placed slightly off the road centre-line (frontage
        offset, pole-snap offset). If we give their offset coordinates directly
        to the graph nearest-vertex lookup we often snap to a vertex on a
        *different* road whose vertex happens to be Euclidean-closer. Dijkstra
        then routes through that wrong road and the subsequent
        ``_enforce_exact_cable_endpoints`` stub cuts across buildings.

        This method projects the device point onto its *own* road geometry to
        get a road-edge anchor that is guaranteed to be on the correct road.

        Returns the nearest point ON THE SPECIFIED ROAD, not just globally
        nearest. This prevents cross-road vertex snapping that causes
        building-crossing cables.

        Args:
            device_point: The device's actual position (may be offset from road)
            road_id: The road this device belongs to

        Returns:
            Point projected onto the device's road, or original point if
            road_id is None or road geometry unavailable.
        """
        if road_id is None:
            return device_point

        if not self.roads or road_id not in self.roads:
            return device_point

        road = self.roads.get(road_id)
        if road is None:
            return device_point

        road_geom = getattr(road, 'geometry', None)
        if road_geom is None or road_geom.isEmpty():
            return device_point

        # Project device point onto its assigned road's geometry
        device_geom = QgsGeometry.fromPointXY(device_point)
        nearest = road_geom.nearestPoint(device_geom)

        if nearest is None or nearest.isEmpty():
            return device_point

        return nearest.asPoint()

    def _device_road_anchor_error(self, point: QgsPointXY,
                                  road_id: Optional[int]) -> Optional[str]:
        """Explain why a device cannot be anchored to its assigned road."""
        if road_id is None:
            return None
        road = self.roads.get(road_id)
        if road is None or not road.geometry or road.geometry.isEmpty():
            return f"assigned road {road_id} is missing or has empty geometry"
        gap = self.dist_calc.distance(
            QgsGeometry.fromPointXY(point), road.geometry,
        )
        if gap > self.max_device_road_anchor_distance:
            return (f"device is {gap:.2f} m from assigned road {road_id}; "
                    f"maximum is {self.max_device_road_anchor_distance:.2f} m")
        return None

    def build_master_graph(
        self,
        points: List[QgsPointXY],
        point_road_ids: Optional[Dict[Tuple[float, float], int]] = None,
    ) -> int:
        """Build ONE shared road graph with every given point tied in as an
        exact graph vertex, via ``_build_tied_graph()``.

        Call this ONCE up front with every device point (FDT/FAT/closure/
        pickup) that routing will need this pass. After this, calls to
        find_shortest_path_points() for any pair of pre-registered points
        reuse this cached graph and only pay the Dijkstra cost — not the
        cost of re-digitizing the entire road layer, which is what made
        find_shortest_path_points() so expensive when called once per cable
        hop (thousands of times on a real network).

        Returns the number of input points successfully tied into the graph.
        Coincident points share a lookup key/graph location but each counts
        as tied; multiple devices may legitimately occupy the same position.
        """
        self._master_graph  = None
        self._master_lookup = {}
        self._master_vcount = 0
        self._master_ecount = 0
        self._master_tree_cache = {}
        self.route_stats = {'master': 0, 'temp_graph': 0, 'fallback': 0}
        self.route_anchor_misses = []
        self.route_failures = []
        self.anchor_errors = {}

        if not points:
            return 0

        try:
            _rl = self._ensure_routing_layer()
            # Tie each device to its known road. A globally nearest segment
            # can be the wrong carriageway or a nearby parallel street, which
            # turns an otherwise short B2B hop into a large graph detour.
            graph_points = []
            for pt in points:
                key = (round(pt.x(), 6), round(pt.y(), 6))
                road_id = (point_road_ids or {}).get(key)
                error = self._device_road_anchor_error(pt, road_id)
                if error:
                    self.anchor_errors[key] = error
                    graph_points.append(pt)
                else:
                    graph_points.append(self._road_snap(pt, road_id))
            graph, vertex_ids = _build_tied_graph(
                _rl, graph_points, tolerance=MASTER_GRAPH_TOPOLOGY_TOLERANCE,
            )
        except Exception:
            return 0

        if not vertex_ids or len(vertex_ids) != len(points):
            return 0

        lookup: Dict[Tuple[float, float], int] = {}
        for orig_pt, v in zip(points, vertex_ids):
            if v >= 0:
                key = (round(orig_pt.x(), 6), round(orig_pt.y(), 6))
                lookup[key] = v

        self._master_graph  = graph
        self._master_lookup = lookup
        self._master_vcount = graph.vertexCount()
        self._master_ecount = graph.edgeCount()
        # The lookup is keyed by coordinates, so coincident FATs collapse to
        # one entry. Count input anchors instead: each coincident point is
        # still tied to the same valid graph vertex.
        return sum(
            1 for pt in points
            if (round(pt.x(), 6), round(pt.y(), 6)) in lookup
        )

    def _shortest_path_via_master(self, start: QgsPointXY,
                                   end: QgsPointXY
                                   ) -> Optional[Tuple[QgsGeometry, float]]:
        """Fast path for find_shortest_path_points() using the cached
        master graph built by build_master_graph().

        Returns None (not a routing failure — a cache miss) if either point
        wasn't included when the master graph was built, so the caller can
        fall back to the slower per-call graph rebuild.
        """
        graph = self._master_graph
        if graph is None or not self._master_lookup:
            return None

        key_s = (round(start.x(), 6), round(start.y(), 6))
        key_e = (round(end.x(), 6), round(end.y(), 6))
        start_v = self._master_lookup.get(key_s, -1)
        end_v   = self._master_lookup.get(key_e, -1)
        if start_v < 0 or end_v < 0:
            return None

        if start_v == end_v:
            pt = graph.vertex(start_v).point()
            g  = QgsGeometry.fromPolylineXY([pt, pt])
            return g, 0.0

        # [Fix 1] One Dijkstra per SOURCE vertex, not per pair. Every wing fans
        # out from the same FDT and each FAT is the source for its own outgoing
        # hop, so on a 24-FDT/186-FAT design this collapses ~186 graph searches
        # to at most ~210 and makes repeated queries free.
        tree = self._master_tree_cache.get(start_v)
        if tree is None:
            tree, _ = QgsGraphAnalyzer.dijkstra(graph, start_v, 0)
            self._master_tree_cache[start_v] = tree
        v_count = self._master_vcount
        e_count = self._master_ecount

        if end_v >= len(tree) or tree[end_v] == -1:
            return None

        pts: List[QgsPointXY] = []
        current = end_v
        steps   = 0
        max_s   = v_count + e_count + 10
        while current != start_v:
            if current < 0 or current >= v_count:
                return None
            pts.append(graph.vertex(current).point())
            eid = tree[current]
            if eid < 0 or eid >= e_count:
                return None
            current = graph.edge(eid).fromVertex()
            steps  += 1
            if steps > max_s:
                return None

        pts.append(graph.vertex(start_v).point())
        pts.reverse()
        pts = _dedupe_points(pts)
        if len(pts) < 2:
            return None

        # Keep the road graph's tied vertices and connect the real device
        # coordinates with endpoint stubs. Replacing these vertices later
        # stretches the first/last road edge into a chord across nearby lots.
        if abs(pts[0].x() - start.x()) > 1e-8 or abs(pts[0].y() - start.y()) > 1e-8:
            pts.insert(0, start)
        if abs(pts[-1].x() - end.x()) > 1e-8 or abs(pts[-1].y() - end.y()) > 1e-8:
            pts.append(end)
        pts = _dedupe_points(pts)

        geom = QgsGeometry.fromPolylineXY(pts)
        return geom, geom.length()

    def build_graph(self):
        """Build graph from road network (no tie points — used only by the
        legacy vertex-nearest fallback path, see find_shortest_path)."""
        _rl = self._ensure_routing_layer()
        graph, _ = _build_tied_graph(_rl, [], tolerance=MASTER_GRAPH_TOPOLOGY_TOLERANCE)
        self.graph = graph
        self._vertex_index = self._build_vertex_spatial_index()

    def _build_vertex_spatial_index(self) -> Optional[QgsSpatialIndex]:
        """Build spatial index of graph vertices for fast nearest-vertex lookup."""
        if not self.graph:
            return None
        idx = QgsSpatialIndex()
        for i in range(self.graph.vertexCount()):
            pt = self.graph.vertex(i).point()
            feat = QgsFeature(i)
            feat.setGeometry(QgsGeometry.fromPointXY(pt))
            idx.addFeature(feat)
        return idx

    def find_shortest_path_points(self,
                                   start: QgsPointXY,
                                   end: QgsPointXY,
                                   start_road_id: Optional[int] = None,
                                   end_road_id: Optional[int] = None) -> Tuple[QgsGeometry, float]:
        """Find the true shortest road path between two arbitrary points.

        Builds a temporary graph with the two points tied in via
        ``_build_tied_graph``, guaranteeing both endpoints become exact
        graph nodes so Dijkstra always finds the globally shortest path —
        no nearest-vertex rounding error, no long detours.

        Falls back to find_shortest_path (vertex-nearest approach) if the
        temporary graph build fails.

        Args:
            start: Start device point
            end: End device point
            start_road_id: Road ID the start device belongs to (prevents wrong-road snapping)
            end_road_id: Road ID the end device belongs to (prevents wrong-road snapping)

        Returns:
            Tuple of (cable geometry, cable length)
        """
        for point, road_id in ((start, start_road_id), (end, end_road_id)):
            key = (round(point.x(), 6), round(point.y(), 6))
            error = self.anchor_errors.get(key) or self._device_road_anchor_error(
                point, road_id,
            )
            if error:
                self.anchor_errors[key] = error
                return QgsGeometry(), 0.0

        # When both devices belong to the same road feature, route only the
        # road substring between their projections. This avoids a nearby
        # junction or parallel street pulling a same-road hop into a loop.
        if (start_road_id is not None and start_road_id == end_road_id
                and start_road_id in self.roads):
            road = self.roads[start_road_id]
            road_geom = getattr(road, 'geometry', None)
            if road_geom is not None and not road_geom.isEmpty():
                start_snap = self._road_snap(start, start_road_id)
                end_snap = self._road_snap(end, end_road_id)
                start_chain = road_geom.lineLocatePoint(
                    QgsGeometry.fromPointXY(start_snap))
                end_chain = road_geom.lineLocatePoint(
                    QgsGeometry.fromPointXY(end_snap))
                if start_chain >= 0 and end_chain >= 0:
                    interior = []
                    for vertex in _road_vertices(road_geom):
                        chain = road_geom.lineLocatePoint(
                            QgsGeometry.fromPointXY(vertex))
                        if min(start_chain, end_chain) + 1e-3 < chain < max(start_chain, end_chain) - 1e-3:
                            interior.append((chain, vertex))
                    interior.sort(key=lambda item: item[0], reverse=start_chain > end_chain)
                    pts = _dedupe_points(
                        [start, start_snap]
                        + [vertex for _, vertex in interior]
                        + [end_snap, end]
                    )
                    if len(pts) >= 2:
                        self.route_stats['temp_graph'] += 1
                        geom = QgsGeometry.fromPolylineXY(pts)
                        return geom, geom.length()

        # ── Fast path: Try master graph FIRST with exact input coordinates.
        # The master was built with post-snap device positions, so a second
        # road-snap here creates coordinate drift and lookup misses.
        via_master = self._shortest_path_via_master(start, end)
        if via_master is not None:
            self.route_stats['master'] += 1
            master_geom, master_length = via_master
            straight_length = self.dist_calc.distance_points(start, end)
            if (straight_length > 0.01 and master_length >= 120.0
                    and master_length / straight_length >= 2.5):
                # The master graph can still inherit a cut where input roads
                # are disconnected. Compare with the topology graph, which
                # knows about road IDs and its explicit gap-healing links.
                if (self.topology_engine is not None
                        and self.topology_engine.adj):
                    topo_geom, topo_length = self.topology_engine.weighted_shortest_path(
                        start, end, start_road_id=start_road_id,
                        end_road_id=end_road_id,
                    )
                    if (topo_geom is not None and not topo_geom.isEmpty()
                            and topo_length > 0
                            and topo_length < master_length):
                        master_geom, master_length = topo_geom, topo_length
                        self.route_stats['fallback'] += 1

                # If the boxes are only a few metres apart, a short connector
                # between their own road projections is safer than sending a
                # local hop around an entire disconnected graph component.
                if straight_length <= 15.0:
                    start_snap = self._road_snap(start, start_road_id)
                    end_snap = self._road_snap(end, end_road_id)
                    local_pts = _dedupe_points(
                        [start, start_snap, end_snap, end]
                    )
                    local_geom = QgsGeometry.fromPolylineXY(local_pts)
                    local_length = local_geom.length()
                    if (len(local_pts) >= 2
                            and local_length <= 2.0 * straight_length + 3.0
                            and local_length < master_length):
                        self.route_stats['fallback'] += 1
                        return local_geom, local_length
            if master_geom is not via_master[0]:
                return master_geom, master_length
            return via_master

        # ── Fallback path: Road-snap for temp graph build ──
        # Only apply road-snap when building a one-off graph, to prevent
        # cross-road vertex snapping that causes building-crossing cables.
        start_road_pt = self._road_snap(start, start_road_id)
        end_road_pt = self._road_snap(end, end_road_id)

        try:
            _rl = self._ensure_routing_layer()
            # Use road-snapped points for graph building to ensure correct road assignment
            graph, vertex_ids = _build_tied_graph(
                _rl, [start_road_pt, end_road_pt], tolerance=MASTER_GRAPH_TOPOLOGY_TOLERANCE,
            )

            if not vertex_ids or len(vertex_ids) < 2:
                return self.find_shortest_path(start, end, start_road_id=start_road_id, end_road_id=end_road_id)

            start_v, end_v = vertex_ids[0], vertex_ids[1]
            if start_v < 0 or end_v < 0:
                return self.find_shortest_path(start, end, start_road_id=start_road_id, end_road_id=end_road_id)

            # [Physical contact fix] The tied vertex is the point ON the road
            # network nearest the device — for a pole-mounted device sitting
            # even slightly off the road centre-line, that is NOT the
            # device's own coordinate. Without the stub appended below, the
            # returned geometry stops at the road and never actually reaches
            # the device.
            def _with_device_stubs(path_pts: List[QgsPointXY]) -> Tuple[QgsGeometry, float]:
                full = list(path_pts)
                if abs(full[0].x() - start.x()) > 1e-8 or abs(full[0].y() - start.y()) > 1e-8:
                    full.insert(0, start)
                if abs(full[-1].x() - end.x()) > 1e-8 or abs(full[-1].y() - end.y()) > 1e-8:
                    full.append(end)
                full = _dedupe_points(full)
                if len(full) < 2:
                    return QgsGeometry(), 0.0
                g = QgsGeometry.fromPolylineXY(full)
                return g, g.length()

            if start_v == end_v:
                pt = graph.vertex(start_v).point()
                result = _with_device_stubs([pt, pt])
                if result[0] and not result[0].isEmpty():
                    self.route_stats['temp_graph'] += 1
                return result

            tree, cost = QgsGraphAnalyzer.dijkstra(graph, start_v, 0)

            if end_v >= len(tree) or tree[end_v] == -1:
                return self.find_shortest_path(start, end, start_road_id=start_road_id, end_road_id=end_road_id)

            # Reconstruct path
            pts     = []
            current = end_v
            v_count = graph.vertexCount()
            e_count = graph.edgeCount()
            steps   = 0
            max_s   = v_count + e_count + 10

            while current != start_v:
                if current < 0 or current >= v_count:
                    return self.find_shortest_path(start, end, start_road_id=start_road_id, end_road_id=end_road_id)
                pts.append(graph.vertex(current).point())
                eid = tree[current]
                if eid < 0 or eid >= e_count:
                    return self.find_shortest_path(start, end, start_road_id=start_road_id, end_road_id=end_road_id)
                current = graph.edge(eid).fromVertex()
                steps  += 1
                if steps > max_s:
                    return self.find_shortest_path(start, end, start_road_id=start_road_id, end_road_id=end_road_id)

            pts.append(graph.vertex(start_v).point())
            pts.reverse()

            pts = _dedupe_points(pts)
            if len(pts) < 2:
                return self.find_shortest_path(start, end, start_road_id=start_road_id, end_road_id=end_road_id)

            result = _with_device_stubs(pts)
            if result[0] and not result[0].isEmpty():
                self.route_stats['temp_graph'] += 1
            return result

        except Exception:
            # Any failure: fall back to the standard vertex-nearest approach
            return self.find_shortest_path(start, end, start_road_id=start_road_id, end_road_id=end_road_id)

    def find_shortest_path(self, start: QgsPointXY, end: QgsPointXY,
                           constraints: Optional[Dict] = None,
                           start_road_id: Optional[int] = None,
                           end_road_id: Optional[int] = None) -> Tuple[QgsGeometry, float]:
        """Find shortest path along road network between two device points.

        Routing strategy (priority order):
          1. Topology-engine weighted Dijkstra (preferred) — uses road-class
             weights, turn-penalty, and virtual connectors for OSM gap healing.
             Returns empty geometry on routing failure (never straight-line).
          2. Legacy graph Dijkstra (fallback when no topology engine).
             Also returns empty geometry on failure instead of a straight line.

        Callers must check `geom.isEmpty()` and log ROUTING_FAILURE accordingly.
        """
        self.route_stats['fallback'] += 1

        def _fail() -> Tuple[QgsGeometry, float]:
            return QgsGeometry(), 0.0

        # ── Path 1: topology-engine weighted Dijkstra ────────────────────
        if self.topology_engine is not None and self.topology_engine.adj:
            return self.topology_engine.weighted_shortest_path(
                start, end, start_road_id=start_road_id,
                end_road_id=end_road_id)

        # ── Path 2: legacy graph Dijkstra ────────────────────────────────
        if not self.graph:
            self.build_graph()

        # Apply road-snap to ensure devices snap to vertices on their assigned road
        start_road_pt = self._road_snap(start, start_road_id)
        end_road_pt   = self._road_snap(end, end_road_id)
        start_vertex  = self.find_nearest_vertex(start_road_pt)
        end_vertex    = self.find_nearest_vertex(end_road_pt)

        if start_vertex < 0 or end_vertex < 0:
            return _fail()

        if start_vertex == end_vertex:
            pts = _dedupe_points([start, start_road_pt, end_road_pt, end])
            if len(pts) < 2:
                return _fail()
            return QgsGeometry.fromPolylineXY(pts), sum(
                self.dist_calc.distance_points(pts[i], pts[i + 1])
                for i in range(len(pts) - 1)
            )

        tree, _ = QgsGraphAnalyzer.dijkstra(self.graph, start_vertex, 0)

        if end_vertex >= len(tree) or tree[end_vertex] == -1:
            return _fail()   # disconnected graph — no straight-line fallback

        vertex_count = self.graph.vertexCount()
        edge_count   = self.graph.edgeCount()
        if end_vertex < 0 or end_vertex >= vertex_count:
            return _fail()

        try:
            graph_pts = [self.graph.vertex(end_vertex).point()]
        except Exception:
            return _fail()

        current   = end_vertex
        max_steps = vertex_count + edge_count + 10
        steps     = 0
        while current != start_vertex:
            if current < 0 or current >= len(tree):
                return _fail()
            edge_id = tree[current]
            if edge_id < 0 or edge_id >= edge_count:
                return _fail()
            edge    = self.graph.edge(edge_id)
            current = edge.fromVertex()
            if current < 0 or current >= vertex_count:
                return _fail()
            try:
                graph_pts.append(self.graph.vertex(current).point())
            except Exception:
                return _fail()
            steps += 1
            if steps > max_steps:
                return _fail()

        graph_pts.reverse()
        full_path = _dedupe_points(
            [start, start_road_pt] + graph_pts + [end_road_pt, end]
        )
        if len(full_path) < 2:
            return _fail()
        geom = QgsGeometry.fromPolylineXY(full_path)
        return geom, geom.length()

    def find_nearest_vertex(self, point: QgsPointXY) -> int:
        """Find nearest vertex index in graph. Uses spatial index when available."""
        if not self.graph:
            return -1
        if self._vertex_index:
            nearest = self._vertex_index.nearestNeighbor(point, 1)
            return nearest[0] if nearest else -1
        best_idx  = -1
        best_dist = float('inf')
        for i in range(self.graph.vertexCount()):
            vertex_point = self.graph.vertex(i).point()
            dist = self.dist_calc.distance_points(point, vertex_point)
            if dist < best_dist:
                best_dist = dist
                best_idx  = i
        return best_idx


def _anchor_point_for_device(geom: QgsGeometry) -> QgsPointXY:
    """Return exact anchor point for a device geometry."""
    if not geom or geom.isEmpty():
        raise ValidationError("Device geometry is empty")
    gtype = QgsWkbTypes.geometryType(geom.wkbType())
    if gtype == QgsWkbTypes.PointGeometry:
        return geom.asPoint()
    if gtype == QgsWkbTypes.PolygonGeometry:
        return geom.centroid().asPoint()
    if gtype == QgsWkbTypes.LineGeometry:
        return geom.centroid().asPoint()
    return geom.centroid().asPoint()


def _line_vertices(line_geom: QgsGeometry) -> List[QgsPointXY]:
    """Extract polyline vertices from single/multi line geometry."""
    if not line_geom or line_geom.isEmpty():
        return []
    if line_geom.isMultipart():
        parts = line_geom.asMultiPolyline()
        return list(parts[0]) if parts and parts[0] else []
    return list(line_geom.asPolyline())


def _enforce_exact_cable_endpoints(cable_geom: QgsGeometry,
                                   from_geom: QgsGeometry,
                                   to_geom: QgsGeometry) -> QgsGeometry:
    """Connect device anchors while preserving the road-route vertices.

    Replacing a graph endpoint with an offset device coordinate stretches the
    adjoining road edge into a straight chord. Add the device anchors as
    stubs instead, keeping the road path intact.
    """
    from_pt = _anchor_point_for_device(from_geom)
    to_pt = _anchor_point_for_device(to_geom)

    vertices = _line_vertices(cable_geom)
    if len(vertices) < 2:
        raise ValidationError("Cannot restore cable endpoints: road routing returned no usable path")

    if abs(vertices[0].x() - from_pt.x()) > 1e-8 or abs(vertices[0].y() - from_pt.y()) > 1e-8:
        vertices.insert(0, from_pt)
    if abs(vertices[-1].x() - to_pt.x()) > 1e-8 or abs(vertices[-1].y() - to_pt.y()) > 1e-8:
        vertices.append(to_pt)
    vertices = _dedupe_points(vertices)

    fixed = QgsGeometry.fromPolylineXY(vertices)

    # Strict zero-gap checks.
    fixed_vertices = _line_vertices(fixed)
    if len(fixed_vertices) < 2:
        raise ValidationError("Cable geometry has insufficient vertices after endpoint snapping")
    start_v = fixed_vertices[0]
    end_v = fixed_vertices[-1]

    distance_start = QgsGeometry.fromPointXY(start_v).distance(from_geom)
    distance_end = QgsGeometry.fromPointXY(end_v).distance(to_geom)
    if distance_start != 0 or distance_end != 0:
        raise ValidationError(
            f"Cable endpoint gap detected: start={distance_start}, end={distance_end}"
        )

    if not fixed.intersects(from_geom) or not fixed.intersects(to_geom):
        raise ValidationError("Cable does not intersect one or both device geometries")

    # touches() can be false for valid point-endpoint cases (and degenerate same-point links)
    # even when endpoint equality and intersects() are already satisfied.
    if (not fixed.touches(from_geom)) and distance_start != 0:
        raise ValidationError("Cable start does not touch source geometry")
    if (not fixed.touches(to_geom)) and distance_end != 0:
        raise ValidationError("Cable end does not touch destination geometry")

    return fixed


class NetworkDistanceOracle:
    """Authoritative device-to-device distance, measured on the routing graph.

    Returns None from :meth:`distance` when it cannot answer (no master graph
    built yet, or the graph has no reachable path). Callers fall back to the
    legacy estimate in that case, so the oracle is always safe to consult.
    """

    def __init__(self,
                 cable_router: 'CableRouter',
                 dist_calc: Optional['DistanceCalculator'] = None,
                 logger: Optional['PerformanceLogger'] = None):
        self._router     = cable_router
        self._dist_calc  = dist_calc
        self._logger     = logger
        self._cost_cache: Dict[int, Any] = {}
        self._pair_cache: Dict[Tuple[int, int], Optional[float]] = {}
        self._vertex_index: Optional[QgsSpatialIndex] = None
        self._vertex_pts: Dict[int, QgsPointXY] = {}
        # [Phase 6 load-test fix] Memoizes _vertex_for()'s fallback
        # resolution (the nearestNeighbor spatial query) per exact query
        # point. FDT anchors move constantly during the repair/rebalance
        # convergence loop, so their post-move coordinates never land in
        # `_master_lookup` (built once, from the graph's tie-in-time
        # positions) — every distance query against a moved anchor was
        # re-running the full nearest-vertex spatial search from scratch.
        # Profiling a 2,640-homepass load test found this fallback firing
        # ~157,000 times in one Wing Distribution stage, because the SAME
        # handful of moved anchors get re-queried against many different
        # FATs across many repair passes. This cache means each distinct
        # anchor position pays the spatial-search cost once, not once per
        # query — a pure memoization of an idempotent lookup (the same
        # point always resolves to the same vertex against a fixed graph),
        # invalidated in refresh() below whenever the graph itself changes.
        self._fallback_cache: Dict[Tuple[float, float], Tuple[int, float]] = {}
        self._generation = 0
        self.stats = {'exact': 0, 'nearest': 0, 'nearest_cached': 0, 'dijkstra': 0, 'unanswered': 0}

    # ── graph plumbing ───────────────────────────────────────────────────
    def _graph(self):
        return getattr(self._router, '_master_graph', None)

    def refresh(self) -> None:
        """Drop every cache. Call after the master graph is rebuilt (e.g. once
        device geometry has been moved by snap_to_structures)."""
        self._cost_cache.clear()
        self._pair_cache.clear()
        self._fallback_cache.clear()
        self._vertex_index = None
        self._vertex_pts = {}
        self._generation += 1

    def _ensure_vertex_index(self) -> None:
        """Spatial index over master-graph vertices, for points that were not
        tied in when the graph was built.

        FDT anchors move during the convergence loop (recentralisation,
        _refresh_fdt_primary_road), so their post-move coordinates are not in
        the exact-match lookup. Without this fallback every such query would
        miss and fall back to the legacy estimate, which is precisely the
        inconsistency this class exists to remove.
        """
        if self._vertex_index is not None:
            return
        graph = self._graph()
        if graph is None:
            return
        idx = QgsSpatialIndex()
        pts: Dict[int, QgsPointXY] = {}
        try:
            for i in range(graph.vertexCount()):
                pt = graph.vertex(i).point()
                pts[i] = pt
                feat = QgsFeature(i)
                feat.setGeometry(QgsGeometry.fromPointXY(pt))
                idx.addFeature(feat)
        except Exception:
            return
        self._vertex_index = idx
        self._vertex_pts = pts

    def _vertex_for(self, pt: QgsPointXY) -> Tuple[int, float]:
        """Resolve a point to a master-graph vertex.

        Returns ``(vertex_id, residual_m)`` where residual_m is the straight-line
        gap between the requested point and the vertex it resolved to. For points
        tied into the graph at build time the residual is zero; for anything else
        it is the frontage/anchor offset, which is added back into the reported
        distance so the answer still describes the full cable run.
        """
        graph = self._graph()
        if graph is None or pt is None:
            return -1, 0.0

        lookup = getattr(self._router, '_master_lookup', None) or {}
        key = (round(pt.x(), 6), round(pt.y(), 6))
        v = lookup.get(key, -1)
        if v >= 0:
            self.stats['exact'] += 1
            return v, 0.0

        cached = self._fallback_cache.get(key)
        if cached is not None:
            self.stats['nearest_cached'] += 1
            return cached

        self._ensure_vertex_index()
        if self._vertex_index is None:
            return -1, 0.0
        try:
            near = self._vertex_index.nearestNeighbor(pt, 1)
        except Exception:
            return -1, 0.0
        if not near:
            return -1, 0.0
        vid = int(near[0])
        vpt = self._vertex_pts.get(vid)
        if vpt is None:
            return -1, 0.0
        self.stats['nearest'] += 1
        if self._dist_calc is not None:
            residual = self._dist_calc.distance_points(pt, vpt)
        else:
            residual = math.sqrt((pt.x() - vpt.x()) ** 2 + (pt.y() - vpt.y()) ** 2)
        self._fallback_cache[key] = (vid, residual)
        return vid, residual

    def _costs_from(self, source_v: int):
        """Cached Dijkstra cost array from one source vertex."""
        cached = self._cost_cache.get(source_v)
        if cached is not None:
            return cached
        graph = self._graph()
        if graph is None:
            return None
        try:
            _tree, cost = QgsGraphAnalyzer.dijkstra(graph, source_v, 0)
        except Exception:
            return None
        self.stats['dijkstra'] += 1
        self._cost_cache[source_v] = cost
        return cost

    # ── public API ───────────────────────────────────────────────────────
    def distance(self, pt_a: QgsPointXY, pt_b: QgsPointXY) -> Optional[float]:
        """Road-network distance between two device anchors, or None."""
        if pt_a is None or pt_b is None:
            return None
        if self._graph() is None:
            return None

        va, res_a = self._vertex_for(pt_a)
        vb, res_b = self._vertex_for(pt_b)
        if va < 0 or vb < 0:
            self.stats['unanswered'] += 1
            return None
        if va == vb:
            return res_a + res_b

        pair = (va, vb) if va <= vb else (vb, va)
        if pair in self._pair_cache:
            base = self._pair_cache[pair]
            if base is None:
                self.stats['unanswered'] += 1
                return None
            return base + res_a + res_b

        cost = self._costs_from(va)
        if cost is None or vb >= len(cost):
            self._pair_cache[pair] = None
            self.stats['unanswered'] += 1
            return None
        base = cost[vb]
        # [Adapted, see module docstring] this shim's QgsGraphAnalyzer.dijkstra
        # marks unreachable vertices with float('inf'), not a negative sentinel.
        if base is None or base == float('inf'):
            self._pair_cache[pair] = None
            self.stats['unanswered'] += 1
            return None
        base = float(base)
        self._pair_cache[pair] = base
        return base + res_a + res_b

    def is_live(self) -> bool:
        return self._graph() is not None


def route_fdt_to_fats(fdts: List[FDT],
                     cable_router: CableRouter,
                     logger: PerformanceLogger,
                     profile: Optional['CapacityProfile'] = None) -> List[CableSegment]:
    """Route PCC box-to-box cables as discrete hop segments.

    Physical model
    --------------
    Each cable runs between exactly two adjacent devices:

        FDT-01 ──B2B_FDT-01_FAT-01A-01──► FAT-01A-01
                                                │
                                   B2B_FAT-01A-01_FAT-01A-02
                                                │
                                           ► FAT-01A-02  …  ► FAT-01A-04 (terminus)

    Wing B is identical, rooted at the FDT Port B output.

    This replaces the previous single-run tap model (one cable per wing,
    intermediate FATs as tap points) with one CableSegment per hop so that:
      - BOQ yields per-segment lengths and core assignments directly
      - start_device / end_device are always an adjacent pair
      - cable name unambiguously identifies the hop: B2B_{from}_{to}

    Chain source
    ------------
    from_device / to_device on each FAT are set by create_fdt_wing_cascades
    (which runs before this function).  The head of each wing is the FAT
    whose from_device == fdt.name.  Fallback: sort by fat_sequence.

    Naming convention
    -----------------
    Cable:  B2B_{from_device}_{fat.name}
            e.g.  B2B_FDT-01_FAT-01A-01
                  B2B_FAT-01A-01_FAT-01A-02
    """
    logger.start_module("FDT to FAT Routing")
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]

    cables: List[CableSegment] = []

    fat_by_name: Dict[str, FAT] = {}
    for fdt in fdts:
        for fat in fdt.fats:
            fat_by_name[fat.name] = fat

    for fdt in fdts:
        fdt_point   = fdt.snapped_geometry or fdt.geometry
        fdt_road_id: Optional[int] = fdt.primary_road_id
        if fdt_road_id is None and fdt.fats:
            from collections import Counter as _C
            fdt_road_id = _C(f.road_id for f in fdt.fats).most_common(1)[0][0]

        # Loop profile.wings (2 for Single-PON, 4 for Dual-PON) instead of a
        # hardcoded A/B pair — Blocker 5. Each wing still gets its own
        # independent chain, rooted at the FDT anchor, exactly as today.
        for wing in profile.wings:
            wing_fats_all = [fat for fat in fdt.fats if fat.wing == wing]
            if not wing_fats_all:
                continue
            wing_pon = WING_TO_PON.get(wing, 1)

            # ── Reconstruct ordered chain from from_device links ──────────────
            # Head FAT: from_device == fdt.name (set by create_fdt_wing_cascades).
            # Containment set: only FATs owned by THIS FDT and this wing may
            # appear in the chain.  Without this guard, a stale to_device link
            # left over from create_fat_cascade (road-level) or from an earlier
            # boundary-fix pass can send the walker into a neighbouring FDT and
            # emit cross-FDT B2B cables — the "star" bug where cables from
            # distant FATs converge onto one FAT in another FDT.
            wing_owned = set(id(f) for f in wing_fats_all)
            fdt_anchor = fdt.snapped_geometry or fdt.geometry
            head = next(
                (f for f in wing_fats_all if f.from_device == fdt.name),
                None,
            )
            if head is None:
                logger.log(
                    f"WARNING: {fdt.name} Wing {wing} — no head FAT found "
                    f"(from_device==fdt.name); rebuilding chain from FDT-anchor distance."
                )
                if fdt_anchor is not None:
                    wing_fats = sorted(
                        wing_fats_all,
                        key=lambda f: (
                            (f.snapped_geometry or f.geometry).x() - fdt_anchor.x()
                        ) ** 2 + (
                            (f.snapped_geometry or f.geometry).y() - fdt_anchor.y()
                        ) ** 2,
                    )
                else:
                    wing_fats = sorted(wing_fats_all, key=lambda f: f.fat_sequence or "")
            else:
                wing_fats = [head]
                while wing_fats[-1].to_device:
                    nxt = fat_by_name.get(wing_fats[-1].to_device)
                    # Guard: the next FAT must be owned by THIS FDT's wing.
                    # Prevents the chain walker from crossing FDT boundaries via
                    # a stale to_device pointer and creating star-topology cables.
                    if nxt is None or nxt in wing_fats or id(nxt) not in wing_owned:
                        if nxt is not None and id(nxt) not in wing_owned:
                            if getattr(nxt, 'parent_fdt', None) == fdt.name:
                                # Same FDT, but a different PON's wing — a stale
                                # link that survived a re-partition (spec §A.8).
                                # Distinct failure mode from CROSS_FDT_LINK:
                                # Single-PON structurally cannot have this, since
                                # there's only one PON.
                                logger.log(
                                    f"WARNING [CROSS_PON_LINK]: {fdt.name} Wing {wing} "
                                    f"chain hit stale same-FDT link "
                                    f"{wing_fats[-1].name}.to_device={nxt.name} "
                                    f"(wing {getattr(nxt, 'wing', '?')}, PON "
                                    f"{WING_TO_PON.get(getattr(nxt, 'wing', ''), '?')}); "
                                    f"truncating chain."
                                )
                            else:
                                logger.log(
                                    f"WARNING [CROSS_FDT_LINK]: {fdt.name} Wing {wing} "
                                    f"chain hit stale link {wing_fats[-1].name}.to_device="
                                    f"{nxt.name} (owned by {getattr(nxt, 'parent_fdt', '?')}); "
                                    f"truncating chain."
                                )
                        break
                    wing_fats.append(nxt)

                # If the chain didn't cover every wing FAT (broken link mid-chain),
                # append the remaining owned FATs in FDT-anchor distance order so
                # no FAT is silently dropped from cabling.
                if len(wing_fats) < len(wing_fats_all) and fdt_anchor is not None:
                    remaining = [f for f in wing_fats_all if f not in wing_fats]
                    remaining.sort(
                        key=lambda f: (
                            (f.snapped_geometry or f.geometry).x() - fdt_anchor.x()
                        ) ** 2 + (
                            (f.snapped_geometry or f.geometry).y() - fdt_anchor.y()
                        ) ** 2,
                    )
                    logger.log(
                        f"WARNING [CHAIN_INCOMPLETE]: {fdt.name} Wing {wing} chain "
                        f"covered {len(wing_fats)}/{len(wing_fats_all)} FATs; "
                        f"appending {len(remaining)} orphaned FAT(s) by distance."
                    )
                    wing_fats.extend(remaining)

            if not wing_fats:
                continue

            # The earlier cascade and repair stages optimize against road
            # topology. In pole-to-pole mode, the final support graph can have
            # different hop costs, so re-evaluate this small wing chain using
            # the exact graph that will emit the cables. This preserves the
            # strict configured limits and only changes order when it improves
            # the worst normalized hop.
            if (cable_router.b2b_routing_mode == "pole_to_pole"
                    and 1 < len(wing_fats) <= 6):
                original_order = list(wing_fats)
                length_cache: Dict[Tuple[int, int], Optional[float]] = {}
                fdt_endpoint = fdt_point
                fdt_support = fdt.snapped_geometry or fdt.geometry

                def _support_hop_length(left_index: int, right_index: int) -> Optional[float]:
                    key = (left_index, right_index)
                    if key in length_cache:
                        return length_cache[key]
                    left_fat = original_order[left_index - 1] if left_index else None
                    right_fat = original_order[right_index - 1]
                    left_point = _b2b_endpoint(left_fat) if left_fat else fdt_endpoint
                    left_anchor = (left_fat.snapped_geometry or left_fat.geometry) if left_fat else fdt_support
                    left_name = left_fat.structure_name if left_fat else fdt.structure_name
                    geometry, length = cable_router.find_support_path_points(
                        left_point,
                        _b2b_endpoint(right_fat),
                        left_anchor,
                        right_fat.snapped_geometry or right_fat.geometry,
                        left_name,
                        right_fat.structure_name,
                    )
                    result = (
                        float(length)
                        if geometry is not None and not geometry.isEmpty()
                        else None
                    )
                    length_cache[key] = result
                    return result

                def _order_score(order_indices: Tuple[int, ...]):
                    ratios: List[float] = []
                    previous_index = 0  # 0 denotes the FDT; FAT indexes start at 1.
                    for hop_index, fat_index in enumerate(order_indices):
                        current_index = fat_index + 1
                        length = _support_hop_length(previous_index, current_index)
                        if length is None:
                            return (float("inf"), float("inf"))
                        limit = b2b_hop_limit(hop_index)
                        ratios.append(length / limit if limit > 0 else float("inf"))
                        previous_index = current_index
                    return (max(ratios, default=0.0), sum(ratios))

                base_indices = tuple(range(len(original_order)))
                base_score = _order_score(base_indices)
                best_indices = base_indices
                best_score = base_score
                for candidate_indices in permutations(base_indices):
                    candidate_score = _order_score(candidate_indices)
                    if candidate_score < best_score:
                        best_indices, best_score = candidate_indices, candidate_score

                if best_indices != base_indices and best_score[0] + 1e-9 < base_score[0]:
                    wing_fats = [original_order[index] for index in best_indices]
                    for index, fat in enumerate(wing_fats):
                        fat.from_device = fdt.name if index == 0 else wing_fats[index - 1].name
                        fat.to_device = wing_fats[index + 1].name if index + 1 < len(wing_fats) else None
                    logger.log(
                        f"[POLE-CHAIN-ORDER] {fdt.name} Wing {wing}: "
                        f"{' → '.join(fat.name for fat in wing_fats)}; "
                        f"worst hop ratio {base_score[0]:.3f} → {best_score[0]:.3f}"
                    )

            # ── Emit one CableSegment per hop ─────────────────────────────────
            # Hops: FDT→FAT[0], FAT[0]→FAT[1], …, FAT[n-2]→FAT[n-1]
            # wing_name groups every hop cable on this wing under one shared
            # identifier — e.g. "FDT-01A" — so all box-to-box cables belonging
            # to FDT-01's Wing A carry the same FDT+wing prefix in their name
            # and can be filtered/grouped together in the attribute table.
            wing_name  = f"{fdt.name}{wing}"
            prev_point = fdt_point
            prev_support_anchor = fdt.snapped_geometry or fdt.geometry
            prev_support_name = fdt.structure_name
            prev_name  = fdt.name
            wing_ok    = True

            for i, fat in enumerate(wing_fats):
                # Use the FAT's real physical position (frontage-offset from
                # the road centreline) as the cable endpoint — NOT the
                # on-road snapped_geometry. The FAT dot is drawn at
                # offset_geometry (see FAT layer population), so a cable that
                # terminates at snapped_geometry instead visually stops short
                # of / cuts past the box rather than touching it.
                # Use _b2b_endpoint() for consistent device anchor resolution
                end_point = _b2b_endpoint(fat)

                # Zone containment check (non-fatal; logged only)
                if fdt.zone_geometry and not fdt.zone_geometry.contains(
                        QgsGeometry.fromPointXY(end_point)):
                    logger.log(
                        f"WARNING [FAT_OUTSIDE_ZONE]: {fat.name} is outside FDT zone"
                    )

                non_master_before = (
                    cable_router.route_stats['temp_graph']
                    + cable_router.route_stats['fallback']
                )
                # Pass road IDs to prevent cross-road vertex snapping
                # For first hop (FDT→FAT), use FDT's road. For subsequent hops, use previous FAT's road.
                start_road_id = fdt_road_id if i == 0 else wing_fats[i-1].road_id
                end_road_id = fat.road_id
                if cable_router.b2b_routing_mode == "pole_to_pole":
                    end_support_anchor = fat.snapped_geometry or fat.geometry
                    geom, hop_len = cable_router.find_support_path_points(
                        prev_point,
                        end_point,
                        prev_support_anchor,
                        end_support_anchor,
                        prev_support_name,
                        fat.structure_name,
                        start_road_id=start_road_id,
                        end_road_id=end_road_id,
                    )
                else:
                    geom, hop_len = cable_router.find_shortest_path_points(
                        prev_point, end_point,
                        start_road_id=start_road_id,
                        end_road_id=end_road_id
                    )
                non_master_after = (
                    cable_router.route_stats['temp_graph']
                    + cable_router.route_stats['fallback']
                )
                if non_master_after > non_master_before:
                    cable_router.route_anchor_misses.append(
                        f"{prev_name} -> {fat.name}"
                    )

                if geom is None or geom.isEmpty():
                    _support_detail = ""
                    if (cable_router.b2b_routing_mode == "pole_to_pole"
                            and cable_router.last_support_route_diagnostic):
                        _support_detail = (
                            " Support diagnosis: "
                            f"{cable_router.last_support_route_diagnostic}."
                        )
                    _failure_reason = ""
                    if cable_router.b2b_routing_mode == "pole_to_pole":
                        _failure_reason = str(
                            cable_router.last_support_route_diagnostic.get("reason", "")
                        )
                    else:
                        for _point, _road_id in (
                            (prev_point, start_road_id),
                            (end_point, end_road_id),
                        ):
                            _anchor_error = cable_router._device_road_anchor_error(
                                _point, _road_id,
                            )
                            if _anchor_error:
                                _failure_reason = _anchor_error
                                break
                    if not _failure_reason:
                        _failure_reason = (
                            "no connected path in the "
                            f"{cable_router.b2b_routing_mode.replace('_', ' ')} graph"
                        )
                    cable_router.route_failures.append(
                        f"{prev_name} -> {fat.name} ({_failure_reason})"
                    )
                    logger.log(
                        f"WARNING [ROUTING_FAILURE]: {prev_name}→{fat.name} "
                        f"no {cable_router.b2b_routing_mode} path: {prev_name}"
                        f"(road {fat.road_id if i > 0 else fdt_road_id})"
                        f" → {fat.name}(road {fat.road_id})."
                        f"{_support_detail} Wing {wing} cable chain truncated "
                        f"at hop {i + 1}."
                    )
                    wing_ok = False
                    break

                # Snap first/last vertices to exact device anchor positions
                try:
                    geom = _enforce_exact_cable_endpoints(
                        geom,
                        QgsGeometry.fromPointXY(prev_point),
                        QgsGeometry.fromPointXY(end_point),
                    )
                except ValidationError:
                    pass  # keep Dijkstra geometry if snapping fails

                if cable_router.b2b_routing_mode == "pole_to_pole":
                    _path_points = geom.asPolyline()
                    hop_len = sum(
                        cable_router.dist_calc.distance_points(left, right)
                        for left, right in zip(_path_points, _path_points[1:])
                    )
                else:
                    hop_len = geom.length()

                # [Fix 4] Same limit resolver as the repair passes and the
                # hard gate, so this warning can never describe a different
                # rule to the one that will actually reject the design.
                _hop_limit = b2b_hop_limit(i)
                if hop_len > _hop_limit + rc.DROP_LENGTH_TOLERANCE:
                    logger.log(
                        f"WARNING [CABLE_LENGTH_EXCEEDED]: {prev_name}→{fat.name} "
                        f"hop {i + 1} length {hop_len:.2f}m exceeds {_hop_limit:.0f}m"
                    )

                cable_name = f"B2B_{wing_name}_{i + 1:02d}_{prev_name}_{fat.name}"
                cable = CableSegment(
                    name=cable_name,
                    start_device=prev_name,
                    end_device=fat.name,
                    geometry=geom,
                    length=hop_len,
                    fdt_id=fdt.name,
                    core_info={
                        "architecture": "PCC",
                        "b2b_routing_mode": cable_router.b2b_routing_mode,
                        "wing":         wing,
                        "wing_name":    wing_name,  # e.g. "FDT-01A" — shared by every cable on this wing
                        "hop_seq":      i + 1,      # 1 = FDT→first FAT
                        "fat_count":    len(wing_fats),
                        "splitter_type": fat.splitter_type,
                        "cable_type":   "box_to_box",
                        "core_pair":    (i * 2 + 1, i * 2 + 2),
                        # Dual-PON traceability (spec §7/§16) — derived, never
                        # a second stored source of truth (pon_index is always
                        # WING_TO_PON[fat.wing]).
                        "pon_index":    wing_pon,
                        "splitter_id":  f"{fdt.name}-SP{wing_pon}",
                        "splitter_port": 1 if wing in ("A", "C") else 2,
                    },
                    # Each discrete cable has exactly one splice point: its end device.
                    tap_points=[{
                        "fat_name":       fat.name,
                        "tap_position_m": round(hop_len, 2),
                        "wing":           wing,
                        "wing_name":      wing_name,
                        "seq":            i + 1,
                        "splitter_type":  fat.splitter_type,
                        "core_pair":      (i * 2 + 1, i * 2 + 2),
                    }],
                )
                cables.append(cable)

                logger.log(
                    f"  {fdt.name} Wing {wing} hop {i + 1}: "
                    f"{prev_name} → {fat.name} ({hop_len:.1f}m)"
                )

                prev_point = end_point
                prev_support_anchor = fat.snapped_geometry or fat.geometry
                prev_support_name = fat.structure_name
                prev_name  = fat.name

            if wing_ok:
                total_wing_m = sum(
                    c.length for c in cables
                    if c.fdt_id == fdt.name
                    and c.core_info.get("wing") == wing
                )
                logger.log(
                    f"{fdt.name} Wing {wing}: {len(wing_fats)} hops, "
                    f"{total_wing_m:.1f}m total"
                )

    logger.end_module("FDT to FAT Routing")
    logger.log(f"Routed {len(cables)} PCC box-to-box hop cables")
    return cables


def route_fat_to_homepasses(fats: List[FAT],
                           homepasses: List[Homepass],
                           dist_calc: DistanceCalculator,
                           logger: PerformanceLogger) -> List[CableSegment]:
    """Route cables from FATs to homepasses.

    When a point is split across FATs (borrowed), create multiple drop cables
    per (FAT, point) - one cable per customer allocated.
    """
    logger.start_module("FAT to Homepass Routing")

    cables = []

    # Build fid -> Homepass lookup
    hp_by_fid = {h.fid: h for h in homepasses}

    for fat in fats:
        start_point = _b2b_endpoint(fat)

        # Use customer_allocations when available (supports split points)
        if fat.customer_allocations:
            fid_count_pairs = list(fat.customer_allocations.items())
        else:
            fid_count_pairs = [(hp_id, 1) for hp_id in fat.customers]

        for hp_id, count in fid_count_pairs:
            hp = hp_by_fid.get(hp_id)
            if not hp:
                continue

            # This was a hard invariant before tail-borrow existed (every
            # cluster only ever contained homepasses from the FAT's own
            # road, by construction). Tail-borrow (generate_fats Pass 2)
            # legitimately breaks it: a borrowed customer's master Homepass
            # record still shows its ORIGINAL road, while the FAT serving it
            # now belongs to the neighbouring road it was merged into. A
            # mismatch here is expected for those customers now, so it's a
            # visibility warning, not a hard failure — the geometry/routing
            # below is unaffected either way (it only ever used hp.geometry,
            # never hp.road_id, to draw the cable).
            if hp.road_id != fat.road_id:
                logger.log(
                    f"WARNING [CROSS_ROAD_DROP]: FAT {fat.name} (road "
                    f"{fat.road_id}) serves customer {hp.fid} (road "
                    f"{hp.road_id}) — expected for a tail-borrowed customer; "
                    f"otherwise indicates a genuine FAT/road mismatch worth "
                    f"reviewing."
                )

            end_point = hp.geometry
            geom = QgsGeometry.fromPolylineXY([start_point, end_point])
            length = dist_calc.distance_points(start_point, end_point)

            if length > (rc.MAX_BOX_TO_CUSTOMER_DISTANCE + rc.DROP_LENGTH_TOLERANCE):
                raise ValidationError(
                    f"Drop cable length exceeded: {fat.name} -> Customer_{hp_id} "
                    f"is {length:.2f}m (max {rc.MAX_BOX_TO_CUSTOMER_DISTANCE + rc.DROP_LENGTH_TOLERANCE:.2f}m)"
                )

            # Create one cable per customer (reflects split allocation)
            for i in range(count):
                cable = CableSegment(
                    name=f"DROP_{fat.name}_C{hp_id}_{i+1}" if count > 1 else f"DROP_{fat.name}_C{hp_id}",
                    start_device=fat.name,
                    end_device=f"Customer_{hp_id}",
                    geometry=geom,
                    length=length,
                    fdt_id=""
                )
                cables.append(cable)

    logger.end_module("FAT to Homepass Routing")
    logger.log(f"Routed {len(cables)} drop cables")

    return cables


def route_legacy_fdt_to_fats_by_road(
    fdts: List['FDT'],
    cable_router: 'CableRouter',
    logger: 'PerformanceLogger',
) -> List['CableSegment']:
    """Legacy road-grouped routing: one 8-core cable per road branch per FDT.

    For each FDT:
      1. Group FATs by road_id.
      2. Sort each road group by cascade_order (closest to FDT first).
      3. Route ONE cable FDT → last FAT on the road (farthest point).
         The cable geometry passes through intermediate FAT positions.
      4. Record each FAT's tap position and core pair on the cable.
      5. Warn if an FDT serves more than 3 roads (soft constraint).
      6. Core assignment: 8-core cable per road; 2 cores tapped per FAT.
    """
    logger.start_module("Legacy FDT-to-FAT Road-Grouped Routing")
    cables: List[CableSegment] = []

    for fdt in fdts:
        if not fdt.fats:
            continue

        fdt_pt = fdt.snapped_geometry or fdt.geometry

        # Group FATs by road
        by_road: Dict[int, List] = defaultdict(list)
        for fat in fdt.fats:
            by_road[fat.road_id].append(fat)

        road_ids = list(by_road.keys())
        if len(road_ids) > 3:
            logger.log(
                f"WARNING: {fdt.name} serves {len(road_ids)} roads; expected ≤ 3. "
                f"Continuing — extra cables will be generated."
            )

        for road_id, road_fats in by_road.items():
            # Sort by cascade_order (physical proximity to FDT on this road)
            road_fats_sorted = sorted(
                road_fats,
                key=lambda f: (
                    int(f.fat_sequence) if f.fat_sequence and f.fat_sequence.isdigit() else 999,
                    f.name,
                )
            )

            # May need a second 8-core cable if > 4 FATs on one road
            for chunk_start in range(0, len(road_fats_sorted), MAX_FAT_PER_WING):
                chunk = road_fats_sorted[chunk_start:chunk_start + MAX_FAT_PER_WING]
                last_fat = chunk[-1]
                # Real physical box position (frontage-offset), not the
                # on-road snap point — see route_fdt_to_fats for the same fix.
                last_pt  = _b2b_endpoint(last_fat)

                # Route cable FDT → last FAT on this road
                geom, length = cable_router.find_shortest_path_points(fdt_pt, last_pt)

                if not geom or geom.isEmpty():
                    logger.log(
                        f"WARNING [ROUTING_FAILURE]: {fdt.name}→{last_fat.name} "
                        f"no topology path for legacy road cable. Cable NOT created."
                    )
                    continue

                try:
                    geom = _enforce_exact_cable_endpoints(
                        geom,
                        QgsGeometry.fromPointXY(fdt_pt),
                        QgsGeometry.fromPointXY(last_pt),
                    )
                except Exception:
                    pass

                length = geom.length()
                chunk_idx = chunk_start // MAX_FAT_PER_WING

                # Build tap records along this cable
                tap_points = []
                for tap_i, fat in enumerate(chunk):
                    core_pair = (tap_i * 2 + 1, tap_i * 2 + 2)
                    fat_pt = _b2b_endpoint(fat)
                    nearest = geom.nearestPoint(QgsGeometry.fromPointXY(fat_pt))
                    tap_m = geom.lineLocatePoint(nearest)
                    tap_points.append({
                        "fat_name":       fat.name,
                        "tap_position_m": round(tap_m, 2),
                        "core_pair":      core_pair,
                    })

                tap_seq = ",".join(str(i + 1) for i in range(len(chunk)))
                cable_name = (
                    f"LEG_{fdt.name}_R{road_id}"
                    + (f"_C{chunk_idx + 1}" if chunk_idx > 0 else "")
                )

                cables.append(CableSegment(
                    name=cable_name,
                    start_device=fdt.name,
                    end_device=last_fat.name,
                    geometry=geom,
                    length=length,
                    fdt_id=fdt.name,
                    core_info={
                        "architecture": "LEGACY",
                        "wing":         "",         # Legacy has no wing concept
                        "wing_name":    fdt.name,   # falls back to FDT id alone
                        "road_id":      road_id,
                        "fat_count":    len(chunk),
                        "tap_sequence": tap_seq,
                        "cable_type":   "8core_road_run",
                    },
                    tap_points=tap_points,
                ))

    logger.end_module("Legacy FDT-to-FAT Road-Grouped Routing")
    logger.log(f"Routed {len(cables)} legacy road-grouped FDT-FAT cables")
    return cables
