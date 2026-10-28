# ============================================================
# OPSYN DEPLOYMENT — app/modules/deployment/service.py
# Network GIS Phase 10: from an approved design to the network in service.
#
#   deploy     only through the approval gate (design version AND its BOQ
#              approved, Phase 9): every row APPROVED → CONSTRUCTION, the
#              designed geometry kept in design_geom, a deployments record
#   progress   the field moves each device / cable along the lifecycle:
#                install  CONSTRUCTION → INSTALLED
#                test     INSTALLED → TESTING
#                verify   … → VERIFIED (through TESTING)
#                fail     TESTING → INSTALLED (failed test: rework; a note
#                         is required)
#              each step is a legal lifecycle transition (network/
#              lifecycle.py) and lands in the audit trail with its actor
#   as-built   where it was really installed: asbuilt_geom, which also
#              becomes geom (map, lengths); the variance report compares
#              it with design_geom (cable length, device displacement)
#   roll-ups   per state, FATs installed x / y, cable m installed / planned,
#              % verified, per FDT
#   promote    once everything is VERIFIED and no code clashes with the
#              live network: VERIFIED → ACTIVE and design_id → NULL on the
#              SAME rows (lineage_id keeps the design) — nothing is copied;
#              the live topology re-derives; the design becomes DEPLOYED
#              and the version it deployed is frozen first
# ============================================================

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approval.service import gate, holders, _notify
from app.modules.design import audit, versions
from app.modules.design.models import Design
from app.modules.network.lifecycle import can_transition

CHAIN = ("CONSTRUCTION", "INSTALLED", "TESTING", "VERIFIED")
INSTALLED = ("INSTALLED", "TESTING", "VERIFIED")
TABLE = {"asset": "net_assets", "cable": "net_cables"}
ACTIONS = {
    "install": ("INSTALLED",),
    "test": ("TESTING",),
    "verify": ("TESTING", "VERIFIED"),          # from INSTALLED it passes through TESTING
    "fail": ("INSTALLED",),
}


def _bad(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg)


async def open_deployment(db: AsyncSession, design_id: uuid.UUID) -> Any:
    return (await db.execute(text("SELECT * FROM deployments WHERE design_id = :d ORDER BY started_at DESC LIMIT 1"),
                             {"d": design_id})).first()


async def _require_open(db: AsyncSession, design: Design) -> Any:
    dep = await open_deployment(db, design.id)
    if dep is None or dep.status != "IN_PROGRESS":
        raise _bad("This design is not being deployed", status.HTTP_409_CONFLICT)
    return dep


# ── Deploy ───────────────────────────────────────────────────

async def deploy(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design, note: str | None) -> dict[str, Any]:
    g = await gate(db, tid, design)
    if not g["can_deploy"]:
        raise _bad("Not ready to deploy: " + "; ".join(g["reasons"]), status.HTTP_409_CONFLICT)
    dep = await open_deployment(db, design.id)
    if dep is not None and dep.status == "IN_PROGRESS":
        raise _bad("This design is already being deployed", status.HTTP_409_CONFLICT)
    await audit.bulk(db)
    for t in ("net_assets", "net_cables"):
        await db.execute(text(f"""
            UPDATE {t} SET lifecycle_status = 'CONSTRUCTION', design_geom = geom, updated_at = now()
            WHERE design_id = :d AND deleted_at IS NULL AND lifecycle_status = 'APPROVED'
        """), {"d": design.id})
    await db.execute(text("""
        UPDATE net_connections SET lifecycle_status = 'CONSTRUCTION' WHERE design_id = :d AND lifecycle_status = 'APPROVED'
    """), {"d": design.id})
    await audit.bulk(db, on=False)
    await db.execute(text("""
        INSERT INTO deployments (tenant_id, design_id, version_id, note, started_by) VALUES (:tid, :d, :v, :n, :by)
    """), {"tid": tid, "d": design.id, "v": design.current_version_id, "n": (note or "").strip() or None, "by": caller.id})
    await audit.summary(db, tid, design.id, "deployment_started", caller, None,
                        {"version_no": (await versions.current(db, design)).version_no, "note": note})
    await _notify(db, tid, await holders(db, tid, "deployment.update"), f"Deployment started: {design.name}",
                  f"{design.name} is approved and handed to the field for construction.", design, caller)
    return await progress(db, tid, design)


