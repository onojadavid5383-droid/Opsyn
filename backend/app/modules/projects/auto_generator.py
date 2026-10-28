# ============================================================
# OPSYN PROJECT AUTO-GENERATOR — app/modules/projects/auto_generator.py
# Phase 4: Generates projects automatically from external tasks.
# Called by TaskWorkflowService.create_external_task() and by
# external app trigger endpoints (Sales, HR, Field, Inventory).
# ============================================================

from __future__ import annotations
import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Integer

from app.modules.projects.models import Project
from app.modules.tasks.models import Task
from app.modules.staff.models import User


async def _generate_project_ticket_number(db: AsyncSession) -> str:
    year   = datetime.datetime.utcnow().year
    prefix = f"PRJ-{year}-"
    max_seq = (await db.execute(
        select(func.max(cast(func.right(Project.ticket_number, 4), Integer)))
        .where(Project.ticket_number.like(f"{prefix}%"))
    )).scalar_one_or_none()
    return f"{prefix}{(max_seq or 0) + 1:04d}"


class ProjectAutoGenerator:

    async def generate_from_task(
        self,
        db:         AsyncSession,
        task:       Task,
        caller:     User,
        source_app: Optional[str] = None,
    ) -> Project:
        """
        Called whenever an external task is created.
        Also called by external app triggers (Sales, HR, Field, etc.).
        Creates a Project linked to the source task and updates
        task.project_id in-place (caller must flush/commit).
        """
        ticket  = await _generate_project_ticket_number(db)
        due_date = task.deadline.date() if task.deadline else None

        project = Project(
            name=task.title,
            description=task.description,
            project_type="external",
            source_task_id=task.id,
            auto_generated=True,
            source_app=source_app or "task_engine",
            department_id=task.department_id,
            owner_id=caller.id,
            due_date=due_date,
            ticket_number=ticket,
            tenant_id=task.tenant_id,
            pipeline_status="not_started",
        )
        db.add(project)
        await db.flush()

        # Link task back to the generated project
        task.project_id = project.id

        # Auto-start pipeline if the target department has a default template
        try:
            await self._try_start_pipeline(db, project, task, caller)
        except Exception:
            pass  # Pipeline auto-start is best-effort

        return project

    async def _try_start_pipeline(
        self, db: AsyncSession, project: Project, task: Task, caller: User
    ) -> None:
        from app.modules.projects.pipeline_service import start_pipeline
        from app.modules.projects.models import PipelineTemplate, PipelineTemplateStage, ProjectPipelineStage

        if not task.department_id:
            return

        default_template = (await db.execute(
            select(PipelineTemplate)
            .join(PipelineTemplateStage, PipelineTemplate.id == PipelineTemplateStage.template_id)
            .where(
                PipelineTemplateStage.department_id == task.department_id,
                PipelineTemplate.is_active == True,  # noqa: E712
            )
            .limit(1)
        )).scalar_one_or_none()

        if default_template:
            # Fixed arg order: project_id, template_id, db, current_user
            await start_pipeline(project.id, default_template.id, db, caller)
            return

        # No template found — seed 5 task-mirroring stages so the project
        # has an active pipeline matching the source task's current state.
        TASK_STAGES = [
            ("New",         1),
            ("Assigned",    2),
            ("In Progress", 3),
            ("Review",      4),
            ("Done",        5),
        ]
        TASK_STATUS_TO_ORDER: dict[str, int] = {
            "new": 1, "assigned": 2, "in_progress": 3, "review": 4,
            "done": 5, "blocked": 3, "archived": 5,
        }
        current_order = TASK_STATUS_TO_ORDER.get(task.status or "new", 1)
        now = datetime.datetime.utcnow()

        stages: list[ProjectPipelineStage] = []
        for name, order in TASK_STAGES:
            stage = ProjectPipelineStage(
                project_id=project.id,
                stage_order=order,
                stage_name=name,
                department_id=task.department_id,
                status="pending",
            )
            db.add(stage)
            stages.append(stage)

        await db.flush()

        active_stage = stages[0]
        for stage in stages:
            if stage.stage_order < current_order:
                stage.status = "approved"
                stage.entered_at = now
                stage.exited_at = now
            elif stage.stage_order == current_order:
                stage.status = "active"
                stage.entered_at = now
                active_stage = stage

        project.pipeline_status = "active"
        project.current_stage_id = active_stage.id
        project.pipeline_started_at = now


project_auto_generator = ProjectAutoGenerator()
