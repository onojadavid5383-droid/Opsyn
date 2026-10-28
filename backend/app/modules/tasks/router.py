# ============================================================
# OPSYN TASKS MODULE — app/modules/tasks/router.py
# Phase 5 Full Workflow Engine Refactor.
#
# STATE MACHINE    : 7 controlled states — all moves via update_status()
# PIPELINE STAGES  : 5 stages (backlog/in_progress/review/unit_done/archive)
# COMMENT WORKFLOW : typed comments drive task transitions
# DUAL APPROVAL    : assignee mark-done + creator approve-done required
# SOFT DELETE      : admin soft-delete with mandatory reason; purge flow
# DEPARTMENT ROUTING: TaskDeptRouting history for external tasks
# AUDIT            : every action → AuditLog + TaskAuditEntry
# NOTIFICATIONS    : bulk dept, @mention, approval, push-back, deadline
# ============================================================

from __future__ import annotations
import uuid, datetime, re
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Integer, Float, or_
from sqlalchemy.orm import selectinload
from fastapi import APIRouter, Depends, Query, Path, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.core.database import get_db
from app.core.utils import get_client_ip
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import check_permission
from app.modules.projects.models import Project, ProjectPipelineStage
from app.modules.staff.models import User, StaffProfile
from app.modules.organisation.models import Department
from app.modules.activity.service import timeline_writer
from app.modules.tasks.models import (
    Task, TaskComment, TaskTag, TaskDependency, TaskAuditEntry,
    TaskAssignmentLog, TaskRejectionLog, TaskDeptRouting,
    ArchiveReference,
    TASK_STATES, PIPELINE_FLOW, ALLOWED_TRANSITIONS, TRANSITION_ROLE_REQUIREMENTS,
    COMMENT_TYPES, APPROVAL_KEYWORDS, REJECTION_KEYWORDS,
    SOURCE_APPS, TASK_SCOPES, TASK_PRIORITIES, TASK_STATUSES,
)
from app.modules.tasks.service import (
    task_workflow_service,
    _parse_mentions, _parse_archive_refs,
    _get_user_by_username, _get_task_by_ticket,
    _notify,
)


# ── Pydantic Schemas ──────────────────────────────────────────

