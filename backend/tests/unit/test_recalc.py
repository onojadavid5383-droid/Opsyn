# ============================================================
# OPSYN — tests/unit/test_recalc.py
# Network GIS Phase 7 pure logic: the BOQ and validation deltas an edit's
# answer carries. The recalculation itself (re-routing on real roads):
# tests/integration/test_recalc_db.py.
# ============================================================

from app.modules.design.recalc import boq_delta, validation_delta


def q(item, code, quantity, unit="m", group="Cable"):
    return {"group": group, "item": item, "code": code, "quantity": quantity, "unit": unit}


def test_boq_delta_lists_only_changed_lines():
    before = {"Cable|B2B": q("B2B", "BOX_TO_BOX", 100.0), "Devices|FAT": q("FAT", "FAT", 2, "each", "Devices"),
              "Cable|Drop": q("Drop", "DROP", 40.04)}
    after = {"Cable|B2B": q("B2B", "BOX_TO_BOX", 212.5), "Devices|FAT": q("FAT", "FAT", 2, "each", "Devices"),
             "Cable|Drop": q("Drop", "DROP", 40.0), "Devices|Closure": q("Closure", "CLOSURE", 1, "each", "Devices")}
    out = {d["code"]: d for d in boq_delta(before, after)}
    assert set(out) == {"BOX_TO_BOX", "CLOSURE"}                   # a 0.04 m wobble is not a change
    assert out["BOX_TO_BOX"] == {"item": "B2B", "code": "BOX_TO_BOX", "unit": "m", "group": "Cable",
                                 "before": 100.0, "after": 212.5, "change": 112.5}
    assert out["CLOSURE"]["before"] == 0 and out["CLOSURE"]["change"] == 1


def test_boq_delta_for_a_removed_line():
    assert boq_delta({"Devices|FAT": q("FAT", "FAT", 1, "each", "Devices")}, {})[0]["change"] == -1


def test_validation_delta_new_and_resolved():
    issue = lambda code, a=None, c=None: {"severity": "ERROR", "code": code, "message": f"{code} msg", "asset_id": a, "cable_id": c}
    before = {("FAT_NOT_FED", "a1", None): issue("FAT_NOT_FED", "a1")}
    after = {("DROP_TOO_LONG", None, "c1"): issue("DROP_TOO_LONG", c="c1")}
    d = validation_delta(before, after)
    assert [i["code"] for i in d["new"]] == ["DROP_TOO_LONG"] and [i["code"] for i in d["resolved"]] == ["FAT_NOT_FED"]
    assert d["new"][0] == {"severity": "ERROR", "code": "DROP_TOO_LONG", "message": "DROP_TOO_LONG msg"}
