# ============================================================
# OPSYN WORKFLOW ROUTER — app/modules/organisation/workflow_router.py
# FastAPI router for department workflow builder endpoints.
# Mount prefix in main.py: /api/v1/workflows
# ============================================================
from __future__ import annotations

import uuid
from typing import Optional, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import check_permission
from app.modules.staff.models import User
from app.modules.organisation.models import DeptWorkflow, DeptWorkflowEdge
import app.modules.organisation.workflow_service as svc

router = APIRouter()


# ── Pydantic request schemas ──────────────────────────────────────────────────

class CreateWorkflowRequest(BaseModel):
    name:            str
    description:     Optional[str] = None
    trigger_dept_id: Optional[uuid.UUID] = None


class UpdateWorkflowRequest(BaseModel):
    name:        Optional[str] = None
    description: Optional[str] = None


class AddEdgeRequest(BaseModel):
    from_dept_id:        Optional[uuid.UUID] = None
    to_dept_id:          uuid.UUID
    edge_order:          int
    label:               Optional[str] = None
    is_parallel:         bool = False
    parallel_group_id:   Optional[str] = None
    gate_requires_group: Optional[str] = None
    can_push_back:       bool = True
    expected_days:       Optional[int] = None


class UpdateEdgeRequest(BaseModel):
    label:               Optional[str] = None
    is_parallel:         bool = False
    parallel_group_id:   Optional[str] = None
    gate_requires_group: Optional[str] = None
    can_push_back:       bool = True
    expected_days:       Optional[int] = None
    edge_order:          Optional[int] = None


# ── Serialiser helpers ────────────────────────────────────────────────────────

def _edge_out(edge: DeptWorkflowEdge) -> dict[str, Any]:
    return {
        "id":                  str(edge.id),
        "workflow_id":         str(edge.workflow_id),
        "from_dept_id":        str(edge.from_dept_id) if edge.from_dept_id else None,
        "to_dept_id":          str(edge.to_dept_id),
        "edge_order":          edge.edge_order,
        "label":               edge.label,
        "is_parallel":         edge.is_parallel,
        "parallel_group_id":   edge.parallel_group_id,
        "gate_requires_group": edge.gate_requires_group,
        "can_push_back":       edge.can_push_back,
        "expected_days":       edge.expected_days,
        "created_at":          edge.created_at.isoformat() if edge.created_at else None,
    }


def _workflow_out(wf: DeptWorkflow, include_edges: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id":              str(wf.id),
        "name":            wf.name,
        "description":     wf.description,
        "trigger_dept_id": str(wf.trigger_dept_id) if wf.trigger_dept_id else None,
        "is_active":       wf.is_active,
        "is_draft":        wf.is_draft,
        "version":         wf.version,
        "created_by":      str(wf.created_by) if wf.created_by else None,
        "published_at":    wf.published_at.isoformat() if wf.published_at else None,
        "created_at":      wf.created_at.isoformat() if wf.created_at else None,
        "updated_at":      wf.updated_at.isoformat() if wf.updated_at else None,
    }
    if include_edges:
        out["edges"] = [_edge_out(e) for e in (wf.edges or [])]
    return out


# ── POST / — create workflow ──────────────────────────────────────────────────
@router.post("")
async def create_workflow(
    body: CreateWorkflowRequest,
    db:   AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("settings.admin")),
):
    wf = await svc.create_workflow(
        name=body.name,
        description=body.description,
        trigger_dept_id=body.trigger_dept_id,
        created_by=caller.id,
        db=db,
    )
    await db.commit()
    return {"success": True, "data": _workflow_out(wf)}


# ── GET / — list workflows ────────────────────────────────────────────────────
@router.get("")
async def list_workflows(
    active_only: bool = Query(True),
    db:   AsyncSession = Depends(get_db),
    _:    User = Depends(get_current_user),
):
    workflows = await svc.list_workflows(active_only=active_only, db=db)
    return {"success": True, "data": [_workflow_out(wf) for wf in workflows]}


# ── GET /{id} — get workflow with full graph ───────────────────────────────────
@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: uuid.UUID,
    db:          AsyncSession = Depends(get_db),
    _:           User = Depends(get_current_user),
):
    wf = await svc.get_workflow(workflow_id=workflow_id, db=db)
    if not wf:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found.")
    return {"success": True, "data": _workflow_out(wf, include_edges=True)}


