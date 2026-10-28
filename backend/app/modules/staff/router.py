# ============================================================
# OPSYN STAFF ROUTER — app/modules/staff/router.py
# Fixed: removed response_model= so FastAPI returns plain JSON
# The service layer now returns dicts, not ORM objects.
# ============================================================

import uuid
from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import check_permission
from app.modules.staff.service import staff_service
from app.modules.staff.schemas import CreateStaffRequest, UpdateStaffRequest, UpdateStatusRequest
from app.modules.staff.models import User, StaffProfile

router = APIRouter()


@router.get("")
async def list_staff(
    page:      int            = Query(1, ge=1),
    size:      int            = Query(20, ge=1, le=500),
    search:    str | None     = None,
    dept_id:   uuid.UUID | None = None,
    role_id:   uuid.UUID | None = None,
    status:    str | None     = None,
    region_id: uuid.UUID | None = None,
    db:        AsyncSession   = Depends(get_db),
    caller:    User           = Depends(get_current_user),
):
    result = await staff_service.list(
        db, caller, page, size, search, dept_id, role_id, status, region_id
    )
    return {"success": True, "data": result}


@router.post("", status_code=201)
async def create_staff(
    payload: CreateStaffRequest,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("staff.create")),
):
    data = await staff_service.create(db, payload, caller)
    return {"success": True, "data": data}


@router.get("/check/email")
async def check_email(
    email: str,
    db:    AsyncSession = Depends(get_db),
    _:     User         = Depends(get_current_user),
):
    exists = (await db.execute(select(User.id).where(User.email == email))).first()
    return {"success": True, "data": {"available": not exists}}


@router.get("/check/username")
async def check_username(
    username: str,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(get_current_user),
):
    # Scoped to the caller's tenant: usernames are unique per tenant
    # (migration 0084), and a global probe would disclose usernames
    # belonging to other organisations.
    exists = (await db.execute(
        select(User.id).where(
            User.username == username, User.tenant_id == caller.tenant_id
        )
    )).first()
    return {"success": True, "data": {"available": not exists}}


@router.get("/{user_id}")
async def get_staff(
    user_id: uuid.UUID  = Path(...),
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(get_current_user),
):
    data = await staff_service.get(db, user_id, caller)
    return {"success": True, "data": data}


@router.put("/{user_id}")
async def update_staff(
    user_id: uuid.UUID          = Path(...),
    body:    UpdateStaffRequest = ...,
    db:      AsyncSession       = Depends(get_db),
    caller:  User               = Depends(check_permission("staff.create")),
):
    data = await staff_service.update(db, user_id, body, caller)
    return {"success": True, "data": data}


@router.delete("/{user_id}", status_code=200)
async def delete_staff(
    user_id: uuid.UUID  = Path(...),
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(get_current_user),
):
    """Soft-delete a staff member. Admin only."""
    data = await staff_service.delete(db, user_id, caller)
    return {"success": True, "data": data}


@router.patch("/{user_id}/status")
async def update_status(
    user_id: uuid.UUID        = Path(...),
    body:    UpdateStatusRequest = ...,
    db:      AsyncSession     = Depends(get_db),
    caller:  User             = Depends(check_permission("staff.create")),
):
    data = await staff_service.update_status(db, user_id, body.status, caller)
    return {"success": True, "data": data}


@router.get("/{user_id}/performance")
async def get_staff_performance(
    user_id: uuid.UUID  = Path(...),
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(get_current_user),
):
    """Return pre-computed efficiency score and component breakdown."""
    from sqlalchemy import text as _text
    profile_row = (await db.execute(
        select(StaffProfile).where(
            StaffProfile.user_id  == user_id,
            StaffProfile.tenant_id == caller.tenant_id,
        )
    )).scalars().first()
    if not profile_row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Staff profile not found")

    from datetime import datetime as _dt, timezone as _tz, timedelta
    cutoff = _dt.now(_tz.utc) - timedelta(days=30)

    stats = (await db.execute(
        _text("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'done')   AS done_count,
                COUNT(*)                                   AS total_count,
                COUNT(*) FILTER (WHERE status IN ('new','assigned','in_progress','review')) AS open_count,
                COUNT(*) FILTER (WHERE status = 'done'
                                   AND due_date IS NOT NULL
                                   AND updated_at <= due_date) AS on_time_count,
                AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 3600.0)
                    FILTER (WHERE status = 'done')          AS avg_hours
            FROM tasks
            WHERE tenant_id = :tid
              AND assigned_to = :uid
              AND created_at >= :cutoff
        """),
        {"tid": str(caller.tenant_id), "uid": str(user_id), "cutoff": cutoff},
    )).fetchone()

    done      = int(stats[0] or 0)
    total     = int(stats[1] or 0)
    open_cnt  = int(stats[2] or 0)
    on_time   = int(stats[3] or 0)
    avg_hours = float(stats[4] or 0)

    return {
        "success": True,
        "data": {
            "user_id": str(user_id),
            "efficiency_score":       float(profile_row.efficiency_score) if profile_row.efficiency_score is not None else None,
            "efficiency_computed_at": profile_row.efficiency_computed_at.isoformat() if profile_row.efficiency_computed_at else None,
            "lookback_days":          30,
            "tasks_assigned":         total,
            "tasks_done":             done,
            "tasks_open":             open_cnt,
            "tasks_on_time":          on_time,
            "avg_resolution_hours":   round(avg_hours, 1),
            "completion_rate_pct":    round(done / max(total, 1) * 100),
            "sla_adherence_pct":      round(on_time / max(done, 1) * 100) if done > 0 else 0,
        },
    }
