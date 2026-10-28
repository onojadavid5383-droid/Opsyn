# ============================================================
# OPSYN SECURITY — app/core/security.py
# bcrypt hashing (direct, no passlib wrapper) + JWT
# ============================================================

from datetime import datetime, timedelta, timezone
from typing import Optional, Any
from jose import JWTError, jwt
import bcrypt

from app.core.config import settings


# ── Password hashing (direct bcrypt — avoids passlib backend bugs) ──
def hash_password(plain: str) -> str:
    """Hash a password with bcrypt. Truncates to 72 bytes (bcrypt limit)."""
    encoded = plain.encode("utf-8")[:72]
    salt    = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    return bcrypt.hashpw(encoded, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against its bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT ────────────────────────────────────────────────────────────
def create_access_token(subject: str, extra: Optional[dict[str, Any]] = None) -> str:
    now     = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(subject), "iat": now, "exp": expires,
               "type": "access", **(extra or {})}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str) -> str:
    now     = datetime.now(timezone.utc)
    expires = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(subject), "iat": now, "exp": expires, "type": "refresh"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Raises JWTError if invalid or expired."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def verify_access_token(token: str) -> Optional[dict[str, Any]]:
    """Return payload if valid access token, else None."""
    if not token:
        return None
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def create_invite_token(user_id: str) -> str:
    """One-time 24h invite token for new staff activation links."""
    now     = datetime.now(timezone.utc)
    expires = now + timedelta(hours=24)
    payload = {"sub": str(user_id), "iat": now, "exp": expires, "type": "invite"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
