"""Scope username uniqueness to the tenant

`users.username` carried a GLOBAL unique constraint, but Opsyn is
multi-tenant and the username is generated from the person's name:

    app/modules/auth/router.py:376
    username = f"{payload.first_name.lower()}.{payload.last_name.lower()}"

So the second organisation to register anyone called (say) "Jane Admin"
hit users_username_key and the endpoint returned 500 Internal Server
Error. Two unrelated companies could not both employ a Jane Admin.

Reproduced before this migration:
    POST /auth/register-tenant  org 1, "Janeprobe Uniqtest"  -> 201
    POST /auth/register-tenant  org 2, same person name      -> 500

This replaces UNIQUE (username) with UNIQUE (tenant_id, username).

Safe to apply: the new constraint is strictly more permissive than the
old one, so no existing row can violate it.

`users.email` is deliberately left globally unique -- login resolves a
user by email alone (auth/router.py:56), so it must stay unambiguous
across tenants.

Revision ID: 0084
Revises: 0083
Create Date: 2026-09-16
"""

from alembic import op

revision      = "0084"
down_revision = "0083"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.drop_constraint("users_username_key", "users", type_="unique")
    op.create_unique_constraint(
        "uq_users_tenant_username", "users", ["tenant_id", "username"]
    )


def downgrade() -> None:
    # Only reversible while no two tenants share a username.
    op.drop_constraint("uq_users_tenant_username", "users", type_="unique")
    op.create_unique_constraint("users_username_key", "users", ["username"])
