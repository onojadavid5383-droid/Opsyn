from app.modules.fttx_designer.engine.cable_routing import (
    CableRouter,
    NetworkDistanceOracle,
    route_fdt_to_fats,
)
from app.modules.fttx_designer.engine.distance_oracle import (
    clear_distance_oracle,
    install_distance_oracle,
)
from app.modules.fttx_designer.engine.domain import CableSegment, FAT, FDT, RoadSegment
from app.modules.fttx_designer.engine.geometry_compat import (
    QgsCoordinateReferenceSystem,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
)
from app.modules.fttx_designer.engine.spatial_utils import DistanceCalculator
from app.modules.fttx_designer.engine.validation import audit_b2b_detours
from app.modules.fttx_designer.engine.validation import (
    diagnose_b2b_headroom,
)


class FakeLogger:
    def __init__(self):
        self.messages = []

    def start_module(self, _name):
        pass

    def log(self, message):
        self.messages.append(message)

    def error(self, message):
        self.messages.append(message)

    def end_module(self, _name):
        pass


def make_single_hop_fixture(fdt_point, fat_point, fdt_road_id=1, fat_road_id=1):
    crs = QgsCoordinateReferenceSystem("EPSG:32631")
    road_a = QgsGeometry.fromPolylineXY([QgsPointXY(x, 0) for x in range(0, 101, 10)])
    road_b = QgsGeometry.fromPolylineXY([QgsPointXY(x, 400) for x in range(0, 101, 10)])
    road_geometries = {1: road_a, 2: road_b}
    road_layer = QgsVectorLayer.from_records(
        [
            {"geometry": road_a, "road_id": 1},
            {"geometry": road_b, "road_id": 2},
        ],
        crs=crs,
    )
    roads = {
        road_id: RoadSegment(
            id=road_id, geometry=geometry, fid=road_id, length=geometry.length()
        )
        for road_id, geometry in road_geometries.items()
    }
    dist_calc = DistanceCalculator(crs)
    router = CableRouter(road_layer, dist_calc, roads=roads)
    fat = FAT(
        name="FAT-01A-01",
        geometry=fat_point,
        road_id=fat_road_id,
        total_customers=1,
        cascade_order=1,
        from_device="FDT-01",
        to_device="",
        wing="A",
        parent_fdt="FDT-01",
        fat_sequence="01",
        offset_geometry=fat_point,
    )
    fdt = FDT(
        name="FDT-01",
        geometry=fdt_point,
        total_customers=1,
        total_fat=1,
        wing_a_count=1,
        wing_b_count=0,
        fats=[fat],
        primary_road_id=fdt_road_id,
    )
    tied = router.build_master_graph([fdt_point, fat_point])
    assert tied == 2
    return router, dist_calc, road_geometries, fdt, fat


def route_single_hop(router, fdt):
    cables = route_fdt_to_fats([fdt], router, FakeLogger())
    assert len(cables) == 1
    return cables[0]


def test_same_road_devices_one_metre_apart_follow_their_valid_road():
    fdt_point, fat_point = QgsPointXY(20, 0), QgsPointXY(21, 0)
    router, _dist_calc, _roads, fdt, _fat = make_single_hop_fixture(
        fdt_point, fat_point, fdt_road_id=1, fat_road_id=1
    )

    cable = route_single_hop(router, fdt)

    assert cable.length <= 3.0
    assert router.route_stats["temp_graph"] == 1
    assert router.route_stats["fallback"] == 0


def test_assigned_road_routes_along_physical_road_and_matches_oracle():
    fdt_point, fat_point = QgsPointXY(20, 0), QgsPointXY(60, 0)
    router, dist_calc, _roads, fdt, _fat = make_single_hop_fixture(
        fdt_point, fat_point, fdt_road_id=1, fat_road_id=1
    )
    oracle = NetworkDistanceOracle(router, dist_calc=dist_calc)
    oracle_distance = oracle.distance(fdt_point, fat_point)

    cable = route_single_hop(router, fdt)

    assert oracle_distance is not None
    assert abs(cable.length - oracle_distance) <= max(25.0, 0.1 * oracle_distance)
    assert cable.length == 40.0


