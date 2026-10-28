# ============================================================
# OPSYN ACTIVITY TIMELINE ROUTER — app/modules/activity/router.py
# GET/POST /tasks/{id}/timeline
# GET/POST /projects/{id}/timeline
# GET      /activity-timeline  (tenant-wide feed)
# ============================================================

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Path
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.modules.staff.models import User
from app.modules.activity.service import timeline_writer

router = APIRouter()


class TimelineCommentRequest(BaseModel):
    body: str
    meta: Optional[dict] = None
    mentions: list[str] = Field(default_factory=list)
    parent_id: Optional[uuid.UUID] = None


# ── Task timeline ─────────────────────────────────────────────

@router.get("/tasks/{task_id}/timeline")
async def get_task_timeline(
    task_id: uuid.UUID    = Path(...),
    page:    int          = Query(1, ge=1),
    size:    int          = Query(50, ge=1, le=200),
    db:      AsyncSession = Depends(get_db),
    _:       User         = Depends(get_current_user),
):
    result = await timeline_writer.get_entity_timeline(db, "task", task_id, page, size)
    return {"success": True, "data": result}


@router.post("/tasks/{task_id}/timeline", status_code=201)
async def post_task_comment(
    task_id: uuid.UUID             = Path(...),
    req:     TimelineCommentRequest = ...,
    db:      AsyncSession          = Depends(get_db),
    caller:  User                  = Depends(get_current_user),
):
    # Keep task timeline posts in the same persistent/threaded store as the
    # task Comments tab. The task service also writes the immutable timeline event.
    from app.modules.tasks.router import task_service, _author_dict

    comment, _ = await task_service.add_comment(
        db, task_id, req.body, caller,
        type="NORMAL", mentions=req.mentions, parent_id=req.parent_id,
    )
    await db.commit()
    author = _author_dict(caller)
    return {
        "success": True,
        "data": {
            "id": str(comment.id), "entity_type": "task", "entity_id": str(task_id),
            "event_type": "user_comment", "actor_id": str(caller.id),
            "actor_label": author["full_name"], "body": comment.body,
            "meta": {"mentions": comment.mentions or [], "comment_type": comment.type},
            "parent_id": str(comment.parent_id) if comment.parent_id else None,
            "mentions": comment.mentions or [], "is_system": False,
            "created_at": comment.created_at.isoformat(),
        },
    }


# ── Project timeline ──────────────────────────────────────────

@router.get("/projects/{project_id}/timeline")
async def get_project_timeline(
    project_id: uuid.UUID    = Path(...),
    page:       int          = Query(1, ge=1),
    size:       int          = Query(50, ge=1, le=200),
    db:         AsyncSession = Depends(get_db),
    _:          User         = Depends(get_current_user),
):
    result = await timeline_writer.get_entity_timeline(db, "project", project_id, page, size)
    return {"success": True, "data": result}


@router.post("/projects/{project_id}/timeline", status_code=201)
async def post_project_comment(
    project_id: uuid.UUID             = Path(...),
    req:        TimelineCommentRequest = ...,
    db:         AsyncSession          = Depends(get_db),
    caller:     User                  = Depends(get_current_user),
):
    event_id = await timeline_writer.write_user_comment(
        db, "project", project_id, caller.id, req.body, req.meta
    )
    return {"success": True, "data": {"id": str(event_id)}}


# ── Tenant-wide feed ──────────────────────────────────────────

@router.get("/activity-timeline")
async def get_global_timeline(
    entity_type: Optional[str]      = Query(None),
    page:        int                 = Query(1, ge=1),
    size:        int                 = Query(50, ge=1, le=200),
    db:          AsyncSession        = Depends(get_db),
    _:           User                = Depends(get_current_user),
):
    from sqlalchemy import select, func
    from app.modules.activity.models import ActivityTimeline

    base = select(ActivityTimeline)
    if entity_type:
        base = base.where(ActivityTimeline.entity_type == entity_type)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    items = (await db.execute(
        base.order_by(ActivityTimeline.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )).scalars().all()

    return {
        "success": True,
        "data": {
            "items":       [timeline_writer._serialize(e) for e in items],
            "total":       total,
            "page":        page,
            "size":        size,
            "total_pages": max(1, -(-total // size)),
        },
    }
