# ============================================================
# OPSYN TASKS — app/modules/tasks/models.py
# ORM models, state machine constants, and new workflow tables.
# Phase 5: Added task_scope, pipeline_stage, soft-delete, dual
# approval columns + TaskAssignmentLog, TaskRejectionLog,
# TaskDeptRouting, TaskCompletionApproval, ArchiveReference.
# ============================================================

from __future__ import annotations
import uuid, datetime
from sqlalchemy import (
    String, Text, ForeignKey, DateTime,
    Boolean, JSON, UniqueConstraint, Float, Integer,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

from typing import TYPE_CHECKING
if TYPE_CHECKING:  # resolves the string annotations below without a runtime cycle
    from app.modules.staff.models import User
    from app.modules.organisation.models import Department


# ── State Machine Constants ───────────────────────────────────

TASK_STATES = {
    "new", "assigned", "in_progress", "review", "blocked", "done", "archived",
}

PIPELINE_FLOW = ["new", "assigned", "in_progress", "review", "done", "archived"]

ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    "new":         ["assigned", "in_progress"],
    "assigned":    ["in_progress", "blocked"],
    "in_progress": ["review", "blocked", "assigned"],
    "review":      ["in_progress", "done", "blocked"],
    "blocked":     ["in_progress", "assigned"],
    # Done is the waiting-for-approval state. Only the approval endpoint may
    # leave it (approve -> archived, reject -> in_progress).
    "done":        [],
    "archived":    [],
}

TRANSITION_ROLE_REQUIREMENTS: dict[str, int] = {
    "done":     2,
    "archived": 3,
}

TERMINAL_STATES    = {"done", "archived"}
COMMENT_TYPES      = {"NORMAL", "SYSTEM", "ACTION", "APPROVAL", "BLOCKER"}
APPROVAL_KEYWORDS  = {"approve", "approved", "lgtm", "looks good", "sign off", "accepted"}
REJECTION_KEYWORDS = {"reject", "rejected", "denied", "not approved", "revise", "rework"}
BLOCKER_KEYWORDS   = {"blocked", "blocking", "cannot proceed", "stuck", "waiting on", "halted"}

TRIGGER_TYPES = {"manual", "automation", "comment", "system", "dependency"}

# ── Pipeline Stage Constants (Phase 5) ───────────────────────

PIPELINE_STAGES = ["backlog", "in_progress", "review", "unit_done", "archive"]

PIPELINE_STAGE_TRANSITIONS: dict[str, list[str]] = {
    "backlog":     ["in_progress"],
    "in_progress": ["review", "backlog"],
    "review":      ["unit_done", "in_progress"],
    "unit_done":   ["archive", "review"],
    "archive":     [],
}

STATUS_TO_PIPELINE_STAGE: dict[str, str] = {
    "new":         "backlog",
    "assigned":    "backlog",
    "in_progress": "in_progress",
    "blocked":     "in_progress",
    "review":      "review",
    "done":        "unit_done",
    "archived":    "archive",
}

TASK_SCOPES = {"internal", "external"}

# Accepted values for the free-text `priority` and `status` columns.
# These mirror the TaskPriority / TaskStatus unions in shared-types so the
# API cannot store a value the frontend has no rendering for.
TASK_PRIORITIES = {"critical", "high", "medium", "low"}
TASK_STATUSES   = set(STATUS_TO_PIPELINE_STAGE)

ASSIGNMENT_TYPES = {"initial", "reassign", "dept_transfer", "escalation"}

REJECTION_TYPES = {"push_back", "dept_return", "escalation_reject", "completion_rejected"}

APPROVAL_RECORD_TYPES = {"assignee_done", "creator_approved"}

SOURCE_APPS = {"sales", "hr", "field", "inventory", "integration", "smartolt", "task_engine"}


# ── ORM Models ────────────────────────────────────────────────

