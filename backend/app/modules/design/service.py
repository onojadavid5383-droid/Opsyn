# ============================================================
# OPSYN DESIGN SERVICE — app/modules/design/service.py
#
# The design container: create (with version 1), read, update, soft delete;
# per-design inputs (save a parsed file as one batch, list, GeoJSON for the
# map, remove a layer); boundary from the inputs; the working set as
# GeoJSON; the summary strip. BOQ, validation and routing live in their own
# services. Tenant: every query filters tenant_id on top of RLS.
# ============================================================

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.design.inputs import LAYER_LABELS, ParsedInputs
from app.modules.design.models import INPUT_LAYERS, LOCKED_STATUSES, Design, DesignInputUpload, DesignVersion
from app.modules.design.schemas import DesignCreate, DesignOut, DesignUpdate, VersionRef
from app.modules.infrastructure.audit_service import write_audit_entry

MAX_INPUT_FEATURES_RETURNED = 20_000


def _uuid_or_404(value: str, what: str = "Design") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


def ensure_editable(design: Design) -> None:
    """Content changes are refused while the design is in review or later."""
    if design.status in LOCKED_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"The design is {design.status.replace('_', ' ').lower()}; its content can't be changed")


async def load_design(db: AsyncSession, tid: uuid.UUID, design_id: str) -> Design:
    design = await db.get(Design, _uuid_or_404(design_id))
    if design is None or design.tenant_id != tid or design.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Design not found")
    return design


async def _project(db: AsyncSession, tid: uuid.UUID, project_id: str) -> Any:
    row = (await db.execute(text("SELECT id, name FROM projects WHERE id = :id AND tenant_id = :tid"),
                            {"id": _uuid_or_404(project_id, "Project"), "tid": tid})).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return row


async def design_out(db: AsyncSession, tid: uuid.UUID, design: Design) -> DesignOut:
    r = (await db.execute(text("""
        SELECT p.name AS project_name,
               ST_AsGeoJSON(d.boundary, 7) AS boundary,
               (SELECT ST_Extent(g) FROM (
                    SELECT d.boundary AS g
                    UNION ALL SELECT geom FROM design_inputs WHERE design_id = d.id
                    UNION ALL SELECT geom FROM net_assets WHERE design_id = d.id AND deleted_at IS NULL
                    UNION ALL SELECT geom FROM net_cables WHERE design_id = d.id AND deleted_at IS NULL
               ) x) AS ext,
               v.id AS v_id, v.version_no, v.label, v.creation_method, v.created_at AS v_created
        FROM designs d
        JOIN projects p ON p.id = d.project_id
        LEFT JOIN design_versions v ON v.id = d.current_version_id
        WHERE d.id = :id AND d.tenant_id = :tid
    """), {"id": design.id, "tid": tid})).one()
    counts = {k: 0 for k in INPUT_LAYERS}
    for c in (await db.execute(text(
            "SELECT layer_key, count(*) AS n FROM design_inputs WHERE design_id = :id GROUP BY 1"),
            {"id": design.id})).all():
        counts[c.layer_key] = int(c.n)
    bbox = None
    if r.ext:
        box = (await db.execute(text("SELECT ST_XMin(CAST(:e AS box2d)), ST_YMin(CAST(:e AS box2d)), "
                                     "ST_XMax(CAST(:e AS box2d)), ST_YMax(CAST(:e AS box2d))"), {"e": r.ext})).one()
        bbox = [float(v) for v in box]
    return DesignOut(
        id=str(design.id), project_id=str(design.project_id), project_name=r.project_name,
        name=design.name, description=design.description, status=design.status,
        boundary=json.loads(r.boundary) if r.boundary else None, bbox=bbox,
        engine_config=design.engine_config or {},
        current_version=VersionRef(id=str(r.v_id), version_no=r.version_no, label=r.label,
                                   creation_method=r.creation_method, created_at=r.v_created.isoformat())
        if r.v_id else None,
        input_counts=counts, created_at=design.created_at.isoformat(), updated_at=design.updated_at.isoformat(),
    )


