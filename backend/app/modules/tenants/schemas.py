# ============================================================
# OPSYN TENANT SCHEMAS — app/modules/tenants/schemas.py
# Pydantic v2 schemas for tenant registration and responses.
# ============================================================

import uuid
import re
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator


def _slugify(name: str) -> str:
    """Convert org name to a URL-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:80]


class TenantRegisterRequest(BaseModel):
    org_name:       str
    admin_email:    EmailStr
    admin_password: str
    plan:           str = "starter"

    @field_validator("admin_password")
    def _strong_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v

    @field_validator("org_name")
    def _non_empty_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Organisation name is required.")
        return v.strip()


class TenantResponse(BaseModel):
    id:         uuid.UUID
    name:       str
    slug:       str
    plan:       str
    max_users:  int
    is_active:  bool

    model_config = {"from_attributes": True}


class TenantSettingsUpdate(BaseModel):
    name:     Optional[str] = None
    plan:     Optional[str] = None
    settings: Optional[dict] = None
