# ============================================================
# OPSYN DESIGN ROUTER — app/modules/design/router.py
#
#   GET    /projects/{project_id}/designs          a project's designs        network.view
#   POST   /projects/{project_id}/designs          create (with version 1)    design.edit
#   GET    /designs/{id}                           the design                 network.view
#   PATCH  /designs/{id}                           name, status, boundary…    design.edit
#   DELETE /designs/{id}                           soft delete                design.edit
#   POST   /designs/{id}/boundary/from-inputs      boundary around the inputs design.edit
#   GET    /designs/{id}/inputs                    input layers and counts    network.view
#   GET    /designs/{id}/inputs/{layer}            one layer as GeoJSON       network.view
#   POST   /designs/{id}/inputs/{layer}            upload (mode=replace|append) design.edit
#   DELETE /designs/{id}/inputs/{layer}            remove a layer             design.edit
#   GET    /designs/{id}/features                  working set as GeoJSON     network.view
#   GET    /designs/{id}/summary                   the summary strip          network.view
#   GET    /designs/{id}/boq                       quantities + street BOQ    network.view
#   POST   /designs/{id}/validate                  run the checks             design.edit
#   GET    /designs/{id}/validation                the stored issues          network.view
#   POST   /designs/{id}/route                     road-graph route           design.edit
#   POST   /designs/{id}/generate                  queue an auto design (P5)  design.edit
#   GET    /designs/{id}/generate/status           latest auto run, progress  network.view
#   GET    /designs/{id}/importable-runs           completed FTTx runs        network.view
#   POST   /designs/{id}/import-run                a run's output → version   design.edit
#   POST   /designs/{id}/operations                one manual edit (P6)       design.edit
#   POST   /designs/{id}/operations/undo|redo      server-side undo / redo    design.edit
#   GET    /designs/{id}/operations                the edit log + undo state  network.view
#   POST   /designs/{id}/snap                      where a click lands        network.view
#   GET    /designs/{id}/versions                  versions, current first    network.view
#   POST   /designs/{id}/versions                  save (name) the current    design.edit
#   GET    /designs/{id}/versions/{no}/features    a version's map features   network.view
#   GET    /designs/{id}/compare?from=&to=         added/removed/moved/changed network.view
#   POST   /designs/{id}/versions/{no}/restore     back to a version (new one) design.edit
#   GET    /designs/{id}/history                   the design's audit trail   network.view
#   GET    /network/history/{entity_id}            one asset / cable's trail  network.view
#
# {success, data} envelope. 404 unknown / other-tenant design, 409 state,
# 422 bad input or no road route.
# ============================================================

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.permissions import check_permission
from app.modules.design.audit import audited
from app.modules.design import (
    audit, auto_design, boq_service, operations, routing_service, service, snap, validation_service, versions,
)
from app.modules.design.inputs import parse_input_file
from app.modules.design.models import INPUT_LAYERS
from app.modules.design.schemas import (
    DesignCreate, DesignUpdate, GenerateRequest, ImportRunRequest, RouteRequest, SaveVersionRequest, SnapRequest,
)
from app.modules.staff.models import User

router = APIRouter()

MAX_INPUT_BYTES = 20 * 1024 * 1024


def _layer(layer_key: str) -> str:
    if layer_key not in INPUT_LAYERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown input layer '{layer_key}'")
    return layer_key


@router.get("/projects/{project_id}/designs")
async def list_designs(project_id: str, db: AsyncSession = Depends(get_db),
                       caller: User = Depends(check_permission("network.view"))):
    designs = await service.list_designs(db, caller.tenant_id, project_id)
    return {"success": True, "data": [d.model_dump() for d in designs]}


@router.post("/projects/{project_id}/designs", status_code=status.HTTP_201_CREATED)
async def create_design(project_id: str, body: DesignCreate, db: AsyncSession = Depends(get_db),
                        caller: User = Depends(audited("design.edit"))):
    design = await service.create_design(db, caller.tenant_id, caller, project_id, body)
    return {"success": True, "data": design.model_dump()}