# ── Progress and roll-ups ────────────────────────────────────

async def progress(db: AsyncSession, tid: uuid.UUID, design: Design) -> dict[str, Any]:
    dep = await open_deployment(db, design.id)
    p = {"d": design.id}
    by_state = (await db.execute(text("""
        SELECT 'asset' AS kind, asset_type AS sub, lifecycle_status AS state, count(*) AS n, 0::float8 AS m
        FROM net_assets WHERE design_id = :d AND deleted_at IS NULL AND parent_id IS NULL GROUP BY 1, 2, 3
        UNION ALL
        SELECT 'cable', cable_category, lifecycle_status, count(*), coalesce(sum(length_m), 0)::float8
        FROM net_cables WHERE design_id = :d AND deleted_at IS NULL GROUP BY 1, 2, 3
    """), p)).all()
    items = sum(r.n for r in by_state)
    installed = sum(r.n for r in by_state if r.state in INSTALLED)
    verified = sum(r.n for r in by_state if r.state == "VERIFIED")
    fats = [r for r in by_state if r.kind == "asset" and r.sub == "FAT"]
    cable_planned = round(sum(r.m for r in by_state if r.kind == "cable"), 1)
    cable_installed = round(sum(r.m for r in by_state if r.kind == "cable" and r.state in INSTALLED), 1)
    states: dict[str, int] = {}
    for r in by_state:
        states[r.state] = states.get(r.state, 0) + int(r.n)

    per_fdt = [dict(r._mapping) for r in (await db.execute(text("""
        SELECT f.asset_code AS fdt, f.lifecycle_status AS state,
               count(a.id) AS fats,
               count(a.id) FILTER (WHERE a.lifecycle_status IN ('INSTALLED', 'TESTING', 'VERIFIED')) AS installed,
               count(a.id) FILTER (WHERE a.lifecycle_status = 'VERIFIED') AS verified
        FROM net_assets f
        LEFT JOIN net_assets a ON a.design_id = f.design_id AND a.asset_type = 'FAT' AND a.deleted_at IS NULL
             AND (lower(a.attributes->>'parent_fdt_code') = lower(f.asset_code)
                  OR EXISTS (SELECT 1 FROM net_connections k WHERE k.source_asset_id = f.id AND k.dest_asset_id = a.id))
        WHERE f.design_id = :d AND f.asset_type = 'FDT' AND f.deleted_at IS NULL
        GROUP BY f.asset_code, f.lifecycle_status ORDER BY f.asset_code
    """), p)).all()]

    variance = [dict(r._mapping) for r in (await db.execute(text("""
        SELECT 'cable' AS kind, id::text AS id, asset_code AS code,
               round(ST_Length(design_geom::geography)::numeric, 1)::float8 AS design_m,
               round(ST_Length(asbuilt_geom::geography)::numeric, 1)::float8 AS asbuilt_m,
               NULL::float8 AS moved_m
        FROM net_cables WHERE design_id = :d AND asbuilt_geom IS NOT NULL AND design_geom IS NOT NULL
        UNION ALL
        SELECT 'asset', id::text, asset_code, NULL, NULL,
               round(ST_Distance(design_geom::geography, asbuilt_geom::geography)::numeric, 1)::float8
        FROM net_assets WHERE design_id = :d AND asbuilt_geom IS NOT NULL AND design_geom IS NOT NULL
        ORDER BY 1, 3
    """), p)).all()]
    for v in variance:
        if v["kind"] == "cable" and v["design_m"]:
            v["difference_m"] = round(v["asbuilt_m"] - v["design_m"], 1)
            v["difference_pct"] = round(100 * (v["asbuilt_m"] - v["design_m"]) / v["design_m"], 1)

    blocking = items - verified
    return {
        "deployment": {"status": dep.status, "started_at": dep.started_at.isoformat(), "note": dep.note,
                       "promoted_at": dep.promoted_at.isoformat() if dep.promoted_at else None,
                       "summary": dep.summary} if dep else None,
        "gate": await gate(db, tid, design),
        "items": items, "states": states,
        "installed": installed, "verified": verified,
        "installed_pct": round(100 * installed / items, 1) if items else 0.0,
        "verified_pct": round(100 * verified / items, 1) if items else 0.0,
        "fats": {"total": sum(r.n for r in fats), "installed": sum(r.n for r in fats if r.state in INSTALLED),
                 "verified": sum(r.n for r in fats if r.state == "VERIFIED")},
        "cable_m": {"planned": cable_planned, "installed": cable_installed},
        "per_fdt": per_fdt, "variance": variance,
        "ready_to_promote": bool(dep and dep.status == "IN_PROGRESS" and items and blocking == 0),
        "not_verified": blocking,
    }


