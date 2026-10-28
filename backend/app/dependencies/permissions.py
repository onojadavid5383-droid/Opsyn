# ============================================================
# OPSYN PERMISSIONS DEPENDENCY — app/dependencies/permissions.py
# check_permission(feature_key) — department-driven RBAC
#
# Three-layer permission check:
#   1. Admin (level 5) → always passes all checks
#   2. department_feature_grants → dept match + min_role_level check
#   3. role_feature_overrides → explicit role override
#   4. Else → 403 Forbidden
#
# Usage: Depends(check_permission("staff.create"))
# ============================================================

from __future__ import annotations
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db
from app.core.context import tenant_id_ctx
from app.dependencies.auth import get_current_user, require_role
from app.modules.staff.models import User

__all__ = [
    "check_permission",
    "check_admin",
    "require_role",
    "get_current_user",
]


def check_permission(feature_key: str):
    """
    FastAPI dependency factory — checks a named feature permission.

    Decision tree:
    1. Admin (role.level == 5) → always True.
    2. Query department_feature_grants for caller's dept + feature_key.
       If found and caller.role.level >= min_role_level → True.
    3. Query role_feature_overrides for caller's role + feature_key.
       If is_granted == True → True.
    4. Otherwise → HTTP 403.

    Usage:
        @router.post("/staff", dependencies=[Depends(check_permission("staff.create"))])
    """
    async def _checker(
        db:     AsyncSession = Depends(get_db),
        caller: User         = Depends(get_current_user),
    ) -> User:
        role_level = caller.role.level if caller.role else 1

        # Gate 1: Admin passes everything
        if role_level >= 5:
            return caller

        tenant_id = tenant_id_ctx.get()
        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No tenant context. Cannot evaluate permissions.",
            )

        # Gate 2: Department feature grant check
        dept_id = None
        if caller.staff_profile:
            dept_id = caller.staff_profile.department_id

        if dept_id:
            grant_row = (await db.execute(
                text("""
                    SELECT min_role_level
                    FROM department_feature_grants
                    WHERE tenant_id     = :tenant_id
                      AND department_id = :dept_id
                      AND feature_key   = :feature_key
                    LIMIT 1
                """),
                {
                    "tenant_id":   str(tenant_id),
                    "dept_id":     str(dept_id),
                    "feature_key": feature_key,
                },
            )).fetchone()

            if grant_row and role_level >= grant_row[0]:
                return caller

        # Gate 3: Role-level override check
        override_row = (await db.execute(
            text("""
                SELECT is_granted
                FROM role_feature_overrides
                WHERE tenant_id   = :tenant_id
                  AND role_id     = :role_id
                  AND feature_key = :feature_key
                LIMIT 1
            """),
            {
                "tenant_id":   str(tenant_id),
                "role_id":     str(caller.role_id),
                "feature_key": feature_key,
            },
        )).fetchone()

        if override_row and override_row[0]:
            return caller

        # Gate 4: Deny
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Access denied: feature '{feature_key}' is not granted "
                f"for your role or department."
            ),
        )

    return _checker


def check_admin():
    """Shortcut: require Admin-level permission."""
    return check_permission("settings.admin")
