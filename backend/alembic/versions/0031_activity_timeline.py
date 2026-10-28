"""
OPSYN ACTIVITY TIMELINE — MIGRATION 0031
Creates a unified, immutable activity_timeline table that replaces the
split audit trail across task_comments (SYSTEM type), TaskAuditEntry,
and ProjectStageComment.

One row per event. entity_type + entity_id identify what the event
belongs to. All writes are INSERT-only — no UPDATE, no DELETE.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0031'
down_revision = '0030'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        'activity_timeline',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
        ),
        sa.Column('tenant_id',    postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('entity_type',  sa.String(50),  nullable=False),   # task | project | onboarding | outage
        sa.Column('entity_id',    postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('event_type',   sa.String(50),  nullable=False),   # comment | state_change | stage_event | system
        sa.Column('actor_id',     postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('body',         sa.Text(),       nullable=True),
        sa.Column('from_state',   sa.String(30),   nullable=True),
        sa.Column('to_state',     sa.String(30),   nullable=True),
        sa.Column('meta',         postgresql.JSONB(), nullable=True, server_default='{}'),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # FK: tenant_id → tenants.id
    op.create_foreign_key(
        'fk_activity_timeline_tenant',
        'activity_timeline', 'tenants',
        ['tenant_id'], ['id'], ondelete='CASCADE',
    )

    # FK: actor_id → users.id (nullable — system events have no actor)
    op.create_foreign_key(
        'fk_activity_timeline_actor',
        'activity_timeline', 'users',
        ['actor_id'], ['id'], ondelete='SET NULL',
    )

    # Primary query pattern: all events for a given entity, newest-first
    op.create_index(
        'ix_activity_timeline_entity',
        'activity_timeline',
        ['tenant_id', 'entity_type', 'entity_id', 'created_at'],
    )

    # Secondary: feed of all activity for a tenant ordered by time
    op.create_index(
        'ix_activity_timeline_tenant_time',
        'activity_timeline',
        ['tenant_id', 'created_at'],
    )

    # Enable Row Level Security
    op.execute("ALTER TABLE activity_timeline ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE activity_timeline FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON activity_timeline
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON activity_timeline")
    op.drop_index('ix_activity_timeline_tenant_time', table_name='activity_timeline')
    op.drop_index('ix_activity_timeline_entity',      table_name='activity_timeline')
    op.drop_constraint('fk_activity_timeline_actor',  'activity_timeline', type_='foreignkey')
    op.drop_constraint('fk_activity_timeline_tenant', 'activity_timeline', type_='foreignkey')
    op.drop_table('activity_timeline')