class Task(Base):
    __tablename__      = "tasks"
    __allow_unmapped__ = True

    id:                   Mapped[uuid.UUID]                = mapped_column(primary_key=True, default=uuid.uuid4)
    title:                Mapped[str]                      = mapped_column(String(300), nullable=False)
    description:          Mapped[str | None]               = mapped_column(Text)
    priority:             Mapped[str]                      = mapped_column(String(20), default="medium")
    status:               Mapped[str]                      = mapped_column(String(20), default="new")
    previous_state:       Mapped[str | None]               = mapped_column(String(20))
    state_changed_at:     Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deadline:             Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    department_id:        Mapped[uuid.UUID | None]         = mapped_column(ForeignKey("departments.id"))
    project_id:           Mapped[uuid.UUID | None]         = mapped_column(ForeignKey("projects.id"))
    assignee_user_id:     Mapped[uuid.UUID | None]         = mapped_column(ForeignKey("users.id"))
    responsible_user_id:  Mapped[uuid.UUID | None]         = mapped_column(ForeignKey("users.id"))
    pipeline_id:          Mapped[uuid.UUID | None]         = mapped_column()
    stage_id:             Mapped[uuid.UUID | None]         = mapped_column()
    created_by:           Mapped[uuid.UUID]                = mapped_column(ForeignKey("users.id"))
    tenant_id:            Mapped[uuid.UUID]                = mapped_column(ForeignKey("tenants.id"), nullable=False)
    block_reason:         Mapped[str | None]               = mapped_column(Text)
    ticket_number:        Mapped[str | None]               = mapped_column(String(20))
    estimated_hours:      Mapped[float | None]             = mapped_column(Float)
    form_submission_id:   Mapped[uuid.UUID | None]         = mapped_column()
    created_at:           Mapped[datetime.datetime]        = mapped_column(default=datetime.datetime.utcnow)
    updated_at:           Mapped[datetime.datetime]        = mapped_column(
        default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Phase 5 new columns
    task_scope:               Mapped[str]                      = mapped_column(String(20), default="internal")
    pipeline_stage:           Mapped[str]                      = mapped_column(String(30), default="backlog")
    is_deleted:               Mapped[bool]                     = mapped_column(Boolean, default=False)
    deleted_at:               Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by:               Mapped[uuid.UUID | None]         = mapped_column(ForeignKey("users.id"))
    deletion_reason:          Mapped[str | None]               = mapped_column(Text)
    source_app:               Mapped[str | None]               = mapped_column(String(50))
    assignee_confirmed_done:  Mapped[bool]                     = mapped_column(Boolean, default=False)
    creator_approved_done:    Mapped[bool]                     = mapped_column(Boolean, default=False)
    assignee_done_at:         Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    creator_approved_at:      Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    is_reopened:              Mapped[bool]                     = mapped_column(Boolean, default=False)

    # Relationships
    department:         "Department | None"         = relationship("Department", lazy="selectin")
    comments:           Mapped[list["TaskComment"]] = relationship("TaskComment",
                                                                   foreign_keys="[TaskComment.task_id]",
                                                                   back_populates="task",
                                                                   cascade="all, delete-orphan",
                                                                   lazy="selectin")
    tags:               Mapped[list["TaskTag"]]     = relationship("TaskTag",
                                                                   back_populates="task",
                                                                   cascade="all, delete-orphan",
                                                                   lazy="selectin")
    assignee:           "User | None"               = relationship("User", foreign_keys=[assignee_user_id],  lazy="selectin")
    responsible_user:   "User | None"               = relationship("User", foreign_keys=[responsible_user_id], lazy="selectin")

    @property
    def deadline_bucket(self) -> str:
        if self.status == "done":
            return "pending_approval"
        # Only approved work is complete. Reopened tasks return to live buckets.
        if self.status == "archived":
            return "completed"
        if self.status in ("new", "assigned") and not self.deadline:
            return "backlog"
        if not self.deadline:
            return "no_deadline"
        now   = datetime.datetime.utcnow()
        delta = (self.deadline.replace(tzinfo=None) - now).days
        if delta < 0:   return "overdue"
        if delta == 0:  return "today"
        if delta <= 7:  return "this_week"
        if delta <= 14: return "next_week"
        return "no_deadline"


class TaskComment(Base):
    __tablename__      = "task_comments"
    __allow_unmapped__ = True

    id:              Mapped[uuid.UUID]              = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id:         Mapped[uuid.UUID]              = mapped_column(ForeignKey("tasks.id"), nullable=False)
    author_user_id:  Mapped[uuid.UUID | None]       = mapped_column(ForeignKey("users.id"))
    body:            Mapped[str]                    = mapped_column(Text, nullable=False)
    type:            Mapped[str]                    = mapped_column(String(20), default="NORMAL", nullable=False)
    mentions:        Mapped[list]                   = mapped_column(JSON, default=list, server_default="[]", nullable=False)
    parent_id:       Mapped[uuid.UUID | None]       = mapped_column(ForeignKey("task_comments.id", ondelete="SET NULL"))
    approval_action: Mapped[str | None]             = mapped_column(String(20))
    is_resolved:     Mapped[bool]                   = mapped_column(Boolean, default=False, nullable=False)
    created_at:      Mapped[datetime.datetime]      = mapped_column(default=datetime.datetime.utcnow)
    updated_at:      Mapped[datetime.datetime | None] = mapped_column(
        default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    task:   "Task" = relationship("Task", back_populates="comments", foreign_keys=[task_id])
    author: "User" = relationship("User", foreign_keys=[author_user_id], lazy="selectin")


class TaskTag(Base):
    __tablename__      = "task_tags"
    __allow_unmapped__ = True

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    tag:     Mapped[str]       = mapped_column(String(60), primary_key=True)

    task: "Task" = relationship("Task", back_populates="tags")


class TaskDependency(Base):
    __tablename__      = "task_dependencies"
    __allow_unmapped__ = True
    __table_args__     = (
        UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependency"),
    )

    id:                  Mapped[uuid.UUID]         = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id:             Mapped[uuid.UUID]         = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    depends_on_task_id:  Mapped[uuid.UUID]         = mapped_column(ForeignKey("tasks.id"), nullable=False)
    created_at:          Mapped[datetime.datetime] = mapped_column(default=datetime.datetime.utcnow)


class TaskAuditEntry(Base):
    """Immutable per-task audit trail — one row per state transition."""
    __tablename__      = "task_audit_entries"
    __allow_unmapped__ = True

    id:           Mapped[uuid.UUID]                = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id:      Mapped[uuid.UUID]                = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    actor_id:     Mapped[uuid.UUID | None]         = mapped_column(ForeignKey("users.id"))
    from_state:   Mapped[str | None]               = mapped_column(String(20))
    to_state:     Mapped[str | None]               = mapped_column(String(20))
    trigger_type: Mapped[str]                      = mapped_column(String(20), default="manual", nullable=False)
    comment_id:   Mapped[uuid.UUID | None]         = mapped_column()
    note:         Mapped[str | None]               = mapped_column(Text)
    created_at:   Mapped[datetime.datetime]        = mapped_column(
        default=datetime.datetime.utcnow, index=True)

    actor: "User | None" = relationship("User", foreign_keys=[actor_id], lazy="selectin")


# ── Phase 5 New ORM Models ────────────────────────────────────

class TaskAssignmentLog(Base):
    """Tracks every assignment/reassignment/transfer event for a task."""
    __tablename__      = "task_assignment_logs"
    __allow_unmapped__ = True

    id:              Mapped[uuid.UUID]               = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id:         Mapped[uuid.UUID]               = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    tenant_id:       Mapped[uuid.UUID]               = mapped_column(ForeignKey("tenants.id"), nullable=False)
    assigned_by:     Mapped[uuid.UUID]               = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_to:     Mapped[uuid.UUID]               = mapped_column(ForeignKey("users.id"), nullable=False)
    from_dept_id:    Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("departments.id"))
    to_dept_id:      Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("departments.id"))
    assignment_type: Mapped[str]                     = mapped_column(String(30), nullable=False)
    note:            Mapped[str | None]              = mapped_column(Text)
    created_at:      Mapped[datetime.datetime]       = mapped_column(default=datetime.datetime.utcnow)

    assigner:  "User | None" = relationship("User", foreign_keys=[assigned_by], lazy="selectin")
    assignee:  "User | None" = relationship("User", foreign_keys=[assigned_to], lazy="selectin")


