# ============================================================
# OPSYN WORKFLOW SERVICE — app/modules/organisation/workflow_service.py
# Async service layer for DeptWorkflow / DeptWorkflowEdge operations.
# ============================================================
from __future__ import annotations

import uuid
import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.organisation.models import DeptWorkflow, DeptWorkflowEdge
from app.modules.organisation.workflow_validator import (
    EdgeData,
    WorkflowValidationResult,
    validate_workflow,
)
from app.events.bus import event_bus
from app.modules.audit.service import audit_service


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_workflow_with_edges_query(workflow_id: uuid.UUID):
    """Return a select statement that eagerly loads edges + their dept relationships."""
    return (
        select(DeptWorkflow)
        .where(DeptWorkflow.id == workflow_id)
        .options(
            selectinload(DeptWorkflow.edges)
            .selectinload(DeptWorkflowEdge.from_dept),
            selectinload(DeptWorkflow.edges)
            .selectinload(DeptWorkflowEdge.to_dept),
        )
    )


async def _require_workflow(workflow_id: uuid.UUID, db: AsyncSession) -> DeptWorkflow:
    wf = (await db.execute(
        select(DeptWorkflow).where(DeptWorkflow.id == workflow_id)
    )).scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found.")
    return wf


async def _require_draft_workflow(workflow_id: uuid.UUID, db: AsyncSession) -> DeptWorkflow:
    wf = await _require_workflow(workflow_id, db)
    if not wf.is_draft:
        raise HTTPException(
            status_code=400,
            detail="This workflow is published and cannot be modified. Clone it to create a new draft.",
        )
    return wf


# ── 1. create_workflow ────────────────────────────────────────────────────────
async def create_workflow(
    name:            str,
    description:     Optional[str],
    trigger_dept_id: Optional[uuid.UUID],
    created_by:      uuid.UUID,
    db:              AsyncSession,
) -> DeptWorkflow:
    wf = DeptWorkflow(
        name=name,
        description=description,
        trigger_dept_id=trigger_dept_id,
        created_by=created_by,
        is_draft=True,
        is_active=True,
        version=1,
    )
    db.add(wf)
    await db.flush()
    await db.refresh(wf)
    return wf


# ── 2. get_workflow ───────────────────────────────────────────────────────────
async def get_workflow(workflow_id: uuid.UUID, db: AsyncSession) -> Optional[DeptWorkflow]:
    result = await db.execute(_load_workflow_with_edges_query(workflow_id))
    return result.scalar_one_or_none()


# ── 3. list_workflows ─────────────────────────────────────────────────────────
async def list_workflows(active_only: bool, db: AsyncSession) -> list[DeptWorkflow]:
    q = select(DeptWorkflow).order_by(DeptWorkflow.created_at.desc())
    if active_only:
        q = q.where(DeptWorkflow.is_active == True)  # noqa: E712
    result = await db.execute(q)
    return list(result.scalars().all())


# ── 4. update_workflow ────────────────────────────────────────────────────────
async def update_workflow(
    workflow_id: uuid.UUID,
    name:        Optional[str],
    description: Optional[str],
    db:          AsyncSession,
) -> DeptWorkflow:
    wf = await _require_draft_workflow(workflow_id, db)
    if name is not None:
        wf.name = name
    if description is not None:
        wf.description = description
    await db.flush()
    await db.refresh(wf)
    return wf


# ── 5. add_edge ───────────────────────────────────────────────────────────────
async def add_edge(
    workflow_id:         uuid.UUID,
    from_dept_id:        Optional[uuid.UUID],
    to_dept_id:          uuid.UUID,
    edge_order:          int,
    label:               Optional[str],
    is_parallel:         bool,
    parallel_group_id:   Optional[str],
    gate_requires_group: Optional[str],
    can_push_back:       bool,
    expected_days:       Optional[int],
    db:                  AsyncSession,
) -> DeptWorkflowEdge:
    await _require_draft_workflow(workflow_id, db)
    edge = DeptWorkflowEdge(
        workflow_id=workflow_id,
        from_dept_id=from_dept_id,
        to_dept_id=to_dept_id,
        edge_order=edge_order,
        label=label,
        is_parallel=is_parallel,
        parallel_group_id=parallel_group_id,
        gate_requires_group=gate_requires_group,
        can_push_back=can_push_back,
        expected_days=expected_days,
    )
    db.add(edge)
    await db.flush()
    await db.refresh(edge)
    return edge


# ── 6. remove_edge ────────────────────────────────────────────────────────────
async def remove_edge(
    edge_id:     uuid.UUID,
    workflow_id: uuid.UUID,
    db:          AsyncSession,
) -> None:
    await _require_draft_workflow(workflow_id, db)
    edge = (await db.execute(
        select(DeptWorkflowEdge)
        .where(DeptWorkflowEdge.id == edge_id, DeptWorkflowEdge.workflow_id == workflow_id)
    )).scalar_one_or_none()
    if not edge:
        raise HTTPException(status_code=404, detail=f"Edge {edge_id} not found in workflow {workflow_id}.")
    await db.delete(edge)
    await db.flush()


