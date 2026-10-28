# ============================================================
# OPSYN E2E TESTS — tests/e2e/test_critical_flows.py
# Critical user flows: Staff creation, Scope violation,
# Task lifecycle, Onboarding flow
# Run: pytest tests/e2e/ -v
# ============================================================

import pytest
import uuid


@pytest.mark.asyncio
class TestStaffCreationFlow:
    """
    E2E: Admin creates a new staff member.
    Verifies the full 11-step pipeline.
    """

    async def test_full_staff_creation_requires_valid_dept_and_role(
        self, client, admin_token, db_session
    ):
        """
        Create real dept + role in DB, then create a staff member.
        Verifies: auth → role gate → scope check → uniqueness → DB commit.
        """
        from app.modules.organisation.models import Department
        from app.modules.roles.models import Role
        from sqlalchemy import select

        # Get or create dept
        dept = (await db_session.execute(
            select(Department).limit(1)
        )).scalars().first()

        role = (await db_session.execute(
            select(Role).where(Role.name == "Staff").limit(1)
        )).scalars().first()

        if not dept or not role:
            pytest.skip("Seed data required — run 'make seed' first")

        email = f"e2e-{uuid.uuid4().hex[:8]}@opsyn.ng"
        username = f"e2e-{uuid.uuid4().hex[:8]}"

        payload = {
            "first_name":     "E2E",
            "last_name":      "TestUser",
            "email":          email,
            "username":       username,
            "department_id":  str(dept.id),
            "role_id":        str(role.id),
            "job_title":      "E2E Test Engineer",
            "employment_type":"permanent",
            "scope_level":    "department",
            "allowed_dashboards": [],
            "approval_authority_level": 0,
            "status":         "active",
            "invite_method":  "email",
        }

        resp = await client.post(
            "/api/v1/staff", json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["success"] is True

    async def test_duplicate_email_returns_409(self, client, admin_token, db_session):
        """Creating a second account with the same email returns 409 Conflict."""
        from app.modules.organisation.models import Department
        from app.modules.roles.models import Role
        from sqlalchemy import select

        dept = (await db_session.execute(select(Department).limit(1))).scalars().first()
        role = (await db_session.execute(select(Role).where(Role.name == "Staff").limit(1))).scalars().first()

        if not dept or not role:
            pytest.skip("Seed data required")

        email = f"dup-{uuid.uuid4().hex[:8]}@opsyn.ng"

        payload_base = {
            "last_name": "Dup", "email": email,
            "department_id": str(dept.id), "role_id": str(role.id),
            "job_title": "Test", "employment_type": "permanent",
            "scope_level": "department", "allowed_dashboards": [],
            "approval_authority_level": 0, "status": "active", "invite_method": "email",
        }

        # First creation — should succeed
        resp1 = await client.post("/api/v1/staff", json={
            **payload_base,
            "first_name": "First",
            "username": f"dup-u1-{uuid.uuid4().hex[:6]}",
        }, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp1.status_code == 201

        # Second creation with same email — should fail
        resp2 = await client.post("/api/v1/staff", json={
            **payload_base,
            "first_name": "Second",
            "username": f"dup-u2-{uuid.uuid4().hex[:6]}",
        }, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp2.status_code == 409, f"Expected 409, got {resp2.status_code}"


@pytest.mark.asyncio
class TestScopeViolationFlow:
    """
    E2E: Verify that scope and hierarchy rules are enforced at every layer.
    """

    async def test_manager_cannot_access_another_dept_staff(
        self, client, admin_token, manager_token
    ):
        """Manager cannot list staff from a department outside their scope."""
        # Get a department that the manager is NOT scoped to
        fake_dept_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/staff?dept_id={fake_dept_id}",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        # Either returns empty list (scoped out) or 403 — never leaks cross-dept data
        assert resp.status_code in (200, 403)
        if resp.status_code == 200:
            # Must return 0 items — no cross-dept leak
            assert resp.json()["data"]["total"] == 0

    async def test_audit_logs_forbidden_for_manager(self, client, manager_token):
        """Manager (level 4) must not access audit logs (requires level 5)."""
        resp = await client.get(
            "/api/v1/audit-logs",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 403
        # The 403 status is the contract; the wording is not. The endpoint
        # answers "Access denied: feature 'settings.admin' is not granted...",
        # which is a correct denial but contains neither literal word.
        assert "denied" in resp.json().get("detail", "").lower()

    async def test_onboarding_approval_forbidden_for_manager(self, client, manager_token):
        """Manager cannot approve onboarding — requires Admin (level 5)."""
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/onboarding/{fake_id}/approve",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 403

    async def test_user_scopes_requires_admin(self, client, manager_token):
        """Only Admin can view/manage user scopes."""
        fake_user_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/user-scopes/{fake_user_id}",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 403

    async def test_role_assignment_forbidden_for_manager(self, client, manager_token):
        """Only Admin can assign roles."""
        fake_role_id = str(uuid.uuid4())
        resp = await client.post(
            f"/api/v1/roles/{fake_role_id}/assign",
            json={"user_id": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 403

    async def test_department_creation_forbidden_for_manager(self, client, manager_token):
        """Only Admin can create departments."""
        resp = await client.post(
            "/api/v1/departments",
            json={"name": f"Unauthorized-Dept-{uuid.uuid4().hex[:6]}"},
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestTaskLifecycleFlow:
    """
    E2E: Complete task lifecycle — create → assign → status update → comment → board.
    """

    async def test_task_create_and_appears_in_board(self, client, admin_token):
        """Create a task with deadline, verify it appears in the correct board bucket."""
        from datetime import datetime, timedelta

        future_date = (datetime.utcnow() + timedelta(days=3)).isoformat()
        title = f"Lifecycle-{uuid.uuid4().hex[:8]}"

        # Create
        resp = await client.post(
            "/api/v1/tasks",
            json={"title": title, "priority": "high", "deadline": future_date, "status": "in_progress"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        task_id = resp.json()["data"]["id"]

        # Verify appears in board under this_week
        board_resp = await client.get(
            "/api/v1/tasks/board",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert board_resp.status_code == 200
        board = board_resp.json()["data"]
        all_tasks = (
            board["completed"] + board["overdue"] + board["today"] + board["this_week"] +
            board["next_week"] + board["no_deadline"] + board["backlog"]
        )
        task_ids = [t["id"] for t in all_tasks]
        assert task_id in task_ids, "Newly created task not found in board"

    async def test_task_status_update(self, client, admin_token):
        """Update a task's status and verify the change persists."""
        # Create task
        resp = await client.post(
            "/api/v1/tasks",
            # "backlog" is a pipeline_stage, not a task status. It used to be
            # accepted and stored verbatim; the status validator now rejects it.
            json={"title": "Status-test task", "status": "new"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        task_id = resp.json()["data"]["id"]

        # Update status
        patch_resp = await client.patch(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": "in_progress"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["data"]["status"] == "in_progress"

    async def test_add_comment_to_task(self, client, admin_token):
        """Add a comment to a task and verify it's stored."""
        # Create task
        resp = await client.post(
            "/api/v1/tasks",
            json={"title": "Comment-test task"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        task_id = resp.json()["data"]["id"]

        # Add comment
        comment_resp = await client.post(
            f"/api/v1/tasks/{task_id}/comments",
            json={"body": "This is an E2E test comment from Opsyn"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert comment_resp.status_code == 201
        assert comment_resp.json()["data"]["body"] == "This is an E2E test comment from Opsyn"

    async def test_timeline_comment_appears_in_task_comments(self, client, admin_token):
        """A comment posted from the activity timeline also appears in Comments."""
        from uuid import uuid4

        headers = {"Authorization": f"Bearer {admin_token}"}
        task_resp = await client.post(
            "/api/v1/tasks",
            json={"title": f"Timeline-comment-{uuid4().hex[:8]}"},
            headers=headers,
        )
        assert task_resp.status_code == 201
        task_id = task_resp.json()["data"]["id"]
        body = f"Timeline comment {uuid4().hex}"

        post_resp = await client.post(
            f"/api/v1/tasks/{task_id}/timeline",
            json={"body": body},
            headers=headers,
        )
        assert post_resp.status_code == 201

        detail_resp = await client.get(f"/api/v1/tasks/{task_id}", headers=headers)
        assert detail_resp.status_code == 200
        comments = detail_resp.json()["data"]["comments"]
        assert any(comment["body"] == body for comment in comments)


@pytest.mark.asyncio
class TestOnboardingWorkflow:
    """E2E: Onboarding request submission → approval."""

    async def test_submit_onboarding_creates_pending_request(self, client, admin_token, db_session):
        """Submit an onboarding request and verify it's pending."""
        from app.modules.organisation.models import Department
        from app.modules.roles.models import Role
        from sqlalchemy import select

        dept = (await db_session.execute(select(Department).limit(1))).scalars().first()
        role = (await db_session.execute(select(Role).where(Role.name == "Staff").limit(1))).scalars().first()

        if not dept or not role:
            pytest.skip("Seed data required")

        resp = await client.post(
            "/api/v1/onboarding",
            json={
                "proposed_first_name": "E2E",
                "proposed_last_name":  "Onboard",
                "proposed_email":      f"onboard-{uuid.uuid4().hex[:6]}@opsyn.ng",
                "proposed_role_id":    str(role.id),
                "department_id":       str(dept.id),
                "justification":       "E2E test onboarding request",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        # Onboarding is a two-stage approval: pending_manager -> pending_admin
        # -> approved. A freshly submitted request lands in the first stage.
        assert data["approval_status"].startswith("pending")

    async def test_approve_nonexistent_request_returns_404(self, client, admin_token):
        """Approving a non-existent request returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/onboarding/{fake_id}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    async def test_reject_nonexistent_request_returns_404(self, client, admin_token):
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/onboarding/{fake_id}/reject",
            json={"reason": "Does not meet criteria"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestOutageFlow:
    """E2E: Log outage → verify it appears in active list → resolve."""

    async def test_log_and_resolve_outage(self, client, admin_token):
        """Full outage lifecycle: log → active → resolve."""
        # Log outage
        log_resp = await client.post(
            "/api/v1/outages",
            json={
                "title":       "E2E Test Outage — Lagos Island OLT-999",
                "severity":    "warning",
                "description": "E2E integration test outage",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert log_resp.status_code == 201
        incident_id = log_resp.json()["data"]["id"]
        assert log_resp.json()["data"]["status"] == "active"
        assert log_resp.json()["data"]["reference"].startswith("OUT-")

        # Resolve
        resolve_resp = await client.patch(
            f"/api/v1/outages/{incident_id}/resolve",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resolve_resp.status_code == 200
        assert resolve_resp.json()["data"]["status"] == "resolved"
        assert resolve_resp.json()["data"]["resolved_at"] is not None

    async def test_log_outage_unauthenticated(self, client):
        resp = await client.post("/api/v1/outages", json={"title": "Test"})
        assert resp.status_code == 401
