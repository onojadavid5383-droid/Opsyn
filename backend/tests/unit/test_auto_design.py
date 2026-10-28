# ============================================================
# OPSYN — tests/unit/test_auto_design.py
# Network GIS Phase 5 pure logic: the golden output-adapter test (a fixture
# shaped exactly like the engine's stored output layers → expected
# working-set rows and FEED connections), run settings (aerial only,
# homepass field), engine findings, the 0091 migration and the DIRECT
# route method. The engine → database path: tests/integration/test_auto_design_db.py.
# ============================================================

import pathlib
import re

import pytest
from fastapi import HTTPException

from app.modules.design.adapters import adapt_engine_output
from app.modules.design.auto_design import engine_findings, input_poles, run_config
from app.modules.network.asset_types import ROUTE_METHODS


def pt(x, y):
    return {"type": "Point", "coordinates": [x, y]}


def line(*coords):
    return {"type": "LineString", "coordinates": [list(c) for c in coords]}


def fc(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def feat(geom, **props):
    return {"type": "Feature", "geometry": geom, "properties": props}


# Property names and value shapes copied from a real run (engine/pipeline.py
# _OUTPUT_LAYER_SCHEMAS, values as layer_to_geojson stores them)
ENGINE_OUTPUT = {
    "fdt": fc(feat(pt(3.3510, 6.5990), Name="FDT-01", fdt_code="FDT-01", fdt_serial="01", total_customers=16,
                   total_FAT=2, pon_count=1, closure_name="CLOSURE-0001", road_name="Toyin Street 2", structure_name="")),
    "fat": fc(
        feat(pt(3.3505, 6.5990), Name="FAT-01A-01", parent_fdt="FDT-01", wing="A", fat_sequence="01", total_customers=8,
             cascade_order=14447, splitter_type="1x9", road_name="Toyin Street 2", structure_name="NP-TS-004",
             allocation_type="native"),
        feat(pt(3.3500, 6.5990), Name="FAT-01A-02", parent_fdt="FDT-01", wing="A", fat_sequence="02", total_customers=9,
             splitter_type="1x8", road_name="Toyin Street 2", structure_name=""),
        feat(pt(3.3530, 6.5990), Name="FAT-09Z-01", parent_fdt="FDT-99", wing="A", fat_sequence="01", total_customers=2,
             splitter_type="", road_name=""),
    ),
    "closure": fc(feat(pt(3.3512, 6.5992), Name="CLOSURE-0001", road_name="Toyin Street 2", total_FDT=1,
                       feed_capacity=24, pickup_name="PICKUP_1")),
    "pole_output": fc(feat(pt(3.35050, 6.59900), Name="NP-TS-004", Tag="NP-TS-004", Original_Name="P-17"),
                      feat(pt(3.35200, 6.59900), Name="NP-TS-005", Tag="NP-TS-005", Original_Name="")),
    "b2b": fc(
        feat(line((3.3510, 6.5990), (3.3505, 6.5990)), name="B2B_FDT-01A_01", start_device="FDT-01",
             end_device="FAT-01A-01", cable_length=55.1, fdt_id="FDT-01", cable_arch="PCC", cable_type="box_to_box", wing="A"),
        feat(line((3.3505, 6.5990), (3.3500, 6.5990)), name="B2B_FDT-01A_02", start_device="FAT-01A-01",
             end_device="FAT-01A-02", fdt_id="FDT-01", cable_type="8core_road_run", wing="A"),
    ),
    "b2c": fc(
        feat(line((3.3505, 6.5990), (3.3506, 6.5991)), name="DROP_FAT-01A-01_C3", fat_name="FAT-01A-01", customer_id=3, cable_length=15.6),
        feat(line((3.3505, 6.5990), (3.3506, 6.5991)), name="DROP_FAT-01A-01_C3", fat_name="FAT-01A-01", customer_id=3, cable_length=15.6),
    ),
    "closure_cable": fc(feat(line((3.3512, 6.5992), (3.3510, 6.5990)), name="CLOSURE-0001-FDT-01", closure_name="CLOSURE-0001",
                             start_device="CLOSURE-0001", end_device="FDT-01", fdt_id="FDT-01", cable_capacity=24, cascade_group=0)),
    "feeder": fc(feat(line((3.3512, 6.5992), (3.3512, 6.5992)), name="PICKUP_1-CLOSURE-0001-24C", start_device="PICKUP_1",
                      end_device="CLOSURE-0001", cable_type="24C", length=0.0, total_core=6, active_core=3, redundant_core=3)),
    "boq": fc(), "pickup_point": fc(),
    "validation_results": fc(feat(None, severity="WARNING", category="B2B_LENGTH_EXCEPTION", message="2 cables exceed"),
                             feat(None, severity="ERROR", category="X", message="bad"), feat(None, severity="INFO", message="")),
}


@pytest.fixture(scope="module")
def adapted():
    return adapt_engine_output(ENGINE_OUTPUT, fdt_capacity=64, fat_ports=8, pon_architecture="single_pon", cascade="pcc",
                               input_poles=[(3.35050, 6.59900, "POLE-0017")])


class TestOutputAdapter:

    def test_devices(self, adapted):
        by = {a.key: a for a in adapted.assets}
        fdt = by[("FDT", "FDT-01")]
        assert (fdt.capacity, fdt.used_capacity, fdt.lng, fdt.lat) == (64, 16, 3.3510, 6.5990)
        assert fdt.attributes == {"pon_architecture": "SINGLE", "pon_count": 1, "closure_name": "CLOSURE-0001",
                                  "road_name": "Toyin Street 2", "fdt_serial": "01"}
        fat = by[("FAT", "FAT-01A-01")]
        assert (fat.capacity, fat.used_capacity) == (8, 8)
        # the keys hydrator.py reads back
        assert fat.attributes["parent_fdt_code"] == "FDT-01" and fat.attributes["wing"] == "A"
        assert fat.attributes["sequence"] == 1 and fat.attributes["engine_splitter_type"] == "1x9"
        assert "splitter_ratio" not in fat.attributes                  # 1:9 isn't a catalogue ratio
        assert fat.attributes["mount"] == "POLE" and fat.attributes["structure_name"] == "NP-TS-004"
        assert by[("FAT", "FAT-01A-02")].attributes["splitter_ratio"] == "1:8"
        assert by[("CLOSURE", "CLOSURE-0001")].capacity == 24

    def test_each_fat_gets_its_splitter(self, adapted):
        spl = {a.key: a for a in adapted.assets if a.asset_type == "SPLITTER"}
        assert set(spl) == {("SPLITTER", "FAT-01A-01-SPL"), ("SPLITTER", "FAT-01A-02-SPL")}      # none for no ratio
        s = spl[("SPLITTER", "FAT-01A-01-SPL")]
        assert s.parent == ("FAT", "FAT-01A-01")
        assert s.attributes == {"input_ports": 1, "output_ports": 9, "splitter_level": "Second-Level", "splitter_type": "PCC",
                                "number_customer": 8, "engine_splitter_type": "1x9"}
        assert spl[("SPLITTER", "FAT-01A-02-SPL")].attributes["split_ratio"] == "1:8"

    def test_poles_existing_by_position(self, adapted):
        poles = {a.asset_code: a.attributes for a in adapted.assets if a.asset_type == "POLE"}
        assert poles["NP-TS-004"] == {"existing": True, "live_asset_code": "POLE-0017", "original_name": "P-17"}
        assert poles["NP-TS-005"] == {"existing": False}

    def test_feed_connections(self, adapted):
        assert set(adapted.links) == {(("FDT", "FDT-01"), ("FAT", "FAT-01A-01")), (("FDT", "FDT-01"), ("FAT", "FAT-01A-02")),
                                      (("CLOSURE", "CLOSURE-0001"), ("FDT", "FDT-01"))}
        assert any("FAT-09Z-01 names FDT FDT-99" in w for w in adapted.warnings)

    def test_cables(self, adapted):
        by = {c.asset_code: c for c in adapted.cables}
        b1 = by["B2B_FDT-01A_01"]
        assert (b1.cable_category, b1.route_method, b1.fiber_count) == ("BOX_TO_BOX", "ROAD_GRAPH", None)
        assert (b1.source, b1.dest) == (("FDT", "FDT-01"), ("FAT", "FAT-01A-01"))
        assert by["B2B_FDT-01A_02"].fiber_count == 8                    # "8core_road_run"
        cc = by["CLOSURE-0001-FDT-01"]
        assert (cc.cable_category, cc.fiber_count, cc.source, cc.dest) == ("CLOSURE_FDT", 24, ("CLOSURE", "CLOSURE-0001"), ("FDT", "FDT-01"))

    def test_drops_run_direct_and_get_unique_codes(self, adapted):
        drops = [c for c in adapted.cables if c.cable_category == "DROP"]
        assert [d.asset_code for d in drops] == ["DROP_FAT-01A-01_C3", "DROP_FAT-01A-01_C3-2"]
        assert all(d.route_method == "DIRECT" and d.source == ("FAT", "FAT-01A-01") and d.dest is None for d in drops)
        assert drops[0].attributes == {"customer_id": 3}

    def test_zero_length_feeder_is_reported_not_drawn(self, adapted):
        assert not [c for c in adapted.cables if c.cable_category == "FEEDER"]
        assert any("PICKUP_1-CLOSURE-0001-24C has no length" in w for w in adapted.warnings)

    def test_counts(self, adapted):
        assert adapted.counts() == {"FDT": 1, "FAT": 3, "SPLITTER": 2, "CLOSURE": 1, "POLE": 2,
                                    "BOX_TO_BOX": 2, "DROP": 2, "CLOSURE_FDT": 1}

    def test_duplicate_devices_keep_the_first(self):
        out = adapt_engine_output({"fdt": fc(feat(pt(1, 1), Name="F"), feat(pt(2, 2), Name="F"))}, fdt_capacity=64,
                                  fat_ports=8, pon_architecture="dual_pon", cascade="pcc")
        assert len(out.assets) == 1 and out.assets[0].lng == 1 and out.assets[0].attributes["pon_architecture"] == "DUAL"
        assert "appears twice" in out.warnings[0]


class TestRunSettings:

    def test_homepass_field_is_always_the_design_one(self):
        assert run_config({"homepass_field_name": "HP", "coverage_pct": 80})["homepass_field_name"] == "customers"
        assert run_config({}, {"pon_architecture": "dual_pon"})["pon_architecture"] == "dual_pon"

    def test_only_aerial_can_run(self):
        with pytest.raises(HTTPException) as exc:
            run_config({"deployment_type": "underground"})
        assert exc.value.status_code == 422 and "aerial" in exc.value.detail.lower()
        with pytest.raises(HTTPException):
            run_config({"not_a_setting": 1})

    def test_input_poles_carry_live_codes(self):
        poles = input_poles(fc(feat(pt(1, 2), Name="P1"), feat(pt(3, 4), Name="POLE-9", live_asset_code="POLE-9")))
        assert poles == [(1.0, 2.0, None), (3.0, 4.0, "POLE-9")]

    def test_engine_findings_errors_first_blank_dropped(self):
        rows = engine_findings(ENGINE_OUTPUT)
        assert [r["severity"] for r in rows] == ["ERROR", "WARNING"]
        assert rows[1] == {"severity": "WARNING", "category": "B2B_LENGTH_EXCEPTION", "message": "2 cables exceed"}


class TestSchema:

    def test_direct_route_method(self):
        assert "DIRECT" in ROUTE_METHODS

    def test_0091_follows_0090(self):
        versions = pathlib.Path(__file__).parents[2] / "alembic" / "versions"
        text = next(versions.glob("0091_*.py")).read_text(encoding="utf-8")
        assert re.search(r"^down_revision\s*=\s*'0090'", text, re.M)
        assert "design_id" in text and "design_version_id" in text and "'DIRECT'" in text


class TestWorker:

    def test_the_worker_resolves_the_run_foreign_keys(self):
        """The Celery worker imports only the task modules (not main.py); the
        run's design_id FK must still resolve there, or every task dies on load."""
        import subprocess
        import sys
        code = ("import importlib\nfrom app.core.celery_app import celery_app\n"
                "for m in celery_app.conf.include: importlib.import_module(m)\n"
                "from app.modules.fttx_designer.models import FttxDesignRun\n"
                "print(sorted(fk.column.table.name for fk in FttxDesignRun.__table__.foreign_keys))")
        backend = pathlib.Path(__file__).parents[2]
        out = subprocess.run([sys.executable, "-c", code], cwd=backend, capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr[-600:]
        assert "designs" in out.stdout and "design_versions" in out.stdout
