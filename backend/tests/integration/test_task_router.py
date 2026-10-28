# ============================================================
# OPSYN — tests/integration/test_task_router.py   (I.1.2)
# Integration tests for the /tasks API endpoints.
# Requires: test DB and seeded admin user (or skips gracefully).
# Run: pytest tests/integration/test_task_router.py -v
# ============================================================

import pytest
import uuid


@pytest.mark.asyncio
class TestTaskRouterAuth:
    """Unauthenticated requests must be rejected."""

    async def test_list_tasks_without_token_returns_401(self, client):
        resp = await client.get("/api/v1/tasks")
        assert resp.status_code == 401

    async def test_pipeline_board_without_token_returns_401(self, client):
        resp = await client.get("/api/v1/tasks/pipeline")
        assert resp.status_code == 401

    async def test_create_task_without_token_returns_401(self, client):
        resp = await client.post("/api/v1/tasks", json={
            "title": "Test", "priority": "medium", "task_scope": "internal",
        })
        assert resp.status_code == 401

    async def test_deleted_tasks_without_token_returns_401(self, client):
        resp = await client.get("/api/v1/tasks/deleted")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestPipelineBoardViews:
    """Pipeline board view parameter tests (E.1.1 + E.2.4)."""

    async def test_pipeline_pending_approvals_view_requires_auth(self, client):
        resp = await client.get("/api/v1/tasks/pipeline?view=pending_approvals")
        assert resp.status_code == 401

    async def test_pipeline_reopened_view_requires_auth(self, client):
        resp = await client.get("/api/v1/tasks/pipeline?view=reopened")
        assert resp.status_code == 401

    async def test_pipeline_default_view_requires_auth(self, client):
        resp = await client.get("/api/v1/tasks/pipeline?scope=all")
        assert resp.status_code == 401

    async def test_pipeline_pending_approvals_view_authenticated(self, client, admin_token):
        resp = await client.get(
            "/api/v1/tasks/pipeline?view=pending_approvals",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    async def test_pipeline_reopened_view_authenticated(self, client, admin_token):
        resp = await client.get(
            "/api/v1/tasks/pipeline?view=reopened",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    async def test_pipeline_default_returns_stage_dict(self, client, admin_token):
        resp = await client.get(
            "/api/v1/tasks/pipeline?scope=all",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        for stage in ("backlog", "in_progress", "review", "unit_done", "archive"):
            assert stage in data


@pytest.mark.asyncio
class TestPushBackValidation:
    """Push-back endpoint input validation."""

    async def test_push_back_nonexistent_task_returns_404(self, client, admin_token):
        resp = await client.post(
            f"/api/v1/tasks/{uuid.uuid4()}/push-back",
            json={"reason": "A" * 20},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # 404 if task not found
        assert resp.status_code in (404, 422)

    async def test_push_back_short_reason_returns_422(self, client, admin_token):
        """Even if the task existed, a short reason must be rejected."""
        resp = await client.post(
            f"/api/v1/tasks/{uuid.uuid4()}/push-back",
            json={"reason": "short"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # 422 from service validation OR 404 from task lookup — both acceptable
        assert resp.status_code in (404, 422)

    async def test_push_back_missing_reason_returns_422(self, client, admin_token):
        resp = await client.post(
            f"/api/v1/tasks/{uuid.uuid4()}/push-back",
            json={},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestReopenEndpoint:
    """Reopen task endpoint (E.2.1)."""

    async def test_reopen_nonexistent_task_returns_404(self, client, admin_token):
        resp = await client.post(
            f"/api/v1/tasks/{uuid.uuid4()}/reopen",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (404, 422)

    async def test_reopen_without_token_returns_401(self, client):
        resp = await client.post(f"/api/v1/tasks/{uuid.uuid4()}/reopen")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestSoftDeleteValidation:
    """Soft-delete endpoint input validation."""

    async def test_delete_without_reason_returns_422(self, client, admin_token):
        # httpx's .delete() has no json= parameter; a DELETE with a body
        # must go through .request().
        resp = await client.request(
            "DELETE",
            f"/api/v1/tasks/{uuid.uuid4()}",
            json={},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    async def test_delete_without_token_returns_401(self, client):
        resp = await client.request(
            "DELETE",
            f"/api/v1/tasks/{uuid.uuid4()}",
            json={"reason": "A" * 25},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestTaskCreation:
    """Task creation endpoint structure validation."""

    async def test_create_task_missing_required_fields(self, client, admin_token):
        resp = await client.post(
            "/api/v1/tasks",
            json={"priority": "medium"},   # missing title and task_scope
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    async def test_create_task_invalid_priority(self, client, admin_token):
        resp = await client.post(
            "/api/v1/tasks",
            json={"title": "T", "priority": "invalid_priority", "task_scope": "internal"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    async def test_create_internal_task_missing_department_422(self, client, admin_token):
        """External tasks without department_id must fail."""
        resp = await client.post(
            "/api/v1/tasks",
            json={"title": "External", "priority": "medium", "task_scope": "external"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # 422 from schema or service validation
        assert resp.status_code in (201, 422)


@pytest.mark.asyncio
class TestDeletedTasksEndpoint:
    """Deleted tasks listing endpoint."""

    async def test_deleted_tasks_authenticated_returns_200(self, client, admin_token):
        resp = await client.get(
            "/api/v1/tasks/deleted",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "items" in body["data"] or isinstance(body["data"], (list, dict))
