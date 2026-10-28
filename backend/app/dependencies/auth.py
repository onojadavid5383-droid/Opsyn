# ============================================================
# OPSYN AUTH DEPENDENCIES — app/dependencies/auth.py
# get_current_user() and require_role() FastAPI Depends callables
# ============================================================

import uuid
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.security import verify_access_token
from app.core.database import get_db
from app.modules.staff.models import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request:     Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db:          AsyncSession = Depends(get_db),
) -> User:
    """
    Extract and verify JWT, load User from DB.
    Injected as request.state.user by AuthMiddleware for most requests;
    this Depends() version loads it fresh when needed.
    """
    # Try middleware-injected user first (avoids second DB hit)
    if hasattr(request.state, "user") and request.state.user is not None:
        return request.state.user

    token = None
    if credentials:
        token = credentials.credentials
    elif request.headers.get("Authorization", "").startswith("Bearer "):
        token = request.headers["Authorization"][7:]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Provide a valid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject.")

    user = (await db.execute(
        select(User)
        .where(User.id == uuid.UUID(user_id))
        .options(
            selectinload(User.role),
            selectinload(User.staff_profile),
            selectinload(User.scopes),
        )
    )).scalar_one_or_none()

    if not user or getattr(user, "is_deleted", False):
        raise HTTPException(status_code=401, detail="User not found.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated.")

    return user


def require_role(min_level: int):
    """
    Factory that returns a FastAPI dependency enforcing a minimum role level.
    Usage: Depends(require_role(4))  # Manager or above
    """
    async def _checker(caller: User = Depends(get_current_user)) -> User:
        if caller.role.level < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient privileges. Required role level: {min_level}, yours: {caller.role.level}.",
            )
        return caller
    return _checker


def require_admin():
    return require_role(5)

def require_manager():
    return require_role(4)

def require_team_lead():
    return require_role(3)
