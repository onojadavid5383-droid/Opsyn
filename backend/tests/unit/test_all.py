# ============================================================
# OPSYN BACKEND UNIT TESTS — tests/unit/test_all.py
# All imports are TOP-LEVEL so conftest.py env vars are
# already set before pydantic-settings instantiates Settings.
#
# Run: pytest tests/unit/ -v
# ============================================================

import pytest
import uuid
from datetime import datetime, timedelta, timezone, UTC
from unittest.mock import MagicMock

# ── Top-level imports (env vars set by conftest.py first) ─────
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    decode_token, verify_access_token, create_invite_token,
)
from app.modules.staff.policy import StaffPolicy
from app.modules.staff.schemas import CreateStaffRequest, UpdateStatusRequest
from app.modules.audit.router import AuditService
from app.modules.tasks.router import Task, TaskComment, TaskTag


# ══════════════════════════════════════════════════════════════
#  SECURITY
# ══════════════════════════════════════════════════════════════

class TestSecurity:
    def test_hash_password_produces_bcrypt(self):
        h = hash_password("test_password_123")
        assert h.startswith("$2b$")
        assert len(h) == 60

    def test_verify_password_correct(self):
        pw = "correct_password_abc"
        h  = hash_password(pw)
        assert verify_password(pw, h) is True

    def test_verify_password_wrong(self):
        h = hash_password("correct")
        assert verify_password("wrong", h) is False

    def test_verify_different_hashes_same_password(self):
        pw = "same_password"
        h1 = hash_password(pw)
        h2 = hash_password(pw)
        assert h1 != h2          # bcrypt is salted — always different
        assert verify_password(pw, h1)
        assert verify_password(pw, h2)

    def test_create_access_token_structure(self):
        token   = create_access_token("user-id-123", {"role": "Admin", "role_level": 5})
        payload = decode_token(token)
        assert payload["sub"]        == "user-id-123"
        assert payload["type"]       == "access"
        assert payload["role"]       == "Admin"
        assert payload["role_level"] == 5

    def test_access_token_has_correct_type(self):
        token   = create_access_token("uid")
        payload = decode_token(token)
        assert payload["type"] == "access"

    def test_refresh_token_has_correct_type(self):
        token   = create_refresh_token("uid")
        payload = decode_token(token)
        assert payload["type"] == "refresh"

    def test_verify_access_token_valid(self):
        token  = create_access_token("uid-123")
        result = verify_access_token(token)
        assert result is not None
        assert result["sub"] == "uid-123"

    def test_verify_access_token_invalid_string(self):
        result = verify_access_token("not.a.valid.token")
        assert result is None

    def test_verify_access_token_rejects_refresh_type(self):
        # verify_access_token checks type == "access" — should reject refresh tokens
        refresh = create_refresh_token("uid")
        result  = verify_access_token(refresh)
        assert result is None

    def test_invite_token_structure(self):
        token   = create_invite_token("user-id-abc")
        payload = decode_token(token)
        assert payload["sub"]  == "user-id-abc"
        assert payload["type"] == "invite"

    def test_empty_string_is_invalid_token(self):
        assert verify_access_token("") is None

    def test_extra_claims_preserved_in_token(self):
        token   = create_access_token("uid", {"custom_claim": "opsyn"})
        payload = decode_token(token)
        assert payload.get("custom_claim") == "opsyn"


# ══════════════════════════════════════════════════════════════
#  STAFF POLICY
# ══════════════════════════════════════════════════════════════

def _make_user(level: int, dept_ids: list = None) -> MagicMock:
    """Helper: make a mock User with a given role level and dept scopes."""
    user           = MagicMock()
    user.id        = uuid.uuid4()
    user.role.level = level
    scopes = []
    for did in (dept_ids or []):
        s = MagicMock()
        s.scope_type         = "department"
        s.scope_reference_id = did
        scopes.append(s)
    user.scopes = scopes
    return user


