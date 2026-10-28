from app.modules.fttx_designer.engine.domain import RoadSegment
from app.modules.fttx_designer.engine.geometry_compat import (
    QgsCoordinateReferenceSystem,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
)
from app.modules.fttx_designer.engine.spatial_utils import DistanceCalculator
from app.modules.fttx_designer.engine.topology import RoadTopologyEngine


class QuietLogger:
    def log(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


def test_t_junction_splits_host_edge_at_projected_intersection():
    crs = QgsCoordinateReferenceSystem("EPSG:32631")
    host = QgsGeometry.fromPolylineXY([
        QgsPointXY(0, 0), QgsPointXY(50, 0), QgsPointXY(100, 0),
    ])
    side = QgsGeometry.fromPolylineXY([QgsPointXY(50, 10), QgsPointXY(50, 0)])
    roads = {
        11: RoadSegment(id=11, geometry=host, fid=11, length=host.length()),
        45: RoadSegment(id=45, geometry=side, fid=45, length=side.length()),
    }
    layer = QgsVectorLayer.from_records(
        [{"geometry": host}, {"geometry": side}], crs=crs,
    )
    engine = RoadTopologyEngine(
        roads, layer, DistanceCalculator(crs), QuietLogger(), snap_tol=1.5,
    )

    engine._build_raw_graph()
    engine._snap_dangling_to_line_interior()
    engine._build_weighted_adj()

    split_chainage, junction = engine._edge_splits[11][0]
    assert split_chainage == 50.0
    assert engine._nodes[junction]["point"] == QgsPointXY(50, 0)
    assert engine._node_degree(junction) == 3
    adjacent = {neighbor for neighbor, road_id, _ in engine.adj[junction]}
    assert adjacent == {
        engine._edges[11]["start"],
        engine._edges[11]["end"],
        engine._edges[45]["start"],
    }
    assert all(weight > 0 for _, _, weight in engine.adj[junction])
