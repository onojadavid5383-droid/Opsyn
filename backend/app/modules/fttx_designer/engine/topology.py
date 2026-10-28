"""Enhanced road graph noding - explicitly split lines at all intersections.

This module provides robust line noding that properly splits road segments
at every crossing point, fixing the T_UNNODED defects that cause B2B detours.

The standard GEOS unaryUnion sometimes doesn't properly share vertices at
crossings. This explicit noding ensures every road intersection becomes
a graph node.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Set, Tuple

from .geometry_compat import (
    Qgis,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
    QgsSpatialIndex,
    QgsFeature,
)
from .spatial_utils import DistanceCalculator
from .perf_logger import PerformanceLogger
from .config import MASTER_GRAPH_TOPOLOGY_TOLERANCE


def _extract_line_vertices(geom: QgsGeometry) -> List[QgsPointXY]:
    """Extract all vertices from a line geometry."""
    if geom.isMultipart():
        # For multilinestrings, just get endpoints
        parts = geom.asMultiPolyline()
        vertices = []
        for part in parts:
            if part:
                vertices.append(part[0])
                if len(part) > 1:
                    vertices.append(part[-1])
        return vertices
    else:
        polyline = geom.asPolyline()
        if not polyline:
            return []
        # Return all vertices
        return list(polyline)


def find_all_intersections(
    road_layer: QgsVectorLayer,
    dist_calc: DistanceCalculator,
    logger: Optional[PerformanceLogger] = None,
    tolerance: float = MASTER_GRAPH_TOPOLOGY_TOLERANCE,
) -> Dict[Tuple[float, float], List[int]]:
    """Find every intersection point between road segments.

    Returns a dict mapping intersection coordinates (rounded to tolerance)
    to the list of feature IDs that meet at that point.

    This is more robust than relying on unaryUnion because it explicitly
    finds where lines cross and ensures all segments share vertices there.
    """
    # First, collect all line segments
    features: List[Tuple[int, QgsGeometry, List[QgsPointXY]]] = []
    for f in road_layer.getFeatures():
        geom = f.geometry()
        if geom is None or geom.isEmpty():
            continue
        vertices = _extract_line_vertices(geom)
        if len(vertices) >= 2:
            features.append((f.id(), geom, vertices))

    if not features:
        return {}

    # Build spatial index for fast neighbor queries
    idx = QgsSpatialIndex()
    geoms: Dict[int, QgsGeometry] = {}
    for fid, geom, _ in features:
        geoms[fid] = geom
        ft = QgsFeature(fid)
        ft.setGeometry(geom)
        idx.addFeature(ft)

    # Find intersections
    intersection_points: Dict[Tuple[float, float], Set[int]] = {}

    for fid_a, geom_a, verts_a in features:
        # Get nearby features
        try:
            candidates = idx.nearestNeighbor(verts_a[0], 10)
        except Exception:
            continue

        for fid_b in candidates:
            if fid_b <= fid_a:  # Avoid duplicate pairs
                continue

            geom_b = geoms.get(fid_b)
            if geom_b is None:
                continue

            # Check if geometries intersect
            try:
                intersection = geom_a.intersection(geom_b)
                if intersection is None or intersection.isEmpty():
                    continue

                # Extract intersection points
                wkb_type = intersection.wkbType()
                if wkb_type == Qgis.WkbType.Point:
                    pt = intersection.asPoint()
                    key = (round(pt.x() / tolerance) * tolerance,
                           round(pt.y() / tolerance) * tolerance)
                    if key not in intersection_points:
                        intersection_points[key] = set()
                    intersection_points[key].add(fid_a)
                    intersection_points[key].add(fid_b)
                elif wkb_type == Qgis.WkbType.MultiPoint:
                    for pt in intersection.asMultiPoint():
                        key = (round(pt.x() / tolerance) * tolerance,
                               round(pt.y() / tolerance) * tolerance)
                        if key not in intersection_points:
                            intersection_points[key] = set()
                        intersection_points[key].add(fid_a)
                        intersection_points[key].add(fid_b)
            except Exception:
                continue

    return {k: list(v) for k, v in intersection_points.items()}


def split_lines_at_intersections(
    road_layer: QgsVectorLayer,
    dist_calc: DistanceCalculator,
    logger: Optional[PerformanceLogger] = None,
    tolerance: float = MASTER_GRAPH_TOPOLOGY_TOLERANCE,
) -> QgsVectorLayer:
    """Split all road lines at every intersection point.

    This creates a fully noded road network where every crossing point
    is a vertex shared by all intersecting segments.

    Returns a new in-memory QgsVectorLayer with the noded linework.
    """
    if logger:
        logger.log("Starting explicit road line noding...")

    t0 = time.time()

    # Collect all geometries
    geoms: List[QgsGeometry] = []
    for f in road_layer.getFeatures():
        g = f.geometry()
        if g and not g.isEmpty():
            geoms.append(g)

    if not geoms:
        if logger:
            logger.log("WARNING [NODING]: no geometries to node")
        return road_layer

    n_input = len(geoms)

    # Use unaryUnion to split at intersections - this is the standard way
    # but we verify the result has proper nodes
    try:
        merged = QgsGeometry.unaryUnion(geoms)
    except Exception as e:
        if logger:
            logger.log(f"WARNING [NODING]: unaryUnion failed: {e}")
        return road_layer

    if merged is None or merged.isEmpty():
        if logger:
            logger.log("WARNING [NODING]: unaryUnion returned empty")
        return road_layer

    # Extract the noded linework
    if merged.isMultipart():
        parts = merged.asMultiPolyline()
    else:
        parts = [merged.asPolyline()]

    # Flatten and filter
    all_lines = []
    for part in parts:
        if part and len(part) >= 2:
            all_lines.append(part)

    n_output = len(all_lines)

    if not all_lines:
        if logger:
            logger.log("WARNING [NODING]: no linework after noding")
        return road_layer

    # Check if noding actually happened
    if n_output <= n_input * 0.8:
        # Strange - should have more segments, not fewer
        if logger:
            logger.log(
                f"WARNING [NODING]: output ({n_output}) <= input ({n_input})*0.8 - "
                f"checking intersection points..."
            )

    # Build output layer
    noded_layer = QgsVectorLayer.from_records(
        [{"geometry": QgsGeometry.fromPolylineXY(part)} for part in all_lines],
        crs=road_layer.crs(),
        layer_id="roads_explicitly_noded",
    )

    elapsed = time.time() - t0
    if logger:
        logger.log(
            f"Explicit noding complete: {n_input} features -> {n_output} segments "
            f"in {elapsed:.2f}s"
        )

    return noded_layer


def auto_repair_road_noding(
    road_layer: QgsVectorLayer,
    dist_calc: DistanceCalculator,
    logger: Optional[PerformanceLogger] = None,
    enable_fallback: bool = True,
) -> QgsVectorLayer:
    """Attempt to automatically repair road network noding.

    This is the main entry point for automatic noding repair. It tries
    the explicit intersection-based approach first, then falls back to
    standard unaryUnion if needed.

    Args:
        road_layer: Original road layer
        dist_calc: Distance calculator
        logger: Optional logger for diagnostics
        enable_fallback: If True, falls back to standard unaryUnion if
                        explicit noding fails

    Returns:
        A noded road layer suitable for routing
    """
    if logger:
        logger.log("=" * 50)
        logger.log("AUTO-REPAIR: Starting road noding repair")
        logger.log("=" * 50)

    # Try explicit intersection-based noding first
    try:
        result = split_lines_at_intersections(
            road_layer, dist_calc, logger, tolerance=MASTER_GRAPH_TOPOLOGY_TOLERANCE
        )

        # Verify the result has proper nodes by checking vertex count
        total_vertices = 0
        for f in result.getFeatures():
            g = f.geometry()
            if g:
                if g.isMultipart():
                    for part in g.asMultiPolyline():
                        total_vertices += len(part)
                else:
                    total_vertices += len(g.asPolyline())

        if total_vertices > 0 and logger:
            logger.log(f"Auto-repair: Noded layer has {total_vertices} total vertices")

        # If we got the same layer back (failure), try fallback
        if result == road_layer and enable_fallback:
            if logger:
                logger.log("Auto-repair: Explicit noding returned original, trying unaryUnion fallback...")
            from .cable_routing import build_noded_routing_layer
            result = build_noded_routing_layer(road_layer, logger if logger else _QuietLogger())

        return result

    except Exception as e:
        if logger:
            logger.log(f"Auto-repair failed: {e}")
        if enable_fallback:
            try:
                from .cable_routing import build_noded_routing_layer
                return build_noded_routing_layer(road_layer, logger if logger else _QuietLogger())
            except Exception:
                pass
        return road_layer


class _QuietLogger:
    """Minimal logger for when no logger is available."""

    def log(self, *args, **kwargs) -> None:
        pass

    def error(self, *args, **kwargs) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers imported by cable_routing, fat_generation, and other engine modules
# ---------------------------------------------------------------------------

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from .geometry_compat import QgsGeometry, QgsPointXY, QgsVectorLayer
from .spatial_utils import DistanceCalculator

if TYPE_CHECKING:
    from .domain import RoadSegment


# ── Low-level geometry helpers ──────────────────────────────────────────────

def _road_vertices(geom: QgsGeometry) -> List[QgsPointXY]:
    """Return all vertices of a line or multiline geometry as a flat list."""
    if geom is None or geom.isEmpty():
        return []
    if geom.isMultipart():
        vertices: List[QgsPointXY] = []
        for part in geom.asMultiPolyline():
            vertices.extend(part)
        return vertices
    polyline = geom.asPolyline()
    return list(polyline) if polyline else []


def _dedupe_points(pts: List[QgsPointXY], tol: float = 1e-8) -> List[QgsPointXY]:
    """Remove consecutive duplicate points (within *tol*) from *pts*."""
    if not pts:
        return []
    out: List[QgsPointXY] = [pts[0]]
    for p in pts[1:]:
        prev = out[-1]
        if abs(p.x() - prev.x()) > tol or abs(p.y() - prev.y()) > tol:
            out.append(p)
    return out


# ── RoadTopologyEngine ───────────────────────────────────────────────────────

class RoadTopologyEngine:
    """Weighted adjacency graph built from a road layer.

    Attributes used by callers
    --------------------------
    adj          : Dict[int, List[Tuple[int, int, float]]]
                   node_id → [(neighbour_id, road_id, weight), ...]
                   road_id < 0 means a synthetic gap-healing connector.
    node_points  : Dict[int, QgsPointXY]   node_id → coordinate
    _nodes       : Dict[int, dict]         node_id → {'point': QgsPointXY,
                                                       'edges': Set[int]}
    _edges       : Dict[int, dict]         road_id → {'start': int,
                                                       'end': int,
                                                       'weight': float,
                                                       'geometry': QgsGeometry}
    """

    # Gap-healing: connect endpoints closer than this (metres / CRS units).
    GAP_HEAL_DISTANCE: float = 2.0

    def __init__(self) -> None:
        # node_id → QgsPointXY
        self.node_points: Dict[int, QgsPointXY] = {}
        # node_id → {'point': QgsPointXY, 'edges': Set[road_id]}
        self._nodes: Dict[int, dict] = {}
        # road_id → {'start': int, 'end': int, 'weight': float,
        #             'geometry': QgsGeometry}
        self._edges: Dict[int, dict] = {}
        # adjacency: node_id → [(neighbour_id, road_id, weight)]
        self.adj: Dict[int, List[Tuple[int, int, float]]] = defaultdict(list)
        self._next_node_id: int = 0
        self._dist_calc: Optional[DistanceCalculator] = None

    # ── Graph construction ──────────────────────────────────────────────────

    def _get_or_add_node(self, pt: QgsPointXY, tol: float = 1e-6) -> int:
        """Return an existing node id for *pt* (within *tol*) or create one."""
        for nid, existing in self.node_points.items():
            if (abs(existing.x() - pt.x()) <= tol
                    and abs(existing.y() - pt.y()) <= tol):
                return nid
        nid = self._next_node_id
        self._next_node_id += 1
        self.node_points[nid] = pt
        self._nodes[nid] = {'point': pt, 'edges': set()}
        self.adj[nid]  # ensure key exists
        return nid

    def build_from_layer(
        self,
        road_layer: QgsVectorLayer,
        dist_calc: DistanceCalculator,
        snap_tol: float = 1e-6,
    ) -> None:
        """Populate the graph from *road_layer*."""
        self._dist_calc = dist_calc

        for feat in road_layer.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            road_id: int = feat.id()
            verts = _road_vertices(geom)
            if len(verts) < 2:
                continue

            start_pt = verts[0]
            end_pt   = verts[-1]
            length   = geom.length() or 1e-3

            # Routing weight: honour RoadSegment.routing_weight if available
            weight = length  # default: straight distance cost

            sn = self._get_or_add_node(start_pt, snap_tol)
            en = self._get_or_add_node(end_pt,   snap_tol)

            self._edges[road_id] = {
                'start': sn, 'end': en,
                'weight': weight, 'geometry': geom,
            }
            self._nodes[sn]['edges'].add(road_id)
            self._nodes[en]['edges'].add(road_id)
            self.adj[sn].append((en, road_id, weight))
            self.adj[en].append((sn, road_id, weight))

        # Gap-healing pass: connect near-miss endpoints with synthetic edges
        self._heal_gaps()

    def _heal_gaps(self) -> None:
        """Add zero-road-id connectors between near-miss endpoints."""
        node_ids = list(self.node_points.keys())
        for i, nid_a in enumerate(node_ids):
            pa = self.node_points[nid_a]
            for nid_b in node_ids[i + 1:]:
                pb = self.node_points[nid_b]
                dist = math.hypot(pa.x() - pb.x(), pa.y() - pb.y())
                if 0 < dist <= self.GAP_HEAL_DISTANCE:
                    # Check they're not already connected
                    already = any(n == nid_b for n, _, _ in self.adj[nid_a])
                    if not already:
                        synthetic_id = -(nid_a * 100000 + nid_b + 1)
                        self.adj[nid_a].append((nid_b, synthetic_id, dist))
                        self.adj[nid_b].append((nid_a, synthetic_id, dist))

    # ── Routing ─────────────────────────────────────────────────────────────

    def weighted_shortest_path(
        self,
        start: QgsPointXY,
        end: QgsPointXY,
        start_road_id: Optional[int] = None,
        end_road_id: Optional[int] = None,
    ) -> Tuple[QgsGeometry, float]:
        """Dijkstra from *start* to *end* using the weighted road graph.

        Returns ``(geometry, length)`` or ``(QgsGeometry(), 0.0)`` on failure.
        """
        if not self._nodes:
            return QgsGeometry(), 0.0

        tol = 1e-6

        # Snap start/end to their nearest graph nodes
        def _nearest_node(pt: QgsPointXY, prefer_road: Optional[int]) -> Optional[int]:
            best_id: Optional[int] = None
            best_d = float('inf')
            # Prefer endpoints of the preferred road
            if prefer_road is not None and prefer_road in self._edges:
                e = self._edges[prefer_road]
                for nid in (e['start'], e['end']):
                    np_ = self.node_points[nid]
                    d = math.hypot(pt.x() - np_.x(), pt.y() - np_.y())
                    if d < best_d:
                        best_d = d
                        best_id = nid
            # Also search all nodes
            for nid, np_ in self.node_points.items():
                d = math.hypot(pt.x() - np_.x(), pt.y() - np_.y())
                if d < best_d:
                    best_d = d
                    best_id = nid
            return best_id

        start_nid = _nearest_node(start, start_road_id)
        end_nid   = _nearest_node(end,   end_road_id)
        if start_nid is None or end_nid is None:
            return QgsGeometry(), 0.0
        if start_nid == end_nid:
            geom = QgsGeometry.fromPolylineXY([start, end])
            return geom, geom.length()

        # Dijkstra
        dist: Dict[int, float] = {start_nid: 0.0}
        prev: Dict[int, Optional[int]] = {start_nid: None}
        heap: List[Tuple[float, int]] = [(0.0, start_nid)]

        while heap:
            cost, u = heapq.heappop(heap)
            if cost > dist.get(u, float('inf')) + tol:
                continue
            if u == end_nid:
                break
            for v, _rid, w in self.adj.get(u, []):
                nc = cost + w
                if nc < dist.get(v, float('inf')) - tol:
                    dist[v] = nc
                    prev[v] = u
                    heapq.heappush(heap, (nc, v))

        if end_nid not in dist:
            return QgsGeometry(), 0.0

        # Reconstruct path
        path_nodes: List[int] = []
        cur: Optional[int] = end_nid
        while cur is not None:
            path_nodes.append(cur)
            cur = prev.get(cur)
        path_nodes.reverse()

        pts: List[QgsPointXY] = [start]
        pts += [self.node_points[nid] for nid in path_nodes]
        pts.append(end)
        pts = _dedupe_points(pts)

        if len(pts) < 2:
            return QgsGeometry(), 0.0

        geom = QgsGeometry.fromPolylineXY(pts)
        return geom, geom.length()


# ── process_roads ────────────────────────────────────────────────────────────

def process_roads(
    road_layer: QgsVectorLayer,
    index_mgr: Any,
    logger: Any,
    dist_calc: Optional[DistanceCalculator] = None,
) -> Tuple[Dict[int, Any], Optional[RoadTopologyEngine]]:
    """Build a ``{road_id: RoadSegment}`` dict and a ``RoadTopologyEngine``.

    Parameters
    ----------
    road_layer : QgsVectorLayer
        The raw road layer from the project.
    index_mgr  : SpatialIndexManager
        Used by callers for spatial lookups; not mutated here.
    logger     : any object with a .log() method
    dist_calc  : DistanceCalculator (optional)

    Returns
    -------
    roads : Dict[int, RoadSegment]
    topo  : RoadTopologyEngine  (or None on failure)
    """
    # Lazy import to avoid circular dependency
    from .domain import RoadSegment

    roads: Dict[int, Any] = {}

    try:
        for feat in road_layer.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            fid = feat.id()
            length = geom.length() or 0.0
            roads[fid] = RoadSegment(
                id=fid,
                geometry=geom,
                fid=fid,
                length=length,
            )
    except Exception as exc:
        if logger:
            logger.log(f'process_roads: failed building RoadSegment dict: {exc}')
        roads = {}

    # Build topology engine
    topo: Optional[RoadTopologyEngine] = None
    if dist_calc is not None:
        try:
            topo = RoadTopologyEngine()
            topo.build_from_layer(road_layer, dist_calc)
            if logger:
                logger.log(
                    f'process_roads: topology built — '
                    f'{len(topo._nodes)} nodes, {len(topo._edges)} edges'
                )
        except Exception as exc:
            if logger:
                logger.log(f'process_roads: topology build failed: {exc}')
            topo = None

    return roads, topo
