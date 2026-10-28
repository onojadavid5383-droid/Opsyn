# ============================================================
# OPSYN TENANT SERVICE — app/modules/tenants/service.py
# CRUD and lifecycle management for tenant accounts.
# ============================================================

from __future__ import annotations
import uuid
import re
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.modules.tenants.models import Tenant
from app.modules.tenants.schemas import TenantRegisterRequest, TenantSettingsUpdate


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")[:80]


class TenantService:

    async def get_by_id(self, db: AsyncSession, tenant_id: uuid.UUID) -> Optional[Tenant]:
        return (await db.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )).scalar_one_or_none()

    async def get_by_slug(self, db: AsyncSession, slug: str) -> Optional[Tenant]:
        return (await db.execute(
            select(Tenant).where(Tenant.slug == slug)
        )).scalar_one_or_none()

    async def register(
        self,
        db:      AsyncSession,
        payload: TenantRegisterRequest,
    ) -> tuple[Tenant, str]:
        """
        Register a new tenant and provision the admin user.
        Returns (tenant, admin_user_id_str).
        The full FTTx template is applied by the router after this.
        """
        from app.core.security import hash_password

        slug = _slugify(payload.org_name)

        # Ensure slug uniqueness (append random suffix if taken)
        existing = await self.get_by_slug(db, slug)
        if existing:
            slug = f"{slug}-{str(uuid.uuid4())[:8]}"

        tenant = Tenant(
            name=payload.org_name,
            slug=slug,
            plan=payload.plan,
            max_users=50,
            is_active=True,
            settings={},
        )
        db.add(tenant)
        await db.flush()  # Get tenant.id

        # Create Admin user for this tenant
        from sqlalchemy import text

        # Find the Admin role for this tenant (created by setup_service)
        # We create it inline here before setup_service runs
        admin_role_id = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO roles (id, tenant_id, name, level, is_system_role)
            VALUES (:id, :tenant_id, 'Admin', 5, true)
            ON CONFLICT DO NOTHING
        """), {"id": admin_role_id, "tenant_id": tenant.id})

        # Temporarily set tenant_id without RLS (migration context)
        await db.flush()

        # Use raw SQL to insert with tenant_id (bypasses ORM tenant_id restriction during setup)
        admin_user_id = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO users (id, tenant_id, username, email, password_hash, role_id, is_active)
            VALUES (:id, :tenant_id, :username, :email, :password_hash, :role_id, true)
            ON CONFLICT DO NOTHING
        """), {
            "id": admin_user_id,
            "tenant_id": tenant.id,
            "username": f"admin_{slug}",
            "email": payload.admin_email,
            "password_hash": hash_password(payload.admin_password),
            "role_id": admin_role_id,
        })

        return tenant, str(admin_user_id)

    async def update_settings(
        self,
        db:        AsyncSession,
        tenant_id: uuid.UUID,
        payload:   TenantSettingsUpdate,
    ) -> Tenant:
        tenant = await self.get_by_id(db, tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")
        if payload.name is not None:
            tenant.name = payload.name
        if payload.plan is not None:
            tenant.plan = payload.plan
        if payload.settings is not None:
            tenant.settings = {**(tenant.settings or {}), **payload.settings}
        await db.flush()
        return tenant


tenant_service = TenantService()
