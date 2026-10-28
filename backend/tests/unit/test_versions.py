# ============================================================
# OPSYN — tests/unit/test_versions.py
# Network GIS Phase 8 pure logic: comparing two versions' features
# (matched by kind + type + code; added / removed / moved / changed) and
# snapshot geometry in both formats. The database side (freeze, restore,
# audit trigger): tests/integration/test_versions_db.py.
# ============================================================

import pathlib
import re

from shapely import wkb
from shapely.geometry import Point

from app.modules.design.versions import MOVED_M, _geojson, _hex, compare_features


def asset(code, x, y, t="FAT", **p):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [x, y]},
            "properties": {"kind": "asset", "id": f"id-{code}-{x}", "asset_code": code, "asset_type": t, **p}}


def cable(code, coords, length, **p):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"kind": "cable", "id": f"c-{code}", "asset_code": code, "cable_category": "BOX_TO_BOX",
                           "length_m": length, **p}}


def test_added_removed_moved_changed():
    old = [asset("FAT-1", 3.39, 6.63), asset("FAT-2", 3.39, 6.63), asset("FDT-1", 3.38, 6.63, "FDT", capacity=64),
           cable("B-1", [[3.38, 6.63], [3.39, 6.63]], 110.0)]
    new = [asset("FAT-1", 3.3903, 6.63), asset("FAT-3", 3.40, 6.63), asset("FDT-1", 3.38, 6.63, "FDT", capacity=128),
           cable("B-1", [[3.38, 6.63], [3.385, 6.631], [3.3903, 6.63]], 140.0)]
    c = compare_features(old, new)
    assert c["counts"] == {"added": 1, "removed": 1, "moved": 1, "changed": 2}
    assert c["added"][0]["properties"]["asset_code"] == "FAT-3" and c["removed"][0]["properties"]["asset_code"] == "FAT-2"
    m = c["moved"][0]
    assert m["code"] == "FAT-1" and 30 < m["distance_m"] < 36 and m["from"] == [3.39, 6.63]
    changed = {x["code"]: x for x in c["changed"]}
    assert changed["FDT-1"]["fields"] == ["capacity"] and changed["FDT-1"]["before"] == {"capacity": 64}
    assert changed["B-1"]["fields"] == ["geometry"] and changed["B-1"]["length_after_m"] == 140.0
    assert changed["B-1"]["geometry_before"]["coordinates"][1] == [3.39, 6.63]


def test_matching_is_by_code_not_id():
    # An engine re-run gives new ids to the same devices: same code = same device
    a = asset("FAT-1", 3.39, 6.63)
    b = asset("FAT-1", 3.39, 6.63)
    b["properties"]["id"] = "a-new-id"
    assert compare_features([a], [b])["counts"] == {"added": 0, "removed": 0, "moved": 0, "changed": 0}


def test_tiny_shifts_are_not_moves():
    shift = MOVED_M / 2 / 111_195
    c = compare_features([asset("FAT-1", 3.39, 6.63)], [asset("FAT-1", 3.39, 6.63 + shift)])
    assert c["moved"] == []


def test_snapshot_geometry_both_formats():
    h = wkb.dumps(Point(3.39, 6.63), hex=True, srid=4326)
    assert _geojson(h) == {"type": "Point", "coordinates": (3.39, 6.63)}
    gj = {"type": "Point", "coordinates": [3.39, 6.63]}
    assert _geojson(gj) is gj and wkb.loads(bytes.fromhex(_hex(gj))).equals(Point(3.39, 6.63))
    assert _geojson(None) is None and _hex(h) == h


def test_0092_follows_0091_with_the_trigger_and_view():
    versions = pathlib.Path(__file__).parents[2] / "alembic" / "versions"
    text = next(versions.glob("0092_*.py")).read_text(encoding="utf-8")
    assert re.search(r"^down_revision\s*=\s*'0091'", text, re.M)
    for part in ("network_audit_log", "network_audit_row", "network_audit_trail", "clock_timestamp()", "app.audit_bulk"):
        assert part in text
