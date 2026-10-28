# Minimal conftest for unit tests — sets env vars only, no DB/Redis imports.
import os

os.environ.setdefault("DATABASE_URL",
    "postgresql+asyncpg://opsyn:opsyn@localhost:5432/opsyn_test")
os.environ.setdefault("SECRET_KEY",
    "test-secret-key-minimum-32-characters-long-for-jwt-signing")
os.environ.setdefault("ENVIRONMENT",       "testing")
os.environ.setdefault("REDIS_URL",         "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("SMTP_PASSWORD",     "test-smtp-password")
os.environ.setdefault("FRONTEND_URL",      "http://localhost:5173")
os.environ.setdefault("ALLOWED_ORIGINS_STR", "http://localhost:5173")