@router.get("/designs/{design_id}")
async def get_design(design_id: str, db: AsyncSession = Depends(get_db),
                     caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": (await service.design_out(db, caller.tenant_id, design)).model_dump()}


@router.patch("/designs/{design_id}")
async def update_design(design_id: str, body: DesignUpdate, db: AsyncSession = Depends(get_db),
                        caller: User = Depends(audited("design.edit"))):
    design = await service.update_design(db, caller.tenant_id, caller, design_id, body)
    return {"success": True, "data": design.model_dump()}


@router.delete("/designs/{design_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_design(design_id: str, db: AsyncSession = Depends(get_db),
                        caller: User = Depends(audited("design.edit"))):
    await service.delete_design(db, caller.tenant_id, caller, design_id)


@router.post("/designs/{design_id}/boundary/from-inputs")
async def boundary_from_inputs(design_id: str, db: AsyncSession = Depends(get_db),
                               caller: User = Depends(audited("design.edit"))):
    design = await service.boundary_from_inputs(db, caller.tenant_id, caller, design_id)
    return {"success": True, "data": design.model_dump()}


@router.get("/designs/{design_id}/inputs")
async def list_inputs(design_id: str, db: AsyncSession = Depends(get_db),
                      caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await service.list_inputs(db, caller.tenant_id, design)}


@router.get("/designs/{design_id}/inputs/{layer_key}")
async def input_layer(design_id: str, layer_key: str, db: AsyncSession = Depends(get_db),
                      caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await service.input_features(db, caller.tenant_id, design, _layer(layer_key))}


@router.post("/designs/{design_id}/inputs/{layer_key}")
async def upload_inputs(
    design_id: str, layer_key: str,
    file: UploadFile = File(..., description="GeoJSON FeatureCollection or Excel (.xlsx)"),
    mode: str = Query("replace", pattern="^(replace|append)$"),
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(audited("design.edit")),
):
    layer = _layer(layer_key)
    design = await service.load_design(db, caller.tenant_id, design_id)
    data = await file.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The file is larger than 20 MB; split it into smaller files")
    from fastapi.concurrency import run_in_threadpool
    parsed = await run_in_threadpool(parse_input_file, layer, file.filename or "upload.geojson", data)
    result = await service.save_inputs(db, caller.tenant_id, caller, design, layer,
                                       file.filename or "upload", mode, parsed)
    return {"success": True, "data": result}


@router.delete("/designs/{design_id}/inputs/{layer_key}")
async def delete_inputs(design_id: str, layer_key: str, db: AsyncSession = Depends(get_db),
                        caller: User = Depends(audited("design.edit"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    removed = await service.delete_inputs(db, caller.tenant_id, caller, design, _layer(layer_key))
    return {"success": True, "data": {"removed": removed}}


@router.get("/designs/{design_id}/features")
async def features(design_id: str, db: AsyncSession = Depends(get_db),
                   caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await service.working_set_features(db, caller.tenant_id, design)}


@router.get("/designs/{design_id}/summary")
async def summary(design_id: str, db: AsyncSession = Depends(get_db),
                  caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await service.summary(db, caller.tenant_id, design)}


@router.get("/designs/{design_id}/boq")
async def boq(design_id: str, db: AsyncSession = Depends(get_db),
              caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await boq_service.compute_boq(db, caller.tenant_id, design)}


@router.post("/designs/{design_id}/validate")
async def validate(design_id: str, db: AsyncSession = Depends(get_db),
                   caller: User = Depends(audited("design.edit"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await validation_service.validate(db, caller.tenant_id, design)}


@router.get("/designs/{design_id}/validation")
async def validation(design_id: str, db: AsyncSession = Depends(get_db),
                     caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    issues = await validation_service.stored_issues(db, caller.tenant_id, design.id)
    findings = await validation_service.engine_findings(db, design.current_version_id)
    return {"success": True, "data": {"issues": issues, "summary": validation_service.summarise(issues),
                                      "engine_findings": findings}}


@router.post("/designs/{design_id}/route")
async def route(design_id: str, body: RouteRequest, db: AsyncSession = Depends(get_db),
                caller: User = Depends(audited("design.edit"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    result = await routing_service.route(db, caller.tenant_id, design,
                                         body.start.model_dump(), body.end.model_dump())
    return {"success": True, "data": result}


# ── Auto design (Phase 5) ────────────────────────────────────

@router.post("/designs/{design_id}/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate(design_id: str, body: GenerateRequest, db: AsyncSession = Depends(get_db),
                   caller: User = Depends(audited("design.edit"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    data = await auto_design.queue_generate(db, caller.tenant_id, caller, design, body.engine_config, body.replace)
    return {"success": True, "data": data}


@router.get("/designs/{design_id}/generate/status")
async def generate_status(design_id: str, db: AsyncSession = Depends(get_db),
                          caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await auto_design.run_status(db, caller.tenant_id, design)}


@router.post("/designs/{design_id}/generate/cancel")
async def cancel_generate(design_id: str, db: AsyncSession = Depends(get_db),
                          caller: User = Depends(audited("design.edit"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await auto_design.cancel_generate(db, caller.tenant_id, design)}


@router.get("/designs/{design_id}/importable-runs")
async def importable_runs(design_id: str, db: AsyncSession = Depends(get_db),
                          caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await auto_design.importable_runs(db, caller.tenant_id, design)}


@router.post("/designs/{design_id}/import-run")
async def import_run(design_id: str, body: ImportRunRequest, db: AsyncSession = Depends(get_db),
                     caller: User = Depends(audited("design.edit"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    data = await auto_design.import_run(db, caller.tenant_id, caller, design, body.run_id, body.replace)
    return {"success": True, "data": data}


# ── Manual design (Phase 6) ──────────────────────────────────

@router.post("/designs/{design_id}/operations")
async def apply_operation(design_id: str, body: dict[str, Any] = Body(..., examples=[{"op": "ADD_ASSET", "asset_type": "FAT", "lng": 3.35, "lat": 6.6}]),
                          db: AsyncSession = Depends(get_db), caller: User = Depends(audited("design.edit"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await operations.apply_operation(db, caller.tenant_id, caller, design, body)}


@router.post("/designs/{design_id}/operations/undo")
async def undo(design_id: str, db: AsyncSession = Depends(get_db),
               caller: User = Depends(audited("design.edit"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await operations.undo(db, caller.tenant_id, caller, design)}


@router.post("/designs/{design_id}/operations/redo")
async def redo(design_id: str, db: AsyncSession = Depends(get_db),
               caller: User = Depends(audited("design.edit"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await operations.redo(db, caller.tenant_id, caller, design)}


@router.get("/designs/{design_id}/operations")
async def operation_log(design_id: str, db: AsyncSession = Depends(get_db),
                        caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await operations.history(db, caller.tenant_id, design)}


@router.post("/designs/{design_id}/snap")
async def snap_point(design_id: str, body: SnapRequest, db: AsyncSession = Depends(get_db),
                     caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await snap.snap(db, caller.tenant_id, design, body.lng, body.lat,
                                                     body.radius_m, body.targets)}


# ── Versions and audit (Phase 8) ─────────────────────────────

@router.get("/designs/{design_id}/versions")
async def list_versions(design_id: str, db: AsyncSession = Depends(get_db),
                        caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await versions.list_versions(db, caller.tenant_id, design)}


@router.post("/designs/{design_id}/versions", status_code=status.HTTP_201_CREATED)
async def save_version(design_id: str, body: SaveVersionRequest, db: AsyncSession = Depends(get_db),
                       caller: User = Depends(audited("design.edit"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await versions.save(db, caller.tenant_id, caller, design, body.label)}


@router.get("/designs/{design_id}/versions/{version_no}/features")
async def version_features(design_id: str, version_no: int, db: AsyncSession = Depends(get_db),
                           caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await versions.version_features(db, caller.tenant_id, design, version_no)}


@router.get("/designs/{design_id}/compare")
async def compare(design_id: str, from_: int = Query(..., alias="from"), to: int = Query(...),
                  db: AsyncSession = Depends(get_db), caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await versions.compare(db, caller.tenant_id, design, from_, to)}


@router.post("/designs/{design_id}/versions/{version_no}/restore")
async def restore_version(design_id: str, version_no: int, db: AsyncSession = Depends(get_db),
                          caller: User = Depends(audited("design.edit"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await versions.restore(db, caller.tenant_id, caller, design, version_no)}


@router.get("/designs/{design_id}/history")
async def design_history(design_id: str, db: AsyncSession = Depends(get_db),
                         caller: User = Depends(check_permission("network.view"))):
    design = await service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await audit.design_history(db, caller.tenant_id, design.id)}


@router.get("/network/history/{entity_id}")
async def entity_history(entity_id: str, db: AsyncSession = Depends(get_db),
                         caller: User = Depends(check_permission("network.view"))):
    import uuid as _uuid
    try:
        eid = _uuid.UUID(entity_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found") from None
    return {"success": True, "data": await audit.entity_history(db, caller.tenant_id, eid)}
