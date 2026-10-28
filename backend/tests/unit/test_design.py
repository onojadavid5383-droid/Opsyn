# ============================================================
# OPSYN — tests/unit/test_design.py
# Network GIS Phase 4 pure logic: the design input parser (every layer's
# geometry rules, homepass counts, Excel and GeoJSON, all-or-nothing
# errors), schemas and editable statuses, hydrator cable grouping, the
# engine bridge's MultiLineString handling, and the 0090 migration.
# The database + engine paths: tests/integration/test_design_db.py.
# ============================================================

import io
import json
import pathlib
import re

import openpyxl
import pytest
from pydantic import ValidationError

from app.modules.design.engine_bridge import MissingInputs, _explode_multilines, build_context
from app.modules.design.hydrator import CABLE_GROUP
from app.modules.design.inputs import GEOMETRY_TYPES, parse_input_file
from app.modules.design.models import DESIGN_STATUSES, EDITABLE_STATUSES, INPUT_LAYERS
from app.modules.design.schemas import DesignCreate, DesignUpdate, RouteRequest
from app.modules.network.asset_types import CABLE_CATEGORIES


def gj(*features):
    return json.dumps({"type": "FeatureCollection", "features": list(features)}).encode()


def feat(geom, **props):
    return {"type": "Feature", "properties": props, "geometry": geom}


def xlsx(rows):
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


LINE = {"type": "LineString", "coordinates": [[3.35, 6.60], [3.36, 6.60]]}
POINT = {"type": "Point", "coordinates": [3.35, 6.60]}


class TestInputParser:

    def test_every_layer_has_geometry_rules(self):
        assert set(GEOMETRY_TYPES) == set(INPUT_LAYERS)

    def test_roads_accept_lines_and_multilines(self):
        multi = {"type": "MultiLineString", "coordinates": [[[3.35, 6.6], [3.36, 6.6]], [[3.36, 6.6], [3.36, 6.61]]]}
        out = parse_input_file("road", "r.geojson", gj(feat(LINE, name="Allen Ave"), feat(multi)))
        assert not out.errors and len(out.features) == 2 and out.features[0]["properties"] == {"name": "Allen Ave"}

    @pytest.mark.parametrize("layer,geom,msg", [
        ("road", POINT, "must be LineString or MultiLineString"),
        ("homepass", LINE, "must be Point"),
        ("road", {"type": "LineString", "coordinates": [[3.35, 6.6], [3.35, 6.6]]}, "two distinct points"),
        ("pole", {"type": "Point", "coordinates": [200, 6.6]}, "outside longitude"),
        ("building", {"type": "Polygon", "coordinates": [[[3.35, 6.6], [3.36, 6.61], [3.36, 6.6], [3.35, 6.61], [3.35, 6.6]]]}, "not valid"),
    ])
    def test_bad_geometry_is_reported(self, layer, geom, msg):
        out = parse_input_file(layer, "x.geojson", gj(feat(geom)))
        assert msg in out.errors[0]["error"] and not out.features

    def test_one_bad_feature_rejects_the_file_but_reports_all(self):
        out = parse_input_file("pole", "p.geojson", gj(feat(POINT), feat(LINE), feat(LINE)))
        assert len(out.errors) == 2 and [e["row"] for e in out.errors] == [2, 3]

    def test_homepass_counts(self):
        out = parse_input_file("homepass", "h.geojson", gj(
            feat(POINT, Customers="4"), feat(POINT, units=2), feat(POINT, name="Block C"), feat(POINT, HP=3.0)))
        assert [f["properties"]["customers"] for f in out.features] == [4, 2, 1, 3]
        assert out.warnings == ["1 homepasses had no customer count and were counted as 1"]

    def test_excel_points_and_lines(self):
        poles = parse_input_file("pole", "p.xlsx", xlsx([["Longitude", "Latitude", "height_m"], [3.35, 6.6, 9]]))
        assert poles.features[0] == {"geometry": {"type": "Point", "coordinates": [3.35, 6.6]}, "properties": {"height_m": 9}}
        roads = parse_input_file("road", "r.xlsx", xlsx([["name", "geometry_wkt"], ["Toyin St", "LINESTRING(3.35 6.6, 3.36 6.6)"]]))
        assert roads.features[0]["geometry"]["type"] == "LineString" and roads.features[0]["properties"] == {"name": "Toyin St"}
        bad = parse_input_file("road", "r.xlsx", xlsx([["name", "geometry_wkt"], ["x", "POINT(3 6)"]]))
        assert bad.errors[0]["field"] == "geometry"

    def test_empty_and_unreadable_files(self):
        assert parse_input_file("pole", "p.geojson", gj()).errors[0]["error"] == "The file has no features"
        assert "not valid JSON" in parse_input_file("pole", "p.geojson", b"{").errors[0]["error"]
        assert parse_input_file("pole", "p.geojson", gj(feat(POINT))).file_hash


