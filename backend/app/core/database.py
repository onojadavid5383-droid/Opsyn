# ============================================================
# OPSYN DATABASE — app/core/database.py
# Async SQLAlchemy engine, session factory, Base, get_db()
# Tenant isolation: get_db() injects SET LOCAL app.tenant_id
# from tenant_id_ctx (set by TenantMiddleware per request).
# ============================================================

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.core.config import settings


# ── Declarative base (all ORM models extend this) ────────────
class Base(DeclarativeBase):
    pass


# ── Async engine ─────────────────────────────────────────────
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

# ── Session factory ───────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ── FastAPI dependency ────────────────────────────────────────
async def get_db():
    """
    Yields an async database session with tenant RLS context injected.
    TenantMiddleware sets tenant_id_ctx before this runs.
    If tenant_id is available, SET LOCAL app.tenant_id scopes all
    RLS policies so cross-tenant data leakage is impossible at DB level.
    """
    from app.core.context import tenant_id_ctx
    async with AsyncSessionLocal() as session:
        try:
            # Inject tenant context for Row Level Security
            tenant_id = tenant_id_ctx.get()
            if tenant_id:
                await session.execute(
                    text(f"SET LOCAL app.tenant_id = '{tenant_id}'")
                )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Health ping ───────────────────────────────────────────────
async def ping_db() -> bool:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
