# ============================================================
# OPSYN PROJECTS PIPELINE SERVICE — app/modules/projects/pipeline_service.py
# Business logic for pipeline operations
# ============================================================

from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException
from app.modules.projects.schemas import (
    PipelineTemplateCreate,
    PipelineTemplateResponse,
    PipelineTemplateStageResponse,
)

from app.modules.projects.models import (
    Project, PipelineTemplate, PipelineTemplateStage, ProjectPipelineStage,
    ProjectStageComment, ProjectStageApproval, StageFieldCompletion,
)
from app.modules.projects.schemas import (
    ProjectPipelineResponse, ProjectPipelineStageResponse, ProjectStageCommentResponse
)
from app.modules.projects.policy import can_manage_pipeline, can_comment_on_stage, can_approve_stage
from app.modules.staff.models import User
from app.modules.organisation.models import Department
from app.modules.audit.service import audit_service
from app.events.bus import event_bus
from app.modules.activity.service import timeline_writer


async def start_pipeline(project_id: uuid.UUID, template_id: uuid.UUID, db: AsyncSession, current_user: User) -> ProjectPipelineStage:
    """
    Validates project exists and has no active pipeline
    Loads template and all its stages
    Creates project_pipeline_stages rows for ALL stages with status='pending'
    Sets Stage 1 to status='active', entered_at=now()
    If Stage 2 has is_parallel=True, also set Stage 2 to status='active', entered_at=now() immediately
    Updates projects.pipeline_template_id, projects.current_stage_id (→ Stage 1), projects.pipeline_status='active', projects.pipeline_started_at=now()
    Emits project.pipeline_started event
    Writes audit log
    """
    # Validate project exists and no active pipeline
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.pipeline_status != "not_started":
        raise HTTPException(status_code=400, detail="Project already has an active pipeline")

    # Load template with stages
    template = await db.get(PipelineTemplate, template_id, options=[selectinload(PipelineTemplate.stages)])
    if not template or not template.is_active:
        raise HTTPException(status_code=404, detail="Pipeline template not found or inactive")

    # Create pipeline stages
    pipeline_stages = []
    for template_stage in template.stages:
        stage = ProjectPipelineStage(
            project_id=project_id,
            template_stage_id=template_stage.id,
            stage_order=template_stage.stage_order,
            stage_name=template_stage.stage_name,
            department_id=template_stage.department_id,
            status="pending"
        )
        db.add(stage)
        pipeline_stages.append(stage)

    await db.flush()  # Get IDs

    # Set Stage 1 active
    stage_1 = next(s for s in pipeline_stages if s.stage_order == 1)
    stage_1.status = "active"
    stage_1.entered_at = datetime.utcnow()

    # If Stage 2 is parallel, activate it too
    stage_2 = next((s for s in pipeline_stages if s.stage_order == 2), None)
    if stage_2 and any(ts.is_parallel for ts in template.stages if ts.stage_order == 2):
        stage_2.status = "active"
        stage_2.entered_at = datetime.utcnow()

    # Update project
    project.pipeline_template_id = template_id
    project.current_stage_id = stage_1.id
    project.pipeline_status = "active"
    project.pipeline_started_at = datetime.utcnow()

    await db.flush()

    # Emit event
    await event_bus.emit("project.pipeline_started", {
        "project_id": str(project_id),
        "project_name": project.name,
        "template_name": template.name,
        "started_by": f"{current_user.staff_profile.first_name} {current_user.staff_profile.last_name}" if current_user.staff_profile else str(current_user.id)
    })

    # Audit log
    await audit_service.log_event(
        actor_id=current_user.id,
        action="project.pipeline.started",
        target_type="project",
        target_id=str(project_id),
        before_state={"pipeline_status": "not_started"},
        after_state={"pipeline_status": "active", "template_id": str(template_id)},
        ip_address=None,
        tenant_id=current_user.tenant_id,
    )

    return stage_1


