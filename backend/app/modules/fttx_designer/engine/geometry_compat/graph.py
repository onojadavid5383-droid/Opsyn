"""networkx-backed adapter for QgsGraph / QgsGraphBuilder / QgsGraphAnalyzer
— the graph *data structure and shortest-path algorithm* half of the QGIS
network API, matching ``graph.vertex(i).point()``, ``graph.edge(id)
.fromVertex()``, ``graph.vertexCount()``/``.edgeCount()``,
``graph.findVertex(point)``, and ``QgsGraphAnalyzer.dijkstra(graph, source,
criterion)`` (returning the same ``(tree, cost)`` arrays QGIS does: `tree[v]`
is the incoming edge id on the shortest path to `v`, or -1).

Deliberately NOT shimmed here: ``QgsVectorLayerDirector`` /
``QgsNetworkDistanceStrategy``. Those build a QgsGraph FROM a QgsVectorLayer
by noding line features and splitting edges at query points — but the
integration plan's §4.2 API-surface table explicitly decides not to shim
QgsVectorLayer at all ("most internal uses are just iterate features... more
naturally a `for row in gdf.itertuples()`"). Reproducing
``director.makeGraph(builder, points)`` transparently would mean re-deriving
that exact noding/point-insertion behavior anyway, just hidden behind a
fake QGIS-shaped API instead of an honest rewrite. Per the plan, the real
port work happens in ``topology.py``/``cable_routing.py`` (Phase 2): those
modules build a ``QgsGraph`` directly from a GeoDataFrame of road geometries
by calling ``QgsGraph._add_vertex()``/``._add_edge()`` below, with the
noding/tolerance-merge logic written explicitly in Python rather than
hidden inside a director shim.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .geometry import QgsPointXY


class QgsGraphVertex:
    """Drop-in replacement for qgis.core.QgsGraphVertex (read-only wrapper
    around the vertex's point, matching the only method the source script
    calls: ``.point()``)."""

    __slots__ = ("_point",)

    def __init__(self, point: QgsPointXY):
        self._point = point

    def point(self) -> QgsPointXY:
        return self._point


class QgsGraphEdge:
    """Drop-in replacement for qgis.core.QgsGraphEdge (matching
    ``.fromVertex()``/``.toVertex()``/``.cost()``)."""

    __slots__ = ("_from_vertex", "_to_vertex", "_cost")

    def __init__(self, from_vertex: int, to_vertex: int, cost: float):
        self._from_vertex = from_vertex
        self._to_vertex = to_vertex
        self._cost = cost

    def fromVertex(self) -> int:
        return self._from_vertex

    def toVertex(self) -> int:
        return self._to_vertex

    def cost(self, _strategy_index: int = 0) -> float:
        return self._cost


class QgsGraph:
    """Drop-in replacement for the subset of qgis.core.QgsGraph used for
    read access (vertexCount/edgeCount/vertex/edge/findVertex). Vertices are
    deduplicated by exact (rounded) coordinate — the caller is responsible
    for any topology-tolerance snapping/noding before calling
    ``_add_vertex``/``_add_edge``, matching how QgsVectorLayerDirector's own
    ``topologyTolerance`` argument only merges vertices, never edges, at
    build time."""

    def __init__(self, coordinate_precision: int = 6):
        self._vertices: List[QgsGraphVertex] = []
        self._edges: List[QgsGraphEdge] = []
        self._vertex_lookup: Dict[Tuple[float, float], int] = {}
        self._precision = coordinate_precision

    def vertexCount(self) -> int:
        return len(self._vertices)

    def edgeCount(self) -> int:
        return len(self._edges)

    def vertex(self, i: int) -> QgsGraphVertex:
        return self._vertices[i]

    def edge(self, i: int) -> QgsGraphEdge:
        return self._edges[i]

    def findVertex(self, point: QgsPointXY) -> int:
        key = (round(point.x(), self._precision), round(point.y(), self._precision))
        return self._vertex_lookup.get(key, -1)

    def _add_vertex(self, point: QgsPointXY) -> int:
        """Not part of the QGIS API — the Phase 2 network-construction
        rewrite's insertion point (see module docstring). Returns the
        existing vertex id if a vertex already sits at this coordinate."""
        key = (round(point.x(), self._precision), round(point.y(), self._precision))
        existing = self._vertex_lookup.get(key)
        if existing is not None:
            return existing
        idx = len(self._vertices)
        self._vertices.append(QgsGraphVertex(point))
        self._vertex_lookup[key] = idx
        return idx

    def _add_edge(self, from_vertex: int, to_vertex: int, cost: float) -> int:
        """Not part of the QGIS API — see ``_add_vertex``. Adds one directed
        edge; callers wanting QGIS's DirectionBoth behavior add both
        directions explicitly (matching how the source script's
        QgsVectorLayerDirector was always constructed with
        ``DirectionBoth``)."""
        idx = len(self._edges)
        self._edges.append(QgsGraphEdge(from_vertex, to_vertex, cost))
        return idx


class QgsGraphBuilder:
    """Drop-in replacement for the subset of qgis.core.QgsGraphBuilder used
    (construction + ``.graph()``). The ``topologyTolerance`` argument is
    accepted for signature compatibility but not applied here — coordinate
    merging happens in ``QgsGraph._add_vertex``'s rounding, driven by
    ``coordinate_precision`` instead; callers needing a specific tolerance
    should round input coordinates to that tolerance before calling
    ``_add_vertex``."""

    def __init__(
        self,
        crs: object = None,
        ctf: bool = True,
        topologyTolerance: float = 0.0,
    ):
        self._topology_tolerance = topologyTolerance
        self._graph = QgsGraph()

    def graph(self) -> QgsGraph:
        return self._graph


class QgsGraphAnalyzer:
    """Drop-in replacement for the subset of qgis.core.QgsGraphAnalyzer used
    (``dijkstra`` single-source shortest path)."""

    @staticmethod
    def dijkstra(
        graph: QgsGraph, start_vertex_idx: int, criterion_index: int = 0
    ) -> Tuple[List[int], List[float]]:
        """Matches QGIS's return shape: ``tree[v]`` is the id of the
        incoming edge on the shortest path from `start_vertex_idx` to `v`
        (-1 if unreachable or `v` is the source), ``cost[v]`` is the total
        path cost (infinite/unreachable left as the caller's own sentinel —
        QGIS uses the C++ double max; this uses ``float('inf')``)."""
        import heapq

        n = graph.vertexCount()
        tree = [-1] * n
        cost = [float("inf")] * n
        if not (0 <= start_vertex_idx < n):
            return tree, cost
        cost[start_vertex_idx] = 0.0

        # Adjacency: vertex -> list of (edge_id, to_vertex, edge_cost)
        adjacency: Dict[int, List[Tuple[int, int, float]]] = {}
        for eid in range(graph.edgeCount()):
            e = graph.edge(eid)
            adjacency.setdefault(e.fromVertex(), []).append(
                (eid, e.toVertex(), e.cost(criterion_index))
            )

        visited = [False] * n
        heap: List[Tuple[float, int]] = [(0.0, start_vertex_idx)]
        while heap:
            d, u = heapq.heappop(heap)
            if visited[u]:
                continue
            visited[u] = True
            for eid, v, w in adjacency.get(u, []):
                nd = d + w
                if nd < cost[v]:
                    cost[v] = nd
                    tree[v] = eid
                    heapq.heappush(heap, (nd, v))

        return tree, cost
