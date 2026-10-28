# ============================================================
# OPSYN STAFF MODELS — app/modules/staff/models.py
# SQLAlchemy 2.0 ORM: User + StaffProfile
# Fixed: __allow_unmapped__ = True for relationship annotations
# ============================================================

from __future__ import annotations
import uuid
import datetime
from sqlalchemy import String, Boolean, ForeignKey, Date, Integer, Text, DateTime, Numeric, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

from typing import TYPE_CHECKING
if TYPE_CHECKING:  # resolves the string annotations below without a runtime cycle
    from app.modules.roles.models import Role
    from app.modules.organisation.models import Department, Team, Region


class User(Base):
    __tablename__       = "users"
    __allow_unmapped__  = True   # Allow forward-ref relationship annotations

    id:            Mapped[uuid.UUID]          = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:     Mapped[uuid.UUID]          = mapped_column(ForeignKey("tenants.id"), nullable=False)
    username:      Mapped[str]                = mapped_column(String(80),  nullable=False)
    email:         Mapped[str]                = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str]                = mapped_column(Text, nullable=False)
    role_id:       Mapped[uuid.UUID]          = mapped_column(ForeignKey("roles.id"), nullable=False)
    is_active:     Mapped[bool]               = mapped_column(Boolean, default=True)
    is_deleted:    Mapped[bool]               = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at:    Mapped[datetime.datetime]  = mapped_column(default=datetime.datetime.utcnow)
    updated_at:    Mapped[datetime.datetime]  = mapped_column(
        default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    # Relationships — use string refs to avoid circular imports
    role:          "Role"          = relationship("Role", back_populates="users",        lazy="joined")
    staff_profile: "StaffProfile"  = relationship("StaffProfile", back_populates="user",
                                                   uselist=False, foreign_keys="[StaffProfile.user_id]",
                                                   lazy="joined")
    scopes:        list            = relationship("UserScope", back_populates="user",
                                                   foreign_keys="[UserScope.user_id]")


class StaffProfile(Base):
    __tablename__      = "staff_profiles"
    __allow_unmapped__ = True

    id:                       Mapped[uuid.UUID]          = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id:                  Mapped[uuid.UUID]          = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    tenant_id:                Mapped[uuid.UUID]          = mapped_column(ForeignKey("tenants.id"), nullable=False)
    staff_code:               Mapped[str]                = mapped_column(String(40), unique=True, nullable=False)
    first_name:               Mapped[str]                = mapped_column(String(100), nullable=False)
    last_name:                Mapped[str]                = mapped_column(String(100), nullable=False)
    phone:                    Mapped[str | None]          = mapped_column(String(30))
    job_title:                Mapped[str | None]          = mapped_column(String(150))
    skill_category:           Mapped[str | None]          = mapped_column(String(100))
    specialization:           Mapped[str | None]          = mapped_column(String(150))
    employment_type:          Mapped[str]                 = mapped_column(String(20), default="permanent")
    region_id:                Mapped[uuid.UUID | None]    = mapped_column(ForeignKey("regions.id"))
    department_id:            Mapped[uuid.UUID]           = mapped_column(ForeignKey("departments.id"), nullable=False)
    team_id:                  Mapped[uuid.UUID | None]    = mapped_column(ForeignKey("teams.id"))
    manager_user_id:          Mapped[uuid.UUID | None]    = mapped_column(ForeignKey("users.id"))
    approval_authority_level: Mapped[int]                 = mapped_column(Integer, default=0)
    olt_domain:               Mapped[str | None]          = mapped_column(String(200))
    work_location:            Mapped[str | None]          = mapped_column(String(200))
    outage_responsibility:    Mapped[str | None]          = mapped_column(Text)
    mec_responsibility:       Mapped[str | None]          = mapped_column(Text)
    status:                   Mapped[str]                 = mapped_column(String(20), default="active")
    notes:                    Mapped[str | None]          = mapped_column(Text)
    joined_at:                Mapped[datetime.date | None]     = mapped_column(Date)
    end_date:                 Mapped[datetime.date | None]     = mapped_column(Date)
    efficiency_score:         Mapped[float | None]        = mapped_column(Numeric(5, 2), nullable=True)
    efficiency_computed_at:   Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_by:               Mapped[uuid.UUID | None]    = mapped_column(ForeignKey("users.id"))
    created_at:               Mapped[datetime.datetime]   = mapped_column(default=datetime.datetime.utcnow)
    updated_at:               Mapped[datetime.datetime]   = mapped_column(
        default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    # Relationships
    user:       "User"         = relationship("User", back_populates="staff_profile", foreign_keys=[user_id])
    department: "Department"   = relationship("Department", foreign_keys=[department_id], lazy="joined")
    team:       "Team | None"  = relationship("Team", foreign_keys=[team_id], lazy="joined")
    region:     "Region | None"= relationship("Region", foreign_keys=[region_id], lazy="joined")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
