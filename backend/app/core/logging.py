# ============================================================
# OPSYN LOGGING — app/core/logging.py
# Re-exports configure_logging from infrastructure
# ============================================================
from app.core.infrastructure import configure_logging
__all__ = ["configure_logging"]