# ── Field updates ────────────────────────────────────────────

async def advance(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design, items: list[dict[str, str]],
                  action: str, note: str | None) -> dict[str, Any]:
    await _require_open(db, design)
    if action not in ACTIONS:
        raise _bad(f"action must be one of {', '.join(ACTIONS)}")
    note = (note or "").strip() or None
    if action == "fail" and not note:
        raise _bad("Say what failed")
    if not items:
        raise _bad("Choose what to update")
    done, refused = [], []
    for it in items:
        kind = it.get("kind")
        if kind not in TABLE:
            raise _bad("Each item needs kind asset or cable")
        try:
            rid = uuid.UUID(str(it.get("id")))
        except ValueError:
            raise _bad("An item id is not valid") from None
        row = (await db.execute(text(f"""
            SELECT id, asset_code, lifecycle_status FROM {TABLE[kind]} WHERE id = :id AND design_id = :d AND deleted_at IS NULL
        """), {"id": rid, "d": design.id})).first()
        if row is None:
            raise _bad("That is not part of this deployment", status.HTTP_404_NOT_FOUND)
        state, path = row.lifecycle_status, list(ACTIONS[action])
        if action == "verify" and state == "TESTING":
            path = ["VERIFIED"]
        if action == "fail" and state != "TESTING":
            refused.append({"code": row.asset_code, "state": state, "reason": "Only something being tested can fail its test"})
            continue
        ok, cur = True, state
        for nxt in path:
            if not can_transition(cur, nxt):
                ok = False
                break
            cur = nxt
        if not ok:
            refused.append({"code": row.asset_code, "state": state,
                            "reason": f"{state.title()} can't be {'verified' if action == 'verify' else action + 'ed'} yet"})
            continue
        for nxt in path:                     # one audit entry per step, with the actor
            extra = ", attributes = attributes || jsonb_build_object('field_note', CAST(:note AS text))" if note else ""
            await db.execute(text(f"UPDATE {TABLE[kind]} SET lifecycle_status = :s, updated_at = now(){extra} WHERE id = :id"),
                             {"s": nxt, "id": rid, **({"note": note} if note else {})})
        done.append({"code": row.asset_code, "from": state, "to": path[-1]})
    return {"changed": done, "refused": refused, "progress": await progress(db, tid, design)}


async def capture_asbuilt(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design, kind: str, item_id: str,
                          geometry: dict[str, Any]) -> dict[str, Any]:
    await _require_open(db, design)
    if kind not in TABLE:
        raise _bad("kind must be asset or cable")
    want = "Point" if kind == "asset" else "LineString"
    if not isinstance(geometry, dict) or geometry.get("type") != want:
        raise _bad(f"An as-built {kind} is a {want}")
    coords = geometry.get("coordinates") or []
    if kind == "cable" and len({tuple(c[:2]) for c in coords}) < 2:
        raise _bad("An as-built cable needs at least two different points")
    rid = uuid.UUID(item_id)
    row = (await db.execute(text(f"SELECT asset_code, lifecycle_status FROM {TABLE[kind]} WHERE id = :id AND design_id = :d"),
                            {"id": rid, "d": design.id})).first()
    if row is None:
        raise _bad("That is not part of this deployment", status.HTTP_404_NOT_FOUND)
    if row.lifecycle_status == "CONSTRUCTION":
        raise _bad(f"{row.asset_code} isn't installed yet; record where it went once it is", status.HTTP_409_CONFLICT)
    route = ", route_method = 'IMPORTED'" if kind == "cable" else ""      # surveyed, as-built plant
    await db.execute(text(f"""
        UPDATE {TABLE[kind]} SET asbuilt_geom = ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326),
               geom = ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326), updated_at = now(){route}
        WHERE id = :id
    """), {"g": json.dumps(geometry), "id": rid})
    return await progress(db, tid, design)