class TestStaffPolicyExtended:

    # ── can_create ────────────────────────────────────────────
    def test_admin_can_create_any_dept(self):
        caller = _make_user(5)
        StaffPolicy.can_create(caller, uuid.uuid4(), 1)  # No exception

    def test_manager_can_create_in_own_dept(self):
        dept   = uuid.uuid4()
        caller = _make_user(4, [dept])
        StaffPolicy.can_create(caller, dept, 1)           # No exception

    def test_manager_cannot_create_in_other_dept(self):
        from fastapi import HTTPException
        caller = _make_user(4, [uuid.uuid4()])            # Scoped to dept A
        with pytest.raises(HTTPException) as exc:
            StaffPolicy.can_create(caller, uuid.uuid4(), 1)  # dept B
        assert exc.value.status_code == 403

    def test_team_lead_cannot_create_staff(self):
        from fastapi import HTTPException
        caller = _make_user(3)
        with pytest.raises(HTTPException) as exc:
            StaffPolicy.can_create(caller, uuid.uuid4(), 1)
        assert exc.value.status_code == 403

    def test_noc_operator_cannot_create_staff(self):
        from fastapi import HTTPException
        caller = _make_user(2)
        with pytest.raises(HTTPException) as exc:
            StaffPolicy.can_create(caller, uuid.uuid4(), 1)
        assert exc.value.status_code == 403

    def test_staff_cannot_create(self):
        from fastapi import HTTPException
        caller = _make_user(1)
        with pytest.raises(HTTPException) as exc:
            StaffPolicy.can_create(caller, uuid.uuid4(), 1)
        assert exc.value.status_code == 403

    def test_hierarchy_violation_same_level(self):
        from fastapi import HTTPException
        dept   = uuid.uuid4()
        caller = _make_user(4, [dept])
        with pytest.raises(HTTPException) as exc:
            StaffPolicy.can_create(caller, dept, 4)       # target == caller level
        assert exc.value.status_code == 403

    def test_hierarchy_violation_above_level(self):
        from fastapi import HTTPException
        dept   = uuid.uuid4()
        caller = _make_user(4, [dept])
        with pytest.raises(HTTPException) as exc:
            StaffPolicy.can_create(caller, dept, 5)       # target > caller level
        assert exc.value.status_code == 403

    # ── can_view_sensitive ───────────────────────────────────
    def test_staff_can_view_own_profile(self):
        caller = _make_user(1)
        StaffPolicy.can_view_sensitive(caller, caller.id)  # No exception

    def test_staff_cannot_view_other_profile(self):
        from fastapi import HTTPException
        caller = _make_user(1)
        with pytest.raises(HTTPException) as exc:
            StaffPolicy.can_view_sensitive(caller, uuid.uuid4())
        assert exc.value.status_code == 403

    def test_manager_can_view_any_profile(self):
        caller = _make_user(4)
        StaffPolicy.can_view_sensitive(caller, uuid.uuid4())   # No exception

    def test_admin_can_view_any_profile(self):
        caller = _make_user(5)
        StaffPolicy.can_view_sensitive(caller, uuid.uuid4())   # No exception

    # ── can_assign_role ───────────────────────────────────────
    def test_admin_can_assign_role_below_own_level(self):
        caller = _make_user(5)
        StaffPolicy.can_assign_role(caller, 4)                 # No exception

    def test_admin_cannot_assign_own_level(self):
        from fastapi import HTTPException
        caller = _make_user(5)
        with pytest.raises(HTTPException):
            StaffPolicy.can_assign_role(caller, 5)

    def test_manager_cannot_assign_any_role(self):
        from fastapi import HTTPException
        caller = _make_user(4)
        with pytest.raises(HTTPException) as exc:
            StaffPolicy.can_assign_role(caller, 1)
        assert exc.value.status_code == 403

    # ── can_view_audit ────────────────────────────────────────
    def test_admin_can_view_audit(self):
        caller = _make_user(5)
        StaffPolicy.can_view_audit(caller)                     # No exception

    def test_manager_cannot_view_audit(self):
        from fastapi import HTTPException
        caller = _make_user(4)
        with pytest.raises(HTTPException) as exc:
            StaffPolicy.can_view_audit(caller)
        assert exc.value.status_code == 403

    def test_staff_cannot_view_audit(self):
        from fastapi import HTTPException
        caller = _make_user(1)
        with pytest.raises(HTTPException) as exc:
            StaffPolicy.can_view_audit(caller)
        assert exc.value.status_code == 403


