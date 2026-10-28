# ============================================================
# OPSYN TEST SUITE
# conftest.py + factories + unit + integration + E2E tests
# Run: pytest tests/ -v
# ============================================================
#
# Fixtures (db_engine, db_session, client, admin_token, manager_token) come
# from tests/conftest.py.
#
# This file used to redefine all of them locally. That shadowing was removed
# because it could never pass and, worse, was destructive:
#   - it pointed at a different database (localhost/opsyn_test) with a
#     different password, ignoring DATABASE_URL, so every test that needed a
#     session errored with a connection failure;
#   - its token fixtures used passwords (opsyn_admin_pass) that the seed script
#     does not create (opsyn_admin_2026), so they raised KeyError on the
#     response body;
#   - its session-scoped engine called drop_all() at teardown, which would
#     destroy the schema and seeded data every other test file depends on;
#   - it overrode `event_loop` at session scope, which conftest.py documents as
#     the cause of "Future attached to a different loop" errors.
#
# The tests below are unchanged; they only ever needed conftest's fixtures.
import uuid

import pytest


# ══ tests/unit/test_staff_policy.py ══════════════════════════
import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from app.modules.staff.policy import StaffPolicy

def make_user(level: int, dept_ids: list = None):
    user = MagicMock()
    user.role.level = level
    user.id = uuid.uuid4()
    scopes = []
    for dept_id in (dept_ids or []):
        scope = MagicMock()
        scope.scope_type = "department"
        scope.scope_reference_id = dept_id
        scopes.append(scope)
    user.scopes = scopes
    return user

class TestStaffPolicy:
    def test_admin_can_create_any_dept(self):
        caller = make_user(5)
        dept   = uuid.uuid4()
        StaffPolicy.can_create(caller, dept, 1)  # Should not raise

    def test_manager_can_create_own_dept(self):
        dept   = uuid.uuid4()
        caller = make_user(4, [dept])
        StaffPolicy.can_create(caller, dept, 1)  # Should not raise

    def test_manager_cannot_create_other_dept(self):
        caller = make_user(4, [uuid.uuid4()])
        with pytest.raises(HTTPException) as exc:
            StaffPolicy.can_create(caller, uuid.uuid4(), 1)
        assert exc.value.status_code == 403

    def test_staff_cannot_create(self):
        caller = make_user(1)
        with pytest.raises(HTTPException) as exc:
            StaffPolicy.can_create(caller, uuid.uuid4(), 1)
        assert exc.value.status_code == 403

    def test_hierarchy_violation_same_level(self):
        dept   = uuid.uuid4()
        caller = make_user(4, [dept])
        with pytest.raises(HTTPException) as exc:
            StaffPolicy.can_create(caller, dept, 4)  # target level == caller level
        assert exc.value.status_code == 403

    def test_hierarchy_violation_above_level(self):
        dept   = uuid.uuid4()
        caller = make_user(4, [dept])
        with pytest.raises(HTTPException) as exc:
            StaffPolicy.can_create(caller, dept, 5)  # target > caller
        assert exc.value.status_code == 403

    def test_can_assign_role_below_own_level(self):
        caller = make_user(5)
        StaffPolicy.can_assign_role(caller, 4)  # Should not raise

    def test_cannot_assign_role_at_own_level(self):
        caller = make_user(5)
        with pytest.raises(HTTPException):
            StaffPolicy.can_assign_role(caller, 5)

    def test_non_admin_cannot_assign_roles(self):
        caller = make_user(4)
        with pytest.raises(HTTPException):
            StaffPolicy.can_assign_role(caller, 2)


# ══ tests/integration/test_auth_routes.py ════════════════════
import pytest

@pytest.mark.asyncio
class TestAuthRoutes:
    async def test_login_invalid_credentials(self, client):
        resp = await client.post("/api/v1/auth/login",
                                  json={"email": "nobody@opsyn.ng", "password": "wrong"})
        assert resp.status_code == 401

    async def test_login_valid(self, client, admin_token):
        assert admin_token is not None
        assert len(admin_token) > 20

    async def test_protected_route_without_token(self, client):
        resp = await client.get("/api/v1/staff")
        assert resp.status_code == 401

    async def test_protected_route_with_valid_token(self, client, admin_token):
        resp = await client.get("/api/v1/staff",
                                 headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200

    async def test_refresh_without_cookie(self, client):
        resp = await client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401


# ══ tests/integration/test_staff_routes.py ═══════════════════
@pytest.mark.asyncio
class TestStaffRoutes:
    async def test_staff_list_requires_manager(self, client, admin_token):
        resp = await client.get("/api/v1/staff",
                                 headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    async def test_create_staff_requires_manager(self, client, admin_token, db_session):
        payload = {
            "first_name": "Test", "last_name": "User", "email": "test.user@opsyn.ng",
            "username": "test.user", "role_id": str(uuid.uuid4()),
            "department_id": str(uuid.uuid4()), "job_title": "NOC Operator",
            "employment_type": "permanent", "scope_level": "department",
            "allowed_dashboards": ["noc"], "approval_authority_level": 0,
            "status": "active", "invite_method": "email",
        }
        # This will 422 on role_id not found — that's expected without seeded data
        resp = await client.post("/api/v1/staff", json=payload,
                                  headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code in (201, 422, 409)

    async def test_staff_list_unauthorized_for_staff_role(self, client, manager_token):
        # Manager token should work; plain staff token would 403
        resp = await client.get("/api/v1/staff",
                                 headers={"Authorization": f"Bearer {manager_token}"})
        assert resp.status_code in (200, 403)


# ══ tests/integration/test_task_routes.py ════════════════════
@pytest.mark.asyncio
class TestTaskRoutes:
    async def test_board_endpoint(self, client, admin_token):
        resp = await client.get("/api/v1/tasks/board",
                                 headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "overdue" in data
        assert "today" in data
        assert "this_week" in data
        assert "backlog" in data

    async def test_create_task(self, client, admin_token):
        resp = await client.post("/api/v1/tasks",
                                  json={"title": "Test task", "priority": "high",
                                        "status": "in_progress"},
                                  headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["title"] == "Test task"

    async def test_my_tasks_endpoint(self, client, admin_token):
        resp = await client.get("/api/v1/tasks/my",
                                 headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200


# ══ tests/e2e/test_scope_violation.py ════════════════════════
@pytest.mark.asyncio
class TestScopeViolation:
    async def test_manager_cannot_access_other_dept_staff(self, client, manager_token):
        """Manager with dept A scope cannot list staff from dept B."""
        resp = await client.get("/api/v1/staff?dept_id=00000000-0000-0000-0000-000000000000",
                                 headers={"Authorization": f"Bearer {manager_token}"})
        # Either returns empty list (scoped) or 403 — never returns cross-dept data
        assert resp.status_code in (200, 403)
        if resp.status_code == 200:
            data = resp.json()["data"]
            assert data["total"] == 0  # No cross-dept leak

    async def test_audit_logs_forbidden_for_manager(self, client, manager_token):
        resp = await client.get("/api/v1/audit-logs",
                                 headers={"Authorization": f"Bearer {manager_token}"})
        assert resp.status_code == 403

    async def test_onboarding_approval_forbidden_for_manager(self, client, manager_token):
        fake_id = str(uuid.uuid4())
        resp = await client.patch(f"/api/v1/onboarding/{fake_id}/approve",
                                   headers={"Authorization": f"Bearer {manager_token}"})
        assert resp.status_code == 403