async def list_designs(db: AsyncSession, tid: uuid.UUID, project_id: str) -> list[DesignOut]:
    project = await _project(db, tid, project_id)
    ids = (await db.execute(text("""
        SELECT id FROM designs WHERE project_id = :p AND tenant_id = :tid AND deleted_at IS NULL
        ORDER BY created_at DESC
    """), {"p": project.id, "tid": tid})).scalars().all()
    return [await design_out(db, tid, await db.get(Design, i)) for i in ids]


def _validate_engine_config(cfg: dict[str, Any]) -> None:
    from app.modules.fttx_designer.config_io import InvalidFttxConfigError, config_from_dict
    try:
        config_from_dict(cfg)
    except InvalidFttxConfigError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


async def create_design(db: AsyncSession, tid: uuid.UUID, caller: Any, project_id: str, body: DesignCreate) -> DesignOut:
    project = await _project(db, tid, project_id)
    _validate_engine_config(body.engine_config)
    design = Design(tenant_id=tid, project_id=project.id, name=body.name, description=body.description,
                    engine_config=body.engine_config, created_by=caller.id, updated_by=caller.id)
    db.add(design)
    await db.flush()
    v1 = DesignVersion(tenant_id=tid, design_id=design.id, version_no=1, creation_method="INITIAL",
                       label="Created", created_by=caller.id)
    db.add(v1)
    await db.flush()
    design.current_version_id = v1.id
    await db.flush()
    await write_audit_entry(db, asset_type="design", asset_id=design.id, asset_key=design.name, action="create",
                            actor_user=caller, tenant_id=tid,
                            new_data={"project_id": str(project.id), "name": design.name})
    await db.refresh(design)
    return await design_out(db, tid, design)


async def update_design(db: AsyncSession, tid: uuid.UUID, caller: Any, design_id: str, body: DesignUpdate) -> DesignOut:
    design = await load_design(db, tid, design_id)
    sent = body.model_fields_set
    if sent & {"boundary", "engine_config", "status"}:
        ensure_editable(design)
    before = {"name": design.name, "status": design.status}
    if "name" in sent and body.name:
        design.name = body.name.strip()
    if "description" in sent:
        design.description = body.description
    if "status" in sent and body.status:
        design.status = body.status
    if "engine_config" in sent and body.engine_config is not None:
        _validate_engine_config(body.engine_config)
        design.engine_config = body.engine_config
    if "boundary" in sent:
        if body.boundary is None:
            await db.execute(text("UPDATE designs SET boundary = NULL WHERE id = :id"), {"id": design.id})
        else:
            ok = (await db.execute(text("""
                SELECT ST_IsValid(g) AND NOT ST_IsEmpty(g) AND ST_Area(g::geography) > 1 AS ok,
                       ST_IsValidReason(g) AS reason
                FROM (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326) AS g) x
            """), {"g": json.dumps(body.boundary.model_dump())})).one()
            if not ok.ok:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    f"The boundary is not a valid area ({ok.reason}). Redraw it without crossing edges.")
            await db.execute(text("""
                UPDATE designs SET boundary = ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)) WHERE id = :id
            """), {"g": json.dumps(body.boundary.model_dump()), "id": design.id})
    design.updated_by = caller.id
    design.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.flush()
    await write_audit_entry(db, asset_type="design", asset_id=design.id, asset_key=design.name, action="update",
                            actor_user=caller, tenant_id=tid, old_data=before,
                            new_data={"name": design.name, "status": design.status, "changed": sorted(sent)})
    await db.refresh(design)
    return await design_out(db, tid, design)


