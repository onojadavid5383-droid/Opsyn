"""
Integration tests for SchemaMigrationService.plan_migration.

plan_migration is pure planning -- it must never touch the target table. These
tests assert on the generated plan and on the fact that nothing was executed.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.modules.form_builder.models import FormSchema
from app.modules.tenants.models import Tenant
from app.modules.form_builder.schema_migration_service import (
    FieldChange,
    SchemaMigrationService,
    ValidationError,
)
from app.modules.form_builder.schema_sql import (
    build_create_table,
    entity_table_name,
    quote_ident,
    split_statements,
)


@pytest.fixture
async def tenant(db_session):
    t = Tenant(name="Plan Test", slug=f"plan-{uuid.uuid4().hex[:12]}")
    db_session.add(t)
    await db_session.flush()
    return t


@pytest.fixture
async def schema(db_session, tenant):
    s = FormSchema(
        tenant_id=tenant.id,
        name="Customer",
        machine_name="customer",
        module="customer",
        status="published",
        current_version=1,
    )
    db_session.add(s)
    await db_session.flush()
    return s


def field(field_key, field_type, **kwargs):
    """A FieldDefinition-shaped stand-in; only the mapped attributes matter."""
    return type('FakeField', (), {
        'field_key': field_key,
        'field_type': field_type,
        'options': kwargs.get('options'),
        'is_required': kwargs.get('is_required', False),
        'label': field_key,
    })()


@pytest.fixture
async def existing_table(db_session, tenant, schema):
    """The dynamic table already exists, so alter/delete plans are legal."""
    table = entity_table_name(tenant.id, schema.machine_name)
    forward, _ = build_create_table(table, [])
    for statement in split_statements(forward):
        await db_session.execute(text(statement))
    await db_session.flush()
    return table


@pytest.fixture
def service(db_session):
    return SchemaMigrationService(db_session)


# ══════════════════════════════════════════════════════════════
#  ADD COLUMN
# ══════════════════════════════════════════════════════════════

class TestPlanAddColumn:
    async def test_adds_column(self, service, db_session, tenant, schema, existing_table):
        plan = await service.plan_migration(
            schema.id, [FieldChange('add', field('email', 'email'))], tenant.id
        )

        assert plan.table_name == existing_table
        assert plan.change_type == 'add_column'
        assert 'ADD COLUMN "email"' in plan.forward_sql
        assert 'DROP COLUMN "email"' in plan.rollback_sql
        assert plan.reversible is True
        assert plan.is_destructive is False

    async def test_planning_executes_nothing(self, service, db_session, tenant, schema, existing_table):
        await service.plan_migration(
            schema.id, [FieldChange('add', field('email', 'email'))], tenant.id
        )
        result = await db_session.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'email'"
        ), {'t': existing_table})
        assert result.scalar() == 0

    async def test_required_field_becomes_not_null(self, service, tenant, schema, existing_table):
        plan = await service.plan_migration(
            schema.id,
            [FieldChange('add', field('name', 'string', is_required=True))],
            tenant.id,
        )
        assert 'NOT NULL' in plan.forward_sql

    async def test_enum_options_produce_a_check(self, service, tenant, schema, existing_table):
        plan = await service.plan_migration(
            schema.id,
            [FieldChange('add', field('status', 'enum', options=['new', 'done']))],
            tenant.id,
        )
        assert 'CHECK' in plan.forward_sql
        assert "'new'" in plan.forward_sql

    async def test_section_header_is_not_a_column(self, service, tenant, schema, existing_table):
        with pytest.raises(ValidationError):
            await service.plan_migration(
                schema.id, [FieldChange('add', field('intro', 'section_header'))], tenant.id
            )

    async def test_multiple_fields_combine(self, service, tenant, schema, existing_table):
        plan = await service.plan_migration(
            schema.id,
            [
                FieldChange('add', field('email', 'email')),
                FieldChange('add', field('age', 'integer')),
            ],
            tenant.id,
        )
        assert len(split_statements(plan.forward_sql)) == 2


# ══════════════════════════════════════════════════════════════
#  VALIDATION / TENANT ISOLATION
# ══════════════════════════════════════════════════════════════

class TestPlanValidation:
    async def test_empty_change_list_rejected(self, service, tenant, schema):
        with pytest.raises(ValidationError):
            await service.plan_migration(schema.id, [], tenant.id)

    async def test_unknown_schema_rejected(self, service, tenant):
        with pytest.raises(ValidationError):
            await service.plan_migration(
                uuid.uuid4(), [FieldChange('add', field('a', 'string'))], tenant.id
            )

    async def test_cross_tenant_schema_rejected(self, service, db_session, schema):
        """The critical isolation check."""
        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:12]}")
        db_session.add(other)
        await db_session.flush()

        with pytest.raises(ValidationError):
            await service.plan_migration(
                schema.id, [FieldChange('add', field('a', 'string'))], other.id
            )

    async def test_reserved_column_rejected(self, service, tenant, schema, existing_table):
        for reserved in ('tenant_id', 'created_at', 'id', 'is_deleted'):
            with pytest.raises(ValidationError):
                await service.plan_migration(
                    schema.id, [FieldChange('add', field(reserved, 'string'))], tenant.id
                )

    async def test_duplicate_column_in_one_plan_rejected(self, service, tenant, schema, existing_table):
        with pytest.raises(ValidationError):
            await service.plan_migration(
                schema.id,
                [FieldChange('add', field('email', 'email')),
                 FieldChange('add', field('email', 'text'))],
                tenant.id,
            )

    async def test_injection_column_key_rejected(self, service, tenant, schema, existing_table):
        with pytest.raises(ValidationError):
            await service.plan_migration(
                schema.id,
                [FieldChange('add', field('x"); DROP TABLE users; --', 'string'))],
                tenant.id,
            )

    async def test_unknown_field_type_rejected(self, service, tenant, schema, existing_table):
        with pytest.raises(ValidationError):
            await service.plan_migration(
                schema.id, [FieldChange('add', field('x', 'nope'))], tenant.id
            )

    async def test_unknown_action_rejected(self, service, tenant, schema, existing_table):
        with pytest.raises(ValidationError):
            await service.plan_migration(
                schema.id, [FieldChange('frobnicate', field('x', 'string'))], tenant.id
            )

    async def test_archived_schema_rejected(self, service, db_session, tenant, schema, existing_table):
        schema.status = 'archived'
        await db_session.flush()
        with pytest.raises(ValidationError):
            await service.plan_migration(
                schema.id, [FieldChange('add', field('a', 'string'))], tenant.id
            )

    async def test_alter_requires_existing_table(self, service, tenant, schema):
        """Table does not exist yet -- alter must not be planned against it."""
        with pytest.raises(ValidationError):
            await service.plan_migration(
                schema.id,
                [FieldChange('modify', field('a', 'integer'),
                             old_value={'field_type': 'string'})],
                tenant.id,
            )

    async def test_modify_without_old_type_rejected(self, service, tenant, schema, existing_table):
        with pytest.raises(ValidationError):
            await service.plan_migration(
                schema.id, [FieldChange('modify', field('a', 'integer'))], tenant.id
            )


# ══════════════════════════════════════════════════════════════
#  MODIFY / DELETE
# ══════════════════════════════════════════════════════════════

class TestPlanModifyDelete:
    async def test_modify_is_flagged_destructive_and_irreversible(
        self, service, tenant, schema, existing_table
    ):
        plan = await service.plan_migration(
            schema.id,
            [FieldChange('modify', field('v', 'text'),
                         old_value={'field_type': 'string'})],
            tenant.id,
        )
        assert plan.change_type == 'alter_column'
        assert plan.is_destructive is True
        assert plan.reversible is False
        assert 'TYPE TEXT' in plan.forward_sql

    async def test_delete_warns_that_data_is_unrecoverable(
        self, service, tenant, schema, existing_table
    ):
        plan = await service.plan_migration(
            schema.id, [FieldChange('delete', field('old_col', 'string'))], tenant.id
        )
        assert plan.change_type == 'drop_column'
        assert plan.reversible is False
        assert plan.is_destructive is True
        assert any('irreversible' in w for w in plan.warnings)

    async def test_field_changes_recorded_for_audit(self, service, tenant, schema, existing_table):
        plan = await service.plan_migration(
            schema.id,
            [FieldChange('modify', field('v', 'integer'),
                         old_value={'field_type': 'string'})],
            tenant.id,
        )
        entry = plan.field_changes[0]
        assert entry['action'] == 'modify'
        assert entry['from_type'] == 'string'
        assert entry['to_type'] == 'integer'


# ══════════════════════════════════════════════════════════════
#  END-TO-END: PLAN SQL IS EXECUTABLE
# ══════════════════════════════════════════════════════════════

class TestPlanIsExecutable:
    async def test_generated_plan_actually_runs(
        self, service, db_session, tenant, schema, existing_table
    ):
        """
        The plan is only useful if Postgres accepts it. Executing it here
        couples plan_migration to the SQL builders in a way no string
        assertion can.
        """
        plan = await service.plan_migration(
            schema.id,
            [
                FieldChange('add', field('email', 'email')),
                FieldChange('add', field('age', 'integer')),
                FieldChange('add', field('status', 'enum', options=['new', 'done'])),
            ],
            tenant.id,
        )
        for statement in split_statements(plan.forward_sql):
            await db_session.execute(text(statement))
        await db_session.flush()

        result = await db_session.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = :t AND column_name IN ('email','age','status')"
        ), {'t': existing_table})
        assert result.scalar() == 3

    async def test_rollback_sql_restores_shape(
        self, service, db_session, tenant, schema, existing_table
    ):
        plan = await service.plan_migration(
            schema.id, [FieldChange('add', field('email', 'email'))], tenant.id
        )
        for statement in split_statements(plan.forward_sql):
            await db_session.execute(text(statement))
        for statement in split_statements(plan.rollback_sql):
            await db_session.execute(text(statement))
        await db_session.flush()

        result = await db_session.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'email'"
        ), {'t': existing_table})
        assert result.scalar() == 0