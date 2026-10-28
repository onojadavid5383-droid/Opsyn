# ============================================================
# OPSYN SHIFTS ROUTER — app/modules/shifts/router.py
# NOC shift scheduling: shifts, assignments, swap requests
# ============================================================

from __future__ import annotations

import datetime
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import check_permission
from app.modules.staff.models import User
from app.modules.shifts.models import Shift, ShiftAssignment, ShiftSwapRequest

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────

class ShiftCreate(BaseModel):
    name:       str
    shift_type: str = "day"
    start_time: str
    end_time:   str
    color:      str = "#06b6d4"


class AssignmentCreate(BaseModel):
    shift_id: uuid.UUID
    user_id:  uuid.UUID
    date:     str
    notes:    Optional[str] = None


class AssignmentStatusUpdate(BaseModel):
    status: str


class SwapRequestCreate(BaseModel):
    from_assignment_id: uuid.UUID
    to_user_id:         uuid.UUID
    reason:             Optional[str] = None


class SwapRequestRespond(BaseModel):
    status: str  # "approved" | "rejected"


# ── Serialisers ───────────────────────────────────────────────

def _shift(s: Shift) -> dict:
    return {
        "id":         str(s.id),
        "name":       s.name,
        "shift_type": s.shift_type,
        "start_time": s.start_time.strftime("%H:%M") if s.start_time else None,
        "end_time":   s.end_time.strftime("%H:%M")   if s.end_time   else None,
        "color":      s.color,
        "created_at": s.created_at.isoformat()       if s.created_at else None,
    }


