"""Shift scheduler tables + outage customer notification tables

Revision ID: 0040
Revises: 0039
Create Date: 2026-05-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision      = '0040'
down_revision = '0039'
branch_labels = None
depends_on    = None

RLS = """
    CREATE POLICY tenant_isolation ON {table}
    USING (
        tenant_id = current_setting('app.tenant_id', TRUE)::uuid
        OR current_setting('app.tenant_id', TRUE) IS NULL
        OR current_setting('app.tenant_id', TRUE) = ''
    )
"""


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(RLS.format(table=table))


def upgrade() -> None:
    # ── shifts ────────────────────────────────────────────────────
    op.create_table(
        "shifts",
        sa.Column("id",          UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id",   UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name",        sa.String(100), nullable=False),
        sa.Column("shift_type",  sa.String(30), server_default="day"),
        sa.Column("start_time",  sa.Time, nullable=False),
        sa.Column("end_time",    sa.Time, nullable=False),
        sa.Column("color",       sa.String(20), server_default="#06b6d4"),
        sa.Column("created_by",  UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_shifts_tenant", "shifts", ["tenant_id"])
    _rls("shifts")

    # ── shift_assignments ─────────────────────────────────────────
    op.create_table(
        "shift_assignments",
        sa.Column("id",          UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id",   UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shift_id",    UUID(as_uuid=True), sa.ForeignKey("shifts.id",  ondelete="CASCADE"), nullable=False),
        sa.Column("user_id",     UUID(as_uuid=True), sa.ForeignKey("users.id",   ondelete="CASCADE"), nullable=False),
        sa.Column("date",        sa.Date, nullable=False),
        sa.Column("status",      sa.String(20), server_default="scheduled"),
        sa.Column("notes",       sa.Text),
        sa.Column("created_by",  UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_shift_assignments_tenant_date", "shift_assignments", ["tenant_id", "date"])
    op.create_index("ix_shift_assignments_user_date",   "shift_assignments", ["user_id", "date"])
    _rls("shift_assignments")

    # ── shift_swap_requests ───────────────────────────────────────
    op.create_table(
        "shift_swap_requests",
        sa.Column("id",                UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id",         UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_assignment_id",UUID(as_uuid=True), sa.ForeignKey("shift_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_user_id",        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason",            sa.Text),
        sa.Column("status",            sa.String(20), server_default="pending"),
        sa.Column("responded_by",      UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("responded_at",      sa.DateTime(timezone=True)),
        sa.Column("created_by",        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at",        sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_shift_swap_tenant", "shift_swap_requests", ["tenant_id"])
    _rls("shift_swap_requests")

    # ── outage_notification_rules ─────────────────────────────────
    op.create_table(
        "outage_notification_rules",
        sa.Column("id",               UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id",        UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name",             sa.String(200), nullable=False),
        sa.Column("min_severity",     sa.String(20), server_default="warning"),
        sa.Column("min_subscribers",  sa.Integer, server_default="0"),
        sa.Column("channels",         JSONB),
        sa.Column("message_template", sa.Text),
        sa.Column("is_auto",          sa.Boolean, server_default="false"),
        sa.Column("is_active",        sa.Boolean, server_default="true"),
        sa.Column("created_by",       UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at",       sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at",       sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_outage_notif_rules_tenant", "outage_notification_rules", ["tenant_id"])
    _rls("outage_notification_rules")

    # ── outage_notification_log ───────────────────────────────────
    op.create_table(
        "outage_notification_log",
        sa.Column("id",            UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id",     UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("outage_id",     UUID(as_uuid=True), sa.ForeignKey("outage_incidents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id",       UUID(as_uuid=True), sa.ForeignKey("outage_notification_rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel",       sa.String(20)),
        sa.Column("recipient",     sa.String(255)),
        sa.Column("status",        sa.String(20), server_default="sent"),
        sa.Column("error_message", sa.Text),
        sa.Column("sent_at",       sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_outage_notif_log_outage", "outage_notification_log", ["outage_id"])
    _rls("outage_notification_log")


def downgrade() -> None:
    op.drop_table("outage_notification_log")
    op.drop_table("outage_notification_rules")
    op.drop_table("shift_swap_requests")
    op.drop_table("shift_assignments")
    op.drop_table("shifts")
