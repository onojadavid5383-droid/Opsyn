# ============================================================
# OPSYN AUDIT SERVICE — app/modules/audit/service.py
# Re-exports audit_service from router for cross-module use
# ============================================================

from app.modules.audit.router import audit_service, AuditLog, AuditService

__all__ = ["audit_service", "AuditLog", "AuditService"]
