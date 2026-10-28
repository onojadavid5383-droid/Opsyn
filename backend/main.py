# ============================================================
# OPSYN — FastAPI Application Factory
# main.py — entry point for all environments
# Powered by SlimTech
# ============================================================

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base
from app.core.logging import configure_logging
from app.core.redis_client import redis_pool

from app.middleware.auth_middleware import AuthMiddleware
from app.middleware.audit_middleware import AuditMiddleware
from app.middleware.rate_limit_middleware import setup_rate_limiter
from app.middleware.request_id_middleware import RequestIDMiddleware
from app.middleware.timing_middleware import TimingMiddleware
from app.middleware.tenant_middleware import TenantMiddleware
from app.core.infrastructure import SecurityHeadersMiddleware

from app.modules.auth.router import router as auth_router
from app.modules.tenants.router import router as tenants_router
from app.modules.staff.router import router as staff_router
from app.modules.organisation.router import router as org_router
from app.modules.organisation.workflow_router import router as workflow_router
from app.modules.roles.router import router as roles_router
from app.modules.permissions.router import router as perms_router
from app.modules.tasks.router import router as tasks_router
from app.modules.projects.router import router as projects_router
from app.modules.outage.router import router as outage_router
from app.modules.onboarding.router import router as onboarding_router
from app.modules.audit.router import router as audit_router
from app.modules.notifications.router import router as notifications_router
from app.modules.reports.router import router as reports_router
from app.modules.settings.router import router as settings_router
from app.modules.activity.router import router as activity_router
from app.modules.infrastructure.router import router as infrastructure_router
from app.modules.fttx_designer.router import router as fttx_designer_router
from app.modules.network.router import router as network_router
from app.modules.gis.router import router as gis_router
from app.modules.design.router import router as design_router
from app.modules.approval.router import router as approval_router
from app.modules.deployment.router import router as deployment_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.forms.router import router as forms_router
from app.modules.customers.forms_router import router as customer_forms_router
from app.modules.customers.router import router as customers_router
from app.modules.customers.external_router import router as external_router
from app.modules.webhooks.router import router as webhooks_router
from app.modules.shifts.router import router as shifts_router
from app.modules.form_builder.router import router as form_builder_router
from app.modules.form_builder.submission_router import router as form_builder_submission_router
from app.modules.form_builder.migration_router import router as form_builder_migration_router
from app.core.exceptions import register_exception_handlers


