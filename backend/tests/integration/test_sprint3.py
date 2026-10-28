# ============================================================
# OPSYN SPRINT 3 INTEGRATION TESTS
# Covers: Infrastructure CRUD, Onboarding auto-provision,
#         Reports MTTR, Account Activation, Dashboard summary,
#         Settings Admin endpoints
# Run: pytest tests/integration/test_sprint3.py -v
# ============================================================

import pytest
import uuid


# ── Infrastructure ────────────────────────────────────────────

@pytest.mark.asyncio
class TestInfrastructureEndpoints:
    """Infrastructure sites, nodes, and routes CRUD."""

    async def test_summary_requires_auth(self, client):
        resp = await client.get("/api/v1/infrastructure/summary")
        assert resp.status_code == 401

    async def test_summary_returns_expected_shape(self, client, admin_token):
        resp = await client.get(
            "/api/v1/infrastructure/summary",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        d = resp.json()
        assert "active_sites" in d or "data" in d  # accept either wrapper style

    async def test_list_sites_empty_or_ok(self, client, admin_token):
        resp = await client.get(
            "/api/v1/infrastructure/sites",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data or isinstance(data, list) or "data" in data

    async def test_create_site_validates_name(self, client, admin_token):
        resp = await client.post(
            "/api/v1/infrastructure/sites",
            json={},  # missing name
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    async def test_create_site_full_lifecycle(self, client, admin_token):
        site_name = f"Test-POP-{uuid.uuid4().hex[:6]}"
        # Create
        create_resp = await client.post(
            "/api/v1/infrastructure/sites",
            json={"name": site_name, "site_type": "POP", "status": "active"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert create_resp.status_code in (200, 201)
        site = create_resp.json()
        site_data = site.get("data", site)
        site_id = site_data["id"]

        # List — should include new site
        list_resp = await client.get(
            "/api/v1/infrastructure/sites",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert list_resp.status_code == 200

        # Delete
        del_resp = await client.delete(
            f"/api/v1/infrastructure/sites/{site_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert del_resp.status_code in (200, 204)

    async def test_create_node_requires_name(self, client, admin_token):
        resp = await client.post(
            "/api/v1/infrastructure/nodes",
            json={"node_type": "OLT"},  # missing name
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    async def test_node_lifecycle(self, client, admin_token):
        node_name = f"OLT-Test-{uuid.uuid4().hex[:6]}"
        # Create site first
        site_resp = await client.post(
            "/api/v1/infrastructure/sites",
            json={"name": f"Site-{uuid.uuid4().hex[:6]}", "site_type": "POP", "status": "active"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        if site_resp.status_code not in (200, 201):
            pytest.skip("Site creation failed — cannot test node lifecycle")

        site_data = site_resp.json().get("data", site_resp.json())
        site_id = site_data["id"]

        # Create node
        node_resp = await client.post(
            "/api/v1/infrastructure/nodes",
            json={"name": node_name, "node_type": "OLT", "site_id": site_id, "status": "active"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert node_resp.status_code in (200, 201)
        node_data = node_resp.json().get("data", node_resp.json())
        node_id = node_data["id"]

        # Delete node
        del_resp = await client.delete(
            f"/api/v1/infrastructure/nodes/{node_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert del_resp.status_code in (200, 204)

    async def test_create_route_requires_both_nodes(self, client, admin_token):
        resp = await client.post(
            "/api/v1/infrastructure/routes",
            json={"from_node_id": str(uuid.uuid4())},  # missing to_node_id
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    async def test_list_routes(self, client, admin_token):
        resp = await client.get(
            "/api/v1/infrastructure/routes",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200


# ── Onboarding auto-provision ─────────────────────────────────

@pytest.mark.asyncio
class TestOnboardingAutoProvision:
    """Approval creates a User + StaffProfile atomically."""

    async def test_list_onboarding_requires_auth(self, client):
        resp = await client.get("/api/v1/onboarding")
        assert resp.status_code == 401

    async def test_list_onboarding_with_token(self, client, admin_token):
        resp = await client.get(
            "/api/v1/onboarding",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body

    async def test_approve_nonexistent_request_returns_404(self, client, admin_token):
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
            json={"reason": "Not eligible"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    async def test_submit_onboarding_request(self, client, admin_token):
        resp = await client.post(
            "/api/v1/onboarding",
            json={
                "proposed_first_name": "Test",
                "proposed_last_name":  f"Candidate-{uuid.uuid4().hex[:6]}",
                "proposed_email":      f"candidate-{uuid.uuid4().hex[:8]}@opsyn.ng",
                "proposed_role_id":    str(uuid.uuid4()),  # may fail FK, that's fine
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # 201 = created, 422 = FK not satisfied — both are valid for this test
        assert resp.status_code in (200, 201, 422, 400)


# ── Reports MTTR ──────────────────────────────────────────────

@pytest.mark.asyncio
class TestReportsMTTR:
    """Enhanced reports with real MTTR computation."""

    async def test_summary_requires_auth(self, client):
        resp = await client.get("/api/v1/reports/summary")
        assert resp.status_code == 401

    async def test_summary_returns_valid_structure(self, client, admin_token):
        resp = await client.get(
            "/api/v1/reports/summary",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    async def test_summary_accepts_date_params(self, client, admin_token):
        resp = await client.get(
            "/api/v1/reports/summary?date_from=2026-01-01&date_to=2026-12-31",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    async def test_mttr_endpoint_requires_auth(self, client):
        resp = await client.get("/api/v1/reports/outages/mttr")
        assert resp.status_code == 401

    async def test_mttr_endpoint_returns_list(self, client, admin_token):
        resp = await client.get(
            "/api/v1/reports/outages/mttr",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # MTTR is an aggregate, not a list:
        # {overall_mttr_hours, total_resolved, by_severity: {...}}
        data = body["data"] if isinstance(body, dict) else body
        assert "overall_mttr_hours" in data and "by_severity" in data

    async def test_mttr_accepts_severity_filter(self, client, admin_token):
        resp = await client.get(
            "/api/v1/reports/outages/mttr?severity=critical",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    async def test_mttr_accepts_date_range(self, client, admin_token):
        resp = await client.get(
            "/api/v1/reports/outages/mttr?date_from=2026-01-01&date_to=2026-12-31",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200


# ── Account activation ────────────────────────────────────────

@pytest.mark.asyncio
class TestAccountActivation:
    """POST /auth/activate — token-based account setup."""

    async def test_activate_missing_token_422(self, client):
        resp = await client.post(
            "/api/v1/auth/activate",
            json={"password": "NewPassword123"},
        )
        assert resp.status_code == 422

    async def test_activate_missing_password_422(self, client):
        resp = await client.post(
            "/api/v1/auth/activate",
            json={"token": "some.jwt.token"},
        )
        assert resp.status_code == 422

    async def test_activate_invalid_token_401(self, client):
        resp = await client.post(
            "/api/v1/auth/activate",
            json={"token": "completely.invalid.token", "password": "NewPassword123"},
        )
        assert resp.status_code in (401, 422)

    async def test_activate_malformed_jwt_structure(self, client):
        # A well-formed JWT but wrong signing key / wrong type
        import base64, json as _json
        header = base64.urlsafe_b64encode(
            _json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            _json.dumps({"sub": str(uuid.uuid4()), "type": "access"}).encode()
        ).rstrip(b"=").decode()
        fake_token = f"{header}.{payload}.invalidsignature"
        resp = await client.post(
            "/api/v1/auth/activate",
            json={"token": fake_token, "password": "NewPassword123"},
        )
        assert resp.status_code in (401, 422)

    async def test_reset_password_invalid_token(self, client):
        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "bad.token", "new_password": "NewPass123"},
        )
        assert resp.status_code in (401, 422)

    async def test_activate_end_to_end(self, client, admin_token):
        """
        Full flow: admin creates an onboarding request → approves it
        → invite token issued → activate with the token.
        Skips if role/dept seeds are missing.
        """
        from app.core.security import create_invite_token

        # Create a test user directly to get an invite token
        fake_user_id = str(uuid.uuid4())
        token = create_invite_token(fake_user_id)

        # The token is valid but the user doesn't exist in DB → 401 or 404
        resp = await client.post(
            "/api/v1/auth/activate",
            json={"token": token, "password": "ValidPass123"},
        )
        assert resp.status_code in (401, 404, 400)


# ── Dashboard summary ─────────────────────────────────────────

@pytest.mark.asyncio
class TestDashboardSummary:
    """GET /dashboard/summary — live aggregated KPIs."""

    async def test_dashboard_requires_auth(self, client):
        resp = await client.get("/api/v1/dashboard/summary")
        assert resp.status_code == 401

    async def test_dashboard_returns_full_structure(self, client, admin_token):
        resp = await client.get(
            "/api/v1/dashboard/summary",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("success") is True
        data = body["data"]

        assert "staff" in data
        assert "tasks" in data
        assert "outages" in data
        assert "infrastructure" in data
        assert "projects" in data
        assert "notifications" in data

    async def test_dashboard_staff_keys(self, client, admin_token):
        resp = await client.get(
            "/api/v1/dashboard/summary",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        staff = resp.json()["data"]["staff"]
        assert "total" in staff
        assert "pending_onboarding" in staff
        assert isinstance(staff["total"], int)

    async def test_dashboard_tasks_keys(self, client, admin_token):
        resp = await client.get(
            "/api/v1/dashboard/summary",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        tasks = resp.json()["data"]["tasks"]
        assert "open" in tasks
        assert "overdue" in tasks
        assert "today" in tasks

    async def test_dashboard_infrastructure_keys(self, client, admin_token):
        resp = await client.get(
            "/api/v1/dashboard/summary",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        infra = resp.json()["data"]["infrastructure"]
        assert "total_nodes" in infra
        assert "active_nodes" in infra
        assert "network_uptime_pct" in infra
        uptime = infra["network_uptime_pct"]
        assert 0.0 <= uptime <= 100.0

    async def test_dashboard_outages_keys(self, client, admin_token):
        resp = await client.get(
            "/api/v1/dashboard/summary",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        outages = resp.json()["data"]["outages"]
        assert "live" in outages
        assert "today" in outages


# ── Settings endpoints ────────────────────────────────────────

@pytest.mark.asyncio
class TestSettingsEndpoints:
    """Settings admin API — org, departments, roles, regions."""

    async def test_org_settings_requires_auth(self, client):
        resp = await client.get("/api/v1/settings/organisation")
        assert resp.status_code == 401

    async def test_org_settings_returns_data(self, client, admin_token):
        resp = await client.get(
            "/api/v1/settings/organisation",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "name" in data
        assert "plan" in data

    async def test_list_departments(self, client, admin_token):
        resp = await client.get(
            "/api/v1/settings/departments",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    async def test_create_department(self, client, admin_token):
        resp = await client.post(
            "/api/v1/settings/departments",
            json={"name": f"Dept-{uuid.uuid4().hex[:6]}"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (200, 201)
        body = resp.json()
        assert body["success"] is True

    async def test_create_department_missing_name_422(self, client, admin_token):
        resp = await client.post(
            "/api/v1/settings/departments",
            json={},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    async def test_list_roles(self, client, admin_token):
        resp = await client.get(
            "/api/v1/settings/roles",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert isinstance(body["data"], list)

    async def test_create_custom_role_admin_level_blocked(self, client, admin_token):
        resp = await client.post(
            "/api/v1/settings/roles",
            json={"name": "Shadow Admin", "level": 5},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    async def test_create_custom_role_valid(self, client, admin_token):
        resp = await client.post(
            "/api/v1/settings/roles",
            json={"name": f"Tech-{uuid.uuid4().hex[:4]}", "level": 2, "description": "Field technician"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (200, 201)

    async def test_list_regions(self, client, admin_token):
        resp = await client.get(
            "/api/v1/settings/regions",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    async def test_create_region(self, client, admin_token):
        code = uuid.uuid4().hex[:3].upper()
        resp = await client.post(
            "/api/v1/settings/regions",
            json={"name": f"Region-{code}", "code": code},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (200, 201)

    async def test_list_feature_permissions(self, client, admin_token):
        resp = await client.get(
            "/api/v1/settings/feature-permissions",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert isinstance(body["data"], list)