async def delete_design(db: AsyncSession, tid: uuid.UUID, caller: Any, design_id: str) -> None:
    design = await load_design(db, tid, design_id)
    if design.status in ("APPROVED", "DEPLOYED"):
        raise HTTPException(status.HTTP_409_CONFLICT, "An approved or deployed design cannot be deleted")
    design.deleted_at = datetime.datetime.now(datetime.timezone.utc)
    design.deleted_by = caller.id
    await db.flush()
    await write_audit_entry(db, asset_type="design", asset_id=design.id, asset_key=design.name,
                            action="soft_delete", actor_user=caller, tenant_id=tid)


async def boundary_from_inputs(db: AsyncSession, tid: uuid.UUID, caller: Any, design_id: str) -> DesignOut:
    """The convex outline of every input, widened by 30 m, as the boundary.

    Convex, not concave: ST_ConcaveHull is pathologically slow on road
    linework (55 s for a handful of segments on PostGIS 3.4), and a person
    can always redraw a tighter boundary by hand.
    """
    design = await load_design(db, tid, design_id)
    ensure_editable(design)
    g = (await db.execute(text("""
        SELECT ST_AsGeoJSON(ST_Multi(
                 ST_Buffer(ST_ConvexHull(ST_Collect(geom))::geography, 30)::geometry), 7)
        FROM design_inputs WHERE design_id = :d
    """), {"d": design.id})).scalar_one()
    if not g:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Upload some inputs first; the boundary is drawn around them.")
    from app.modules.design.schemas import BoundaryGeometry
    return await update_design(db, tid, caller, design_id, DesignUpdate(boundary=BoundaryGeometry(**json.loads(g))))


# ── Inputs ───────────────────────────────────────────────────

async def _checkpoint_if_layer(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design, layer: str,
                               reason: str) -> None:
    """Replacing or removing a layer with data first freezes a version (Phase 8: nothing is lost)."""
    from app.modules.design import versions
    if (await db.execute(text("SELECT 1 FROM design_inputs WHERE design_id = :d AND layer_key = :l LIMIT 1"),
                         {"d": design.id, "l": layer})).first():
        await versions.checkpoint(db, tid, design, reason, caller)


async def save_inputs(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design, layer: str,
                      filename: str, mode: str, parsed: ParsedInputs) -> dict[str, Any]:
    ensure_editable(design)
    if parsed.errors:
        return {"status": "rejected", "layer_key": layer, "feature_count": 0,
                "errors": parsed.errors, "warnings": parsed.warnings, "upload_id": None}
    if mode == "replace":
        await _checkpoint_if_layer(db, tid, caller, design, layer, f"Before replacing {LAYER_LABELS[layer].lower()}")
        await db.execute(text("DELETE FROM design_inputs WHERE design_id = :d AND layer_key = :l"),
                         {"d": design.id, "l": layer})
    upload = DesignInputUpload(tenant_id=tid, design_id=design.id, layer_key=layer, filename=filename,
                               file_hash=parsed.file_hash, feature_count=len(parsed.features), mode=mode,
                               uploaded_by=caller.id)
    db.add(upload)
    await db.flush()
    await db.execute(text("""
        INSERT INTO design_inputs (tenant_id, design_id, layer_key, geom, properties, upload_id)
        VALUES (:tid, :d, :l, ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326), CAST(:p AS jsonb), :u)
    """), [{"tid": tid, "d": design.id, "l": layer, "g": json.dumps(f["geometry"]),
            "p": json.dumps(f["properties"]), "u": upload.id} for f in parsed.features])
    outside = 0
    if design.boundary is not None:
        outside = (await db.execute(text("""
            SELECT count(*) FROM design_inputs i JOIN designs d ON d.id = i.design_id
            WHERE i.upload_id = :u AND NOT ST_Intersects(d.boundary, i.geom)
        """), {"u": upload.id})).scalar_one()
    warnings = list(parsed.warnings)
    if outside:
        warnings.append(f"{outside} features lie outside the design boundary")
    if design.status == "GENERATED":
        design.status = "MODIFIED"
    design.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.flush()
    await write_audit_entry(db, asset_type="design_input", asset_id=design.id, asset_key=f"{design.name}: {layer}",
                            action="upload", actor_user=caller, tenant_id=tid,
                            new_data={"layer": layer, "filename": filename, "mode": mode, "features": len(parsed.features)})
    return {"status": "saved", "layer_key": layer, "feature_count": len(parsed.features),
            "errors": [], "warnings": warnings, "upload_id": str(upload.id)}


