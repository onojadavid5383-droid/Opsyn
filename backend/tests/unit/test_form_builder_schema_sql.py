"""
Unit tests for dynamic-DDL SQL generation.

schema_sql turns user-supplied schema and field names into DDL, so these tests
are as much a security boundary as a correctness suite. The injection cases
below are the reason quote_ident exists at all.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.form_builder.models import FIELD_TYPES
from app.modules.form_builder.schema_sql import (
    CHECKED_TYPES,
    FIELD_SQL_TYPES,
    MAX_ENUM_OPTIONS,
    RESERVED_COLUMNS,
    SqlGenerationError,
    build_add_column,
    build_alter_column,
    build_create_table,
    build_drop_column,
    build_index,
    build_rls,
    check_constraint_name,
    default_index_name,
    entity_table_name,
    quote_ident,
    quote_literal,
    split_statements,
    validate_identifier,
)


# ══════════════════════════════════════════════════════════════
#  IDENTIFIER SAFETY
# ══════════════════════════════════════════════════════════════

class TestIdentifierSafety:
    def test_accepts_normal_names(self):
        assert validate_identifier('customer_address') == 'customer_address'
        assert validate_identifier('_private') == '_private'
        assert validate_identifier('field2') == 'field2'

    @pytest.mark.parametrize('name', [
        'col"; DROP TABLE users; --',      # statement break-out
        "col'; DROP TABLE users; --",      # via a string literal
        'col; DROP TABLE users',
        'col name',                        # space
        'col-name',                        # dash
        '1col',                            # leading digit
        '',                                # empty
        'COL',                             # uppercase
        'café',                     # non-ascii
        'col$',
        'col()',
        'col--comment',
    ])
    def test_rejects_unsafe_names(self, name):
        with pytest.raises(SqlGenerationError):
            validate_identifier(name)

    def test_rejects_non_string(self):
        with pytest.raises(SqlGenerationError):
            validate_identifier(123)
        with pytest.raises(SqlGenerationError):
            validate_identifier(None)

    def test_rejects_over_length(self):
        # Postgres truncates at 63 bytes; a name near that that crosses it
        # would silently collide with a different field.
        validate_identifier('a' * 63)
        with pytest.raises(SqlGenerationError):
            validate_identifier('a' * 64)

    def test_quoted_output_is_always_double_quoted(self):
        assert quote_ident('abc') == '"abc"'

    def test_quoted_output_cannot_contain_a_bare_quote(self):
        # Belt and braces: even though the regex already rejects these, the
        # guarantee the rest of the code relies on is that quote_ident output
        # has no way to terminate the identifier early.
        for name in ['abc', 'a_b_1']:
            assert '"' not in quote_ident(name)[1:-1]


# ══════════════════════════════════════════════════════════════
#  LITERAL ESCAPING
# ══════════════════════════════════════════════════════════════

class TestLiteralEscaping:
    def test_plain_value(self):
        assert quote_literal('Lagos') == "'Lagos'"

    def test_doubles_embedded_quote(self):
        assert quote_literal("O'Brien") == "'O''Brien'"

    def test_rejects_null_byte(self):
        with pytest.raises(SqlGenerationError):
            quote_literal('a\x00b')

    def test_rejects_over_length(self):
        with pytest.raises(SqlGenerationError):
            quote_literal('x' * 101)

    def test_rejects_non_string(self):
        with pytest.raises(SqlGenerationError):
            quote_literal(5)


# ══════════════════════════════════════════════════════════════
#  TABLE NAMING
# ══════════════════════════════════════════════════════════════

class TestTableNaming:
    def test_shape(self):
        tenant = uuid.uuid4()
        assert entity_table_name(tenant, 'customer') == \
            f'tenant_{tenant.hex}_customer_data'

    def test_rejects_injection_in_machine_name(self):
        tenant = uuid.uuid4()
        with pytest.raises(SqlGenerationError):
            entity_table_name(tenant, 'customer"; DROP TABLE users; --')

    def test_tenant_id_cannot_be_injected(self):
        # tenant_id is a UUID, never a string -- assert the type guard holds
        # rather than relying on the caller to have validated it.
        with pytest.raises(SqlGenerationError):
            entity_table_name('1; DROP TABLE users', 'customer')


# ══════════════════════════════════════════════════════════════
#  TYPE MAPPING
# ══════════════════════════════════════════════════════════════

class TestTypeMapping:
    def test_covers_every_declared_field_type(self):
        # A field type the CHECK constraint accepts but the DDL generator does
        # not know would fail at plan time with a confusing error.
        assert set(FIELD_TYPES) <= set(FIELD_SQL_TYPES)

    def test_kobo_aligned_types(self):
        assert FIELD_SQL_TYPES['string'][0] == 'VARCHAR(500)'
        assert FIELD_SQL_TYPES['text'][0] == 'TEXT'
        assert FIELD_SQL_TYPES['integer'][0] == 'INTEGER'
        assert FIELD_SQL_TYPES['float'][0] == 'NUMERIC(12,4)'
        assert FIELD_SQL_TYPES['currency'][0] == 'NUMERIC(12,2)'
        assert FIELD_SQL_TYPES['coordinates'][0] == 'JSONB'
        assert FIELD_SQL_TYPES['multiselect'][0] == 'TEXT[]'
        assert FIELD_SQL_TYPES['datetime'][0] == 'TIMESTAMPTZ'
        assert FIELD_SQL_TYPES['lookup'][0] == 'UUID'

    def test_section_header_has_no_column(self):
        assert FIELD_SQL_TYPES['section_header'][0] is None


# ══════════════════════════════════════════════════════════════
#  STATEMENT BUILDERS
# ══════════════════════════════════════════════════════════════

class TestAddColumn:
    def test_basic(self):
        forward, rollback = build_add_column('t', 'age', 'integer')
        assert forward == 'ALTER TABLE "t" ADD COLUMN "age" INTEGER'
        assert rollback == 'ALTER TABLE "t" DROP COLUMN "age"'

    def test_not_null(self):
        forward, _ = build_add_column('t', 'age', 'integer', nullable=False)
        assert forward.endswith('INTEGER NOT NULL')

    def test_enum_gets_null_tolerant_check(self):
        forward, _ = build_add_column('t', 'status', 'enum', options=['new', 'old'])
        # The IS NULL arm is what lets this apply to a table with existing rows.
        assert '"status" IS NULL' in forward
        assert '"status" = \'new\'' in forward
        assert '"status" = \'old\'' in forward

    def test_escaped_option_cannot_break_out(self):
        forward, _ = build_add_column(
            't', 'status', 'enum', options=["x'); DROP TABLE users; --"]
        )
        # The dangerous text survives only as an escaped literal; the statement
        # still contains exactly one unescaped terminator structure.
        assert "x''); DROP TABLE users; --" in forward
        assert forward.count(' CHECK (') == 1

    def test_quote_in_option_does_not_fool_statement_splitter(self):
        forward, _ = build_add_column('t', 'c', 'enum', options=["a'; DROP TABLE t; --"])
        statements = split_statements(forward)
        assert len(statements) == 1

    def test_enum_requires_options(self):
        with pytest.raises(SqlGenerationError):
            build_add_column('t', 'status', 'enum', options=[])
        with pytest.raises(SqlGenerationError):
            build_add_column('t', 'status', 'enum', options=None)

    def test_rejects_duplicate_options(self):
        with pytest.raises(SqlGenerationError):
            build_add_column('t', 'status', 'enum', options=['a', 'a'])

    def test_rejects_too_many_options(self):
        opts = [f'o{i}' for i in range(MAX_ENUM_OPTIONS + 1)]
        with pytest.raises(SqlGenerationError):
            build_add_column('t', 'status', 'enum', options=opts)

    def test_plain_type_ignores_options(self):
        forward, _ = build_add_column('t', 'name', 'string', options=['a', 'b'])
        assert 'CHECK' not in forward

    def test_section_header_cannot_be_a_column(self):
        with pytest.raises(SqlGenerationError):
            build_add_column('t', 'header', 'section_header')

    def test_unknown_type_rejected(self):
        with pytest.raises(SqlGenerationError):
            build_add_column('t', 'x', 'not_a_type')


class TestDropColumn:
    def test_round_trip_shape(self):
        forward, rollback = build_drop_column('t', 'age')
        assert forward == 'ALTER TABLE "t" DROP COLUMN "age"'
        assert rollback == 'ALTER TABLE "t" ADD COLUMN "age" TEXT'

    def test_rejects_unsafe_column(self):
        with pytest.raises(SqlGenerationError):
            build_drop_column('t', 'age"; DROP TABLE users; --')


class TestAlterColumn:
    def test_simple_retype(self):
        forward, rollback = build_alter_column('t', 'x', 'string', 'text')
        assert 'DROP CONSTRAINT IF EXISTS' in forward
        assert 'ALTER COLUMN "x" TYPE TEXT' in forward
        assert 'TYPE VARCHAR(500)' in rollback

    def test_retype_into_option_type_drops_and_readds_check(self):
        forward, _ = build_alter_column('t', 'x', 'string', 'enum', options=['a'])
        assert forward.count('DROP CONSTRAINT IF EXISTS') == 1
        assert 'ADD CONSTRAINT' in forward
        assert 'CHECK' in forward

    def test_checked_to_unchecked_drops_constraint(self):
        forward, rollback = build_alter_column(
            't', 'x', 'enum', 'text', from_options=['a']
        )
        assert 'DROP CONSTRAINT IF EXISTS' in forward
        assert 'CHECK' not in forward
        assert 'DROP CONSTRAINT IF EXISTS' in rollback

    def test_rollback_refuses_to_silently_drop_the_old_check(self):
        # enum -> text with no from_options would produce a rollback that
        # retypes the column but leaves it with no CHECK at all. That is a
        # degraded rollback, not a correct one, so it must be an error.
        with pytest.raises(SqlGenerationError):
            build_alter_column('t', 'x', 'enum', 'text')

    def test_rejects_unknown_types(self):
        with pytest.raises(SqlGenerationError):
            build_alter_column('t', 'x', 'nope', 'text')
        with pytest.raises(SqlGenerationError):
            build_alter_column('t', 'x', 'string', 'nope')


class TestCreateTable:
    def test_includes_infrastructure_columns(self):
        forward, rollback = build_create_table('t', [('name', 'string', None)])
        assert '"tenant_id" UUID NOT NULL' in forward
        assert '"id" UUID PRIMARY KEY' in forward
        assert '"is_deleted" BOOLEAN NOT NULL' in forward
        # Multi-statement now: the policy must be removed before the drop.
        assert rollback.endswith('DROP TABLE IF EXISTS "t"')
        assert 'DROP POLICY IF EXISTS tenant_isolation ON "t"' in rollback

    def test_skips_section_header_but_keeps_others(self):
        forward, _ = build_create_table(
            't', [('hdr', 'section_header', None), ('name', 'string', None)]
        )
        assert '"hdr"' not in forward
        assert '"name"' in forward

    def test_unsafe_column_rejected(self):
        with pytest.raises(SqlGenerationError):
            build_create_table('t', [('x"; DROP TABLE users; --', 'string', None)])

    def test_create_then_rls_in_one_plan(self):
        """A dynamic table must never exist unprotected, even for a moment."""
        forward, _ = build_create_table('t', [])
        statements = split_statements(forward)
        assert statements[0].startswith('CREATE TABLE')
        assert any('ENABLE ROW LEVEL SECURITY' in st for st in statements)
        assert any('CREATE POLICY' in st for st in statements)
        # Policy creation is dead weight without ENABLE, and ENABLE without
        # FORCE is bypassable by the table owner -- both are required.
        assert 'FORCE ROW LEVEL SECURITY' in forward

    def test_forward_sql_splits_into_exactly_four_statements(self):
        """Pins the split count.

        The policy body contains an `= ''` comparison whose doubled quote
        looks like an escaped quote to split_statements, so it stays in-literal
        mode until the next lone quote. That is harmless only because no
        semicolon appears between them; this assertion is what makes that
        assumption fail loudly if the policy text is ever reworded.
        """
        forward, _ = build_create_table('t', [])
        assert len(split_statements(forward)) == 4


class TestRlsPolicy:
    def test_matches_the_0029_semantics(self):
        forward, _ = build_rls('t')
        assert 'ALTER TABLE "t" ENABLE ROW LEVEL SECURITY' in forward
        assert 'ALTER TABLE "t" FORCE ROW LEVEL SECURITY' in forward
        assert 'CREATE POLICY tenant_isolation ON "t"' in forward
        # Fail-open on an unset GUC, exactly like 0029/0081/0095.
        assert "current_setting('app.tenant_id', TRUE) IS NULL" in forward
        assert "current_setting('app.tenant_id', TRUE) = ''" in forward
        # A read filter alone is not enough: writes must be constrained too.
        assert 'WITH CHECK' in forward

    def test_empty_guc_casts_to_null_not_an_error(self):
        """
        The cast is NULLIF-wrapped so the `= ''` branch is actually reachable.

        With the bare cast these migrations use, Postgres evaluates the left
        operand first and raises "invalid input syntax for type uuid: ''" on an
        empty GUC, so the empty-string guard is dead code.
        """
        forward, _ = build_rls('t')
        assert "NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid" in forward
        assert "current_setting('app.tenant_id', TRUE)::uuid" not in forward

    def test_rollback_drops_policy_before_table(self):
        _, rollback = build_rls('t')
        assert rollback.splitlines()[0].startswith('DROP POLICY IF EXISTS')
        assert 'DISABLE ROW LEVEL SECURITY' in rollback

    def test_unsafe_table_rejected(self):
        with pytest.raises(SqlGenerationError):
            build_rls('t"; DROP TABLE users; --')

    def test_soft_delete_is_not_part_of_the_policy(self):
        """Documented decision, so assert it rather than trusting the docstring."""
        forward, _ = build_rls('t')
        assert 'is_deleted' not in forward


class TestIndex:
    def test_plain(self):
        forward, rollback = build_index('t', 'email', 'idx_t_email')
        assert forward == 'CREATE INDEX "idx_t_email" ON "t" ("email")'
        assert rollback == 'DROP INDEX IF EXISTS "idx_t_email"'

    def test_unique(self):
        forward, _ = build_index('t', 'email', 'idx_t_email', unique=True)
        assert forward.startswith('CREATE UNIQUE INDEX')

    def test_unsafe_index_name_rejected(self):
        with pytest.raises(SqlGenerationError):
            build_index('t', 'email', 'idx"; DROP TABLE users; --')


class TestDefaultIndexName:
    """
    Entity table names are already ~45 bytes, so the obvious index name
    overruns Postgres' 63-byte limit. These cases pin the truncation.
    """

    def test_short_name_is_used_verbatim(self):
        assert default_index_name('users', 'email') == 'users_email_idx'

    def test_unique_gets_key_suffix(self):
        assert default_index_name('users', 'email', unique=True) == 'users_email_key'

    def test_long_name_is_truncated_to_the_limit(self):
        table = entity_table_name(uuid.uuid4(), 'testentity')
        name = default_index_name(table, 'customer_reference_code')
        assert len(name.encode()) <= 63

    def test_truncation_is_deterministic(self):
        table = entity_table_name(uuid.uuid4(), 'testentity')
        assert default_index_name(table, 'a_very_long_column_name_here') == \
            default_index_name(table, 'a_very_long_column_name_here')

    def test_distinct_inputs_stay_distinct_after_truncation(self):
        # The reason a digest is appended rather than a plain slice: two long
        # names sharing a 54-char prefix would otherwise collide.
        table = entity_table_name(uuid.uuid4(), 'testentity')
        a = default_index_name(table, 'a_very_long_column_name_here')
        b = default_index_name(table, 'a_very_long_column_name_there')
        assert a != b


# ══════════════════════════════════════════════════════════════
#  RESERVED COLUMNS
# ══════════════════════════════════════════════════════════════

class TestReservedColumns:
    @pytest.mark.parametrize('column', sorted(RESERVED_COLUMNS))
    def test_infrastructure_columns_are_reserved(self, column):
        assert column in RESERVED_COLUMNS

    def test_reserved_names_are_still_valid_identifiers(self):
        # The reserved set guards *policy*, not syntax: these must still pass
        # validate_identifier, and be rejected by the service layer instead.
        # If this ever fails the two checks have been conflated.
        for column in RESERVED_COLUMNS:
            assert validate_identifier(column) == column


# ══════════════════════════════════════════════════════════════
#  STATEMENT SPLITTING
# ══════════════════════════════════════════════════════════════

class TestSplitStatements:
    def test_single(self):
        assert split_statements('SELECT 1') == ['SELECT 1']

    def test_multiple(self):
        assert split_statements('SELECT 1; SELECT 2;') == ['SELECT 1', 'SELECT 2']

    def test_ignores_empty_segments(self):
        assert split_statements('  ;; SELECT 1 ;; ') == ['SELECT 1']

    def test_keeps_semicolon_inside_literal(self):
        assert split_statements("SELECT 'a;b'") == ["SELECT 'a;b'"]

    def test_handles_doubled_quote_inside_literal(self):
        assert split_statements("SELECT 'a''b;c'") == ["SELECT 'a''b;c'"]

    def test_alter_column_forward_splits_into_three(self):
        forward, _ = build_alter_column('t', 'x', 'string', 'enum', options=['a'])
        assert len(split_statements(forward)) == 3