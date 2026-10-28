# ============================================================
# OPSYN — tests/unit/test_network_catalogue.py
# Network GIS Phase 2 pure logic: attribute specs and coercion, the
# catalogue contract, generated-code format, network upload parsing
# (Excel + GeoJSON, points + WKT/GeoJSON lines), row validation, templates,
# cable geometry schema, update-only-what-changed attribute checks, and the
# 0088 migration's place in the chain. No database required — the SQL
# paths are covered by tests/integration/test_network_catalogue_db.py.
# ============================================================

import io
import json
import pathlib
import re

import openpyxl
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.network.asset_types import ASSET_TYPES, CABLE_CATEGORIES, ROUTE_METHODS
from app.modules.network.attributes import (
    ASSET_ATTRIBUTES, CABLE_ATTRIBUTES, FieldSpec, coerce, validate_attributes,
)
from app.modules.network.catalogue import build_catalogue
from app.modules.network.codes import code_pattern, format_code, prefix_for
from app.modules.network.schemas import AssetCreate, CableCreate, LineGeometry
from app.modules.network.service import checked_attributes
from app.modules.network.upload import (
    NET_UPLOAD_TYPES, FileError, columns, file_format, line_from_row, point_from_row,
    read_rows, template_xlsx, upload_type_specs, validate_row,
)


# ── Attributes ───────────────────────────────────────────────

class TestCoerce:

    @pytest.mark.parametrize("spec,raw,expected", [
        (FieldSpec("h", "Height", "number", min=0), "9.5", 9.5),
        (FieldSpec("h", "Height", "number", min=0), 12, 12.0),
        (FieldSpec("n", "Trays", "int", min=0), "12", 12),
        (FieldSpec("n", "Trays", "int", min=0), 12.0, 12),
        (FieldSpec("b", "Existing", "bool"), "Yes", True),
        (FieldSpec("b", "Existing", "bool"), 0, False),
        (FieldSpec("m", "Material", "enum", options=("CONCRETE", "WOOD")), "concrete", "CONCRETE"),
        (FieldSpec("t", "Owner", "text"), "  IHS  ", "IHS"),
        (FieldSpec("t", "Owner", "text"), "   ", None),
        (FieldSpec("t", "Owner", "text"), None, None),
    ])
    def test_accepts(self, spec, raw, expected):
        assert coerce(spec, raw) == (expected, None)

    @pytest.mark.parametrize("spec,raw", [
        (FieldSpec("n", "Trays", "int", min=0), "12.5"),
        (FieldSpec("n", "Trays", "int", min=0), -1),
        (FieldSpec("n", "Trays", "int", min=0), "twelve"),
        (FieldSpec("h", "Height", "number"), "nan"),
        (FieldSpec("h", "Height", "number"), True),
        (FieldSpec("b", "Existing", "bool"), "maybe"),
        (FieldSpec("m", "Material", "enum", options=("CONCRETE",)), "STEEL"),
        (FieldSpec("t", "Owner", "text"), "x" * 201),
    ])
    def test_rejects_with_a_readable_message(self, spec, raw):
        value, err = coerce(spec, raw)
        assert value is None and spec.label in err


class TestValidateAttributes:

    def test_known_keys_checked_unknown_keys_kept(self):
        clean, errors = validate_attributes(ASSET_ATTRIBUTES["POLE"], {
            "height_m": "9", "material": "wood", "legacy_ref": {"x": 1}, "engine_wing": "A",
        })
        assert errors == []
        assert clean == {"height_m": 9.0, "material": "WOOD", "legacy_ref": {"x": 1}, "engine_wing": "A"}

    def test_blank_known_value_is_removed(self):
        clean, _ = validate_attributes(ASSET_ATTRIBUTES["POLE"], {"owner": ""})
        assert "owner" not in clean

    def test_every_asset_type_has_a_spec_and_unique_keys(self):
        assert set(ASSET_ATTRIBUTES) == set(ASSET_TYPES)
        for specs in [*ASSET_ATTRIBUTES.values(), CABLE_ATTRIBUTES]:
            keys = [s.key for s in specs]
            assert len(keys) == len(set(keys))
            for s in specs:
                assert s.kind in {"text", "int", "number", "bool", "enum"}
                assert (s.kind == "enum") == bool(s.options)

    def test_update_checks_only_what_changed(self):
        # An imported split ratio outside the enum must not block an unrelated edit
        old = {"split_ratio": "1:12", "number_customer": 3}
        new = {"split_ratio": "1:12", "number_customer": 5}
        assert checked_attributes(ASSET_ATTRIBUTES["SPLITTER"], new, old) == {"split_ratio": "1:12", "number_customer": 5}
        with pytest.raises(HTTPException) as exc:
            checked_attributes(ASSET_ATTRIBUTES["SPLITTER"], {"split_ratio": "1:13"}, old)
        assert exc.value.status_code == 422 and "Split ratio" in exc.value.detail


