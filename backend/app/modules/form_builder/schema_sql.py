"""
Pure SQL generation for dynamic entity-table DDL.

Every function here is deliberately side-effect free and database-free so the
DDL that will be handed to Postgres can be asserted on directly in unit tests.
The migration service executes what this module produces; it never builds SQL
itself.

Security note
-------------
Table and column names come from user-authored schema names (``machine_name``,
``field_key``) and Postgres has no bind parameter for an identifier. So the
identifiers are *validated against an allowlist-shaped regex and then quoted*,
never interpolated raw. Quoting alone is not the defence -- ``"a"; DROP TABLE
b; --"`` is perfectly legal quoted syntax -- and regex alone is not either, so
both are applied and ``quote_ident`` is the single choke point.

Anything that reaches here that is not a plain identifier (a computed type, a
quoted option literal) is escaped by a dedicated function rather than
concatenated.
"""

from __future__ import annotations

import hashlib
import re
import uuid

# Postgres truncates identifiers at 63 bytes. Dynamic column names are built by
# prefixing user keys, so the budget for the user half is smaller than 63.
MAX_IDENTIFIER_LEN = 63

_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

# Columns the dynamic table infrastructure owns. A form field may not collide
# with these, or a submission would overwrite the tenancy or audit columns.
RESERVED_COLUMNS: frozenset[str] = frozenset({
    'id', 'tenant_id', 'created_at', 'updated_at',
    'created_by', 'updated_by', 'is_deleted', 'deleted_at', 'deleted_by',
})

# Enum/option values arrive as user data, not identifiers. Kept separate so the
# two escaping rules cannot be confused for one another.
_RESERVED_PREFIX = 'tenant_'
_RESERVED_SUFFIX = '_data'


class SqlGenerationError(ValueError):
    """An identifier or value was rejected before it could reach DDL."""


# ══════════════════════════════════════════════════════════════
#  FIELD TYPE MAPPING
# ══════════════════════════════════════════════════════════════

# field_type -> (postgres type, is_reversible)
#
# `is_reversible` is False where the inverse SQL cannot faithfully restore the
# prior state -- dropping a column loses its values, and narrowing a VARCHAR or
# NUMERIC can fail or truncate on existing rows. Those get flagged destructive
# and are refused unless explicitly forced.
FIELD_SQL_TYPES: dict[str, tuple[str, bool]] = {
    'string':         ('VARCHAR(500)',        True),
    'text':           ('TEXT',                True),
    'integer':        ('INTEGER',             True),
    'float':          ('NUMERIC(12,4)',       True),
    'boolean':        ('BOOLEAN',             True),
    'date':           ('DATE',                True),
    'datetime':       ('TIMESTAMPTZ',         True),
    'time':           ('TIME',                True),
    'email':          ('VARCHAR(255)',        True),
    'phone':          ('VARCHAR(50)',         True),
    'url':            ('VARCHAR(1000)',       True),
    'enum':           ('VARCHAR(100)',        True),
    'multiselect':    ('TEXT[]',              True),
    'radio':          ('VARCHAR(100)',        True),
    'file':           ('VARCHAR(500)',        True),
    'image':          ('VARCHAR(500)',        True),
    'signature':      ('VARCHAR(500)',        True),
    'coordinates':    ('JSONB',               True),
    'address':        ('JSONB',               True),
    'currency':       ('NUMERIC(12,2)',       True),
    'rating':         ('SMALLINT',            True),
    'lookup':         ('UUID',                True),
    'computed':       ('TEXT',                True),
    # section_header renders nothing; it has no column at all.
    'section_header': (None,                  True),
}

# Types where choices are enforced with a CHECK constraint.
CHECKED_TYPES: frozenset[str] = frozenset({'enum', 'radio'})

MAX_ENUM_OPTIONS = 200
MAX_OPTION_LENGTH = 100