async def list_inputs(db: AsyncSession, tid: uuid.UUID, design: Design) -> list[dict[str, Any]]:
    counts = {r.layer_key: int(r.n) for r in (await db.execute(text(
        "SELECT layer_key, count(*) AS n FROM design_inputs WHERE design_id = :d AND tenant_id = :tid GROUP BY 1"),
        {"d": design.id, "tid": tid})).all()}
    last = {r.layer_key: r for r in (await db.execute(text("""
        SELECT DISTINCT ON (layer_key) layer_key, filename, uploaded_at, mode, feature_count
        FROM design_input_uploads WHERE design_id = :d AND tenant_id = :tid
        ORDER BY layer_key, uploaded_at DESC
    """), {"d": design.id, "tid": tid})).all()}
    return [{
        "layer_key": k, "label": LAYER_LABELS[k], "feature_count": counts.get(k, 0),
        "last_upload": {"filename": last[k].filename, "uploaded_at": last[k].uploaded_at.isoformat(),
                        "mode": last[k].mode, "feature_count": last[k].feature_count} if k in last else None,
    } for k in INPUT_LAYERS]


async def input_features(db: AsyncSession, tid: uuid.UUID, design: Design, layer: str) -> dict[str, Any]:
    rows = (await db.execute(text("""
        SELECT id, ST_AsGeoJSON(geom, 7) AS g, properties FROM design_inputs
        WHERE design_id = :d AND tenant_id = :tid AND layer_key = :l ORDER BY created_at, id LIMIT :cap
    """), {"d": design.id, "tid": tid, "l": layer, "cap": MAX_INPUT_FEATURES_RETURNED + 1})).all()
    truncated = len(rows) > MAX_INPUT_FEATURES_RETURNED
    return {"type": "FeatureCollection", "truncated": truncated, "features": [
        {"type": "Feature", "id": str(r.id), "geometry": json.loads(r.g),
         "properties": {**(r.properties or {}), "layer_key": layer}}
        for r in rows[:MAX_INPUT_FEATURES_RETURNED]]}


async def delete_inputs(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design, layer: str) -> int:
    ensure_editable(design)
    await _checkpoint_if_layer(db, tid, caller, design, layer, f"Before removing {LAYER_LABELS[layer].lower()}")
    n = (await db.execute(text("DELETE FROM design_inputs WHERE design_id = :d AND tenant_id = :tid AND layer_key = :l"),
                          {"d": design.id, "tid": tid, "l": layer})).rowcount
    await write_audit_entry(db, asset_type="design_input", asset_id=design.id, asset_key=f"{design.name}: {layer}",
                            action="delete", actor_user=caller, tenant_id=tid, old_data={"layer": layer, "features": n})
    return n


# ── Working set & summary ────────────────────────────────────

