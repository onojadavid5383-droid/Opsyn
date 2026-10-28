# ============================================================
# OPSYN STAFF SERVICE — app/modules/staff/service.py
# Fixed: serialize User ORM objects to dicts to prevent
# PydanticSerializationError: Unable to serialize unknown type
# ============================================================

from __future__ import annotations
import uuid
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status

from app.modules.staff.models import User, StaffProfile
from app.modules.staff.policy import StaffPolicy
from app.modules.staff.schemas import CreateStaffRequest, UpdateStaffRequest
from app.modules.roles.models import Role
from app.modules.organisation.models import Department
from app.core.security import hash_password, create_invite_token
from app.modules.audit.service import audit_service
from app.events.bus import event_bus

import logging
log = logging.getLogger("opsyn.staff")


def _serialize_user(user: User) -> dict:
    """
    Convert a User ORM object + StaffProfile into a JSON-safe dict.
    This prevents PydanticSerializationError when returning ORM objects
    inside response_model=StaffListResponse (which has data: dict).
    """
    p = user.staff_profile
    r = user.role

    profile_dict = None
    if p:
        profile_dict = {
            "id":                       str(p.id),
            "user_id":                  str(p.user_id),
            "staff_code":               p.staff_code,
            "first_name":               p.first_name,
            "last_name":                p.last_name,
            "full_name":                f"{p.first_name} {p.last_name}",
            "phone":                    p.phone,
            "job_title":                p.job_title,
            "skill_category":           p.skill_category,
            "specialization":           p.specialization,
            "employment_type":          p.employment_type,
            "status":                   p.status,
            "olt_domain":               p.olt_domain,
            "work_location":            p.work_location,
            "outage_responsibility":    p.outage_responsibility,
            "mec_responsibility":       p.mec_responsibility,
            "approval_authority_level": p.approval_authority_level,
            "notes":                    p.notes,
            "joined_at":                p.joined_at.isoformat() if p.joined_at else None,
            "end_date":                 p.end_date.isoformat() if p.end_date else None,
            "created_at":               p.created_at.isoformat() if p.created_at else None,
            "department": {
                "id":   str(p.department.id),
                "name": p.department.name,
            } if p.department else None,
            "team": {
                "id":            str(p.team.id),
                "name":          p.team.name,
                "department_id": str(p.team.department_id),
            } if p.team else None,
            "region": {
                "id":   str(p.region.id),
                "name": p.region.name,
                "code": p.region.code,
            } if p.region else None,
        }

    return {
        "id":            str(user.id),
        "username":      user.username,
        "email":         user.email,
        "is_active":     user.is_active,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at":    user.created_at.isoformat() if user.created_at else None,
        "role": {
            "id":            str(r.id),
            "name":          r.name,
            "level":         r.level,
            "is_system_role": r.is_system_role,
        } if r else None,
        "staff_profile": profile_dict,
    }


