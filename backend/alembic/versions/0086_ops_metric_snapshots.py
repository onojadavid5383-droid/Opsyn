"""Command Center trends: point-in-time operational metric snapshots

The dashboard's trend charts need history for metrics that only exist as a
live value — node availability (active / total infrastructure nodes) and
PON port utilisation (used / total capacity across infra_ports). Nothing
stored those values over time, so a trend line for them could not be drawn
without inventing data.

This table is written by the hourly Celery beat task
`reports.capture_metric_snapshots` (app/tasks/metric_snapshots.py) and read by
GET /reports/trends. Metrics derivable from existing timestamps (outages
opened/resolved, MTTR, tasks created/completed, customers added) are computed
directly from their source tables and are NOT snapshotted here.

One row per (tenant, metric, capture time). `numerator`/`denominator` are
kept alongside `value` so a bucketed average can be recomputed as a true
ratio (sum(num)/sum(den)) rather than an average of percentages.

RLS follows the tenant-isolation pattern used throughout (see 0085).

Revision ID: 0086
Revises: 0085
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0086'
down_revision = '0085'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        'ops_metric_snapshots',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        # 'node_availability_pct' | 'port_utilisation_pct'
        sa.Column('metric_key', sa.String(50), nullable=False),
        sa.Column('value', sa.Numeric(7, 3), nullable=False),
        sa.Column('numerator', sa.BigInteger(), nullable=False),
        sa.Column('denominator', sa.BigInteger(), nullable=False),
        sa.Column('captured_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index(
        'ix_ops_metric_snapshots_tenant_metric_time',
        'ops_metric_snapshots', ['tenant_id', 'metric_key', 'captured_at'],
    )

    op.execute("ALTER TABLE ops_metric_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ops_metric_snapshots FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON ops_metric_snapshots
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ops_metric_snapshots")
    op.drop_index('ix_ops_metric_snapshots_tenant_metric_time', table_name='ops_metric_snapshots')
    op.drop_table('ops_metric_snapshots')
