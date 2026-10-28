"""
OPSYN INFRASTRUCTURE MAP — MIGRATION 0032
FTTx network asset registry:
  infrastructure_sites  — physical locations (POPs, exchanges, cabinets)
  infrastructure_nodes  — network equipment (OLTs, aggregation switches, core)
  infrastructure_routes — fiber routes connecting nodes

All tables are tenant-scoped with RLS.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0032'
down_revision = '0031'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── infrastructure_sites ──────────────────────────────────
    op.create_table(
        'infrastructure_sites',
        sa.Column('id',          postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',   postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name',        sa.String(200), nullable=False),
        sa.Column('site_type',   sa.String(30),  nullable=False, server_default='POP'),
        sa.Column('address',     sa.Text(),      nullable=True),
        sa.Column('latitude',    sa.Numeric(10, 7), nullable=True),
        sa.Column('longitude',   sa.Numeric(10, 7), nullable=True),
        sa.Column('region_id',   postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('status',      sa.String(20),  nullable=False, server_default='active'),
        sa.Column('notes',       sa.Text(),      nullable=True),
        sa.Column('created_by',  postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at',  sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at',  sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_foreign_key(
        'fk_infra_sites_tenant', 'infrastructure_sites', 'tenants',
        ['tenant_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_infra_sites_region', 'infrastructure_sites', 'regions',
        ['region_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_infra_sites_created_by', 'infrastructure_sites', 'users',
        ['created_by'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_infra_sites_tenant', 'infrastructure_sites', ['tenant_id'])

    # ── infrastructure_nodes ──────────────────────────────────
    op.create_table(
        'infrastructure_nodes',
        sa.Column('id',           postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',    postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('site_id',      postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name',         sa.String(200), nullable=False),
        sa.Column('node_type',    sa.String(30),  nullable=False, server_default='OLT'),
        sa.Column('manufacturer', sa.String(100), nullable=True),
        sa.Column('model',        sa.String(100), nullable=True),
        sa.Column('ip_address',   sa.String(45),  nullable=True),
        sa.Column('port_count',   sa.Integer(),   nullable=True),
        sa.Column('status',       sa.String(20),  nullable=False, server_default='active'),
        sa.Column('meta',         postgresql.JSONB(), nullable=True, server_default='{}'),
        sa.Column('created_by',   postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at',   sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at',   sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_foreign_key(
        'fk_infra_nodes_tenant', 'infrastructure_nodes', 'tenants',
        ['tenant_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_infra_nodes_site', 'infrastructure_nodes', 'infrastructure_sites',
        ['site_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_infra_nodes_created_by', 'infrastructure_nodes', 'users',
        ['created_by'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_infra_nodes_tenant',  'infrastructure_nodes', ['tenant_id'])
    op.create_index('ix_infra_nodes_site',    'infrastructure_nodes', ['site_id'])

    # ── infrastructure_routes ─────────────────────────────────
    op.create_table(
        'infrastructure_routes',
        sa.Column('id',             postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',      postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('from_node_id',   postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('to_node_id',     postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('cable_type',     sa.String(50),  nullable=True),
        sa.Column('length_km',      sa.Numeric(8, 3), nullable=True),
        sa.Column('capacity_gbps',  sa.Numeric(8, 2), nullable=True),
        sa.Column('status',         sa.String(20), nullable=False, server_default='active'),
        sa.Column('installed_at',   sa.Date(), nullable=True),
        sa.Column('notes',          sa.Text(), nullable=True),
        sa.Column('created_by',     postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at',     sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_foreign_key(
        'fk_infra_routes_tenant', 'infrastructure_routes', 'tenants',
        ['tenant_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_infra_routes_from_node', 'infrastructure_routes', 'infrastructure_nodes',
        ['from_node_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_infra_routes_to_node', 'infrastructure_routes', 'infrastructure_nodes',
        ['to_node_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_infra_routes_created_by', 'infrastructure_routes', 'users',
        ['created_by'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_infra_routes_tenant',    'infrastructure_routes', ['tenant_id'])
    op.create_index('ix_infra_routes_from_node', 'infrastructure_routes', ['from_node_id'])
    op.create_index('ix_infra_routes_to_node',   'infrastructure_routes', ['to_node_id'])

    # Enable RLS on all three tables
    for table in ('infrastructure_sites', 'infrastructure_nodes', 'infrastructure_routes'):
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


def downgrade() -> None:
    for table in ('infrastructure_routes', 'infrastructure_nodes', 'infrastructure_sites'):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
