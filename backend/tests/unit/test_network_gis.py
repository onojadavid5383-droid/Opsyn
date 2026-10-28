# ============================================================
# OPSYN — tests/unit/test_network_gis.py
# Network GIS Phase 1 pure logic: lifecycle transitions, asset-type zoom
# bands, tile coordinate/revision validation, the layer registry
# contract, request schemas, bbox parsing, LIKE escaping, and the 0087
# migration's place in the revision chain. No database required — the
# PostGIS behaviour (tiles, RLS, backfill) is covered by
# tests/integration/test_network_gis_db.py.
# ============================================================

import pathlib
import re

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.gis import tiles
from app.modules.gis.layer_registry import (
    ASSETS_SOURCE_LAYER, CABLES_SOURCE_LAYER, TILE_MAX_ZOOM, build_registry,
)
from app.modules.network.asset_types import (
    ASSET_TYPES, CABLE_CATEGORIES, CONTAINED_MIN_ZOOM,
    asset_types_visible_at, cable_categories_visible_at,
)
from app.modules.network.backfill import BACKFILL_STATEMENTS
from app.modules.network.lifecycle import (
    LIFECYCLE_STATES, LIVE_STATES, TRANSITIONS, can_transition,
)
from app.modules.network.schemas import AssetCreate, AssetUpdate
from app.modules.network.service import escape_like, parse_bbox


class TestLifecycle:

    def test_every_state_has_a_transition_entry(self):
        assert set(TRANSITIONS) == set(LIFECYCLE_STATES)

    @pytest.mark.parametrize("current,target", [
        ("DRAFT", "PLANNED"), ("DESIGNED", "UNDER_REVIEW"), ("UNDER_REVIEW", "APPROVED"),
        ("APPROVED", "CONSTRUCTION"), ("TESTING", "VERIFIED"), ("VERIFIED", "ACTIVE"),
        ("ACTIVE", "FAULTY"), ("FAULTY", "ACTIVE"), ("ACTIVE", "RETIRED"),
    ])
    def test_allowed_moves(self, current, target):
        assert can_transition(current, target)

    @pytest.mark.parametrize("current,target", [
        ("DRAFT", "ACTIVE"),          # cannot skip review and construction
        ("APPROVED", "DESIGNED"),     # an approved design is locked
        ("RETIRED", "ACTIVE"),        # retired is terminal
        ("ACTIVE", "ACTIVE"),         # staying put is not a transition
        ("ACTIVE", "NOT_A_STATE"),
        ("NOT_A_STATE", "ACTIVE"),
    ])
    def test_rejected_moves(self, current, target):
        assert not can_transition(current, target)

    def test_retired_is_terminal(self):
        assert TRANSITIONS["RETIRED"] == frozenset()

    def test_live_states_are_the_operating_network(self):
        assert set(LIVE_STATES) == {"ACTIVE", "FAULTY", "VERIFIED"}


class TestZoomBands:

    def test_low_zoom_shows_only_the_backbone(self):
        visible = set(asset_types_visible_at(7))
        assert {"POP", "OLT", "SITE"} <= visible
        assert not visible & {"FAT", "SPLITTER", "POLE", "ONU", "FDT", "CABINET"}

    def test_distribution_appears_by_street_zoom(self):
        assert {"FDT", "CABINET"} <= set(asset_types_visible_at(11))
        assert {"FAT", "SPLITTER", "CLOSURE"} <= set(asset_types_visible_at(12))
        assert "ONU" not in asset_types_visible_at(14)

    def test_everything_is_visible_at_max_zoom(self):
        assert set(asset_types_visible_at(TILE_MAX_ZOOM)) == set(ASSET_TYPES)
        assert set(cable_categories_visible_at(TILE_MAX_ZOOM)) == set(CABLE_CATEGORIES)

    def test_drops_only_at_customer_zoom(self):
        assert "DROP" not in cable_categories_visible_at(14)
        assert "DROP" in cable_categories_visible_at(15)
        assert "FEEDER" in cable_categories_visible_at(0)

    def test_visibility_is_monotonic(self):
        for z in range(TILE_MAX_ZOOM):
            assert set(asset_types_visible_at(z)) <= set(asset_types_visible_at(z + 1))
            assert set(cable_categories_visible_at(z)) <= set(cable_categories_visible_at(z + 1))


class TestTileMaths:

    @pytest.mark.parametrize("z,x,y", [(0, 0, 0), (15, 16383, 16383), (20, 0, (1 << 20) - 1)])
    def test_valid_tiles(self, z, x, y):
        assert tiles.valid_tile(z, x, y)

    @pytest.mark.parametrize("z,x,y", [(-1, 0, 0), (21, 0, 0), (1, 2, 0), (1, 0, -1), (15, 1 << 15, 0)])
    def test_invalid_tiles(self, z, x, y):
        assert not tiles.valid_tile(z, x, y)

    @pytest.mark.parametrize("rev,ok", [
        ("0a1b2c3d4e5f6789", True), ("abc", True), (None, False), ("", False),
        ("ABC", False), ("abc;drop", False), ("a" * 33, False),
    ])
    def test_revision_validation(self, rev, ok):
        assert tiles.valid_revision(rev) is ok

    def test_cache_key_is_tenant_and_revision_scoped(self):
        a = tiles.cache_key("t1", "r1", "network", 14, 1, 2)
        assert a != tiles.cache_key("t2", "r1", "network", 14, 1, 2)
        assert a != tiles.cache_key("t1", "r2", "network", 14, 1, 2)

    def test_tile_params_apply_zoom_rules(self):
        p = tiles.tile_params("tid", 10, 1, 2)
        assert "SPLITTER" not in p["asset_types"] and "OLT" in p["asset_types"]
        assert p["show_contained"] is False
        assert tiles.tile_params("tid", CONTAINED_MIN_ZOOM, 0, 0)["show_contained"] is True
        assert p["live"] == list(LIVE_STATES)

    def test_tile_sql_binds_tenant_and_names_both_layers(self):
        assert "a.tenant_id = :tid" in tiles.TILE_SQL and "c.tenant_id = :tid" in tiles.TILE_SQL
        assert f"'{ASSETS_SOURCE_LAYER}'" in tiles.TILE_SQL
        assert f"'{CABLES_SOURCE_LAYER}'" in tiles.TILE_SQL
        assert "a.design_id IS NULL" in tiles.TILE_SQL and "a.deleted_at IS NULL" in tiles.TILE_SQL