async def working_set_features(db: AsyncSession, tid: uuid.UUID, design: Design,
                               asset_ids: list[uuid.UUID] | None = None,
                               cable_ids: list[uuid.UUID] | None = None) -> dict[str, Any]:
    """The design's assets and cables as GeoJSON with the same properties the tiles carry.
    With ids, only those rows (the features an edit changed, Phase 7)."""
    only = asset_ids is not None or cable_ids is not None
    p = {"d": design.id, "tid": tid, "aids": list(asset_ids or []), "cids": list(cable_ids or [])}
    assets = (await db.execute(text("""
        SELECT id, asset_code, asset_type, coalesce(name, '') AS name, lifecycle_status, creation_method,
               capacity, used_capacity, ST_AsGeoJSON(geom, 7) AS g
        FROM net_assets WHERE design_id = :d AND tenant_id = :tid AND deleted_at IS NULL
    """ + ("AND id = ANY(:aids)" if only else "")), p)).all()
    cables = (await db.execute(text("""
        SELECT id, asset_code, cable_category, coalesce(name, '') AS name, lifecycle_status, fiber_count,
               length_m::float8 AS length_m, route_method, ST_AsGeoJSON(geom, 7) AS g
        FROM net_cables WHERE design_id = :d AND tenant_id = :tid AND deleted_at IS NULL
    """ + ("AND id = ANY(:cids)" if only else "")), p)).all()
    feats = [{"type": "Feature", "geometry": json.loads(a.g), "properties": {
        "kind": "asset", "id": str(a.id), "asset_code": a.asset_code, "asset_type": a.asset_type, "name": a.name,
        "lifecycle_status": a.lifecycle_status, "creation_method": a.creation_method,
        "capacity": a.capacity, "used_capacity": a.used_capacity}} for a in assets]
    feats += [{"type": "Feature", "geometry": json.loads(c.g), "properties": {
        "kind": "cable", "id": str(c.id), "asset_code": c.asset_code, "cable_category": c.cable_category,
        "name": c.name, "lifecycle_status": c.lifecycle_status, "fiber_count": c.fiber_count,
        "length_m": c.length_m, "route_method": c.route_method}} for c in cables]
    return {"type": "FeatureCollection", "features": feats}


async def summary(db: AsyncSession, tid: uuid.UUID, design: Design) -> dict[str, Any]:
    p = {"d": design.id, "tid": tid}
    r = (await db.execute(text("""
        SELECT
          (SELECT count(*) FROM design_inputs WHERE design_id = :d AND layer_key = 'homepass') AS homepasses,
          (SELECT coalesce(sum(CASE WHEN properties->>'customers' ~ '^[0-9]+$' THEN (properties->>'customers')::int ELSE 1 END), 0)
             FROM design_inputs WHERE design_id = :d AND layer_key = 'homepass') AS customers,
          (SELECT count(*) FROM net_assets WHERE design_id = :d AND deleted_at IS NULL AND asset_type = 'FDT') AS fdt,
          (SELECT count(*) FROM net_assets WHERE design_id = :d AND deleted_at IS NULL AND asset_type = 'FAT') AS fat,
          (SELECT count(*) FROM net_assets WHERE design_id = :d AND deleted_at IS NULL AND asset_type = 'SPLITTER') AS splitters,
          (SELECT count(*) FROM net_assets WHERE design_id = :d AND deleted_at IS NULL AND asset_type = 'CLOSURE') AS closures,
          (SELECT count(*) FROM net_assets WHERE design_id = :d AND deleted_at IS NULL AND asset_type = 'POLE') AS poles,
          (SELECT coalesce(sum(length_m), 0)::float8 FROM net_cables WHERE design_id = :d AND deleted_at IS NULL) AS cable_m,
          (SELECT count(*) FILTER (WHERE severity = 'ERROR') FROM design_validation_issues WHERE design_id = :d) AS errors,
          (SELECT count(*) FILTER (WHERE severity = 'WARNING') FROM design_validation_issues WHERE design_id = :d) AS warnings,
          (SELECT v.validation_summary->>'validated_at' FROM designs d JOIN design_versions v ON v.id = d.current_version_id
             WHERE d.id = :d) AS validated_at
    """), p)).one()
    return {
        "homepasses": int(r.homepasses), "customers": int(r.customers), "fdt": int(r.fdt), "fat": int(r.fat),
        "splitters": int(r.splitters), "closures": int(r.closures), "poles": int(r.poles),
        "cable_km": round(float(r.cable_m) / 1000.0, 3), "errors": int(r.errors or 0), "warnings": int(r.warnings or 0),
        "validated_at": r.validated_at,
    }