async def start_graph_pipeline(project_id: uuid.UUID, workflow_id: uuid.UUID, db: AsyncSession, current_user: User) -> ProjectPipelineStage:
    """Start a pipeline from a graph-based DeptWorkflow instead of a linear template."""
    from app.modules.organisation.workflow_service import get_workflow_graph_for_project_start

    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.pipeline_status != "not_started":
        raise HTTPException(status_code=400, detail="Project already has an active pipeline")

    edges = await get_workflow_graph_for_project_start(workflow_id, db)
    if not edges:
        raise HTTPException(status_code=400, detail="Workflow has no edges defined")

    # Build stages: each unique edge_order value → one step; multiple edges at same order = parallel
    pipeline_stages: list[ProjectPipelineStage] = []
    for edge in sorted(edges, key=lambda e: e.edge_order):
        stage = ProjectPipelineStage(
            project_id=project_id,
            template_stage_id=None,
            workflow_edge_id=edge.id,
            stage_order=edge.edge_order,
            stage_name=edge.to_dept.name if edge.to_dept else f"Stage {edge.edge_order}",
            department_id=edge.to_dept_id,
            status="pending",
        )
        db.add(stage)
        pipeline_stages.append(stage)

    await db.flush()

    # Activate all stages at edge_order = 1 (entry stages, possibly parallel)
    first_order = min(s.stage_order for s in pipeline_stages)
    first_stages = [s for s in pipeline_stages if s.stage_order == first_order]
    for stage in first_stages:
        stage.status = "active"
        stage.entered_at = datetime.utcnow()

    project.workflow_id = workflow_id
    project.pipeline_template_id = None
    project.current_stage_id = first_stages[0].id
    project.pipeline_status = "active"
    project.pipeline_started_at = datetime.utcnow()

    await db.flush()

    await event_bus.emit("project.pipeline_started", {
        "project_id": str(project_id),
        "project_name": project.name,
        "workflow_id": str(workflow_id),
        "started_by": f"{current_user.staff_profile.first_name} {current_user.staff_profile.last_name}" if current_user.staff_profile else str(current_user.id),
    })

    await audit_service.log_event(
        actor_id=current_user.id,
        action="project.pipeline.started",
        target_type="project",
        target_id=str(project_id),
        before_state={"pipeline_status": "not_started"},
        after_state={"pipeline_status": "active", "workflow_id": str(workflow_id)},
        ip_address=None,
        tenant_id=current_user.tenant_id,
    )

    return first_stages[0]


