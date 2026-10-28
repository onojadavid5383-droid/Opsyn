"""
Cross-tenant isolation tests for dynamic entity tables.

A dynamic table has no Alembic migration and no ORM model, so the RLS policy
in build_rls() is the only thing standing between tenants. These tests assert
it actually holds.

Two details make this harder than it looks, and both are load-bearing:

1. The test connection is a superuser, and superusers bypass RLS. Every
   assertion here therefore runs under SET LOCAL ROLE to a freshly created
   non-superuser, non-BYPASSRLS role. Without that this whole file would pass
   vacuously. test_probe_role_is_itself_unprivileged() guards that.

2. The policy's USING clause fails open (unset GUC sees everything, matching
   0029/0081/0095) but its WITH CHECK clause does not -- it has no NULL-safe
   branch, so a write with no GUC is rejected. Reads and writes therefore
   behave differently on purpose, and both are asserted below.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.form_builder.schema_sql import (
    build_create_table,
    entity_table_name,
    quote_ident,
    split_statements,
)
from app.modules.tenants.models import Tenant


PROBE_PREFIX = 'rls_probe_'


@pytest.fixture
async def tenants(db_session):
    a = Tenant(name="Alpha", slug=f"alpha-{uuid.uuid4().hex[:12]}")
    b = Tenant(name="Beta", slug=f"beta-{uuid.uuid4().hex[:12]}")
    db_session.add_all([a, b])
    await db_session.flush()
    return a, b


@pytest.fixture
async def table(db_session, tenants):
    """Alpha's dynamic table, created the way production would create it."""
    alpha, _beta = tenants
    name = entity_table_name(alpha.id, 'customer')
    forward, _ = build_create_table(name, [('full_name', 'string', None)])
    for statement in split_statements(forward):
        await db_session.execute(text(statement))
    await db_session.flush()
    return name


@pytest.fixture
async def probe_role(db_session):
    """
    A non-superuser role to run assertions under.

    The name embeds uuid4 hex, so interpolating it into DDL cannot be an
    injection vector. Created inside db_session's transaction, so the rollback
    in that fixture removes it -- no global state is left behind.
    """
    name = PROBE_PREFIX + uuid.uuid4().hex[:12]
    await db_session.execute(text(f'CREATE ROLE "{name}" NOLOGIN'))
    await db_session.execute(text(f'GRANT "{name}" TO CURRENT_USER'))
    return name


async def _scope(db, tenant_id):
    """
    Become the probe role and set the tenant GUC for this transaction.

    set_config() is parameterised deliberately; interpolating a uuid into a
    SET statement would work but makes the injection-safety of this file
    depend on a value it also asserts about. '' is how an unset GUC is
    represented to the policy.
    """
    await db.execute(text('RESET ROLE'))
    await db.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"),
        {'t': '' if tenant_id is None else str(tenant_id)},
    )


async def _rows(db, sql, role, tenant_id):
    """Run a SELECT as `role` scoped to `tenant_id`; return the tenant_ids seen."""
    await db.execute(text(f'SET LOCAL ROLE "{role}"'))
    await db.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"),
        {'t': '' if tenant_id is None else str(tenant_id)},
    )
    result = await db.execute(text(sql))
    return [str(r[0]) for r in result.fetchall()]


class TestStaticTableNullif:
    """
    0097 rewrote the inherited policy on every static table.

    Same bug as the dynamic tables: the bare
    `current_setting(...)::uuid` cast raised on an empty GUC, making the
    policy's own `= ''` fail-open guard unreachable.
    """

    async def test_no_static_policy_uses_the_bare_cast(self, db_session):
        """
        Regression guard for 0097.

        Asserts on the catalog rather than on behaviour because it has to cover
        every table, including the ~90 no test exercises. A new migration that
        reintroduces the old policy body would otherwise pass every behavioural
        test here, since all of them set a real uuid.
        """
        result = await db_session.execute(text("""
            SELECT count(*)
            FROM pg_policy p
            WHERE p.polname = 'tenant_isolation'
              AND p.polqual IS NOT NULL
              AND pg_get_expr(p.polqual, p.polrelid) LIKE '%current_setting%'
              AND pg_get_expr(p.polqual, p.polrelid) NOT LIKE '%NULLIF%'
        """))
        remaining = result.scalar()
        assert remaining == 0, (
            f'{remaining} tenant_isolation policies still use the bare uuid '
            'cast; 0097 should have rewritten all of them'
        )

    async def test_static_policy_admits_empty_guc(self, db_session, probe_role):
        """
        The behaviour the rewrite exists to enable.

        Same shape as the dynamic-table case: an empty GUC must return rows
        (fail open) rather than raise. Run as the non-superuser probe, because
        a superuser skips the policy entirely and would pass regardless.
        """
        await db_session.execute(
            text(f'GRANT SELECT ON users TO "{probe_role}"')
        )
        seen = await _rows(db_session, 'SELECT id FROM users', probe_role, None)
        # Whether the table has rows is irrelevant; the assertion is that the
        # query completed instead of raising `invalid input syntax for uuid`.
        assert isinstance(seen, list)

    async def test_static_policy_still_scopes_a_real_tenant(
        self, db_session, tenants, probe_role,
    ):
        """
        The rewrite must not have weakened the filter that actually runs.

        The dynamic-table tests below cover this properly with data present;
        this is the static-table smoke check, asserting a real tenant id still
        returns rows rather than nothing.
        """
        alpha, _beta = tenants
        await db_session.execute(
            text(f'GRANT SELECT ON tenants TO "{probe_role}"')
        )
        seen = await _rows(
            db_session, 'SELECT id FROM tenants', probe_role, alpha.id
        )
        assert seen == [str(alpha.id)]