def _init_sentry() -> None:
    """Initialize Sentry if DSN is configured. No-op otherwise."""
    if not settings.SENTRY_DSN:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
            traces_sample_rate=0.05,
            environment=settings.ENVIRONMENT,
            send_default_pii=False,
            release="opsyn@2.0.0",
        )
    except ImportError:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    _init_sentry()
    configure_logging()
    await redis_pool.connect()
    await setup_rate_limiter()
    from app.events.bus import register_handlers
    register_handlers()
    yield
    await redis_pool.disconnect()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Opsyn API",
        description="Operational Intelligence Platform — Powered by SlimTech",
        version="2.0.0",
        docs_url="/api/docs" if settings.ENVIRONMENT == "development" else None,
        redoc_url="/api/redoc" if settings.ENVIRONMENT == "development" else None,
        lifespan=lifespan,
    )

    # ── CORS ────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Custom middleware (order matters — outermost first) ──
    # Stack (innermost to outermost due to LIFO order in Starlette):
    # AuditMiddleware → TenantMiddleware → AuthMiddleware → Timing → RequestID → Security
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(TimingMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(TenantMiddleware)   # After Auth — reads JWT tenant_id
    app.add_middleware(AuditMiddleware)

    # ── Exception handlers ───────────────────────────────────
    register_exception_handlers(app)

    # ── Routers (all prefixed /api/v1) ───────────────────────
    PREFIX = "/api/v1"
    app.include_router(auth_router,          prefix=f"{PREFIX}/auth",          tags=["Auth"])
    app.include_router(tenants_router,       prefix=f"{PREFIX}/tenants",       tags=["Tenants"])
    app.include_router(staff_router,         prefix=f"{PREFIX}/staff",         tags=["Staff"])
    app.include_router(org_router,           prefix=f"{PREFIX}",               tags=["Organisation"])
    app.include_router(workflow_router,      prefix=f"{PREFIX}/workflows",     tags=["Workflows"])
    app.include_router(roles_router,         prefix=f"{PREFIX}",               tags=["Roles"])
    app.include_router(perms_router,         prefix=f"{PREFIX}",               tags=["Permissions"])
    app.include_router(infrastructure_router, prefix=f"{PREFIX}",              tags=["Infrastructure"])
    app.include_router(fttx_designer_router,  prefix=f"{PREFIX}",              tags=["FTTx Designer"])
    app.include_router(network_router,        prefix=f"{PREFIX}",              tags=["Network"])
    app.include_router(gis_router,            prefix=f"{PREFIX}",              tags=["GIS"])
    app.include_router(design_router,         prefix=f"{PREFIX}",              tags=["Design"])
    app.include_router(approval_router,       prefix=f"{PREFIX}",              tags=["Approval"])
    app.include_router(deployment_router,     prefix=f"{PREFIX}",              tags=["Deployment"])
    app.include_router(form_builder_router,            prefix=f"{PREFIX}/form-builder", tags=["Form Builder"])
    app.include_router(form_builder_submission_router, prefix=f"{PREFIX}/form-builder", tags=["Form Builder"])
    app.include_router(form_builder_migration_router,   prefix=f"{PREFIX}/form-builder", tags=["Form Builder"])
    app.include_router(tasks_router,                   prefix=f"{PREFIX}/tasks",        tags=["Tasks"])
    app.include_router(projects_router,      prefix=f"{PREFIX}/projects",      tags=["Projects"])
    app.include_router(outage_router,        prefix=f"{PREFIX}/outages",       tags=["Outage"])
    app.include_router(onboarding_router,    prefix=f"{PREFIX}/onboarding",    tags=["Onboarding"])
    app.include_router(audit_router,         prefix=f"{PREFIX}/audit-logs",    tags=["Audit"])
    app.include_router(notifications_router, prefix=f"{PREFIX}/notifications", tags=["Notifications"])
    app.include_router(reports_router,       prefix=f"{PREFIX}/reports",       tags=["Reports"])
    app.include_router(settings_router,      prefix=f"{PREFIX}/settings",      tags=["Settings"])
    app.include_router(activity_router,      prefix=f"{PREFIX}",               tags=["Activity"])
    app.include_router(dashboard_router,      prefix=f"{PREFIX}/dashboard",    tags=["Dashboard"])
    # customer_forms_router MUST be registered BEFORE forms_router.
    # forms_router has GET /forms/{context} which would shadow
    # GET /forms/schemas if registered first.
    app.include_router(customer_forms_router, prefix=f"{PREFIX}/forms",         tags=["Customer Forms"])
    app.include_router(customers_router,      prefix=f"{PREFIX}/customers",     tags=["Customers"])
    app.include_router(external_router,       prefix=f"{PREFIX}/external",      tags=["External Webhooks"])
    app.include_router(forms_router,          prefix=f"{PREFIX}",               tags=["Forms"])
    app.include_router(webhooks_router,       prefix=f"{PREFIX}",               tags=["Webhooks"])
    app.include_router(shifts_router,         prefix=f"{PREFIX}",               tags=["Shifts"])

    # ── Health check ────────────────────────────────────────
    @app.get("/health", tags=["Health"])
    async def health():
        from app.core.database import get_db
        from app.core.redis_client import redis_pool
        db_ok    = False
        redis_ok = False
        try:
            async for session in get_db():
                await session.execute("SELECT 1")
                db_ok = True
        except Exception:
            pass
        try:
            await redis_pool.client.ping()
            redis_ok = True
        except Exception:
            pass
        return {
            "status": "healthy" if (db_ok and redis_ok) else "degraded",
            "database": "ok" if db_ok else "error",
            "redis": "ok" if redis_ok else "error",
            "app": "Opsyn v2.0.0",
            "powered_by": "SlimTech",
        }

    return app


app = create_app()