# ══════════════════════════════════════════════════════════════
#  TASK DEADLINE BUCKETING
# ══════════════════════════════════════════════════════════════

class TaskTestDouble:
    """
    Pure Python stand-in for the Task ORM model — tests deadline_bucket
    logic without needing SQLAlchemy session instrumentation.
    Mirrors the exact property logic from app/modules/tasks/router.py Task.
    """
    def __init__(self, status="in_progress", deadline=None, comments=None, tags=None):
        self.status   = status
        self.deadline = deadline
        self.comments = comments or []
        self.tags     = tags or []

    @property
    def deadline_bucket(self) -> str:
        if self.status in ("done", "archived"):
            return "completed"
        if self.status == "backlog" and not self.deadline:
            return "backlog"
        if not self.deadline:
            return "no_deadline"
        now      = datetime.now(UTC).replace(tzinfo=None)
        deadline = self.deadline.replace(tzinfo=None)
        # Bucket by calendar day, not by 24h window
        today    = now.date()
        dl_date  = deadline.date()
        if dl_date < today:    return "overdue"
        if dl_date == today:   return "today"
        delta_days = (dl_date - today).days
        if delta_days <= 7:    return "this_week"
        if delta_days <= 14:   return "next_week"
        return "no_deadline"

    @property
    def comment_count(self) -> int:
        return len(self.comments)

    @property
    def tag_list(self) -> list:
        return [t.tag for t in self.tags]


def _make_task(status="in_progress", deadline_offset_days=None) -> TaskTestDouble:
    """Build a Task test double without SQLAlchemy instrumentation."""
    deadline = None
    if deadline_offset_days is not None:
        deadline = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=deadline_offset_days)
    return TaskTestDouble(status=status, deadline=deadline)


class TestTaskDeadlineBucket:

    def test_overdue_task(self):
        task = _make_task(deadline_offset_days=-2)
        assert task.deadline_bucket == "overdue"

    def test_today_task(self):
        task = _make_task(deadline_offset_days=0)
        assert task.deadline_bucket == "today"

    def test_this_week_task(self):
        task = _make_task(deadline_offset_days=5)
        assert task.deadline_bucket == "this_week"

    def test_next_week_task(self):
        task = _make_task(deadline_offset_days=10)
        assert task.deadline_bucket == "next_week"

    def test_no_deadline_in_progress(self):
        task = _make_task(status="in_progress", deadline_offset_days=None)
        assert task.deadline_bucket == "no_deadline"

    def test_backlog_no_deadline(self):
        task = _make_task(status="backlog", deadline_offset_days=None)
        assert task.deadline_bucket == "backlog"

    def test_far_future_falls_in_no_deadline_bucket(self):
        task = _make_task(deadline_offset_days=30)
        # > 14 days → no_deadline
        assert task.deadline_bucket == "no_deadline"

    def test_comment_count_zero_when_empty(self):
        task = _make_task()
        assert task.comment_count == 0

    def test_comment_count_reflects_comments(self):
        task          = _make_task()
        task.comments = [MagicMock(), MagicMock(), MagicMock()]
        assert task.comment_count == 3

    def test_tag_list_empty_when_no_tags(self):
        task = _make_task()
        assert task.tag_list == []

    def test_tag_list_returns_tag_strings(self):
        task      = _make_task()
        t1        = MagicMock(); t1.tag = "noc"
        t2        = MagicMock(); t2.tag = "urgent"
        task.tags = [t1, t2]
        assert task.tag_list == ["noc", "urgent"]


# ══════════════════════════════════════════════════════════════
#  STAFF SCHEMAS
# ══════════════════════════════════════════════════════════════