class TaskRejectionLog(Base):
    """Immutable record of every push-back or department return."""
    __tablename__      = "task_rejection_logs"
    __allow_unmapped__ = True

    id:              Mapped[uuid.UUID]               = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id:         Mapped[uuid.UUID]               = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    tenant_id:       Mapped[uuid.UUID]               = mapped_column(ForeignKey("tenants.id"), nullable=False)
    rejected_by:     Mapped[uuid.UUID]               = mapped_column(ForeignKey("users.id"), nullable=False)
    rejection_type:  Mapped[str]                     = mapped_column(String(30), nullable=False)
    from_dept_id:    Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("departments.id"))
    to_dept_id:      Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("departments.id"))
    reason:          Mapped[str]                     = mapped_column(Text, nullable=False)
    previous_status: Mapped[str | None]              = mapped_column(String(30))
    created_at:      Mapped[datetime.datetime]       = mapped_column(default=datetime.datetime.utcnow)

    actor: "User | None" = relationship("User", foreign_keys=[rejected_by], lazy="selectin")


class TaskDeptRouting(Base):
    """Tracks which department currently owns a task and full routing history."""
    __tablename__      = "task_department_routing"
    __allow_unmapped__ = True

    id:                  Mapped[uuid.UUID]               = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id:             Mapped[uuid.UUID]               = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    tenant_id:           Mapped[uuid.UUID]               = mapped_column(ForeignKey("tenants.id"), nullable=False)
    department_id:       Mapped[uuid.UUID]               = mapped_column(ForeignKey("departments.id"), nullable=False)
    assigned_by:         Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("users.id"))
    assigned_to_user_id: Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("users.id"))
    routing_order:       Mapped[int]                     = mapped_column(Integer, nullable=False)
    entered_at:          Mapped[datetime.datetime]       = mapped_column(default=datetime.datetime.utcnow)
    exited_at:           Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    exit_reason:         Mapped[str | None]              = mapped_column(String(30))
    is_current:          Mapped[bool]                    = mapped_column(Boolean, default=True)

    department: "Department | None" = relationship("Department", foreign_keys=[department_id], lazy="selectin")


