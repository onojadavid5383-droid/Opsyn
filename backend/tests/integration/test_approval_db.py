# ============================================================
# OPSYN — tests/integration/test_approval_db.py
# Network GIS Phase 9 against real PostGIS: design and BOQ approval.
# Validation gate on submit; the submitted version frozen and the design
# locked; per-step permissions (design.review / design.approve) and "not
# your own submission"; reject → a new version to revise; approve → the
# approved version; BOQ only for an approved design, frozen at submission,
# revisions compared; the deployment gate needs both; comments, withdraw,
# reopen, notifications. Harness: NETWORK_GIS_DB_URL, rolled back.
# ============================================================

import json
import os
import types
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

if os.environ.get("NETWORK_GIS_DB_URL"):
    import main  # noqa: F401 — registers every ORM mapper

from app.core.context import tenant_id_ctx
from app.modules.approval import service as approval
from app.modules.design import operations, service
from app.modules.design.inputs import parse_input_file
from app.modules.design.schemas import DesignCreate

DB_URL = os.environ.get("NETWORK_GIS_DB_URL")
pytestmark = [
    pytest.mark.skipif(not DB_URL, reason="NETWORK_GIS_DB_URL not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
# check_permission() reads the request's tenant from this context variable. Set
# here, at import, so every test task inherits it (a fixture's own context isn't)
tenant_id_ctx.set(str(TENANT))
X0, Y0, D = 3.4500, 6.6900, 0.001


def fc(features):
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


ROADS = fc([{"type": "Feature", "properties": {"name": f"A Street {i}"},
             "geometry": {"type": "LineString", "coordinates": [[X0, Y0 + i * D], [X0 + 2 * D, Y0 + i * D]]}} for i in range(2)]
           + [{"type": "Feature", "properties": {"name": f"A Avenue {i}"},
               "geometry": {"type": "LineString", "coordinates": [[X0 + i * D, Y0], [X0 + i * D, Y0 + D]]}} for i in range(3)])
HP = fc([{"type": "Feature", "properties": {"customers": 1},
          "geometry": {"type": "Point", "coordinates": [X0 + 0.0003 + k * 0.0002, Y0 + 0.00008]}} for k in range(4)])


async def user(db, username):
    r = (await db.execute(text("""
        SELECT u.id, u.username, u.role_id, r.level, sp.department_id FROM users u JOIN roles r ON r.id = u.role_id
        LEFT JOIN staff_profiles sp ON sp.user_id = u.id WHERE u.username = :n
    """), {"n": username})).one()
    return types.SimpleNamespace(id=r.id, username=r.username, role_id=r.role_id, role=types.SimpleNamespace(level=r.level),
                                 staff_profile=types.SimpleNamespace(department_id=r.department_id) if r.department_id else None)


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def db():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def people(db):
    return {"engineer": await user(db, "manager.test"), "admin": await user(db, "david.onoja")}


async def build(db, name, who, *, fed=True):
    project = (await db.execute(text("SELECT id FROM projects WHERE tenant_id = :t LIMIT 1"), {"t": TENANT})).scalar_one()
    out = await service.create_design(db, TENANT, who, str(project), DesignCreate(name=name))
    d = await service.load_design(db, TENANT, out.id)
    for layer, data in (("road", ROADS), ("homepass", HP)):
        await service.save_inputs(db, TENANT, who, d, layer, f"{layer}.geojson", "replace", parse_input_file(layer, "x.geojson", data))
    await service.boundary_from_inputs(db, TENANT, who, out.id)
    op = lambda **b: operations.apply_operation(db, TENANT, who, d, b)  # noqa: E731
    fdt = (await op(op="ADD_ASSET", asset_type="FDT", lng=X0 + 0.0001, lat=Y0 - 0.00004))["operation"]["asset_id"]
    fat = (await op(op="ADD_ASSET", asset_type="FAT", lng=X0 + 0.0008, lat=Y0 + 0.00004))["operation"]["asset_id"]
    if fed:
        await op(op="DRAW_CABLE", cable_category="BOX_TO_BOX", **{"from": {"asset_id": fdt}, "to": {"asset_id": fat}})
    return await service.load_design(db, TENANT, out.id), fat


async def notes(db, uid):
    return (await db.execute(text("SELECT count(*) FROM notifications WHERE recipient_id = :u AND type = 'design_approval'"),
                             {"u": uid})).scalar_one()


S: dict = {}


async def test_errors_block_submission(db, people):
    d, fat = await build(db, "Approval — unfed", people["engineer"], fed=False)
    with pytest.raises(HTTPException) as exc:
        await approval.submit_design(db, TENANT, people["engineer"], d, None)
    assert exc.value.status_code == 422 and "1 error" in exc.value.detail
    assert d.status != "UNDER_REVIEW"


async def test_submit_freezes_and_locks(db, people):
    d, fat = await build(db, "Approval — Toyin", people["engineer"])
    S["design"], S["fat"] = d, fat
    before = await notes(db, people["admin"].id)
    r = await approval.submit_design(db, TENANT, people["engineer"], d, "Ready for review")
    S["req"] = r["id"]
    assert r["status"] == "PENDING" and r["pending_step"] == "ENGINEERING_REVIEW" and r["revision"] == 1
    assert [s["status"] for s in r["steps"]] == ["PENDING", "WAITING"]
    assert d.status == "UNDER_REVIEW"
    v = (await db.execute(text("SELECT snapshot IS NOT NULL AS frozen, label FROM design_versions WHERE id = :v"),
                          {"v": d.current_version_id})).one()
    assert v.frozen                                   # the reviewed state is kept exactly
    assert await notes(db, people["admin"].id) == before + 1                    # the reviewer was told
    with pytest.raises(HTTPException) as exc:                                    # locked while in review
        await operations.apply_operation(db, TENANT, people["engineer"], d, {"op": "ADD_ASSET", "asset_type": "FAT", "lng": X0, "lat": Y0})
    assert exc.value.status_code == 409


async def test_only_permitted_others_decide(db, people):
    with pytest.raises(HTTPException) as exc:                                    # no design.review grant
        await approval.decide(db, TENANT, people["engineer"], S["req"], "APPROVE", None)
    assert exc.value.status_code == 403 and "design.review" in exc.value.detail
    await db.execute(text("""
        INSERT INTO role_feature_overrides (tenant_id, role_id, feature_key, is_granted) VALUES (:t, :r, 'design.review', true)
        ON CONFLICT (tenant_id, role_id, feature_key) DO UPDATE SET is_granted = true
    """), {"t": TENANT, "r": people["engineer"].role_id})
    with pytest.raises(HTTPException) as exc:                                    # granted, but it's their own submission
        await approval.decide(db, TENANT, people["engineer"], S["req"], "APPROVE", None)
    assert exc.value.status_code == 403 and "someone else" in exc.value.detail


async def test_reject_sends_it_back_as_a_new_version(db, people):
    d = S["design"]
    reviewed = d.current_version_id
    with pytest.raises(HTTPException):
        await approval.decide(db, TENANT, people["admin"], S["req"], "REJECT", "  ")    # a reason is required
    r = await approval.decide(db, TENANT, people["admin"], S["req"], "REJECT", "Move the FAT nearer the homes")
    assert r["status"] == "REJECTED" and r["steps"][0]["comment"] == "Move the FAT nearer the homes"
    assert r["steps"][1]["status"] == "CANCELLED"
    d = await service.load_design(db, TENANT, d.id)
    assert d.status == "REJECTED" and d.current_version_id != reviewed
    assert await notes(db, people["engineer"].id) >= 1
    # Revise and resubmit: a new request for the new version
    await operations.apply_operation(db, TENANT, people["engineer"], d, {"op": "MOVE_ASSET", "id": S["fat"],
                                                                         "lng": X0 + 0.0006, "lat": Y0 + 0.00004})
    r2 = await approval.submit_design(db, TENANT, people["engineer"], d, "Moved it")
    assert r2["revision"] > r["revision"]
    S["req"] = r2["id"]


async def test_two_steps_to_approval(db, people):
    admin = people["admin"]
    engineer = people["engineer"]
    # A second design submitted by the admin: the engineer (design.review granted) can review it…
    other, _ = await build(db, "Approval — other", admin)
    ro = await approval.submit_design(db, TENANT, admin, other, None)
    ro = await approval.decide(db, TENANT, engineer, ro["id"], "APPROVE", "Looks right")
    assert ro["pending_step"] == "LINE_MANAGER_APPROVAL"
    with pytest.raises(HTTPException) as exc:                                    # …but not approve it
        await approval.decide(db, TENANT, engineer, ro["id"], "APPROVE", None)
    assert exc.value.status_code == 403 and "design.approve" in exc.value.detail

    r = await approval.decide(db, TENANT, admin, S["req"], "APPROVE", None)
    r = await approval.decide(db, TENANT, admin, S["req"], "APPROVE", "Approved")
    assert r["status"] == "APPROVED" and [s["status"] for s in r["steps"]] == ["APPROVED", "APPROVED"]
    d = await service.load_design(db, TENANT, S["design"].id)
    assert d.status == "APPROVED"
    g = await approval.gate(db, TENANT, d)
    assert g["design_approved"] and not g["boq_approved"] and not g["can_deploy"] and g["reasons"] == ["Its BOQ is not approved"]
    S["design"] = d


async def test_boq_frozen_revised_and_approved(db, people):
    d = S["design"]
    b1 = await approval.submit_boq(db, TENANT, people["engineer"], d, None)
    assert b1["subject_type"] == "BOQ" and b1["revision"] == 1
    q = {x["code"]: x["quantity"] for x in b1["payload"]["quantities"]}
    assert q["FAT"] == 1 and q["FDT"] == 1
    with pytest.raises(HTTPException):                                           # one open BOQ at a time
        await approval.submit_boq(db, TENANT, people["engineer"], d, None)
    await approval.decide(db, TENANT, people["admin"], b1["id"], "REJECT", "Add the drop cable quantities")
    b2 = await approval.submit_boq(db, TENANT, people["engineer"], d, "Resubmitted")
    assert b2["revision"] == 2
    diff = await approval.boq_diff(db, TENANT, b2["id"])
    assert diff["previous_revision"] == 1 and diff["changes"] == []              # nothing changed in between
    await approval.decide(db, TENANT, people["admin"], b2["id"], "APPROVE", None)
    await approval.decide(db, TENANT, people["admin"], b2["id"], "APPROVE", None)
    g = await approval.gate(db, TENANT, d)
    assert g["can_deploy"] and g["reasons"] == []
    with pytest.raises(HTTPException) as exc:
        await approval.submit_boq(db, TENANT, people["engineer"], d, None)
    assert exc.value.status_code == 409 and "approved" in exc.value.detail


async def test_comments(db, people):
    listing = await approval.list_for_design(db, TENANT, people["admin"], S["design"])
    rid = listing["requests"][0]["id"]
    r = await approval.add_comment(db, TENANT, people["admin"], rid, "Check this FAT's pole", S["fat"], None, None, None)
    c = r["comments"][-1]
    assert c["target_code"].startswith("FAT-") and c["lng"] is not None and c["author"]
    r = await approval.add_comment(db, TENANT, people["admin"], rid, "Road crossing here", None, None, X0 + 0.001, Y0)
    assert r["comments"][-1]["lat"] == pytest.approx(Y0)
    r = await approval.resolve_comment(db, TENANT, people["engineer"], c["id"], True)
    assert next(x for x in r["comments"] if x["id"] == c["id"])["resolved"]


async def test_withdraw_and_reopen(db, people):
    d, _ = await build(db, "Approval — withdrawn", people["engineer"])
    r = await approval.submit_design(db, TENANT, people["engineer"], d, None)
    with pytest.raises(HTTPException) as exc:
        await approval.withdraw(db, TENANT, people["admin"], r["id"])
    assert exc.value.status_code == 403
    r = await approval.withdraw(db, TENANT, people["engineer"], r["id"])
    assert r["status"] == "WITHDRAWN" and (await service.load_design(db, TENANT, d.id)).status == "MODIFIED"

    approved = S["design"]
    out = await approval.reopen(db, TENANT, people["engineer"], approved)
    assert out["status"] == "MODIFIED"
    g = await approval.gate(db, TENANT, await service.load_design(db, TENANT, approved.id))
    assert not g["can_deploy"]                                                   # the new version isn't approved
