# ============================================================
# OPSYN TENANTS ROUTER — app/modules/tenants/router.py
# Tenant registration and management endpoints.
# POST /tenants/register — public endpoint (no auth required)
# GET  /tenants/me       — returns calling tenant's data
# PATCH /tenants/me      — update tenant settings (Admin only)
# ============================================================

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.tenants.schemas import TenantRegisterRequest, TenantSettingsUpdate
from app.modules.tenants.service import tenant_service
from app.modules.tenants.setup_service import apply_fttx_template
from app.dependencies.auth import get_current_user
from app.modules.staff.models import User

router = APIRouter()


@router.post("/register", status_code=201)
async def register_tenant(
    payload: TenantRegisterRequest,
    db:      AsyncSession = Depends(get_db),
):
    """
    Public endpoint — no auth required.
    Creates a new tenant, provisions admin user, applies FTTx template.
    """
    tenant, admin_user_id = await tenant_service.register(db, payload)

    # Apply FTTx baseline template: roles, departments, regions, permissions
    from uuid import UUID
    template_result = await apply_fttx_template(db, tenant.id, UUID(admin_user_id))

    await db.commit()

    return {
        "success": True,
        "data": {
            "tenant": {
                "id":   str(tenant.id),
                "name": tenant.name,
                "slug": tenant.slug,
                "plan": tenant.plan,
            },
            "admin_user_id": admin_user_id,
            "template":      template_result,
            "message": (
                f"Tenant '{tenant.name}' registered. "
                f"Admin account created at '{payload.admin_email}'. "
                "Log in to complete setup."
            ),
        },
    }


@router.get("/me")
async def get_my_tenant(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(get_current_user),
):
    """Returns the calling user's tenant details."""
    from app.core.context import tenant_id_ctx
    tenant_id = tenant_id_ctx.get()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant context found.")

    tenant = await tenant_service.get_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    return {
        "success": True,
        "data": {
            "id":        str(tenant.id),
            "name":      tenant.name,
            "slug":      tenant.slug,
            "plan":      tenant.plan,
            "max_users": tenant.max_users,
            "is_active": tenant.is_active,
            "settings":  tenant.settings,
        },
    }


@router.patch("/me")
async def update_tenant_settings(
    payload: TenantSettingsUpdate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(get_current_user),
):
    """Update tenant settings. Admin only."""
    if caller.role.level < 5:
        raise HTTPException(status_code=403, detail="Admin access required.")

    from app.core.context import tenant_id_ctx
    tenant_id = tenant_id_ctx.get()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant context found.")

    tenant = await tenant_service.update_settings(db, tenant_id, payload)
    return {
        "success": True,
        "data": {
            "id":   str(tenant.id),
            "name": tenant.name,
            "slug": tenant.slug,
            "plan": tenant.plan,
        },
    }
