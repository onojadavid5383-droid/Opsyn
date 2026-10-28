# ============================================================
# OPSYN PROJECTS MODELS — app/modules/projects/models.py
# SQLAlchemy 2.0 ORM: Project + Pipeline models
# Fixed: __allow_unmapped__ = True for relationship annotations
# ============================================================

from __future__ import annotations
import uuid
import datetime
from sqlalchemy import String, Boolean, ForeignKey, Date, Integer, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Project(Base):
    __tablename__      = "projects"
    __allow_unmapped__ = True   # Allow forward-ref relationship annotations

    id:             Mapped[uuid.UUID]          = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:      Mapped[uuid.UUID]          = mapped_column(ForeignKey("tenants.id"), nullable=False)
    name:           Mapped[str]                = mapped_column(String(200), nullable=False)
    description:    Mapped[str | None]         = mapped_column(Text)
    status:         Mapped[str]                = mapped_column(String(20), default="active")
    project_type:   Mapped[str]                = mapped_column(String(20), default="internal", nullable=False)
    department_id:  Mapped[uuid.UUID | None]   = mapped_column(ForeignKey("departments.id"))
    owner_id:       Mapped[uuid.UUID | None]   = mapped_column(ForeignKey("users.id"))
    completion_pct: Mapped[int]                = mapped_column(Integer, default=0)
    due_date:       Mapped[datetime.date | None]     = mapped_column(Date)
    # Pipeline extensions
    pipeline_template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pipeline_templates.id"))
    workflow_id:          Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dept_workflows.id", ondelete="SET NULL"))
    current_stage_id:     Mapped[uuid.UUID | None] = mapped_column(ForeignKey("project_pipeline_stages.id"))
    pipeline_status:      Mapped[str]             = mapped_column(String(30), default="not_started")
    pipeline_started_at:  Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    pipeline_completed_at:Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    ticket_number:  Mapped[str | None]          = mapped_column(String(20))
    # Phase 5: auto-generation link (migration 0050)
    source_task_id: Mapped[uuid.UUID | None]    = mapped_column(ForeignKey("tasks.id", use_alter=True, ondelete="SET NULL"))
    source_app:     Mapped[str | None]          = mapped_column(String(50))
    auto_generated: Mapped[bool]                = mapped_column(Boolean, default=False)
    # Customer Module: originating customer (migration 0065)
    customer_id:    Mapped[uuid.UUID | None]    = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    created_at:     Mapped[datetime.datetime]  = mapped_column(default=datetime.datetime.utcnow)
    updated_at:     Mapped[datetime.datetime]  = mapped_column(
        default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    # Relationships
    pipeline_template: "PipelineTemplate" = relationship("PipelineTemplate", back_populates="projects", lazy="joined")
    # post_update: projects point at a stage and stages point back at their
    # project. Without it, a flush that touches both (advance, push back,
    # pipeline init) is an unsortable cycle — CircularDependencyError. With it,
    # current_stage_id is written in a separate UPDATE after the rows exist.
    current_stage:     "ProjectPipelineStage" = relationship("ProjectPipelineStage", foreign_keys=[current_stage_id], lazy="joined", post_update=True)
    pipeline_stages:   list["ProjectPipelineStage"] = relationship("ProjectPipelineStage", back_populates="project", foreign_keys="[ProjectPipelineStage.project_id]")


class PipelineTemplate(Base):
    __tablename__      = "pipeline_templates"
    __allow_unmapped__ = True

    id:             Mapped[uuid.UUID]          = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:      Mapped[uuid.UUID]          = mapped_column(ForeignKey("tenants.id"), nullable=False)
    name:           Mapped[str]                = mapped_column(String(200), nullable=False)
    description:    Mapped[str | None]         = mapped_column(Text)
    is_active:      Mapped[bool]               = mapped_column(Boolean, default=True)
    created_by:     Mapped[uuid.UUID]          = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at:     Mapped[datetime.datetime]  = mapped_column(default=datetime.datetime.utcnow)
    updated_at:     Mapped[datetime.datetime]  = mapped_column(
        default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    # Relationships
    stages:         list["PipelineTemplateStage"] = relationship("PipelineTemplateStage", back_populates="template", order_by="PipelineTemplateStage.stage_order")
    projects:       list["Project"] = relationship("Project", back_populates="pipeline_template")


class PipelineTemplateStage(Base):
    __tablename__      = "pipeline_template_stages"
    __allow_unmapped__ = True

    id:                      Mapped[uuid.UUID]          = mapped_column(primary_key=True, default=uuid.uuid4)
    template_id:             Mapped[uuid.UUID]          = mapped_column(ForeignKey("pipeline_templates.id"), nullable=False)
    stage_order:             Mapped[int]                = mapped_column(Integer, nullable=False)
    stage_name:              Mapped[str]                = mapped_column(String(200), nullable=False)
    department_id:           Mapped[uuid.UUID]          = mapped_column(ForeignKey("departments.id"), nullable=False)
    is_required:             Mapped[bool]               = mapped_column(Boolean, default=True)
    is_parallel:             Mapped[bool]               = mapped_column(Boolean, default=False)
    requires_approval:       Mapped[bool]               = mapped_column(Boolean, default=False)
    parallel_gate_stage_order:Mapped[int | None]        = mapped_column(Integer)
    expected_duration_days:  Mapped[int | None]         = mapped_column(Integer)
    created_at:              Mapped[datetime.datetime]  = mapped_column(default=datetime.datetime.utcnow)

    # Relationships
    template:       "PipelineTemplate" = relationship("PipelineTemplate", back_populates="stages")


class ProjectPipelineStage(Base):
    __tablename__      = "project_pipeline_stages"
    __allow_unmapped__ = True

    id:                  Mapped[uuid.UUID]          = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id:          Mapped[uuid.UUID]          = mapped_column(ForeignKey("projects.id"), nullable=False)
    template_stage_id:   Mapped[uuid.UUID | None]    = mapped_column(ForeignKey("pipeline_template_stages.id"), nullable=True)
    workflow_edge_id:    Mapped[uuid.UUID | None]    = mapped_column(ForeignKey("dept_workflow_edges.id", ondelete="SET NULL"), nullable=True)
    stage_order:         Mapped[int]                = mapped_column(Integer, nullable=False)
    stage_name:          Mapped[str]                = mapped_column(String(200), nullable=False)
    department_id:       Mapped[uuid.UUID]          = mapped_column(ForeignKey("departments.id"), nullable=False)
    status:              Mapped[str]                = mapped_column(String(30), default="pending")
    assigned_to_user_id: Mapped[uuid.UUID | None]   = mapped_column(ForeignKey("users.id"))
    entered_at:          Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    exited_at:           Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    pushed_back_reason:  Mapped[str | None]         = mapped_column(Text)
    pushed_back_by:      Mapped[uuid.UUID | None]   = mapped_column(ForeignKey("users.id"))
    approved_by:         Mapped[uuid.UUID | None]   = mapped_column(ForeignKey("users.id"))
    created_at:          Mapped[datetime.datetime]  = mapped_column(default=datetime.datetime.utcnow)
    updated_at:          Mapped[datetime.datetime]  = mapped_column(
        default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    # Relationships
    project:        "Project" = relationship("Project", back_populates="pipeline_stages", foreign_keys=[project_id])
    template_stage: "PipelineTemplateStage" = relationship("PipelineTemplateStage")
    comments:       list["ProjectStageComment"] = relationship("ProjectStageComment", back_populates="stage", order_by="ProjectStageComment.created_at")


class ProjectStageComment(Base):
    __tablename__      = "project_stage_comments"
    __allow_unmapped__ = True

    id:                  Mapped[uuid.UUID]          = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id:          Mapped[uuid.UUID]          = mapped_column(ForeignKey("projects.id"), nullable=False)
    stage_id:            Mapped[uuid.UUID]          = mapped_column(ForeignKey("project_pipeline_stages.id"), nullable=False)
    author_user_id:      Mapped[uuid.UUID]          = mapped_column(ForeignKey("users.id"), nullable=False)
    body:                Mapped[str]                = mapped_column(Text, nullable=False)
    comment_type:        Mapped[str]                = mapped_column(String(30), default="progress")
    attachments:         Mapped[dict | None]        = mapped_column(JSONB)
    created_at:          Mapped[datetime.datetime]  = mapped_column(default=datetime.datetime.utcnow)

    # Relationships
    stage:         "ProjectPipelineStage" = relationship("ProjectPipelineStage", back_populates="comments")


class ProjectStageApproval(Base):
    __tablename__      = "project_stage_approvals"
    __allow_unmapped__ = True

    id:                  Mapped[uuid.UUID]          = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:           Mapped[uuid.UUID]          = mapped_column(ForeignKey("tenants.id"), nullable=False)
    project_id:          Mapped[uuid.UUID]          = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    stage_id:            Mapped[uuid.UUID]          = mapped_column(ForeignKey("project_pipeline_stages.id", ondelete="CASCADE"), nullable=False)
    approver_id:         Mapped[uuid.UUID | None]   = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at:         Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes:               Mapped[str | None]         = mapped_column(Text)
    created_at:          Mapped[datetime.datetime]  = mapped_column(default=datetime.datetime.utcnow)


class StageFieldCompletion(Base):
    __tablename__      = "stage_field_completion"
    __allow_unmapped__ = True

    id:                  Mapped[uuid.UUID]          = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:           Mapped[uuid.UUID]          = mapped_column(ForeignKey("tenants.id"), nullable=False)
    project_id:          Mapped[uuid.UUID]          = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    stage_id:            Mapped[uuid.UUID]          = mapped_column(ForeignKey("project_pipeline_stages.id", ondelete="CASCADE"), nullable=False)
    field_definition_id: Mapped[uuid.UUID]          = mapped_column(ForeignKey("field_definitions.id", ondelete="CASCADE"), nullable=False)
    is_complete:         Mapped[bool]               = mapped_column(Boolean, default=False)
    updated_at:          Mapped[datetime.datetime]  = mapped_column(default=datetime.datetime.utcnow)