# ── Promote ──────────────────────────────────────────────────

async def promote(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design) -> dict[str, Any]:
    from app.modules.network.topology import sync_derived_connections
    dep = await _require_open(db, design)
    not_verified = (await db.execute(text("""
        SELECT (SELECT count(*) FROM net_assets WHERE design_id = :d AND deleted_at IS NULL AND lifecycle_status <> 'VERIFIED')
             + (SELECT count(*) FROM net_cables WHERE design_id = :d AND deleted_at IS NULL AND lifecycle_status <> 'VERIFIED')
    """), {"d": design.id})).scalar_one()
    if not_verified:
        raise _bad(f"{not_verified} devices and cables are not verified yet", status.HTTP_409_CONFLICT)
    clashes = list((await db.execute(text("""
        SELECT a.asset_code FROM net_assets a JOIN net_assets l ON l.tenant_id = a.tenant_id AND l.asset_type = a.asset_type
             AND l.asset_code = a.asset_code AND l.design_id IS NULL AND l.deleted_at IS NULL
        WHERE a.design_id = :d AND a.deleted_at IS NULL
        UNION
        SELECT c.asset_code FROM net_cables c JOIN net_cables l ON l.tenant_id = c.tenant_id
             AND l.asset_code = c.asset_code AND l.design_id IS NULL AND l.deleted_at IS NULL
        WHERE c.design_id = :d AND c.deleted_at IS NULL
        ORDER BY 1 LIMIT 20
    """), {"d": design.id})).scalars())
    if clashes:
        raise _bad(f"These codes are already used in the live network; rename them first: {', '.join(clashes)}",
                   status.HTTP_409_CONFLICT)

    # The as-built state stays in the design's history: a version of its own
    # after the approved one (which was frozen when it was submitted)
    approved = await versions.current(db, design)
    await versions.start(db, tid, design, "MANUAL", None, approved, caller)
    v = await versions.freeze(db, design, "As built: promoted to the live network")
    counts = (await db.execute(text("""
        SELECT (SELECT count(*) FROM net_assets WHERE design_id = :d AND deleted_at IS NULL) AS assets,
               (SELECT count(*) FROM net_cables WHERE design_id = :d AND deleted_at IS NULL) AS cables,
               (SELECT coalesce(sum(length_m), 0)::float8 FROM net_cables WHERE design_id = :d AND deleted_at IS NULL) AS cable_m
    """), {"d": design.id})).one()
    # The same rows become live: lifecycle ACTIVE, no design, lineage kept (one audit row each: "promote")
    for t in ("net_assets", "net_cables"):
        await db.execute(text(f"""
            UPDATE {t} SET lifecycle_status = 'ACTIVE', lineage_id = design_id, design_id = NULL, updated_at = now()
            WHERE design_id = :d AND deleted_at IS NULL
        """), {"d": design.id})
    await db.execute(text("""
        UPDATE net_connections SET lifecycle_status = 'ACTIVE', design_id = NULL, updated_at = now() WHERE design_id = :d
    """), {"d": design.id})
    await sync_derived_connections(db, tid)
    summary = {"assets": counts.assets, "cables": counts.cables, "cable_m": round(counts.cable_m, 1),
               "version_no": v.version_no}
    await db.execute(text("""
        UPDATE deployments SET status = 'PROMOTED', promoted_by = :by, promoted_at = clock_timestamp(),
               summary = CAST(:s AS jsonb) WHERE id = :id
    """), {"by": caller.id, "s": json.dumps(summary), "id": dep.id})
    design.status = "DEPLOYED"
    design.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.flush()
    await audit.summary(db, tid, design.id, "promoted", caller, None, summary)
    await _notify(db, tid, await holders(db, tid, "network.view"), f"In service: {design.name}",
                  f"{counts.assets} devices and {round(counts.cable_m / 1000, 2)} km of cable from {design.name} are now live.",
                  design, caller)
    return {"promoted": summary, "design_status": design.status}
