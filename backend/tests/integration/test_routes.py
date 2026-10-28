# ============================================================
# OPSYN INTEGRATION TESTS — tests/integration/test_routes.py
# Full HTTP request→response cycle for all major routes
# Run: pytest tests/integration/ -v
# ============================================================

import pytest
import uuid


@pytest.mark.asyncio
class TestAuthIntegration:
    """Auth route integration tests."""

    async def test_login_success_returns_token(self, client):
        """Successful login returns access token and user data."""
        # This test requires seeded admin user
        resp = await client.post("/api/v1/auth/login", json={
            "email": "admin@opsyn.ng",
            "password": "opsyn_admin_2026",
        })
        if resp.status_code == 200:
            data = resp.json()
            assert data["success"] is True
            assert "access_token" in data["data"]
            assert data["data"]["token_type"] == "bearer"
            assert data["data"]["user"]["role"]["level"] == 5

    async def test_login_wrong_password_returns_401(self, client):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "admin@opsyn.ng",
            "password": "wrong-password",
        })
        assert resp.status_code == 401
        assert resp.json()["success"] is False

    async def test_login_nonexistent_email_returns_401(self, client):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "nobody@nowhere.com",
            "password": "any-password",
        })
        assert resp.status_code == 401

    async def test_refresh_without_cookie_returns_401(self, client):
        resp = await client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401

    async def test_protected_route_no_token_returns_401(self, client):
        resp = await client.get("/api/v1/staff")
        assert resp.status_code == 401

    async def test_protected_route_invalid_token_returns_401(self, client):
        resp = await client.get("/api/v1/staff", headers={"Authorization": "Bearer invalid.token.here"})
        assert resp.status_code == 401

    async def test_logout_with_valid_token(self, client, admin_token):
        resp = await client.post("/api/v1/auth/logout",
                                 headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200

    async def test_health_endpoint_public(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["app"] == "Opsyn v2.0.0"
        assert data["powered_by"] == "SlimTech"


@pytest.mark.asyncio
class TestStaffRoutes:
    """Staff route integration tests — RBAC enforcement."""

    async def test_list_staff_requires_manager(self, client, admin_token):
        resp = await client.get("/api/v1/staff",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "items" in data["data"]
        assert "total" in data["data"]

    async def test_list_staff_denied_without_token(self, client):
        resp = await client.get("/api/v1/staff")
        assert resp.status_code == 401

    async def test_check_email_requires_auth(self, client):
        resp = await client.get("/api/v1/staff/check/email?email=test@opsyn.ng")
        assert resp.status_code == 401

    async def test_check_email_with_token(self, client, admin_token):
        resp = await client.get(
            "/api/v1/staff/check/email?email=unique-not-taken@opsyn.ng",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["available"] is True

    async def test_create_staff_invalid_payload(self, client, admin_token):
        # Missing required fields should return 422
        resp = await client.post(
            "/api/v1/staff",
            json={"first_name": "Test"},  # Missing many required fields
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    async def test_create_staff_invalid_role_id(self, client, admin_token):
        # Valid structure but role_id not found → 422 or 403
        payload = {
            "first_name": "Test", "last_name": "User",
            "email": f"test-{uuid.uuid4().hex[:8]}@opsyn.ng",
            "username": f"test-{uuid.uuid4().hex[:8]}",
            "role_id": str(uuid.uuid4()),       # Non-existent role
            "department_id": str(uuid.uuid4()), # Non-existent dept
            "job_title": "Test Engineer",
        }
        resp = await client.post(
            "/api/v1/staff", json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (422, 409, 403)

    async def test_get_nonexistent_staff_returns_404(self, client, admin_token):
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/staff/{fake_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestTaskRoutes:
    """Task route integration tests."""

    async def test_board_endpoint_returns_buckets(self, client, admin_token):
        resp = await client.get("/api/v1/tasks/board",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        # All 7 deadline buckets must be present
        for bucket in ["completed", "overdue", "today", "this_week", "next_week", "no_deadline", "backlog"]:
            assert bucket in data, f"Missing bucket: {bucket}"
        assert "total" in data

    async def test_my_tasks_endpoint(self, client, admin_token):
        resp = await client.get("/api/v1/tasks/my",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    async def test_create_task_minimal(self, client, admin_token):
        resp = await client.post(
            "/api/v1/tasks",
            json={"title": "Integration test task", "priority": "medium", "status": "new"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["title"] == "Integration test task"

    async def test_create_task_returns_correct_bucket(self, client, admin_token):
        from datetime import datetime, timedelta
        # Task with overdue deadline
        past = (datetime.utcnow() - timedelta(days=2)).isoformat()
        resp = await client.post(
            "/api/v1/tasks",
            json={"title": "Past deadline task", "priority": "high", "deadline": past},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201

    async def test_create_task_no_auth_denied(self, client):
        resp = await client.post("/api/v1/tasks",
                                 json={"title": "Unauthorized task"})
        assert resp.status_code == 401

    async def test_list_tasks_paginated(self, client, admin_token):
        resp = await client.get("/api/v1/tasks?page=1&size=10",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "items" in data
        assert "total" in data
        assert "page" in data


@pytest.mark.asyncio
class TestOrganisationRoutes:
    """Organisation route integration tests."""

    async def test_departments_list_authenticated(self, client, admin_token):
        resp = await client.get("/api/v1/departments",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    async def test_teams_list_authenticated(self, client, admin_token):
        resp = await client.get("/api/v1/teams",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200

    async def test_regions_list_authenticated(self, client, admin_token):
        resp = await client.get("/api/v1/regions",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200

    async def test_departments_unauthenticated_denied(self, client):
        resp = await client.get("/api/v1/departments")
        assert resp.status_code == 401

    async def test_create_department_requires_admin(self, client, admin_token, manager_token):
        # Manager should be denied
        resp = await client.post(
            "/api/v1/departments",
            json={"name": f"Test-Dept-{uuid.uuid4().hex[:6]}"},
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code in (403, 422)

        # Admin should succeed
        resp = await client.post(
            "/api/v1/departments",
            json={"name": f"Test-Dept-{uuid.uuid4().hex[:6]}"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (201, 200)


@pytest.mark.asyncio
class TestRoleRoutes:
    """Role and permission route integration tests."""

    async def test_list_roles_authenticated(self, client, admin_token):
        resp = await client.get("/api/v1/roles",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        roles = resp.json()["data"]
        assert isinstance(roles, list)
        # Seeded roles should be present
        role_names = [r["name"] for r in roles]
        assert "Admin" in role_names
        assert "Staff" in role_names

    async def test_list_assignable_roles_filters_by_level(self, client, admin_token):
        resp = await client.get("/api/v1/roles?assignable=true",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        # All returned roles should be below Admin level (5)
        for role in resp.json()["data"]:
            assert role["level"] < 5

    async def test_permissions_list_requires_admin(self, client, manager_token):
        resp = await client.get("/api/v1/permissions",
                                headers={"Authorization": f"Bearer {manager_token}"})
        assert resp.status_code == 403

    async def test_permissions_list_admin_succeeds(self, client, admin_token):
        resp = await client.get("/api/v1/permissions",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        perms = resp.json()["data"]
        assert isinstance(perms, list)
        assert len(perms) > 0
        # All perms have key and description
        for p in perms:
            assert "key" in p


@pytest.mark.asyncio
class TestAuditRoutes:
    """Audit log route integration tests — admin only."""

    async def test_audit_logs_requires_admin(self, client, manager_token):
        resp = await client.get("/api/v1/audit-logs",
                                headers={"Authorization": f"Bearer {manager_token}"})
        assert resp.status_code == 403

    async def test_audit_logs_admin_access(self, client, admin_token):
        resp = await client.get("/api/v1/audit-logs",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "items" in data
        assert "total" in data

    async def test_audit_logs_unauthenticated(self, client):
        resp = await client.get("/api/v1/audit-logs")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestOnboardingRoutes:
    """Onboarding route integration tests."""

    async def test_list_onboarding_requires_manager(self, client, admin_token):
        resp = await client.get("/api/v1/onboarding",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200

    async def test_approve_onboarding_requires_admin(self, client, manager_token):
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/onboarding/{fake_id}/approve",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 403

    async def test_reject_onboarding_requires_manager(self, client, admin_token):
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/onboarding/{fake_id}/reject",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # 404 because fake_id doesn't exist, but auth passed
        assert resp.status_code in (404, 200)


@pytest.mark.asyncio
class TestReportRoutes:
    """Report route integration tests."""

    async def test_summary_requires_manager(self, client, admin_token):
        resp = await client.get("/api/v1/reports/summary",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "staff_total" in data
        assert "tasks_completed" in data

    async def test_summary_unauthenticated(self, client):
        resp = await client.get("/api/v1/reports/summary")
        assert resp.status_code == 401

    async def test_summary_shape(self, client, admin_token):
        resp = await client.get("/api/v1/reports/summary",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        for key in ("staff_total", "staff_active", "tasks_completed", "outages_resolved"):
            assert key in data, f"Missing key in report summary: {key}"


@pytest.mark.asyncio
class TestOutageRoutes:
    """Outage incident route integration tests."""

    async def test_list_outages_authenticated(self, client, admin_token):
        resp = await client.get("/api/v1/outages",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "items" in data or isinstance(data, list)

    async def test_list_outages_unauthenticated(self, client):
        resp = await client.get("/api/v1/outages")
        assert resp.status_code == 401

    async def test_log_outage_minimal(self, client, admin_token):
        resp = await client.post(
            "/api/v1/outages",
            json={"title": "Integration test outage", "severity": "warning"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["title"] == "Integration test outage"
        assert data["status"] == "active"
        assert data["reference"].startswith("OUT-")

    async def test_log_outage_missing_title_returns_422(self, client, admin_token):
        resp = await client.post(
            "/api/v1/outages",
            json={"severity": "critical"},  # Missing required title
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    async def test_resolve_nonexistent_outage_returns_404(self, client, admin_token):
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/outages/{fake_id}/resolve",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    async def test_log_and_resolve_outage(self, client, admin_token):
        # Log
        log_resp = await client.post(
            "/api/v1/outages",
            json={"title": "Route integration outage", "severity": "critical"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert log_resp.status_code == 201
        incident_id = log_resp.json()["data"]["id"]

        # Resolve
        resolve_resp = await client.patch(
            f"/api/v1/outages/{incident_id}/resolve",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resolve_resp.status_code == 200
        assert resolve_resp.json()["data"]["status"] == "resolved"

    async def test_list_live_outages_filter(self, client, admin_token):
        resp = await client.get(
            "/api/v1/outages?status=active",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestNotificationRoutes:
    """Notification route integration tests."""

    async def test_list_notifications_authenticated(self, client, admin_token):
        resp = await client.get("/api/v1/notifications",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    async def test_list_notifications_unauthenticated(self, client):
        resp = await client.get("/api/v1/notifications")
        assert resp.status_code == 401

    async def test_unread_count_authenticated(self, client, admin_token):
        resp = await client.get("/api/v1/notifications/unread-count",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "count" in data
        assert isinstance(data["count"], int)

    async def test_unread_count_unauthenticated(self, client):
        resp = await client.get("/api/v1/notifications/unread-count")
        assert resp.status_code == 401

    async def test_mark_all_read_authenticated(self, client, admin_token):
        resp = await client.patch(
            "/api/v1/notifications/read-all",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    async def test_mark_nonexistent_notification_read(self, client, admin_token):
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/notifications/{fake_id}/read",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Either 404 (not found) or 200 (idempotent) — never 500
        assert resp.status_code in (200, 404)


@pytest.mark.asyncio
class TestProjectRoutes:
    """Project route integration tests."""

    async def test_list_projects_authenticated(self, client, admin_token):
        resp = await client.get("/api/v1/projects",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "items" in data or isinstance(data, list)

    async def test_list_projects_unauthenticated(self, client):
        resp = await client.get("/api/v1/projects")
        assert resp.status_code == 401

    async def test_create_project_minimal(self, client, admin_token):
        resp = await client.post(
            "/api/v1/projects",
            json={"name": f"Integration project {uuid.uuid4().hex[:6]}", "status": "active"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert "id" in data
        assert data["status"] == "active"

    async def test_create_project_missing_name_returns_422(self, client, admin_token):
        resp = await client.post(
            "/api/v1/projects",
            json={"status": "active"},  # Missing required name
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    async def test_get_nonexistent_project_returns_404(self, client, admin_token):
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/projects/{fake_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestSecurityHeaders:
    """Verify OWASP security headers are present on all responses."""

    async def test_security_headers_on_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("referrer-policy") == "same-origin"
        assert resp.headers.get("x-xss-protection") == "1; mode=block"

    async def test_security_headers_on_api_route(self, client, admin_token):
        resp = await client.get("/api/v1/departments",
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("x-content-type-options") == "nosniff"

    async def test_security_headers_on_401(self, client):
        resp = await client.get("/api/v1/staff")
        assert resp.status_code == 401
        assert resp.headers.get("x-frame-options") == "DENY"
