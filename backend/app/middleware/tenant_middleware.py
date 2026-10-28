# ============================================================
# OPSYN TENANT MIDDLEWARE — app/middleware/tenant_middleware.py
# Extracts tenant_id from the authenticated JWT payload and
# sets the tenant_id_ctx contextvar so get_db() can inject
# SET LOCAL app.tenant_id on every DB session.
#
# Order in middleware stack: AFTER AuthMiddleware
# (AuthMiddleware decodes JWT → request.state.user)
# (TenantMiddleware reads user.tenant_id → sets contextvar)
# ============================================================

from __future__ import annotations
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import tenant_id_ctx
from app.core.security import verify_access_token

# Routes that bypass tenant isolation (public / health)
PUBLIC_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/api/v1/tenants/register",
    "/health",
    "/api/docs",
    "/api/redoc",
    "/openapi.json",
}


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Runs after AuthMiddleware.
    1. Skips public routes.
    2. Reads tenant_id from JWT claims (set at login time).
    3. Sets tenant_id_ctx so get_db() injects RLS context.
    4. Returns 400 if tenant_id is missing on authenticated routes.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip public routes
        if request.url.path in PUBLIC_PATHS or request.url.path.startswith("/api/docs"):
            return await call_next(request)

        tenant_id: uuid.UUID | None = None

        # Try to read tenant_id from JWT via request.state.user (set by AuthMiddleware)
        user = getattr(request.state, "user", None)
        if user and hasattr(user, "tenant_id"):
            tenant_id = user.tenant_id

        # Fallback: decode JWT directly to read tenant_id claim
        if tenant_id is None:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                payload = verify_access_token(token)
                if payload and "tenant_id" in payload:
                    try:
                        tenant_id = uuid.UUID(payload["tenant_id"])
                    except (ValueError, TypeError):
                        pass

        # Set the contextvar — get_db() will read this
        token_ctx = tenant_id_ctx.set(tenant_id)
        try:
            response = await call_next(request)
        finally:
            tenant_id_ctx.reset(token_ctx)

        return response
