# ============================================================
# OPSYN STAFF SCHEMAS — app/modules/staff/schemas.py
# Pydantic v2 request / response models
# ============================================================

from __future__ import annotations
import uuid
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator
import re


class RoleOut(BaseModel):
    id: uuid.UUID
    name: str
    level: int
    is_system_role: bool

    model_config = {"from_attributes": True}


class DeptOut(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class TeamOut(BaseModel):
    id: uuid.UUID
    name: str
    department_id: uuid.UUID

    model_config = {"from_attributes": True}


class RegionOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str

    model_config = {"from_attributes": True}


class StaffSummary(BaseModel):
    id: uuid.UUID
    staff_code: str
    first_name: str
    last_name: str

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    model_config = {"from_attributes": True}


class StaffProfileOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    staff_code: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    job_title: Optional[str] = None
    skill_category: Optional[str] = None
    specialization: Optional[str] = None
    employment_type: str
    status: str
    olt_domain: Optional[str] = None
    work_location: Optional[str] = None
    outage_responsibility: Optional[str] = None
    mec_responsibility: Optional[str] = None
    approval_authority_level: int
    notes: Optional[str] = None
    joined_at: Optional[str] = None
    end_date: Optional[str] = None
    created_at: str

    # Nested
    role: Optional[RoleOut] = None
    department: Optional[DeptOut] = None
    team: Optional[TeamOut] = None
    region: Optional[RegionOut] = None

    # From user
    username: str = ""
    email: str = ""
    last_login_at: Optional[str] = None
    is_active: bool = True

    model_config = {"from_attributes": True}


class CreateStaffRequest(BaseModel):
    # Tab 1: Basic Info
    first_name: str
    last_name: str
    email: EmailStr
    phone: Optional[str] = None
    username: str
    staff_code: Optional[str] = None
    invite_method: str = "email"
    temporary_password: Optional[str] = None

    # Tab 2: Organisation
    department_id: uuid.UUID
    team_id: Optional[uuid.UUID] = None
    manager_user_id: Optional[uuid.UUID] = None
    role_id: uuid.UUID
    job_title: Optional[str] = None
    employment_type: str = "permanent"

    # Tab 3: Access
    permission_profile: Optional[str] = None
    scope_level: str = "department"
    allowed_dashboards: list[str] = []

    # Tab 4: Operational
    region_id: Optional[uuid.UUID] = None
    olt_domain: Optional[str] = None
    project_unit: Optional[str] = None
    outage_responsibility: Optional[str] = None
    mec_responsibility: Optional[str] = None
    approval_authority_level: int = 0
    work_location: Optional[str] = None
    specialization: Optional[str] = None
    notes: Optional[str] = None

    # Tab 5: Status
    status: str = "active"
    joined_at: Optional[str] = None
    end_date: Optional[str] = None

    @field_validator("team_id", "region_id", "manager_user_id", mode="before")
    @classmethod
    def coerce_optional_uuid(cls, v):
        """Convert empty-string to None so optional UUID fields don't fail validation."""
        if v == "" or v is None:
            return None
        return v

    @field_validator("status")
    @classmethod
    def validate_create_status(cls, v: str) -> str:
        allowed = {"active", "inactive", "suspended", "on_leave"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v

    @field_validator("scope_level")
    @classmethod
    def validate_scope(cls, v: str) -> str:
        allowed = {"department", "team", "region", "system"}
        if not v or v.strip() == "":
            return "department"
        if v not in allowed:
            raise ValueError(f"scope_level must be one of {allowed}")
        return v

    @field_validator("approval_authority_level", mode="before")
    @classmethod
    def coerce_auth_level(cls, v) -> int:
        try:
            return int(v)
        except (ValueError, TypeError):
            return 0

    @field_validator("allowed_dashboards", mode="before")
    @classmethod
    def coerce_dashboards(cls, v) -> list:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [v] if v else []
        return list(v)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^(\+?[1-9]|0)\d{6,14}$", v.replace(" ", "").replace("-","")):
            raise ValueError("Invalid phone number format. Use E.164 format.")
        return v

    @field_validator("employment_type")
    @classmethod
    def validate_employment_type(cls, v: str) -> str:
        allowed = {"permanent", "contract", "intern"}
        if v not in allowed:
            raise ValueError(f"employment_type must be one of {allowed}")
        return v

class UpdateStaffRequest(BaseModel):
    """Partial update — all fields optional. email/username/staff_code are immutable."""
    role_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None
    employment_type: Optional[str] = None
    phone: Optional[str] = None
    job_title: Optional[str] = None
    skill_category: Optional[str] = None
    specialization: Optional[str] = None
    team_id: Optional[uuid.UUID] = None
    manager_user_id: Optional[uuid.UUID] = None
    region_id: Optional[uuid.UUID] = None
    olt_domain: Optional[str] = None
    work_location: Optional[str] = None
    outage_responsibility: Optional[str] = None
    mec_responsibility: Optional[str] = None
    approval_authority_level: Optional[int] = None
    notes: Optional[str] = None
    joined_at: Optional[str] = None
    end_date: Optional[str] = None

    @field_validator("employment_type")
    @classmethod
    def validate_employment_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in {"permanent", "contract", "intern"}:
            raise ValueError("employment_type must be one of permanent, contract, intern")
        return v


class UpdateStatusRequest(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"active", "inactive", "suspended", "on_leave"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v


class StaffResponse(BaseModel):
    success: bool
    data: dict  # Serialized StaffProfile

    model_config = {"from_attributes": True}


class StaffListResponse(BaseModel):
    success: bool
    data: dict  # Paginated list

    model_config = {"from_attributes": True}