# ── 7. update_edge ────────────────────────────────────────────────────────────
async def update_edge(
    edge_id:             uuid.UUID,
    workflow_id:         uuid.UUID,
    label:               Optional[str],
    is_parallel:         bool,
    parallel_group_id:   Optional[str],
    gate_requires_group: Optional[str],
    can_push_back:       bool,
    expected_days:       Optional[int],
    edge_order:          Optional[int],
    db:                  AsyncSession,
) -> DeptWorkflowEdge:
    await _require_draft_workflow(workflow_id, db)
    edge = (await db.execute(
        select(DeptWorkflowEdge)
        .where(DeptWorkflowEdge.id == edge_id, DeptWorkflowEdge.workflow_id == workflow_id)
    )).scalar_one_or_none()
    if not edge:
        raise HTTPException(status_code=404, detail=f"Edge {edge_id} not found in workflow {workflow_id}.")

    edge.label               = label
    edge.is_parallel         = is_parallel
    edge.parallel_group_id   = parallel_group_id
    edge.gate_requires_group = gate_requires_group
    edge.can_push_back       = can_push_back
    edge.expected_days       = expected_days
    if edge_order is not None:
        edge.edge_order = edge_order

    await db.flush()
    await db.refresh(edge)
    return edge


# ── 8. validate_workflow_graph ────────────────────────────────────────────────
async def validate_workflow_graph(
    workflow_id: uuid.UUID,
    db:          AsyncSession,
) -> WorkflowValidationResult:
    edges_rows = (await db.execute(
        select(DeptWorkflowEdge).where(DeptWorkflowEdge.workflow_id == workflow_id)
    )).scalars().all()

    edge_data_list = [
        EdgeData(
            from_dept_id=str(e.from_dept_id) if e.from_dept_id else None,
            to_dept_id=str(e.to_dept_id),
            edge_order=e.edge_order,
            parallel_group_id=e.parallel_group_id,
            gate_requires_group=e.gate_requires_group,
            id=str(e.id),
        )
        for e in edges_rows
    ]
    return validate_workflow(edge_data_list)


# ── 9. publish_workflow ───────────────────────────────────────────────────────
async def publish_workflow(
    workflow_id: uuid.UUID,
    actor_id:    uuid.UUID,
    db:          AsyncSession,
) -> DeptWorkflow:
    wf = await _require_draft_workflow(workflow_id, db)

    # Validate graph before publishing
    result = await validate_workflow_graph(workflow_id, db)
    if not result.is_valid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Workflow graph validation failed. Fix all errors before publishing.",
                "errors": result.errors,
            },
        )

    before_state = {"is_draft": wf.is_draft, "published_at": None}
    wf.is_draft     = False
    wf.published_at = datetime.datetime.utcnow()
    await db.flush()
    await db.refresh(wf)

    await event_bus.emit("workflow.published", {
        "workflow_id": str(wf.id),
        "name":        wf.name,
        "actor_id":    str(actor_id),
        "published_at": wf.published_at.isoformat(),
    })

    await audit_service.log(
        db=db,
        actor_id=actor_id,
        action="workflow.published",
        target_type="dept_workflow",
        target_id=wf.id,
        before_state=before_state,
        after_state={"is_draft": False, "published_at": wf.published_at.isoformat()},
        tenant_id=wf.tenant_id,
    )

    return wf


# ── 10. clone_workflow ────────────────────────────────────────────────────────
async def clone_workflow(
    workflow_id: uuid.UUID,
    actor_id:    uuid.UUID,
    db:          AsyncSession,
) -> DeptWorkflow:
    original = (await db.execute(
        _load_workflow_with_edges_query(workflow_id)
    )).scalar_one_or_none()
    if not original:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found.")

    new_version = original.version + 1
    new_wf = DeptWorkflow(
        name=f"{original.name} (Draft v{new_version})",
        description=original.description,
        trigger_dept_id=original.trigger_dept_id,
        created_by=actor_id,
        is_draft=True,
        is_active=True,
        version=new_version,
    )
    db.add(new_wf)
    await db.flush()

    for orig_edge in original.edges:
        new_edge = DeptWorkflowEdge(
            workflow_id=new_wf.id,
            from_dept_id=orig_edge.from_dept_id,
            to_dept_id=orig_edge.to_dept_id,
            edge_order=orig_edge.edge_order,
            label=orig_edge.label,
            is_parallel=orig_edge.is_parallel,
            parallel_group_id=orig_edge.parallel_group_id,
            gate_requires_group=orig_edge.gate_requires_group,
            can_push_back=orig_edge.can_push_back,
            expected_days=orig_edge.expected_days,
        )
        db.add(new_edge)

    await db.flush()
    await db.refresh(new_wf)
    return new_wf


# ── 11. delete_workflow ───────────────────────────────────────────────────────
async def delete_workflow(workflow_id: uuid.UUID, db: AsyncSession) -> None:
    wf = await _require_workflow(workflow_id, db)
    if not wf.is_draft:
        raise HTTPException(
            status_code=400,
            detail="Published workflows cannot be deleted. Archive it instead.",
        )
    await db.delete(wf)
    await db.flush()


# ── 12. get_workflow_graph_for_project_start ──────────────────────────────────
async def get_workflow_graph_for_project_start(
    workflow_id: uuid.UUID,
    db:          AsyncSession,
) -> list[DeptWorkflowEdge]:
    wf = await _require_workflow(workflow_id, db)
    if wf.is_draft:
        raise HTTPException(
            status_code=400,
            detail="Cannot use a draft workflow to start a project. Publish it first.",
        )
    edges = (await db.execute(
        select(DeptWorkflowEdge)
        .where(DeptWorkflowEdge.workflow_id == workflow_id)
        .order_by(DeptWorkflowEdge.edge_order)
    )).scalars().all()
    return list(edges)
