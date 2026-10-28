"""Make the tenant_isolation policy's uuid cast NULL-safe

Every static table with RLS got the same policy body from 0029, copied forward
by 0081, 0095 and ~20 others:

    USING (
        tenant_id = current_setting('app.tenant_id', TRUE)::uuid
        OR current_setting('app.tenant_id', TRUE) IS NULL
        OR current_setting('app.tenant_id', TRUE) = ''
    )

That body does not do what it reads like. Postgres evaluates an OR's left
operand first, so an empty-string GUC raises

    ERROR: invalid input syntax for type uuid: ""

before the `= ''` branch on the right can be reached. The fail-open guard is
unreachable code.

This is latent rather than live: app/core/database.py only ever sets a real
uuid, so the empty case does not occur on the request path. It still matters,
for two reasons. The guard is the reason these policies fail open at all, and
it cannot be exercised while it throws -- a fail-open branch nobody can test is
not one to rely on. And a blank value is the obvious thing for a future
non-request caller to send.

So the cast becomes NULLIF(current_setting(...), '')::uuid, which yields NULL
instead of raising and makes the empty case behave the way the guard always
intended. This matches form_builder.schema_sql.build_rls, which already
emitted NULLIF.

Scope, deliberately narrow:

  * Tables are discovered from pg_policy, never hardcoded. A hardcoded list
    would rot the moment a table is added, and 23 migrations each redeclaring
    this policy is already how the list drifted in the first place.
  * Only the cast is rewritten. Each policy's USING and WITH CHECK expressions
    are deparsed, textually patched and re-applied as-is. In particular
    WITH CHECK is *not* added to the ~69 policies that have none: no
    WITH CHECK means Postgres falls back to USING for writes, and since USING
    fails open those tables accept a cross-tenant write today. Tightening that
    is a real behaviour change needing its own review and backfill, and does
    not belong in a migration that claims to fix a cast.
  * Policies already using NULLIF are skipped, so re-running is a no-op.

Downgrade restores the bare cast, i.e. the pre-existing behaviour including the
throw.
"""

from __future__ import annotations

from alembic import op

revision      = '0097'
down_revision = '0096'

POLICY = 'tenant_isolation'


def _sql_literal(value: str) -> str:
    """Quote a Python string as an SQL string literal.

    Double quotes would be an *identifier* in Postgres, so the literals below
    have to be single-quoted with internal quotes doubled.
    """
    return "'" + value.replace("'", "''") + "'"


# These are deparsed expressions, not the DDL we wrote: Postgres normalises the
# string literal to `::text` inside current_setting(). Matching the deparsed
# form is what makes the replace() below match.
BARE_CAST   = "(current_setting('app.tenant_id'::text, true))::uuid"
NULLIF_CAST = (
    "(NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid"
)

BARE_CAST_SQL   = _sql_literal(BARE_CAST)
NULLIF_CAST_SQL = _sql_literal(NULLIF_CAST)


def _rewrite(target_is_nullif: bool) -> None:
    """
    Recreate every tenant_isolation policy with the other cast.

    Runs as a DO block so the catalog read and the DDL share one transaction
    and ~90 rows never cross the driver boundary just to be looped over.
    """
    old_cast, new_cast = (
        (NULLIF_CAST_SQL, BARE_CAST_SQL) if target_is_nullif
        else (BARE_CAST_SQL, NULLIF_CAST_SQL)
    )
    required, excluded = ('%NULLIF%', '%current_setting%') if target_is_nullif else (
        '%current_setting%', '%NULLIF%'
    )

    op.execute(f"""
        DO $$
        DECLARE
            r       record;
            patched text;
            n_patched integer := 0;
        BEGIN
            FOR r IN
                SELECT c.relname                             AS table_name,
                       pg_get_expr(p.polqual, p.polrelid)      AS qual,
                       pg_get_expr(p.polwithcheck, p.polrelid) AS with_check
                FROM pg_policy p
                JOIN pg_class c ON c.oid = p.polrelid
                WHERE p.polname    = '{POLICY}'
                  AND p.polqual IS NOT NULL
                  AND pg_get_expr(p.polqual, p.polrelid) LIKE '{required}'
                  AND pg_get_expr(p.polqual, p.polrelid) NOT LIKE '{excluded}'
            LOOP
                patched := replace(r.qual, {old_cast}, {new_cast});

                EXECUTE format('DROP POLICY %I ON %I', '{POLICY}', r.table_name);

                IF r.with_check IS NULL THEN
                    -- Deliberately left without WITH CHECK. See docstring.
                    EXECUTE format(
                        'CREATE POLICY %I ON %I USING (%s)',
                        '{POLICY}', r.table_name, patched
                    );
                ELSE
                    EXECUTE format(
                        'CREATE POLICY %I ON %I USING (%s) WITH CHECK (%s)',
                        '{POLICY}', r.table_name, patched,
                        replace(r.with_check, {old_cast}, {new_cast})
                    );
                END IF;

                n_patched := n_patched + 1;
            END LOOP;

            RAISE NOTICE 'tenant_isolation: rewrote % policies', n_patched;
        END $$;
    """)


def upgrade() -> None:
    _rewrite(target_is_nullif=False)


def downgrade() -> None:
    _rewrite(target_is_nullif=True)