class CreateTaskRequest(BaseModel):
    title:               str
    task_scope:          str                 = "internal"
    description:         Optional[str]       = None
    priority:            str                 = "medium"
    status:              str                 = "new"
    deadline:            Optional[str]       = None
    department_id:       Optional[uuid.UUID] = None
    project_id:          Optional[uuid.UUID] = None
    assignee_user_id:    Optional[uuid.UUID] = None
    responsible_user_id: Optional[uuid.UUID] = None
    pipeline_id:         Optional[uuid.UUID] = None
    stage_id:            Optional[uuid.UUID] = None
    dependent_task_ids:  list[uuid.UUID]     = []
    tags:                list[str]           = []
    estimated_hours:     Optional[float]     = None
    source_app:          Optional[str]       = None
    archive_refs:        list[uuid.UUID]     = []

    @field_validator("task_scope")
    def _validate_scope(cls, v):
        if v not in TASK_SCOPES:
            raise ValueError("task_scope must be 'internal' or 'external'")
        return v

    @field_validator("priority")
    def _validate_priority(cls, v):
        # Previously unvalidated: any string was accepted and stored, so a
        # task could carry a priority the UI has no colour or ordering for.
        if v not in TASK_PRIORITIES:
            raise ValueError(
                "priority must be one of: " + ", ".join(sorted(TASK_PRIORITIES))
            )
        return v

    @field_validator("status")
    def _validate_status(cls, v):
        if v not in TASK_STATUSES:
            raise ValueError(
                "status must be one of: " + ", ".join(sorted(TASK_STATUSES))
            )
        return v

    @field_validator("deadline", "department_id", "project_id",
                     "assignee_user_id", "responsible_user_id", mode="before")
    def _normalize_blank_strings(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class BlockRequest(BaseModel):
    block_reason: str


class UpdateStatusRequest(BaseModel):
    status: str


class AddCommentRequest(BaseModel):
    body:      str
    type:      str       = "NORMAL"
    mentions:  list[str] = []
    parent_id: Optional[uuid.UUID] = None

    @field_validator("type")
    def _validate_type(cls, v):
        if v not in COMMENT_TYPES:
            raise ValueError(f"Invalid comment type '{v}'. Must be one of: {COMMENT_TYPES}")
        return v


class TransitionRequest(BaseModel):
    to_status:   str
    comment:     Optional[AddCommentRequest] = None
    to_stage_id: Optional[uuid.UUID]         = None


class AddDependencyRequest(BaseModel):
    depends_on_task_id: uuid.UUID


class AssignRequest(BaseModel):
    assignee_user_id: uuid.UUID
    note:             Optional[str] = None
    skill_match:      bool          = False


class ReassignRequest(BaseModel):
    to_user_id: uuid.UUID
    reason:     Optional[str] = None


class ForwardRequest(BaseModel):
    to_user_id: uuid.UUID
    note:       Optional[str] = None


class ForwardDeptRequest(BaseModel):
    to_dept_id: uuid.UUID
    note:       Optional[str] = None


class PushBackRequest(BaseModel):
    to_user_id: Optional[uuid.UUID] = None
    reason:     str


class ReturnDeptRequest(BaseModel):
    reason: str


class EscalateRequest(BaseModel):
    note: str


class RejectDoneRequest(BaseModel):
    reason: str


class SoftDeleteRequest(BaseModel):
    reason: str


# ── State Machine — Pure Validation Logic ─────────────────────

def _flow_index(state: str) -> int:
    try:
        return PIPELINE_FLOW.index(state)
    except ValueError:
        return -1


def can_transition(
    from_state:              str,
    to_state:                str,
    user_role_level:         int,
    assignee_user_id:        Optional[uuid.UUID],
    dep_statuses:            list[str],
    has_unresolved_actions:  bool,
) -> tuple[bool, str]:
    if from_state == "archived":
        return False, "Archived tasks cannot be transitioned. Clone or reopen the task."
    allowed = ALLOWED_TRANSITIONS.get(from_state, [])
    if to_state not in allowed:
        return False, (
            f"Invalid transition: '{from_state}' → '{to_state}'. "
            f"Allowed next states: {allowed or ['none']}"
        )
    required_level = TRANSITION_ROLE_REQUIREMENTS.get(to_state, 1)
    if user_role_level < required_level:
        return False, (
            f"Your role level ({user_role_level}) is insufficient to move a task to "
            f"'{to_state}'. Required: {required_level}."
        )
    if to_state == "in_progress" and not assignee_user_id:
        return False, "Task must have an assignee before moving to In Progress."
    if to_state == "in_progress" and dep_statuses:
        blocked = [s for s in dep_statuses if s != "done"]
        if blocked:
            return False, (
                f"{len(blocked)} blocking dependenc{'y' if len(blocked) == 1 else 'ies'} "
                f"must be completed before starting this task."
            )
    is_forward = _flow_index(to_state) > _flow_index(from_state)
    if is_forward and has_unresolved_actions and to_state != "blocked":
        return False, "Unresolved ACTION comments must be resolved before moving forward."
    return True, ""


# ── Keyword helpers ───────────────────────────────────────────

def _contains_keyword(body: str, keywords: set) -> bool:
    lower = body.lower()
    return any(kw in lower for kw in keywords)


def _extract_mentions(body: str) -> list[str]:
    return list(set(re.findall(r"@([\w.\-]+)", body)))


# ── Ticket number generator ───────────────────────────────────

async def _generate_ticket_number(db: AsyncSession) -> str:
    year   = datetime.datetime.utcnow().year
    prefix = f"TSK-{year}-"
    max_seq = (await db.execute(
        select(func.max(cast(func.right(Task.ticket_number, 4), Integer)))
        .where(Task.ticket_number.like(f"{prefix}%"))
    )).scalar_one_or_none()
    return f"{prefix}{(max_seq or 0) + 1:04d}"


# ── Eager-load option builders ────────────────────────────────

def _with_rels():
    return [
        selectinload(Task.comments),
        selectinload(Task.tags),
        selectinload(Task.assignee),
        selectinload(Task.responsible_user),
        selectinload(Task.department),
    ]


def _with_rels_full():
    return [
        selectinload(Task.comments).selectinload(TaskComment.author),
        selectinload(Task.tags),
        selectinload(Task.assignee),
        selectinload(Task.responsible_user),
        selectinload(Task.department),
    ]


# ── Serialisers ───────────────────────────────────────────────

def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _author_dict(u) -> dict:
    sp = u.staff_profile if u else None
    return {
        "id":         str(u.id)     if u  else "",
        "full_name":  sp.full_name  if sp else (u.username if u else ""),
        "first_name": sp.first_name if sp else "",
        "last_name":  sp.last_name  if sp else "",
        "staff_code": sp.staff_code if sp else "",
    }


def _staff_summary(u) -> dict | None:
    if not u:
        return None
    sp = u.staff_profile
    if not sp:
        return {
            "id": str(u.id), "staff_code": "", "job_title": None,
            "first_name": u.username, "last_name": "", "full_name": u.username,
        }
    return {
        "id":         str(sp.id),
        "staff_code": sp.staff_code,
        "first_name": sp.first_name,
        "last_name":  sp.last_name,
        "full_name":  sp.full_name,
        "job_title":  sp.job_title,
    }


def _comment_dict(c: TaskComment) -> dict:
    return {
        "id":              str(c.id),
        "task_id":         str(c.task_id),
        "body":            c.body,
        "type":            getattr(c, "type", "NORMAL"),
        "mentions":        c.mentions or [] if hasattr(c, "mentions") else [],
        "parent_id":       str(c.parent_id) if c.parent_id else None,
        "approval_action": getattr(c, "approval_action", None),
        "is_resolved":     getattr(c, "is_resolved", False),
        "created_at":      c.created_at.isoformat(),
        "updated_at":      (c.updated_at.isoformat() if c.updated_at else c.created_at.isoformat()),
        "author":          _author_dict(c.author) if getattr(c, "author", None) else {},
        "replies":         [],
    }


def _build_comment_threads(raw_comments: list[TaskComment]) -> list[dict]:
    top_level  = [c for c in raw_comments if not c.parent_id]
    by_parent: dict[str, list] = {}
    for c in raw_comments:
        if c.parent_id:
            pid = str(c.parent_id)
            by_parent.setdefault(pid, []).append(c)

    result = []
    for c in sorted(top_level, key=lambda x: x.created_at):
        cd = _comment_dict(c)
        replies = sorted(by_parent.get(str(c.id), []), key=lambda x: x.created_at)
        cd["replies"] = [_comment_dict(r) for r in replies]
        result.append(cd)
    return result


def _task_dict(t: Task) -> dict:
    return {
        "id":                      str(t.id),
        "title":                   t.title,
        "description":             t.description,
        "priority":                t.priority,
        "status":                  t.status,
        "task_scope":              getattr(t, "task_scope", "internal"),
        "pipeline_stage":          getattr(t, "pipeline_stage", "backlog"),
        "previous_state":          t.previous_state,
        "state_changed_at":        t.state_changed_at.isoformat() if t.state_changed_at else None,
        "deadline":                t.deadline.isoformat() if t.deadline else None,
        "deadline_bucket":         t.deadline_bucket,
        "pipeline_id":             str(t.pipeline_id)  if t.pipeline_id  else None,
        "stage_id":                str(t.stage_id)     if t.stage_id     else None,
        "comment_count":           len(_as_list(t.comments)),
        "tags":                    [tg.tag for tg in _as_list(t.tags)],
        "department_id":           str(t.department_id) if t.department_id else None,
        "project_id":              str(t.project_id)   if t.project_id   else None,
        "department":              {"id": str(t.department.id), "name": t.department.name} if t.department else None,
        "assignee":                _staff_summary(t.assignee),
        "responsible_user":        _staff_summary(t.responsible_user),
        "created_by":              str(t.created_by),
        "ticket_number":           t.ticket_number,
        "block_reason":            t.block_reason,
        "estimated_hours":         t.estimated_hours,
        "source_app":              getattr(t, "source_app", None),
        "is_deleted":              getattr(t, "is_deleted", False),
        "is_reopened":             getattr(t, "is_reopened", False),
        "assignee_confirmed_done": getattr(t, "assignee_confirmed_done", False),
        "creator_approved_done":   getattr(t, "creator_approved_done", False),
        "created_at":              t.created_at.isoformat(),
        "updated_at":              t.updated_at.isoformat(),
    }


def _audit_dict(e: TaskAuditEntry) -> dict:
    return {
        "id":           str(e.id),
        "task_id":      str(e.task_id),
        "actor":        _staff_summary(e.actor) if e.actor else None,
        "from_state":   e.from_state,
        "to_state":     e.to_state,
        "trigger_type": e.trigger_type,
        "comment_id":   str(e.comment_id) if e.comment_id else None,
        "note":         e.note,
        "created_at":   e.created_at.isoformat(),
    }


# ── Legacy TaskService (preserves backward-compatible methods) ─

class TaskService:

    async def get_board(
        self, db: AsyncSession, caller: User,
        dept_id:     Optional[uuid.UUID] = None,
        assignee_id: Optional[uuid.UUID] = None,
    ) -> dict:
        q = select(Task).options(*_with_rels()).where(Task.is_deleted == False)  # noqa: E712
        if dept_id:     q = q.where(Task.department_id    == dept_id)
        if assignee_id: q = q.where(Task.assignee_user_id == assignee_id)
        tasks = (await db.execute(q)).scalars().all()

        board: dict[str, list | int] = {
            "pending_approval": [],
            "completed": [],
            "overdue": [], "today": [], "this_week": [],
            "next_week": [], "no_deadline": [], "backlog": [],
        }
        for t in tasks:
            bucket = t.deadline_bucket
            if bucket in board:
                board[bucket].append(_task_dict(t))  # type: ignore[index]
        board["total"] = len(tasks)
        return board

    async def get_my_tasks(self, db: AsyncSession, caller: User) -> list[dict]:
        rows = (await db.execute(
            select(Task).options(*_with_rels())
            .where(Task.assignee_user_id == caller.id, Task.is_deleted == False)  # noqa: E712
            .order_by(Task.deadline.asc().nullslast())
        )).scalars().all()
        return [_task_dict(t) for t in rows]

    async def list_tasks(
        self, db: AsyncSession,
        page: int = 1,
        size: int = 50,
        task_scope: Optional[str] = None,
    ) -> dict:
        base = select(Task).where(Task.is_deleted == False)  # noqa: E712
        if task_scope:
            base = base.where(Task.task_scope == task_scope)
        total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        rows  = (await db.execute(
            base.options(*_with_rels()).offset((page - 1) * size).limit(size)
        )).scalars().all()
        return {
            "items":       [_task_dict(t) for t in rows],
            "total":       total,
            "page":        page,
            "size":        size,
            "total_pages": max(1, -(-total // size)),
        }

    async def get_detail(self, db: AsyncSession, task_id: uuid.UUID) -> Task:
        task = (await db.execute(
            select(Task).options(*_with_rels_full())
            .where(Task.id == task_id, Task.is_deleted == False)  # noqa: E712
        )).scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found.")
        return task

    async def update_status(
        self,
        db:           AsyncSession,
        task_id:      uuid.UUID,
        new_state:    str,
        caller:       User,
        trigger_type: str = "manual",
        comment_id:   Optional[uuid.UUID] = None,
    ) -> Task:
        if new_state == "done":
            raise HTTPException(
                status_code=422,
                detail="Use the mark-done action to submit completion for approval.",
            )
        if new_state not in TASK_STATES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown state '{new_state}'. Valid states: {sorted(TASK_STATES)}",
            )
        task = (await db.execute(
            select(Task).where(Task.id == task_id, Task.is_deleted == False)  # noqa: E712
            .with_for_update()
        )).scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found.")

        from_state = task.status
        if from_state == "done":
            raise HTTPException(
                status_code=422,
                detail="This task is waiting for approval. Approve it or send it back for revision.",
            )
        if from_state == new_state:
            return (await db.execute(
                select(Task).options(*_with_rels()).where(Task.id == task_id)
            )).scalar_one()

        dep_statuses       = await self._get_dep_statuses(db, task_id)
        unresolved_actions = await self._has_unresolved_actions(db, task_id)
        role_level         = caller.role.level if caller.role else 1

        # Auto-assign the caller when they start work on an unassigned task.
        # "Start Work" semantically means self-assign + begin; the assignee
        # requirement in can_transition would otherwise reject this correctly
        # but unhelpfully.
        if new_state == "in_progress" and not task.assignee_user_id:
            task.assignee_user_id = caller.id
            db.add(TaskAssignmentLog(
                task_id=task.id,
                tenant_id=caller.tenant_id,
                assigned_by=caller.id,
                assigned_to=caller.id,
                to_dept_id=task.department_id,
                assignment_type="initial",
                note="Self-assigned on start",
            ))
            await db.flush()

        allowed, reason = can_transition(
            from_state=from_state,
            to_state=new_state,
            user_role_level=role_level,
            assignee_user_id=task.assignee_user_id,
            dep_statuses=dep_statuses,
            has_unresolved_actions=unresolved_actions,
        )
        if not allowed:
            raise HTTPException(status_code=422, detail=reason)

        # Guard: archive requires dual approval
        if new_state == "archived":
            if not getattr(task, "assignee_confirmed_done", False) or \
               not getattr(task, "creator_approved_done", False):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Dual approval required before archiving. "
                        "Step 1: Assignee must mark done. "
                        "Step 2: Creator must approve completion."
                    ),
                )

        now = datetime.datetime.utcnow()
        task.previous_state   = from_state
        task.status           = new_state
        task.state_changed_at = now
        # Sync pipeline stage
        task_workflow_service.sync_pipeline_stage(task, new_state)
        await db.flush()

        await self._create_system_comment(
            db, task_id,
            f"Task moved from '{from_state}' → '{new_state}'.",
            caller.id,
        )
        await self._log_audit(db, task_id, from_state, new_state, caller, trigger_type, comment_id)

        await timeline_writer.write_state_change(
            db, "task", task_id, caller.id, from_state, new_state,
            meta={"trigger_type": trigger_type},
        )

        if trigger_type != "automation":
            await self._run_automation_rules(db, task_id, new_state, caller)

        return (await db.execute(
            select(Task).options(*_with_rels()).where(Task.id == task_id)
        )).scalar_one()

    async def add_comment(
        self,
        db:        AsyncSession,
        task_id:   uuid.UUID,
        body:      str,
        caller:    User,
        type:      str             = "NORMAL",
        mentions:  list[str]       = [],
        parent_id: Optional[uuid.UUID] = None,
    ) -> tuple[TaskComment, Optional[str]]:
        if parent_id:
            parent = (await db.execute(
                select(TaskComment).where(TaskComment.id == parent_id)
            )).scalar_one_or_none()
            if not parent or str(parent.task_id) != str(task_id):
                raise HTTPException(status_code=422, detail="Parent comment not found on this task.")

        await self._get_or_404(db, task_id)   # 404 guard

        all_mentions = list(set(mentions + _extract_mentions(body)))

        comment = TaskComment(
            task_id=task_id,
            author_user_id=caller.id,
            body=body,
            type=type,
            mentions=all_mentions,
            parent_id=parent_id,
        )

        if type == "APPROVAL":
            if _contains_keyword(body, APPROVAL_KEYWORDS):
                comment.approval_action = "approved"
            elif _contains_keyword(body, REJECTION_KEYWORDS):
                comment.approval_action = "rejected"
            else:
                comment.approval_action = "pending"

        db.add(comment)
        await db.flush()

        # Parse and notify @mentions
        usernames = _parse_mentions(body)
        mention_user_ids = []
        for uname in set(usernames):
            user = await _get_user_by_username(db, uname, caller.tenant_id)
            if user and user.id != caller.id:
                mention_user_ids.append(str(user.id))
                preview = body[:150] + ("..." if len(body) > 150 else "")
                await _notify(
                    db, user.id, caller.tenant_id,
                    "task_mentioned",
                    f"{caller.username} mentioned you in a comment",
                    f'@{uname} was mentioned: "{preview}"',
                    action_url=f"/tasks/{task_id}",
                    sender_id=caller.id,
                    related_task_id=task_id,
                )
        comment.mentions = mention_user_ids or all_mentions

        # Parse @archive references
        arch_tickets = _parse_archive_refs(body)
        for ticket in arch_tickets:
            if ticket != "__search__":
                task_ref = await _get_task_by_ticket(db, ticket, caller.tenant_id)
                if task_ref:
                    db.add(ArchiveReference(
                        task_id=task_id,
                        referenced_archive_task_id=task_ref.id,
                        referenced_by=caller.id,
                        tenant_id=caller.tenant_id,
                    ))

        await db.flush()

        await timeline_writer.write_user_comment(
            db, "task", task_id, caller.id, body,
            meta={"comment_id": str(comment.id), "comment_type": type},
        )

        if type == "ACTION":
            await self._create_system_comment(
                db, task_id,
                f"ACTION required — posted by {caller.username}. Task cannot move forward until resolved.",
                None,
            )

        return comment, None

    async def resolve_comment(self, db, task_id, comment_id, caller):
        comment = await self._get_comment_or_404(db, task_id, comment_id)
        if comment.type != "ACTION":
            raise HTTPException(status_code=422, detail="Only ACTION comments can be resolved.")
        comment.is_resolved = True
        comment.updated_at  = datetime.datetime.utcnow()
        await db.flush()
        return comment

    async def approve_comment(self, db, task_id, comment_id, caller):
        comment = await self._get_comment_or_404(db, task_id, comment_id)
        if comment.type != "APPROVAL":
            raise HTTPException(status_code=422, detail="Only APPROVAL comments can be approved.")
        comment.approval_action = "approved"
        comment.updated_at      = datetime.datetime.utcnow()
        await db.flush()
        return comment

    async def reject_comment(self, db, task_id, comment_id, caller):
        comment = await self._get_comment_or_404(db, task_id, comment_id)
        if comment.type != "APPROVAL":
            raise HTTPException(status_code=422, detail="Only APPROVAL comments can be rejected.")
        comment.approval_action = "rejected"
        comment.updated_at      = datetime.datetime.utcnow()
        await db.flush()
        task = await self._get_or_404(db, task_id)
        if task.status == "review":
            await self.update_status(db, task_id, "in_progress", caller, trigger_type="comment", comment_id=comment.id)
        return comment

    async def get_status_board(self, db, caller, dept_id=None, assignee_id=None):
        q = select(Task).options(*_with_rels()).where(Task.is_deleted == False)  # noqa: E712
        if dept_id:     q = q.where(Task.department_id    == dept_id)
        if assignee_id: q = q.where(Task.assignee_user_id == assignee_id)
        tasks = (await db.execute(q)).scalars().all()
        board: dict[str, list | int] = {
            "new": [], "assigned": [], "in_progress": [],
            "review": [], "blocked": [], "done": [], "archived": [],
        }
        for t in tasks:
            if t.status in board:
                board[t.status].append(_task_dict(t))  # type: ignore[index]
        board["total"] = len(tasks)
        return board

    async def get_audit(self, db: AsyncSession, task_id: uuid.UUID) -> list[dict]:
        await self._get_or_404(db, task_id)
        entries = (await db.execute(
            select(TaskAuditEntry)
            .options(selectinload(TaskAuditEntry.actor))
            .where(TaskAuditEntry.task_id == task_id)
            .order_by(TaskAuditEntry.created_at.asc())
        )).scalars().all()
        return [_audit_dict(e) for e in entries]

    async def get_dependencies(self, db: AsyncSession, task_id: uuid.UUID) -> list[dict]:
        deps = (await db.execute(
            select(TaskDependency).where(TaskDependency.task_id == task_id)
        )).scalars().all()
        if not deps:
            return []
        dep_task_ids   = [d.depends_on_task_id for d in deps]
        dep_tasks_rows = (await db.execute(
            select(Task).options(selectinload(Task.assignee)).where(Task.id.in_(dep_task_ids))
        )).scalars().all()
        dep_task_map   = {t.id: t for t in dep_tasks_rows}
        result = []
        for dep in deps:
            t = dep_task_map.get(dep.depends_on_task_id)
            result.append({
                "id":                 str(dep.id),
                "task_id":            str(dep.task_id),
                "depends_on_task_id": str(dep.depends_on_task_id),
                "depends_on_task":    {
                    "id": str(t.id), "title": t.title, "status": t.status,
                    "assignee": _staff_summary(t.assignee),
                } if t else None,
                "created_at": dep.created_at.isoformat(),
            })
        return result

    async def add_dependency(self, db, task_id, depends_on_task_id, caller):
        if task_id == depends_on_task_id:
            raise HTTPException(status_code=422, detail="A task cannot depend on itself.")
        if await self._would_create_cycle(db, task_id, depends_on_task_id):
            raise HTTPException(status_code=422, detail="Adding this dependency would create a circular dependency.")
        await self._add_dependency_safe(db, task_id, depends_on_task_id)
        await db.flush()
        await self._create_system_comment(
            db, task_id,
            f"Dependency added: task #{depends_on_task_id} must be completed first.",
            caller.id,
        )
        deps = await self.get_dependencies(db, task_id)
        return next((d for d in deps if d["depends_on_task_id"] == str(depends_on_task_id)), {})

    async def remove_dependency(self, db, task_id, dependency_id, caller):
        dep = (await db.execute(
            select(TaskDependency)
            .where(TaskDependency.id == dependency_id, TaskDependency.task_id == task_id)
        )).scalar_one_or_none()
        if not dep:
            raise HTTPException(status_code=404, detail="Dependency not found.")
        await db.delete(dep)
        await db.flush()

    async def clone(self, db, task_id, caller, overrides=None):
        source        = await self._get_or_404(db, task_id)
        ticket_number = await _generate_ticket_number(db)
        new_task = Task(
            title=f"[Clone] {source.title}",
            description=source.description,
            priority=source.priority,
            status="new",
            state_changed_at=datetime.datetime.utcnow(),
            deadline=source.deadline,
            department_id=source.department_id,
            project_id=source.project_id,
            pipeline_id=source.pipeline_id,
            stage_id=source.stage_id,
            created_by=caller.id,
            tenant_id=source.tenant_id,
            ticket_number=ticket_number,
            estimated_hours=source.estimated_hours,
            task_scope=getattr(source, "task_scope", "internal"),
            pipeline_stage="backlog",
        )
        if overrides:
            for k, v in overrides.items():
                if hasattr(new_task, k):
                    setattr(new_task, k, v)
        db.add(new_task)
        await db.flush()
        for tag in _as_list(source.tags):
            db.add(TaskTag(task_id=new_task.id, tag=tag.tag))
        await self._create_system_comment(db, new_task.id, f"Task cloned from #{task_id}.", caller.id)
        await self._log_audit(db, new_task.id, None, "new", caller, "manual", note=f"Cloned from {task_id}")
        await db.flush()
        return (await db.execute(
            select(Task).options(*_with_rels()).where(Task.id == new_task.id)
        )).scalar_one()

    async def action_start(self, db, task_id, caller):
        return await self.update_status(db, task_id, "in_progress", caller)

    async def action_submit_review(self, db, task_id, caller):
        return await self.update_status(db, task_id, "review", caller)

    async def action_block(self, db, task_id, caller, block_reason):
        task = await self._get_or_404(db, task_id)
        task.block_reason = block_reason
        await db.flush()
        return await self.update_status(db, task_id, "blocked", caller)

    async def action_unblock(self, db, task_id, caller):
        await self.update_status(db, task_id, "in_progress", caller)
        raw = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()
        raw.block_reason = None
        await db.flush()
        return (await db.execute(
            select(Task).options(*_with_rels()).where(Task.id == task_id)
        )).scalar_one()

    async def action_done_intelligent(self, db, task_id, caller):
        task = await self._get_or_404(db, task_id)
        if task.project_id:
            remaining = (await db.execute(
                select(ProjectPipelineStage)
                .where(
                    ProjectPipelineStage.project_id == task.project_id,
                    ProjectPipelineStage.status.in_(["pending", "in_progress"]),
                )
                .order_by(ProjectPipelineStage.stage_order.asc())
            )).scalars().all()
            if remaining:
                ns = remaining[0]
                return {
                    "requires_routing": True,
                    "next_stage": {
                        "id": str(ns.id), "stage_name": ns.stage_name, "stage_order": ns.stage_order,
                    },
                }
        done_task = await task_workflow_service.mark_done(db, task_id, caller)
        return {"requires_routing": False, "task": _task_dict(done_task)}

    async def action_archive(self, db, task_id, caller):
        task = await self._get_or_404(db, task_id)
        if not getattr(task, "assignee_confirmed_done", False) or \
           not getattr(task, "creator_approved_done", False):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Dual approval required before archiving. "
                    "Step 1: Assignee must mark done. "
                    "Step 2: Creator must approve completion."
                ),
            )
        return await self.update_status(db, task_id, "archived", caller)

    # ── Internal helpers ──────────────────────────────────────

    async def _get_or_404(self, db: AsyncSession, task_id: uuid.UUID) -> Task:
        task = (await db.execute(
            select(Task).where(Task.id == task_id, Task.is_deleted == False)  # noqa: E712
        )).scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found.")
        return task

    async def _get_comment_or_404(self, db, task_id, comment_id):
        c = (await db.execute(
            select(TaskComment)
            .where(TaskComment.id == comment_id, TaskComment.task_id == task_id)
        )).scalar_one_or_none()
        if not c:
            raise HTTPException(status_code=404, detail="Comment not found on this task.")
        return c

    async def _get_dep_statuses(self, db, task_id):
        deps = (await db.execute(
            select(TaskDependency).where(TaskDependency.task_id == task_id)
        )).scalars().all()
        if not deps:
            return []
        dep_ids  = [d.depends_on_task_id for d in deps]
        statuses = (await db.execute(
            select(Task.status).where(Task.id.in_(dep_ids))
        )).scalars().all()
        return list(statuses)

    async def _has_unresolved_actions(self, db, task_id):
        count = (await db.execute(
            select(func.count()).select_from(
                select(TaskComment)
                .where(
                    TaskComment.task_id    == task_id,
                    TaskComment.type       == "ACTION",
                    TaskComment.is_resolved == False,  # noqa: E712
                ).subquery()
            )
        )).scalar_one()
        return count > 0

    async def _create_system_comment(self, db, task_id, body, actor_id=None):
        c = TaskComment(
            task_id=task_id,
            author_user_id=actor_id,
            body=body,
            type="SYSTEM",
            mentions=[],
        )
        db.add(c)
        await db.flush()
        return c

    async def _log_audit(self, db, task_id, from_state, to_state, caller, trigger_type, comment_id=None, note=None):
        entry = TaskAuditEntry(
            task_id=task_id,
            actor_id=caller.id,
            from_state=from_state,
            to_state=to_state,
            trigger_type=trigger_type,
            comment_id=comment_id,
            note=note,
        )
        db.add(entry)
        await db.flush()
        return entry

    async def _run_automation_rules(self, db, task_id, new_state, caller):
        task = await self._get_or_404(db, task_id)
        if task.deadline:
            is_overdue = task.deadline.replace(tzinfo=None) < datetime.datetime.utcnow()
            if is_overdue and new_state not in ("done", "archived"):
                await self._create_system_comment(
                    db, task_id,
                    f"Automation: Task deadline ({task.deadline.strftime('%d %b %Y')}) has passed. Consider escalating.",
                )
        if new_state == "done":
            blocking_for = (await db.execute(
                select(TaskDependency).where(TaskDependency.depends_on_task_id == task_id)
            )).scalars().all()
            for dep in blocking_for:
                all_statuses = await self._get_dep_statuses(db, dep.task_id)
                if all_statuses and all(s == "done" for s in all_statuses):
                    await self._create_system_comment(
                        db, dep.task_id,
                        "Automation: All blocking dependencies are now complete. "
                        "This task is ready to move to In Progress.",
                    )

    async def _add_dependency_safe(self, db, task_id, depends_on_task_id):
        existing = (await db.execute(
            select(TaskDependency)
            .where(
                TaskDependency.task_id == task_id,
                TaskDependency.depends_on_task_id == depends_on_task_id,
            )
        )).scalar_one_or_none()
        if existing:
            return existing
        dep = TaskDependency(task_id=task_id, depends_on_task_id=depends_on_task_id)
        db.add(dep)
        return dep

    async def _would_create_cycle(self, db, task_id, new_dep_id):
        visited: set[uuid.UUID] = set()
        queue: list[uuid.UUID] = [new_dep_id]
        while queue:
            current = queue.pop(0)
            if current == task_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            children = (await db.execute(
                select(TaskDependency.depends_on_task_id)
                .where(TaskDependency.task_id == current)
            )).scalars().all()
            queue.extend(children)
        return False


