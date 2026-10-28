"""Infrastructure Management — Phase 1 (4/8): olts

OLT (Optical Line Terminal) asset table with PostGIS Point geometry.

Revision ID: 0070
Revises: 0069
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0070'
down_revision = '0069'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE olts (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name                VARCHAR(200) NOT NULL,
            location_description TEXT        NOT NULL,
            number_of_odf       SMALLINT    CHECK (number_of_odf >= 0),
            longitude           DOUBLE PRECISION NOT NULL
                                    CHECK (longitude BETWEEN -180 AND 180),
            latitude            DOUBLE PRECISION NOT NULL
                                    CHECK (latitude BETWEEN -90 AND 90),
            location            geometry(Point, 4326) NOT NULL,
            is_deleted          BOOLEAN     NOT NULL DEFAULT FALSE,
            created_by          UUID        REFERENCES users(id) ON DELETE SET NULL,
            upload_session_id   UUID        REFERENCES infrastructure_upload_sessions(id)
                                             ON DELETE SET NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Unique constraint: (name, tenant_id) WHERE is_deleted = FALSE
    op.execute("""
        CREATE UNIQUE INDEX uq_olts_name_tenant
        ON olts (name, tenant_id)
        WHERE is_deleted = FALSE
    """)

    op.create_index('ix_olts_tenant', 'olts', ['tenant_id'])
    op.create_index('ix_olts_name_tenant', 'olts', ['name', 'tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_olts_name_tenant', table_name='olts')
    op.drop_index('ix_olts_tenant', table_name='olts')
    op.execute("DROP INDEX IF EXISTS uq_olts_name_tenant")
    op.drop_table('olts')
