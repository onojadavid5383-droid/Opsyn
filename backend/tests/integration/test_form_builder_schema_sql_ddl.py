"""
Integration tests that execute generated DDL against real PostgreSQL.

The unit suite in test_form_builder_schema_sql.py asserts on SQL *strings*.
That cannot catch a syntax Postgres dislikes, a CHECK that rejects NULL, or a
rollback that does not actually restore the prior shape. These tests run the
statements, which is the only way to know the generated DDL is real.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text

from app.modules.form_builder.schema_sql import (
    build_add_column,
    build_alter_column,
    build_create_table,
    build_drop_column,
    build_index,
    check_constraint_name,
    entity_table_name,
    quote_ident,
    split_statements,
)


async def run(db, sql: str) -> None:
    """Execute a generated (possibly multi-statement) plan."""
    for statement in split_statements(sql):
        await db.execute(text(statement))
    await db.flush()


@asynccontextmanager
async def savepoint(db):
    """
    Nest the block in a SAVEPOINT.

    db_session is a single top-level transaction, so a bare rollback() to
    contain an expected failure would also discard the fixture's CREATE TABLE
    and every earlier assertion in the test. A savepoint confines the damage to
    the statements that actually failed.
    """
    async with db.begin_nested():
        yield


@pytest.fixture
def table_name() -> str:
    return entity_table_name(uuid.uuid4(), 'testentity')


@pytest.fixture
async def created(db_session, table_name):
    """An empty dynamic table, dropped at the end of the test."""
    forward, rollback = build_create_table(table_name, [])
    await run(db_session, forward)
    yield table_name
    await run(db_session, rollback)


# ══════════════════════════════════════════════════════════════
#  CREATE
# ══════════════════════════════════════════════════════════════

class TestCreateTable:
    async def test_creates_with_infrastructure_columns(self, db_session, table_name):
        forward, _ = build_create_table(table_name, [
            ('full_name', 'string', None),
            ('score', 'rating', None),
            ('photo', 'image', None),
            ('location', 'coordinates', None),
        ])
        await run(db_session, forward)

        result = await db_session.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = :t ORDER BY column_name"
        ), {'t': table_name})
        columns = {r[0]: r[1] for r in result.all()}

        assert columns['id'] == 'uuid'
        assert columns['tenant_id'] == 'uuid'
        assert columns['is_deleted'] == 'boolean'
        assert columns['created_at'] == 'timestamp with time zone'
        assert columns['full_name'] == 'character varying'
        assert columns['score'] == 'smallint'
        assert columns['location'] == 'jsonb'

        await run(db_session, f'DROP TABLE IF EXISTS {quote_ident(table_name)}')

    async def test_section_header_produces_no_column(self, db_session, table_name):
        forward, _ = build_create_table(table_name, [
            ('intro', 'section_header', None),
            ('name', 'string', None),
        ])
        await run(db_session, forward)

        result = await db_session.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'intro'"
        ), {'t': table_name})
        assert result.scalar() == 0

        await run(db_session, f'DROP TABLE IF EXISTS {quote_ident(table_name)}')

    async def test_table_name_is_not_quoted_so_matches_config_pattern(
        self, db_session, table_name
    ):
        # entity_table_name produces a lowercase, already-safe identifier, so
        # it is used unquoted in DDL. Confirm that is true in the catalog.
        forward, _ = build_create_table(table_name, [])
        await run(db_session, forward)

        result = await db_session.execute(text(
            "SELECT to_regclass(:t) IS NOT NULL"
        ), {'t': table_name})
        assert result.scalar() is True

        await run(db_session, f'DROP TABLE IF EXISTS {quote_ident(table_name)}')


# ══════════════════════════════════════════════════════════════
#  ADD COLUMN
# ══════════════════════════════════════════════════════════════

class TestAddColumn:
    async def test_adds_and_accepts_rows(self, db_session, created, table_name):
        forward, rollback = build_add_column(table_name, 'email', 'email')
        await run(db_session, forward)

        tenant = uuid.uuid4()
        await db_session.execute(text(
            f'INSERT INTO {quote_ident(table_name)} (tenant_id, "email") '
            'VALUES (:t, :e)'
        ), {'t': tenant, 'e': 'a@example.com'})
        await db_session.flush()

        await run(db_session, rollback)

    async def test_rollback_drops_the_column(self, db_session, created, table_name):
        forward, rollback = build_add_column(table_name, 'note', 'text')
        await run(db_session, forward)
        await run(db_session, rollback)

        result = await db_session.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'note'"
        ), {'t': table_name})
        assert result.scalar() == 0

    @pytest.mark.parametrize('field_type', [
        'string', 'text', 'integer', 'float', 'boolean', 'date', 'datetime',
        'time', 'email', 'phone', 'url', 'multiselect', 'file', 'image',
        'signature', 'coordinates', 'address', 'currency', 'rating',
        'lookup', 'computed',
    ])
    async def test_every_column_type_is_valid_postgres(
        self, db_session, created, table_name, field_type
    ):
        forward, _ = build_add_column(table_name, f'f_{field_type}', field_type)
        await run(db_session, forward)

    async def test_not_null_column_on_populated_table_fails(
        self, db_session, created, table_name
    ):
        # Postgres fills an existing row with NULL then applies NOT NULL, so
        # this must fail rather than silently corrupt. The service surfaces
        # it as a validation error; here we only assert the behaviour.
        await db_session.execute(text(
            f'INSERT INTO {quote_ident(table_name)} (tenant_id) VALUES (:t)'
        ), {'t': uuid.uuid4()})
        await db_session.flush()

        forward, _ = build_add_column(table_name, 'req', 'string', nullable=False)
        with pytest.raises(Exception):
            async with savepoint(db_session):
                await run(db_session, forward)


# ══════════════════════════════════════════════════════════════
#  ENUM / RADIO CHECK CONSTRAINTS
# ══════════════════════════════════════════════════════════════

class TestCheckConstraints:
    async def test_accepts_valid_value(self, db_session, created, table_name):
        await run(db_session, build_add_column(
            table_name, 'status', 'enum', options=['new', 'in_progress'])[0])
        await db_session.execute(text(
            f'INSERT INTO {quote_ident(table_name)} (tenant_id, "status") '
            'VALUES (:t, :s)'
        ), {'t': uuid.uuid4(), 's': 'new'})
        await db_session.flush()

    async def test_rejects_value_outside_options(self, db_session, created, table_name):
        await run(db_session, build_add_column(
            table_name, 'status', 'enum', options=['new', 'done'])[0])
        with pytest.raises(Exception):
            async with savepoint(db_session):
                await db_session.execute(text(
                    f'INSERT INTO {quote_ident(table_name)} (tenant_id, "status") '
                    'VALUES (:t, :s)'
                ), {'t': uuid.uuid4(), 's': 'tampered'})

    async def test_accepts_null(self, db_session, created, table_name):
        # This is why the CHECK carries an IS NULL arm.
        await run(db_session, build_add_column(
            table_name, 'status', 'enum', options=['new'])[0])
        await db_session.execute(text(
            f'INSERT INTO {quote_ident(table_name)} (tenant_id, "status") '
            'VALUES (:t, NULL)'
        ), {'t': uuid.uuid4()})
        await db_session.flush()

    async def test_option_containing_sql_is_stored_as_data(
        self, db_session, created, table_name
    ):
        """
        The whole reason quote_literal exists.

        An option value that is itself SQL must round-trip as a string in the
        CHECK, not execute. If escaping were wrong this insert would either
        fail or drop a table.
        """
        hostile = "'); DROP TABLE " + table_name + "; --"
        await run(db_session, build_add_column(
            table_name, 'sneaky', 'enum', options=[hostile, 'benign'])[0])

        await db_session.execute(text(
            f'INSERT INTO {quote_ident(table_name)} (tenant_id, "sneaky") '
            'VALUES (:t, :s)'
        ), {'t': uuid.uuid4(), 's': hostile})
        await db_session.flush()

        # Table still exists, and the hostile value is still only data.
        exists = await db_session.execute(text(
            "SELECT to_regclass(:t) IS NOT NULL"
        ), {'t': table_name})
        assert exists.scalar() is True

    async def test_column_name_cannot_execute(self, db_session, created):
        # A rejected identifier must fail before it ever reaches the server.
        from app.modules.form_builder.schema_sql import SqlGenerationError
        with pytest.raises(SqlGenerationError):
            build_add_column('t', 'x"; DROP TABLE users; --', 'string')


# ══════════════════════════════════════════════════════════════
#  ALTER COLUMN
# ══════════════════════════════════════════════════════════════

class TestAlterColumn:
    async def test_widening_retype(self, db_session, created, table_name):
        await run(db_session, build_add_column(table_name, 'v', 'string')[0])
        await db_session.execute(text(
            f'INSERT INTO {quote_ident(table_name)} (tenant_id, "v") '
            'VALUES (:t, :v)'
        ), {'t': uuid.uuid4(), 'v': 'existing value'})
        await db_session.flush()

        forward, rollback = build_alter_column(table_name, 'v', 'string', 'text')
        await run(db_session, forward)

        stored = await db_session.execute(text(
            f'SELECT "v" FROM {quote_ident(table_name)}'
        ))
        assert stored.scalar() == 'existing value'

        await run(db_session, rollback)

    async def test_retype_into_enum_then_back(self, db_session, created, table_name):
        await run(db_session, build_add_column(table_name, 'v', 'string')[0])

        forward, rollback = build_alter_column(
            table_name, 'v', 'string', 'enum', options=['a', 'b'])
        await run(db_session, forward)

        with pytest.raises(Exception):
            async with savepoint(db_session):
                await db_session.execute(text(
                    f'INSERT INTO {quote_ident(table_name)} (tenant_id, "v") '
                    "VALUES (:t, 'not_allowed')"
                ), {'t': uuid.uuid4()})

        await run(db_session, rollback)

    async def test_widening_from_checked_type_succeeds_and_drops_check(
        self, db_session, created, table_name
    ):
        # enum -> text widens and intentionally drops the CHECK. Existing
        # values that were valid under the old options stay valid, so this must
        # succeed rather than fail on the populated row.
        await run(db_session, build_add_column(
            table_name, 'v', 'enum', options=['a', 'b'])[0])
        await db_session.execute(text(
            f'INSERT INTO {quote_ident(table_name)} (tenant_id, "v") '
            "VALUES (:t, 'a')"
        ), {'t': uuid.uuid4()})
        await db_session.flush()

        forward, _ = build_alter_column(
            table_name, 'v', 'enum', 'text', from_options=['a', 'b'])
        await run(db_session, forward)

        stored = await db_session.execute(text(
            f'SELECT "v" FROM {quote_ident(table_name)}'
        ))
        assert stored.scalar() == 'a'
        # Constraint gone, value preserved. Scope to our named constraint:
        # modern Postgres also materialises implicit CHECKs for NOT NULL
        # columns, so counting every CHECK would count those too.
        constraints = await db_session.execute(text(
            "SELECT count(*) FROM information_schema.table_constraints "
            "WHERE table_name = :t AND constraint_name = :c"
        ), {'t': table_name, 'c': check_constraint_name('v')})
        assert constraints.scalar() == 0

    async def test_narrowing_retype_fails_on_incompatible_row(
        self, db_session, created, table_name
    ):
        # The genuinely destructive case: the row cannot be represented in the
        # new type, so the migration must fail instead of rewriting it.
        await run(db_session, build_add_column(table_name, 'v', 'text')[0])
        await db_session.execute(text(
            f'INSERT INTO {quote_ident(table_name)} (tenant_id, "v") '
            "VALUES (:t, 'not a number')"
        ), {'t': uuid.uuid4()})
        await db_session.flush()

        forward, _ = build_alter_column(table_name, 'v', 'text', 'integer')
        with pytest.raises(Exception):
            async with savepoint(db_session):
                await run(db_session, forward)


# ══════════════════════════════════════════════════════════════
#  INDEX / DROP
# ══════════════════════════════════════════════════════════════

class TestIndexAndDrop:
    async def test_creates_unique_index_and_enforces_it(
        self, db_session, created, table_name
    ):
        await run(db_session, build_add_column(table_name, 'code', 'string')[0])
        await run(db_session, build_index(table_name, 'code', unique=True)[0])

        await db_session.execute(text(
            f'INSERT INTO {quote_ident(table_name)} (tenant_id, "code") '
            "VALUES (:t, 'DUP')"
        ), {'t': uuid.uuid4()})
        await db_session.flush()

        with pytest.raises(Exception):
            async with savepoint(db_session):
                await db_session.execute(text(
                    f'INSERT INTO {quote_ident(table_name)} (tenant_id, "code") '
                    "VALUES (:t, 'DUP')"
                ), {'t': uuid.uuid4()})

    async def test_drop_column_removes_data(self, db_session, created, table_name):
        await run(db_session, build_add_column(table_name, 'gone', 'text')[0])
        await db_session.execute(text(
            f'INSERT INTO {quote_ident(table_name)} (tenant_id, "gone") '
            "VALUES (:t, 'bye')"
        ), {'t': uuid.uuid4()})
        await db_session.flush()

        await run(db_session, build_drop_column(table_name, 'gone')[0])

        # Confirms why drop is flagged irreversible: the rollback can restore
        # the column shape but not this value.
        await run(db_session, build_drop_column(table_name, 'gone')[1])
        result = await db_session.execute(text(
            f'SELECT count(*) FROM {quote_ident(table_name)} WHERE "gone" IS NOT NULL'
        ))
        assert result.scalar() == 0


# ══════════════════════════════════════════════════════════════
#  TRANSACTIONALITY
# ══════════════════════════════════════════════════════════════

class TestTransactional:
    async def test_failed_multi_statement_plan_leaves_no_partial_column(
        self, db_session, created, table_name
    ):
        """
        A retype plan is several statements. If statement 2 fails, the whole
        plan must vanish with the transaction -- otherwise a failed migration
        leaves the table half-migrated.
        """
        await run(db_session, build_add_column(table_name, 'v', 'string')[0])
        await db_session.execute(text(
            f'INSERT INTO {quote_ident(table_name)} (tenant_id, "v") '
            "VALUES (:t, 'not_numeric')"
        ), {'t': uuid.uuid4()})
        await db_session.flush()

        # string -> integer fails on the existing row; VARCHAR(500) -> INTEGER
        forward, _ = build_alter_column(table_name, 'v', 'string', 'integer')
        with pytest.raises(Exception):
            async with savepoint(db_session):
                await run(db_session, forward)

        # Column must still be varchar, i.e. the type change was rolled back.
        result = await db_session.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'v'"
        ), {'t': table_name})
        assert result.scalar() == 'character varying'