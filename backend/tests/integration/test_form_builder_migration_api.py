"""
Integration tests for the migration router.

These go through the real HTTP stack (routing, dependency injection,
permission checks, response envelope) rather than calling the endpoint
functions directly, because most of what can go wrong here is in the wiring:
a router that is never registered, a dependency that does not resolve, a
route that matches the wrong path.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.modules.form_builder.models import FieldDefinition, FormSchema
from app.modules.form_builder.schema_sql import (
    build_create_table,
    entity_table_name,
    split_statements,
)
from app.modules.tenants.models import Tenant


BASE = "/api/v1/form-builder"


@pytest.fixture
async def tenant(db_session):
    t = Tenant(name="API Test", slug=f"api-{uuid.uuid4().hex[:12]}")
    db_session.add(t)
    await db_session.flush()
    return t


@pytest.fixture
async def schema(db_session, tenant):
    s = FormSchema(
        tenant_id=tenant.id, name="Customer", machine_name="customer",
        module="customer", status="published", current_version=1,
    )
    db_session.add(s)
    await db_session.flush()
    return s


@pytest.fixture
async def field(db_session, schema):
    f = FieldDefinition(
        schema_id=schema.id, tenant_id=schema.tenant_id,
        field_key="customer_email", label="Email", field_type="email",
    )
    db_session.add(f)
    await db_session.flush()
    return f


@pytest.fixture
async def table(db_session, tenant, schema):
    """The dynamic table exists, so alter/delete plans are legal."""
    name = entity_table_name(tenant.id, schema.machine_name)
    forward, _ = build_create_table(name, [])
    for statement in split_statements(forward):
        await db_session.execute(text(statement))
    await db_session.flush()
    return name


@pytest.fixture
async def admin(db_session, tenant):
    """
    A real admin user, because get_current_user() loads User by the token's
    `sub`. A synthetic subject verifies fine but then 401s with
    "User not found." once the DB is consulted.
    """
    from app.modules.roles.models import Role
    from app.modules.staff.models import User

    role = Role(tenant_id=tenant.id, name="Admin", level=5, is_system_role=True)
    db_session.add(role)
    await db_session.flush()

    user = User(
        tenant_id=tenant.id,
        username=f"api-admin-{uuid.uuid4().hex[:8]}",
        email=f"api-admin-{uuid.uuid4().hex[:8]}@opsyn.test",
        password_hash="not-used-in-these-tests",
        role_id=role.id,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def auth_headers(user, tenant_id):
    from app.core.security import create_access_token
    return {"Authorization": f"Bearer {create_access_token(str(user.id), {
        'role': 'Admin', 'role_level': 5, 'tenant_id': str(tenant_id),
    })}"}


@pytest.fixture
def admin_auth(admin, tenant):
    return auth_headers(admin, tenant.id)


@pytest.fixture
def make_admin(db_session):
    """Create a real admin user in a given tenant and return auth headers."""
    from app.modules.roles.models import Role
    from app.modules.staff.models import User

    async def _make(tenant):
        role = Role(tenant_id=tenant.id, name="Admin", level=5, is_system_role=True)
        db_session.add(role)
        await db_session.flush()
        user = User(
            tenant_id=tenant.id,
            username=f"x-{uuid.uuid4().hex[:8]}",
            email=f"x-{uuid.uuid4().hex[:8]}@opsyn.test",
            password_hash="not-used",
            role_id=role.id,
        )
        db_session.add(user)
        await db_session.flush()
        return auth_headers(user, tenant.id)
    return _make


def change(field_id, action="add", **kw):
    payload = {"action": action, "field_id": str(field_id)}
    payload.update(kw)
    return payload


# ══════════════════════════════════════════════════════════════
#  PREVIEW
# ══════════════════════════════════════════════════════════════

class TestPreview:
    async def test_returns_plan_without_executing(
        self, client, admin_auth, schema, field, db_session, table
    ):
        resp = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]},
            headers=admin_auth,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert data["change_type"] == "add_column"
        assert "ADD COLUMN" in data["forward_sql"]
        assert "DROP COLUMN" in data["rollback_sql"]
        assert data["table_name"] == table
        assert data["reversible"] is True

        # The column must NOT exist yet.
        cols = await db_session.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'customer_email'"
        ), {'t': table})
        assert cols.scalar() == 0

    async def test_persists_plan_as_pending(
        self, client, admin_auth, schema, field, table
    ):
        resp = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]},
            headers=admin_auth,
        )
        mid = resp.json()["data"]["migration_id"]

        detail = await client.get(
            f"{BASE}/migrations/{mid}", headers=admin_auth
        )
        assert detail.status_code == 200
        assert detail.json()["data"]["status"] == "pending"

    async def test_rejects_empty_change_list(
        self, client, admin_auth, schema
    ):
        resp = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": []}, headers=admin_auth,
        )
        assert resp.status_code == 422

    async def test_can_plan_a_drop_after_the_field_is_soft_deleted(
        self, client, admin_auth, schema, field, table, db_session
    ):
        """
        The builder discovers removals by diffing against the published
        snapshot, which only happens after the delete has already soft-deleted
        the row. So a DROP has to be plannable from an inactive field -- the
        alternative is that a removed field can never have its column dropped
        at all.
        """
        field.is_deleted = True
        await db_session.flush()

        resp = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id, action="delete")]},
            headers=admin_auth,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["change_type"] == "drop_column"
        assert "DROP COLUMN" in data["forward_sql"]
        # Dropping loses the values, so it must never be advertised as
        # reversible or safe to undo.
        assert data["reversible"] is False
        assert data["is_destructive"] is True
        assert data["warnings"], "a destructive plan must warn before it is run"

    async def test_soft_deleted_field_is_still_404_for_add(
        self, client, admin_auth, schema, field, db_session
    ):
        """
        allow_deleted is for drops only. An 'add' against an inactive field
        would build a plan for a column the builder has already retired.
        """
        field.is_deleted = True
        await db_session.flush()

        resp = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id, action="add")]},
            headers=admin_auth,
        )
        assert resp.status_code == 404

    async def test_rejects_unknown_action(self, client, admin_auth, schema, field):
        resp = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id, action="frobnicate")]},
            headers=admin_auth,
        )
        assert resp.status_code == 422

    async def test_rejects_duplicate_field_in_one_request(
        self, client, admin_auth, schema, field
    ):
        resp = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id), change(field.id, action="delete")]},
            headers=admin_auth,
        )
        assert resp.status_code == 422

    async def test_unknown_schema_is_404(self, client, admin_auth):
        resp = await client.post(
            f"{BASE}/schemas/{uuid.uuid4()}/migrations/preview",
            json={"changes": [change(uuid.uuid4())]}, headers=admin_auth,
        )
        assert resp.status_code == 404

    async def test_field_from_another_schema_is_404(
        self, client, admin_auth, schema, field, db_session
    ):
        other = FieldDefinition(
            schema_id=schema.id, tenant_id=schema.tenant_id,
            field_key="stray", label="Stray", field_type="string",
        )
        db_session.add(other)
        await db_session.flush()
        # Point the request at a schema that does not own this field.
        other_schema = FormSchema(
            tenant_id=schema.tenant_id, name="Other", machine_name="other",
            module="generic", status="published", current_version=1,
        )
        db_session.add(other_schema)
        await db_session.flush()

        resp = await client.post(
            f"{BASE}/schemas/{other_schema.id}/migrations/preview",
            json={"changes": [change(field.id)]}, headers=admin_auth,
        )
        assert resp.status_code == 404

    async def test_requires_authentication(self, client, schema, field):
        resp = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]},
        )
        assert resp.status_code in (401, 403)

    async def test_cross_tenant_schema_is_404(
        self, client, db_session, make_admin, schema, field
    ):
        """A valid token for another tenant must not see this schema."""
        intruder = Tenant(name="Intruder", slug=f"int-{uuid.uuid4().hex[:12]}")
        db_session.add(intruder)
        await db_session.flush()

        resp = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]},
            headers=await make_admin(intruder),
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════
#  APPLY
# ══════════════════════════════════════════════════════════════

class TestApply:
    async def test_preview_then_apply(
        self, client, admin_auth, schema, field, db_session, table
    ):
        preview = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]}, headers=admin_auth,
        )
        mid = preview.json()["data"]["migration_id"]

        applied = await client.post(
            f"{BASE}/migrations/{mid}/apply", headers=admin_auth
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["data"]["columns_added"] == ["customer_email"]

        cols = await db_session.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'customer_email'"
        ), {'t': table})
        assert cols.scalar() == 1

    async def test_cannot_apply_twice(self, client, admin_auth, schema, field, table):
        preview = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]}, headers=admin_auth,
        )
        mid = preview.json()["data"]["migration_id"]

        assert (await client.post(
            f"{BASE}/migrations/{mid}/apply", headers=admin_auth
        )).status_code == 200

        second = await client.post(
            f"{BASE}/migrations/{mid}/apply", headers=admin_auth
        )
        assert second.status_code == 409
        assert "pending" in second.json()["detail"]

    async def test_cannot_apply_unknown_migration(self, client, admin_auth):
        resp = await client.post(
            f"{BASE}/migrations/{uuid.uuid4()}/apply", headers=admin_auth
        )
        assert resp.status_code == 404

    async def test_cross_tenant_apply_is_404(
        self, client, db_session, make_admin, tenant, schema, field, table
    ):
        first = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]}, headers=await make_admin(tenant),
        )
        mid = first.json()["data"]["migration_id"]

        intruder = Tenant(name="Intruder2", slug=f"int2-{uuid.uuid4().hex[:12]}")
        db_session.add(intruder)
        await db_session.flush()

        resp = await client.post(
            f"{BASE}/migrations/{mid}/apply",
            headers=await make_admin(intruder),
        )
        assert resp.status_code == 404

    async def test_failed_apply_marks_row_failed(
        self, client, admin_auth, db_session, schema, field, table
    ):
        """
        A retype that cannot represent existing data reports 409 and the row
        records the failure.

        The field is retyped to integer in the draft first: narrowing the
        column to INTEGER is what makes the stored 'not-a-number' value
        unrepresentable, so the DDL genuinely fails.
        """
        from app.modules.form_builder.models import FieldDefinition as FD

        await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]}, headers=admin_auth,
        )
        add_id = (await client.get(
            f"{BASE}/schemas/{schema.id}/migrations", headers=admin_auth
        )).json()["data"][0]["id"]
        await client.post(f"{BASE}/migrations/{add_id}/apply", headers=admin_auth)

        await db_session.execute(text(
            f'INSERT INTO "{table}" (tenant_id, "customer_email") '
            "VALUES (:t, 'not-a-number')"
        ), {'t': schema.tenant_id})
        await db_session.flush()

        # The field is now an integer in the draft, so the plan is
        # VARCHAR(255) -> INTEGER, which the existing row cannot satisfy.
        stored = await db_session.get(FD, field.id)
        stored.field_type = "integer"
        await db_session.flush()

        mid2 = (await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id, action="modify", from_type="text")]},
            headers=admin_auth,
        )).json()["data"]["migration_id"]

        resp = await client.post(f"{BASE}/migrations/{mid2}/apply", headers=admin_auth)
        assert resp.status_code == 409

        detail = await client.get(f"{BASE}/migrations/{mid2}", headers=admin_auth)
        assert detail.json()["data"]["status"] == "failed"
        assert detail.json()["data"]["error_message"]

        # The column must be untouched, i.e. the DDL rolled back with the row.
        dtype = await db_session.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'customer_email'"
        ), {'t': table})
        assert dtype.scalar() == 'character varying'


# ══════════════════════════════════════════════════════════════
#  ROLLBACK
# ══════════════════════════════════════════════════════════════

class TestRollback:
    async def test_rollback_removes_the_column(
        self, client, admin_auth, db_session, schema, field, table
    ):
        preview = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]}, headers=admin_auth,
        )
        mid = preview.json()["data"]["migration_id"]
        await client.post(f"{BASE}/migrations/{mid}/apply", headers=admin_auth)

        resp = await client.post(
            f"{BASE}/migrations/{mid}/rollback", headers=admin_auth
        )
        assert resp.status_code == 200, resp.text

        cols = await db_session.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'customer_email'"
        ), {'t': table})
        assert cols.scalar() == 0

    async def test_cannot_rollback_twice(self, client, admin_auth, schema, field, table):
        preview = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]}, headers=admin_auth,
        )
        mid = preview.json()["data"]["migration_id"]
        await client.post(f"{BASE}/migrations/{mid}/apply", headers=admin_auth)
        await client.post(f"{BASE}/migrations/{mid}/rollback", headers=admin_auth)

        resp = await client.post(
            f"{BASE}/migrations/{mid}/rollback", headers=admin_auth
        )
        assert resp.status_code == 400

    async def test_cannot_rollback_pending(self, client, admin_auth, schema, field, table):
        preview = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]}, headers=admin_auth,
        )
        mid = preview.json()["data"]["migration_id"]

        resp = await client.post(
            f"{BASE}/migrations/{mid}/rollback", headers=admin_auth
        )
        assert resp.status_code == 400

    async def test_destructive_migration_refuses_rollback(
        self, client, admin_auth, db_session, schema, field, table
    ):
        add = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]}, headers=admin_auth,
        )
        await client.post(
            f"{BASE}/migrations/{add.json()['data']['migration_id']}/apply",
            headers=admin_auth,
        )

        drop = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id, action="delete")]},
            headers=admin_auth,
        )
        drop_id = drop.json()["data"]["migration_id"]
        assert drop.json()["data"]["is_destructive"] is True
        await client.post(f"{BASE}/migrations/{drop_id}/apply", headers=admin_auth)

        resp = await client.post(
            f"{BASE}/migrations/{drop_id}/rollback", headers=admin_auth
        )
        assert resp.status_code == 400
        assert "irreversible" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════════
#  HISTORY
# ══════════════════════════════════════════════════════════════

class TestHistory:
    async def test_lists_in_newest_first_with_envelope(
        self, client, admin_auth, schema, field, table
    ):
        preview = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]}, headers=admin_auth,
        )
        await client.post(
            f"{BASE}/migrations/{preview.json()['data']['migration_id']}/apply",
            headers=admin_auth,
        )

        resp = await client.get(
            f"{BASE}/schemas/{schema.id}/migrations", headers=admin_auth
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["data"][0]["status"] == "applied"
        # List view must not leak the executable SQL.
        assert "forward_sql" not in body["data"][0]

    async def test_status_filter(self, client, admin_auth, schema, field, table):
        preview = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]}, headers=admin_auth,
        )
        await client.post(
            f"{BASE}/migrations/{preview.json()['data']['migration_id']}/apply",
            headers=admin_auth,
        )

        pending = await client.get(
            f"{BASE}/schemas/{schema.id}/migrations?status=pending",
            headers=admin_auth,
        )
        assert pending.json()["total"] == 0

        applied = await client.get(
            f"{BASE}/schemas/{schema.id}/migrations?status=applied",
            headers=admin_auth,
        )
        assert applied.json()["total"] == 1

    async def test_rejects_unknown_status_filter(self, client, admin_auth, schema):
        resp = await client.get(
            f"{BASE}/schemas/{schema.id}/migrations?status=bogus",
            headers=admin_auth,
        )
        assert resp.status_code == 400

    async def test_detail_includes_sql(self, client, admin_auth, schema, field, table):
        preview = await client.post(
            f"{BASE}/schemas/{schema.id}/migrations/preview",
            json={"changes": [change(field.id)]}, headers=admin_auth,
        )
        mid = preview.json()["data"]["migration_id"]

        resp = await client.get(f"{BASE}/migrations/{mid}", headers=admin_auth)
        assert resp.status_code == 200
        assert "ADD COLUMN" in resp.json()["data"]["forward_sql"]

    async def test_unknown_migration_detail_is_404(self, client, admin_auth):
        resp = await client.get(
            f"{BASE}/migrations/{uuid.uuid4()}", headers=admin_auth
        )
        assert resp.status_code == 404
