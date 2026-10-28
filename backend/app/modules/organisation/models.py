# ============================================================
# OPSYN ORGANISATION MODELS — app/modules/organisation/models.py
# Department, Team, Region, DeptWorkflow, DeptWorkflowEdge
# ============================================================
from __future__ import annotations
import uuid
import datetime
from typing import List
from sqlalchemy import String, Text, Boolean, Integer, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

__all__ = [
    "Department",
    "Team",
    "Region",
    "DeptWorkflow",
    "DeptWorkflowEdge",
]


class Department(Base):
    __tablename__      = "departments"
    __allow_unmapped__ = True

    id:           Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:    Mapped[uuid.UUID]        = mapped_column(ForeignKey("tenants.id"), nullable=False)
    name:         Mapped[str]              = mapped_column(String(150), nullable=False)
    head_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    parent_id:    Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))


class Team(Base):
    __tablename__      = "teams"
    __allow_unmapped__ = True

    id:            Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:     Mapped[uuid.UUID]        = mapped_column(ForeignKey("tenants.id"), nullable=False)
    name:          Mapped[str]              = mapped_column(String(150), nullable=False)
    department_id: Mapped[uuid.UUID]        = mapped_column(ForeignKey("departments.id"), nullable=False)
    lead_user_id:  Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Region(Base):
    __tablename__      = "regions"
    __allow_unmapped__ = True

    id:        Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID]        = mapped_column(ForeignKey("tenants.id"), nullable=False)
    name:      Mapped[str]              = mapped_column(String(100), nullable=False)
    code:      Mapped[str]              = mapped_column(String(20),  nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("regions.id"))


class DeptWorkflow(Base):
    __tablename__      = "dept_workflows"
    __allow_unmapped__ = True

    id:              Mapped[uuid.UUID]               = mapped_column(
        primary_key=True, server_default="gen_random_uuid()", default=uuid.uuid4
    )
    tenant_id:       Mapped[uuid.UUID]               = mapped_column(ForeignKey("tenants.id"), nullable=False)
    name:            Mapped[str]                     = mapped_column(String(200), nullable=False)
    description:     Mapped[str | None]              = mapped_column(Text, nullable=True)
    trigger_dept_id: Mapped[uuid.UUID | None]        = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    is_active:       Mapped[bool]                    = mapped_column(Boolean, nullable=False, default=True)
    is_draft:        Mapped[bool]                    = mapped_column(Boolean, nullable=False, default=True)
    version:         Mapped[int]                     = mapped_column(Integer, nullable=False, default=1)
    created_by:      Mapped[uuid.UUID | None]        = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_at:    Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:      Mapped[datetime.datetime]        = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.utcnow
    )
    updated_at:      Mapped[datetime.datetime]        = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    # Relationships
    edges:        List["DeptWorkflowEdge"] = relationship(
        "DeptWorkflowEdge", back_populates="workflow", cascade="all, delete-orphan"
    )
    trigger_dept: "Department" = relationship(
        "Department", foreign_keys=[trigger_dept_id]
    )


class DeptWorkflowEdge(Base):
    __tablename__      = "dept_workflow_edges"
    __allow_unmapped__ = True

    id:                  Mapped[uuid.UUID]        = mapped_column(
        primary_key=True, server_default="gen_random_uuid()", default=uuid.uuid4
    )
    workflow_id:         Mapped[uuid.UUID]        = mapped_column(
        ForeignKey("dept_workflows.id", ondelete="CASCADE"), nullable=False
    )
    from_dept_id:        Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    to_dept_id:          Mapped[uuid.UUID]        = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), nullable=False
    )
    edge_order:          Mapped[int]              = mapped_column(Integer, nullable=False)
    label:               Mapped[str | None]       = mapped_column(String(200), nullable=True)
    is_parallel:         Mapped[bool]             = mapped_column(Boolean, nullable=False, default=False)
    parallel_group_id:   Mapped[str | None]       = mapped_column(String(50), nullable=True)
    gate_requires_group: Mapped[str | None]       = mapped_column(String(50), nullable=True)
    can_push_back:       Mapped[bool]             = mapped_column(Boolean, nullable=False, default=True)
    expected_days:       Mapped[int | None]       = mapped_column(Integer, nullable=True)
    created_at:          Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.utcnow
    )

    # Relationships
    workflow:   "DeptWorkflow" = relationship("DeptWorkflow", back_populates="edges")
    from_dept:  "Department"   = relationship("Department", foreign_keys=[from_dept_id])
    to_dept:    "Department"   = relationship("Department", foreign_keys=[to_dept_id])
