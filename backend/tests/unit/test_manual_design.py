# ============================================================
# OPSYN — tests/unit/test_manual_design.py
# Network GIS Phase 6 pure logic: the operation catalogue matches the plan
# (§3.7), restore order, line clean-up, the road-side snap offset and the
# snap kinds. The operations themselves, with undo/redo against real rows:
# tests/integration/test_manual_design_db.py.
# ============================================================

import math

import pytest
from fastapi import HTTPException

from app.modules.design.operations import FEEDING_CABLES, GEOM_COLS, OP_LABEL, OPS, TABLES, _dedupe, _parents_first
from app.modules.design.snap import KINDS, ROAD_SIDE_M, side_of_road
from app.modules.network.asset_types import CABLE_CATEGORIES


def test_every_planned_operation_exists():
    planned = {"ADD_ASSET", "MOVE_ASSET", "DELETE_ASSET", "UPDATE_ATTRS", "DRAW_CABLE", "EDIT_CABLE_GEOM",
               "SPLIT_CABLE", "EXTEND_CABLE", "CONNECT", "DISCONNECT"}
    assert planned <= set(OPS) and set(OPS) <= set(OP_LABEL)


def test_feeding_cables_are_real_categories():
    assert set(FEEDING_CABLES) <= set(CABLE_CATEGORIES) and "DROP" not in FEEDING_CABLES


def test_row_images_cover_every_table_and_geometry():
    assert set(GEOM_COLS) == set(TABLES) and GEOM_COLS["net_assets"] == ("geom", "design_geom", "asbuilt_geom")


def test_parents_are_restored_before_children():
    rows = [{"id": "kid", "parent_id": "fat"}, {"id": "fat", "parent_id": None}, {"id": "other", "parent_id": "live"}]
    assert [r["id"] for r in _parents_first(rows)] == ["fat", "other", "kid"]


def test_lines_lose_repeated_points_and_need_two():
    assert _dedupe([[1, 1], [1, 1], [2, 2]]) == [[1, 1], [2, 2]]
    with pytest.raises(HTTPException):
        _dedupe([[1, 1], [1, 1]])


def test_devices_sit_beside_the_road():
    m = 6_371_000 * math.pi / 180          # metres per degree of latitude on the sphere side_of_road uses
    road = (3.39, 6.63)
    north = side_of_road(road, (3.39, 6.63 + 20 / m))
    assert math.isclose((north[1] - road[1]) * m, ROAD_SIDE_M, rel_tol=1e-3) and north[0] == pytest.approx(road[0])
    near = side_of_road(road, (3.39, 6.63 + 1 / m))          # closer than the offset: the click itself
    assert (near[1] - road[1]) * m == pytest.approx(1, rel=1e-3)
    assert side_of_road(road, road) == road


def test_snap_prefers_devices_over_roads():
    assert KINDS.index("asset") < KINDS.index("homepass") < KINDS.index("road") < KINDS.index("boundary")
