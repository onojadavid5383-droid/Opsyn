"""Form Builder Phase 9 — seed forms.admin permission

Registers the 'forms.admin' feature key in the global feature_permissions
registry and grants it to all roles with level >= 4 in the test tenant.

Gate 1 of check_permission() already passes Admin users (role.level >= 5)
unconditionally, so no DB rows are needed for them. This migration grants
the permission for manager-level users (level 4) so integration tests with
non-admin callers work out of the box.

For production tenants: grant forms.admin via the admin UI using either
role_feature_overrides or department_feature_grants as appropriate.

TEST_TENANT_ID = '00000000-0000-0000-0000-000000000001'

Revision ID: 0083
Revises: 0082
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa

revision      = '0083'
down_revision = '0082'
branch_labels = None
depends_on    = None

_TEST_TENANT = '00000000-0000-0000-0000-000000000001'


def upgrade() -> None:
    conn = op.get_bind()

    # ── Register forms.admin in global feature registry ──────────
    conn.execute(sa.text("""
        INSERT INTO feature_permissions
            (feature_key, feature_label, module, description)
        VALUES
            ('forms.admin',
             'Form Builder Admin',
             'forms',
             'Create and manage form schemas, fields, versions, and associations')
        ON CONFLICT (feature_key) DO NOTHING
    """))

    # ── Seed test tenant only (guard: skip if tenant does not exist) ──
    tenant_exists = conn.execute(
        sa.text("SELECT 1 FROM tenants WHERE id = :tid"),
        {"tid": _TEST_TENANT},
    ).scalar_one_or_none()

    if not tenant_exists:
        return  # Non-test / production environments: grant via admin UI

    # Grant forms.admin to every role in the test tenant with level >= 4.
    # Level 5 = Admin (already bypasses all checks via Gate 1).
    # Level 4 = Manager-equivalent — needs an explicit DB grant.
    roles = conn.execute(
        sa.text("""
            SELECT id
            FROM   roles
            WHERE  tenant_id = :tid
              AND  level >= 4
        """),
        {"tid": _TEST_TENANT},
    ).fetchall()

    for (role_id,) in roles:
        conn.execute(
            sa.text("""
                INSERT INTO role_feature_overrides
                    (tenant_id, role_id, feature_key, is_granted)
                VALUES
                    (:tid, :rid, 'forms.admin', true)
                ON CONFLICT (tenant_id, role_id, feature_key)
                DO UPDATE SET is_granted = true
            """),
            {"tid": _TEST_TENANT, "rid": str(role_id)},
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Remove test-tenant grants
    conn.execute(
        sa.text("""
            DELETE FROM role_feature_overrides
            WHERE  feature_key = 'forms.admin'
              AND  tenant_id   = :tid
        """),
        {"tid": _TEST_TENANT},
    )

    # Remove feature_permissions registry entry
    conn.execute(
        sa.text("DELETE FROM feature_permissions WHERE feature_key = 'forms.admin'"),
    )
