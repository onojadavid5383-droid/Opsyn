# ============================================================
# OPSYN TASK DB HELPER — app/tasks/_db.py
#
# Creates a FRESH async engine + session for each Celery task
# invocation. This prevents the "Future attached to a different
# loop" / "Event loop is closed" errors that occur when the
# global FastAPI engine (bound to the parent process loop) is
# reused inside a forked worker's asyncio.run() loop.
#
# Usage:
#   engine, db = await make_task_session()
#   try:
#       ...work...
#   finally:
#       await db.close()
#       await engine.dispose()
# ============================================================

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings as cfg


async def make_task_session():
    """Return a (engine, session) pair scoped to this task invocation."""
    engine = create_async_engine(
        cfg.DATABASE_URL,
        pool_size=2,
        max_overflow=0,
        connect_args={"timeout": 10},
    )
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, Session()
