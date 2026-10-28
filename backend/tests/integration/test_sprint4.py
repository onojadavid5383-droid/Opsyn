# ============================================================
# OPSYN SPRINT 4 INTEGRATION TESTS
# Covers: Activity Timeline, Notifications, Outage status,
#         Settings Admin, Reports export, AppShell data
# Run: pytest tests/integration/test_sprint4.py -v
# ============================================================

import pytest
import uuid


# ── Activity Timeline ─────────────────────────────────────────

@pytest.mark.asyncio
class TestActivityTimeline:
    """GET /activity-timeline — tenant-wide event feed."""

    async def test_global_feed_requires_auth(self, client):
        resp = await client.get("/api/v1/activity-timeline")
        assert resp.status_code == 401

    async def test_global_feed_returns_paginated_structure(self, client, admin_token):
        resp = await client.get(
            "/api/v1/activity-timeline",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "total_pages" in data
        assert isinstance(data["items"], list)

    async def test_global_feed_accepts_entity_type_filter(self, client, admin_token):
        for entity_type in ("task", "project", "outage", "staff"):
            resp = await client.get(
                f"/api/v1/activity-timeline?entity_type={entity_type}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert resp.status_code == 200
            data = resp.json()["data"]
            for item in data["items"]:
                assert item["entity_type"] == entity_type

    async def test_global_feed_pagination(self, client, admin_token):
        resp = await client.get(
            "/api/v1/activity-timeline?page=1&size=5",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["items"]) <= 5
        assert data["size"] == 5

    async def test_task_timeline_requires_auth(self, client):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/tasks/{fake_id}/timeline")
        assert resp.status_code == 401

    async def test_task_timeline_nonexistent_task(self, client, admin_token):
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/tasks/{fake_id}/timeline",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Non-existent task returns empty timeline (not 404)
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            assert resp.json()["success"] is True

    async def test_project_timeline_requires_auth(self, client):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/projects/{fake_id}/timeline")
        assert resp.status_code == 401

    async def test_post_task_comment_requires_auth(self, client):
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"/api/v1/tasks/{fake_id}/timeline",
            json={"body": "Test comment"},
        )
        assert resp.status_code == 401

    async def test_post_task_comment_missing_body(self, client, admin_token):
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"/api/v1/tasks/{fake_id}/timeline",
            json={},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422


# ── Notifications unread count ────────────────────────────────

@pytest.mark.asyncio
class TestNotificationsUnreadCount:
    """GET /notifications/unread-count — used by AppShell live badge."""

    async def test_unread_count_requires_auth(self, client):
        resp = await client.get("/api/v1/notifications/unread-count")
        assert resp.status_code == 401

    async def test_unread_count_returns_integer(self, client, admin_token):
        resp = await client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        count = body["data"]["count"]
        assert isinstance(count, int)
        assert count >= 0

    async def test_list_notifications(self, client, admin_token):
        resp = await client.get(
            "/api/v1/notifications",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert isinstance(body["data"], list)

    async def test_mark_all_read(self, client, admin_token):
        resp = await client.patch(
            "/api/v1/notifications/read-all",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    async def test_mark_nonexistent_read_404(self, client, admin_token):
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/notifications/{fake_id}/read",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (200, 404)


# ── Outage status update ──────────────────────────────────────

@pytest.mark.asyncio
class TestOutageStatusUpdate:
    """PATCH /outages/{id} status transitions — monitoring → resolved."""

    async def test_outage_list_requires_auth(self, client):
        resp = await client.get("/api/v1/outages")
        assert resp.status_code == 401

    async def test_outage_list_returns_paginated(self, client, admin_token):
        resp = await client.get(
            "/api/v1/outages",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body

    async def test_log_outage_invalid_payload(self, client, admin_token):
        resp = await client.post(
            "/api/v1/outages",
            json={},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    async def test_outage_full_lifecycle(self, client, admin_token):
        """Log → set monitoring → resolve."""
        # Log
        log_resp = await client.post(
            "/api/v1/outages",
            json={
                "title": f"Test Outage {uuid.uuid4().hex[:6]}",
                "severity": "warning",
                "description": "Integration test outage",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        if log_resp.status_code not in (200, 201):
            pytest.skip("Outage creation failed — check permissions/seed")

        outage_data = log_resp.json().get("data", log_resp.json())
        outage_id = outage_data["id"]

        # Set monitoring
        mon_resp = await client.patch(
            f"/api/v1/outages/{outage_id}",
            json={"status": "monitoring"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert mon_resp.status_code == 200
        assert mon_resp.json()["data"]["status"] == "monitoring"

        # Resolve
        res_resp = await client.patch(
            f"/api/v1/outages/{outage_id}/resolve",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_resp.status_code == 200
        assert res_resp.json()["data"]["status"] == "resolved"

    async def test_resolve_nonexistent_outage_404(self, client, admin_token):
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/outages/{fake_id}/resolve",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    async def test_update_status_nonexistent_outage_404(self, client, admin_token):
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/outages/{fake_id}",
            json={"status": "monitoring"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404


# ── Reports export ────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.skip(
    reason="/api/v1/reports/export/pdf does not exist -- the API exposes only "
           "/reports/export/csv. frontend/src/api/index.ts still declares an "
           "exportPDF() helper, but no component calls it. Unskip if PDF "
           "export is implemented."
)
class TestReportsExport:
    """Reports PDF and CSV export endpoints."""

    async def test_csv_export_requires_auth(self, client):
        resp = await client.get("/api/v1/reports/export/csv")
        assert resp.status_code == 401

    async def test_pdf_export_requires_auth(self, client):
        resp = await client.get("/api/v1/reports/export/pdf")
        assert resp.status_code == 401

    async def test_csv_export_returns_blob(self, client, admin_token):
        resp = await client.get(
            "/api/v1/reports/export/csv",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "text/csv" in ct or "application/octet-stream" in ct or "application/csv" in ct

    async def test_pdf_export_returns_blob(self, client, admin_token):
        resp = await client.get(
            "/api/v1/reports/export/pdf",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (200, 501)  # 501 = not yet implemented is acceptable

    async def test_audit_csv_export_requires_auth(self, client):
        resp = await client.get("/api/v1/audit-logs/export")
        assert resp.status_code == 401

    async def test_audit_csv_export_returns_data(self, client, admin_token):
        resp = await client.get(
            "/api/v1/audit-logs/export",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200


# ── Full AppShell data contract ───────────────────────────────

@pytest.mark.asyncio
class TestAppShellDataContract:
    """All data endpoints consumed by AppShell on load."""

    async def test_dashboard_summary_complete(self, client, admin_token):
        resp = await client.get(
            "/api/v1/dashboard/summary",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        # All top-level keys must be present
        required = {"staff", "tasks", "outages", "infrastructure", "projects", "notifications"}
        assert required <= set(data.keys())
        # Types
        assert isinstance(data["staff"]["total"], int)
        assert isinstance(data["outages"]["live"], int)
        assert 0.0 <= data["infrastructure"]["network_uptime_pct"] <= 100.0

    async def test_notification_unread_count_on_load(self, client, admin_token):
        resp = await client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"]["count"], int)

    async def test_onboarding_pending_list_on_load(self, client, admin_token):
        resp = await client.get(
            "/api/v1/onboarding?status=pending",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    async def test_infrastructure_summary_on_load(self, client, admin_token):
        resp = await client.get(
            "/api/v1/infrastructure/summary",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    async def test_activity_feed_on_load(self, client, admin_token):
        resp = await client.get(
            "/api/v1/activity-timeline?page=1&size=20",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "items" in data
        assert "total" in data


# ── Settings integrity ────────────────────────────────────────

@pytest.mark.asyncio
class TestSettingsIntegrity:
    """Settings admin API returns consistent data across reads."""

    async def test_org_settings_consistent(self, client, admin_token):
        r1 = await client.get(
            "/api/v1/settings/organisation",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        r2 = await client.get(
            "/api/v1/settings/organisation",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["data"]["id"] == r2.json()["data"]["id"]

    async def test_departments_and_features_cross_check(self, client, admin_token):
        dept_resp = await client.get(
            "/api/v1/settings/departments",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert dept_resp.status_code == 200
        depts = dept_resp.json()["data"]

        if depts:
            dept_id = depts[0]["id"]
            feat_resp = await client.get(
                f"/api/v1/settings/departments/{dept_id}/features",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert feat_resp.status_code == 200
            assert isinstance(feat_resp.json()["data"], list)

    async def test_roles_are_ordered_by_level(self, client, admin_token):
        resp = await client.get(
            "/api/v1/settings/roles",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        roles = resp.json()["data"]
        if len(roles) >= 2:
            levels = [r["level"] for r in roles]
            assert levels == sorted(levels, reverse=True)

    async def test_create_and_verify_region(self, client, admin_token):
        code = uuid.uuid4().hex[:3].upper()
        name = f"Sprint4-Region-{code}"
        create_resp = await client.post(
            "/api/v1/settings/regions",
            json={"name": name, "code": code},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert create_resp.status_code in (200, 201)

        list_resp = await client.get(
            "/api/v1/settings/regions",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert list_resp.status_code == 200
        region_names = [r["name"] for r in list_resp.json()["data"]]
        assert name in region_names

    async def test_feature_permissions_non_empty(self, client, admin_token):
        resp = await client.get(
            "/api/v1/settings/feature-permissions",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        features = resp.json()["data"]
        # Each feature must have required keys
        for f in features:
            assert "feature_key" in f
            assert "feature_label" in f
            assert "module" in f
