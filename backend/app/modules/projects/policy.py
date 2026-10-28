# ============================================================
# OPSYN PROJECTS POLICY — app/modules/projects/policy.py
# Pure RBAC enforcement logic — no HTTP, no DB
# Every function is independently testable
# ============================================================

from __future__ import annotations
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.staff.models import User


def can_manage_pipeline(user: "User", stage_department_id: uuid.UUID) -> bool:
    """
    Returns True if the user can advance or push back the given pipeline stage.
    True if: user's department scope includes stage_department_id
             OR user.role.level >= 4 (Manager can override any stage)
    """
    # Admin (5) or Manager (4) can manage any stage
    if user.role.level >= 4:
        return True

    # Check if user's department scope includes the stage's department
    user_dept_ids = {
        scope.scope_reference_id
        for scope in (user.scopes or [])
        if scope.scope_type == "department"
    }
    return stage_department_id in user_dept_ids


def can_approve_stage(user: "User", stage_department_id: uuid.UUID) -> bool:
    """
    Returns True if the user can formally approve a pipeline stage gate.
    True if: user's department scope includes stage_department_id
             OR user.role.level >= 3 (Team Lead+)
    """
    if user.role.level >= 3:
        return True
    user_dept_ids = {
        scope.scope_reference_id
        for scope in (user.scopes or [])
        if scope.scope_type == "department"
    }
    return stage_department_id in user_dept_ids


def can_comment_on_stage(user: "User", stage_department_id: uuid.UUID) -> bool:
    """
    Returns True if the user can add comments to the given stage.
    True if: user's department scope includes stage_department_id
             OR user.role.level >= 3 (Team Lead can comment on any stage for visibility)
    """
    # Manager (4) or Admin (5) or Team Lead (3) can comment on any stage
    if user.role.level >= 3:
        return True

    # Check if user's department scope includes the stage's department
    user_dept_ids = {
        scope.scope_reference_id
        for scope in (user.scopes or [])
        if scope.scope_type == "department"
    }
    return stage_department_id in user_dept_ids