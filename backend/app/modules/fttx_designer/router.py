# ============================================================
# OPSYN FTTX DESIGNER ROUTER — app/modules/fttx_designer/router.py
#
# Endpoints for the web port of the standalone QGIS "FTTx Designer"
# script: create a run, upload its input layers as GeoJSON, trigger
# execution as a Celery task, poll status, and fetch results.
#
# Mirrors app/modules/infrastructure/router.py's conventions:
#   - Depends(check_permission("fttx_designer.view"|"fttx_designer.edit"))
#     for both auth and the permission gate (returns the caller User).
#   - Depends(get_db) for the async session — this router never touches
#     app/tasks/_db.py, which is exclusively for the Celery worker side.
#   - Inline Pydantic schemas with a from_orm_obj(...) classmethod,
#     converting UUID/datetime to str explicitly.
#
# Status polling (see app/tasks/fttx_design_run.py's module docstring):
# the DB row (`status`/`progress_pct`/`progress_message`) is the
# authoritative state, updated only at task start/end. While a run is
# "running", GET .../status merges in live progress from
# AsyncResult(celery_task_id) (a Celery PROGRESS state carrying
# {"pct": ..., "message": ...}) so the frontend sees granular progress
# without the task ever touching the DB mid-run.
# ============================================================

from __future__ import annotations

import base64
import copy
import datetime
import os
import re
import tempfile
import uuid
from typing import Any, Dict, List, Optional

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.database import get_db
from app.dependencies.permissions import check_permission
from app.modules.staff.models import User
from app.modules.fttx_designer.cancellation import request_cancellation
from app.modules.fttx_designer.config_io import InvalidFttxConfigError, config_from_dict
from app.modules.fttx_designer.ded_report import generate_ded_report
from app.modules.fttx_designer.models import FttxDesignRun, FttxDesignRunLayer, FttxDesignRunOutput
from app.tasks.fttx_design_run import run_fttx_design_task

router = APIRouter()

_VALID_LAYER_KEYS = {"road", "homepass", "pole", "building", "pickup"}
_REQUIRED_LAYER_KEYS = {"road", "homepass", "pole"}


# ── Schemas ──────────────────────────────────────────────────────────────

class RunCreate(BaseModel):
    name: Optional[str] = None
    config: Dict[str, Any] = {}


class RunRerunIn(BaseModel):
    config_overrides: Dict[str, Any] = Field(default_factory=dict)


class RunOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: Optional[str]
    status: str
    config: Dict[str, Any]
    progress_pct: int
    progress_message: Optional[str]
    error_message: Optional[str]
    celery_task_id: Optional[str]
    result_summary: Optional[Dict[str, Any]]
    created_by: Optional[uuid.UUID]
    created_at: str
    updated_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    uploaded_layer_keys: List[str] = []

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_obj(cls, run: FttxDesignRun, uploaded_layer_keys: Optional[List[str]] = None) -> "RunOut":
        return cls(
            id=run.id,
            tenant_id=run.tenant_id,
            name=run.name,
            status=run.status,
            config=run.config or {},
            progress_pct=run.progress_pct,
            progress_message=run.progress_message,
            error_message=run.error_message,
            celery_task_id=run.celery_task_id,
            result_summary=run.result_summary,
            created_by=run.created_by,
            created_at=run.created_at.isoformat(),
            updated_at=run.updated_at.isoformat(),
            started_at=run.started_at.isoformat() if run.started_at else None,
            completed_at=run.completed_at.isoformat() if run.completed_at else None,
            uploaded_layer_keys=uploaded_layer_keys or [],
        )


class RunStatusOut(BaseModel):
    id: uuid.UUID
    status: str
    progress_pct: int
    progress_message: Optional[str]
    error_message: Optional[str]
    result_summary: Optional[Dict[str, Any]]


class LayerUploadIn(BaseModel):
    layer_key: str
    original_filename: Optional[str] = None
    geojson: Dict[str, Any]


_PROPERTY_KEY_SAMPLE_SIZE = 25


