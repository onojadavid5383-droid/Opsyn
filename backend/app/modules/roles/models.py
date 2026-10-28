# ============================================================
# OPSYN ROLES MODELS — app/modules/roles/models.py
# Re-exports Role and related models from all_modules
# ============================================================

from app.modules.all_modules import Role, UserScope, UserRoleHistory

__all__ = ["Role", "UserScope", "UserRoleHistory"]