# ══════════════════════════════════════════════════════════════
#  IDENTIFIER SAFETY
# ══════════════════════════════════════════════════════════════

def validate_identifier(name: object, kind: str = 'identifier') -> str:
    """Return `name` if it is a safe bare identifier, else raise.

    Lowercase-only and ASCII-only on purpose. Folding to lowercase would mean
    two field keys differing only in case collapse onto one column, and
    non-ASCII identifiers interact badly with Postgres' 63-byte truncation.
    """
    if not isinstance(name, str):
        raise SqlGenerationError(f'{kind} must be a string, got {type(name).__name__}')
    if not name:
        raise SqlGenerationError(f'{kind} must not be empty')
    if len(name.encode('utf-8')) > MAX_IDENTIFIER_LEN:
        raise SqlGenerationError(
            f'{kind} {name!r} exceeds {MAX_IDENTIFIER_LEN} bytes'
        )
    if not _IDENTIFIER_RE.match(name):
        raise SqlGenerationError(
            f'{kind} {name!r} is not a valid identifier '
            '(must match [a-z_][a-z0-9_]*)'
        )
    return name


def quote_ident(name: object, kind: str = 'identifier') -> str:
    """Validate then double-quote. The only way an identifier becomes SQL."""
    return '"' + validate_identifier(name, kind) + '"'


def quote_literal(value: object) -> str:
    """Render a user-supplied value as a single-quoted SQL literal.

    Used for CHECK-constraint enum members, which are data, not identifiers.
    Postgres has no bound form for these inside DDL, so escaping is the whole
    defence: double the quote, and reject the characters that would let the
    literal be closed early or change the statement's meaning regardless.
    """
    if not isinstance(value, str):
        raise SqlGenerationError(f'option value must be a string, got {type(value).__name__}')
    if len(value) > MAX_OPTION_LENGTH:
        raise SqlGenerationError(
            f'option value exceeds {MAX_OPTION_LENGTH} characters'
        )
    if '\x00' in value:
        raise SqlGenerationError('option value must not contain a null byte')
    return "'" + value.replace("'", "''") + "'"


def entity_table_name(tenant_id: uuid.UUID, machine_name: str) -> str:
    """
    `tenant_{tenant_id}_{machine_name}_data`, per app.core.config.

    tenant_id is type-checked rather than assumed. It is interpolated as a
    table-name fragment and Postgres has no bind parameter for that, so a
    string reaching here would land in DDL unquoted. uuid.hex is fixed-length
    hex, which is what makes this safe.
    """
    if not isinstance(tenant_id, uuid.UUID):
        raise SqlGenerationError(
            f'tenant_id must be a uuid.UUID, got {type(tenant_id).__name__}'
        )
    validate_identifier(machine_name, 'machine_name')
    return f'{_RESERVED_PREFIX}{tenant_id.hex}_{machine_name}{_RESERVED_SUFFIX}'


# ══════════════════════════════════════════════════════════════
#  STATEMENT BUILDERS
# ══════════════════════════════════════════════════════════════

def check_constraint_name(column: str) -> str:
    """Deterministic CHECK constraint name for a column's option set."""
    return f'{validate_identifier(column, "field_key")}_options_check'


def _options_clause(column: str, field_type: str, options: object) -> str:
    """
    ` CONSTRAINT col_options_check CHECK (col IS NULL OR col = 'a' ...)`
    for enum/radio, else ''.

    The IS NULL arm matters: without it Postgres applies the constraint to
    every existing row during ALTER, and a single NULL in a nullable column
    would fail the whole migration.
    """
    if field_type not in CHECKED_TYPES:
        return ''

    if not isinstance(options, (list, tuple)) or not options:
        raise SqlGenerationError(
            f"'{field_type}' fields require a non-empty 'options' list"
        )
    if len(options) > MAX_ENUM_OPTIONS:
        raise SqlGenerationError(
            f"'{field_type}' fields accept at most {MAX_ENUM_OPTIONS} options"
        )

    seen: set[str] = set()
    literals: list[str] = []
    for opt in options:
        if not isinstance(opt, str):
            raise SqlGenerationError('each option must be a string')
        if opt in seen:
            # Duplicate members make the CHECK unreviewable and usually mean
            # the builder lost data.
            raise SqlGenerationError(f'duplicate option value {opt!r}')
        seen.add(opt)
        literals.append(quote_literal(opt))

    quoted = quote_ident(column, 'field_key')
    predicate = ' OR '.join(f'{quoted} = {lit}' for lit in literals)
    constraint = quote_ident(check_constraint_name(column), 'constraint_name')
    return f' CONSTRAINT {constraint} CHECK ({quoted} IS NULL OR {predicate})'


