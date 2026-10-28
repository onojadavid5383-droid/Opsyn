"""Infrastructure Management — Phase 1 (3/8): cabinets

FTTH cabinet (ODF / splice box) asset table with PostGIS Point geometry.
Uses raw DDL for geometry column to avoid geoalchemy2 import in migration context.

Revision ID: 0069
Revises: 0068
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0069'
down_revision = '0068'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # Raw DDL — geometry column requires PostGIS type syntax
    op.execute("""
        CREATE TABLE cabinets (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            cabinet_id       VARCHAR(100) NOT NULL,
            capacity         INTEGER     NOT NULL CHECK (capacity > 0),
            number_tray      SMALLINT    NOT NULL CHECK (number_tray >= 0),
            longitude        DOUBLE PRECISION NOT NULL
                                CHECK (longitude BETWEEN -180 AND 180),
            latitude         DOUBLE PRECISION NOT NULL
                                CHECK (latitude BETWEEN -90 AND 90),
            location         geometry(Point, 4326) NOT NULL,
            is_deleted       BOOLEAN     NOT NULL DEFAULT FALSE,
            created_by       UUID        REFERENCES users(id) ON DELETE SET NULL,
            upload_session_id UUID       REFERENCES infrastructure_upload_sessions(id)
                                         ON DELETE SET NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Unique constraint: (cabinet_id, tenant_id) WHERE is_deleted = FALSE
    op.execute("""
        CREATE UNIQUE INDEX uq_cabinets_cabinet_id_tenant
        ON cabinets (cabinet_id, tenant_id)
        WHERE is_deleted = FALSE
    """)

    op.create_index('ix_cabinets_tenant', 'cabinets', ['tenant_id'])
    op.create_index('ix_cabinets_cabinet_id_tenant', 'cabinets', ['cabinet_id', 'tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_cabinets_cabinet_id_tenant', table_name='cabinets')
    op.drop_index('ix_cabinets_tenant', table_name='cabinets')
    op.execute("DROP INDEX IF EXISTS uq_cabinets_cabinet_id_tenant")
    op.drop_table('cabinets')