task_service = TaskService()


# ── Router ────────────────────────────────────────────────────

router = APIRouter()


# ── Static-path endpoints MUST come before /{task_id} ────────

@router.get("/board")
async def get_board(
    dept_id:     Optional[uuid.UUID] = None,
    assignee_id: Optional[uuid.UUID] = None,
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(get_current_user),
):
    board = await task_service.get_board(db, caller, dept_id, assignee_id)
    return {"success": True, "data": board}


@router.get("/my")
async def my_tasks(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(get_current_user),
):
    tasks = await task_service.get_my_tasks(db, caller)
    return {"success": True, "data": tasks}


@router.get("/status-board")
async def get_status_board(
    dept_id:     Optional[uuid.UUID] = None,
    assignee_id: Optional[uuid.UUID] = None,
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(get_current_user),
):
    board = await task_service.get_status_board(db, caller, dept_id, assignee_id)
    return {"success": True, "data": board}


@router.get("/deleted")
async def list_deleted_tasks(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("tasks.delete")),
):
    """Admin-only: list soft-deleted tasks."""
    base  = select(Task).where(Task.is_deleted == True)  # noqa: E712
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows  = (await db.execute(
        base.options(*_with_rels()).order_by(Task.deleted_at.desc())
        .offset((page - 1) * size).limit(size)
    )).scalars().all()
    return {"success": True, "data": {
        "items": [_task_dict(t) for t in rows], "total": total, "page": page, "size": size,
    }}