def _sample_property_keys(geojson: Optional[Dict[str, Any]]) -> List[str]:
    """Union of attribute/property names across the first N features of a
    stored layer's GeoJSON, sorted for a stable dropdown order. Used so the
    wizard can offer a "which field holds the homepass count" selector
    built from the layer's own real fields, instead of the user having to
    guess or match the engine's bare "Name" default blind."""
    if not geojson:
        return []
    features = geojson.get("features") or []
    keys: set[str] = set()
    for feat in features[:_PROPERTY_KEY_SAMPLE_SIZE]:
        props = feat.get("properties") if isinstance(feat, dict) else None
        if isinstance(props, dict):
            keys.update(props.keys())
    return sorted(keys)


class LayerOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    layer_key: str
    original_filename: Optional[str]
    feature_count: Optional[int]
    uploaded_at: str
    property_keys: List[str] = []

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_obj(cls, layer: FttxDesignRunLayer) -> "LayerOut":
        return cls(
            id=layer.id,
            run_id=layer.run_id,
            layer_key=layer.layer_key,
            original_filename=layer.original_filename,
            feature_count=layer.feature_count,
            uploaded_at=layer.uploaded_at.isoformat(),
            property_keys=_sample_property_keys(layer.geojson),
        )


class ResultsOut(BaseModel):
    run_id: uuid.UUID
    output_layers: Dict[str, Any]
    boq_rows: Optional[List[Any]]
    boq_fdt_rows: Optional[List[Any]]
    optical_loss_summary: Optional[Dict[str, Any]]
    project_identity: Optional[Dict[str, Any]]
    created_at: str

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_obj(cls, output: FttxDesignRunOutput) -> "ResultsOut":
        return cls(
            run_id=output.run_id,
            output_layers=output.output_layers,
            boq_rows=output.boq_rows,
            boq_fdt_rows=output.boq_fdt_rows,
            optical_loss_summary=output.optical_loss_summary,
            project_identity=output.project_identity,
            created_at=output.created_at.isoformat(),
        )


class DedReportOut(BaseModel):
    """Both DED report artifacts in one response — see ded_report.py's
    generate_ded_report(), which always produces the .docx and its
    warnings.txt together from a single generation pass (map rendering
    involves real network tile fetches, so this avoids making the client
    trigger generation twice for what the desktop tool always treated as
    one action). The .docx is base64-encoded; the frontend decodes it into
    a Blob to trigger a download, the same way it already does for the
    plain-text run log."""
    filename: str
    docx_base64: str
    warnings_filename: str
    warnings_text: str


# ── Helpers ──────────────────────────────────────────────────────────────