# ── Catalogue & codes ────────────────────────────────────────

class TestCatalogue:

    def test_lists_every_type_with_its_fields(self):
        cat = build_catalogue()
        assert [t["code"] for t in cat["asset_types"]] == list(ASSET_TYPES)
        assert [c["code"] for c in cat["cable_categories"]] == list(CABLE_CATEGORIES)
        fat = next(t for t in cat["asset_types"] if t["code"] == "FAT")
        assert fat["code_example"] == "FAT-0001" and fat["capacity_label"] == "Customer ports"
        ratio = next(f for f in fat["attributes"] if f["key"] == "splitter_ratio")
        assert ratio["kind"] == "enum" and "1:8" in ratio["options"]
        assert cat["transitions"]["RETIRED"] == []
        assert "IMPORTED" in cat["route_methods"]

    def test_catalogue_is_json_serialisable(self):
        json.dumps(build_catalogue())


class TestCodes:

    def test_format_and_pattern_agree(self):
        assert format_code("FAT", 14) == "FAT-0014"
        assert format_code("POLE", 12345) == "POLE-12345"
        assert re.match(code_pattern("FAT"), "FAT-0014")
        assert not re.match(code_pattern("FAT"), "FAT-14A")
        assert not re.match(code_pattern("FAT"), "XFAT-0014")

    def test_prefixes(self):
        assert prefix_for("asset", "MANHOLE") == "MH"
        assert prefix_for("cable", "DROP") == "DRP"

    def test_create_without_code_is_allowed(self):
        a = AssetCreate(asset_type="POLE", geometry={"type": "Point", "coordinates": [3.35, 6.6]}, asset_code="  ")
        assert a.asset_code is None


# ── Cable geometry schema ────────────────────────────────────

class TestLineGeometry:

    def test_valid_line(self):
        g = LineGeometry(type="LineString", coordinates=[[3.35, 6.6, 12.0], [3.36, 6.61]])
        assert g.coordinates == [[3.35, 6.6], [3.36, 6.61]]  # elevation dropped

    @pytest.mark.parametrize("coords", [[[3.35, 6.6]], [[3.35, 6.6], [3.35, 6.6]], [[3.35, 6.6], [200, 6.6]], [[0, 0], [3.3, 6.6]]])
    def test_invalid_lines(self, coords):
        with pytest.raises(ValidationError):
            LineGeometry(type="LineString", coordinates=coords)

    def test_client_cannot_claim_road_graph(self):
        with pytest.raises(ValidationError):
            CableCreate(cable_category="DROP", route_method="ROAD_GRAPH",
                        geometry={"type": "LineString", "coordinates": [[3.35, 6.6], [3.36, 6.61]]})

    def test_route_methods_include_imported_and_direct(self):
        assert ROUTE_METHODS == ("ROAD_GRAPH", "MANUAL_GEOMETRY", "IMPORTED", "DIRECT")      # 0088, 0091


# ── Uploads ──────────────────────────────────────────────────

def _xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _geojson(features: list[dict]) -> bytes:
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


class TestReadRows:

    def test_xlsx_headers_are_case_insensitive(self):
        headers, rows = read_rows("poles.xlsx", _xlsx([["Longitude", "LATITUDE", "Height_m"], [3.35, 6.6, 9], [None, None, None]]))
        assert headers == ["longitude", "latitude", "height_m"]
        assert list(rows) == [(2, {"longitude": 3.35, "latitude": 6.6, "height_m": 9}, None)]  # blank row skipped

    def test_geojson_features(self):
        headers, rows = read_rows("c.geojson", _geojson([
            {"type": "Feature", "properties": {"Cable_Category": "DROP"},
             "geometry": {"type": "LineString", "coordinates": [[3.35, 6.6], [3.36, 6.61]]}},
        ]))
        n, props, geom = next(rows)
        assert headers == ["cable_category"] and props == {"cable_category": "DROP"} and geom["type"] == "LineString"

    @pytest.mark.parametrize("name,data,msg", [
        ("p.csv", b"a,b", "not an Excel"),
        ("p.xlsx", b"", "empty"),
        ("p.xlsx", b"not a zip", "not a valid Excel"),
        ("p.geojson", b"{", "not valid JSON"),
        ("p.geojson", b'{"type": "Feature"}', "FeatureCollection"),
    ])
    def test_bad_files(self, name, data, msg):
        with pytest.raises(FileError, match=msg):
            read_rows(name, data)

    def test_format_detection(self):
        assert file_format("A.XLSX") == "xlsx" and file_format("a.json") == "geojson"


