# ============================================================
# OPSYN DEPLOYMENT ROUTER — app/modules/deployment/router.py (Network GIS Phase 10)
#
#   POST   /designs/{id}/deploy                 approved design → construction   deployment.update
#   GET    /designs/{id}/deployment             progress, roll-ups, variance     network.view
#   POST   /designs/{id}/deployment/progress    install / test / verify / fail   deployment.update
#   POST   /designs/{id}/deployment/asbuilt     where it was really installed    asbuilt.capture
#   POST   /designs/{id}/promote                verified → the live network      network.promote
# ============================================================

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.permissions import check_permission
from app.modules.deployment import service
from app.modules.design import service as design_service
from app.modules.design.audit import audited
from app.modules.staff.models import User

router = APIRouter()


class DeployRequest(BaseModel):
    note: Optional[str] = Field(None, max_length=2000)


class Item(BaseModel):
    kind: Literal["asset", "cable"]
    id: str


class ProgressRequest(BaseModel):
    items: list[Item] = Field(min_length=1, max_length=2000)
    action: Literal["install", "test", "verify", "fail"]
    note: Optional[str] = Field(None, max_length=2000)


class AsBuiltRequest(BaseModel):
    kind: Literal["asset", "cable"]
    id: str
    geometry: dict[str, Any]


@router.post("/designs/{design_id}/deploy", status_code=201)
async def deploy(design_id: str, body: DeployRequest, db: AsyncSession = Depends(get_db),
                 caller: User = Depends(audited("deployment.update"))):
    design = await design_service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await service.deploy(db, caller.tenant_id, caller, design, body.note)}


@router.get("/designs/{design_id}/deployment")
async def deployment(design_id: str, db: AsyncSession = Depends(get_db),
                     caller: User = Depends(check_permission("network.view"))):
    design = await design_service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await service.progress(db, caller.tenant_id, design)}


@router.post("/designs/{design_id}/deployment/progress")
async def advance(design_id: str, body: ProgressRequest, db: AsyncSession = Depends(get_db),
                  caller: User = Depends(audited("deployment.update"))):
    design = await design_service.load_design(db, caller.tenant_id, design_id)
    items = [i.model_dump() for i in body.items]
    return {"success": True, "data": await service.advance(db, caller.tenant_id, caller, design, items, body.action, body.note)}


@router.post("/designs/{design_id}/deployment/asbuilt")
async def asbuilt(design_id: str, body: AsBuiltRequest, db: AsyncSession = Depends(get_db),
                  caller: User = Depends(audited("asbuilt.capture"))):
    design = await design_service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await service.capture_asbuilt(db, caller.tenant_id, caller, design, body.kind, body.id,
                                                                    body.geometry)}


@router.post("/designs/{design_id}/promote")
async def promote(design_id: str, db: AsyncSession = Depends(get_db),
                  caller: User = Depends(audited("network.promote"))):
    design = await design_service.load_design(db, caller.tenant_id, design_id)
    return {"success": True, "data": await service.promote(db, caller.tenant_id, caller, design)}
