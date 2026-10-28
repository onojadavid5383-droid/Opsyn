# ============================================================
# OPSYN AUTO DESIGN — app/modules/design/auto_design.py
# Network GIS Phase 5, Track A (plan §3.5, §3.6). Independent of manual
# design (Phase 6): both only share the Phase 4 container and services.
#
#   generate  design inputs (+ boundary, + live poles inside it)
#             → an fttx_design_runs row (design_id set) → the EXISTING
#             Celery task (app/tasks/fttx_design_run.py) runs the engine →
#             apply_output(): the old working set is snapshotted onto the
#             current version, replaced by the engine's output as a NEW
#             version (creation_method AUTO), BOQ + optical kept on that
#             version, validation re-run. Nothing is lost: the previous
#             state stays restorable (Phase 8).
#   import    the same apply_output() from a completed standalone run
#             ("Import existing run as design"), creation_method IMPORTED;
#             the run's inputs are copied for any layer the design lacks and
#             its settings become the design's.
#
# Input adapter rules:
#   roads        every road within 100 m of the boundary (routing needs the
#                network just outside it too)
#   homepasses   inside the boundary only (the rest are reported, not sent)
#   poles        design poles + existing structures + live POLE assets,
#                within 30 m of the boundary (or the roads' outline when no
#                boundary is drawn); one per spot
#   buildings, pickups   within 30 m of the boundary
# Aerial only: the web engine has no other deployment strategy yet, so
# anything else is refused before a run is queued.
# ============================================================

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.design import validation_service
from app.modules.design.adapters import LIFECYCLE, Adapted, adapt_engine_output
from app.modules.design.engine_bridge import HOMEPASS_COUNT_FIELD, _explode_multilines
from app.modules.design.inputs import parse_input_file
from app.modules.design.models import LOCKED_STATUSES, Design, DesignVersion
from app.modules.fttx_designer.config_io import InvalidFttxConfigError, config_from_dict
from app.modules.fttx_designer.engine.config import MAX_CUSTOMERS_PER_FAT, DeploymentType, get_capacity_profile
from app.modules.fttx_designer.models import FttxDesignRun, FttxDesignRunLayer, FttxDesignRunOutput
from app.modules.infrastructure.audit_service import write_audit_entry
from app.modules.network.lifecycle import LIVE_STATES

ACTIVE_RUN_STATES = ("queued", "running", "cancelling")
ROAD_REACH_M = 100
AREA_REACH_M = 30


NOUNS = {"road": ("road", "roads"), "homepass": ("homepass", "homepasses"), "pole": ("pole", "poles"),
         "building": ("building", "buildings"), "pickup": ("pickup point", "pickup points"),
         "existing_structure": ("existing structure", "existing structures")}


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


class DesignLocked(Exception):
    """The design moved into review (or later) while a run was in flight."""


async def set_tenant(db: AsyncSession, tid: uuid.UUID) -> None:
    """RLS scope for this transaction (the Celery task has no request context)."""
    await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})


# ── Settings ─────────────────────────────────────────────────

def run_config(base: dict[str, Any] | None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """The design's engine settings as a run config. Refuses what can't run."""
    cfg = {**(base or {}), **(overrides or {}), "homepass_field_name": HOMEPASS_COUNT_FIELD}
    try:
        parsed = config_from_dict(cfg)
    except InvalidFttxConfigError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if parsed.deployment_type != DeploymentType.AERIAL:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Only aerial deployment can be designed automatically so far; "
                            "choose Aerial or design this area by hand.")
    return cfg


# ── Input adapter ────────────────────────────────────────────

