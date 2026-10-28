# ============================================================
# OPSYN S4.4 INTEGRATION TESTS
# Covers:
#   - Infrastructure CRUD (sites, nodes, routes, subscribers)
#   - Auth flows (login, register-tenant, refresh, logout)
#   - Shifts CRUD + swap requests
#   - Capacity monitor endpoints (monitoring configs, alert rules)
#   - Notifications + reports (infra, shifts, SLA)
# Run: pytest tests/integration/test_s44.py -v
# ============================================================

import pytest
import uuid


# ── Infrastructure ────────────────────────────────────────────

@pytest.mark.asyncio
class TestInfrastructure:
    """CRUD for sites, nodes, routes, and subscriber endpoints."""

    async def test_sites_list_requires_auth(self, client):
        resp = await client.get("/api/v1/infrastructure/sites")
        assert resp.status_code == 401

    async def test_sites_list_returns_list(self, client, admin_token):
        resp = await client.get(
            "/api/v1/infrastructure/sites",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["items"], list)

    async def test_site_create_and_retrieve(self, client, admin_token):
        name = f"TestPOP-{uuid.uuid4().hex[:6]}"
        create_resp = await client.post(
            "/api/v1/infrastructure/sites",
            json={"name": name, "site_type": "POP", "status": "active"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert create_resp.status_code in (200, 201), create_resp.text
        site = create_resp.json()          # bare object, not enveloped
        assert site["name"] == name

        get_resp = await client.get(
            f"/api/v1/infrastructure/sites/{site['id']}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == site["id"]

    async def test_site_update(self, client, admin_token):
        name = f"TestSite-{uuid.uuid4().hex[:6]}"
        c = await client.post(
            "/api/v1/infrastructure/sites",
            json={"name": name, "site_type": "POP", "status": "active"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        if c.status_code not in (200, 201):
            pytest.skip("Site creation failed")
        site_id = c.json()["id"]

        upd = await client.put(
            f"/api/v1/infrastructure/sites/{site_id}",
            json={"status": "maintenance"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert upd.status_code == 200
        assert upd.json()["status"] == "maintenance"

    async def test_site_not_found(self, client, admin_token):
        resp = await client.get(
            f"/api/v1/infrastructure/sites/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    async def test_nodes_list(self, client, admin_token):
        resp = await client.get(
            "/api/v1/infrastructure/nodes",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json()["items"], list)

    async def test_node_create(self, client, admin_token):
        name = f"OLT-{uuid.uuid4().hex[:6]}"
        resp = await client.post(
            "/api/v1/infrastructure/nodes",
            json={"name": name, "node_type": "OLT", "status": "active"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (200, 201), resp.text
        assert resp.json()["name"] == name

    async def test_routes_list(self, client, admin_token):
        resp = await client.get(
            "/api/v1/infrastructure/routes",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    async def test_subscribers_list(self, client, admin_token):
        resp = await client.get(
            "/api/v1/infrastructure/subscribers",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)   # bare list, not paginated

    async def test_subscribers_filter_by_service_type(self, client, admin_token):
        for stype in ("FTTH", "FTTB", "FTTC"):
            resp = await client.get(
                f"/api/v1/infrastructure/subscribers?service_type={stype}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert resp.status_code == 200
            for s in resp.json():
                assert s["service_type"] == stype

    async def test_sync_ports_queued(self, client, admin_token):
        resp = await client.post(
            "/api/v1/infrastructure/sync-ports",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (200, 202)
        body = resp.json()
        assert body.get("queued") is True or body.get("success") is True

    async def test_infra_summary(self, client, admin_token):
        resp = await client.get(
            "/api/v1/infrastructure/summary",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()   # bare object
        assert "active_sites" in data or "sites" in data


# ── Auth Flows ────────────────────────────────────────────────

@pytest.mark.asyncio
class TestAuthFlows:
    """Login, register-tenant, refresh, and logout."""

    async def test_login_invalid_password(self, client):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "admin@opsyn.ng", "password": "wrong-password",
        })
        assert resp.status_code == 401

    async def test_login_invalid_email(self, client):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "nonexistent@example.com", "password": "any-pass",
        })
        assert resp.status_code == 401

    async def test_login_missing_fields(self, client):
        resp = await client.post("/api/v1/auth/login", json={"email": "x@y.com"})
        assert resp.status_code == 422

    async def test_register_tenant_creates_workspace(self, client):
        slug = f"test-org-{uuid.uuid4().hex[:8]}"
        resp = await client.post("/api/v1/auth/register-tenant", json={
            "org_name":   f"Test Org {slug}",
            "slug":       slug,
            "first_name": "Jane",
            "last_name":  "Admin",
            "email":      f"{slug}@example.com",
            "password":   "securepass123",
        })
        assert resp.status_code in (200, 201), resp.text
        data = resp.json()["data"]
        assert "access_token" in data
        assert data["tenant"]["slug"] == slug
        assert data["user"]["email"] == f"{slug}@example.com"

    async def test_register_tenant_duplicate_slug(self, client):
        slug = f"dup-slug-{uuid.uuid4().hex[:8]}"
        payload = {
            "org_name": "Dupe Org", "slug": slug,
            "first_name": "A", "last_name": "B",
            "email": f"{slug}@example.com", "password": "pass12345",
        }
        r1 = await client.post("/api/v1/auth/register-tenant", json=payload)
        assert r1.status_code in (200, 201)

        payload["email"] = f"{slug}2@example.com"
        r2 = await client.post("/api/v1/auth/register-tenant", json=payload)
        assert r2.status_code == 409

    async def test_register_tenant_duplicate_email(self, client):
        email = f"dup-email-{uuid.uuid4().hex[:8]}@example.com"
        r1 = await client.post("/api/v1/auth/register-tenant", json={
            "org_name": "Org1", "slug": f"org1-{uuid.uuid4().hex[:8]}",
            "first_name": "A", "last_name": "B",
            "email": email, "password": "pass12345",
        })
        assert r1.status_code in (200, 201)

        r2 = await client.post("/api/v1/auth/register-tenant", json={
            "org_name": "Org2", "slug": f"org2-{uuid.uuid4().hex[:8]}",
            "first_name": "A", "last_name": "B",
            "email": email, "password": "pass12345",
        })
        assert r2.status_code == 409

    async def test_register_tenant_short_password(self, client):
        resp = await client.post("/api/v1/auth/register-tenant", json={
            "org_name": "TinyOrg", "slug": f"tiny-{uuid.uuid4().hex[:8]}",
            "first_name": "A", "last_name": "B",
            "email": f"tiny-{uuid.uuid4().hex[:6]}@ex.com", "password": "short",
        })
        assert resp.status_code == 422

    async def test_register_tenant_invalid_slug(self, client):
        resp = await client.post("/api/v1/auth/register-tenant", json={
            "org_name": "BadSlug", "slug": "NO SPACES!",
            "first_name": "A", "last_name": "B",
            "email": f"bad-{uuid.uuid4().hex[:6]}@ex.com", "password": "pass12345",
        })
        assert resp.status_code == 422

    async def test_refresh_without_cookie_401(self, client):
        resp = await client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401

    async def test_logout_requires_auth(self, client):
        resp = await client.post("/api/v1/auth/logout")
        assert resp.status_code == 401

    async def test_logout_success(self, client, admin_token):
        resp = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── Shifts ────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestShifts:
    """Shift CRUD and swap request flows."""

    async def test_shifts_list_requires_auth(self, client):
        resp = await client.get("/api/v1/shifts")
        assert resp.status_code == 401

    async def test_shifts_list_returns_list(self, client, admin_token):
        resp = await client.get(
            "/api/v1/shifts",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    async def test_shift_assignments_list(self, client, admin_token):
        resp = await client.get(
            "/api/v1/shifts/assignments",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    async def test_swap_requests_list(self, client, admin_token):
        resp = await client.get(
            "/api/v1/shifts/swap-requests",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    async def test_create_shift_missing_fields(self, client, admin_token):
        resp = await client.post(
            "/api/v1/shifts",
            json={},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    async def test_swap_approve_nonexistent(self, client, admin_token):
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/shifts/swap-requests/{fake_id}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (404, 422)


# ── Capacity Monitor ──────────────────────────────────────────

@pytest.mark.asyncio
class TestCapacityMonitor:
    """Monitoring configs, alert rules, and capacity alerts."""

    async def test_monitoring_configs_list_requires_auth(self, client):
        resp = await client.get("/api/v1/settings/infrastructure/monitoring")
        assert resp.status_code == 401

    async def test_monitoring_configs_list(self, client, admin_token):
        resp = await client.get(
            "/api/v1/settings/infrastructure/monitoring",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    async def test_create_monitoring_config(self, client, admin_token):
        resp = await client.post(
            "/api/v1/settings/infrastructure/monitoring",
            json={
                "entity_type":       "node",
                "entity_id":         str(uuid.uuid4()),
                "warn_threshold_pct":     80,
                "critical_threshold_pct": 95,
                "check_interval_minutes": 15,
                "is_active":         True,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (200, 201), resp.text
        data = resp.json()["data"]
        assert data["warn_threshold_pct"] == 80

    async def test_alert_rules_list(self, client, admin_token):
        resp = await client.get(
            "/api/v1/settings/infrastructure/alert-rules",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    async def test_create_alert_rule(self, client, admin_token):
        resp = await client.post(
            "/api/v1/settings/infrastructure/alert-rules",
            json={
                "name":            f"Rule-{uuid.uuid4().hex[:6]}",
                "condition_field": "utilisation_pct",
                "operator":        "gt",
                "threshold_value": 90,
                "severity":        "critical",
                "action_type":     "notify",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (200, 201), resp.text

    async def test_capacity_alerts_list(self, client, admin_token):
        resp = await client.get(
            "/api/v1/infrastructure/capacity-alerts",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    @pytest.mark.skip(
        reason="No collection endpoint for ports. The API exposes only "
               "/infrastructure/ports/{port_id} and "
               "/infrastructure/nodes/{node_id}/ports. Unskip if a list "
               "endpoint is added."
    )
    async def test_ports_list(self, client, admin_token):
        resp = await client.get(
            "/api/v1/infrastructure/ports",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200


# ── Reports (S4.4 additions) ──────────────────────────────────

@pytest.mark.asyncio
class TestS44Reports:
    """Infrastructure, shifts, and SLA report endpoints."""

    async def test_infra_report_requires_auth(self, client):
        resp = await client.get("/api/v1/reports/infrastructure")
        assert resp.status_code == 401

    async def test_infra_report_returns_structure(self, client, admin_token):
        resp = await client.get(
            "/api/v1/reports/infrastructure",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "sites" in data
        assert "alert_summary" in data
        assert "recent_alerts" in data
        assert isinstance(data["recent_alerts"], list)

    async def test_shifts_report_requires_auth(self, client):
        resp = await client.get("/api/v1/reports/shifts")
        assert resp.status_code == 401

    async def test_shifts_report_returns_structure(self, client, admin_token):
        resp = await client.get(
            "/api/v1/reports/shifts",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "coverage" in data
        assert "oncall_load" in data
        assert "swap_requests" in data

    async def test_sla_report_requires_auth(self, client):
        resp = await client.get("/api/v1/reports/sla")
        assert resp.status_code == 401

    async def test_sla_report_returns_structure(self, client, admin_token):
        resp = await client.get(
            "/api/v1/reports/sla",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "by_severity" in data
        assert "worst_olts" in data

    async def test_staff_performance_endpoint(self, client, admin_token):
        """GET /staff/{id}/performance — requires valid staff id or returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/staff/{fake_id}/performance",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            data = resp.json()["data"]
            assert "completion_rate_pct" in data
            assert "sla_adherence_pct" in data

    async def test_staff_report_requires_auth(self, client):
        resp = await client.get("/api/v1/reports/staff/breakdown")
        assert resp.status_code == 401

    async def test_tasks_report_requires_auth(self, client):
        resp = await client.get("/api/v1/reports/tasks/breakdown")
        assert resp.status_code == 401

    async def test_overview_report_returns_structure(self, client, admin_token):
        resp = await client.get(
            "/api/v1/reports/summary",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert isinstance(data, dict)
