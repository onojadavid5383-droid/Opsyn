# ============================================================
# OPSYN CONSTANTS — app/core/constants.py
# Re-exports from infrastructure to keep import paths consistent
# ============================================================
from app.core.infrastructure import (
    DEFAULT_STAFF_CODE_PREFIX,
    SEED_ROLES,
    SEED_REGIONS,
    ROLE_LEVELS,
    TASK_DEADLINE_BUCKETS,
)
__all__ = [
    "DEFAULT_STAFF_CODE_PREFIX", "SEED_ROLES", "SEED_REGIONS",
    "ROLE_LEVELS", "TASK_DEADLINE_BUCKETS",
]