async def build_run_inputs(db: AsyncSession, tid: uuid.UUID, design: Design) -> tuple[dict[str, Any], list[str]]:
    """The design's inputs as the engine's input FeatureCollections, plus notes."""
    rows = (await db.execute(text(f"""
        SELECT i.layer_key, ST_AsGeoJSON(i.geom, 7) AS g, i.properties,
               CASE
                 WHEN d.boundary IS NULL THEN true
                 WHEN i.layer_key = 'road' THEN ST_DWithin(i.geom::geography, d.boundary::geography, {ROAD_REACH_M})
                 WHEN i.layer_key = 'homepass' THEN ST_Intersects(i.geom, d.boundary)
                 ELSE ST_DWithin(i.geom::geography, d.boundary::geography, {AREA_REACH_M})
               END AS inside
        FROM design_inputs i JOIN designs d ON d.id = i.design_id
        WHERE i.design_id = :d AND i.tenant_id = :tid
        ORDER BY i.layer_key, i.created_at, i.id
    """), {"d": design.id, "tid": tid})).all()

    fcs: dict[str, list[dict[str, Any]]] = {}
    left_out: dict[str, int] = {}
    for r in rows:
        if not r.inside:
            left_out[r.layer_key] = left_out.get(r.layer_key, 0) + 1
            continue
        key = "pole" if r.layer_key == "existing_structure" else r.layer_key
        props = dict(r.properties or {})
        if key == "pole":
            props.setdefault("Name", props.get("name") or props.get("Name") or "")
        fcs.setdefault(key, []).append({"type": "Feature", "geometry": json.loads(r.g), "properties": props})

    notes = [f"{_count(n, *NOUNS[k])} outside the boundary {'was' if n == 1 else 'were'} left out"
             for k, n in sorted(left_out.items())]
    if not fcs.get("road"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Upload the design's roads first: every cable is routed along them.")
    if not fcs.get("homepass"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Upload the homepasses to design for, inside the boundary.")

    # Live poles in the area become existing structures for the engine
    live = (await db.execute(text(f"""
        WITH area AS (
            SELECT coalesce(d.boundary,
                            (SELECT ST_ConvexHull(ST_Collect(geom)) FROM design_inputs
                             WHERE design_id = d.id AND layer_key = 'road')) AS g
            FROM designs d WHERE d.id = :d
        )
        SELECT a.asset_code, ST_X(a.geom) AS lng, ST_Y(a.geom) AS lat
        FROM net_assets a, area
        WHERE a.tenant_id = :tid AND a.design_id IS NULL AND a.deleted_at IS NULL
          AND a.asset_type = 'POLE' AND a.lifecycle_status = ANY(:live)
          AND ST_DWithin(a.geom::geography, area.g::geography, {AREA_REACH_M})
        ORDER BY a.asset_code
    """), {"d": design.id, "tid": tid, "live": list(LIVE_STATES)})).all()
    poles = fcs.setdefault("pole", [])
    taken = [tuple(f["geometry"]["coordinates"][:2]) for f in poles]
    added = 0
    for p in live:
        if any(abs(p.lng - x) < 1e-5 and abs(p.lat - y) < 1e-5 for x, y in taken):
            continue
        poles.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p.lng, p.lat]},
                      "properties": {"Name": p.asset_code, "live_asset_code": p.asset_code}})
        added += 1
    if added:
        notes.append(f"{_count(added, 'pole', 'poles')} already in the network {'was' if added == 1 else 'were'} "
                     "offered to the engine as existing structures")

    out = {k: {"type": "FeatureCollection", "features": v} for k, v in fcs.items()}
    out["road"] = _explode_multilines(out["road"])
    out.setdefault("pole", {"type": "FeatureCollection", "features": []})     # the engine requires the layer
    return out, notes


def input_poles(pole_fc: dict[str, Any] | None) -> list[tuple[float, float, str | None]]:
    out = []
    for f in (pole_fc or {}).get("features", []):
        g = f.get("geometry") or {}
        if g.get("type") == "Point":
            out.append((float(g["coordinates"][0]), float(g["coordinates"][1]),
                        (f.get("properties") or {}).get("live_asset_code")))
    return out


# ── Runs ─────────────────────────────────────────────────────

async def latest_run(db: AsyncSession, tid: uuid.UUID, design_id: uuid.UUID) -> FttxDesignRun | None:
    return (await db.execute(
        select(FttxDesignRun).where(FttxDesignRun.design_id == design_id, FttxDesignRun.tenant_id == tid)
        .order_by(FttxDesignRun.created_at.desc()).limit(1)
    )).scalar_one_or_none()