def _column_clause(
    column: str,
    field_type: str,
    options: object = None,
    nullable: bool = True,
) -> str:
    """One column definition. Returns '' for types with no column."""
    if field_type not in FIELD_SQL_TYPES:
        raise SqlGenerationError(f'unknown field_type {field_type!r}')

    pg_type, _ = FIELD_SQL_TYPES[field_type]
    if pg_type is None:
        # section_header is presentation only.
        return ''

    nullability = '' if nullable else ' NOT NULL'
    return (
        f'{quote_ident(column, "field_key")} {pg_type}{nullability}'
        f'{_options_clause(column, field_type, options)}'
    )


def build_add_column(
    table: str,
    column: str,
    field_type: str,
    options: object = None,
    nullable: bool = True,
) -> tuple[str, str]:
    """(forward, rollback) for ADD COLUMN. rollback is DROP COLUMN."""
    clause = _column_clause(column, field_type, options, nullable)
    if not clause:
        raise SqlGenerationError(
            f"'{field_type}' has no column and cannot be added or dropped"
        )
    tbl = quote_ident(table, 'table_name')
    quoted = quote_ident(column, 'field_key')
    return f'ALTER TABLE {tbl} ADD COLUMN {clause}', f'ALTER TABLE {tbl} DROP COLUMN {quoted}'


def build_drop_column(table: str, column: str) -> tuple[str, str]:
    """
    (forward, rollback) for DROP COLUMN.

    rollback recreates the column *without* its data. There is no way to
    restore dropped values, which is why the plan is marked destructive and
    reversible=False upstream -- the SQL exists so the shape can be inspected,
    not so a rollback can be trusted to recover data.
    """
    tbl = quote_ident(table, 'table_name')
    quoted = quote_ident(column, 'field_key')
    return f'ALTER TABLE {tbl} DROP COLUMN {quoted}', f'ALTER TABLE {tbl} ADD COLUMN {quoted} TEXT'


def build_alter_column(
    table: str,
    column: str,
    from_type: str,
    to_type: str,
    options: object = None,
    from_options: object = None,
) -> tuple[str, str]:
    """
    (forward, rollback) for ALTER COLUMN TYPE.

    Postgres cannot change a column's type while a CHECK constraint on it
    exists, so an option-bearing transition drops the constraint, retypes, and
    re-adds it as three separate statements. Rollback mirrors that in reverse.

    `from_options` is required when the old type is option-bearing. Producing a
    rollback that retypes the column but quietly omits its CHECK would leave
    the table accepting values the form never offered, so that is an error
    rather than a silently degraded rollback. The caller holds the previous
    FieldDefinition and can always supply it.
    """
    if from_type not in FIELD_SQL_TYPES:
        raise SqlGenerationError(f'unknown field_type {from_type!r}')
    if to_type not in FIELD_SQL_TYPES:
        raise SqlGenerationError(f'unknown field_type {to_type!r}')

    old_pg = FIELD_SQL_TYPES[from_type][0]
    new_pg = FIELD_SQL_TYPES[to_type][0]
    if old_pg is None or new_pg is None:
        raise SqlGenerationError(
            f"'{from_type}' -> '{to_type}': section_header has no column"
        )

    tbl = quote_ident(table, 'table_name')
    quoted = quote_ident(column, 'field_key')
    constraint = quote_ident(check_constraint_name(column), 'constraint_name')

    def retype(target_pg: str) -> str:
        return f'ALTER TABLE {tbl} ALTER COLUMN {quoted} TYPE {target_pg}'

    forward_parts = [f'ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS {constraint}',
                     retype(new_pg)]
    rollback_parts = [f'ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS {constraint}',
                      retype(old_pg)]

    new_check = _options_clause(column, to_type, options)
    if new_check:
        # _options_clause already carries a leading space.
        forward_parts.append(f'ALTER TABLE {tbl} ADD{new_check}')

    # Validate before emitting anything, so a missing from_options is an error
    # rather than a half-correct rollback.
    old_check = _options_clause(column, from_type, from_options)
    if old_check:
        rollback_parts.append(f'ALTER TABLE {tbl} ADD{old_check}')

    return ';'.join(forward_parts), ';'.join(rollback_parts)