@router.get("/department-inbox")
async def department_inbox(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(get_current_user),
):
    """Managers/leads: unassigned external tasks in their department."""
    role_level = caller.role.level if caller.role else 1
    if role_level < 3:
        raise HTTPException(status_code=403, detail="Only managers or admins can view the department inbox.")
    sp = caller.staff_profile
    if not sp or not sp.department_id:
        raise HTTPException(status_code=422, detail="Staff profile missing department.")

    rows = (await db.execute(
        select(Task).options(*_with_rels())
        .where(
            Task.department_id   == sp.department_id,
            Task.is_deleted      == False,  # noqa: E712
            Task.pipeline_stage  != "archive",
            or_(
                Task.assignee_user_id.is_(None),
                Task.task_scope == "external",
            ),
        )
        .order_by(Task.created_at.asc())
    )).scalars().all()

    return {"success": True, "data": {"items": [_task_dict(t) for t in rows], "total": len(rows)}}


@router.get("/staff/department")
async def get_department_staff(
    search: Optional[str] = Query(None),
    size:   int           = Query(50, ge=1, le=200),
    db:     AsyncSession  = Depends(get_db),
    caller: User          = Depends(get_current_user),
):
    """Return staff in caller's department with workload counts (F.1.1)."""
    sp = caller.staff_profile
    if not sp or not sp.department_id:
        raise HTTPException(status_code=422, detail="You are not assigned to a department.")

    now = datetime.datetime.utcnow()

    # Subquery: active (non-archived, non-deleted) task count per user
    active_subq = (
        select(Task.assignee_user_id, func.count(Task.id).label("active_count"))
        .where(Task.is_deleted == False, Task.pipeline_stage != "archive")  # noqa: E712
        .group_by(Task.assignee_user_id)
        .subquery("active_tasks")
    )

    # Subquery: overdue task count per user
    overdue_subq = (
        select(Task.assignee_user_id, func.count(Task.id).label("overdue_count"))
        .where(
            Task.is_deleted     == False,  # noqa: E712
            Task.pipeline_stage != "archive",
            Task.deadline.isnot(None),
            Task.deadline       <  now,
        )
        .group_by(Task.assignee_user_id)
        .subquery("overdue_tasks")
    )

    q = (
        select(
            User, StaffProfile,
            func.coalesce(active_subq.c.active_count,    0).label("active_task_count"),
            func.coalesce(overdue_subq.c.overdue_count,  0).label("overdue_task_count"),
        )
        .join(StaffProfile, StaffProfile.user_id == User.id)
        .outerjoin(active_subq,  active_subq.c.assignee_user_id  == User.id)
        .outerjoin(overdue_subq, overdue_subq.c.assignee_user_id == User.id)
        .where(
            StaffProfile.department_id == sp.department_id,
            User.is_active             == True,  # noqa: E712
            User.id                    != caller.id,
        )
    )
    if search:
        pattern = f"%{search.lower()}%"
        q = q.where(or_(
            func.lower(StaffProfile.first_name + " " + StaffProfile.last_name).like(pattern),
            func.lower(StaffProfile.staff_code).like(pattern),
        ))
    q = q.limit(size)

    rows = (await db.execute(q)).all()
    data = []
    for user, prof, active_count, overdue_count in rows:
        data.append({
            "user_id":            str(user.id),
            "first_name":         prof.first_name,
            "last_name":          prof.last_name,
            "staff_code":         prof.staff_code,
            "job_title":          prof.job_title,
            "full_name":          prof.full_name,
            "active_task_count":  int(active_count),
            "overdue_task_count": int(overdue_count),
        })
    return {"success": True, "data": data}


