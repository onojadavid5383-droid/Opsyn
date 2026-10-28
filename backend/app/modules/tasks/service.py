# ============================================================
# OPSYN TASK WORKFLOW SERVICE — app/modules/tasks/service.py
# Phase 5: Centralized business logic for task creation,
# assignment, workflow routing, dual approval, soft-delete,
# archive references, and enterprise notifications.
# ============================================================

from __future__ import annotations
import uuid, datetime, re
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Integer
from sqlalchemy.orm import selectinload
from fastapi import HTTPException

from app.modules.tasks.models import (
    Task, TaskComment, TaskTag, TaskAssignmentLog, TaskRejectionLog, TaskDeptRouting,
    TaskCompletionApproval, ArchiveReference,
    STATUS_TO_PIPELINE_STAGE,
)
from app.modules.staff.models import User, StaffProfile
from app.modules.organisation.models import Department
from app.modules.audit.router import AuditLog


# ── Helpers ───────────────────────────────────────────────────

async def _generate_ticket_number(db: AsyncSession) -> str:
    year   = datetime.datetime.utcnow().year
    prefix = f"TSK-{year}-"
    max_seq = (await db.execute(
        select(func.max(cast(func.right(Task.ticket_number, 4), Integer)))
        .where(Task.ticket_number.like(f"{prefix}%"))
    )).scalar_one_or_none()
    return f"{prefix}{(max_seq or 0) + 1:04d}"


async def _generate_project_ticket_number(db: AsyncSession) -> str:
    from app.modules.projects.models import Project
    year   = datetime.datetime.utcnow().year
    prefix = f"PRJ-{year}-"
    max_seq = (await db.execute(
        select(func.max(cast(func.right(Project.ticket_number, 4), Integer)))
        .where(Project.ticket_number.like(f"{prefix}%"))
    )).scalar_one_or_none()
    return f"{prefix}{(max_seq or 0) + 1:04d}"


def _parse_mentions(body: str) -> list[str]:
    return list(set(re.findall(r'@([a-zA-Z0-9_.\-]+)', body)))


def _parse_archive_refs(body: str) -> list[str]:
    refs = re.findall(r'@archive\[([A-Z]+-\d{4}-\d+)\]', body)
    if "@archive" in body and not refs:
        return ["__search__"]
    return refs


async def _get_user_by_username(db: AsyncSession, username: str, tenant_id: uuid.UUID) -> Optional[User]:
    return (await db.execute(
        select(User).where(User.username == username, User.tenant_id == tenant_id)
    )).scalar_one_or_none()


async def _get_task_by_ticket(db: AsyncSession, ticket: str, tenant_id: uuid.UUID) -> Optional[Task]:
    return (await db.execute(
        select(Task).where(Task.ticket_number == ticket, Task.tenant_id == tenant_id)
    )).scalar_one_or_none()


async def _get_dept_members(db: AsyncSession, dept_id: uuid.UUID) -> list[User]:
    rows = (await db.execute(
        select(User)
        .join(StaffProfile, StaffProfile.user_id == User.id)
        .where(
            StaffProfile.department_id == dept_id,
            User.is_active == True,  # noqa: E712
        )
    )).scalars().all()
    return list(rows)


async def _get_dept_manager(db: AsyncSession, dept_id: uuid.UUID) -> Optional[User]:
    dept = (await db.execute(
        select(Department).where(Department.id == dept_id)
    )).scalar_one_or_none()
    if dept and dept.head_user_id:
        return (await db.execute(
            select(User).where(User.id == dept.head_user_id)
        )).scalar_one_or_none()
    return None


async def _log_audit_event(
    db:           AsyncSession,
    actor_id:     uuid.UUID,
    action:       str,
    target_type:  str,
    target_id:    uuid.UUID,
    tenant_id:    uuid.UUID,
    before_state: Optional[dict] = None,
    after_state:  Optional[dict] = None,
    ip_address:   Optional[str] = None,
) -> None:
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        tenant_id=tenant_id,
        before_state=before_state,
        after_state=after_state,
        ip_address=ip_address,
    )
    db.add(entry)
    await db.flush()


def _task_snapshot(task: Task) -> dict:
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "pipeline_stage": task.pipeline_stage,
        "task_scope": task.task_scope,
        "assignee_user_id": str(task.assignee_user_id) if task.assignee_user_id else None,
        "department_id": str(task.department_id) if task.department_id else None,
        "project_id": str(task.project_id) if task.project_id else None,
        "is_deleted": task.is_deleted,
        "is_reopened": task.is_reopened,
        "assignee_confirmed_done": task.assignee_confirmed_done,
        "creator_approved_done": task.creator_approved_done,
        "deadline": task.deadline.isoformat() if task.deadline else None,
    }


# ── Notification helpers ──────────────────────────────────────

async def _notify(
    db: AsyncSession,
    recipient_id: uuid.UUID,
    tenant_id: uuid.UUID,
    notif_type: str,
    title: str,
    body: str,
    action_url: str = "",
    sender_id: Optional[uuid.UUID] = None,
    related_task_id: Optional[uuid.UUID] = None,
    related_project_id: Optional[uuid.UUID] = None,
    related_dept_id: Optional[uuid.UUID] = None,
) -> None:
    from app.modules.all_modules import Notification
    notif = Notification(
        recipient_id=recipient_id,
        type=notif_type,
        title=title,
        body=body,
        action_url=action_url,
        tenant_id=tenant_id,
        notification_category=notif_type,
        sender_id=sender_id,
        related_task_id=related_task_id,
        related_project_id=related_project_id,
        related_dept_id=related_dept_id,
    )
    db.add(notif)
    await db.flush()


