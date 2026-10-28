# ============================================================
# OPSYN TEST CONFTEST — tests/conftest.py
# CRITICAL: env vars must be set BEFORE any app module imports.
# This file is loaded by pytest before any test collection.
# ============================================================

import os

# ── Set required env vars immediately ─────────────────────────
# These are set before any import so pydantic-settings can load.
os.environ.setdefault("DATABASE_URL",
    "postgresql+asyncpg://opsyn:opsyn@localhost:5432/opsyn_test")
os.environ.setdefault("SECRET_KEY",
    "test-secret-key-minimum-32-characters-long-for-jwt-signing")
os.environ.setdefault("ENVIRONMENT",       "testing")
os.environ.setdefault("REDIS_URL",         "redis://localhost:6379/0")
os.environ.setdefault("SMTP_PASSWORD",     "test-smtp-password")
os.environ.setdefault("FRONTEND_URL",      "http://localhost:5173")
os.environ.setdefault("ALLOWED_ORIGINS_STR", "http://localhost:5173")

# Derive the Celery broker from REDIS_URL when it is not given explicitly.
#
# These two were previously independent defaults, so a run that pointed
# REDIS_URL at a container (as the isolated test harness does) still left the
# broker on localhost and any task that enqueued work raised
# "ConnectionError: Error 111 connecting to localhost:6379" -- a harness
# failure that surfaced as an unrelated application error. Deriving the broker
# keeps the two in step; the db index differs so tests and tasks cannot collide.
if not os.environ.get("CELERY_BROKER_URL"):
    _redis = os.environ["REDIS_URL"].rstrip("/")
    _base, _, _tail = _redis.rpartition("/")
    os.environ["CELERY_BROKER_URL"] = f"{_base}/1" if _base else "redis://localhost:6379/1"

# ── Now safe to import app modules ────────────────────────────
import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker
)
from sqlalchemy.pool import NullPool

from app.core.database import Base, get_db
from app.core.redis_client import redis_pool
from main import app, setup_rate_limiter


# ── Event loop policy ─────────────────────────────────────────
# NOTE: there is deliberately no `event_loop` fixture here.
#
# pytest-asyncio runs each async test in its own function-scoped loop.
# A session-scoped engine therefore hands out asyncpg connections bound
# to the loop that created them, and the next test -- running in a
# different loop -- fails with "Future attached to a different loop".
# Overriding `event_loop` is also deprecated in pytest-asyncio >= 0.23.
#
# Instead: schema setup runs in its own isolated loop and is torn down
# before any test starts, and every test gets a fresh engine with
# NullPool so no connection ever outlives the loop that opened it.
# This mirrors app/tasks/_db.py, which solves the same problem for
# Celery workers.