async def _get_run_or_404(db: AsyncSession, run_id: uuid.UUID) -> FttxDesignRun:
    run = await db.get(FttxDesignRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FTTx design run not found")
    return run


async def _uploaded_layer_keys(db: AsyncSession, run_id: uuid.UUID) -> List[str]:
    rows = (await db.execute(
        select(FttxDesignRunLayer.layer_key).where(FttxDesignRunLayer.run_id == run_id)
    )).scalars().all()
    return list(rows)


# ── Endpoints ────────────────────────────────────────────────────────────

@router.post("/fttx-designer/runs", status_code=status.HTTP_201_CREATED, response_model=RunOut)
async def create_run(
    body: RunCreate,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.edit")),
) -> RunOut:
    """Create a draft run. `config` is applied as overrides on top of
    FTTXConfig()'s own defaults at execution time — see config_io.py."""
    try:
        config_from_dict(body.config)  # validate now, fail fast on bad config
    except InvalidFttxConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    run = FttxDesignRun(
        tenant_id=caller.tenant_id,
        name=body.name,
        status="draft",
        config=body.config,
        created_by=caller.id,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return RunOut.from_orm_obj(run)


@router.get("/fttx-designer/runs", response_model=List[RunOut])
async def list_runs(
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.view")),
) -> List[RunOut]:
    rows = (await db.execute(
        select(FttxDesignRun)
        .where(FttxDesignRun.tenant_id == caller.tenant_id)
        .order_by(FttxDesignRun.created_at.desc())
    )).scalars().all()
    changed = False
    from app.modules.fttx_designer.cancellation import cancellation_requested
    for run in rows:
        if run.status in ("queued", "running") and run.celery_task_id and cancellation_requested(run.celery_task_id):
            run.status = "cancelling"
            run.progress_message = "Cancellation requested; stopping at the next safe checkpoint."
            changed = True
    if changed:
        await db.commit()
    return [RunOut.from_orm_obj(r) for r in rows]


@router.get("/fttx-designer/runs/{run_id}", response_model=RunOut)
async def get_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.view")),
) -> RunOut:
    run = await _get_run_or_404(db, run_id)
    keys = await _uploaded_layer_keys(db, run_id)
    return RunOut.from_orm_obj(run, uploaded_layer_keys=keys)


@router.put("/fttx-designer/runs/{run_id}/config", response_model=RunOut)
async def update_run_config(
    run_id: uuid.UUID,
    body: RunCreate,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.edit")),
) -> RunOut:
    """Update a run's name/config, any time before execution has been
    triggered (draft/layers_pending/ready — including once all required
    layers are already in and the run is sitting at "ready"). Refused
    once queued/running/completed/etc — editing config after execution
    started would desync it from what actually executed."""
    run = await _get_run_or_404(db, run_id)
    if run.status not in ("draft", "layers_pending", "ready"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot edit config for a run in status '{run.status}'",
        )
    try:
        config_from_dict(body.config)
    except InvalidFttxConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    run.name = body.name
    run.config = body.config
    await db.commit()
    await db.refresh(run)
    return RunOut.from_orm_obj(run)


@router.post("/fttx-designer/runs/{run_id}/layers/{layer_key}", status_code=status.HTTP_201_CREATED, response_model=LayerOut)
async def upload_layer(
    run_id: uuid.UUID,
    layer_key: str,
    body: LayerUploadIn,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.edit")),
) -> LayerOut:
    """Upload (or replace) one input layer's GeoJSON FeatureCollection.

    Re-uploading the same layer_key on the same run replaces the previous
    upload (uq_fttx_design_run_layers_run_key) rather than accumulating
    duplicates. Allowed any time before execution has been triggered
    (draft/layers_pending/ready) — a run sitting at "ready" must still be
    able to have a bad layer replaced without deleting the whole run.
    """
    if layer_key not in _VALID_LAYER_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid layer_key '{layer_key}'; expected one of {sorted(_VALID_LAYER_KEYS)}",
        )
    if body.layer_key != layer_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="layer_key in path and body must match",
        )
    if body.geojson.get("type") != "FeatureCollection":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="geojson must be a GeoJSON FeatureCollection",
        )

    run = await _get_run_or_404(db, run_id)
    if run.status not in ("draft", "layers_pending", "ready"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot upload layers for a run in status '{run.status}'",
        )

    existing = (await db.execute(
        select(FttxDesignRunLayer).where(
            FttxDesignRunLayer.run_id == run_id,
            FttxDesignRunLayer.layer_key == layer_key,
        )
    )).scalar_one_or_none()

    feature_count = len(body.geojson.get("features") or [])
    if existing is not None:
        existing.original_filename = body.original_filename
        existing.feature_count = feature_count
        existing.geojson = body.geojson
        existing.uploaded_by = caller.id
        existing.uploaded_at = datetime.datetime.now(datetime.timezone.utc)
        layer = existing
    else:
        layer = FttxDesignRunLayer(
            run_id=run_id,
            tenant_id=caller.tenant_id,
            layer_key=layer_key,
            original_filename=body.original_filename,
            feature_count=feature_count,
            geojson=body.geojson,
            uploaded_by=caller.id,
        )
        db.add(layer)

    uploaded_keys = set(await _uploaded_layer_keys(db, run_id)) | {layer_key}
    run.status = "ready" if _REQUIRED_LAYER_KEYS.issubset(uploaded_keys) else "layers_pending"

    await db.commit()
    await db.refresh(layer)
    return LayerOut.from_orm_obj(layer)


