# ============================================================
# OPSYN APPROVAL ROUTER — app/modules/approval/router.py (Network GIS Phase 9)
#
#   GET    /designs/{id}/approvals            requests, steps, comments, gate   network.view
#   POST   /designs/{id}/submit               submit the design version         design.edit
#   POST   /designs/{id}/boq/submit           submit its BOQ (approved design)  design.edit
#   POST   /designs/{id}/reopen               approved design back to editing   design.edit
#   POST   /approvals/{id}/decide             approve / reject the open step    the step's key
#   POST   /approvals/{id}/withdraw           the submitter takes it back       network.view
#   POST   /approvals/{id}/comments           a review comment (asset / point)  network.view
#   PATCH  /approval-comments/{id}            resolve / reopen a comment        network.view
#   GET    /approvals/{id}/boq-diff           BOQ revision vs the previous one  network.view
# Deciding checks the open step's own feature key (design.review,
# design.approve, boq.review, boq.approve) in the service.
# ============================================================

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.permissions import check_permission
from app.modules.approval import service
from app.modules.design import service as design_service
from app.modules.design.audit import audited
from app.modules.staff.models import User

router = APIRouter()


class SubmitRequest(BaseModel):
    note: Optional[str] = Field(None, max_length=2000)


class DecideRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT", "approve", "reject"]
    comment: Optional[str] = Field(None, max_length=4000)


class CommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    asset_id: Optional[str] = None
    cable_id: Optional[str] = None
    lng: Optional[float] = Field(None, ge=-180, le=180)
    lat: Optional[float] = Field(None, ge=-90, le=90)


class ResolveRequest(BaseModel):
    resolved: bool = True


@router.get("/designs/{design_id}/approvals")
async def approvals(design_id: str, db: AsyncSession = Depends(get_db),
                    caller: User = Depends(check_permission("network.view"))):
    design = await design_service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await service.list_for_design(db, caller.tenant_id, caller, design)}


@router.post("/designs/{design_id}/submit", status_code=201)
async def submit_design(design_id: str, body: SubmitRequest, db: AsyncSession = Depends(get_db),
                        caller: User = Depends(audited("design.edit"))):
    design = await design_service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await service.submit_design(db, caller.tenant_id, caller, design, body.note)}


@router.post("/designs/{design_id}/boq/submit", status_code=201)
async def submit_boq(design_id: str, body: SubmitRequest, db: AsyncSession = Depends(get_db),
                     caller: User = Depends(audited("design.edit"))):
    design = await design_service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await service.submit_boq(db, caller.tenant_id, caller, design, body.note)}


@router.post("/designs/{design_id}/reopen")
async def reopen(design_id: str, db: AsyncSession = Depends(get_db), caller: User = Depends(audited("design.edit"))):
    design = await design_service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await service.reopen(db, caller.tenant_id, caller, design)}


@router.post("/approvals/{request_id}/decide")
async def decide(request_id: str, body: DecideRequest, db: AsyncSession = Depends(get_db),
                 caller: User = Depends(audited("network.view"))):
    return {"success": True, "data": await service.decide(db, caller.tenant_id, caller, request_id, body.decision, body.comment)}


@router.post("/approvals/{request_id}/withdraw")
async def withdraw(request_id: str, db: AsyncSession = Depends(get_db), caller: User = Depends(audited("network.view"))):
    return {"success": True, "data": await service.withdraw(db, caller.tenant_id, caller, request_id)}


@router.post("/approvals/{request_id}/comments", status_code=201)
async def comment(request_id: str, body: CommentRequest, db: AsyncSession = Depends(get_db),
                  caller: User = Depends(check_permission("network.view"))):
    return {"success": True, "data": await service.add_comment(db, caller.tenant_id, caller, request_id, body.body,
                                                               body.asset_id, body.cable_id, body.lng, body.lat)}


@router.patch("/approval-comments/{comment_id}")
async def resolve(comment_id: str, body: ResolveRequest, db: AsyncSession = Depends(get_db),
                  caller: User = Depends(check_permission("network.view"))):
    return {"success": True, "data": await service.resolve_comment(db, caller.tenant_id, caller, comment_id, body.resolved)}


@router.get("/approvals/{request_id}/boq-diff")
async def boq_diff(request_id: str, db: AsyncSession = Depends(get_db),
                   caller: User = Depends(check_permission("network.view"))):
    return {"success": True, "data": await service.boq_diff(db, caller.tenant_id, request_id)}
