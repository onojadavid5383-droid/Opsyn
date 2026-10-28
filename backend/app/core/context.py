# ============================================================
# OPSYN CONTEXT — app/core/context.py
# Python contextvars for per-request tenant isolation.
# TenantMiddleware sets these before any endpoint runs.
# get_db() reads tenant_id_ctx to inject SET LOCAL app.tenant_id.
# ============================================================

from contextvars import ContextVar
from typing import Optional
import uuid

# Set by TenantMiddleware on every authenticated request.
# get_db() reads this to scope every DB session to the correct tenant.
tenant_id_ctx: ContextVar[Optional[uuid.UUID]] = ContextVar(
    "tenant_id_ctx", default=None
)
