# ============================================================
# OPSYN EXCEPTIONS — app/core/exceptions.py
# Custom exception classes + global handler registration
# Re-exports register_exception_handlers from infrastructure
# ============================================================

from app.core.infrastructure import register_exception_handlers
from fastapi import HTTPException


class OpsznException(HTTPException):
    """Base Opsyn application exception."""
    def __init__(self, status_code: int, detail: str, code: str = "opsyn_error"):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


class NotFoundError(OpsznException):
    def __init__(self, resource: str = "Resource"):
        super().__init__(404, f"{resource} not found.", "not_found")


class ForbiddenError(OpsznException):
    def __init__(self, detail: str = "Access denied."):
        super().__init__(403, detail, "forbidden")


class ConflictError(OpsznException):
    def __init__(self, detail: str = "Resource already exists."):
        super().__init__(409, detail, "conflict")


class ValidationError(OpsznException):
    def __init__(self, detail: str = "Validation failed."):
        super().__init__(422, detail, "validation_error")


__all__ = [
    "register_exception_handlers",
    "OpsznException", "NotFoundError", "ForbiddenError",
    "ConflictError", "ValidationError",
]