# ── PUT /{id} — update name/description ──────────────────────────────────────
@router.put("/{workflow_id}")
async def update_workflow(
    workflow_id: uuid.UUID,
    body:        UpdateWorkflowRequest,
    db:          AsyncSession = Depends(get_db),
    _:           User = Depends(check_permission("settings.admin")),
):
    wf = await svc.update_workflow(
        workflow_id=workflow_id,
        name=body.name,
        description=body.description,
        db=db,
    )
    await db.commit()
    return {"success": True, "data": _workflow_out(wf)}


# ── POST /{id}/edges — add edge ───────────────────────────────────────────────
@router.post("/{workflow_id}/edges")
async def add_edge(
    workflow_id: uuid.UUID,
    body:        AddEdgeRequest,
    db:          AsyncSession = Depends(get_db),
    _:           User = Depends(check_permission("settings.admin")),
):
    edge = await svc.add_edge(
        workflow_id=workflow_id,
        from_dept_id=body.from_dept_id,
        to_dept_id=body.to_dept_id,
        edge_order=body.edge_order,
        label=body.label,
        is_parallel=body.is_parallel,
        parallel_group_id=body.parallel_group_id,
        gate_requires_group=body.gate_requires_group,
        can_push_back=body.can_push_back,
        expected_days=body.expected_days,
        db=db,
    )
    await db.commit()
    return {"success": True, "data": _edge_out(edge)}


# ── DELETE /{id}/edges/{edge_id} — remove edge ───────────────────────────────
@router.delete("/{workflow_id}/edges/{edge_id}")
async def remove_edge(
    workflow_id: uuid.UUID,
    edge_id:     uuid.UUID,
    db:          AsyncSession = Depends(get_db),
    _:           User = Depends(check_permission("settings.admin")),
):
    await svc.remove_edge(edge_id=edge_id, workflow_id=workflow_id, db=db)
    await db.commit()
    return {"success": True, "data": None}


# ── PUT /{id}/edges/{edge_id} — update edge ──────────────────────────────────
@router.put("/{workflow_id}/edges/{edge_id}")
async def update_edge(
    workflow_id: uuid.UUID,
    edge_id:     uuid.UUID,
    body:        UpdateEdgeRequest,
    db:          AsyncSession = Depends(get_db),
    _:           User = Depends(check_permission("settings.admin")),
):
    edge = await svc.update_edge(
        edge_id=edge_id,
        workflow_id=workflow_id,
        label=body.label,
        is_parallel=body.is_parallel,
        parallel_group_id=body.parallel_group_id,
        gate_requires_group=body.gate_requires_group,
        can_push_back=body.can_push_back,
        expected_days=body.expected_days,
        edge_order=body.edge_order,
        db=db,
    )
    await db.commit()
    return {"success": True, "data": _edge_out(edge)}


# ── POST /{id}/validate — validate graph ─────────────────────────────────────
@router.post("/{workflow_id}/validate")
async def validate_workflow(
    workflow_id: uuid.UUID,
    db:          AsyncSession = Depends(get_db),
    _:           User = Depends(check_permission("settings.admin")),
):
    result = await svc.validate_workflow_graph(workflow_id=workflow_id, db=db)
    return {"success": True, "data": {"is_valid": result.is_valid, "errors": result.errors}}


# ── POST /{id}/publish — publish workflow ─────────────────────────────────────
@router.post("/{workflow_id}/publish")
async def publish_workflow(
    workflow_id: uuid.UUID,
    db:          AsyncSession = Depends(get_db),
    caller:      User = Depends(check_permission("settings.admin")),
):
    wf = await svc.publish_workflow(
        workflow_id=workflow_id,
        actor_id=caller.id,
        db=db,
    )
    await db.commit()
    return {"success": True, "data": _workflow_out(wf)}


# ── POST /{id}/clone — clone workflow ─────────────────────────────────────────
@router.post("/{workflow_id}/clone")
async def clone_workflow(
    workflow_id: uuid.UUID,
    db:          AsyncSession = Depends(get_db),
    caller:      User = Depends(check_permission("settings.admin")),
):
    new_wf = await svc.clone_workflow(
        workflow_id=workflow_id,
        actor_id=caller.id,
        db=db,
    )
    await db.commit()
    return {"success": True, "data": _workflow_out(new_wf)}


# ── DELETE /{id} — delete draft workflow ──────────────────────────────────────
@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: uuid.UUID,
    db:          AsyncSession = Depends(get_db),
    _:           User = Depends(check_permission("settings.admin")),
):
    await svc.delete_workflow(workflow_id=workflow_id, db=db)
    await db.commit()
    return {"success": True, "data": None}