@router.get("/fttx-designer/runs/{run_id}/layers", response_model=List[LayerOut])
async def list_layers(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.view")),
) -> List[LayerOut]:
    await _get_run_or_404(db, run_id)
    rows = (await db.execute(
        select(FttxDesignRunLayer).where(FttxDesignRunLayer.run_id == run_id)
    )).scalars().all()
    return [LayerOut.from_orm_obj(r) for r in rows]


@router.get("/fttx-designer/runs/{run_id}/layers/{layer_key}/geojson")
async def get_layer_geojson(
    run_id: uuid.UUID,
    layer_key: str,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.view")),
) -> Dict[str, Any]:
    """Return one uploaded input layer's original GeoJSON on demand.

    Kept separate from the layer-list response so large uploads are only
    fetched when someone opens that layer's attribute table or map overlay.
    """
    if layer_key not in _VALID_LAYER_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found")
    await _get_run_or_404(db, run_id)
    layer = (await db.execute(
        select(FttxDesignRunLayer).where(
            FttxDesignRunLayer.run_id == run_id,
            FttxDesignRunLayer.layer_key == layer_key,
        )
    )).scalar_one_or_none()
    if layer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found")
    return layer.geojson


@router.post("/fttx-designer/runs/{run_id}/execute", response_model=RunOut)
async def execute_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.edit")),
) -> RunOut:
    """Trigger the Celery task. Requires status == 'ready' (road, homepass,
    and pole layers all uploaded)."""
    run = await _get_run_or_404(db, run_id)
    if run.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Run is not ready to execute (status='{run.status}'). "
                f"Required layers: {sorted(_REQUIRED_LAYER_KEYS)}"
            ),
        )

    run.status = "queued"
    task_id = str(uuid.uuid4())
    run.celery_task_id = task_id
    run.error_message = None
    await db.commit()
    try:
        run_fttx_design_task.apply_async(args=[str(run.id)], task_id=task_id)
    except Exception as exc:
        run.status = "failed"
        run.progress_message = "Failed to queue design"
        run.error_message = "The task queue is unavailable, so the design could not start. Try again shortly."
        run.completed_at = datetime.datetime.now(datetime.timezone.utc)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=run.error_message) from exc
    await db.refresh(run)
    return RunOut.from_orm_obj(run)


@router.post("/fttx-designer/runs/{run_id}/rerun", status_code=status.HTTP_201_CREATED, response_model=RunOut)
async def rerun_failed_run(
    run_id: uuid.UUID,
    payload: Optional[RunRerunIn] = None,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.edit")),
) -> RunOut:
    """Create and queue a new run from a failed run's saved config and layers."""
    source = await _get_run_or_404(db, run_id)
    if source.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FTTx design run not found")
    if source.status != "failed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed runs can be rerun")

    source_layers = (await db.execute(
        select(FttxDesignRunLayer).where(FttxDesignRunLayer.run_id == source.id)
    )).scalars().all()
    if not _REQUIRED_LAYER_KEYS.issubset({layer.layer_key for layer in source_layers}):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The failed run is missing required input layers")

    rerun_config = copy.deepcopy(source.config or {})
    config_overrides = (payload.config_overrides if payload else {}) or {}
    unsupported_overrides = set(config_overrides) - {"allow_documented_b2b_exceptions"}
    if unsupported_overrides:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported rerun config override(s): {sorted(unsupported_overrides)}",
        )
    rerun_config.update(config_overrides)
    try:
        config_from_dict(rerun_config)
    except InvalidFttxConfigError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    run = FttxDesignRun(
        tenant_id=caller.tenant_id,
        name=f"{(source.name or 'FTTx design')[:190]} (rerun)",
        status="queued",
        config=rerun_config,
        created_by=caller.id,
    )
    db.add(run)
    await db.flush()
    for layer in source_layers:
        db.add(FttxDesignRunLayer(
            run_id=run.id,
            tenant_id=caller.tenant_id,
            layer_key=layer.layer_key,
            original_filename=layer.original_filename,
            feature_count=layer.feature_count,
            geojson=copy.deepcopy(layer.geojson),
            uploaded_by=caller.id,
        ))
    task_id = str(uuid.uuid4())
    run.celery_task_id = task_id
    await db.commit()
    try:
        run_fttx_design_task.apply_async(args=[str(run.id)], task_id=task_id)
    except Exception as exc:
        run.status = "failed"
        run.progress_message = "Failed to queue design"
        run.error_message = "The task queue is unavailable, so the design could not start. Try again shortly."
        run.completed_at = datetime.datetime.now(datetime.timezone.utc)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=run.error_message) from exc
    await db.refresh(run)
    return RunOut.from_orm_obj(run, uploaded_layer_keys=[layer.layer_key for layer in source_layers])