def test_distant_assigned_road_is_flagged_instead_of_snapping_device():
    start, end = QgsPointXY(20, 0), QgsPointXY(60, 0)
    router, _dist_calc, _roads, _fdt, _fat = make_single_hop_fixture(
        start, end, fdt_road_id=2, fat_road_id=1,
    )

    geometry, length = router.find_shortest_path_points(
        start, end, start_road_id=2, end_road_id=1,
    )

    assert geometry.isEmpty()
    assert length == 0.0
    assert "maximum is 25.00 m" in router.anchor_errors[(20.0, 0.0)]


def test_nonexistent_assigned_road_is_flagged():
    start, end = QgsPointXY(20, 0), QgsPointXY(60, 0)
    router, _dist_calc, _roads, _fdt, _fat = make_single_hop_fixture(
        start, end, fdt_road_id=1, fat_road_id=1,
    )

    geometry, length = router.find_shortest_path_points(
        start, end, start_road_id=999, end_road_id=1,
    )

    assert geometry.isEmpty()
    assert length == 0.0
    assert "road 999 is missing" in router.anchor_errors[(20.0, 0.0)]


def test_b2b_vertices_follow_noded_roads_and_endpoint_stubs_are_bounded():
    fdt_point, fat_point = QgsPointXY(20, 0), QgsPointXY(80, 0)
    router, dist_calc, road_geometries, fdt, _fat = make_single_hop_fixture(
        fdt_point, fat_point, fdt_road_id=1, fat_road_id=1
    )

    cable = route_single_hop(router, fdt)
    vertices = cable.geometry.asPolyline()

    assert len(vertices) >= 4
    assert dist_calc.distance_points(vertices[0], vertices[1]) <= 15.0
    assert dist_calc.distance_points(vertices[-2], vertices[-1]) <= 15.0
    for vertex in vertices[1:-1]:
        point_geom = QgsGeometry.fromPointXY(vertex)
        assert min(geometry.distance(point_geom) for geometry in road_geometries.values()) <= 1e-6


def test_same_road_route_has_zero_anchor_misses_and_headroom_disagreements():
    fdt_point, fat_point = QgsPointXY(20, 0), QgsPointXY(60, 0)
    router, dist_calc, _roads, fdt, _fat = make_single_hop_fixture(
        fdt_point, fat_point, fdt_road_id=None, fat_road_id=1
    )
    cable = route_single_hop(router, fdt)
    logger = FakeLogger()
    oracle = NetworkDistanceOracle(router, dist_calc=dist_calc, logger=logger)
    install_distance_oracle(oracle)
    try:
        summary = diagnose_b2b_headroom(
            [fdt], [cable], logger, dist_calc=dist_calc
        )
    finally:
        clear_distance_oracle()

    assert summary["oracle_disagreements"] == []
    assert any("Decision-time and routed distances agree on every hop" in m for m in logger.messages)
    assert router.route_stats["temp_graph"] == 1
    assert router.route_stats["fallback"] == 0
    assert router.route_stats["master"] == 0


def test_route_stats_record_temporary_graph_and_fallback_answers():
    fdt_point, fat_point = QgsPointXY(20, 0), QgsPointXY(60, 0)
    router, _dist_calc, _roads, _fdt, _fat = make_single_hop_fixture(
        fdt_point, fat_point
    )

    router.build_master_graph([])
    route, _length = router.find_shortest_path_points(fdt_point, fat_point)
    assert not route.isEmpty()
    assert router.route_stats == {"master": 0, "temp_graph": 1, "fallback": 0}

    empty_router = CableRouter(
        QgsVectorLayer.from_records([], crs=QgsCoordinateReferenceSystem("EPSG:32631")),
        DistanceCalculator(QgsCoordinateReferenceSystem("EPSG:32631")),
    )
    empty_router.find_shortest_path_points(fdt_point, fat_point)
    assert empty_router.route_stats == {"master": 0, "temp_graph": 0, "fallback": 1}


