from app.modules.fttx_designer.engine.domain import PoleStructure, RoadSegment
from app.modules.fttx_designer.engine.geometry_compat import (
    QgsCoordinateReferenceSystem,
    QgsGeometry,
    QgsPointXY,
)
from app.modules.fttx_designer.engine.pole_routing import (
    build_pole_graph,
    route_between_supports,
)
from app.modules.fttx_designer.engine.spatial_utils import DistanceCalculator
from collections import defaultdict


def _pole(identifier, x, y=0.0, name=""):
    return PoleStructure(
        id=identifier,
        geometry=QgsPointXY(x, y),
        name=name,
    )


def _road(identifier, points):
    geometry = QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points])
    return RoadSegment(
        id=identifier, fid=identifier, geometry=geometry, length=geometry.length()
    )


def _dist_calc():
    return DistanceCalculator(QgsCoordinateReferenceSystem("EPSG:32631"))


def test_same_road_poles_have_a_geometry_backed_path():
    poles = [_pole(1, 10, name="P1"), _pole(2, 50, name="P2")]
    roads = {1: _road(1, [(0, 0), (100, 0)])}
    edge_paths = {}
    graph_poles, adjacency = build_pole_graph(
        poles, roads, _dist_calc(), edge_paths=edge_paths
    )
    diagnostic = {}

    route = route_between_supports(
        graph_poles, adjacency, _dist_calc(),
        QgsPointXY(10, 0), QgsPointXY(50, 0),
        QgsPointXY(10, 0), QgsPointXY(50, 0),
        "P1", "P2", edge_paths=edge_paths, diagnostic=diagnostic,
    )

    assert route is not None and not route.isEmpty()
    assert route.length() == 40.0
    assert diagnostic["start_component"] == diagnostic["end_component"]


def test_disconnected_pole_components_are_reported_without_fallback():
    poles = [_pole(1, 10, name="P1"), _pole(2, 210, name="P2")]
    roads = {
        1: _road(1, [(0, 0), (100, 0)]),
        2: _road(2, [(200, 0), (300, 0)]),
    }
    graph_poles, adjacency = build_pole_graph(poles, roads, _dist_calc())
    diagnostic = {}

    route = route_between_supports(
        graph_poles, adjacency, _dist_calc(),
        QgsPointXY(10, 0), QgsPointXY(210, 0),
        QgsPointXY(10, 0), QgsPointXY(210, 0),
        "P1", "P2", diagnostic=diagnostic,
    )

    assert route is None
    assert "disconnected" in diagnostic["reason"]
    assert diagnostic["start_component"] != diagnostic["end_component"]


def test_distant_named_support_anchor_is_distinguished_from_graph_cut():
    poles = [_pole(1, 10, name="P1"), _pole(2, 50, name="P2")]
    adjacency = {0: {1: 40.0}, 1: {0: 40.0}}
    edge_paths = {
        (0, 1): [QgsPointXY(10, 0), QgsPointXY(50, 0)],
        (1, 0): [QgsPointXY(50, 0), QgsPointXY(10, 0)],
    }
    diagnostic = {}

    route = route_between_supports(
        poles, adjacency, _dist_calc(),
        QgsPointXY(10, 0), QgsPointXY(50, 0),
        QgsPointXY(30, 0), QgsPointXY(50, 0),
        "P1", "P2", edge_paths=edge_paths, diagnostic=diagnostic,
    )

    assert route is None
    assert "start anchor is 20.00 m" in diagnostic["reason"]


def test_topology_t_junction_connects_nearby_poles_at_projected_intersection():
    class Topology:
        _nodes = {0: {"point": QgsPointXY(50, 0), "edges": {1, 2}}}
        adj = defaultdict(list)
        node_points = {0: QgsPointXY(50, 0)}

    poles = [_pole(1, 45), _pole(2, 50, -8)]
    roads = {
        1: _road(1, [(0, 0), (100, 0)]),
        2: _road(2, [(50, -100), (50, 0)]),
    }
    edge_paths = {}
    graph_poles, adjacency = build_pole_graph(
        poles, roads, _dist_calc(), topology=Topology(), edge_paths=edge_paths
    )
    diagnostic = {}

    route = route_between_supports(
        graph_poles, adjacency, _dist_calc(),
        QgsPointXY(45, 0), QgsPointXY(50, -8),
        QgsPointXY(45, 0), QgsPointXY(50, -8),
        edge_paths=edge_paths, diagnostic=diagnostic,
    )

    assert route is not None and not route.isEmpty()
    assert adjacency[0].get(1) is not None
    assert diagnostic["start_component"] == diagnostic["end_component"]
