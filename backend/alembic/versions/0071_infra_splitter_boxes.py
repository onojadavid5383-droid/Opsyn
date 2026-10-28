"""Infrastructure Management — Phase 1 (5/8): splitter_boxes

FTTH splitter box asset table (First-Level and Second-Level).
Self-referential parent_splitter_id for hierarchy linkage.
Partial unique index: (box_id, tenant_id) WHERE is_deleted = FALSE.

Revision ID: 0071
Revises: 0070
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0071'
down_revision = '0070'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE splitter_boxes (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            box_id            VARCHAR(100) NOT NULL,
            input_ports       SMALLINT    NOT NULL CHECK (input_ports >= 1),
            output_ports      SMALLINT    NOT NULL CHECK (output_ports >= 1),
            splitter_level    VARCHAR(20) NOT NULL
                                CHECK (splitter_level IN ('First-Level', 'Second-Level')),
            splitter_type     VARCHAR(20) NOT NULL
                                CHECK (splitter_type IN ('PCC', 'Legacy')),
            number_customer   INTEGER     CHECK (number_customer >= 0),
            longitude         DOUBLE PRECISION NOT NULL
                                CHECK (longitude BETWEEN -180 AND 180),
            latitude          DOUBLE PRECISION NOT NULL
                                CHECK (latitude BETWEEN -90 AND 90),
            location          geometry(Point, 4326) NOT NULL,
            parent_splitter_id UUID       REFERENCES splitter_boxes(id) ON DELETE SET NULL,
            cabinet_id        UUID        REFERENCES cabinets(id) ON DELETE SET NULL,
            is_deleted        BOOLEAN     NOT NULL DEFAULT FALSE,
            created_by        UUID        REFERENCES users(id) ON DELETE SET NULL,
            upload_session_id UUID        REFERENCES infrastructure_upload_sessions(id)
                                           ON DELETE SET NULL,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Unique constraint: (box_id, tenant_id) WHERE is_deleted = FALSE
    # Allows re-uploading after a soft-delete
    op.execute("""
        CREATE UNIQUE INDEX uq_splitter_boxes_box_id_tenant
        ON splitter_boxes (box_id, tenant_id)
        WHERE is_deleted = FALSE
    """)

    op.create_index('ix_splitter_boxes_tenant', 'splitter_boxes', ['tenant_id'])
    op.create_index('ix_splitter_boxes_box_id_tenant',
                    'splitter_boxes', ['box_id', 'tenant_id'])
    op.create_index('ix_splitter_boxes_cabinet', 'splitter_boxes', ['cabinet_id'])
    op.create_index('ix_splitter_boxes_level',
                    'splitter_boxes', ['tenant_id', 'splitter_level'])


def downgrade() -> None:
    op.drop_index('ix_splitter_boxes_level', table_name='splitter_boxes')
    op.drop_index('ix_splitter_boxes_cabinet', table_name='splitter_boxes')
    op.drop_index('ix_splitter_boxes_box_id_tenant', table_name='splitter_boxes')
    op.drop_index('ix_splitter_boxes_tenant', table_name='splitter_boxes')
    op.execute("DROP INDEX IF EXISTS uq_splitter_boxes_box_id_tenant")
    op.drop_table('splitter_boxes')