@router.get("/fttx-designer/runs/{run_id}/status", response_model=RunStatusOut)
async def get_run_status(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.view")),
) -> RunStatusOut:
    """Poll run status. The DB row is authoritative for status/error/
    result_summary; while status == 'queued' or 'running', live progress
    is merged in from the Celery task's own PROGRESS state (a cheap Redis
    read via AsyncResult — see app/tasks/fttx_design_run.py)."""
    run = await _get_run_or_404(db, run_id)

    progress_pct = run.progress_pct
    progress_message = run.progress_message
    if run.status in ("queued", "running", "cancelling") and run.celery_task_id:
        # Must be built from the explicit `celery_app` import, not
        # `run_fttx_design_task.AsyncResult(...)`. run_fttx_design_task is a
        # @shared_task (see app/tasks/fttx_design_run.py), which binds
        # lazily to whatever Celery app is "current" the first time it's
        # touched. In this FastAPI process, app.modules.fttx_designer.router
        # (this module) gets imported before app.core.celery_app's real
        # "opsyn" app (the one with backend=redis://redis:6379/0) is ever
        # instantiated, so the shared task permanently bound itself to
        # Celery's auto-created bare `default` app instead — whose backend
        # is DisabledBackend, raising AttributeError on .state/.info.
        # celery_app.AsyncResult(...) sidesteps that entirely: it builds the
        # AsyncResult directly against the real, explicitly-configured app,
        # independent of which app the shared-task proxy happened to latch
        # onto.
        from app.modules.fttx_designer.cancellation import cancellation_requested, read_progress
        if cancellation_requested(run.celery_task_id):
            progress_message = "Cancellation requested; stopping at the next safe checkpoint."
        else:
            live_progress = read_progress(run.celery_task_id)
            if live_progress is not None:
                progress_pct = live_progress.get("pct", progress_pct)
                progress_message = live_progress.get("message", progress_message)
            else:
                try:
                    async_result = celery_app.AsyncResult(run.celery_task_id)
                    if async_result.state == "PROGRESS" and isinstance(async_result.info, dict):
                        progress_pct = async_result.info.get("pct", progress_pct)
                        progress_message = async_result.info.get("message", progress_message)
                except Exception:
                    # Progress is best-effort; the status endpoint should
                    # still return the last database checkpoint on Redis hiccups.
                    pass

    return RunStatusOut(
        id=run.id,
        status=run.status,
        progress_pct=progress_pct,
        progress_message=progress_message,
        error_message=run.error_message,
        result_summary=run.result_summary,
    )


@router.post("/fttx-designer/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.edit")),
) -> RunOut:
    run = await _get_run_or_404(db, run_id)
    if run.status in ("cancelled", "cancelling"):
        return RunOut.from_orm_obj(run)
    if run.status not in ("queued", "running") or not run.celery_task_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only queued or running design runs can be cancelled")

    try:
        request_cancellation(run.celery_task_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Cancellation service is unavailable; the run is still active") from exc

    if run.status == "queued":
        try:
            celery_app.control.revoke(run.celery_task_id, terminate=False)
        except Exception:
            # The Redis cancellation flag remains authoritative if broker
            # control is temporarily unavailable; the worker checks it before
            # entering the pipeline.
            pass
        run.status = "cancelled"
        run.progress_message = "Cancelled"
        run.error_message = "Design run cancelled before it started."
        run.completed_at = datetime.datetime.now(datetime.timezone.utc)
    else:
        run.status = "cancelling"
        run.progress_message = "Cancellation requested; stopping at the next safe checkpoint."
    await db.commit()
    await db.refresh(run)
    return RunOut.from_orm_obj(run)


@router.get("/fttx-designer/runs/{run_id}/results", response_model=ResultsOut)
async def get_run_results(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.view")),
) -> ResultsOut:
    run = await _get_run_or_404(db, run_id)
    if run.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run has not completed (status='{run.status}')",
        )
    output = (await db.execute(
        select(FttxDesignRunOutput).where(FttxDesignRunOutput.run_id == run_id)
    )).scalar_one_or_none()
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run is marked completed but has no output row — this is a server-side inconsistency",
        )
    return ResultsOut.from_orm_obj(output)