# The RLS body follows alembic/versions/0029 and 0081/0095: an unset or empty
# app.tenant_id means *unfiltered*, not *no rows*, so Celery workers, admin
# scripts and tests that never set the GUC still work. Tightening this to
# fail-closed would silently break all of them.
#
# One deliberate divergence from those migrations: they cast with a bare
# `current_setting('app.tenant_id', TRUE)::uuid`, which makes the
# `= ''` branch below unreachable. Postgres evaluates the left operand of an
# OR first, so an empty-string GUC raises "invalid input syntax for type uuid:
# ''" instead of reaching that branch. NULLIF makes the empty case behave the
# way the guard always intended. `get_db()` only ever sets a real uuid, so the
# bug is latent rather than live -- but it means the fail-open path cannot be
# exercised, and a fail-open path you cannot test is not one you should rely on.
# A follow-up migration should apply the same NULLIF to the static tables.
_TENANT_GUC = "NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid"
_TENANT_GUC_RAW = "current_setting('app.tenant_id', TRUE)"
_RLS_POLICY_NAME = 'tenant_isolation'


def build_rls(table: str) -> tuple[str, str]:
    """
    (forward, rollback) for the tenant isolation policy on a dynamic table.

    Every static table in this schema gets RLS from an Alembic migration. A
    dynamic entity table cannot: it is created at runtime by this module, so
    there is no migration to enable it and no ORM model to enforce it. The only
    place it can be applied is the CREATE TABLE plan itself, which is why this
    is emitted alongside the DDL rather than as a separate step -- a table must
    never exist, even briefly, without a policy.

    `is_deleted` is deliberately not filtered here. Soft-delete visibility is
    the application layer's job everywhere else in this codebase (see
    form_builder/router.py filtering FieldDefinition.is_deleted). Folding it
    into RLS would make undelete impossible on a table that has no model to
    bypass the policy with.

    Statements are separated by `;` rather than newlines: split_statements
    splits on semicolons, so a newline-joined blob would reach the driver as one
    unparseable statement.
    """
    tbl = quote_ident(table, 'table_name')
    forward = ';\n'.join([
        f'ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY',
        f'ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY',
        f"""CREATE POLICY {_RLS_POLICY_NAME} ON {tbl}
USING (
    tenant_id = {_TENANT_GUC}
    OR {_TENANT_GUC_RAW} IS NULL
    OR {_TENANT_GUC_RAW} = ''
)
WITH CHECK (
    tenant_id = {_TENANT_GUC}
)""",
    ])
    rollback = ';\n'.join([
        f'DROP POLICY IF EXISTS {_RLS_POLICY_NAME} ON {tbl}',
        f'ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY',
    ])
    return forward, rollback


