# ============================================================
# OPSYN CORE INFRASTRUCTURE — app/core/infrastructure.py
# Middleware · Exception handlers · Logging · Constants
# Fixed: fastapi_limiter.depends.RateLimiter (v0.2.x API)
# ============================================================

import time, uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from fastapi import FastAPI as FA
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.security import verify_access_token


# ══ AuthMiddleware ════════════════════════════════════════════
class AuthMiddleware(BaseHTTPMiddleware):
    SKIP = {"/health", "/api/docs", "/api/redoc", "/openapi.json",
            "/api/v1/auth/login", "/api/v1/auth/refresh"}

    async def dispatch(self, request: Request, call_next):
        request.state.user    = None
        request.state.user_id = None
        if request.url.path not in self.SKIP:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                payload = verify_access_token(auth[7:])
                if payload:
                    request.state.user_id    = payload.get("sub")
                    request.state.role_level = payload.get("role_level", 0)
        return await call_next(request)


# ══ RequestIDMiddleware ═══════════════════════════════════════
class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = rid
        resp = await call_next(request)
        resp.headers["X-Request-ID"] = rid
        return resp


# ══ TimingMiddleware ══════════════════════════════════════════
class TimingMiddleware(BaseHTTPMiddleware):
    SLOW_MS = 500

    async def dispatch(self, request: Request, call_next):
        t0   = time.perf_counter()
        resp = await call_next(request)
        ms   = (time.perf_counter() - t0) * 1000
        resp.headers["X-Response-Time-Ms"] = str(round(ms, 2))
        if ms > self.SLOW_MS:
            try:
                import structlog
                structlog.get_logger().warning("slow_request",
                    path=request.url.path, method=request.method, duration_ms=round(ms, 2))
            except Exception:
                # Intentionally silent: this block *is* the logger. Logging a
                # logging failure would recurse, and telemetry must never break
                # request handling.
                pass
        return resp


# ══ AuditMiddleware ═══════════════════════════════════════════
class AuditMiddleware(BaseHTTPMiddleware):
    METHODS = {"POST", "PUT", "PATCH", "DELETE"}
    SKIP    = {"/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/auth/refresh"}

    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        if (request.method in self.METHODS
                and request.url.path not in self.SKIP
                and getattr(request.state, "user_id", None)
                and resp.status_code < 400):
            try:
                import structlog
                structlog.get_logger().info("api_mutation",
                    actor=request.state.user_id,
                    method=request.method, path=request.url.path,
                    status=resp.status_code)
            except Exception:
                # Intentionally silent: this block *is* the logger. Logging a
                # logging failure would recurse, and telemetry must never break
                # request handling.
                pass
        return resp


# ══ SecurityHeadersMiddleware ═════════════════════════════════
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add OWASP-recommended security response headers to every reply."""

    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Frame-Options"]        = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"]        = "same-origin"
        resp.headers["X-XSS-Protection"]       = "1; mode=block"
        resp.headers["Permissions-Policy"]     = "geolocation=(), camera=(), microphone=()"
        # Only send HSTS over HTTPS — detect via proxy header
        if request.headers.get("x-forwarded-proto") == "https":
            resp.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        return resp


# ══ Rate limiter setup ════════════════════════════════════════
async def setup_rate_limiter():
    """
    Initialize rate limiter with Redis backend.
    fastapi-limiter v0.2.x uses RateLimiter from fastapi_limiter.depends.
    No global init required — RateLimiter is used directly as Depends().
    """
    pass   # v0.2.x is dependency-based, no global init needed


# ══ Exception handlers ════════════════════════════════════════
def register_exception_handlers(app: FA):
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, exc):
        errors = [
            {"field": ".".join(str(l) for l in e["loc"]),
             "message": e["msg"], "code": e["type"]}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"success": False, "detail": errors})

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request, exc):
        # Without this, FastAPI answers HTTPException with a bare
        # {"detail": ...}, while validation and unhandled errors answer
        # {"success": false, "detail": ...}. Clients had to cope with both.
        # `detail` keeps its position and shape, so existing consumers
        # reading response.data.detail are unaffected.
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def generic_handler(request, exc):
        try:
            import structlog
            structlog.get_logger().error("unhandled_exception",
                error=str(exc), path=str(request.url))
        except Exception:
            # Intentionally silent: this block *is* the logger. See note above.
            pass
        return JSONResponse(status_code=500, content={"success": False, "detail": "Internal server error."})


# ══ Logging config ════════════════════════════════════════════
def configure_logging():
    try:
        import structlog, logging
        structlog.configure(
            processors=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.BoundLogger,
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
        )
        logging.basicConfig(level=logging.INFO)
    except ImportError:
        import logging
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(name)s %(message)s")


# ══ Constants ═════════════════════════════════════════════════
DEFAULT_STAFF_CODE_PREFIX = "OPS"

ROLE_LEVELS = {
    "Staff": 1, "NOC Operator": 2, "MEC Reviewer": 2,
    "Executive Viewer": 2, "Team Lead": 3, "Manager": 4, "Admin": 5,
}

SEED_ROLES = [
    {"name": "Staff",            "level": 1, "is_system_role": True},
    {"name": "NOC Operator",     "level": 2, "is_system_role": True},
    {"name": "MEC Reviewer",     "level": 2, "is_system_role": True},
    {"name": "Executive Viewer", "level": 2, "is_system_role": True},
    {"name": "Team Lead",        "level": 3, "is_system_role": True},
    {"name": "Manager",          "level": 4, "is_system_role": True},
    {"name": "Admin",            "level": 5, "is_system_role": True},
]

SEED_REGIONS = [
    {"name": "Lagos",         "code": "LOS"},
    {"name": "Abuja",         "code": "ABJ"},
    {"name": "Port Harcourt", "code": "PHC"},
    {"name": "Kano",          "code": "KAN"},
    {"name": "Enugu",         "code": "ENU"},
    {"name": "Ibadan",        "code": "IBA"},
]

TASK_DEADLINE_BUCKETS = ["pending_approval", "overdue", "today", "this_week", "next_week", "no_deadline", "backlog", "completed"]
