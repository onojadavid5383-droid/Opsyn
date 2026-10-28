# ============================================================
# OPSYN CONFIG — app/core/config.py
# Pydantic v2 settings — ALLOWED_ORIGINS as str to avoid
# pydantic-settings JSON-parsing conflict.
# ============================================================

from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────
    APP_NAME:    str  = "Opsyn"
    ENVIRONMENT: str  = "development"
    DEBUG:       bool = False

    # ── Database ─────────────────────────────────────────────
    DATABASE_URL: str

    # ── Redis ────────────────────────────────────────────────
    REDIS_URL:         str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"

    # ── JWT ──────────────────────────────────────────────────
    SECRET_KEY:                   str
    ALGORITHM:                    str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES:  int = 15
    REFRESH_TOKEN_EXPIRE_DAYS:    int = 7

    # ── Email ────────────────────────────────────────────────
    SMTP_HOST:     str = "smtp.sendgrid.net"
    SMTP_PORT:     int = 587
    SMTP_USER:     str = "apikey"
    SMTP_PASSWORD: str = ""
    FROM_EMAIL:    str = "no-reply@opsyn.ng"
    FROM_NAME:     str = "Opsyn Platform"

    # ── Frontend ─────────────────────────────────────────────
    FRONTEND_URL: str = "http://localhost:5173"

    # ── CORS — stored as plain comma-separated string ─────────
    # Use get_allowed_origins() to get as list
    ALLOWED_ORIGINS_STR: str = "http://localhost:5173"

    # ── Bcrypt ───────────────────────────────────────────────
    BCRYPT_ROUNDS: int = 12

    # ── Rate limiting ────────────────────────────────────────
    LOGIN_RATE_LIMIT_ATTEMPTS: int = 5
    LOGIN_RATE_LIMIT_WINDOW:   int = 900

    # ── Monitoring ───────────────────────────────────────────
    SENTRY_DSN: str = ""

    # ── Dynamic Form Builder ─────────────────────────────────
    # Enable automatic schema migrations (requires forms.admin permission)
    ENABLE_DYNAMIC_MIGRATIONS: bool = True

    # Table naming pattern for dynamic entity tables
    # Pattern: tenant_{tenant_id}_{schema_machine_name}_data
    DYNAMIC_TABLE_PREFIX: str = "tenant"
    DYNAMIC_TABLE_SUFFIX: str = "data"

    # Migration settings
    MAX_MIGRATION_DURATION_SECONDS: int = 300  # 5 minutes timeout
    MIGRATION_WARNING_ROW_COUNT: int = 100000  # Warn if table has 100K+ rows

    # Feature flags for gradual rollout
    ENABLE_MOBILE_FORM_EXPORT: bool = True     # XForm export for KoboCollect
    ENABLE_MIGRATION_ROLLBACK: bool = True     # Allow rollback of migrations

    @property
    def ALLOWED_ORIGINS(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS_STR.split(",") if o.strip()]


settings = Settings()
