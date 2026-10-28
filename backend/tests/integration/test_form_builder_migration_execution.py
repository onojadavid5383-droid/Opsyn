"""
Integration tests for execute_migration / rollback_migration.

These exercise the parts that only a real database can show: that DDL actually
lands, that a failure leaves the schema untouched, that the advisory lock
serialises, and that a rejected migration still leaves an audit trace.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.form_builder.models import (
    FieldDefinition,
    FormSchema,
    SchemaMigrationHistory,
)
from app.modules.form_builder.schema_migration_service import (
    ConcurrentModificationError,
    ExecutionError,
    FieldChange,
    RollbackError,
    SchemaMigrationService,
    ValidationError,
    plan_hash,
    schema_lock_id,
)
from app.modules.form_builder.schema_sql import (
    build_create_table,
    entity_table_name,
    split_statements,
)
from app.modules.roles.models import Role
from app.modules.staff.models import User
from app.modules.tenants.models import Tenant


@pytest.fixture
async def tenant(db_session):
    t = Tenant(name="Exec Test", slug=f"exec-{uuid.uuid4().hex[:12]}")
    db_session.add(t)
    await db_session.flush()
    return t


@pytest.fixture
async def actor(db_session, tenant):
    """
    A real user, because schema_migration_history.applied_by is a FK to users.

    Passing a bare uuid4() would violate the constraint and mask the behaviour
    these tests are actually about.
    """
    role = Role(tenant_id=tenant.id, name="Form Admin", level=1, is_system_role=True)
    db_session.add(role)
    await db_session.flush()

    user = User(
        tenant_id=tenant.id,
        username=f"migrator-{uuid.uuid4().hex[:8]}",
        email=f"migrator-{uuid.uuid4().hex[:8]}@opsyn.test",
        password_hash="not-used-in-these-tests",
        role_id=role.id,
    )
    db_session.add(user)
    await db_session.flush()
    return user


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
async def table(db_session, tenant, schema):
    name = entity_table_name(tenant.id, schema.machine_name)
    forward, _ = build_create_table(name, [])
    for statement in split_statements(forward):
        await db_session.execute(text(statement))
    await db_session.flush()
    return name


@pytest.fixture
def service(db_session):
    return SchemaMigrationService(db_session)


def field(field_key, field_type, **kw):
    return type('FakeField', (), {
        'field_key': field_key, 'field_type': field_type,
        'options': kw.get('options'), 'is_required': kw.get('is_required', False),
        'label': field_key,
    })()


async def columns_of(db, table):
    result = await db.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
    ), {'t': table})
    return {r[0] for r in result.all()}


# A failed migration rolls the session back, which expires every ORM instance
# in it. Reading schema.id after that would trigger a lazy refresh outside the
# greenlet context, so tests that expect a failure capture these first.
@pytest.fixture
def ids(tenant, schema):
    return schema.id, tenant.id


# ══════════════════════════════════════════════════════════════
#  EXECUTE
# ══════════════════════════════════════════════════════════════

class TestExecute:
    async def test_applies_the_column(self, service, db_session, tenant, schema, table, actor):
        plan = await service.plan_migration(
            schema.id, [FieldChange('add', field('email', 'email'))], tenant.id
        )
        result = await service.execute_migration(plan, actor.id)

        assert result.success is True
        assert result.columns_added == ['email']
        assert result.execution_duration_ms >= 0
        assert 'email' in await columns_of(db_session, table)

    async def test_writes_history_row(self, service, db_session, tenant, schema, table, actor):
        plan = await service.plan_migration(
            schema.id, [FieldChange('add', field('age', 'integer'))], tenant.id
        )
        result = await service.execute_migration(plan, actor.id)

        row = (await db_session.execute(
            text("SELECT status, change_type, plan_hash, table_name, applied_by "
                 "FROM schema_migration_history WHERE id = :i"),
            {'i': result.migration_id}
        )).one()
        assert row[0] == 'applied'
        assert row[1] == 'add_column'
        assert row[2] == plan_hash(plan.forward_sql)
        assert row[3] == table
        assert row[4] is not None

    async def test_no_alembic_revision_recorded(self, service, db_session, tenant, schema, table, actor):
        """Runtime DDL writes no migration file, so there is no revision."""
        plan = await service.plan_migration(
            schema.id, [FieldChange('add', field('age', 'integer'))], tenant.id
        )
        result = await service.execute_migration(plan, actor.id)
        rev = await db_session.execute(text(
            "SELECT alembic_revision FROM schema_migration_history WHERE id = :i"
        ), {'i': result.migration_id})
        assert rev.scalar() is None

    async def test_history_is_visible_to_the_tenant(self, service, db_session, tenant, schema, table, actor):
        """The RLS-scoped read path the API will use."""
        plan = await service.plan_migration(
            schema.id, [FieldChange('add', field('age', 'integer'))], tenant.id
        )
        await service.execute_migration(plan, actor.id)

        found = await service.get_migration_history(schema.id, tenant.id)
        assert len(found) == 1
        assert found[0].status == 'applied'

    async def test_multiple_columns_in_one_migration(
        self, service, db_session, tenant, schema, table,
        actor,
    ):
        plan = await service.plan_migration(
            schema.id,
            [FieldChange('add', field('email', 'email')),
             FieldChange('add', field('age', 'integer')),
             FieldChange('add', field('status', 'enum', options=['a', 'b']))],
            tenant.id,
        )
        result = await service.execute_migration(plan, actor.id)

        assert result.columns_added == ['email', 'age', 'status']
        cols = await columns_of(db_session, table)
        assert {'email', 'age', 'status'} <= cols

    async def test_duplicate_plan_is_refused(self, service, db_session, tenant, schema, table, actor):
        plan = await service.plan_migration(
            schema.id, [FieldChange('add', field('email', 'email'))], tenant.id
        )
        await service.execute_migration(plan, actor.id)

        with pytest.raises(ExecutionError) as exc:
            await service.execute_migration(plan, actor.id)
        assert 'already applied' in str(exc.value)

    async def test_different_plan_still_runs(self, service, db_session, tenant, schema, table, actor):
        first = await service.plan_migration(
            schema.id, [FieldChange('add', field('email', 'email'))], tenant.id
        )
        await service.execute_migration(first, actor.id)

        second = await service.plan_migration(
            schema.id, [FieldChange('add', field('age', 'integer'))], tenant.id
        )
        result = await service.execute_migration(second, actor.id)
        assert result.success is True


# ══════════════════════════════════════════════════════════════
#  FAILURE
# ══════════════════════════════════════════════════════════════

class TestExecuteFailure:
    async def test_failed_ddl_leaves_schema_unchanged(
        self, service, db_session, tenant, schema, table,
        actor, ids,
    ):
        """
        A retype that cannot represent existing data must fail with the table
        exactly as it was, and with no 'applied' history row.
        """
        schema_id, tenant_id = ids
        plan = await service.plan_migration(
            schema_id, [FieldChange('add', field('v', 'text'))], tenant_id
        )
        await service.execute_migration(plan, actor.id)

        await db_session.execute(text(
            f'INSERT INTO "{table}" (tenant_id, "v") VALUES (:t, \'not a number\')'
        ), {'t': tenant_id})
        await db_session.flush()

        bad = await service.plan_migration(
            schema_id,
            [FieldChange('modify', field('v', 'integer'),
                         old_value={'field_type': 'text'})],
            tenant_id,
        )
        with pytest.raises(ExecutionError):
            await service.execute_migration(bad, actor.id)

        # Column still text, and the failed attempt is not 'applied'.
        dtype = await db_session.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'v'"
        ), {'t': table})
        assert dtype.scalar() == 'text'

        applied = await db_session.execute(text(
            "SELECT count(*) FROM schema_migration_history "
            "WHERE schema_id = :s AND status = 'applied' AND change_type = 'alter_column'"
        ), {'s': schema_id})
        assert applied.scalar() == 0

    async def test_failure_is_still_recorded_for_audit(
        self, service, db_session, tenant, schema, table,
        actor, ids,
    ):
        """
        A rejected migration must leave a trace, otherwise an operator
        cannot tell a refusal from a request that never arrived.
        """
        schema_id, tenant_id = ids
        plan = await service.plan_migration(
            schema_id, [FieldChange('add', field('v', 'text'))], tenant_id
        )
        await service.execute_migration(plan, actor.id)
        await db_session.execute(text(
            f'INSERT INTO "{table}" (tenant_id, "v") VALUES (:t, \'nope\')'
        ), {'t': tenant_id})
        await db_session.flush()

        bad = await service.plan_migration(
            schema_id,
            [FieldChange('modify', field('v', 'integer'),
                         old_value={'field_type': 'text'})],
            tenant_id,
        )
        with pytest.raises(ExecutionError):
            await service.execute_migration(bad, actor.id)

        row = (await db_session.execute(text(
            "SELECT status, error_message FROM schema_migration_history "
            "WHERE schema_id = :s AND change_type = 'alter_column'"
        ), {'s': schema_id})).one()
        assert row[0] == 'failed'
        assert row[1]

    async def test_partial_multi_statement_plan_is_fully_reverted(
        self, service, db_session, tenant, schema, table,
        actor, ids,
    ):
        """
        A retype emits three statements (drop constraint, retype, re-add).
        The failure happens on the second, so the first must be rolled back
        too -- otherwise the column is left with no CHECK at all.
        """
        schema_id, tenant_id = ids
        plan = await service.plan_migration(
            schema_id,
            [FieldChange('add', field('v', 'enum', options=['a', 'b']))],
            tenant_id,
        )
        await service.execute_migration(plan, actor.id)
        await db_session.execute(text(
            f'INSERT INTO "{table}" (tenant_id, "v") VALUES (:t, \'a\')'
        ), {'t': tenant_id})
        await db_session.flush()

        bad = await service.plan_migration(
            schema_id,
            [FieldChange('modify', field('v', 'integer'),
                         old_value={'field_type': 'enum', 'options': ['a', 'b']})],
            tenant_id,
        )
        with pytest.raises(ExecutionError):
            await service.execute_migration(bad, actor.id)

        # The CHECK must still be enforcing: 'a' is a valid value, 'zz' is not.
        with pytest.raises(Exception):
            await db_session.execute(text(
                f'INSERT INTO "{table}" (tenant_id, "v") VALUES (:t, \'zz\')'
            ), {'t': tenant_id})
        await db_session.rollback()

        constraints = await db_session.execute(text(
            "SELECT count(*) FROM information_schema.table_constraints "
            "WHERE table_name = :t AND constraint_name = 'v_options_check'"
        ), {'t': table})
        assert constraints.scalar() == 1


# ══════════════════════════════════════════════════════════════
#  CONCURRENCY
# ══════════════════════════════════════════════════════════════

class TestConcurrency:
    async def test_lock_is_refused_while_held(self, service, db_session, db_engine,
                                              tenant, schema, table, actor):
        """
        A second connection cannot take the same schema's advisory lock while
        the first holds it, which is what stops two field saves from racing.

        The holder must be a *different* session. Advisory locks are
        re-entrant within one session, so taking the lock on the same session
        under test would always succeed and the test would prove nothing.
        """
        schema_id = schema.id
        other = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )()
        try:
            held = await other.execute(
                text("SELECT pg_try_advisory_xact_lock(:l)"),
                {'l': schema_lock_id(schema_id)},
            )
            assert held.scalar() is True

            plan = await service.plan_migration(
                schema_id, [FieldChange('add', field('email', 'email'))], tenant.id
            )
            with pytest.raises(ConcurrentModificationError):
                await service.execute_migration(plan, actor.id)
        finally:
            await other.close()

    async def test_lock_is_available_once_released(self, service, db_session, db_engine,
                                                   tenant, schema, table, actor):
        """The lock is transaction-scoped, so a finished holder frees it."""
        schema_id = schema.id
        other = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )()
        try:
            await other.execute(
                text("SELECT pg_try_advisory_xact_lock(:l)"),
                {'l': schema_lock_id(schema_id)},
            )
            await other.commit()
        finally:
            await other.close()

        plan = await service.plan_migration(
            schema_id, [FieldChange('add', field('email', 'email'))], tenant.id
        )
        result = await service.execute_migration(plan, actor.id)
        assert result.success is True

    async def test_lock_key_is_stable(self, actor):
        """Two processes must derive the same key, or the lock protects nothing."""
        sid = uuid.uuid4()
        assert schema_lock_id(sid) == schema_lock_id(sid)
        assert schema_lock_id(sid) != schema_lock_id(uuid.uuid4())
        assert 0 <= schema_lock_id(sid) < (1 << 63)


# ══════════════════════════════════════════════════════════════
#  ROLLBACK
# ══════════════════════════════════════════════════════════════

class TestRollback:
    async def test_rolls_back_an_addition(self, service, db_session, tenant, schema, table, actor):
        plan = await service.plan_migration(
            schema.id, [FieldChange('add', field('email', 'email'))], tenant.id
        )
        applied = await service.execute_migration(plan, actor.id)
        assert 'email' in await columns_of(db_session, table)

        result = await service.rollback_migration(applied.migration_id, actor.id)
        assert result.success is True
        assert 'email' not in await columns_of(db_session, table)

    async def test_history_records_the_rollback(self, service, db_session, tenant, schema, table, actor):
        plan = await service.plan_migration(
            schema.id, [FieldChange('add', field('email', 'email'))], tenant.id
        )
        applied = await service.execute_migration(plan, actor.id)
        await service.rollback_migration(applied.migration_id, actor.id)

        row = (await db_session.execute(text(
            "SELECT status, rolled_back_at, rolled_back_by "
            "FROM schema_migration_history WHERE id = :i"
        ), {'i': applied.migration_id})).one()
        assert row[0] == 'rolled_back'
        assert row[1] is not None
        assert row[2] is not None

    async def test_cannot_rollback_twice(self, service, db_session, tenant, schema, table, actor):
        plan = await service.plan_migration(
            schema.id, [FieldChange('add', field('email', 'email'))], tenant.id
        )
        applied = await service.execute_migration(plan, actor.id)
        await service.rollback_migration(applied.migration_id, actor.id)

        with pytest.raises(RollbackError):
            await service.rollback_migration(applied.migration_id, actor.id)

    async def test_unknown_migration_rejected(self, service, tenant, actor):
        with pytest.raises(RollbackError):
            await service.rollback_migration(uuid.uuid4(), actor.id)

    async def test_destructive_migration_refuses_rollback(
        self, service, db_session, tenant, schema, table,
        actor,
    ):
        """
        A DROP's rollback restores the column shape but not its data. Allowing
        it would imply a recovery that cannot happen.
        """
        plan = await service.plan_migration(
            schema.id, [FieldChange('add', field('temp', 'text'))], tenant.id
        )
        applied = await service.execute_migration(plan, actor.id)

        drop = await service.plan_migration(
            schema.id, [FieldChange('delete', field('temp', 'text'))], tenant.id
        )
        dropped = await service.execute_migration(drop, actor.id)

        with pytest.raises(RollbackError) as exc:
            await service.rollback_migration(dropped.migration_id, actor.id)
        assert 'irreversible' in str(exc.value)

    async def test_failed_migration_cannot_be_rolled_back(
        self, service, db_session, tenant, schema, table,
        actor, ids,
    ):
        schema_id, tenant_id = ids
        # actor.id must be read before the failure below rolls the session
        # back and expires every ORM instance in it.
        actor_id = actor.id
        plan = await service.plan_migration(
            schema_id, [FieldChange('add', field('v', 'text'))], tenant_id
        )
        await service.execute_migration(plan, actor_id)
        await db_session.execute(text(
            f'INSERT INTO "{table}" (tenant_id, "v") VALUES (:t, \'nope\')'
        ), {'t': tenant_id})
        await db_session.flush()

        bad = await service.plan_migration(
            schema_id,
            [FieldChange('modify', field('v', 'integer'),
                         old_value={'field_type': 'text'})],
            tenant_id,
        )
        with pytest.raises(ExecutionError):
            await service.execute_migration(bad, actor_id)

        failed = (await db_session.execute(text(
            "SELECT id FROM schema_migration_history "
            "WHERE schema_id = :s AND status = 'failed'"
        ), {'s': schema_id})).scalar_one()

        with pytest.raises(RollbackError):
            await service.rollback_migration(failed, actor_id)
