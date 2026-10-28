"""SmartOLT integration tables + outage_incidents enhancements

Revision ID: 0039
Revises: 0038
Create Date: 2026-05-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision      = '0039'
down_revision = '0038'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── smartolt_config ──────────────────────────────────────────
    op.create_table(
        "smartolt_config",
        sa.Column("id",                    UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id",             UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_key",               sa.String(255)),
        sa.Column("api_url",               sa.String(500), server_default="https://app.smartolt.com"),
        sa.Column("webhook_secret",        sa.String(255)),
        sa.Column("polling_enabled",       sa.Boolean, server_default="false"),
        sa.Column("polling_interval_secs", sa.Integer, server_default="60"),
        sa.Column("severity_thresholds",   JSONB),
        sa.Column("created_at",            sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at",            sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_smartolt_config_tenant", "smartolt_config", ["tenant_id"], unique=True)

    op.execute("ALTER TABLE smartolt_config ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON smartolt_config
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)

    # ── smartolt_olt_map ─────────────────────────────────────────
    op.create_table(
        "smartolt_olt_map",
        sa.Column("id",               UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id",        UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("smartolt_olt_id",  sa.String(100), nullable=False),
        sa.Column("olt_name",         sa.String(200)),
        sa.Column("region_id",        UUID(as_uuid=True), sa.ForeignKey("regions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("latitude",         sa.Float),
        sa.Column("longitude",        sa.Float),
        sa.Column("is_active",        sa.Boolean, server_default="true"),
        sa.Column("last_synced_at",   sa.DateTime(timezone=True)),
    )
    op.create_index("ix_smartolt_olt_map_tenant_olt", "smartolt_olt_map", ["tenant_id", "smartolt_olt_id"], unique=True)

    op.execute("ALTER TABLE smartolt_olt_map ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON smartolt_olt_map
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)

    # ── outage_incidents — new columns ───────────────────────────
    op.add_column("outage_incidents", sa.Column("source",               sa.String(20),              server_default="manual"))
    op.add_column("outage_incidents", sa.Column("smartolt_event_id",    sa.String(100),             nullable=True))
    op.add_column("outage_incidents", sa.Column("affected_customer_ids",JSONB,                      nullable=True))
    op.add_column("outage_incidents", sa.Column("affected_subscribers", sa.Integer,                 server_default="0"))
    op.add_column("outage_incidents", sa.Column("sla_deadline",         sa.DateTime(timezone=True), nullable=True))
    op.add_column("outage_incidents", sa.Column("breached_sla",         sa.Boolean,                 server_default="false"))
    op.add_column("outage_incidents", sa.Column("linked_task_id",       UUID(as_uuid=True),         sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True))

    op.create_index("ix_outage_smartolt_event",  "outage_incidents", ["smartolt_event_id"],   unique=True,  postgresql_where=sa.text("smartolt_event_id IS NOT NULL"))
    op.create_index("ix_outage_sla_deadline",    "outage_incidents", ["sla_deadline"],         unique=False, postgresql_where=sa.text("sla_deadline IS NOT NULL AND status != 'resolved'"))


def downgrade() -> None:
    op.drop_index("ix_outage_sla_deadline",    table_name="outage_incidents")
    op.drop_index("ix_outage_smartolt_event",  table_name="outage_incidents")
    op.drop_column("outage_incidents", "linked_task_id")
    op.drop_column("outage_incidents", "breached_sla")
    op.drop_column("outage_incidents", "sla_deadline")
    op.drop_column("outage_incidents", "affected_subscribers")
    op.drop_column("outage_incidents", "affected_customer_ids")
    op.drop_column("outage_incidents", "smartolt_event_id")
    op.drop_column("outage_incidents", "source")
    op.drop_table("smartolt_olt_map")
    op.drop_table("smartolt_config")