@router.get("/pipeline")
async def get_pipeline_board(
    stage:  Optional[str] = Query(None),
    scope:  str           = Query("mine"),
    view:   Optional[str] = Query(None),  # E.1.1: pending_approvals | reopened
    db:     AsyncSession  = Depends(get_db),
    caller: User          = Depends(get_current_user),
):
    """Tasks grouped by pipeline stage for kanban view."""
    # E.1.1: pending_approvals — tasks awaiting creator sign-off
    if view == "pending_approvals":
        q = (
            select(Task)
            .options(*_with_rels())
            .where(
                Task.is_deleted             == False,  # noqa: E712
                Task.tenant_id              == caller.tenant_id,
                Task.assignee_confirmed_done == True,   # noqa: E712
                Task.creator_approved_done   == False,  # noqa: E712
                Task.status                 == "done",
            )
        )
        role_level = caller.role.level if caller.role else 1
        if role_level < 4:
            q = q.where(Task.created_by == caller.id)
        tasks = (await db.execute(q)).scalars().all()
        return {"success": True, "data": [_task_dict(t) for t in tasks]}

    # E.2.4: reopened — tasks that have been reopened from archive
    if view == "reopened":
        q = (
            select(Task)
            .options(*_with_rels())
            .where(
                Task.is_deleted   == False,  # noqa: E712
                Task.is_reopened  == True,   # noqa: E712
            )
        )
        tasks = (await db.execute(q)).scalars().all()
        return {"success": True, "data": [_task_dict(t) for t in tasks]}

    q = select(Task).options(*_with_rels()).where(Task.is_deleted == False)  # noqa: E712

    if scope == "mine":
        q = q.where(Task.assignee_user_id == caller.id)
    elif scope == "dept":
        sp = caller.staff_profile
        if sp and sp.department_id:
            q = q.where(Task.department_id == sp.department_id)
    # scope == "all" → no additional filter

    if stage:
        q = q.where(Task.pipeline_stage == stage)

    tasks = (await db.execute(q)).scalars().all()

    board: dict[str, list] = {s: [] for s in ["backlog", "in_progress", "review", "unit_done", "archive"]}
    for t in tasks:
        ps = getattr(t, "pipeline_stage", "backlog")
        if ps in board:
            board[ps].append(_task_dict(t))

    return {"success": True, "data": board}


@router.get("/archive/search")
async def archive_search(
    q:     str         = Query(..., min_length=2),
    limit: int         = Query(10, ge=1, le=50),
    db:    AsyncSession = Depends(get_db),
    caller: User        = Depends(get_current_user),
):
    """Full-text search across archived tasks for @archive autocomplete."""
    pattern = f"%{q}%"
    task_rows = (await db.execute(
        select(Task).where(
            Task.pipeline_stage == "archive",
            Task.is_deleted     == False,  # noqa: E712
            or_(
                Task.title.ilike(pattern),
                Task.description.ilike(pattern),
            ),
        ).limit(limit)
    )).scalars().all()

    project_rows = (await db.execute(
        select(Project).where(
            Project.pipeline_status == "completed",
            Project.auto_generated  == True,  # noqa: E712
            Project.name.ilike(pattern),
        ).limit(limit)
    )).scalars().all()

    results = []
    for t in task_rows:
        results.append({
            "id": str(t.id), "type": "task",
            "ticket_number": t.ticket_number,
            "title": t.title,
            "archived_at": t.updated_at.isoformat() if t.updated_at else None,
            "department_id": str(t.department_id) if t.department_id else None,
        })
    for p in project_rows:
        results.append({
            "id": str(p.id), "type": "project",
            "ticket_number": p.ticket_number,
            "title": p.name,
            "archived_at": p.pipeline_completed_at.isoformat() if p.pipeline_completed_at else None,
            "department_id": str(p.department_id) if p.department_id else None,
        })

    return {"success": True, "data": results[:limit]}


@router.get("")
async def list_tasks(
    page:       int            = Query(1, ge=1),
    size:       int            = Query(50, ge=1, le=200),
    task_scope: Optional[str]  = Query(None),
    db:         AsyncSession   = Depends(get_db),
    _:          User           = Depends(get_current_user),
):
    result = await task_service.list_tasks(db, page, size, task_scope)
    return {"success": True, "data": result}


# ── Create — routes to internal or external workflow ──────────

@router.post("", status_code=201)
async def create_task(
    payload: CreateTaskRequest,
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("tasks.manage")),
):
    if payload.task_scope == "external":
        task, project = await task_workflow_service.create_external_task(db, payload, caller)
        await db.commit()
        return {
            "success": True,
            "data": {
                "task":    _task_dict(task),
                "project": {
                    "id":            str(project.id),
                    "ticket_number": project.ticket_number,
                    "name":          project.name,
                    "auto_generated": project.auto_generated,
                },
            },
        }
    else:
        task = await task_workflow_service.create_internal_task(db, payload, caller)
        await db.commit()
        return {"success": True, "data": _task_dict(task)}


@router.post("/from-app/{source_app}", status_code=201)
async def create_task_from_app(
    source_app: str,
    payload:    CreateTaskRequest,
    db:         AsyncSession = Depends(get_db),
    caller:     User         = Depends(check_permission("tasks.manage")),
):
    """External app integration endpoint — forces task_scope='external'."""
    if source_app not in SOURCE_APPS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid source_app '{source_app}'. Must be one of: {sorted(SOURCE_APPS)}",
        )
    payload.task_scope = "external"
    task, project = await task_workflow_service.create_external_task(db, payload, caller, source_app=source_app)
    await db.commit()
    return {
        "success": True,
        "data": {
            "task":       _task_dict(task),
            "project":    {"id": str(project.id), "ticket_number": project.ticket_number, "name": project.name},
            "source_app": source_app,
        },
    }


@router.put("/{task_id}")
async def update_task(
    task_id: uuid.UUID         = Path(...),
    payload: CreateTaskRequest = ...,
    db:      AsyncSession      = Depends(get_db),
    caller:  User              = Depends(get_current_user),
):
    task = await task_service.update_status(db, task_id, payload.status, caller)
    return {"success": True, "data": _task_dict(task)}


@router.patch("/{task_id}/status")
async def update_task_status(
    task_id: uuid.UUID           = Path(...),
    req:     UpdateStatusRequest = ...,
    db:      AsyncSession        = Depends(get_db),
    caller:  User                = Depends(get_current_user),
):
    task = await task_service.update_status(db, task_id, req.status, caller)
    return {"success": True, "data": _task_dict(task)}


# ── Full transition endpoint ──────────────────────────────────

@router.post("/{task_id}/transition")
async def transition_task(
    task_id: uuid.UUID        = Path(...),
    req:     TransitionRequest = ...,
    db:      AsyncSession     = Depends(get_db),
    caller:  User             = Depends(get_current_user),
):
    comment_id: Optional[uuid.UUID] = None
    if req.comment:
        comment, _ = await task_service.add_comment(
            db, task_id, req.comment.body, caller,
            type=req.comment.type,
            mentions=req.comment.mentions,
            parent_id=req.comment.parent_id,
        )
        comment_id = comment.id
    task = await task_service.update_status(
        db, task_id, req.to_status, caller, trigger_type="manual", comment_id=comment_id,
    )
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


