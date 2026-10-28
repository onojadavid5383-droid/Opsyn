# ============================================================
# OPSYN AUTH MODULE — app/modules/auth/router.py
# Login, refresh token rotation, logout
# ============================================================

from datetime import datetime, timezone
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from pydantic import BaseModel, EmailStr, field_validator

from app.core.database import get_db
from app.core.security import verify_password, create_access_token, create_refresh_token, decode_token, hash_password
from app.core.config import settings
from app.core.redis_client import redis_pool
from app.dependencies.auth import get_current_user
from app.modules.staff.models import User, StaffProfile
from app.modules.tenants.models import Tenant
from app.modules.tenants.setup_service import apply_fttx_template
from app.modules.audit.service import audit_service
from jose import JWTError

import logging
log = logging.getLogger("opsyn.auth")

router = APIRouter()

REFRESH_COOKIE = "opsyn_refresh"
REFRESH_TTL    = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400


# ── Schemas ───────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email:    EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    expires_in:   int = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


# ── Endpoints ─────────────────────────────────────────────────
@router.post("/login", response_model=dict)
async def login(
    payload:  LoginRequest,
    response: Response,
    request:  Request,
    db:       AsyncSession = Depends(get_db),
):
    # Load user (explicitly join-load role so we can read role.name/level)
    from sqlalchemy.orm import joinedload as _jl
    user = (await db.execute(
        select(User)
        .where(User.email == payload.email)
        .options(_jl(User.role))
    )).scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    if getattr(user, "is_deleted", False):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact your administrator.",
        )

    # Build token extra claims — tenant_id included for TenantMiddleware
    extra = {
        "role":       user.role.name,
        "role_level": user.role.level,
        "username":   user.username,
        "tenant_id":  str(user.tenant_id) if hasattr(user, "tenant_id") and user.tenant_id else None,
    }

    access_token   = create_access_token(str(user.id), extra)
    refresh_token  = create_refresh_token(str(user.id))

    # Store hashed refresh token in Redis
    import hashlib
    rh = hashlib.sha256(refresh_token.encode()).hexdigest()
    await redis_pool.client.setex(f"refresh:{rh}", REFRESH_TTL, str(user.id))

    # Set httpOnly cookie for refresh token
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=(settings.ENVIRONMENT == "production"),
        samesite="lax",
        max_age=REFRESH_TTL,
        path="/api/v1/auth",
    )

    # Update last login
    user.last_login_at = datetime.now(timezone.utc)
    await db.flush()

    # Audit
    try:
        await audit_service.log(db, user.id, "auth.login", "user", user.id,
                                 after_state={"ip": request.client.host if request.client else "unknown"},
                                 tenant_id=user.tenant_id)
    except Exception:
        # Audit writes are a security control -- never fail the request
        # over one, but never lose it silently either.
        log.exception("audit_log_write_failed")

    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "token_type":   "bearer",
            "expires_in":   settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": {
                "id":         str(user.id),
                "username":   user.username,
                "email":      user.email,
                "role":       {"id": str(user.role.id), "name": user.role.name, "level": user.role.level},
                "role_level": user.role.level,
                "is_active":  user.is_active,
            }
        }
    }