async def working_set_size(db: AsyncSession, design_id: uuid.UUID) -> tuple[int, int]:
    r = (await db.execute(text("""
        SELECT (SELECT count(*) FROM net_assets WHERE design_id = :d AND deleted_at IS NULL) AS a,
               (SELECT count(*) FROM net_cables WHERE design_id = :d AND deleted_at IS NULL) AS c
    """), {"d": design_id})).one()
    return int(r.a), int(r.c)


async def _refuse_if_busy_or_full(db: AsyncSession, tid: uuid.UUID, design: Design, replace: bool) -> None:
    run = await latest_run(db, tid, design.id)
    if run and run.status in ACTIVE_RUN_STATES:
        raise HTTPException(status.HTTP_409_CONFLICT, "An auto design is already running for this design; wait for it to finish.")
    assets, cables = await working_set_size(db, design.id)
    if (assets or cables) and not replace:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This design already has {assets} assets and {cables} cables. Confirm to replace them; "
                            "the current state is kept as its own version.")


async def queue_generate(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design,
                         overrides: dict[str, Any] | None, replace: bool) -> dict[str, Any]:
    from app.modules.design.service import ensure_editable
    from app.tasks.fttx_design_run import run_fttx_design_task

    ensure_editable(design)
    await _refuse_if_busy_or_full(db, tid, design, replace)
    cfg = run_config(design.engine_config, overrides)
    if overrides:
        design.engine_config = {k: v for k, v in cfg.items() if k != "homepass_field_name"}
    inputs, notes = await build_run_inputs(db, tid, design)

    run = FttxDesignRun(tenant_id=tid, name=f"{design.name} · auto design"[:200], status="queued", config=cfg,
                        progress_pct=0, progress_message="Queued", created_by=caller.id, design_id=design.id)
    db.add(run)
    await db.flush()
    for key, fc in inputs.items():
        db.add(FttxDesignRunLayer(run_id=run.id, tenant_id=tid, layer_key=key, original_filename="design inputs",
                                  feature_count=len(fc["features"]), geojson=fc, uploaded_by=caller.id))
    await write_audit_entry(db, asset_type="design", asset_id=design.id, asset_key=design.name, action="auto_design",
                            actor_user=caller, tenant_id=tid,
                            new_data={"run_id": str(run.id), "replace": replace, "notes": notes})
    # The worker must see the run: commit before queueing
    await db.commit()
    await set_tenant(db, tid)
    try:
        run.celery_task_id = run_fttx_design_task.delay(str(run.id)).id
    except Exception as exc:
        run.status, run.progress_message = "failed", "Failed"
        run.error_message = "The task queue is unavailable, so the auto design could not start. Try again shortly."
        await db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, run.error_message) from exc
    await db.commit()
    await set_tenant(db, tid)
    return {**await run_status(db, tid, design), "notes": notes}


async def cancel_generate(db: AsyncSession, tid: uuid.UUID, design: Design) -> dict[str, Any]:
    from app.core.celery_app import celery_app
    from app.modules.fttx_designer.cancellation import request_cancellation

    run = await latest_run(db, tid, design.id)
    if run is None or run.status not in ACTIVE_RUN_STATES or not run.celery_task_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "There is no queued or running auto design to cancel.")
    try:
        request_cancellation(run.celery_task_id)
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Cancellation service is unavailable; the auto design is still active.") from exc
    if run.status == "cancelling":
        return await run_status(db, tid, design)
    if run.status == "queued":
        try:
            celery_app.control.revoke(run.celery_task_id, terminate=False)
        except Exception:
            pass  # The worker also checks the Redis cancellation flag on startup.
        run.status = "cancelled"
        run.progress_message = "Cancelled"
        run.error_message = "Design run cancelled before it started."
        run.completed_at = datetime.datetime.now(datetime.timezone.utc)
    else:
        run.status = "cancelling"
        run.progress_message = "Cancellation requested; stopping at the next safe checkpoint."
    await db.commit()
    return await run_status(db, tid, design)