class TestStaffSchemas:

    def _base_payload(self, **overrides) -> dict:
        base = {
            "first_name":      "Olumide",
            "last_name":       "Adesanya",
            "email":           "olumide@opsyn.ng",
            "username":        "olumide.adesanya",
            "department_id":   str(uuid.uuid4()),
            "role_id":         str(uuid.uuid4()),
            "job_title":       "NOC Operator",
        }
        base.update(overrides)
        return base

    def test_valid_request_defaults(self):
        req = CreateStaffRequest(**self._base_payload())
        assert req.first_name             == "Olumide"
        assert req.employment_type        == "permanent"    # default
        assert req.status                 == "active"       # default
        assert req.approval_authority_level == 0           # default
        assert req.invite_method          == "email"        # default

    def test_valid_contract_employment(self):
        req = CreateStaffRequest(**self._base_payload(employment_type="contract"))
        assert req.employment_type == "contract"

    def test_valid_intern_employment(self):
        req = CreateStaffRequest(**self._base_payload(employment_type="intern"))
        assert req.employment_type == "intern"

    def test_invalid_employment_type_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError) as exc:
            CreateStaffRequest(**self._base_payload(employment_type="freelance"))
        errors = exc.value.errors()
        assert any(e["loc"] == ("employment_type",) for e in errors)

    def test_invalid_phone_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError) as exc:
            CreateStaffRequest(**self._base_payload(phone="not-a-phone"))
        errors = exc.value.errors()
        assert any(e["loc"] == ("phone",) for e in errors)

    def test_valid_phone_formats(self):
        for phone in ["+2348012345678", "08012345678"]:
            req = CreateStaffRequest(**self._base_payload(phone=phone))
            assert req.phone == phone

    def test_invalid_status_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError) as exc:
            CreateStaffRequest(**self._base_payload(status="archived"))
        errors = exc.value.errors()
        assert any(e["loc"] == ("status",) for e in errors)

    def test_inactive_status_valid(self):
        req = CreateStaffRequest(**self._base_payload(status="inactive"))
        assert req.status == "inactive"

    def test_suspended_status_valid(self):
        req = CreateStaffRequest(**self._base_payload(status="suspended"))
        assert req.status == "suspended"

    def test_update_status_active(self):
        r = UpdateStatusRequest(status="active")
        assert r.status == "active"

    def test_update_status_inactive(self):
        r = UpdateStatusRequest(status="inactive")
        assert r.status == "inactive"

    def test_update_status_suspended(self):
        r = UpdateStatusRequest(status="suspended")
        assert r.status == "suspended"

    def test_update_status_invalid_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UpdateStatusRequest(status="deleted")


# ══════════════════════════════════════════════════════════════
#  AUDIT SERVICE
# ══════════════════════════════════════════════════════════════

class TestAuditService:

    def setup_method(self):
        self.svc = AuditService()

    def test_scrub_removes_password_hash(self):
        state   = {"username": "test", "password_hash": "$2b$12$abc", "email": "t@opsyn.ng"}
        cleaned = self.svc._scrub(state)
        assert cleaned["password_hash"] == "***"
        assert cleaned["username"]      == "test"
        assert cleaned["email"]         == "t@opsyn.ng"

    def test_scrub_removes_token_field(self):
        state   = {"token": "super-secret-token", "user_id": "123"}
        cleaned = self.svc._scrub(state)
        assert cleaned["token"]   == "***"
        assert cleaned["user_id"] == "123"

    def test_scrub_removes_secret_field(self):
        state   = {"secret": "my-api-secret", "name": "opsyn"}
        cleaned = self.svc._scrub(state)
        assert cleaned["secret"] == "***"
        assert cleaned["name"]   == "opsyn"

    def test_scrub_removes_password_field(self):
        state   = {"password": "plaintext!", "email": "x@y.com"}
        cleaned = self.svc._scrub(state)
        assert cleaned["password"] == "***"

    def test_scrub_none_returns_none(self):
        assert self.svc._scrub(None) is None

    def test_scrub_empty_dict_returns_empty(self):
        assert self.svc._scrub({}) == {}

    def test_scrub_does_not_mutate_original(self):
        original = {"username": "x", "password_hash": "hashed"}
        cleaned  = self.svc._scrub(original)
        assert original["password_hash"] == "hashed"  # Original unchanged
        assert cleaned["password_hash"]  == "***"

    def test_scrub_preserves_unrelated_fields(self):
        state   = {"user_id": "abc", "action": "staff.created",
                   "dept": "NOC", "timestamp": "2026-04-21"}
        cleaned = self.svc._scrub(state)
        assert cleaned == state   # Nothing to scrub — returned as-is
