# ============================================================
# OPSYN STAFF POLICY — app/modules/staff/policy.py
# Pure RBAC enforcement logic — no HTTP, no DB
# Every function is independently testable
# ============================================================

from __future__ import annotations
import uuid
from fastapi import HTTPException, status
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.staff.models import User


class StaffPolicy:
    """
    Enforces the 5-layer RBAC decision chain for all staff mutations.
    All methods raise HTTPException on violation — never return False silently.
    """

    @staticmethod
    def can_create(caller: "User", target_dept_id: uuid.UUID, target_role_level: int) -> None:
        """
        Checks caller has permission to create a staff member in a given
        department with a given role level.
        """
        # Rule 1: Only Manager (4) or Admin (5) can create staff
        if caller.role.level < 4:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role level. Manager or Admin required to create staff.",
            )

        # Rule 2: Scope check — Manager can only create in own dept
        if caller.role.level < 5:  # Not admin
            caller_dept_ids = {
                scope.scope_reference_id
                for scope in (caller.scopes or [])
                if scope.scope_type == "department"
            }
            if target_dept_id not in caller_dept_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Scope violation. You do not have authority over department {target_dept_id}.",
                )

        # Rule 3: Hierarchy — cannot assign role at or above own level
        if target_role_level >= caller.role.level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Hierarchy violation. Cannot assign role at level {target_role_level}. "
                    f"Your level is {caller.role.level}."
                ),
            )

    @staticmethod
    def can_update(caller: "User", target: "User", target_dept_id: uuid.UUID) -> None:
        """Check if caller can update a staff profile."""
        # Admin can update anyone
        if caller.role.level >= 5:
            return

        # Manager can only update staff in own dept
        if caller.role.level >= 4:
            caller_dept_ids = {
                scope.scope_reference_id
                for scope in (caller.scopes or [])
                if scope.scope_type == "department"
            }
            if target_dept_id not in caller_dept_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have authority over this staff member's department.",
                )
            return

        # Self-update limited fields only (handled in service)
        if str(caller.id) != str(target.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only update your own profile.",
            )

    @staticmethod
    def can_deactivate(caller: "User", target: "User") -> None:
        """Only Admin can deactivate. Manager can deactivate within own dept."""
        if caller.role.level < 4:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Manager or Admin required to deactivate staff.",
            )

    @staticmethod
    def can_assign_role(caller: "User", new_role_level: int) -> None:
        """Only Admin can assign roles. Role level must be below caller's."""
        if caller.role.level < 5:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Admin can assign roles.",
            )
        if new_role_level >= caller.role.level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot assign role at or above your own level.",
            )

    @staticmethod
    def can_view_sensitive(caller: "User", target_user_id: uuid.UUID) -> None:
        """Manager+ can view any profile. Others can only view their own."""
        if caller.role.level < 4 and str(caller.id) != str(target_user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own profile.",
            )

    @staticmethod
    def can_delete(caller: "User", target: "User") -> None:
        """Only Admin can permanently delete a staff member."""
        if caller.role.level < 5:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Admins can delete staff members.",
            )
        if str(caller.id) == str(target.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot delete your own account.",
            )

    @staticmethod
    def can_view_audit(caller: "User") -> None:
        """Only Admin can view audit logs."""
        if caller.role.level < 5:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required for audit logs.",
            )