class TestDynamicTableRls:
    async def test_probe_role_is_itself_unprivileged(self, db_session, probe_role):
        """Guards the rest of this file: a superuser probe would prove nothing."""
        result = await db_session.execute(
            text('SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :n'),
            {'n': probe_role},
        )
        row = result.first()
        assert row is not None, 'probe role was not created'
        assert row[0] is False, 'probe role must not be a superuser'
        assert row[1] is False, 'probe role must not have BYPASSRLS'

    async def test_create_table_turns_rls_on_and_forces_it(
        self, db_session, table,
    ):
        """
        ENABLE alone is not enough. Without FORCE, the table owner bypasses its
        own policy, and the owner is exactly who runs migrations.
        """
        result = await db_session.execute(
            text(
                'SELECT relrowsecurity, relforcerowsecurity '
                'FROM pg_class WHERE relname = :n'
            ),
            {'n': table},
        )
        row = result.first()
        assert row[0] is True, 'RLS not enabled on the dynamic table'
        assert row[1] is True, 'RLS not forced on the dynamic table'

    async def test_tenant_sees_its_own_rows(self, db_session, table, tenants, probe_role):
        alpha, _beta = tenants
        tbl = quote_ident(table, 'table_name')
        await db_session.execute(
            text(f'GRANT SELECT ON {tbl} TO "{probe_role}"')
        )
        await _scope(db_session, alpha.id)
        await db_session.execute(
            text(f"INSERT INTO {tbl} (tenant_id, full_name) VALUES (:t, 'Alpha Row')"),
            {'t': str(alpha.id)},
        )

        seen = await _rows(
            db_session, f'SELECT tenant_id FROM {tbl}', probe_role, alpha.id
        )
        assert seen == [str(alpha.id)]

    async def test_tenant_sees_nothing_of_another_tenant(
        self, db_session, table, tenants, probe_role,
    ):
        alpha, beta = tenants
        tbl = quote_ident(table, 'table_name')
        await db_session.execute(
            text(f'GRANT SELECT ON {tbl} TO "{probe_role}"')
        )
        await _scope(db_session, alpha.id)
        await db_session.execute(
            text(f"INSERT INTO {tbl} (tenant_id, full_name) VALUES (:t, 'Alpha Row')"),
            {'t': str(alpha.id)},
        )

        seen = await _rows(
            db_session, f'SELECT tenant_id FROM {tbl}', probe_role, beta.id
        )
        assert seen == [], 'a tenant was able to read another tenant\'s row'

    async def test_cross_tenant_insert_is_rejected(
        self, db_session, table, tenants, probe_role,
    ):
        """
        WITH CHECK has no NULL-safe branch, so writing another tenant's id is
        refused even though USING would have let it be read.
        """
        alpha, beta = tenants
        tbl = quote_ident(table, 'table_name')
        await db_session.execute(
            text(f'GRANT INSERT ON {tbl} TO "{probe_role}"')
        )

        await db_session.execute(text(f'SET LOCAL ROLE "{probe_role}"'))
        await db_session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {'t': str(alpha.id)},
        )
        savepoint = await db_session.begin_nested()
        try:
            with pytest.raises(DBAPIError) as exc:
                await db_session.execute(
                    text(
                        f"INSERT INTO {tbl} (tenant_id, full_name) "
                        f"VALUES (:t, 'Forged')"
                    ),
                    {'t': str(beta.id)},
                )
            assert 'row-level security' in str(exc.value).lower()
        finally:
            await savepoint.rollback()

    async def test_unset_guc_reads_are_unfiltered_by_design(
        self, db_session, table, tenants, probe_role,
    ):
        """
        Documents the deliberate fail-open read path: a worker or admin script
        that never sets the GUC still sees rows. Celery depends on this, so it
        is pinned here rather than left to a comment.
        """
        alpha, _beta = tenants
        tbl = quote_ident(table, 'table_name')
        await db_session.execute(
            text(f'GRANT SELECT ON {tbl} TO "{probe_role}"')
        )
        await _scope(db_session, alpha.id)
        await db_session.execute(
            text(f"INSERT INTO {tbl} (tenant_id, full_name) VALUES (:t, 'Alpha Row')"),
            {'t': str(alpha.id)},
        )

        seen = await _rows(db_session, f'SELECT tenant_id FROM {tbl}', probe_role, None)
        assert seen == [str(alpha.id)]

    async def test_unset_guc_writes_are_refused(
        self, db_session, table, tenants, probe_role,
    ):
        """The asymmetry with the read path, asserted so it cannot drift."""
        alpha, _beta = tenants
        tbl = quote_ident(table, 'table_name')
        await db_session.execute(
            text(f'GRANT INSERT ON {tbl} TO "{probe_role}"')
        )
        await db_session.execute(text(f'SET LOCAL ROLE "{probe_role}"'))
        await db_session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {'t': ''},
        )
        savepoint = await db_session.begin_nested()
        try:
            with pytest.raises(DBAPIError) as exc:
                await db_session.execute(
                    text(
                        f"INSERT INTO {tbl} (tenant_id, full_name) "
                        f"VALUES (:t, 'No Guc')"
                    ),
                    {'t': str(alpha.id)},
                )
            assert 'row-level security' in str(exc.value).lower()
        finally:
            await savepoint.rollback()