async def _notify_department(
    db: AsyncSession,
    dept_id: uuid.UUID,
    tenant_id: uuid.UUID,
    notif_type: str,
    title: str,
    body: str,
    action_url: str = "",
    sender_id: Optional[uuid.UUID] = None,
    related_task_id: Optional[uuid.UUID] = None,
    related_project_id: Optional[uuid.UUID] = None,
    exclude_user_ids: Optional[list[uuid.UUID]] = None,
) -> None:
    members = await _get_dept_members(db, dept_id)
    exclude = set(str(uid) for uid in (exclude_user_ids or []))
    for user in members:
        if str(user.id) in exclude:
            continue
        await _notify(
            db, user.id, tenant_id, notif_type, title, body,
            action_url=action_url,
            sender_id=sender_id,
            related_task_id=related_task_id,
            related_dept_id=dept_id,
        )


# ── TaskWorkflowService ───────────────────────────────────────

class TaskWorkflowService:

    # ── Internal task creation ────────────────────────────────

    async def create_internal_task(
        self,
        db:      AsyncSession,
        payload: "CreateTaskRequest",  # noqa: F821
        caller:  User,
    ) -> Task:
        sp = caller.staff_profile
        if not sp or not sp.department_id:
            raise HTTPException(
                status_code=422,
                detail="Your staff profile is missing a department. Contact an admin.",
            )

        dept_id = sp.department_id

        # Validate assignee is in same department
        if payload.assignee_user_id:
            assignee = (await db.execute(
                select(User)
                .options(selectinload(User.staff_profile))
                .where(User.id == payload.assignee_user_id)
            )).scalar_one_or_none()
            if not assignee:
                raise HTTPException(status_code=422, detail="Assignee not found.")
            if (not assignee.staff_profile or
                    assignee.staff_profile.department_id != dept_id):
                raise HTTPException(
                    status_code=422,
                    detail="Internal task assignee must be in the same department as the creator.",
                )

        deadline = self._parse_deadline(payload.deadline)
        ticket   = await _generate_ticket_number(db)
        now      = datetime.datetime.utcnow()

        initial_status = "assigned" if payload.assignee_user_id else "new"
        task = Task(
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            status=initial_status,
            state_changed_at=now,
            deadline=deadline,
            department_id=dept_id,
            project_id=payload.project_id,
            assignee_user_id=payload.assignee_user_id,
            created_by=caller.id,
            tenant_id=caller.tenant_id,
            ticket_number=ticket,
            estimated_hours=payload.estimated_hours,
            task_scope="internal",
            pipeline_stage=STATUS_TO_PIPELINE_STAGE[initial_status],
            source_app=payload.source_app,
        )
        db.add(task)
        await db.flush()

        # Tags
        for tag in (payload.tags or []):
            db.add(TaskTag(task_id=task.id, tag=tag.lstrip("#")))

        # Archive references
        if payload.archive_refs:
            await self._store_archive_refs(db, task.id, payload.archive_refs, caller)

        # Assignment log
        if payload.assignee_user_id:
            db.add(TaskAssignmentLog(
                task_id=task.id,
                tenant_id=caller.tenant_id,
                assigned_by=caller.id,
                assigned_to=payload.assignee_user_id,
                to_dept_id=dept_id,
                assignment_type="initial",
                note="Task created with initial assignee",
            ))

        await db.flush()

        # Notify assignee
        if payload.assignee_user_id and payload.assignee_user_id != caller.id:
            await _notify(
                db, payload.assignee_user_id, caller.tenant_id,
                "task_assigned",
                f"New task assigned to you: {task.title}",
                f"Task {ticket} has been assigned to you by {caller.username}.",
                action_url=f"/tasks/{task.id}",
                sender_id=caller.id,
                related_task_id=task.id,
                related_dept_id=dept_id,
            )

        await _log_audit_event(
            db, caller.id, "task.created", "task", task.id, caller.tenant_id,
            after_state={
                "task_scope": "internal", "title": task.title,
                "dept_id": str(dept_id),
                "assignee": str(payload.assignee_user_id) if payload.assignee_user_id else None,
                "deadline": deadline.isoformat() if deadline else None,
            },
        )

        task = (await db.execute(
            select(Task)
            .options(selectinload(Task.assignee), selectinload(Task.department),
                     selectinload(Task.tags), selectinload(Task.comments))
            .where(Task.id == task.id)
        )).scalar_one()
        return task

    # ── External task creation ────────────────────────────────

    async def create_external_task(
        self,
        db:         AsyncSession,
        payload:    "CreateTaskRequest",  # noqa: F821
        caller:     User,
        source_app: Optional[str] = None,
    ) -> tuple[Task, "Project"]:  # noqa: F821
        from app.modules.projects.auto_generator import project_auto_generator

        if not payload.department_id:
            raise HTTPException(
                status_code=422,
                detail="department_id is required for external tasks.",
            )

        dept = (await db.execute(
            select(Department).where(
                Department.id == payload.department_id,
                Department.tenant_id == caller.tenant_id,
            )
        )).scalar_one_or_none()
        if not dept:
            raise HTTPException(status_code=422, detail="Target department not found.")

        deadline = self._parse_deadline(payload.deadline)
        ticket   = await _generate_ticket_number(db)
        now      = datetime.datetime.utcnow()
        app_src  = source_app or payload.source_app or "task_engine"

        task = Task(
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            status="new",
            state_changed_at=now,
            deadline=deadline,
            department_id=payload.department_id,
            assignee_user_id=None,
            created_by=caller.id,
            tenant_id=caller.tenant_id,
            ticket_number=ticket,
            estimated_hours=payload.estimated_hours,
            task_scope="external",
            pipeline_stage="backlog",
            source_app=app_src,
        )
        db.add(task)
        await db.flush()

        # Tags
        for tag in (payload.tags or []):
            db.add(TaskTag(task_id=task.id, tag=tag.lstrip("#")))

        # Auto-generate project
        project = await project_auto_generator.generate_from_task(
            db, task, caller, source_app=app_src
        )

        # Initial department routing record
        routing_count = (await db.execute(
            select(func.count()).select_from(
                select(TaskDeptRouting).where(TaskDeptRouting.task_id == task.id).subquery()
            )
        )).scalar_one()

        db.add(TaskDeptRouting(
            task_id=task.id,
            tenant_id=caller.tenant_id,
            department_id=payload.department_id,
            assigned_by=caller.id,
            routing_order=routing_count + 1,
            is_current=True,
        ))
        await db.flush()

        # Archive references
        if payload.archive_refs:
            await self._store_archive_refs(db, task.id, payload.archive_refs, caller)

        # Notify entire target department
        await _notify_department(
            db, payload.department_id, caller.tenant_id,
            "task_assigned",
            f"New external task routed to your department: {task.title}",
            f"Task {ticket} has been routed to your department and requires assignment.",
            action_url=f"/tasks/{task.id}",
            sender_id=caller.id,
            related_task_id=task.id,
            related_project_id=project.id,
        )

        await _log_audit_event(
            db, caller.id, "task.created", "task", task.id, caller.tenant_id,
            after_state={
                "task_scope": "external", "title": task.title,
                "dept_id": str(payload.department_id),
                "source_app": app_src,
                "project_id": str(project.id),
            },
        )
        await _log_audit_event(
            db, caller.id, "project.auto_generated", "project", project.id, caller.tenant_id,
            after_state={
                "source_task_id": str(task.id), "source_app": app_src,
                "dept_id": str(payload.department_id),
            },
        )

        task = (await db.execute(
            select(Task)
            .options(selectinload(Task.assignee), selectinload(Task.department),
                     selectinload(Task.tags), selectinload(Task.comments))
            .where(Task.id == task.id)
        )).scalar_one()
        return task, project

    # ── Assignment ────────────────────────────────────────────

    async def assign_task(
        self,
        db:               AsyncSession,
        task_id:          uuid.UUID,
        assignee_user_id: uuid.UUID,
        caller:           User,
        note:             Optional[str] = None,
        ip_address:       Optional[str] = None,
    ) -> Task:
        task = await self._get_task_or_404(db, task_id)
        self._assert_not_deleted(task)
        await self._assert_can_assign(caller, task)

        assignee = (await db.execute(
            select(User).options(selectinload(User.staff_profile))
            .where(User.id == assignee_user_id)
        )).scalar_one_or_none()
        if not assignee:
            raise HTTPException(status_code=422, detail="Assignee not found.")

        old_assignee = task.assignee_user_id
        task.assignee_user_id = assignee_user_id
        task.status           = "assigned"
        task.pipeline_stage   = "backlog"
        await db.flush()

        db.add(TaskAssignmentLog(
            task_id=task.id,
            tenant_id=caller.tenant_id,
            assigned_by=caller.id,
            assigned_to=assignee_user_id,
            to_dept_id=task.department_id,
            assignment_type="initial" if not old_assignee else "reassign",
            note=note,
        ))

        # Update routing record with assignee
        routing = (await db.execute(
            select(TaskDeptRouting).where(
                TaskDeptRouting.task_id == task.id,
                TaskDeptRouting.is_current == True,  # noqa: E712
            )
        )).scalar_one_or_none()
        if routing:
            routing.assigned_to_user_id = assignee_user_id

        await db.flush()

        # Notify assignee
        await _notify(
            db, assignee_user_id, caller.tenant_id,
            "task_assigned",
            f"Task assigned to you: {task.title}",
            f"You have been assigned task {task.ticket_number} by {caller.username}.",
            action_url=f"/tasks/{task.id}",
            sender_id=caller.id,
            related_task_id=task.id,
            related_dept_id=task.department_id,
        )
        # Confirm to assigner
        await _notify(
            db, caller.id, caller.tenant_id,
            "task_assigned",
            f"Assignment confirmed: {task.title}",
            f"Task {task.ticket_number} assigned to {assignee.username}.",
            action_url=f"/tasks/{task.id}",
            related_task_id=task.id,
        )

        await _log_audit_event(
            db, caller.id, "task.assigned", "task", task.id, caller.tenant_id,
            before_state={"assignee_user_id": str(old_assignee) if old_assignee else None},
            after_state={"assignee_user_id": str(assignee_user_id), "note": note},
            ip_address=ip_address,
        )

        return await self._reload(db, task.id)

    async def reassign_task(
        self,
        db:          AsyncSession,
        task_id:     uuid.UUID,
        to_user_id:  uuid.UUID,
        caller:      User,
        reason:      Optional[str] = None,
    ) -> Task:
        task = await self._get_task_or_404(db, task_id)
        self._assert_not_deleted(task)
        await self._assert_can_assign(caller, task)

        old_assignee = task.assignee_user_id
        task.assignee_user_id = to_user_id
        await db.flush()

        db.add(TaskAssignmentLog(
            task_id=task.id,
            tenant_id=caller.tenant_id,
            assigned_by=caller.id,
            assigned_to=to_user_id,
            to_dept_id=task.department_id,
            assignment_type="reassign",
            note=reason,
        ))
        await db.flush()

        # Notify new and old assignee
        await _notify(
            db, to_user_id, caller.tenant_id,
            "task_assigned",
            f"Task reassigned to you: {task.title}",
            f"Task {task.ticket_number} has been reassigned to you.",
            action_url=f"/tasks/{task.id}",
            sender_id=caller.id,
            related_task_id=task.id,
        )
        if old_assignee and old_assignee != to_user_id:
            await _notify(
                db, old_assignee, caller.tenant_id,
                "task_assigned",
                f"Task reassigned from you: {task.title}",
                f"Task {task.ticket_number} has been reassigned by {caller.username}.",
                action_url=f"/tasks/{task.id}",
                related_task_id=task.id,
            )

        await _log_audit_event(
            db, caller.id, "task.reassigned", "task", task.id, caller.tenant_id,
            before_state={"assignee_user_id": str(old_assignee) if old_assignee else None},
            after_state={"assignee_user_id": str(to_user_id), "reason": reason},
        )

        return await self._reload(db, task.id)

    # ── Forward within department ─────────────────────────────

    async def forward_task(
        self,
        db:         AsyncSession,
        task_id:    uuid.UUID,
        to_user_id: uuid.UUID,
        caller:     User,
        note:       Optional[str] = None,
    ) -> Task:
        task = await self._get_task_or_404(db, task_id)
        self._assert_not_deleted(task)

        # Must be current assignee or manager-level
        role_level = caller.role.level if caller.role else 1
        if task.assignee_user_id != caller.id and role_level < 3:
            raise HTTPException(
                status_code=403,
                detail="Only the current assignee or a manager can forward this task.",
            )

        # to_user must be in same department
        to_user = (await db.execute(
            select(User).options(selectinload(User.staff_profile))
            .where(User.id == to_user_id)
        )).scalar_one_or_none()
        if not to_user:
            raise HTTPException(status_code=422, detail="Target user not found.")
        if (to_user.staff_profile and
                to_user.staff_profile.department_id != task.department_id):
            raise HTTPException(
                status_code=422,
                detail="Forward target must be in the same department.",
            )

        task.assignee_user_id = to_user_id
        await db.flush()

        db.add(TaskAssignmentLog(
            task_id=task.id,
            tenant_id=caller.tenant_id,
            assigned_by=caller.id,
            assigned_to=to_user_id,
            to_dept_id=task.department_id,
            assignment_type="reassign",
            note=note,
        ))
        await db.flush()

        await _notify(
            db, to_user_id, caller.tenant_id,
            "task_assigned",
            f"Task forwarded to you: {task.title}",
            f"Task {task.ticket_number} was forwarded to you by {caller.username}.",
            action_url=f"/tasks/{task.id}",
            sender_id=caller.id,
            related_task_id=task.id,
        )

        await _log_audit_event(
            db, caller.id, "task.forward", "task", task.id, caller.tenant_id,
            after_state={"to_user_id": str(to_user_id), "note": note},
        )

        return await self._reload(db, task.id)

    # ── Push-back ─────────────────────────────────────────────

    async def push_back_task(
        self,
        db:         AsyncSession,
        task_id:    uuid.UUID,
        reason:     str,
        caller:     User,
        to_user_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str]       = None,
    ) -> Task:
        if not reason or len(reason.strip()) < 10:
            raise HTTPException(
                status_code=422,
                detail="A push-back reason of at least 10 characters is required.",
            )

        task = await self._get_task_or_404(db, task_id)
        self._assert_not_deleted(task)

        role_level = caller.role.level if caller.role else 1
        if task.assignee_user_id != caller.id and role_level < 3:
            raise HTTPException(
                status_code=403,
                detail="Only the current assignee or a manager can push back this task.",
            )

        before = _task_snapshot(task)
        old_assignee = task.assignee_user_id

        if to_user_id:
            task.assignee_user_id = to_user_id
        task.pipeline_stage           = "in_progress"
        task.status                   = "in_progress"
        task.assignee_confirmed_done  = False
        await db.flush()

        db.add(TaskRejectionLog(
            task_id=task.id,
            tenant_id=caller.tenant_id,
            rejected_by=caller.id,
            rejection_type="push_back",
            from_dept_id=task.department_id,
            reason=reason,
            previous_status=before["status"],
        ))
        await db.flush()

        # Standardized notification body (C.1.5)
        notif_body = (
            f"Task {task.ticket_number} was pushed back by {caller.username}. "
            f"Reason: {reason}"
        )
        action_url = f"/tasks/{task.id}"
        notify_ids = {str(caller.id)}

        # Current/old assignee
        if old_assignee and str(old_assignee) not in notify_ids:
            await _notify(
                db, old_assignee, caller.tenant_id, "push_back",
                f"Task pushed back: {task.title}",
                notif_body,
                action_url=action_url,
                sender_id=caller.id, related_task_id=task.id,
            )
            notify_ids.add(str(old_assignee))

        # Explicit target user (optional re-assignment)
        if to_user_id and str(to_user_id) not in notify_ids:
            await _notify(
                db, to_user_id, caller.tenant_id, "push_back",
                f"Task returned to you: {task.title}",
                notif_body,
                action_url=action_url,
                sender_id=caller.id, related_task_id=task.id,
            )
            notify_ids.add(str(to_user_id))

        # Task creator
        if task.created_by and str(task.created_by) not in notify_ids:
            await _notify(
                db, task.created_by, caller.tenant_id, "push_back",
                f"Task you created was pushed back: {task.title}",
                notif_body,
                action_url=action_url,
                related_task_id=task.id,
            )
            notify_ids.add(str(task.created_by))

        # Department manager
        mgr = await _get_dept_manager(db, task.department_id) if task.department_id else None
        if mgr and str(mgr.id) not in notify_ids:
            await _notify(
                db, mgr.id, caller.tenant_id, "push_back",
                f"Task in your department was pushed back: {task.title}",
                notif_body,
                action_url=action_url,
                related_task_id=task.id,
            )
            notify_ids.add(str(mgr.id))

        # C.1.1-C.1.2: Previous department — notify all members
        prev_routing = (await db.execute(
            select(TaskDeptRouting)
            .where(
                TaskDeptRouting.task_id == task.id,
                TaskDeptRouting.is_current == False,  # noqa: E712
            )
            .order_by(TaskDeptRouting.routing_order.desc())
            .limit(1)
        )).scalar_one_or_none()
        if prev_routing:
            await _notify_department(
                db, prev_routing.department_id, caller.tenant_id,
                "push_back",
                f"Task returned to your department: {task.title}",
                notif_body,
                action_url=action_url,
                sender_id=caller.id,
                related_task_id=task.id,
                exclude_user_ids=[caller.id],
            )

        # C.1.3: Previous assignee from assignment logs (2nd-to-last)
        prev_log = (await db.execute(
            select(TaskAssignmentLog)
            .where(TaskAssignmentLog.task_id == task.id)
            .order_by(TaskAssignmentLog.created_at.desc())
            .offset(1)
            .limit(1)
        )).scalar_one_or_none()
        if prev_log and str(prev_log.assigned_to) not in notify_ids:
            await _notify(
                db, prev_log.assigned_to, caller.tenant_id, "push_back",
                f"Task previously assigned to you was pushed back: {task.title}",
                notif_body,
                action_url=action_url,
                sender_id=caller.id, related_task_id=task.id,
            )
            notify_ids.add(str(prev_log.assigned_to))

        # C.1.4: Project owner if task is linked to a project
        if task.project_id:
            from app.modules.projects.models import Project as ProjectModel
            linked_project = (await db.execute(
                select(ProjectModel).where(ProjectModel.id == task.project_id)
            )).scalar_one_or_none()
            if (linked_project and linked_project.owner_id
                    and str(linked_project.owner_id) not in notify_ids):
                await _notify(
                    db, linked_project.owner_id, caller.tenant_id, "push_back",
                    f"Task in your project was pushed back: {task.title}",
                    notif_body,
                    action_url=action_url,
                    sender_id=caller.id, related_task_id=task.id,
                    related_project_id=task.project_id,
                )
                notify_ids.add(str(linked_project.owner_id))

        await _log_audit_event(
            db, caller.id, "task.push_back", "task", task.id, caller.tenant_id,
            before_state=before,
            after_state={"pipeline_stage": "in_progress", "reason": reason},
            ip_address=ip_address,
        )

        return await self._reload(db, task.id)

    # ── Escalate ──────────────────────────────────────────────

    async def escalate_task(
        self,
        db:         AsyncSession,
        task_id:    uuid.UUID,
        note:       str,
        caller:     User,
        ip_address: Optional[str] = None,
    ) -> Task:
        task = await self._get_task_or_404(db, task_id)
        self._assert_not_deleted(task)

        mgr = await _get_dept_manager(db, task.department_id) if task.department_id else None
        if mgr:
            await _notify(
                db, mgr.id, caller.tenant_id, "escalation",
                f"Task escalated in your department: {task.title}",
                f"Escalated by {caller.username}. Note: {note}",
                action_url=f"/tasks/{task.id}",
                sender_id=caller.id, related_task_id=task.id,
            )

        # System comment
        c = TaskComment(
            task_id=task.id,
            author_user_id=None,
            body=f"ESCALATION raised by {caller.username}: {note}",
            type="SYSTEM",
            mentions=[],
        )
        db.add(c)
        await db.flush()

        await _log_audit_event(
            db, caller.id, "task.escalated", "task", task.id, caller.tenant_id,
            after_state={"note": note},
            ip_address=ip_address,
        )

        return await self._reload(db, task.id)

    # ── Forward to another department ─────────────────────────

    async def forward_dept(
        self,
        db:         AsyncSession,
        task_id:    uuid.UUID,
        to_dept_id: uuid.UUID,
        caller:     User,
        note:       Optional[str] = None,
    ) -> Task:
        task = await self._get_task_or_404(db, task_id)
        self._assert_not_deleted(task)

        if task.task_scope != "external":
            raise HTTPException(
                status_code=422,
                detail="Department-to-department forwarding is only allowed for external tasks.",
            )
        role_level = caller.role.level if caller.role else 1
        if role_level < 3:
            raise HTTPException(status_code=403, detail="Only managers or admins can forward to another department.")
        if to_dept_id == task.department_id:
            raise HTTPException(status_code=422, detail="Target department must be different from current department.")

        now = datetime.datetime.utcnow()

        # Close current routing
        current_routing = (await db.execute(
            select(TaskDeptRouting).where(
                TaskDeptRouting.task_id == task.id,
                TaskDeptRouting.is_current == True,  # noqa: E712
            )
        )).scalar_one_or_none()
        if current_routing:
            current_routing.is_current  = False
            current_routing.exited_at   = now
            current_routing.exit_reason = "forwarded"

        routing_count = (await db.execute(
            select(func.count()).select_from(
                select(TaskDeptRouting).where(TaskDeptRouting.task_id == task.id).subquery()
            )
        )).scalar_one()

        db.add(TaskDeptRouting(
            task_id=task.id,
            tenant_id=caller.tenant_id,
            department_id=to_dept_id,
            assigned_by=caller.id,
            routing_order=routing_count + 1,
            is_current=True,
        ))

        old_dept = task.department_id
        task.department_id    = to_dept_id
        task.assignee_user_id = None
        task.pipeline_stage   = "backlog"
        await db.flush()

        await _notify_department(
            db, to_dept_id, caller.tenant_id,
            "dept_transfer",
            f"Task routed to your department: {task.title}",
            f"External task {task.ticket_number} forwarded from another department. Requires assignment.",
            action_url=f"/tasks/{task.id}",
            sender_id=caller.id,
            related_task_id=task.id,
        )

        await _log_audit_event(
            db, caller.id, "task.forward_dept", "task", task.id, caller.tenant_id,
            before_state={"department_id": str(old_dept) if old_dept else None},
            after_state={"department_id": str(to_dept_id), "note": note},
        )

        return await self._reload(db, task.id)

    # ── Return to previous department ─────────────────────────

    async def return_dept(
        self,
        db:      AsyncSession,
        task_id: uuid.UUID,
        reason:  str,
        caller:  User,
    ) -> Task:
        if not reason or len(reason.strip()) < 10:
            raise HTTPException(
                status_code=422,
                detail="A return reason of at least 10 characters is required.",
            )

        task = await self._get_task_or_404(db, task_id)
        self._assert_not_deleted(task)

        if task.task_scope != "external":
            raise HTTPException(status_code=422, detail="Only external tasks can be returned to previous department.")

        role_level = caller.role.level if caller.role else 1
        if role_level < 3:
            raise HTTPException(status_code=403, detail="Only managers or admins can return tasks to previous department.")

        now = datetime.datetime.utcnow()

        # Get routing history ordered by routing_order DESC
        all_routing = (await db.execute(
            select(TaskDeptRouting)
            .where(TaskDeptRouting.task_id == task.id)
            .order_by(TaskDeptRouting.routing_order.desc())
        )).scalars().all()

        current = next((r for r in all_routing if r.is_current), None)
        if not current:
            raise HTTPException(status_code=422, detail="No current routing found for this task.")

        previous = next((r for r in all_routing if not r.is_current and r.routing_order == current.routing_order - 1), None)
        if not previous:
            raise HTTPException(status_code=422, detail="No previous department to return to.")

        current.is_current  = False
        current.exited_at   = now
        current.exit_reason = "dept_return"

        previous.is_current = True
        previous.exited_at  = None

        from_dept = task.department_id
        task.department_id    = previous.department_id
        task.assignee_user_id = None
        task.pipeline_stage   = "in_progress"
        task.status           = "in_progress"
        await db.flush()

        db.add(TaskRejectionLog(
            task_id=task.id,
            tenant_id=caller.tenant_id,
            rejected_by=caller.id,
            rejection_type="dept_return",
            from_dept_id=from_dept,
            to_dept_id=previous.department_id,
            reason=reason,
            previous_status="backlog",
        ))
        await db.flush()

        # Notify both departments
        await _notify_department(
            db, previous.department_id, caller.tenant_id,
            "dept_transfer",
            f"Task returned to your department: {task.title}",
            f"Task {task.ticket_number} has been returned. Reason: {reason}",
            action_url=f"/tasks/{task.id}",
            sender_id=caller.id, related_task_id=task.id,
        )
        if from_dept:
            await _notify_department(
                db, from_dept, caller.tenant_id,
                "dept_transfer",
                f"Task returned from your department: {task.title}",
                f"Task {task.ticket_number} was returned by {caller.username}. Reason: {reason}",
                action_url=f"/tasks/{task.id}",
                related_task_id=task.id,
            )

        await _log_audit_event(
            db, caller.id, "task.return_dept", "task", task.id, caller.tenant_id,
            after_state={
                "from_dept": str(from_dept) if from_dept else None,
                "to_dept": str(previous.department_id), "reason": reason,
            },
        )

        return await self._reload(db, task.id)

    # ── Mark done (assignee step) ─────────────────────────────

    async def mark_done(self, db: AsyncSession, task_id: uuid.UUID, caller: User, ip_address: Optional[str] = None) -> Task:
        task = await self._get_task_or_404(db, task_id)
        self._assert_not_deleted(task)

        if task.tenant_id != caller.tenant_id:
            raise HTTPException(status_code=404, detail="Task not found.")

        if task.assignee_user_id != caller.id:
            raise HTTPException(status_code=403, detail="Only the assigned staff member can mark this task as done.")
        if task.status not in ("in_progress", "review") or task.pipeline_stage not in ("in_progress", "review"):
            raise HTTPException(
                status_code=422,
                detail=f"Task must be in 'in_progress' or 'review' to mark done. Current stage: {task.pipeline_stage}",
            )
        if task.assignee_confirmed_done:
            raise HTTPException(status_code=422, detail="You have already marked this task as done.")

        now = datetime.datetime.utcnow()
        task.assignee_confirmed_done = True
        task.assignee_done_at        = now
        task.pipeline_stage          = "unit_done"
        task.status                  = "done"
        await db.flush()

        db.add(TaskCompletionApproval(
            task_id=task.id,
            tenant_id=caller.tenant_id,
            approval_type="assignee_done",
            actor_id=caller.id,
        ))
        await db.flush()

        # Notify creator
        if task.created_by and task.created_by != caller.id:
            await _notify(
                db, task.created_by, caller.tenant_id,
                "approval_needed",
                f"Task is ready for your approval: {task.title}",
                f"Task {task.ticket_number} is marked done by the assignee. Your approval is required to archive it.",
                action_url=f"/tasks/{task.id}",
                sender_id=caller.id,
                related_task_id=task.id,
            )

        await _log_audit_event(
            db, caller.id, "task.marked_done", "task", task.id, caller.tenant_id,
            after_state={"assignee_confirmed_done": True, "pipeline_stage": "unit_done"},
            ip_address=ip_address,
        )

        return await self._reload(db, task.id)

    # ── Approve done (creator step) ───────────────────────────

    async def approve_done(self, db: AsyncSession, task_id: uuid.UUID, caller: User, ip_address: Optional[str] = None) -> Task:
        task = await self._get_task_or_404(db, task_id)
        self._assert_not_deleted(task)

        if task.tenant_id != caller.tenant_id:
            raise HTTPException(status_code=404, detail="Task not found.")

        role_level = caller.role.level if caller.role else 1
        if task.created_by != caller.id and role_level < 4:
            raise HTTPException(
                status_code=403,
                detail="Only the task creator (or an admin) can approve completion.",
            )
        if task.status != "done" or not task.assignee_confirmed_done:
            raise HTTPException(
                status_code=422,
                detail="The assignee must mark the task done first (Step 1 of dual approval).",
            )
        if task.creator_approved_done:
            raise HTTPException(status_code=422, detail="You have already approved this task.")

        now = datetime.datetime.utcnow()
        task.creator_approved_done = True
        task.creator_approved_at   = now
        task.pipeline_stage        = "archive"
        task.status                = "archived"
        await db.flush()

        db.add(TaskCompletionApproval(
            task_id=task.id,
            tenant_id=caller.tenant_id,
            approval_type="creator_approved",
            actor_id=caller.id,
        ))
        await db.flush()

        # Notify assignee
        if task.assignee_user_id:
            await _notify(
                db, task.assignee_user_id, caller.tenant_id,
                "completion_approved",
                f"Task approved and archived: {task.title}",
                f"Task {task.ticket_number} has been approved and archived.",
                action_url=f"/tasks/{task.id}",
                sender_id=caller.id, related_task_id=task.id,
            )

        # Check if all tasks in project are archived — if so mark project complete
        if task.project_id:
            await self._check_project_completion(db, task.project_id, caller)

        await _log_audit_event(
            db, caller.id, "task.creator_approved", "task", task.id, caller.tenant_id,
            after_state={"creator_approved_done": True, "pipeline_stage": "archive", "status": "archived"},
            ip_address=ip_address,
        )

        return await self._reload(db, task.id)

    # ── Reject done (creator step) ────────────────────────────

    async def reject_done(self, db: AsyncSession, task_id: uuid.UUID, reason: str, caller: User, ip_address: Optional[str] = None) -> Task:
        task = await self._get_task_or_404(db, task_id)
        self._assert_not_deleted(task)

        if task.tenant_id != caller.tenant_id:
            raise HTTPException(status_code=404, detail="Task not found.")

        role_level = caller.role.level if caller.role else 1
        if task.created_by != caller.id and role_level < 4:
            raise HTTPException(status_code=403, detail="Only the task creator (or an admin) can reject completion.")

        if task.status != "done" or not task.assignee_confirmed_done or task.creator_approved_done:
            raise HTTPException(status_code=422, detail="Assignee has not marked the task done yet.")

        before = _task_snapshot(task)
        task.assignee_confirmed_done = False
        task.pipeline_stage          = "in_progress"
        task.status                  = "in_progress"
        await db.flush()

        db.add(TaskRejectionLog(
            task_id=task.id,
            tenant_id=caller.tenant_id,
            rejected_by=caller.id,
            rejection_type="completion_rejected",
            reason=reason,
            previous_status=before["status"],
        ))
        await db.flush()

        if task.assignee_user_id:
            await _notify(
                db, task.assignee_user_id, caller.tenant_id,
                "push_back",
                f"Completion rejected: {task.title}",
                f"Your completion was rejected. Reason: {reason}",
                action_url=f"/tasks/{task.id}",
                sender_id=caller.id, related_task_id=task.id,
            )

        await _log_audit_event(
            db, caller.id, "task.completion_rejected", "task", task.id, caller.tenant_id,
            before_state=before,
            after_state={"pipeline_stage": "in_progress", "reason": reason},
            ip_address=ip_address,
        )

        return await self._reload(db, task.id)

    # ── Reopen archived task (E.2.1) ──────────────────────────

    async def reopen_task(
        self,
        db:         AsyncSession,
        task_id:    uuid.UUID,
        caller:     User,
        ip_address: Optional[str] = None,
    ) -> Task:
        task = await self._get_task_or_404(db, task_id)
        self._assert_not_deleted(task)

        if task.pipeline_stage != "archive":
            raise HTTPException(
                status_code=422,
                detail="Only archived tasks can be reopened.",
            )

        role_level = caller.role.level if caller.role else 1
        if task.created_by != caller.id and role_level < 4:
            raise HTTPException(
                status_code=403,
                detail="Only the task creator or a manager can reopen this task.",
            )

        before = _task_snapshot(task)
        task.pipeline_stage           = "in_progress"
        task.status                   = "in_progress"
        task.assignee_confirmed_done  = False
        task.creator_approved_done    = False
        task.is_reopened              = True
        await db.flush()

        notif_body = (
            f"Task {task.ticket_number} was reopened by {caller.username}. "
            f"It has been moved back to In Progress."
        )
        action_url = f"/tasks/{task.id}"
        notify_ids = {str(caller.id)}

        if task.assignee_user_id and str(task.assignee_user_id) not in notify_ids:
            await _notify(
                db, task.assignee_user_id, caller.tenant_id, "task_reopened",
                f"Task reopened: {task.title}",
                notif_body,
                action_url=action_url,
                sender_id=caller.id, related_task_id=task.id,
            )
            notify_ids.add(str(task.assignee_user_id))

        mgr = await _get_dept_manager(db, task.department_id) if task.department_id else None
        if mgr and str(mgr.id) not in notify_ids:
            await _notify(
                db, mgr.id, caller.tenant_id, "task_reopened",
                f"Task in your department was reopened: {task.title}",
                notif_body,
                action_url=action_url,
                related_task_id=task.id,
            )

        await _log_audit_event(
            db, caller.id, "task.reopened", "task", task.id, caller.tenant_id,
            before_state=before,
            after_state={"pipeline_stage": "in_progress", "is_reopened": True},
            ip_address=ip_address,
        )

        return await self._reload(db, task.id)

    # ── Soft delete ───────────────────────────────────────────

    async def soft_delete(
        self,
        db:      AsyncSession,
        task_id: uuid.UUID,
        reason:  str,
        caller:  User,
        ip:      Optional[str] = None,
    ) -> None:
        if not reason or len(reason.strip()) < 10:
            raise HTTPException(
                status_code=422,
                detail="A deletion reason of at least 10 characters is required.",
            )

        role_level = caller.role.level if caller.role else 1
        if role_level < 4:
            raise HTTPException(status_code=403, detail="Only admins can delete tasks.")

        task = await self._get_task_or_404(db, task_id)
        if task.is_deleted:
            raise HTTPException(status_code=422, detail="Task is already deleted.")

        before = _task_snapshot(task)
        now = datetime.datetime.utcnow()
        task.is_deleted      = True
        task.deleted_at      = now
        task.deleted_by      = caller.id
        task.deletion_reason = reason
        await db.flush()

        # Notify creator's dept manager
        if task.created_by:
            creator = (await db.execute(
                select(User).options(selectinload(User.staff_profile))
                .where(User.id == task.created_by)
            )).scalar_one_or_none()
            if creator and creator.staff_profile and creator.staff_profile.department_id:
                mgr = await _get_dept_manager(db, creator.staff_profile.department_id)
                if mgr:
                    await _notify(
                        db, mgr.id, caller.tenant_id,
                        "task_deleted",
                        f"Task deleted: {task.title}",
                        f"Task {task.ticket_number} was deleted by {caller.username}. Reason: {reason}",
                        action_url="/tasks/deleted",
                        related_task_id=task.id,
                    )

        await _log_audit_event(
            db, caller.id, "task.soft_deleted", "task", task.id, caller.tenant_id,
            before_state=before,
            after_state={"is_deleted": True, "deleted_at": now.isoformat(), "deletion_reason": reason},
            ip_address=ip,
        )

    # ── Restore ───────────────────────────────────────────────

    async def restore_task(self, db: AsyncSession, task_id: uuid.UUID, caller: User, ip_address: Optional[str] = None) -> Task:
        role_level = caller.role.level if caller.role else 1
        if role_level < 4:
            raise HTTPException(status_code=403, detail="Only admins can restore tasks.")

        task = (await db.execute(
            select(Task).where(Task.id == task_id)
        )).scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found.")
        if not task.is_deleted:
            raise HTTPException(status_code=422, detail="Task is not deleted.")

        task.is_deleted      = False
        task.deleted_at      = None
        task.deleted_by      = None
        task.deletion_reason = None
        task.pipeline_stage  = "backlog"
        await db.flush()

        # Notify creator and assignee
        for uid in {task.created_by, task.assignee_user_id}:
            if uid:
                await _notify(
                    db, uid, caller.tenant_id,
                    "task_assigned",
                    f"Task restored: {task.title}",
                    f"Task {task.ticket_number} has been restored by {caller.username}.",
                    action_url=f"/tasks/{task.id}",
                    related_task_id=task.id,
                )

        await _log_audit_event(
            db, caller.id, "task.restored", "task", task.id, caller.tenant_id,
            after_state={"is_deleted": False, "pipeline_stage": "backlog"},
            ip_address=ip_address,
        )

        return await self._reload(db, task.id)

    # ── Hard purge (super-admin) ──────────────────────────────

    async def purge_task(self, db: AsyncSession, task_id: uuid.UUID, caller: User, ip_address: Optional[str] = None) -> None:
        role_level = caller.role.level if caller.role else 1
        if role_level < 5:
            raise HTTPException(status_code=403, detail="Only super-admins can purge tasks.")

        task = (await db.execute(
            select(Task).where(Task.id == task_id)
        )).scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found.")
        if not task.is_deleted:
            raise HTTPException(
                status_code=422,
                detail="Task must be soft-deleted before purging.",
            )

        await _log_audit_event(
            db, caller.id, "task.purged", "task", task.id, caller.tenant_id,
            after_state={"IRREVERSIBLE": True, "ticket_number": task.ticket_number},
            ip_address=ip_address,
        )
        await db.delete(task)
        await db.flush()

    # ── Archive reference storage ─────────────────────────────

    async def _store_archive_refs(
        self,
        db:         AsyncSession,
        task_id:    uuid.UUID,
        ref_ids:    list[uuid.UUID],
        caller:     User,
    ) -> None:
        for ref_id in ref_ids:
            archived = (await db.execute(
                select(Task).where(Task.id == ref_id)
            )).scalar_one_or_none()
            if archived and archived.pipeline_stage == "archive":
                db.add(ArchiveReference(
                    task_id=task_id,
                    referenced_archive_task_id=ref_id,
                    referenced_by=caller.id,
                    tenant_id=caller.tenant_id,
                ))
        await db.flush()

    # ── Pipeline stage sync ───────────────────────────────────

    @staticmethod
    def sync_pipeline_stage(task: Task, new_status: str) -> None:
        task.pipeline_stage = STATUS_TO_PIPELINE_STAGE.get(new_status, task.pipeline_stage)

    # ── Project completion check ──────────────────────────────

    async def _check_project_completion(
        self, db: AsyncSession, project_id: uuid.UUID, caller: User
    ) -> None:
        from app.modules.projects.models import Project
        incomplete = (await db.execute(
            select(func.count()).select_from(
                select(Task).where(
                    Task.project_id == project_id,
                    Task.status != "archived",
                    Task.is_deleted == False,  # noqa: E712
                ).subquery()
            )
        )).scalar_one()

        if incomplete == 0:
            project = (await db.execute(
                select(Project).where(Project.id == project_id)
            )).scalar_one_or_none()
            if project:
                project.pipeline_status      = "completed"
                project.pipeline_completed_at = datetime.datetime.utcnow()
                await db.flush()
                await _log_audit_event(
                    db, caller.id, "project.pipeline_completed", "project",
                    project.id, caller.tenant_id,
                    after_state={"pipeline_status": "completed"},
                )

    # ── Permission guards ─────────────────────────────────────

    async def _assert_can_assign(self, caller: User, task: Task) -> None:
        sp = caller.staff_profile
        if sp and sp.department_id and sp.department_id != task.department_id:
            raise HTTPException(
                status_code=403,
                detail="You can only assign tasks within your own department.",
            )
        role_level = caller.role.level if caller.role else 1
        authority  = sp.approval_authority_level if sp else 0
        if role_level < 3 and authority < 2:
            raise HTTPException(
                status_code=403,
                detail="Only managers, team leads, or admins can assign department tasks.",
            )

    @staticmethod
    def _assert_not_deleted(task: Task) -> None:
        if task.is_deleted:
            raise HTTPException(status_code=404, detail="Task not found.")

    # ── Loaders ───────────────────────────────────────────────

    async def _get_task_or_404(self, db: AsyncSession, task_id: uuid.UUID) -> Task:
        task = (await db.execute(
            select(Task).where(Task.id == task_id)
        )).scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found.")
        return task

    async def _reload(self, db: AsyncSession, task_id: uuid.UUID) -> Task:
        return (await db.execute(
            select(Task)
            .options(
                selectinload(Task.assignee),
                selectinload(Task.department),
                selectinload(Task.tags),
                selectinload(Task.comments),
                selectinload(Task.responsible_user),
            )
            .where(Task.id == task_id)
        )).scalar_one()

    @staticmethod
    def _parse_deadline(raw: Optional[str]) -> Optional[datetime.datetime]:
        if not raw:
            return None
        try:
            return datetime.datetime.fromisoformat(raw)
        except ValueError:
            return None


task_workflow_service = TaskWorkflowService()