async def run_status(db: AsyncSession, tid: uuid.UUID, design: Design) -> dict[str, Any] | None:
    run = await latest_run(db, tid, design.id)
    if run is None:
        return None
    pct, message = run.progress_pct, run.progress_message
    if run.status in ACTIVE_RUN_STATES and run.celery_task_id:
        try:                                   # live progress from the task (see fttx_designer/router.py)
            from app.core.celery_app import celery_app
            from app.modules.fttx_designer.cancellation import cancellation_requested
            if cancellation_requested(run.celery_task_id):
                message = "Cancellation requested; stopping at the next safe checkpoint."
            else:
                res = celery_app.AsyncResult(run.celery_task_id)
                if res.state == "PROGRESS" and isinstance(res.info, dict):
                    pct, message = res.info.get("pct", pct), res.info.get("message", message)
        except Exception:
            pass
    version = None
    if run.design_version_id:
        v = await db.get(DesignVersion, run.design_version_id)
        if v:
            version = {"id": str(v.id), "version_no": v.version_no}
    return {
        "run_id": str(run.id), "status": run.status, "progress_pct": int(pct or 0), "progress_message": message,
        "error_message": run.error_message, "result_summary": run.result_summary, "design_version": version,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


# ── Writing the output into the design ───────────────────────

async def _write_rows(db: AsyncSession, tid: uuid.UUID, design: Design, adapted: Adapted, method: str,
                      actor_id: uuid.UUID | None) -> None:
    ids = {a.key: uuid.uuid4() for a in adapted.assets}
    if adapted.assets:
        await db.execute(text("""
            INSERT INTO net_assets (id, tenant_id, design_id, project_id, asset_code, asset_type, name, geom, parent_id,
                                    capacity, used_capacity, lifecycle_status, creation_method, attributes, created_by)
            VALUES (:id, :tid, :d, :p, :code, :type, :name, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), :parent,
                    :cap, :used, :life, :method, CAST(:attrs AS jsonb), :by)
        """), [{"id": ids[a.key], "tid": tid, "d": design.id, "p": design.project_id, "code": a.asset_code[:100],
                "type": a.asset_type, "name": (a.name or None) and a.name[:200], "lng": a.lng, "lat": a.lat,
                "parent": ids.get(a.parent) if a.parent else None, "cap": a.capacity, "used": a.used_capacity,
                "life": LIFECYCLE, "method": method, "attrs": json.dumps(a.attributes, default=str), "by": actor_id}
               for a in adapted.assets])
    if adapted.cables:
        await db.execute(text("""
            INSERT INTO net_cables (tenant_id, design_id, project_id, asset_code, cable_category, name, geom, fiber_count,
                                    installation_type, route_method, source_asset_id, dest_asset_id, lifecycle_status,
                                    creation_method, attributes, created_by)
            VALUES (:tid, :d, :p, :code, :cat, :name, ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326), :fibres,
                    'AERIAL', :route, :src, :dst, :life, :method, CAST(:attrs AS jsonb), :by)
        """), [{"tid": tid, "d": design.id, "p": design.project_id, "code": c.asset_code[:100], "cat": c.cable_category,
                "name": (c.name or None) and c.name[:200],
                "g": json.dumps({"type": "LineString", "coordinates": c.coordinates}), "fibres": c.fiber_count,
                "route": c.route_method, "src": ids.get(c.source) if c.source else None,
                "dst": ids.get(c.dest) if c.dest else None, "life": LIFECYCLE, "method": method,
                "attrs": json.dumps(c.attributes, default=str), "by": actor_id} for c in adapted.cables])
    links = [(ids[s], ids[t]) for s, t in adapted.links if s in ids and t in ids]
    if links:
        await db.execute(text("""
            INSERT INTO net_connections (tenant_id, design_id, source_asset_id, dest_asset_id, connection_type,
                                         lifecycle_status, created_by)
            VALUES (:tid, :d, :s, :t, 'FEED', :life, :by)
        """), [{"tid": tid, "d": design.id, "s": s, "t": t, "life": LIFECYCLE, "by": actor_id} for s, t in links])


async def apply_output(db: AsyncSession, tid: uuid.UUID, design_id: uuid.UUID, *, output: FttxDesignRunOutput,
                       run: FttxDesignRun, pole_fc: dict[str, Any] | None, method: str, label: str,
                       actor: Any = None) -> dict[str, Any]:
    """Replace the design's working set with a run's output, as a new version."""
    await set_tenant(db, tid)
    # populate_existing: the status must be the committed one, not a cached object's
    design = (await db.execute(select(Design).where(Design.id == design_id, Design.tenant_id == tid)
                               .with_for_update().execution_options(populate_existing=True))).scalar_one()
    if design.status in LOCKED_STATUSES or design.deleted_at is not None:
        raise DesignLocked(f"The design is {design.status.replace('_', ' ').lower()}; its working set can't be replaced.")

    cfg = config_from_dict(run.config or {})
    profile = get_capacity_profile(cfg.pon_architecture)
    adapted = adapt_engine_output(
        output.output_layers or {}, fdt_capacity=profile.max_fdt_capacity, fat_ports=MAX_CUSTOMERS_PER_FAT,
        pon_architecture=cfg.pon_architecture.value, cascade=cfg.cascade_architecture.value,
        input_poles=input_poles(pole_fc),
    )

    # What is there now is kept: the current version is frozen (Phase 8) before it is replaced
    from app.modules.design import audit, versions
    current = await versions.freeze(db, design)
    if current is not None and current.label is None:
        current.label = f"Before {'import' if method == 'IMPORTED' else 'auto design'}"
    replaced = await working_set_size(db, design.id)
    await audit.bulk(db)                 # one summary row below, not one per replaced row
    # The manual edit log refers to rows about to be replaced (Phase 6)
    from app.modules.design.operations import clear_log
    await clear_log(db, design.id)
    for table in ("net_connections", "net_cables", "net_assets"):
        await db.execute(text(f"DELETE FROM {table} WHERE design_id = :d AND tenant_id = :tid"), {"d": design.id, "tid": tid})

    actor_id = getattr(actor, "id", None) or run.created_by
    await _write_rows(db, tid, design, adapted, method, actor_id)
    await audit.bulk(db, on=False)

    next_no = (await db.execute(text("SELECT coalesce(max(version_no), 0) + 1 FROM design_versions WHERE design_id = :d"),
                                {"d": design.id})).scalar_one()
    version = DesignVersion(tenant_id=tid, design_id=design.id, version_no=next_no,
                            parent_version_id=current.id if current else None, creation_method=method, label=label[:200],
                            boq_snapshot={"streets": output.boq_rows or [], "fdt_detail": output.boq_fdt_rows or []},
                            optical_summary=output.optical_loss_summary, created_by=actor_id,
                            validation_summary={"engine_findings": engine_findings(output.output_layers or {})})
    db.add(version)
    await db.flush()
    design.current_version_id = version.id
    design.status = "GENERATED"
    design.updated_at = datetime.datetime.now(datetime.timezone.utc)
    run.design_version_id = version.id
    await db.flush()

    validation = await validation_service.validate(db, tid, design)
    await audit.summary(db, tid, design.id, "auto_design" if method == "AUTO" else "run_imported", actor,
                        {"version_no": current.version_no if current else None, "assets": replaced[0], "cables": replaced[1]},
                        {"version_no": next_no, "run_id": str(run.id), "counts": adapted.counts()})
    await write_audit_entry(db, asset_type="design", asset_id=design.id, asset_key=design.name, action="version",
                            actor_user=actor, tenant_id=tid,
                            old_data={"assets": replaced[0], "cables": replaced[1]},
                            new_data={"version_no": next_no, "method": method, "run_id": str(run.id),
                                      "counts": adapted.counts(), "warnings": adapted.warnings[:50]})
    return {"version_no": next_no, "counts": adapted.counts(), "warnings": adapted.warnings,
            "validation": validation["summary"]}


def engine_findings(layers: dict[str, Any], cap: int = 300) -> list[dict[str, str]]:
    """The run's own Validation_Results (engine warnings/errors), errors first, capped."""
    rows = [{"severity": str((f.get("properties") or {}).get("severity") or "WARNING").upper(),
             "category": str((f.get("properties") or {}).get("category") or ""),
             "message": str((f.get("properties") or {}).get("message") or "")}
            for f in (layers.get("validation_results") or {}).get("features", [])]
    rows = [r for r in rows if r["message"]]
    rows.sort(key=lambda r: 0 if r["severity"] == "ERROR" else 1)
    return rows[:cap]


# ── Import an existing run ───────────────────────────────────

async def importable_runs(db: AsyncSession, tid: uuid.UUID, design: Design) -> list[dict[str, Any]]:
    """Completed FTTx Designer runs with results: standalone ones, or this design's own."""
    rows = (await db.execute(text("""
        SELECT r.id, r.name, r.completed_at, r.result_summary, r.config, r.design_id
        FROM fttx_design_runs r
        WHERE r.tenant_id = :tid AND r.status = 'completed'
          AND (r.design_id IS NULL OR r.design_id = :d)
          AND EXISTS (SELECT 1 FROM fttx_design_run_outputs o WHERE o.run_id = r.id)
        ORDER BY r.completed_at DESC NULLS LAST
        LIMIT 50
    """), {"tid": tid, "d": design.id})).all()
    return [{
        "id": str(r.id), "name": r.name, "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "from_this_design": r.design_id is not None,
        "fdt_count": (r.result_summary or {}).get("fdt_count"), "fat_count": (r.result_summary or {}).get("fat_count"),
        "homepass_count": (r.result_summary or {}).get("homepass_count"),
        "deployment_type": (r.config or {}).get("deployment_type"), "pon_architecture": (r.config or {}).get("pon_architecture"),
    } for r in rows]


async def import_run(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design, run_id: str,
                     replace: bool) -> dict[str, Any]:
    from app.modules.design.service import ensure_editable, save_inputs

    ensure_editable(design)
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found") from None
    run = (await db.execute(select(FttxDesignRun).where(FttxDesignRun.id == rid, FttxDesignRun.tenant_id == tid))
           ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    output = (await db.execute(select(FttxDesignRunOutput).where(FttxDesignRunOutput.run_id == run.id))).scalar_one_or_none()
    if run.status != "completed" or output is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a completed run with results can be imported.")
    await _refuse_if_busy_or_full(db, tid, design, replace)

    layers = {r.layer_key: r.geojson for r in (await db.execute(
        select(FttxDesignRunLayer).where(FttxDesignRunLayer.run_id == run.id))).scalars().all()}
    counts = {r.layer_key: int(r.n) for r in (await db.execute(text(
        "SELECT layer_key, count(*) AS n FROM design_inputs WHERE design_id = :d GROUP BY 1"), {"d": design.id})).all()}
    field = (run.config or {}).get("homepass_field_name")
    copied: list[str] = []
    for key in ("road", "homepass", "pole", "building", "pickup"):
        fc = layers.get(key)
        if not fc or not fc.get("features") or counts.get(key):
            continue
        if key == "homepass" and field and field != HOMEPASS_COUNT_FIELD:
            fc = {"type": "FeatureCollection", "features": [
                {**f, "properties": {**(f.get("properties") or {}), HOMEPASS_COUNT_FIELD: (f.get("properties") or {}).get(field)}}
                for f in fc["features"]]}
        parsed = parse_input_file(key, f"run-{key}.geojson", json.dumps(fc).encode())
        res = await save_inputs(db, tid, caller, design, key, f"{run.name or 'FTTx run'} ({key})", "replace", parsed)
        if res["status"] == "saved":
            copied.append(key)

    # The run's settings become the design's, so validation judges it by the rules it was built to
    design.engine_config = {k: v for k, v in (run.config or {}).items() if k != "homepass_field_name"}
    await db.flush()
    run.design_id = run.design_id or design.id
    result = await apply_output(db, tid, design.id, output=output, run=run, pole_fc=layers.get("pole"),
                                method="IMPORTED", label=f"Imported from {run.name or 'an FTTx run'}"[:200], actor=caller)
    return {**result, "inputs_copied": copied}
