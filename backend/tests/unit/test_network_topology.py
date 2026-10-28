# ============================================================
# OPSYN — tests/unit/test_network_topology.py
# Network GIS Phase 3 pure logic: derived-connection rules, trace SQL
# shape (direction, cycle guard, tenant, caps), utilisation states,
# TIA-598 fibre listing, schemas, catalogue additions and the 0089
# migration. The SQL behaviour itself runs against PostGIS in
# tests/integration/test_network_topology_db.py.
# ============================================================

import pathlib
import re
import types

import pytest
from pydantic import ValidationError

from app.modules.gis import tiles
from app.modules.network.asset_types import CONNECTION_TYPES, TIA_598_COLOURS
from app.modules.network.catalogue import build_catalogue
from app.modules.network.schemas import ConnectionCreate, FibreUpdate
from app.modules.network.topology import (
    DERIVED_RULES, DERIVED_SOURCES, SYNC_STATEMENTS, UTIL_BASIS, UTIL_USED,
    fibre_colour, fibres_for, shallowest, trace_sql, util_state,
)


class TestDerivedRules:

    def test_every_rule_names_the_columns_the_upsert_reads(self):
        for _table, sql in DERIVED_RULES:
            for col in ("source_asset_id", "dest_asset_id", "via_cable_id", "connection_type",
                        "lifecycle_status", "source_id"):
                assert col in sql, f"{_table} is missing {col}"

    def test_every_rule_is_tenant_filterable_and_live_only(self):
        for _table, sql in DERIVED_RULES:
            assert "CAST(:tid AS uuid)" in sql
            assert "deleted_at IS NULL" in sql and "design_id IS NULL" in sql

    def test_sources_are_what_the_ui_explains(self):
        assert DERIVED_SOURCES == ("net_cables", "attr:parent_splitter", "attr:cabinet", "attr:parent_fdt")

    def test_sync_upserts_then_retires_then_cleans_dead_endpoints(self):
        n = len(DERIVED_RULES)
        assert len(SYNC_STATEMENTS) == 2 * n + 1
        assert all("INSERT INTO net_connections" in s for s in SYNC_STATEMENTS[:n])
        assert all("UPDATE net_connections" in s for s in SYNC_STATEMENTS[n:])

    def test_second_level_splitters_are_not_also_fed_by_the_cabinet(self):
        cabinet = dict(DERIVED_RULES)["attr:cabinet"]
        assert "NOT x.attributes ? 'legacy_parent_splitter_asset_id'" in cabinet

    def test_uuid_attributes_are_cast_only_when_valid(self):
        for table in ("attr:parent_splitter", "attr:cabinet"):
            assert "~*" in dict(DERIVED_RULES)[table]


class TestTraceSql:

    @pytest.mark.parametrize("direction,join,nxt", [
        ("upstream", "c.dest_asset_id = w.asset_id", "c.source_asset_id"),
        ("downstream", "c.source_asset_id = w.asset_id", "c.dest_asset_id"),
    ])
    def test_direction(self, direction, join, nxt):
        sql = trace_sql(direction)
        assert join in sql
        assert f"NOT ({nxt} = ANY(w.path))" in sql      # cycle guard
        assert "w.depth < :max_depth" in sql and "LIMIT :cap" in sql
        assert "c.tenant_id = :tid" in sql and "a.tenant_id = :tid" in sql
        assert "c.design_id IS NULL" in sql

    def test_shallowest_keeps_first_visit(self):
        r = lambda aid, d: types.SimpleNamespace(asset_id=aid, depth=d)
        assert [x.depth for x in shallowest([r("a", 0), r("b", 1), r("b", 2), r("c", 2)])] == [0, 1, 2]


class TestUtilisation:

    @pytest.mark.parametrize("cap,used,expected", [
        (16, 4, (25.0, "ok")),
        (16, 12, (75.0, "warning")),
        (16, 15, (93.8, "critical")),
        (16, 16, (100.0, "critical")),
        (16, 17, (106.2, "full")),
        (None, 4, (None, "unknown")),
        (0, 0, (None, "unknown")),
        (16, None, (None, "unknown")),
    ])
    def test_states(self, cap, used, expected):
        assert util_state(cap, used) == expected

    def test_one_definition_serves_api_and_tiles(self):
        assert "{UTIL_USED}" not in tiles.TILE_SQL        # interpolated, not left as a placeholder
        assert UTIL_USED.strip() in tiles.TILE_SQL
        assert "net_connections" in tiles.REVISION_SQL    # a new link moves the tile revision

    def test_basis_covers_every_branch(self):
        for basis in ("ports", "fat_ports", "connections", "recorded", "none"):
            assert f"'{basis}'" in UTIL_BASIS


class TestFibres:

    def test_tia_598_order(self):
        assert [c for c, _ in TIA_598_COLOURS][:3] == ["Blue", "Orange", "Green"]
        assert fibre_colour(12)[0] == "Aqua" and fibre_colour(13)[0] == "Blue"

    def test_listing_by_tube(self):
        fibres = fibres_for(24, {13: {"status": "USED"}})
        assert len(fibres) == 24
        f13 = fibres[12]
        assert (f13["tube_no"], f13["position"], f13["colour"], f13["tube_colour"]) == (2, 1, "Blue", "Orange")
        assert f13["status"] == "USED" and f13["recorded"]
        assert fibres[0]["status"] == "FREE" and not fibres[0]["recorded"]

    def test_no_fibre_count_no_fibres(self):
        assert fibres_for(None, {}) == []


class TestSchemas:

    def test_connection_type_checked(self):
        assert ConnectionCreate(source_asset_id="a", dest_asset_id="b").connection_type == "FEED"
        with pytest.raises(ValidationError):
            ConnectionCreate(source_asset_id="a", dest_asset_id="b", connection_type="MAGIC")

    def test_fibre_status_checked(self):
        with pytest.raises(ValidationError):
            FibreUpdate(status="BROKEN")

    def test_catalogue_serves_topology_vocabulary(self):
        cat = build_catalogue()
        assert cat["connection_types"] == list(CONNECTION_TYPES)
        assert cat["utilisation_thresholds"] == {"warning": 70, "critical": 90}


class TestMigration:

    def test_0089_follows_0088_with_frozen_vocab(self):
        versions = pathlib.Path(__file__).parents[2] / "alembic" / "versions"
        text = next(versions.glob("0089_*.py")).read_text(encoding="utf-8")
        assert re.search(r"^down_revision\s*=\s*'0088'", text, re.M)
        assert "CONNECTION_TYPES = ('FEED', 'SPLIT', 'SPLICE', 'PATCH', 'DROP', 'UPLINK')" in text
        assert "FORCE ROW LEVEL SECURITY" in text