async def advance_stage(project_id: uuid.UUID, comment: str | None, db: AsyncSession, current_user: User) -> ProjectPipelineStage:
    """
    Loads current active stage for the project
    RBAC check: caller's department must match current stage's department_id OR caller role level >= 4
    Scope check: use existing policy.can_manage_pipeline(user, stage.department_id)
    Gate check for parallel stages: if next stage requires a parallel stage to be approved first, check it — if not, raise HTTP 400 with detail "gate_not_cleared" and message explaining Finance must confirm first
    Sets current stage: status='approved', exited_at=now(), approved_by=current_user.id
    If comment provided, creates project_stage_comments row with comment_type='approval_note'
    Activates next stage: status='active', entered_at=now()
    If next stage is a parallel stage (is_parallel=True), also activate the stage after it simultaneously
    If no next stage exists: sets projects.pipeline_status='completed', projects.pipeline_completed_at=now()
    Updates projects.current_stage_id to the next active non-parallel stage
    Emits project.stage_advanced event with {project_id, from_stage, to_stage, advanced_by}
    Writes audit log row
    """
    # Load project with current stage
    project = await db.get(Project, project_id, options=[
        selectinload(Project.pipeline_stages),
        selectinload(Project.pipeline_template).selectinload(PipelineTemplate.stages)
    ])
    if not project or project.pipeline_status != "active":
        raise HTTPException(status_code=404, detail="Active pipeline not found")

    current_stage = project.current_stage
    if not current_stage or current_stage.status != "active":
        raise HTTPException(status_code=400, detail="No active stage to advance")

    # RBAC check
    if not can_manage_pipeline(current_user, current_stage.department_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions to advance this stage")

    # Gate check for parallel stages (skip when project has no template)
    template_stages = (
        {ts.stage_order: ts for ts in project.pipeline_template.stages}
        if project.pipeline_template else {}
    )
    current_template_stage = template_stages.get(current_stage.stage_order)
    if current_template_stage and current_template_stage.parallel_gate_stage_order:
        gate_stage = next((s for s in project.pipeline_stages if s.stage_order == current_template_stage.parallel_gate_stage_order), None)
        if gate_stage and gate_stage.status != "approved":
            raise HTTPException(
                status_code=400,
                detail="gate_not_cleared",
                headers={"X-Error-Message": f"Cannot advance until Stage {current_template_stage.parallel_gate_stage_order} is approved"}
            )

    # Field completion gate — block if required fields are incomplete
    from app.modules.customers.models import FieldVisibilityRule
    incomplete_rows = (await db.execute(
        select(StageFieldCompletion, FieldVisibilityRule)
        .join(
            FieldVisibilityRule,
            (FieldVisibilityRule.field_definition_id == StageFieldCompletion.field_definition_id)
            & (FieldVisibilityRule.stage_order == current_stage.stage_order),
        )
        .where(
            StageFieldCompletion.project_id   == project_id,
            StageFieldCompletion.stage_id     == current_stage.id,
            StageFieldCompletion.is_complete  == False,  # noqa: E712
            FieldVisibilityRule.is_required_to_advance == True,  # noqa: E712
        )
    )).all()
    if incomplete_rows:
        from app.modules.customers.models import FieldDefinition
        field_ids = [row.StageFieldCompletion.field_definition_id for row in incomplete_rows]
        field_defs = (await db.execute(
            select(FieldDefinition).where(FieldDefinition.id.in_(field_ids))
        )).scalars().all()
        missing = [fd.key for fd in field_defs]
        raise HTTPException(
            status_code=422,
            detail={"missing_required_fields": missing},
        )

    # Schema-driven stage gate. Forms are stored against the project entity and
    # linked to the stage association that required them; a submission from a
    # different project or association must not satisfy this gate.
    from app.modules.form_builder.models import FormAssociation, FormSchema, FormSubmission
    mandatory_forms = (await db.execute(
        select(FormAssociation, FormSchema.name)
        .join(FormSchema, FormSchema.id == FormAssociation.schema_id)
        .where(
            FormAssociation.tenant_id == current_user.tenant_id,
            FormAssociation.context_type == "pipeline_stage",
            or_(FormAssociation.context_id == current_stage.id, FormAssociation.context_id.is_(None)),
            FormAssociation.is_mandatory == True,  # noqa: E712
            FormAssociation.is_deleted == False,  # noqa: E712
            FormSchema.tenant_id == current_user.tenant_id,
            FormSchema.status == "published",
            FormSchema.is_deleted == False,  # noqa: E712
        )
        .order_by(FormAssociation.display_order, FormAssociation.created_at)
    )).all()
    missing_forms: list[str] = []
    for association, schema_name in mandatory_forms:
        completed = (await db.execute(
            select(FormSubmission.id).where(
                FormSubmission.tenant_id == current_user.tenant_id,
                FormSubmission.schema_id == association.schema_id,
                FormSubmission.association_id == association.id,
                FormSubmission.entity_type == "project",
                FormSubmission.entity_id == project_id,
                FormSubmission.status.in_(("submitted", "approved")),
                FormSubmission.is_deleted == False,  # noqa: E712
            ).limit(1)
        )).scalar_one_or_none()
        if completed is None:
            missing_forms.append(schema_name)
    if missing_forms:
        raise HTTPException(
            status_code=422,
            detail={"missing_required_forms": missing_forms},
        )

    # Approval gate — block if template stage requires explicit approval and none recorded
    if current_template_stage and current_template_stage.requires_approval:
        approval = (await db.execute(
            select(ProjectStageApproval).where(
                ProjectStageApproval.project_id  == project_id,
                ProjectStageApproval.stage_id    == current_stage.id,
                ProjectStageApproval.approved_at.isnot(None),
            )
        )).scalar_one_or_none()
        if not approval:
            raise HTTPException(
                status_code=403,
                detail="Awaiting approval. A manager or team lead must approve this stage before it can be advanced.",
            )

    # Set current stage approved
    current_stage.status = "approved"
    current_stage.exited_at = datetime.utcnow()
    current_stage.approved_by = current_user.id

    # Add comment if provided
    if comment:
        db.add(ProjectStageComment(
            project_id=project_id,
            stage_id=current_stage.id,
            author_user_id=current_user.id,
            body=comment,
            comment_type="approval_note"
        ))

    # Find and activate next stage
    next_stage_order = current_stage.stage_order + 1
    next_stage = next((s for s in project.pipeline_stages if s.stage_order == next_stage_order), None)

    if next_stage:
        next_stage.status = "active"
        next_stage.entered_at = datetime.utcnow()

        # If next is parallel, activate the one after it too
        next_template_stage = template_stages.get(next_stage_order)
        if next_template_stage and next_template_stage.is_parallel:
            after_next_order = next_stage_order + 1
            after_next_stage = next((s for s in project.pipeline_stages if s.stage_order == after_next_order), None)
            if after_next_stage:
                after_next_stage.status = "active"
                after_next_stage.entered_at = datetime.utcnow()

        project.current_stage = next_stage
    else:
        # No more stages
        project.pipeline_status = "completed"
        project.pipeline_completed_at = datetime.utcnow()
        project.current_stage = None

    await db.flush()

    # Timeline event for stage advancement
    to_stage_name = next_stage.stage_name if next_stage else "Completed"
    await timeline_writer.write_stage_event(
        db, "project", project_id, current_user.id,
        body=f"Pipeline stage advanced: '{current_stage.stage_name}' → '{to_stage_name}'.",
        from_state=current_stage.stage_name,
        to_state=to_stage_name,
    )

    # Notify next department that the stage has arrived
    if next_stage:
        from app.modules.notifications.service import notification_service
        actor_name = (
            current_user.staff_profile.full_name
            if current_user.staff_profile else current_user.username
        )
        await notification_service.notify_department(
            db                 = db,
            dept_id            = str(next_stage.department_id),
            notif_type         = "pipeline.stage_arrived",
            title              = f"New stage ready: {next_stage.stage_name}",
            body               = f"Project '{project.name}' has reached your department's stage. Advanced by {actor_name}.",
            action_url         = f"/projects/{project_id}/pipeline",
            sender_id          = str(current_user.id),
            related_project_id = str(project_id),
            exclude_user_ids   = [str(current_user.id)],
        )

    # Emit event
    await event_bus.emit("project.stage_advanced", {
        "project_id": str(project_id),
        "project_name": project.name,
        "from_stage_name": current_stage.stage_name,
        "to_stage_name": next_stage.stage_name if next_stage else None,
        "to_department_id": str(next_stage.department_id) if next_stage else None,
        "to_department_name": None,  # TODO: join department name
        "advanced_by_name": f"{current_user.staff_profile.first_name} {current_user.staff_profile.last_name}" if current_user.staff_profile else str(current_user.id)
    })

    # Audit log
    await audit_service.log_event(
        actor_id=current_user.id,
        action="project.pipeline.advanced",
        target_type="project_pipeline_stage",
        target_id=str(current_stage.id),
        before_state={"status": "active"},
        after_state={"status": "approved"},
        ip_address=None,
        tenant_id=current_user.tenant_id,
    )

    return next_stage or current_stage


async def push_back_stage(project_id: uuid.UUID, reason: str, comment: str | None, db: AsyncSession, current_user: User) -> ProjectPipelineStage:
    """
    Loads current active stage
    RBAC check: same as advance — department match OR role >= 4
    Validates this is not Stage 1 (cannot push back from the first stage — create a cancel action instead)
    Sets current stage: status='pushed_back', exited_at=now(), pushed_back_reason=reason, pushed_back_by=current_user.id
    Creates project_stage_comments row with comment_type='pushback_reason', body=reason
    Finds the previous stage (by stage_order - 1, skipping parallel stages going backward)
    Reactivates previous stage: status='active', clears exited_at, clears approved_by
    Updates projects.current_stage_id to the reactivated stage
    Emits project.stage_pushed_back event with {project_id, from_stage, to_stage, reason, pushed_back_by}
    Writes audit log row
    """
    # Load project with stages
    project = await db.get(Project, project_id, options=[selectinload(Project.pipeline_stages)])
    if not project or project.pipeline_status != "active":
        raise HTTPException(status_code=404, detail="Active pipeline not found")

    current_stage = project.current_stage
    if not current_stage or current_stage.status != "active":
        raise HTTPException(status_code=400, detail="No active stage to push back")

    # Cannot push back from stage 1
    if current_stage.stage_order == 1:
        raise HTTPException(status_code=400, detail="Cannot push back from the first stage")

    # RBAC check
    if not can_manage_pipeline(current_user, current_stage.department_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions to push back this stage")

    # Set current stage pushed back
    current_stage.status = "pushed_back"
    current_stage.exited_at = datetime.utcnow()
    current_stage.pushed_back_reason = reason
    current_stage.pushed_back_by = current_user.id

    # Add pushback comment
    db.add(ProjectStageComment(
        project_id=project_id,
        stage_id=current_stage.id,
        author_user_id=current_user.id,
        body=reason,
        comment_type="pushback_reason"
    ))

    # Add additional comment if provided
    if comment:
        db.add(ProjectStageComment(
            project_id=project_id,
            stage_id=current_stage.id,
            author_user_id=current_user.id,
            body=comment,
            comment_type="progress"
        ))

    # Find previous stage (skip parallel stages going backward)
    prev_stage_order = current_stage.stage_order - 1
    prev_stage = next((s for s in project.pipeline_stages if s.stage_order == prev_stage_order), None)
    if not prev_stage:
        raise HTTPException(status_code=400, detail="No previous stage to reactivate")

    # Reactivate previous stage
    prev_stage.status = "active"
    prev_stage.exited_at = None
    prev_stage.approved_by = None
    project.current_stage = prev_stage

    await db.flush()

    # Timeline event for push-back
    await timeline_writer.write_stage_event(
        db, "project", project_id, current_user.id,
        body=f"Stage pushed back: '{current_stage.stage_name}' → '{prev_stage.stage_name}'. Reason: {reason}",
        from_state=current_stage.stage_name,
        to_state=prev_stage.stage_name,
        meta={"reason": reason},
    )

    # Emit event
    await event_bus.emit("project.stage_pushed_back", {
        "project_id": str(project_id),
        "project_name": project.name,
        "from_stage_name": current_stage.stage_name,
        "to_stage_name": prev_stage.stage_name,
        "to_department_id": str(prev_stage.department_id),
        "reason": reason,
        "pushed_back_by_name": f"{current_user.staff_profile.first_name} {current_user.staff_profile.last_name}" if current_user.staff_profile else str(current_user.id)
    })

    # Audit log
    await audit_service.log_event(
        actor_id=current_user.id,
        action="project.pipeline.pushed_back",
        target_type="project_pipeline_stage",
        target_id=str(current_stage.id),
        before_state={"status": "active"},
        after_state={"status": "pushed_back", "reason": reason},
        ip_address=None,
        tenant_id=current_user.tenant_id,
    )

    return prev_stage


async def add_stage_comment(project_id: uuid.UUID, stage_id: uuid.UUID, body: str, comment_type: str, db: AsyncSession, current_user: User) -> ProjectStageComment:
    """
    Validates stage belongs to project
    RBAC check: caller's department matches stage's department OR role >= 3 (Team Lead+)
    Creates project_stage_comments row
    Returns comment with author name joined
    """
    # Load stage with project check
    stage = await db.get(ProjectPipelineStage, stage_id, options=[selectinload(ProjectPipelineStage.project)])
    if not stage or str(stage.project_id) != str(project_id):
        raise HTTPException(status_code=404, detail="Stage not found")

    # RBAC check
    if not can_comment_on_stage(current_user, stage.department_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions to comment on this stage")

    # Create comment
    comment = ProjectStageComment(
        project_id=project_id,
        stage_id=stage_id,
        author_user_id=current_user.id,
        body=body,
        comment_type=comment_type
    )
    db.add(comment)
    await db.flush()

    # Load author name
    await db.refresh(comment)  # To get the created_at

    return comment


async def approve_stage(project_id: uuid.UUID, stage_id: uuid.UUID, notes: str | None, db: AsyncSession, current_user: User) -> ProjectStageApproval:
    """
    Grant formal approval for a pipeline stage gate.
    Only Team Lead+ (role >= 3) or department-scoped user may approve.
    Creates or updates a ProjectStageApproval row. Emits timeline entry.
    """
    # Verify stage belongs to this project and is active
    stage = (await db.execute(
        select(ProjectPipelineStage).where(
            ProjectPipelineStage.id         == stage_id,
            ProjectPipelineStage.project_id == project_id,
        )
    )).scalar_one_or_none()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found for this project.")
    if stage.status != "active":
        raise HTTPException(status_code=400, detail=f"Stage is not active (status: {stage.status}). Only active stages can be approved.")

    # RBAC
    if not can_approve_stage(current_user, stage.department_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions to approve this stage.")

    # Upsert approval record
    existing = (await db.execute(
        select(ProjectStageApproval).where(
            ProjectStageApproval.project_id == project_id,
            ProjectStageApproval.stage_id   == stage_id,
        )
    )).scalar_one_or_none()

    now = datetime.utcnow()
    if existing:
        existing.approver_id = current_user.id
        existing.approved_at = now
        existing.notes       = notes
        approval = existing
    else:
        approval = ProjectStageApproval(
            tenant_id   = current_user.tenant_id,
            project_id  = project_id,
            stage_id    = stage_id,
            approver_id = current_user.id,
            approved_at = now,
            notes       = notes,
        )
        db.add(approval)

    await db.flush()

    # Timeline entry
    actor_label = (
        current_user.staff_profile.full_name
        if current_user.staff_profile else current_user.username
    )
    await timeline_writer.write_stage_event(
        db, "project", project_id, current_user.id,
        body=f"Stage '{stage.stage_name}' approved by {actor_label}." + (f" Notes: {notes}" if notes else ""),
        from_state=stage.stage_name,
        to_state="approved_gate",
        meta={"notes": notes, "approver": actor_label},
    )

    # Audit log
    await audit_service.log_event(
        actor_id   = current_user.id,
        action     = "project.pipeline.stage_approved",
        target_type= "project_pipeline_stage",
        target_id  = str(stage_id),
        before_state={"approved_at": None},
        after_state ={"approved_at": now.isoformat(), "approver_id": str(current_user.id)},
        ip_address = None,
        tenant_id  = current_user.tenant_id,
    )

    return approval


async def get_pipeline(project_id: uuid.UUID, db: AsyncSession, current_user: User) -> ProjectPipelineResponse:
    """
    Loads project with all pipeline stages ordered by stage_order
    For each stage, loads its comments ordered by created_at
    Computes can_advance and can_push_back booleans for the current user based on department match and role level
    Returns full ProjectPipelineResponse
    """
    # Load project with full pipeline data
    project = await db.get(Project, project_id, options=[
        selectinload(Project.pipeline_template).selectinload(PipelineTemplate.stages),
        selectinload(Project.pipeline_stages).selectinload(ProjectPipelineStage.comments).selectinload(ProjectStageComment.stage)
    ])
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Load department names for stages
    dept_ids = {s.department_id for s in project.pipeline_stages}
    depts = await db.execute(select(Department).where(Department.id.in_(dept_ids)))
    dept_map = {d.id: d.name for d in depts.scalars()}

    # Build stage responses
    all_stages = []
    for stage in sorted(project.pipeline_stages, key=lambda s: s.stage_order):
        # Load comments with author names
        comments = []
        for comment in stage.comments:
            author_name = "Unknown"
            if comment.author_user_id:
                # TODO: join user name
                author_name = str(comment.author_user_id)  # Placeholder

            comments.append(ProjectStageCommentResponse(
                id=comment.id,
                stage_id=comment.stage_id,
                author_user_id=comment.author_user_id,
                author_name=author_name,
                body=comment.body,
                comment_type=comment.comment_type,
                created_at=comment.created_at
            ))

        duration_days = None
        if stage.entered_at and stage.exited_at:
            duration_days = (stage.exited_at - stage.entered_at).total_seconds() / (24 * 3600)

        all_stages.append(ProjectPipelineStageResponse(
            id=stage.id,
            project_id=stage.project_id,
            stage_order=stage.stage_order,
            stage_name=stage.stage_name,
            department_id=stage.department_id,
            department_name=dept_map.get(stage.department_id, "Unknown"),
            status=stage.status,
            assigned_to_user_id=stage.assigned_to_user_id,
            entered_at=stage.entered_at,
            exited_at=stage.exited_at,
            pushed_back_reason=stage.pushed_back_reason,
            duration_days=duration_days,
            comments=comments
        ))

    current_stage = next((s for s in all_stages if s.id == project.current_stage_id), None)

    # Compute permissions
    can_advance = can_push_back = False
    if current_stage and current_stage.status == "active":
        can_advance = can_manage_pipeline(current_user, current_stage.department_id)
        can_push_back = can_manage_pipeline(current_user, current_stage.department_id) and current_stage.stage_order > 1

    # Load current stage approval state, requires_approval flag, and missing required fields
    current_stage_approval = None
    stage_requires_approval = False
    missing_required_fields: list[str] = []

    if current_stage and current_stage.status == "active":
        active_stage_obj = next(
            (s for s in project.pipeline_stages if s.id == project.current_stage_id), None
        )
        if active_stage_obj:
            # Check if the template stage requires approval
            if project.pipeline_template:
                tmpl_stage = next(
                    (ts for ts in project.pipeline_template.stages
                     if ts.stage_order == active_stage_obj.stage_order), None
                )
                stage_requires_approval = bool(tmpl_stage and tmpl_stage.requires_approval)

            approval_row = (await db.execute(
                select(ProjectStageApproval).where(
                    ProjectStageApproval.project_id == project.id,
                    ProjectStageApproval.stage_id   == active_stage_obj.id,
                )
            )).scalar_one_or_none()
            if approval_row:
                current_stage_approval = {
                    "id":          str(approval_row.id),
                    "approved_at": approval_row.approved_at.isoformat() if approval_row.approved_at else None,
                    "approver_id": str(approval_row.approver_id) if approval_row.approver_id else None,
                    "notes":       approval_row.notes,
                }

            # Incomplete required fields at this stage
            from app.modules.customers.models import FieldDefinition, FieldVisibilityRule
            incomplete = (await db.execute(
                select(FieldDefinition.key)
                .join(
                    StageFieldCompletion,
                    StageFieldCompletion.field_definition_id == FieldDefinition.id,
                )
                .join(
                    FieldVisibilityRule,
                    (FieldVisibilityRule.field_definition_id == FieldDefinition.id)
                    & (FieldVisibilityRule.stage_order == active_stage_obj.stage_order),
                )
                .where(
                    StageFieldCompletion.project_id  == project.id,
                    StageFieldCompletion.stage_id    == active_stage_obj.id,
                    StageFieldCompletion.is_complete == False,  # noqa: E712
                    FieldVisibilityRule.is_required_to_advance == True,  # noqa: E712
                )
            )).scalars().all()
            missing_required_fields = list(incomplete)

    return ProjectPipelineResponse(
        project_id=project.id,
        project_name=project.name,
        pipeline_template_id=project.pipeline_template_id,
        pipeline_template_name=project.pipeline_template.name if project.pipeline_template else "Unknown",
        pipeline_status=project.pipeline_status,
        current_stage=current_stage,
        all_stages=all_stages,
        can_advance=can_advance,
        can_push_back=can_push_back,
        current_stage_approval=current_stage_approval,
        stage_requires_approval=stage_requires_approval,
        missing_required_fields=missing_required_fields,
    )


async def get_all_templates(db: AsyncSession) -> list[PipelineTemplateResponse]:
    templates = await db.execute(
        select(PipelineTemplate)
        .options(selectinload(PipelineTemplate.stages))
        .where(PipelineTemplate.is_active == True)
        .order_by(PipelineTemplate.created_at)
    )
    templates = templates.scalars().all()

    # Load department names
    dept_ids = {ts.department_id for t in templates for ts in t.stages}
    depts = await db.execute(select(Department).where(Department.id.in_(dept_ids)))
    dept_map = {d.id: d.name for d in depts.scalars()}

    responses = []
    for template in templates:
        stages = []
        for ts in sorted(template.stages, key=lambda s: s.stage_order):
            stages.append(PipelineTemplateStageResponse(
                id=ts.id,
                template_id=ts.template_id,
                stage_order=ts.stage_order,
                stage_name=ts.stage_name,
                department_id=ts.department_id,
                department_name=dept_map.get(ts.department_id, "Unknown"),
                is_required=ts.is_required,
                is_parallel=ts.is_parallel,
                parallel_gate_stage_order=ts.parallel_gate_stage_order,
                expected_duration_days=ts.expected_duration_days
            ))

        responses.append(PipelineTemplateResponse(
            id=template.id,
            name=template.name,
            description=template.description,
            is_active=template.is_active,
            stages=stages,
            created_at=template.created_at
        ))

    return responses


async def create_template(data: PipelineTemplateCreate, db: AsyncSession, current_user: User) -> PipelineTemplateResponse:
    # Create template
    template = PipelineTemplate(
        tenant_id=current_user.tenant_id,
        name=data.name,
        description=data.description,
        created_by=current_user.id
    )
    db.add(template)
    await db.flush()

    # Create stages
    stages = []
    for stage_data in data.stages:
        stage = PipelineTemplateStage(
            template_id=template.id,
            stage_order=stage_data.stage_order,
            stage_name=stage_data.stage_name,
            department_id=stage_data.department_id,
            is_required=stage_data.is_required,
            is_parallel=stage_data.is_parallel,
            parallel_gate_stage_order=stage_data.parallel_gate_stage_order,
            expected_duration_days=stage_data.expected_duration_days
        )
        db.add(stage)
        stages.append(stage)

    await db.flush()

    # Build response (similar to get_all_templates)
    dept_ids = {s.department_id for s in stages}
    depts = await db.execute(select(Department).where(Department.id.in_(dept_ids)))
    dept_map = {d.id: d.name for d in depts.scalars()}

    stage_responses = []
    for ts in sorted(stages, key=lambda s: s.stage_order):
        stage_responses.append(PipelineTemplateStageResponse(
            id=ts.id,
            template_id=ts.template_id,
            stage_order=ts.stage_order,
            stage_name=ts.stage_name,
            department_id=ts.department_id,
            department_name=dept_map.get(ts.department_id, "Unknown"),
            is_required=ts.is_required,
            is_parallel=ts.is_parallel,
            parallel_gate_stage_order=ts.parallel_gate_stage_order,
            expected_duration_days=ts.expected_duration_days
        ))

    return PipelineTemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        is_active=template.is_active,
        stages=stage_responses,
        created_at=template.created_at
    )
