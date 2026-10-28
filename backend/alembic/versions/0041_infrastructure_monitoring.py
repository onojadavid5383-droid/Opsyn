"""
OPSYN INFRASTRUCTURE MONITORING — MIGRATION 0041
Adds capacity/port tracking and monitoring configuration:
  infra_ports              — per-node port utilisation data
  infra_subscribers        — subscriber records tied to nodes/sites
  infra_capacity_alerts    — triggered threshold breach events
  infra_monitoring_config  — per-entity warn/critical thresholds
  infra_alert_rules        — conditional trigger rules for alerting

Also adds is_monitored flag to infrastructure_sites.
All tables tenant-scoped with RLS.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0041'
down_revision = '0040'
branch_labels = None
depends_on    = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)


def upgrade() -> None:
    # ── is_monitored flag on infrastructure_sites ──────────────
    op.add_column(
        'infrastructure_sites',
        sa.Column('is_monitored', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )

    # ── infra_ports ────────────────────────────────────────────
    op.create_table(
        'infra_ports',
        sa.Column('id',             postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',      postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('node_id',        postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('port_number',    sa.String(20),  nullable=False),
        sa.Column('port_type',      sa.String(30),  nullable=False, server_default=sa.text("'GPON'")),
        sa.Column('total_capacity', sa.Integer(),   nullable=False, server_default=sa.text('128')),
        sa.Column('used_capacity',  sa.Integer(),   nullable=False, server_default=sa.text('0')),
        sa.Column('status',         sa.String(20),  nullable=False, server_default=sa.text("'active'")),
        sa.Column('last_synced_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at',     sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at',     sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_foreign_key(
        'fk_infra_ports_tenant', 'infra_ports', 'tenants',
        ['tenant_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_infra_ports_node', 'infra_ports', 'infrastructure_nodes',
        ['node_id'], ['id'], ondelete='CASCADE',
    )
    op.create_unique_constraint('uq_infra_port_node_number', 'infra_ports', ['tenant_id', 'node_id', 'port_number'])
    op.create_index('ix_infra_ports_tenant', 'infra_ports', ['tenant_id'])
    op.create_index('ix_infra_ports_node',   'infra_ports', ['node_id'])
    _rls('infra_ports')

    # ── infra_subscribers ──────────────────────────────────────
    op.create_table(
        'infra_subscribers',
        sa.Column('id',           postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',    postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id',  sa.String(100), nullable=False),
        sa.Column('site_id',      postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('node_id',      postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('port_id',      postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('service_type', sa.String(50),  nullable=False, server_default=sa.text("'FTTH'")),
        sa.Column('status',       sa.String(20),  nullable=False, server_default=sa.text("'active'")),
        sa.Column('address',      sa.Text(),      nullable=True),
        sa.Column('latitude',     sa.Numeric(10, 7), nullable=True),
        sa.Column('longitude',    sa.Numeric(10, 7), nullable=True),
        sa.Column('created_at',   sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at',   sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_foreign_key(
        'fk_infra_subs_tenant', 'infra_subscribers', 'tenants',
        ['tenant_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_infra_subs_site', 'infra_subscribers', 'infrastructure_sites',
        ['site_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_infra_subs_node', 'infra_subscribers', 'infrastructure_nodes',
        ['node_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_infra_subs_port', 'infra_subscribers', 'infra_ports',
        ['port_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_infra_subs_tenant',      'infra_subscribers', ['tenant_id'])
    op.create_index('ix_infra_subs_customer_id', 'infra_subscribers', ['customer_id'])
    _rls('infra_subscribers')

    # ── infra_capacity_alerts ──────────────────────────────────
    op.create_table(
        'infra_capacity_alerts',
        sa.Column('id',              postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',       postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('site_id',         postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('node_id',         postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('alert_type',      sa.String(30), nullable=False, server_default=sa.text("'capacity'")),
        sa.Column('severity',        sa.String(20), nullable=False, server_default=sa.text("'warning'")),
        sa.Column('threshold_pct',   sa.Integer(),  nullable=False),
        sa.Column('current_pct',     sa.Integer(),  nullable=False),
        sa.Column('message',         sa.Text(),     nullable=True),
        sa.Column('is_resolved',     sa.Boolean(),  nullable=False, server_default=sa.text('false')),
        sa.Column('resolved_at',     sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('linked_task_id',  postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at',      sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_foreign_key(
        'fk_infra_alerts_tenant', 'infra_capacity_alerts', 'tenants',
        ['tenant_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_infra_alerts_site', 'infra_capacity_alerts', 'infrastructure_sites',
        ['site_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_infra_alerts_node', 'infra_capacity_alerts', 'infrastructure_nodes',
        ['node_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_infra_alerts_task', 'infra_capacity_alerts', 'tasks',
        ['linked_task_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_infra_alerts_tenant',      'infra_capacity_alerts', ['tenant_id'])
    op.create_index('ix_infra_alerts_unresolved',  'infra_capacity_alerts', ['tenant_id', 'is_resolved'])
    _rls('infra_capacity_alerts')

    # ── infra_monitoring_config ────────────────────────────────
    op.create_table(
        'infra_monitoring_config',
        sa.Column('id',                     postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',              postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('entity_type',            sa.String(30), nullable=False),
        sa.Column('entity_id',              postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('warn_threshold_pct',     sa.Integer(), nullable=False, server_default=sa.text('70')),
        sa.Column('critical_threshold_pct', sa.Integer(), nullable=False, server_default=sa.text('90')),
        sa.Column('check_interval_minutes', sa.Integer(), nullable=False, server_default=sa.text('15')),
        sa.Column('alert_channels',         postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('assigned_role_level',    sa.Integer(), nullable=False, server_default=sa.text('2')),
        sa.Column('is_active',              sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at',             sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at',             sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_foreign_key(
        'fk_infra_mon_config_tenant', 'infra_monitoring_config', 'tenants',
        ['tenant_id'], ['id'], ondelete='CASCADE',
    )
    op.create_unique_constraint(
        'uq_infra_mon_entity', 'infra_monitoring_config', ['tenant_id', 'entity_type', 'entity_id'],
    )
    op.create_index('ix_infra_mon_config_tenant', 'infra_monitoring_config', ['tenant_id'])
    _rls('infra_monitoring_config')

    # ── infra_alert_rules ──────────────────────────────────────
    op.create_table(
        'infra_alert_rules',
        sa.Column('id',               postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',        postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name',             sa.String(200), nullable=False),
        sa.Column('condition_field',  sa.String(50),  nullable=False),
        sa.Column('operator',         sa.String(10),  nullable=False, server_default=sa.text("'gt'")),
        sa.Column('threshold_value',  sa.Numeric(10, 2), nullable=False),
        sa.Column('severity',         sa.String(20),  nullable=False, server_default=sa.text("'warning'")),
        sa.Column('action_type',      sa.String(30),  nullable=False, server_default=sa.text("'notify'")),
        sa.Column('action_params',    postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('is_active',        sa.Boolean(),   nullable=False, server_default=sa.text('true')),
        sa.Column('created_at',       sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_foreign_key(
        'fk_infra_alert_rules_tenant', 'infra_alert_rules', 'tenants',
        ['tenant_id'], ['id'], ondelete='CASCADE',
    )
    op.create_index('ix_infra_alert_rules_tenant', 'infra_alert_rules', ['tenant_id'])
    _rls('infra_alert_rules')


def downgrade() -> None:
    for tbl in ('infra_alert_rules', 'infra_monitoring_config',
                'infra_capacity_alerts', 'infra_subscribers', 'infra_ports'):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl}")
        op.drop_table(tbl)
    op.drop_column('infrastructure_sites', 'is_monitored')
