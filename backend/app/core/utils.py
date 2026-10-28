# ============================================================
# OPSYN — app/core/utils.py
# Shared utility helpers for request handling.
# G.1.3: IP extraction for audit logging.
# ============================================================

from typing import Optional
from fastapi import Request


def get_client_ip(request: Request) -> Optional[str]:
    """Extract the real client IP, honouring X-Forwarded-For behind a proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None