class StaffService:

    async def create(self, db: AsyncSession, payload: CreateStaffRequest, caller: User) -> dict:
        target_role = await self._load_role(db, payload.role_id)
        StaffPolicy.can_create(caller, payload.department_id, target_role.level)

        await self._assert_email_unique(db, payload.email)
        await self._assert_username_unique(db, payload.username, caller.tenant_id)
        if payload.staff_code:
            await self._assert_staff_code_unique(db, payload.staff_code)

        staff_code = payload.staff_code or await self._generate_staff_code(db, payload.department_id)

        if payload.invite_method == "password" and payload.temporary_password:
            pw_hash = hash_password(payload.temporary_password)
        else:
            pw_hash = hash_password(uuid.uuid4().hex)

        # is_active = can this user login? Only "inactive" and "suspended" block login.
        # "on_leave" staff are still employees and must retain login access.
        account_active = payload.status not in ("inactive", "suspended")

        user = User(
            tenant_id=caller.tenant_id,
            username=payload.username,
            email=payload.email,
            password_hash=pw_hash,
            role_id=payload.role_id,
            is_active=account_active,
        )
        db.add(user)
        await db.flush()

        profile = StaffProfile(
            tenant_id=caller.tenant_id,
            user_id=user.id,
            staff_code=staff_code,
            first_name=payload.first_name,
            last_name=payload.last_name,
            phone=payload.phone,
            job_title=payload.job_title,
            skill_category=getattr(payload, "skill_category", None),
            specialization=payload.specialization,
            employment_type=payload.employment_type,
            region_id=payload.region_id,
            department_id=payload.department_id,
            team_id=payload.team_id,
            manager_user_id=payload.manager_user_id,
            approval_authority_level=payload.approval_authority_level,
            olt_domain=payload.olt_domain,
            work_location=payload.work_location,
            outage_responsibility=payload.outage_responsibility,
            mec_responsibility=payload.mec_responsibility,
            status=payload.status,
            notes=payload.notes,
            joined_at=date.fromisoformat(payload.joined_at) if payload.joined_at else None,
            end_date=date.fromisoformat(payload.end_date) if payload.end_date else None,
            created_by=caller.id,
        )
        db.add(profile)
        await db.flush()

        try:
            await audit_service.log(
                db, actor_id=caller.id, action="staff.created",
                target_type="user", target_id=user.id,
                after_state={"username": user.username, "email": user.email,
                             "role_id": str(user.role_id), "staff_code": staff_code},
                tenant_id=caller.tenant_id,
            )
        except Exception:
            # Audit writes are a security control -- never fail the request
            # over one, but never lose it silently either.
            log.exception("audit_log_write_failed")

        await event_bus.emit("staff.created", {
            "user_id":      str(user.id), "email": user.email,
            "invite_method": payload.invite_method,
            "invite_token":  create_invite_token(str(user.id)) if payload.invite_method == "email" else None,
            "actor_id":     str(caller.id),
        })

        await db.refresh(user)
        # Reload with full relationships
        user = await self._load_user(db, user.id)
        return _serialize_user(user)

    async def list(
        self, db: AsyncSession, caller: User,
        page: int = 1, size: int = 20,
        search: str | None = None,
        dept_id: uuid.UUID | None = None,
        role_id: uuid.UUID | None = None,
        status: str | None = None,
        region_id: uuid.UUID | None = None,
    ) -> dict:
        q = (
            select(User)
            .join(StaffProfile, StaffProfile.user_id == User.id)
            .where(User.is_deleted.is_(False))
            .options(
                selectinload(User.staff_profile).selectinload(StaffProfile.department),
                selectinload(User.staff_profile).selectinload(StaffProfile.team),
                selectinload(User.staff_profile).selectinload(StaffProfile.region),
                selectinload(User.role),
            )
        )

        if caller.role.level < 5:
            dept_ids = [s.scope_reference_id for s in (caller.scopes or [])
                        if s.scope_type == "department"]
            if dept_ids:
                q = q.where(StaffProfile.department_id.in_(dept_ids))

        if search:
            q = q.where(or_(
                StaffProfile.first_name.ilike(f"%{search}%"),
                StaffProfile.last_name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                StaffProfile.staff_code.ilike(f"%{search}%"),
            ))
        if dept_id:   q = q.where(StaffProfile.department_id == dept_id)
        if role_id:   q = q.where(User.role_id == role_id)
        if status:    q = q.where(StaffProfile.status == status)
        if region_id: q = q.where(StaffProfile.region_id == region_id)

        total = (await db.execute(
            select(func.count()).select_from(q.subquery())
        )).scalar_one()

        users = (await db.execute(
            q.offset((page - 1) * size).limit(size)
        )).scalars().all()

        return {
            "items":       [_serialize_user(u) for u in users],
            "total":       total,
            "page":        page,
            "size":        size,
            "total_pages": max(1, -(-total // size)),
        }

    async def get(self, db: AsyncSession, user_id: uuid.UUID, caller: User) -> dict:
        StaffPolicy.can_view_sensitive(caller, user_id)
        user = await self._load_user(db, user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Staff member not found.")
        return _serialize_user(user)

    async def update(self, db: AsyncSession, user_id: uuid.UUID,
                     payload: UpdateStaffRequest, caller: User) -> dict:
        user = await self._load_user(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Staff member not found.")
        StaffPolicy.can_deactivate(caller, user)  # reuse same level check (manager+)

        profile = user.staff_profile
        if not profile:
            raise HTTPException(status_code=404, detail="Staff profile not found.")

        changes: dict = {}

        if payload.role_id is not None and payload.role_id != user.role_id:
            role = await self._load_role(db, payload.role_id)
            if role.level >= (caller.role.level if caller.role else 0):
                raise HTTPException(403, "Cannot assign a role at or above your own level.")
            changes["role_id"] = {"from": str(user.role_id), "to": str(payload.role_id)}
            user.role_id = payload.role_id

        profile_field_map = {
            "department_id":           "department_id",
            "employment_type":         "employment_type",
            "phone":                   "phone",
            "job_title":               "job_title",
            "skill_category":          "skill_category",
            "specialization":          "specialization",
            "team_id":                 "team_id",
            "manager_user_id":         "manager_user_id",
            "region_id":               "region_id",
            "olt_domain":              "olt_domain",
            "work_location":           "work_location",
            "outage_responsibility":   "outage_responsibility",
            "mec_responsibility":      "mec_responsibility",
            "approval_authority_level":"approval_authority_level",
            "notes":                   "notes",
        }
        for field, attr in profile_field_map.items():
            new_val = getattr(payload, field)
            if new_val is not None:
                old_val = getattr(profile, attr)
                if str(old_val) != str(new_val):
                    changes[field] = {"from": str(old_val) if old_val is not None else None,
                                      "to":   str(new_val)}
                    setattr(profile, attr, new_val)

        for date_field in ("joined_at", "end_date"):
            raw = getattr(payload, date_field)
            if raw is not None:
                parsed = date.fromisoformat(raw)
                old_val = getattr(profile, date_field)
                if old_val != parsed:
                    changes[date_field] = {"from": old_val.isoformat() if old_val else None,
                                           "to":   raw}
                    setattr(profile, date_field, parsed)

        if changes:
            try:
                await audit_service.log(
                    db, actor_id=caller.id, action="staff.profile_updated",
                    target_type="user", target_id=user_id,
                    after_state={"changed_fields": changes},
                    tenant_id=caller.tenant_id,
                )
            except Exception:
                # Audit writes are a security control -- never fail the request
                # over one, but never lose it silently either.
                log.exception("audit_log_write_failed")

        await db.flush()
        await db.commit()
        user = await self._load_user(db, user_id)
        return _serialize_user(user)

    async def update_status(self, db: AsyncSession, user_id: uuid.UUID,
                             new_status: str, caller: User) -> dict:
        user = (await db.execute(
            select(User).where(User.id == user_id)
            .options(selectinload(User.staff_profile), selectinload(User.role))
        )).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="Staff member not found.")
        StaffPolicy.can_deactivate(caller, user)
        user.staff_profile.status = new_status
        user.is_active = new_status not in ("inactive", "suspended")
        try:
            await audit_service.log(db, caller.id, "staff.status_changed", "user",
                                     user.id, after_state={"status": new_status},
                                     tenant_id=caller.tenant_id)
        except Exception:
            # Audit writes are a security control -- never fail the request
            # over one, but never lose it silently either.
            log.exception("audit_log_write_failed")
        await db.flush()
        user = await self._load_user(db, user_id)
        return _serialize_user(user)

    async def delete(self, db: AsyncSession, user_id: uuid.UUID, caller: User) -> dict:
        user = await self._load_user(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Staff member not found.")
        if user.is_deleted:
            raise HTTPException(status_code=404, detail="Staff member not found.")
        StaffPolicy.can_delete(caller, user)

        user.is_deleted = True
        user.is_active  = False
        if user.staff_profile:
            user.staff_profile.status = "inactive"

        try:
            await audit_service.log(
                db, actor_id=caller.id, action="staff.deleted",
                target_type="user", target_id=user_id,
                after_state={"deleted_by": str(caller.id), "email": user.email},
                tenant_id=caller.tenant_id,
            )
        except Exception:
            # Audit writes are a security control -- never fail the request
            # over one, but never lose it silently either.
            log.exception("audit_log_write_failed")

        await db.flush()
        return {"id": str(user_id), "deleted": True}

    async def _load_user(self, db: AsyncSession, user_id: uuid.UUID) -> User | None:
        return (await db.execute(
            select(User).where(User.id == user_id)
            .options(
                selectinload(User.staff_profile).selectinload(StaffProfile.department),
                selectinload(User.staff_profile).selectinload(StaffProfile.team),
                selectinload(User.staff_profile).selectinload(StaffProfile.region),
                selectinload(User.role),
                selectinload(User.scopes),
            )
        )).scalar_one_or_none()

    async def _load_role(self, db: AsyncSession, role_id: uuid.UUID) -> Role:
        role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
        if not role:
            raise HTTPException(status_code=422, detail="Invalid role_id.")
        return role

    async def _assert_email_unique(self, db: AsyncSession, email: str) -> None:
        if (await db.execute(select(User.id).where(User.email == email))).first():
            raise HTTPException(status_code=409, detail="A user with this email already exists.")

    async def _assert_username_unique(
        self, db: AsyncSession, username: str, tenant_id: uuid.UUID
    ) -> None:
        # Usernames are unique per tenant (see migration 0084), not globally.
        # A global check would reject a name another organisation happens to
        # use and leak the fact that it exists.
        if (await db.execute(
            select(User.id).where(
                User.username == username, User.tenant_id == tenant_id
            )
        )).first():
            raise HTTPException(status_code=409, detail="Username is already taken.")

    async def _assert_staff_code_unique(self, db: AsyncSession, staff_code: str) -> None:
        if (await db.execute(
            select(StaffProfile.id).where(StaffProfile.staff_code == staff_code)
        )).first():
            raise HTTPException(status_code=409, detail="Staff code is already in use.")

    async def _generate_staff_code(self, db: AsyncSession, dept_id: uuid.UUID) -> str:
        dept = (await db.execute(
            select(Department).where(Department.id == dept_id)
        )).scalar_one_or_none()
        prefix = dept.name[:3].upper() if dept else "OPS"
        count = (await db.execute(
            select(func.count()).where(StaffProfile.department_id == dept_id)
        )).scalar_one()
        return f"{prefix}-{str(count + 1).zfill(4)}"


staff_service = StaffService()