def test_moved_device_rebuild_clears_master_lookup_and_dijkstra_cache():
    old_start, moved_start, end = (
        QgsPointXY(20, 0), QgsPointXY(25, 0), QgsPointXY(60, 0),
    )
    router, _dist_calc, _roads, _fdt, _fat = make_single_hop_fixture(
        old_start, end,
    )
    router.build_master_graph([old_start, end])
    assert router.find_shortest_path_points(old_start, end)[0].isEmpty() is False
    assert router._master_tree_cache

    router.build_master_graph([moved_start, end])
    assert router._master_tree_cache == {}
    assert (round(old_start.x(), 6), round(old_start.y(), 6)) not in router._master_lookup
    assert (round(moved_start.x(), 6), round(moved_start.y(), 6)) in router._master_lookup

    geometry, length = router.find_shortest_path_points(moved_start, end)
    vertices = geometry.asPolyline()
    assert vertices[0] == moved_start
    assert vertices[-1] == end
    assert length == 35.0


def test_nearby_parallel_roads_remain_disconnected_in_master_graph():
    crs = QgsCoordinateReferenceSystem("EPSG:32631")
    road_geoms = {
        1: QgsGeometry.fromPolylineXY([QgsPointXY(0, 0), QgsPointXY(100, 0)]),
        2: QgsGeometry.fromPolylineXY([QgsPointXY(0, 8), QgsPointXY(100, 8)]),
    }
    roads = {
        rid: RoadSegment(id=rid, geometry=geom, fid=rid, length=geom.length())
        for rid, geom in road_geoms.items()
    }
    layer = QgsVectorLayer.from_records(
        [{"geometry": geom} for geom in road_geoms.values()], crs=crs,
    )
    router = CableRouter(layer, DistanceCalculator(crs), roads=roads)
    start, end = QgsPointXY(20, 0), QgsPointXY(60, 8)
    road_ids = {
        (round(start.x(), 6), round(start.y(), 6)): 1,
        (round(end.x(), 6), round(end.y(), 6)): 2,
    }

    assert router.build_master_graph([start, end], point_road_ids=road_ids) == 2
    geometry, length = router.find_shortest_path_points(
        start, end, start_road_id=1, end_road_id=2,
    )

    assert geometry.isEmpty()
    assert length == 0.0


def test_real_road_detour_with_modest_ratio_passes_detour_audit():
    crs = QgsCoordinateReferenceSystem("EPSG:32631")
    road = QgsGeometry.fromPolylineXY([
        QgsPointXY(0, 0), QgsPointXY(0, 150),
        QgsPointXY(1000, 150), QgsPointXY(1000, 0),
    ])
    roads = {1: RoadSegment(id=1, geometry=road, fid=1, length=road.length())}
    layer = QgsVectorLayer.from_records([{"geometry": road}], crs=crs)
    dist_calc = DistanceCalculator(crs)
    router = CableRouter(layer, dist_calc, roads=roads)
    start, end = QgsPointXY(0, 0), QgsPointXY(1000, 0)

    geometry, length = router.find_shortest_path_points(
        start, end, start_road_id=1, end_road_id=1,
    )
    cable = CableSegment(
        name="genuine-detour", start_device="A", end_device="B",
        geometry=geometry, length=length, fdt_id="FDT-01",
    )

    assert not geometry.isEmpty()
    assert geometry.asPolyline()[0] == start
    assert geometry.asPolyline()[-1] == end
    assert length == geometry.length() == 1300.0
    assert audit_b2b_detours([cable], dist_calc, FakeLogger()) == []