class TaskCompletionApproval(Base):
    """Dual-approval audit trail — one row per approval step."""
    __tablename__      = "task_completion_approvals"
    __allow_unmapped__ = True

    id:            Mapped[uuid.UUID]         = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id:       Mapped[uuid.UUID]         = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    tenant_id:     Mapped[uuid.UUID]         = mapped_column(ForeignKey("tenants.id"), nullable=False)
    approval_type: Mapped[str]               = mapped_column(String(20), nullable=False)
    actor_id:      Mapped[uuid.UUID]         = mapped_column(ForeignKey("users.id"), nullable=False)
    comment:       Mapped[str | None]        = mapped_column(Text)
    created_at:    Mapped[datetime.datetime] = mapped_column(default=datetime.datetime.utcnow)

    actor: "User | None" = relationship("User", foreign_keys=[actor_id], lazy="selectin")


class ArchiveReference(Base):
    """Stores references to archived tasks/projects embedded in new tasks or comments."""
    __tablename__      = "archive_references"
    __allow_unmapped__ = True

    id:                           Mapped[uuid.UUID]               = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id:                      Mapped[uuid.UUID]               = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    referenced_archive_task_id:   Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    referenced_archive_project_id:Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    referenced_by:                Mapped[uuid.UUID]               = mapped_column(ForeignKey("users.id"), nullable=False)
    tenant_id:                    Mapped[uuid.UUID]               = mapped_column(ForeignKey("tenants.id"), nullable=False)
    created_at:                   Mapped[datetime.datetime]       = mapped_column(default=datetime.datetime.utcnow)