def build_create_table(
    table: str,
    columns: list[tuple[str, str, object]],
) -> tuple[str, str]:
    """
    (forward, rollback) for CREATE TABLE plus its RLS policy.

    `columns` is [(field_key, field_type, options)]. Always carries the
    standard infrastructure columns so the dynamic table has tenancy and audit
    support from the moment it exists.

    The forward SQL is multi-statement, like build_alter_column's. Execute it
    through split_statements() rather than passing the whole string to
    text(), which takes one statement only.
    """
    tbl = quote_ident(table, 'table_name')
    definitions = [
        '"id" UUID PRIMARY KEY DEFAULT gen_random_uuid()',
        '"tenant_id" UUID NOT NULL',
        '"created_at" TIMESTAMPTZ NOT NULL DEFAULT now()',
        '"updated_at" TIMESTAMPTZ NOT NULL DEFAULT now()',
        '"created_by" UUID',
        '"is_deleted" BOOLEAN NOT NULL DEFAULT FALSE',
    ]

    for column, field_type, options in columns:
        clause = _column_clause(column, field_type, options)
        if clause:
            definitions.append(clause)

    create = f'CREATE TABLE {tbl} (\n  ' + ',\n  '.join(definitions) + '\n)'
    rls_forward, rls_rollback = build_rls(table)
    forward   = f'{create};\n{rls_forward}'
    rollback  = f'{rls_rollback};\nDROP TABLE IF EXISTS {tbl}'
    return forward, rollback


def default_index_name(table: str, column: str, unique: bool = False) -> str:
    """
    Derive a legal index name from a table and column.

    The obvious name -- `{table}_{column}_idx` -- overruns Postgres' 63-byte
    limit almost immediately, because an entity table name is already
    `tenant_{32 hex}_{machine_name}_data`. Rather than reject that or let
    Postgres silently truncate it (which turns two distinct indexes into one
    name conflict), truncate explicitly and append a digest of the full name so
    distinct inputs stay distinct.
    """
    validate_identifier(table, 'table_name')
    validate_identifier(column, 'field_key')
    base = f'{table}_{column}' + ('_key' if unique else '_idx')
    if len(base) <= MAX_IDENTIFIER_LEN:
        return base
    digest = hashlib.blake2b(base.encode('utf-8'), digest_size=4).hexdigest()
    keep = MAX_IDENTIFIER_LEN - len(digest) - 1
    return f'{base[:keep]}_{digest}'


def build_index(
    table: str,
    column: str,
    index_name: str | None = None,
    unique: bool = False,
) -> tuple[str, str]:
    """(forward, rollback) for CREATE INDEX."""
    tbl = quote_ident(table, 'table_name')
    idx = quote_ident(
        index_name if index_name is not None else default_index_name(table, column, unique),
        'index_name',
    )
    quoted = quote_ident(column, 'field_key')
    uniqueness = 'UNIQUE ' if unique else ''
    forward = f'CREATE {uniqueness}INDEX {idx} ON {tbl} ({quoted})'
    rollback = f'DROP INDEX IF EXISTS {idx}'
    return forward, rollback


def split_statements(sql: str) -> list[str]:
    """
    Split a multi-statement plan into individual statements.

    A naive `sql.split(';')` is wrong here: the CHECK constraints this module
    emits can contain semicolons inside quoted option literals, and the forward
    SQL for an alter_column is deliberately several statements joined by `;`.
    So track quote state rather than splitting blindly.
    """
    statements: list[str] = []
    current: list[str] = []
    in_literal = False
    index = 0
    length = len(sql)

    while index < length:
        char = sql[index]
        if in_literal:
            if char == "'":
                # Doubled '' is an escaped quote, not a terminator.
                if index + 1 < length and sql[index + 1] == "'":
                    current.append("''")
                    index += 2
                    continue
                in_literal = False
            current.append(char)
        elif char == "'":
            in_literal = True
            current.append(char)
        elif char == ';':
            statement = ''.join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)
        index += 1

    tail = ''.join(current).strip()
    if tail:
        statements.append(tail)
    return statements