# ── Phase 5: Assignment endpoints ─────────────────────────────

@router.post("/{task_id}/assign")
async def assign_task(
    task_id: uuid.UUID     = Path(...),
    req:     AssignRequest = ...,
    db:      AsyncSession  = Depends(get_db),
    caller:  User          = Depends(get_current_user),
    request: Request       = ...,
):
    task = await task_workflow_service.assign_task(
        db, task_id, req.assignee_user_id, caller, note=req.note,
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


@router.post("/{task_id}/reassign")
async def reassign_task(
    task_id: uuid.UUID       = Path(...),
    req:     ReassignRequest = ...,
    db:      AsyncSession    = Depends(get_db),
    caller:  User            = Depends(get_current_user),
):
    task = await task_workflow_service.reassign_task(db, task_id, req.to_user_id, caller, reason=req.reason)
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


# ── Phase 11: Forward / Push-Back / Dept Routing ─────────────

@router.post("/{task_id}/forward")
async def forward_task(
    task_id: uuid.UUID      = Path(...),
    req:     ForwardRequest = ...,
    db:      AsyncSession   = Depends(get_db),
    caller:  User           = Depends(get_current_user),
    request: Request        = ...,
):
    task = await task_workflow_service.forward_task(
        db, task_id, req.to_user_id, caller, note=req.note,
    )
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


@router.post("/{task_id}/push-back")
async def push_back_task(
    task_id: uuid.UUID       = Path(...),
    req:     PushBackRequest = ...,
    db:      AsyncSession    = Depends(get_db),
    caller:  User            = Depends(get_current_user),
    request: Request         = ...,
):
    task = await task_workflow_service.push_back_task(
        db, task_id, req.reason, caller,
        to_user_id=req.to_user_id,
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


@router.post("/{task_id}/forward-dept")
async def forward_dept(
    task_id: uuid.UUID         = Path(...),
    req:     ForwardDeptRequest = ...,
    db:      AsyncSession      = Depends(get_db),
    caller:  User              = Depends(get_current_user),
):
    task = await task_workflow_service.forward_dept(db, task_id, req.to_dept_id, caller, note=req.note)
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


@router.post("/{task_id}/return-dept")
async def return_dept(
    task_id: uuid.UUID         = Path(...),
    req:     ReturnDeptRequest = ...,
    db:      AsyncSession      = Depends(get_db),
    caller:  User              = Depends(get_current_user),
):
    task = await task_workflow_service.return_dept(db, task_id, req.reason, caller)
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


@router.post("/{task_id}/escalate")
async def escalate_task(
    task_id: uuid.UUID       = Path(...),
    req:     EscalateRequest = ...,
    db:      AsyncSession    = Depends(get_db),
    caller:  User            = Depends(get_current_user),
    request: Request         = ...,
):
    task = await task_workflow_service.escalate_task(
        db, task_id, req.note, caller, ip_address=get_client_ip(request),
    )
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


# ── Phase 8: Dual Approval ────────────────────────────────────

@router.post("/{task_id}/mark-done")
async def mark_done(
    task_id: uuid.UUID    = Path(...),
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(get_current_user),
    request: Request      = ...,
):
    task = await task_workflow_service.mark_done(db, task_id, caller, ip_address=get_client_ip(request))
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


@router.post("/{task_id}/approve-done")
async def approve_done(
    task_id: uuid.UUID    = Path(...),
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(get_current_user),
    request: Request      = ...,
):
    task = await task_workflow_service.approve_done(db, task_id, caller, ip_address=get_client_ip(request))
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


@router.post("/{task_id}/reject-done")
async def reject_done(
    task_id: uuid.UUID         = Path(...),
    req:     RejectDoneRequest = ...,
    db:      AsyncSession      = Depends(get_db),
    caller:  User              = Depends(get_current_user),
    request: Request           = ...,
):
    task = await task_workflow_service.reject_done(
        db, task_id, req.reason, caller, ip_address=get_client_ip(request),
    )
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


# ── Explicit action shortcuts ─────────────────────────────────

@router.post("/{task_id}/start")
async def start_task(task_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    task = await task_service.action_start(db, task_id, caller)
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


@router.post("/{task_id}/submit-review")
async def submit_task_for_review(task_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    task = await task_service.action_submit_review(db, task_id, caller)
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


@router.post("/{task_id}/block")
async def block_task(task_id: uuid.UUID = Path(...), req: BlockRequest = ..., db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    task = await task_service.action_block(db, task_id, caller, req.block_reason)
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


@router.post("/{task_id}/unblock")
async def unblock_task(task_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    task = await task_service.action_unblock(db, task_id, caller)
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


@router.post("/{task_id}/done")
async def done_task(task_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    result = await task_service.action_done_intelligent(db, task_id, caller)
    if not result["requires_routing"]:
        await db.commit()
    return {"success": True, "data": result}


@router.post("/{task_id}/archive")
async def archive_task(task_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    task = await task_service.action_archive(db, task_id, caller)
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


# ── E.2.1: Reopen archived task ───────────────────────────────

@router.post("/{task_id}/reopen")
async def reopen_task(
    task_id: uuid.UUID    = Path(...),
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(get_current_user),
    request: Request      = ...,
):
    # reopen_task lives on TaskWorkflowService, not the router-local
    # TaskService. Calling it on the wrong object raised AttributeError,
    # so this endpoint returned 500 on every request.
    task = await task_workflow_service.reopen_task(
        db, task_id, caller, ip_address=get_client_ip(request)
    )
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


# ── Phase 12: Soft-Delete / Restore / Purge ──────────────────

@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: uuid.UUID        = Path(...),
    req:     SoftDeleteRequest = ...,
    db:      AsyncSession     = Depends(get_db),
    caller:  User             = Depends(check_permission("tasks.delete")),
    request: Request          = ...,
):
    await task_workflow_service.soft_delete(db, task_id, req.reason, caller, ip=get_client_ip(request))
    await db.commit()


@router.post("/{task_id}/restore")
async def restore_task(
    task_id: uuid.UUID    = Path(...),
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("tasks.delete")),
    request: Request      = ...,
):
    task = await task_workflow_service.restore_task(db, task_id, caller, ip_address=get_client_ip(request))
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


@router.delete("/{task_id}/purge", status_code=204)
async def purge_task(
    task_id: uuid.UUID    = Path(...),
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("tasks.delete")),
    request: Request      = ...,
):
    await task_workflow_service.purge_task(db, task_id, caller, ip_address=get_client_ip(request))
    await db.commit()


# ── Phase 7: Pipeline history ─────────────────────────────────

@router.get("/{task_id}/pipeline-history")
async def get_pipeline_history(
    task_id: uuid.UUID    = Path(...),
    db:      AsyncSession = Depends(get_db),
    _:       User         = Depends(get_current_user),
):
    routing = (await db.execute(
        select(TaskDeptRouting)
        .options(selectinload(TaskDeptRouting.department))
        .where(TaskDeptRouting.task_id == task_id)
        .order_by(TaskDeptRouting.routing_order.asc())
    )).scalars().all()

    stages = []
    for r in routing:
        stages.append({
            "id":           str(r.id),
            "dept":         {"id": str(r.department_id), "name": r.department.name if r.department else None},
            "routing_order": r.routing_order,
            "entered_at":   r.entered_at.isoformat() if r.entered_at else None,
            "exited_at":    r.exited_at.isoformat()  if r.exited_at  else None,
            "exit_reason":  r.exit_reason,
            "is_current":   r.is_current,
            "assigned_to_user_id": str(r.assigned_to_user_id) if r.assigned_to_user_id else None,
        })

    return {"success": True, "data": {"stages": stages}}


# ── Phase 10: Unified activity timeline ───────────────────────

@router.get("/{task_id}/timeline")
async def get_task_timeline(
    task_id: uuid.UUID    = Path(...),
    db:      AsyncSession = Depends(get_db),
    _:       User         = Depends(get_current_user),
):
    """Unified chronological feed in TimelineEntry format consumed by ActivityTimeline."""
    task = (await db.execute(
        select(Task).where(Task.id == task_id)
    )).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    events: list[dict] = []
    tid = str(task_id)

    # Comments
    comments = (await db.execute(
        select(TaskComment)
        .options(selectinload(TaskComment.author).selectinload(User.staff_profile))
        .where(TaskComment.task_id == task_id)
        .order_by(TaskComment.created_at.asc())
    )).scalars().all()
    for c in comments:
        events.append({
            "id":          str(c.id),
            "entity_type": "task",
            "entity_id":   tid,
            "event_type":  "user_comment",
            "actor_id":    str(c.author.id)       if c.author else None,
            "actor_label": (c.author.staff_profile.full_name if c.author.staff_profile else c.author.username) if c.author else "System",
            "body":        c.body or "",
            "meta":        {
                "mentions":        c.mentions,
                "approval_action": c.approval_action,
                "is_resolved":     c.is_resolved,
                "comment_type":    c.type,
            },
            "is_system":   c.type == "SYSTEM",
            "created_at":  c.created_at.isoformat(),
        })

    # State changes (audit entries)
    audit_entries = (await db.execute(
        select(TaskAuditEntry)
        .options(selectinload(TaskAuditEntry.actor).selectinload(User.staff_profile))
        .where(TaskAuditEntry.task_id == task_id)
        .order_by(TaskAuditEntry.created_at.asc())
    )).scalars().all()
    for e in audit_entries:
        events.append({
            "id":          str(e.id),
            "entity_type": "task",
            "entity_id":   tid,
            "event_type":  "state_change",
            "actor_id":    str(e.actor.id)        if e.actor else None,
            "actor_label": (e.actor.staff_profile.full_name if e.actor.staff_profile else e.actor.username) if e.actor else "System",
            "body":        e.note or f"Status changed from {e.from_state} to {e.to_state}",
            "meta":        {"from_state": e.from_state, "to_state": e.to_state, "trigger": e.trigger_type},
            "is_system":   e.actor is None,
            "created_at":  e.created_at.isoformat(),
        })

    # Assignment logs
    assignments = (await db.execute(
        select(TaskAssignmentLog)
        .options(
            selectinload(TaskAssignmentLog.assigner).selectinload(User.staff_profile),
            selectinload(TaskAssignmentLog.assignee),
        )
        .where(TaskAssignmentLog.task_id == task_id)
        .order_by(TaskAssignmentLog.created_at.asc())
    )).scalars().all()
    for a in assignments:
        events.append({
            "id":          str(a.id),
            "entity_type": "task",
            "entity_id":   tid,
            "event_type":  "assignment_change",
            "actor_id":    str(a.assigner.id)     if a.assigner else None,
            "actor_label": (a.assigner.staff_profile.full_name if a.assigner.staff_profile else a.assigner.username) if a.assigner else "System",
            "body":        a.note or f"Task {a.assignment_type} assignment",
            "meta":        {
                "assignment_type": a.assignment_type,
                "assigned_to":     str(a.assigned_to) if a.assigned_to else None,
                "to_dept_id":      str(a.to_dept_id)  if a.to_dept_id  else None,
            },
            "is_system":   False,
            "created_at":  a.created_at.isoformat(),
        })

    # Rejection / push-back logs
    rejections = (await db.execute(
        select(TaskRejectionLog)
        .options(selectinload(TaskRejectionLog.actor).selectinload(User.staff_profile))
        .where(TaskRejectionLog.task_id == task_id)
        .order_by(TaskRejectionLog.created_at.asc())
    )).scalars().all()
    for r in rejections:
        events.append({
            "id":          str(r.id),
            "entity_type": "task",
            "entity_id":   tid,
            "event_type":  "stage_pushback",
            "actor_id":    str(r.actor.id)        if r.actor else None,
            "actor_label": (r.actor.staff_profile.full_name if r.actor.staff_profile else r.actor.username) if r.actor else "System",
            "body":        r.reason or "Task returned",
            "meta":        {
                "rejection_type":  r.rejection_type,
                "previous_status": r.previous_status,
                "from_dept_id":    str(r.from_dept_id) if r.from_dept_id else None,
            },
            "is_system":   False,
            "created_at":  r.created_at.isoformat(),
        })

    events.sort(key=lambda x: x["created_at"])
    return {"success": True, "data": events}


@router.post("/{task_id}/timeline", status_code=201)
async def post_task_timeline_comment(
    task_id: uuid.UUID = Path(...),
    req: AddCommentRequest = ...,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(get_current_user),
):
    """Store timeline comments as task comments so both task views stay in sync."""
    comment, _ = await task_service.add_comment(
        db, task_id, req.body, caller,
        type="NORMAL", mentions=req.mentions, parent_id=req.parent_id,
    )
    await db.commit()
    author = _author_dict(caller)
    return {
        "success": True,
        "data": {
            "id": str(comment.id),
            "entity_type": "task",
            "entity_id": str(task_id),
            "event_type": "user_comment",
            "actor_id": str(caller.id),
            "actor_label": author["full_name"],
            "body": comment.body,
            "meta": {"mentions": comment.mentions or [], "comment_type": comment.type},
            "parent_id": str(comment.parent_id) if comment.parent_id else None,
            "mentions": comment.mentions or [],
            "is_system": False,
            "created_at": comment.created_at.isoformat(),
        },
    }


# ── GET single task ───────────────────────────────────────────

@router.get("/{task_id}")
async def get_task(
    task_id: uuid.UUID    = Path(...),
    db:      AsyncSession = Depends(get_db),
    _:       User         = Depends(get_current_user),
):
    task    = await task_service.get_detail(db, task_id)
    deps    = await task_service.get_dependencies(db, task_id)
    threads = _build_comment_threads(_as_list(task.comments))
    data    = _task_dict(task)
    data["comments"]     = threads
    data["dependencies"] = deps
    return {"success": True, "data": data}


# ── Comments ──────────────────────────────────────────────────

@router.post("/{task_id}/comments", status_code=201)
async def add_comment(
    task_id: uuid.UUID         = Path(...),
    req:     AddCommentRequest = ...,
    db:      AsyncSession      = Depends(get_db),
    caller:  User              = Depends(get_current_user),
):
    comment, workflow_action = await task_service.add_comment(
        db, task_id, req.body, caller,
        type=req.type, mentions=req.mentions, parent_id=req.parent_id,
    )
    await db.commit()
    return {
        "success": True,
        "data": {
            "id":              str(comment.id),
            "task_id":         str(comment.task_id),
            "body":            comment.body,
            "type":            comment.type,
            "mentions":        comment.mentions or [],
            "parent_id":       str(comment.parent_id) if comment.parent_id else None,
            "approval_action": comment.approval_action,
            "is_resolved":     comment.is_resolved,
            "created_at":      comment.created_at.isoformat(),
            "author":          _author_dict(caller),
        },
        "workflow_action": workflow_action,
    }


@router.post("/{task_id}/comments/{comment_id}/replies", status_code=201)
async def reply_to_comment(
    task_id:    uuid.UUID         = Path(...),
    comment_id: uuid.UUID         = Path(...),
    req:        AddCommentRequest = ...,
    db:         AsyncSession      = Depends(get_db),
    caller:     User              = Depends(get_current_user),
):
    req.parent_id = comment_id
    comment, _ = await task_service.add_comment(
        db, task_id, req.body, caller,
        type=req.type, mentions=req.mentions, parent_id=comment_id,
    )
    await db.commit()
    return {"success": True, "data": _comment_dict(comment)}


@router.patch("/{task_id}/comments/{comment_id}/resolve")
async def resolve_comment(task_id: uuid.UUID = Path(...), comment_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    comment = await task_service.resolve_comment(db, task_id, comment_id, caller)
    await db.commit()
    return {"success": True, "data": _comment_dict(comment)}


@router.patch("/{task_id}/comments/{comment_id}/approve")
async def approve_comment(task_id: uuid.UUID = Path(...), comment_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    comment = await task_service.approve_comment(db, task_id, comment_id, caller)
    await db.commit()
    return {"success": True, "data": _comment_dict(comment)}


@router.patch("/{task_id}/comments/{comment_id}/reject")
async def reject_comment(task_id: uuid.UUID = Path(...), comment_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    comment = await task_service.reject_comment(db, task_id, comment_id, caller)
    await db.commit()
    return {"success": True, "data": _comment_dict(comment)}


# ── Dependencies ──────────────────────────────────────────────

@router.get("/{task_id}/dependencies")
async def list_dependencies(task_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    deps = await task_service.get_dependencies(db, task_id)
    return {"success": True, "data": deps}


@router.post("/{task_id}/dependencies", status_code=201)
async def add_dependency(task_id: uuid.UUID = Path(...), req: AddDependencyRequest = ..., db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    dep = await task_service.add_dependency(db, task_id, req.depends_on_task_id, caller)
    await db.commit()
    return {"success": True, "data": dep}


@router.delete("/{task_id}/dependencies/{dependency_id}", status_code=204)
async def remove_dependency(task_id: uuid.UUID = Path(...), dependency_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    await task_service.remove_dependency(db, task_id, dependency_id, caller)


# ── Audit log ─────────────────────────────────────────────────

@router.get("/{task_id}/audit")
async def get_task_audit(task_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    entries = await task_service.get_audit(db, task_id)
    return {"success": True, "data": entries}


# ── Clone ──────────────────────────────────────────────────────

@router.post("/{task_id}/clone", status_code=201)
async def clone_task(task_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    task = await task_service.clone(db, task_id, caller)
    await db.commit()
    return {"success": True, "data": _task_dict(task)}


# ── H.1.1: Archive cross-references for a task ───────────────

@router.get("/{task_id}/archive-references")
async def get_archive_references(
    task_id: uuid.UUID    = Path(...),
    db:      AsyncSession = Depends(get_db),
    _:       User         = Depends(get_current_user),
):
    """Return all ArchiveReference records linked to this task (H.1.1)."""
    refs = (await db.execute(
        select(ArchiveReference).where(ArchiveReference.task_id == task_id)
    )).scalars().all()

    data = []
    for ref in refs:
        item: dict = {
            "id":         str(ref.id),
            "created_at": ref.created_at.isoformat() if ref.created_at else None,
        }
        if ref.referenced_archive_task_id:
            ref_task = (await db.execute(
                select(Task).where(Task.id == ref.referenced_archive_task_id)
            )).scalar_one_or_none()
            if ref_task:
                item.update({
                    "type":          "task",
                    "ticket_number": ref_task.ticket_number,
                    "title":         ref_task.title,
                    "pipeline_stage": ref_task.pipeline_stage,
                    "url":           f"/tasks/{ref_task.id}",
                })
        elif ref.referenced_archive_project_id:
            ref_proj = (await db.execute(
                select(Project).where(Project.id == ref.referenced_archive_project_id)
            )).scalar_one_or_none()
            if ref_proj:
                item.update({
                    "type":          "project",
                    "ticket_number": getattr(ref_proj, "ticket_number", None),
                    "title":         ref_proj.name,
                    "pipeline_stage": None,
                    "url":           f"/projects/{ref_proj.id}",
                })
        data.append(item)

    return {"success": True, "data": data}


# ── F.2.1: Assignment analytics — per-user totals ────────────

@router.get("/analytics/assignments")
async def get_assignment_analytics(
    from_date:     Optional[str]       = Query(None),
    to_date:       Optional[str]       = Query(None),
    department_id: Optional[uuid.UUID] = Query(None),
    db:            AsyncSession        = Depends(get_db),
    caller:        User                = Depends(get_current_user),
):
    """Per-user workload and completion analytics (F.2.1)."""
    role_level = caller.role.level if caller.role else 1
    if role_level < 3:
        raise HTTPException(status_code=403, detail="Requires manager level or above.")

    from_dt = datetime.datetime.fromisoformat(from_date) if from_date else None
    to_dt   = datetime.datetime.fromisoformat(to_date)   if to_date   else None

    # Staff roster
    staff_q = (
        select(User.id, StaffProfile.full_name, StaffProfile.department_id)
        .join(StaffProfile, StaffProfile.user_id == User.id)
        .where(User.is_active == True)  # noqa: E712
    )
    if department_id:
        staff_q = staff_q.where(StaffProfile.department_id == department_id)
    staff_rows = (await db.execute(staff_q)).all()

    if not staff_rows:
        return {"success": True, "data": []}

    user_ids = [r.id for r in staff_rows]

    # Assignments received
    recv_q = (
        select(TaskAssignmentLog.assigned_to, func.count().label("cnt"))
        .where(TaskAssignmentLog.assigned_to.in_(user_ids))
        .group_by(TaskAssignmentLog.assigned_to)
    )
    if from_dt: recv_q = recv_q.where(TaskAssignmentLog.created_at >= from_dt)
    if to_dt:   recv_q = recv_q.where(TaskAssignmentLog.created_at <= to_dt)
    recv_map = {str(r.assigned_to): r.cnt for r in (await db.execute(recv_q)).all()}

    # Assignments forwarded (user was the assigner, type forward/reassign)
    fwd_q = (
        select(TaskAssignmentLog.assigned_by, func.count().label("cnt"))
        .where(
            TaskAssignmentLog.assigned_by.in_(user_ids),
            TaskAssignmentLog.assignment_type.in_(["forward", "reassign"]),
        )
        .group_by(TaskAssignmentLog.assigned_by)
    )
    if from_dt: fwd_q = fwd_q.where(TaskAssignmentLog.created_at >= from_dt)
    if to_dt:   fwd_q = fwd_q.where(TaskAssignmentLog.created_at <= to_dt)
    fwd_map = {str(r.assigned_by): r.cnt for r in (await db.execute(fwd_q)).all()}

    # Completed tasks (archived, not deleted)
    comp_q = (
        select(Task.assignee_user_id, func.count().label("cnt"))
        .where(
            Task.assignee_user_id.in_(user_ids),
            Task.pipeline_stage == "archive",
            Task.is_deleted     == False,  # noqa: E712
        )
        .group_by(Task.assignee_user_id)
    )
    comp_map = {str(r.assignee_user_id): r.cnt for r in (await db.execute(comp_q)).all()}

    # Avg completion days (epoch seconds → days)
    avg_q = (
        select(
            Task.assignee_user_id,
            func.avg(
                cast(func.extract("epoch", Task.creator_approved_at), Float) -
                cast(func.extract("epoch", Task.created_at), Float)
            ).label("avg_seconds"),
        )
        .where(
            Task.assignee_user_id.in_(user_ids),
            Task.pipeline_stage       == "archive",
            Task.is_deleted           == False,  # noqa: E712
            Task.creator_approved_at.isnot(None),
        )
        .group_by(Task.assignee_user_id)
    )
    avg_map = {
        str(r.assignee_user_id): round(float(r.avg_seconds) / 86400, 1) if r.avg_seconds else 0
        for r in (await db.execute(avg_q)).all()
    }

    data = []
    for row in staff_rows:
        uid = str(row.id)
        data.append({
            "user_id":               uid,
            "full_name":             row.full_name,
            "assignments_received":  recv_map.get(uid, 0),
            "assignments_forwarded": fwd_map.get(uid, 0),
            "tasks_completed":       comp_map.get(uid, 0),
            "avg_completion_days":   avg_map.get(uid, 0),
        })

    return {"success": True, "data": data}


# ── F.2.2: Department analytics — per-dept totals ────────────

@router.get("/analytics/departments")
async def get_department_analytics(
    from_date: Optional[str] = Query(None),
    to_date:   Optional[str] = Query(None),
    db:        AsyncSession  = Depends(get_db),
    caller:    User          = Depends(get_current_user),
):
    """Per-department routing and completion analytics (F.2.2)."""
    role_level = caller.role.level if caller.role else 1
    if role_level < 3:
        raise HTTPException(status_code=403, detail="Requires manager level or above.")

    from_dt = datetime.datetime.fromisoformat(from_date) if from_date else None
    to_dt   = datetime.datetime.fromisoformat(to_date)   if to_date   else None

    # All departments
    depts = (await db.execute(select(Department.id, Department.name))).all()
    if not depts:
        return {"success": True, "data": []}
    dept_ids = [d.id for d in depts]

    # Tasks received per department (routing records)
    recv_q = (
        select(TaskDeptRouting.department_id, func.count().label("cnt"))
        .where(TaskDeptRouting.department_id.in_(dept_ids))
        .group_by(TaskDeptRouting.department_id)
    )
    if from_dt: recv_q = recv_q.where(TaskDeptRouting.entered_at >= from_dt)
    if to_dt:   recv_q = recv_q.where(TaskDeptRouting.entered_at <= to_dt)
    recv_map = {str(r.department_id): r.cnt for r in (await db.execute(recv_q)).all()}

    # Tasks completed (archived) per department
    comp_q = (
        select(Task.department_id, func.count().label("cnt"))
        .where(
            Task.department_id.in_(dept_ids),
            Task.pipeline_stage == "archive",
            Task.is_deleted     == False,  # noqa: E712
        )
        .group_by(Task.department_id)
    )
    comp_map = {str(r.department_id): r.cnt for r in (await db.execute(comp_q)).all()}

    # Push-backs originating from each department
    pb_q = (
        select(TaskRejectionLog.from_dept_id, func.count().label("cnt"))
        .where(
            TaskRejectionLog.from_dept_id.in_(dept_ids),
            TaskRejectionLog.rejection_type == "push_back",
        )
        .group_by(TaskRejectionLog.from_dept_id)
    )
    if from_dt: pb_q = pb_q.where(TaskRejectionLog.created_at >= from_dt)
    if to_dt:   pb_q = pb_q.where(TaskRejectionLog.created_at <= to_dt)
    pb_map = {str(r.from_dept_id): r.cnt for r in (await db.execute(pb_q)).all()}

    # Avg time-in-dept (seconds → days)
    avg_q = (
        select(
            TaskDeptRouting.department_id,
            func.avg(
                cast(func.extract("epoch", TaskDeptRouting.exited_at), Float) -
                cast(func.extract("epoch", TaskDeptRouting.entered_at), Float)
            ).label("avg_seconds"),
        )
        .where(
            TaskDeptRouting.department_id.in_(dept_ids),
            TaskDeptRouting.exited_at.isnot(None),
        )
        .group_by(TaskDeptRouting.department_id)
    )
    if from_dt: avg_q = avg_q.where(TaskDeptRouting.entered_at >= from_dt)
    avg_map = {
        str(r.department_id): round(float(r.avg_seconds) / 86400, 1) if r.avg_seconds else 0
        for r in (await db.execute(avg_q)).all()
    }

    data = []
    for d in depts:
        did = str(d.id)
        data.append({
            "department_id":   did,
            "department_name": d.name,
            "tasks_received":  recv_map.get(did, 0),
            "tasks_completed": comp_map.get(did, 0),
            "tasks_pushed_back": pb_map.get(did, 0),
            "avg_days_in_dept": avg_map.get(did, 0),
        })

    return {"success": True, "data": data}