@router.post("/refresh", response_model=dict)
async def refresh_token(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token.")

    try:
        payload = decode_token(token)
        if payload.get("type") != "refresh":
            raise ValueError("Not a refresh token")
        user_id = payload["sub"]
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid refresh token.")

    import hashlib
    rh = hashlib.sha256(token.encode()).hexdigest()
    stored = await redis_pool.client.get(f"refresh:{rh}")
    if not stored:
        raise HTTPException(status_code=401, detail="Refresh token revoked or expired.")

    # Rotate: delete old, issue new
    await redis_pool.client.delete(f"refresh:{rh}")

    # Refresh requests run outside the login path, so eagerly load the role
    # before building the access-token claims. Accessing a lazy relationship
    # here can trigger async IO from ordinary attribute access and fail the
    # refresh with a 500 once the 15-minute access token expires.
    from sqlalchemy.orm import joinedload
    user = (await db.execute(
        select(User).where(User.id == user_id).options(joinedload(User.role))
    )).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive.")

    extra = {
        "role": user.role.name, "role_level": user.role.level, "username": user.username,
        "tenant_id": str(user.tenant_id) if hasattr(user, "tenant_id") and user.tenant_id else None,
    }
    new_access  = create_access_token(str(user.id), extra)
    new_refresh = create_refresh_token(str(user.id))
    new_rh      = hashlib.sha256(new_refresh.encode()).hexdigest()
    await redis_pool.client.setex(f"refresh:{new_rh}", REFRESH_TTL, str(user.id))

    response.set_cookie(REFRESH_COOKIE, new_refresh, httponly=True,
                        secure=(settings.ENVIRONMENT=="production"),
                        samesite="lax", max_age=REFRESH_TTL, path="/api/v1/auth")

    return {"success": True, "data": {"access_token": new_access, "token_type": "bearer",
                                       "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60}}


class ActivateRequest(BaseModel):
    token:    str
    password: str


class ResetRequest(BaseModel):
    token:        str
    new_password: str


@router.post("/activate", response_model=dict)
async def activate_account(
    body:     ActivateRequest,
    request:  Request,
    response: Response,
    db:       AsyncSession = Depends(get_db),
):
    """
    Redeem a one-time invite token and set the account password.
    On success the account is activated and a session token is returned.
    """

    # Validate invite token
    try:
        payload = decode_token(body.token)
        if payload.get("type") != "invite":
            raise ValueError("Not an invite token")
        user_id = payload["sub"]
    except (JWTError, ValueError, Exception):
        raise HTTPException(status_code=401, detail="Invalid or expired activation token.")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.is_active:
        raise HTTPException(status_code=409, detail="Account is already activated.")

    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")

    user.password_hash = hash_password(body.password)
    user.is_active     = True
    user.last_login_at = datetime.now(timezone.utc)

    extra = {
        "role":       user.role.name,
        "role_level": user.role.level,
        "username":   user.username,
        "tenant_id":  str(user.tenant_id) if user.tenant_id else None,
    }
    access_token  = create_access_token(str(user.id), extra)
    refresh_token = create_refresh_token(str(user.id))

    import hashlib
    rh = hashlib.sha256(refresh_token.encode()).hexdigest()
    await redis_pool.client.setex(f"refresh:{rh}", REFRESH_TTL, str(user.id))

    response.set_cookie(
        key=REFRESH_COOKIE, value=refresh_token,
        httponly=True, secure=(settings.ENVIRONMENT == "production"),
        samesite="lax", max_age=REFRESH_TTL, path="/api/v1/auth",
    )

    try:
        await audit_service.log(db, user.id, "auth.account_activated", "user", user.id,
                                 after_state={"ip": request.client.host if request.client else "unknown"},
                                 tenant_id=user.tenant_id)
    except Exception:
        # Audit writes are a security control -- never fail the request
        # over one, but never lose it silently either.
        log.exception("audit_log_write_failed")

    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "token_type":   "bearer",
            "expires_in":   settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": {
                "id":         str(user.id),
                "username":   user.username,
                "email":      user.email,
                "role":       {"id": str(user.role.id), "name": user.role.name, "level": user.role.level},
                "role_level": user.role.level,
                "is_active":  True,
            }
        }
    }


@router.post("/reset-password", response_model=dict)
async def reset_password_with_token(
    body:    ResetRequest,
    request: Request,
    db:      AsyncSession = Depends(get_db),
):
    """Reset password using a token (same invite-token mechanism)."""

    try:
        payload = decode_token(body.token)
        if payload.get("type") not in ("invite", "reset"):
            raise ValueError
        user_id = payload["sub"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired reset token.")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")

    user.password_hash = hash_password(body.new_password)
    return {"success": True, "message": "Password reset successfully."}


class RegisterTenantRequest(BaseModel):
    org_name:       str
    slug:           str
    first_name:     str
    last_name:      str
    email:          EmailStr
    password:       str

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        import re
        v = v.lower().strip()
        if not re.match(r'^[a-z0-9][a-z0-9\-]{2,79}$', v):
            raise ValueError("Slug must be 3-80 lowercase alphanumeric chars or hyphens.")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