# ── Test database schema (session, sync) ──────────────────────
@pytest.fixture(scope="session", autouse=True)
def _db_schema():
    """
    Create the schema once per session and drop it at the end.

    This is a *sync* fixture that drives async work through
    asyncio.run(), so it owns a private loop that is closed before any
    test runs. Nothing it opens can leak into a test's loop.
    """
    test_url = os.environ["DATABASE_URL"]

    async def _run(op):
        engine = create_async_engine(test_url, echo=False, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(op)
        finally:
            await engine.dispose()

    # create_all is idempotent -- it only adds missing tables, so it is
    # safe on a database Alembic already owns (which is what CI does:
    # `alembic upgrade head` then pytest).
    try:
        asyncio.run(_run(Base.metadata.create_all))
    except Exception as e:
        pytest.skip(f"Test database unavailable: {e}")

    yield

    # Deliberately NO drop_all. This fixture used to drop every table at
    # session teardown, which would destroy the schema CI had just
    # migrated and wipe any seeded fixture data. Tests get isolation from
    # the per-test session rollback in `db_session`, not from dropping
    # the database.


# ── Test database engine (per test) ───────────────────────────
@pytest.fixture
async def db_engine():
    """A fresh engine bound to this test's event loop."""
    engine = create_async_engine(
        os.environ["DATABASE_URL"], echo=False, poolclass=NullPool
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Provide a rolled-back async DB session per test."""
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client(db_session):
    """HTTP test client wired to the test database session.

    httpx's ASGITransport does not run the application lifespan, so
    anything main.lifespan() normally sets up has to be started here.
    Without the Redis connect below, every login fails with
    "'NoneType' object has no attribute 'setex'" when the refresh token
    is written -- redis_pool.client is still None.

    Connecting inside this (function-scoped) fixture also keeps the
    Redis client on the same event loop as the test using it.
    """
    await redis_pool.connect()
    try:
        await setup_rate_limiter()
    except Exception:
        pass  # rate limiting is optional in tests; Redis is already up

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        await redis_pool.disconnect()


# ── Seeded auth accounts ──────────────────────────────────────
# The admin/manager token fixtures log in with credentials that only exist
# after scripts/seed.py runs. Seeding it here (rather than skipping or minting
# a token) is what makes the permission tests meaningful: a token for a
# non-existent user returns 401 where a test expects 403, which looks like a
# permissions bug but is really a missing fixture.
@pytest.fixture(scope="session", autouse=True)
def _seeded_database():
    """
    Run the real seed once per session.

    It is scripts/seed.py rather than a test-local stub so tests run against
    the same tenant, roles, departments and feature permissions that dev and
    CI see -- a stub would let permission tests pass against a role wiring that
    does not exist outside the suite.

    It commits, so it must not run inside db_session's per-test rollback.
    Its own loop, like _db_schema, is closed before any test runs.
    """
    test_url = os.environ["DATABASE_URL"]

    async def _run() -> None:
        engine = create_async_engine(test_url, echo=False, poolclass=NullPool)
        try:
            # Point the application's session factory at the test database for
            # the duration of the seed, so seed() cannot touch a dev database
            # if DATABASE_URL is ever set differently in the environment.
            from app.core import database as database_module
            previous = database_module.AsyncSessionLocal
            database_module.AsyncSessionLocal = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            try:
                from scripts.seed import seed
                await seed()
            finally:
                database_module.AsyncSessionLocal = previous
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    except Exception as e:
        pytest.fail(
            "Seeding the test database failed, so admin_token/manager_token "
            f"cannot authenticate and every permission test would be vacuous: {e}"
        )

    yield


# ── Auth token fixtures ───────────────────────────────────────
@pytest.fixture
async def admin_token(client, _seeded_database):
    """JWT for admin@opsyn.ng.

    Fails rather than skipping: this account is seeded by _seeded_database, so
    a non-200 here means seeding or login is genuinely broken, and skipping
    would hide that behind a green run.
    """
    resp = await client.post("/api/v1/auth/login", json={
        "email":    "admin@opsyn.ng",
        "password": "opsyn_admin_2026",
    })
    if resp.status_code != 200:
        pytest.fail(
            f"admin@opsyn.ng could not log in ({resp.status_code}). "
            f"Seeded by _seeded_database, so this is a real failure: "
            f"{resp.text[:300]}"
        )
    return resp.json()["data"]["access_token"]


@pytest.fixture
async def manager_token(client, _seeded_database):
    """JWT for manager@opsyn.ng.

    There is deliberately no fallback here any more. The old one minted a
    token for 00000000-0000-0000-0000-000000000001, a user that only exists if
    the database was seeded and which otherwise does not exist at all --
    producing a validly-signed token that resolves to no user, so every
    permission assertion saw 401 instead of the 403 it was checking for.
    """
    resp = await client.post("/api/v1/auth/login", json={
        "email":    "manager@opsyn.ng",
        "password": "opsyn_manager_2026",
    })
    if resp.status_code != 200:
        pytest.fail(
            f"manager@opsyn.ng could not log in ({resp.status_code}). "
            f"Seeded by _seeded_database, so this is a real failure: "
            f"{resp.text[:300]}"
        )
    return resp.json()["data"]["access_token"]