@router.get("/fttx-designer/runs/{run_id}/log", response_model=Dict[str, Optional[str]])
async def get_run_log(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.view")),
) -> Dict[str, Optional[str]]:
    """Full PerformanceLogger text for a completed run — same content a
    desktop run writes to fttx_run_*.log."""
    await _get_run_or_404(db, run_id)
    output = (await db.execute(
        select(FttxDesignRunOutput).where(FttxDesignRunOutput.run_id == run_id)
    )).scalar_one_or_none()
    log_text = output.log_text if output is not None else None
    if not log_text:
        run = await _get_run_or_404(db, run_id)
        log_text = run.log_text
    if not log_text:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No output for this run yet")
    return {"log_text": log_text}


def _safe_filename_stem(project_identity: Optional[Dict[str, Any]], run: FttxDesignRun) -> str:
    name = (project_identity or {}).get("project_name") or run.name or "FTTx_Deployment"
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")
    return stem or "FTTx_Deployment"


@router.post("/fttx-designer/runs/{run_id}/ded-report", response_model=DedReportOut)
async def generate_run_ded_report(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.view")),
) -> DedReportOut:
    """Generate the Detailed Engineering Design .docx + its warnings.txt for
    a completed run — the web equivalent of the desktop dialog's "Generate
    DED Report" button. Generated fresh on every call (never persisted) —
    same on-demand behavior as the desktop tool, so re-running it after
    reviewing the warnings file always reflects any change to the run's
    stored output.

    Map rendering does real synchronous work (matplotlib) plus outbound
    network calls (basemap tile fetches via contextily) that would block
    the event loop if awaited directly — run_in_threadpool() offloads the
    whole generate_ded_report() call to a worker thread instead.
    """
    run = await _get_run_or_404(db, run_id)
    if run.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run has not completed (status='{run.status}')",
        )
    output = (await db.execute(
        select(FttxDesignRunOutput).where(FttxDesignRunOutput.run_id == run_id)
    )).scalar_one_or_none()
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run is marked completed but has no output row — this is a server-side inconsistency",
        )

    stem = _safe_filename_stem(output.project_identity, run)
    with tempfile.TemporaryDirectory() as tmp_dir:
        docx_path = os.path.join(tmp_dir, f"{stem}_DED_Report.docx")
        try:
            result = await run_in_threadpool(
                generate_ded_report,
                output.output_layers,
                docx_path,
                optical_summary=output.optical_loss_summary,
                project_identity=output.project_identity,
                include_maps=True,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

        with open(result["report_path"], "rb") as f:
            docx_bytes = f.read()
        with open(result["warnings_path"], encoding="utf-8") as f:
            warnings_text = f.read()

    return DedReportOut(
        filename=f"{stem}_DED_Report.docx",
        docx_base64=base64.b64encode(docx_bytes).decode("ascii"),
        warnings_filename=f"{stem}_Warnings.txt",
        warnings_text=warnings_text,
    )


@router.delete(
    "/fttx-designer/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("fttx_designer.edit")),
) -> None:
    run = await _get_run_or_404(db, run_id)
    if run.status in ("queued", "running", "cancelling"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a run while it is queued, running, or cancelling — wait for it to stop first",
        )
    await db.delete(run)
    await db.commit()