@router.post("/register-tenant", status_code=201, response_model=dict)
async def register_tenant(
    payload:  RegisterTenantRequest,
    response: Response,
    request:  Request,
    db:       AsyncSession = Depends(get_db),
):
    """
    Self-service tenant registration.
    Creates: Tenant → seeds roles/depts/perms via apply_fttx_template
    → creates Admin User + StaffProfile → returns access token.
    """
    # Validate slug uniqueness
    existing = (await db.execute(
        select(Tenant).where(Tenant.slug == payload.slug)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Organisation slug already taken.")

    # Validate email uniqueness
    email_taken = (await db.execute(
        select(User).where(User.email == payload.email)
    )).scalar_one_or_none()
    if email_taken:
        raise HTTPException(status_code=409, detail="Email address already registered.")

    # Create tenant
    tenant = Tenant(
        id=uuid.uuid4(),
        name=payload.org_name,
        slug=payload.slug,
        plan="starter",
        is_active=True,
        settings={},
    )
    db.add(tenant)
    await db.flush()  # get tenant.id

    # Seed template with a placeholder admin id (we'll create the user next)
    admin_placeholder_id = uuid.uuid4()
    await apply_fttx_template(db, tenant.id, admin_placeholder_id)

    # Resolve the Admin role id that was just created
    admin_role_row = (await db.execute(text(
        "SELECT id FROM roles WHERE tenant_id = :tid AND name = 'Admin' LIMIT 1"
    ), {"tid": tenant.id})).first()
    if not admin_role_row:
        raise HTTPException(status_code=500, detail="Role seeding failed.")
    admin_role_id = admin_role_row[0]

    # Resolve Management department for the admin's profile
    mgmt_dept_row = (await db.execute(text(
        "SELECT id FROM departments WHERE tenant_id = :tid AND name = 'Management' LIMIT 1"
    ), {"tid": tenant.id})).first()
    mgmt_dept_id = mgmt_dept_row[0] if mgmt_dept_row else None

    # Create admin User
    admin_id = admin_placeholder_id
    username = f"{payload.first_name.lower()}.{payload.last_name.lower()}"
    user = User(
        id=admin_id,
        tenant_id=tenant.id,
        username=username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role_id=admin_role_id,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    # Create StaffProfile for the admin
    staff_code = f"ADM-{str(tenant.id)[:8].upper()}"
    if mgmt_dept_id:
        profile = StaffProfile(
            id=uuid.uuid4(),
            user_id=admin_id,
            tenant_id=tenant.id,
            staff_code=staff_code,
            first_name=payload.first_name,
            last_name=payload.last_name,
            department_id=mgmt_dept_id,
            created_by=admin_id,
        )
        db.add(profile)

    await db.commit()

    # Issue tokens
    extra = {
        "role":       "Admin",
        "role_level": 5,
        "username":   username,
        "tenant_id":  str(tenant.id),
    }
    access_token  = create_access_token(str(admin_id), extra)
    refresh_token = create_refresh_token(str(admin_id))

    import hashlib
    rh = hashlib.sha256(refresh_token.encode()).hexdigest()
    await redis_pool.client.setex(f"refresh:{rh}", REFRESH_TTL, str(admin_id))

    response.set_cookie(
        key=REFRESH_COOKIE, value=refresh_token,
        httponly=True, secure=(settings.ENVIRONMENT == "production"),
        samesite="lax", max_age=REFRESH_TTL, path="/api/v1/auth",
    )

    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "token_type":   "bearer",
            "expires_in":   settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "tenant": {"id": str(tenant.id), "name": tenant.name, "slug": tenant.slug},
            "user": {
                "id":       str(admin_id),
                "username": username,
                "email":    payload.email,
                "role":     "Admin",
            },
        }
    }


@router.post("/logout")
async def logout(response: Response, request: Request, caller: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        import hashlib
        rh = hashlib.sha256(token.encode()).hexdigest()
        await redis_pool.client.delete(f"refresh:{rh}")
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    try:
        await audit_service.log(db, caller.id, "auth.logout", "user", caller.id,
                                 tenant_id=caller.tenant_id)
    except Exception:
        # Audit writes are a security control -- never fail the request
        # over one, but never lose it silently either.
        log.exception("audit_log_write_failed")
    return {"success": True, "message": "Logged out successfully."}