class TestGeometryParsing:

    def test_point_from_columns_or_geometry(self):
        assert point_from_row({"longitude": "3.35", "latitude": "6.6"}, None)[0] == [3.35, 6.6]
        assert point_from_row({}, {"type": "Point", "coordinates": [3.35, 6.6]})[0] == [3.35, 6.6]
        assert point_from_row({"longitude": 0, "latitude": 0}, None)[1].startswith("(0, 0)")
        assert "Point" in point_from_row({}, {"type": "LineString", "coordinates": []})[1]

    def test_wkt_lines(self):
        coords, err = line_from_row({"geometry_wkt": "linestring( 3.35 6.6 , 3.36 6.61 )"}, None)
        assert err is None and coords == [[3.35, 6.6], [3.36, 6.61]]
        assert line_from_row({"geometry_wkt": "POINT(3 6)"}, None)[1].startswith("geometry_wkt must")
        assert "two distinct" in line_from_row({"geometry_wkt": "LINESTRING(3.3 6.6, 3.3 6.6)"}, None)[1]


class TestValidateRow:

    def test_pole_row(self):
        out, errs = validate_row(NET_UPLOAD_TYPES["pole"], {
            "longitude": 3.35, "latitude": 6.6, "material": "steel", "height_m": "11", "lifecycle_status": "",
        }, None)
        assert errs == []
        assert out["lifecycle_status"] == "ACTIVE" and out["asset_code"] is None
        assert out["attributes"] == {"material": "STEEL", "height_m": 11.0}
        assert out["_geometry"] == {"type": "Point", "coordinates": [3.35, 6.6]}

    def test_every_problem_is_reported(self):
        _out, errs = validate_row(NET_UPLOAD_TYPES["fat"], {
            "longitude": "x", "latitude": 6.6, "splitter_ratio": "1:3", "capacity": 8, "used_capacity": 9,
            "lifecycle_status": "LIVE",
        }, None)
        fields = {e["field"] for e in errs}
        assert {"longitude", "splitter_ratio", "used_capacity", "lifecycle_status"} <= fields

    def test_cable_row(self):
        out, errs = validate_row(NET_UPLOAD_TYPES["cable"], {
            "cable_category": "drop", "geometry_wkt": "LINESTRING(3.35 6.6, 3.36 6.61)",
            "fiber_count": 2, "installation_type": "aerial", "source_asset_code": " FAT-0014 ",
        }, None)
        assert errs == []
        assert out["cable_category"] == "DROP" and out["installation_type"] == "AERIAL"
        assert out["source_asset_code"] == "FAT-0014"

    def test_cable_needs_a_category(self):
        _out, errs = validate_row(NET_UPLOAD_TYPES["cable"], {"geometry_wkt": "LINESTRING(3.35 6.6, 3.36 6.61)"}, None)
        assert errs[0]["field"] == "cable_category"


class TestSpecsAndTemplates:

    def test_specs_list_attribute_columns(self):
        specs = {s["key"]: s for s in upload_type_specs()}
        assert "height_m" in specs["pole"]["optional_columns"]
        assert specs["cable"]["required_columns"] == ["cable_category", "geometry_wkt"]
        assert specs["cable"]["geojson_geometry"] == "LineString"

    @pytest.mark.parametrize("key", list(NET_UPLOAD_TYPES))
    def test_template_round_trips_through_validation(self, key):
        u = NET_UPLOAD_TYPES[key]
        headers, rows = read_rows("t.xlsx", template_xlsx(u).getvalue())
        req, opt = columns(u)
        assert headers == req + opt
        _n, row, geom = next(rows)
        _out, errs = validate_row(u, row, geom)
        assert errs == []  # the example row itself must be valid


class TestMigrationChain:

    def test_0088_follows_0087(self):
        versions = pathlib.Path(__file__).parents[2] / "alembic" / "versions"
        text = next(versions.glob("0088_*.py")).read_text(encoding="utf-8")
        assert re.search(r"^down_revision\s*=\s*'0087'", text, re.M)

    def test_0087_route_methods_are_frozen(self):
        versions = pathlib.Path(__file__).parents[2] / "alembic" / "versions"
        text = next(versions.glob("0087_*.py")).read_text(encoding="utf-8")
        assert "ROUTE_METHODS = ('ROAD_GRAPH', 'MANUAL_GEOMETRY')" in text