class TestLayerRegistry:

    def test_every_type_and_category_is_listed_once(self):
        reg = build_registry({"OLT": 3}, {"FEEDER": 2}, "abc")
        asset_keys = [l["key"] for g in reg["groups"] if g["kind"] == "asset" for l in g["layers"]]
        cable_keys = [l["key"] for g in reg["groups"] if g["kind"] == "cable" for l in g["layers"]]
        assert sorted(asset_keys) == sorted(ASSET_TYPES)
        assert sorted(cable_keys) == sorted(CABLE_CATEGORIES)

    def test_counts_default_to_zero(self):
        reg = build_registry({"OLT": 3}, {}, "abc")
        layers = {l["key"]: l for g in reg["groups"] for l in g["layers"]}
        assert layers["OLT"]["count"] == 3 and layers["FAT"]["count"] == 0

    def test_tile_contract(self):
        reg = build_registry({}, {}, "abc")
        assert reg["revision"] == "abc"
        assert reg["tiles"]["url_template"] == "/gis/tiles/network/{z}/{x}/{y}.mvt"
        assert reg["tiles"]["source_layers"] == {"assets": "assets", "cables": "cables"}
        assert reg["tiles"]["max_zoom"] == TILE_MAX_ZOOM


class TestSchemas:

    def _point(self, lng=3.35, lat=6.6):
        return {"type": "Point", "coordinates": [lng, lat]}

    def test_valid_create(self):
        a = AssetCreate(asset_code="  FAT-0014 ", asset_type="FAT", geometry=self._point())
        assert a.asset_code == "FAT-0014"

    # A blank code is valid since Phase 2 — it is generated (test_network_catalogue.py)
    @pytest.mark.parametrize("payload", [
        {"asset_code": "X", "asset_type": "TOASTER"},
        {"asset_code": "X", "asset_type": "FAT", "lifecycle_status": "LIVE"},
        {"asset_code": "X", "asset_type": "FAT", "capacity": -1},
    ])
    def test_invalid_create(self, payload):
        with pytest.raises(ValidationError):
            AssetCreate(geometry=self._point(), **payload)

    @pytest.mark.parametrize("coords", [[0, 0], [181, 6], [3, 91], [float("nan"), 6], [3]])
    def test_invalid_coordinates(self, coords):
        with pytest.raises(ValidationError):
            AssetCreate(asset_code="X", asset_type="FAT", geometry={"type": "Point", "coordinates": coords})

    def test_update_tracks_only_sent_fields(self):
        u = AssetUpdate(name="New name")
        assert u.model_fields_set == {"name"}

    def test_update_rejects_unknown_lifecycle(self):
        with pytest.raises(ValidationError):
            AssetUpdate(lifecycle_status="LIVE")


class TestHelpers:

    def test_escape_like(self):
        assert escape_like("50%_a\\b") == "50\\%\\_a\\\\b"

    def test_parse_bbox(self):
        assert parse_bbox("3.3,6.5,3.4,6.7") == (3.3, 6.5, 3.4, 6.7)
        assert parse_bbox(None) is None

    @pytest.mark.parametrize("bbox", ["1,2,3", "a,b,c,d", "3.4,6.5,3.3,6.7", "0,0,200,1"])
    def test_parse_bbox_rejects(self, bbox):
        with pytest.raises(HTTPException) as exc:
            parse_bbox(bbox)
        assert exc.value.status_code == 422


class TestBackfillStatements:

    def test_every_statement_is_tenant_filterable(self):
        for stmt in BACKFILL_STATEMENTS:
            assert "CAST(:tid AS uuid)" in stmt

    def test_upserts_are_keyed_by_source(self):
        upserts = [s for s in BACKFILL_STATEMENTS if "INSERT INTO net_assets" in s]
        assert len(upserts) == 3
        for s in upserts:
            assert "ON CONFLICT (tenant_id, source_table, source_id)" in s
            assert "NOT s.is_deleted" in s


class TestMigrationChain:

    def test_0087_follows_0086(self):
        versions = pathlib.Path(__file__).parents[2] / "alembic" / "versions"
        files = list(versions.glob("0087_*.py"))
        assert len(files) == 1
        text = files[0].read_text(encoding="utf-8")
        assert re.search(r"^revision\s*=\s*'0087'", text, re.M)
        assert re.search(r"^down_revision\s*=\s*'0086'", text, re.M)
        # The legacy tables are left alone (decision D4, revised).
        for legacy in ("infrastructure_sites", "infrastructure_nodes", "infrastructure_routes"):
            assert legacy not in text.split('"""', 2)[2]