class TestSchemas:

    def test_create_strips_the_name(self):
        assert DesignCreate(name="  Phase 1 ").name == "Phase 1"
        with pytest.raises(ValidationError):
            DesignCreate(name="   ")

    def test_only_draft_or_modified_can_be_set_by_hand(self):
        assert set(EDITABLE_STATUSES) <= set(DESIGN_STATUSES)
        assert DesignUpdate(status="MODIFIED").status == "MODIFIED"
        with pytest.raises(ValidationError) as exc:
            DesignUpdate(status="APPROVED")
        assert "own steps" in str(exc.value)

    def test_boundary_must_be_an_area(self):
        with pytest.raises(ValidationError):
            DesignUpdate(boundary=LINE)
        assert DesignUpdate(boundary=None).model_fields_set == {"boundary"}

    def test_route_request_uses_from_and_to(self):
        r = RouteRequest.model_validate({"from": {"asset_id": "a"}, "to": {"lng": 3.3, "lat": 6.6}})
        assert r.start.asset_id == "a" and r.end.lat == 6.6


class TestEngineBridge:

    def test_every_cable_category_has_an_engine_group(self):
        assert set(CABLE_GROUP) == set(CABLE_CATEGORIES) - {"INTERNAL"}

    def test_multilines_are_split_for_the_engine(self):
        multi = {"type": "MultiLineString", "coordinates": [[[3.35, 6.6], [3.36, 6.6]], [[3.36, 6.6], [3.36, 6.61]]]}
        out = _explode_multilines({"features": [feat(multi, name="A"), feat(LINE, name="B")]})
        assert [f["geometry"]["type"] for f in out["features"]] == ["LineString"] * 3
        assert [f["properties"]["name"] for f in out["features"]] == ["A", "A", "B"]

    def test_no_roads_is_a_clear_refusal(self):
        with pytest.raises(MissingInputs, match="Upload the design's roads first"):
            build_context({"homepass": {"features": [feat(POINT)]}}, {})


class TestValidationCodes:

    def test_documented_codes_are_the_ones_raised(self):
        src = pathlib.Path(__file__).parents[2] / "app" / "modules" / "design" / "validation_service.py"
        text = src.read_text(encoding="utf-8")
        header = text.split("from __future__")[0]          # the comment header only
        documented = set(re.findall(r"\b([A-Z]+(?:_[A-Z]+)+)\b", header))     # every code has an underscore
        raised = set(re.findall(r'_issue\("(?:ERROR|WARNING|INFO)", "([A-Z_]+)"', text))
        assert raised == documented


class TestMigration:

    def test_0090_follows_0089_and_links_working_sets(self):
        versions = pathlib.Path(__file__).parents[2] / "alembic" / "versions"
        text = next(versions.glob("0090_*.py")).read_text(encoding="utf-8")
        assert re.search(r"^down_revision\s*=\s*'0089'", text, re.M)
        for table in ("net_assets", "net_cables", "net_connections"):
            assert table in text
        assert "FORCE ROW LEVEL SECURITY" in text and "ON DELETE CASCADE" in text