def _assignment(a: ShiftAssignment) -> dict:
    return {
        "id":         str(a.id),
        "shift_id":   str(a.shift_id),
        "user_id":    str(a.user_id),
        "date":       a.date.isoformat() if a.date else None,
        "status":     a.status,
        "notes":      a.notes,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _swap(r: ShiftSwapRequest) -> dict:
    return {
        "id":                 str(r.id),
        "from_assignment_id": str(r.from_assignment_id),
        "to_user_id":         str(r.to_user_id),
        "reason":             r.reason,
        "status":             r.status,
        "responded_by":       str(r.responded_by) if r.responded_by else None,
        "responded_at":       r.responded_at.isoformat() if r.responded_at else None,
        "created_at":         r.created_at.isoformat() if r.created_at else None,
    }


# ── Shift templates ───────────────────────────────────────────

@router.get("/shifts")
async def list_shifts(db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    rows = (await db.execute(
        select(Shift).where(Shift.tenant_id == caller.tenant_id).order_by(Shift.name)
    )).scalars().all()
    return {"success": True, "data": [_shift(s) for s in rows]}


@router.post("/shifts", status_code=201)
async def create_shift(
    payload: ShiftCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    try:
        st = datetime.time.fromisoformat(payload.start_time)
        et = datetime.time.fromisoformat(payload.end_time)
    except ValueError:
        raise HTTPException(400, "start_time/end_time must be HH:MM or HH:MM:SS")
    s = Shift(
        tenant_id  = caller.tenant_id,
        name       = payload.name,
        shift_type = payload.shift_type,
        start_time = st,
        end_time   = et,
        color      = payload.color,
        created_by = caller.id,
    )
    db.add(s); await db.flush(); await db.commit()
    return {"success": True, "data": _shift(s)}


@router.delete("/shifts/{sid}", status_code=204)
async def delete_shift(
    sid: uuid.UUID = Path(...),
    db:  AsyncSession = Depends(get_db),
    _:   User         = Depends(check_permission("settings.admin")),
):
    s = (await db.execute(select(Shift).where(Shift.id == sid))).scalar_one_or_none()
    if not s: raise HTTPException(404, "Shift not found.")
    await db.delete(s); await db.commit()


# ── Weekly schedule ───────────────────────────────────────────

@router.get("/shifts/weekly")
async def get_weekly_schedule(
    week_start: str  = Query(..., description="ISO date YYYY-MM-DD for Monday of the week"),
    db:         AsyncSession = Depends(get_db),
    caller:     User         = Depends(get_current_user),
):
    try:
        start = datetime.date.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(400, "week_start must be YYYY-MM-DD")
    end = start + datetime.timedelta(days=6)

    assignments = (await db.execute(
        select(ShiftAssignment).where(
            ShiftAssignment.tenant_id == caller.tenant_id,
            ShiftAssignment.date >= start,
            ShiftAssignment.date <= end,
        ).order_by(ShiftAssignment.date, ShiftAssignment.user_id)
    )).scalars().all()

    # Enrich with shift + user info
    shift_ids = {a.shift_id for a in assignments}
    user_ids  = {a.user_id  for a in assignments}

    shifts_map: dict = {}
    if shift_ids:
        for s in (await db.execute(select(Shift).where(Shift.id.in_(shift_ids)))).scalars().all():
            shifts_map[s.id] = _shift(s)

    users_map: dict = {}
    if user_ids:
        from app.modules.staff.models import StaffProfile
        rows = (await db.execute(
            select(User, StaffProfile)
            .join(StaffProfile, StaffProfile.user_id == User.id, isouter=True)
            .where(User.id.in_(user_ids))
        )).all()
        for u, sp in rows:
            users_map[u.id] = {
                "id":         str(u.id),
                "name":       f"{sp.first_name} {sp.last_name}" if sp else u.email,
                "email":      u.email,
                "role_level": getattr(u, "role_level", None),
            }

    result = []
    for a in assignments:
        result.append({
            **_assignment(a),
            "shift": shifts_map.get(a.shift_id),
            "user":  users_map.get(a.user_id),
        })

    return {"success": True, "data": {"assignments": result, "week_start": week_start}}


# ── Assignments ───────────────────────────────────────────────

@router.get("/shifts/assignments")
async def list_assignments(
    date:   Optional[str]  = Query(None),
    user_id:Optional[str]  = Query(None),
    status: Optional[str]  = Query(None),
    db:     AsyncSession   = Depends(get_db),
    caller: User           = Depends(get_current_user),
):
    q = select(ShiftAssignment).where(ShiftAssignment.tenant_id == caller.tenant_id)
    if date:
        try:
            q = q.where(ShiftAssignment.date == datetime.date.fromisoformat(date))
        except ValueError:
            pass
    if user_id:
        try:
            q = q.where(ShiftAssignment.user_id == uuid.UUID(user_id))
        except ValueError:
            pass
    if status:
        q = q.where(ShiftAssignment.status == status)

    rows = (await db.execute(q.order_by(ShiftAssignment.date.desc()))).scalars().all()
    return {"success": True, "data": [_assignment(a) for a in rows]}


@router.post("/shifts/assignments", status_code=201)
async def create_assignment(
    payload: AssignmentCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("outage.manage")),
):
    try:
        date = datetime.date.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")

    # Conflict check: same user + same date + active shift
    existing = (await db.execute(
        select(ShiftAssignment).where(
            ShiftAssignment.tenant_id == caller.tenant_id,
            ShiftAssignment.user_id   == payload.user_id,
            ShiftAssignment.date      == date,
            ShiftAssignment.status.not_in(["cancelled"]),
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"User already has a shift assigned on {payload.date}.")

    a = ShiftAssignment(
        tenant_id  = caller.tenant_id,
        shift_id   = payload.shift_id,
        user_id    = payload.user_id,
        date       = date,
        notes      = payload.notes,
        status     = "scheduled",
        created_by = caller.id,
    )
    db.add(a); await db.flush(); await db.commit()
    return {"success": True, "data": _assignment(a)}


@router.patch("/shifts/assignments/{aid}/status")
async def update_assignment_status(
    aid:     uuid.UUID          = Path(...),
    payload: AssignmentStatusUpdate = ...,
    db:      AsyncSession       = Depends(get_db),
    caller:  User               = Depends(check_permission("outage.manage")),
):
    a = (await db.execute(select(ShiftAssignment).where(ShiftAssignment.id == aid))).scalar_one_or_none()
    if not a: raise HTTPException(404, "Assignment not found.")
    if payload.status not in ("scheduled", "confirmed", "cancelled", "swapped"):
        raise HTTPException(400, "Invalid status.")
    a.status = payload.status
    await db.flush(); await db.commit()
    return {"success": True, "data": _assignment(a)}


@router.delete("/shifts/assignments/{aid}", status_code=204)
async def delete_assignment(
    aid: uuid.UUID    = Path(...),
    db:  AsyncSession = Depends(get_db),
    _:   User         = Depends(check_permission("outage.manage")),
):
    a = (await db.execute(select(ShiftAssignment).where(ShiftAssignment.id == aid))).scalar_one_or_none()
    if not a: raise HTTPException(404, "Assignment not found.")
    await db.delete(a); await db.commit()


# ── Swap requests ─────────────────────────────────────────────

@router.get("/shifts/swap-requests")
async def list_swap_requests(
    status: Optional[str] = Query(None),
    db:     AsyncSession  = Depends(get_db),
    caller: User          = Depends(get_current_user),
):
    q = select(ShiftSwapRequest).where(ShiftSwapRequest.tenant_id == caller.tenant_id)
    if status:
        q = q.where(ShiftSwapRequest.status == status)
    rows = (await db.execute(q.order_by(ShiftSwapRequest.created_at.desc()))).scalars().all()
    return {"success": True, "data": [_swap(r) for r in rows]}


@router.post("/shifts/swap-requests", status_code=201)
async def create_swap_request(
    payload: SwapRequestCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(get_current_user),
):
    req = ShiftSwapRequest(
        tenant_id          = caller.tenant_id,
        from_assignment_id = payload.from_assignment_id,
        to_user_id         = payload.to_user_id,
        reason             = payload.reason,
        status             = "pending",
        created_by         = caller.id,
    )
    db.add(req); await db.flush(); await db.commit()
    return {"success": True, "data": _swap(req)}


@router.patch("/shifts/swap-requests/{rid}/respond")
async def respond_swap_request(
    rid:     uuid.UUID        = Path(...),
    payload: SwapRequestRespond = ...,
    db:      AsyncSession     = Depends(get_db),
    caller:  User             = Depends(check_permission("outage.manage")),
):
    req = (await db.execute(select(ShiftSwapRequest).where(ShiftSwapRequest.id == rid))).scalar_one_or_none()
    if not req: raise HTTPException(404, "Swap request not found.")
    if req.status != "pending": raise HTTPException(400, "Request already responded.")
    if payload.status not in ("approved", "rejected"):
        raise HTTPException(400, "status must be 'approved' or 'rejected'.")

    req.status       = payload.status
    req.responded_by = caller.id
    req.responded_at = datetime.datetime.utcnow()

    if payload.status == "approved":
        # Execute the swap: cancel original, create new assignment for to_user
        original = (await db.execute(
            select(ShiftAssignment).where(ShiftAssignment.id == req.from_assignment_id)
        )).scalar_one_or_none()
        if original:
            new_a = ShiftAssignment(
                tenant_id  = original.tenant_id,
                shift_id   = original.shift_id,
                user_id    = req.to_user_id,
                date       = original.date,
                status     = "scheduled",
                notes      = f"Swap from {str(req.from_assignment_id)[:8]}…",
                created_by = caller.id,
            )
            original.status = "swapped"
            db.add(new_a)

    await db.flush(); await db.commit()
    return {"success": True, "data": _swap(req)}
