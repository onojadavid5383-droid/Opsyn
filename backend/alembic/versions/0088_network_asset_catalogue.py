"""Network GIS Phase 2: imported cable geometry

Cables brought in by bulk upload carry surveyed / as-built geometry. They
are neither road-graph routed (ROAD_GRAPH) nor hand-drawn
(MANUAL_GEOMETRY, which validation will flag), so net_cables.route_method
gains a third value, IMPORTED.

Everything else Phase 2 adds (per-type attribute schemas, generated asset
codes, network upload types) is application logic over the 0087 tables and
needs no schema change: codes are derived from existing rows under an
advisory lock, uploads stage through infrastructure_upload_staging.

Downgrade: IMPORTED cables become MANUAL_GEOMETRY (the closest remaining
value) with attributes.route_method_before_downgrade = 'IMPORTED', so the
information is kept on the row.

Revision ID: 0088
Revises: 0087
Create Date: 2026-09-26
"""

from alembic import op

revision      = '0088'
down_revision = '0087'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.execute("ALTER TABLE net_cables DROP CONSTRAINT IF EXISTS net_cables_route_method_check")
    op.execute("""
        ALTER TABLE net_cables ADD CONSTRAINT net_cables_route_method_check
        CHECK (route_method IN ('ROAD_GRAPH', 'MANUAL_GEOMETRY', 'IMPORTED'))
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE net_cables
        SET route_method = 'MANUAL_GEOMETRY',
            attributes   = attributes || '{"route_method_before_downgrade": "IMPORTED"}'::jsonb
        WHERE route_method = 'IMPORTED'
    """)
    op.execute("ALTER TABLE net_cables DROP CONSTRAINT IF EXISTS net_cables_route_method_check")
    op.execute("""
        ALTER TABLE net_cables ADD CONSTRAINT net_cables_route_method_check
        CHECK (route_method IN ('ROAD_GRAPH', 'MANUAL_GEOMETRY'))
    """)
