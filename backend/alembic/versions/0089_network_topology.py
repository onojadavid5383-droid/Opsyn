"""Network GIS Phase 3: explicit topology (net_connections) and fibres (net_fibers)

net_connections  source feeds dest (source nearer the OLT), optionally via a
                 cable / fibre / ports. Manual rows have no source_table;
                 derived rows (from cable endpoints, uploaded splitter and
                 FAT references) are keyed by (tenant, source_table,
                 source_id) and kept in step by
                 app/modules/network/topology.sync_derived_connections.
net_fibers       fibres of a cable, stored only once something about a fibre
                 is recorded (status); the rest are listed virtually.

Both: tenant_id + FORCE RLS (policy as 0086/0087), CHECKs mirroring
asset_types.CONNECTION_TYPES / FIBER_STATUSES and lifecycle states.

Data: the derivation rules run once for every tenant, turning the
existing cable endpoints and upload references into connections.

Downgrade drops both tables; nothing else is touched.

Revision ID: 0089
Revises: 0088
Create Date: 2026-09-26
"""

from alembic import op
import sqlalchemy as sa

from app.modules.network.topology import SYNC_STATEMENTS

revision      = '0089'
down_revision = '0088'
branch_labels = None
depends_on    = None

# Frozen at this revision
CONNECTION_TYPES = ('FEED', 'SPLIT', 'SPLICE', 'PATCH', 'DROP', 'UPLINK')
FIBER_STATUSES = ('FREE', 'USED', 'RESERVED', 'FAULTY', 'DARK')
LIFECYCLE_STATES = ('DRAFT', 'PLANNED', 'DESIGNED', 'UNDER_REVIEW', 'APPROVED', 'CONSTRUCTION',
                    'INSTALLED', 'TESTING', 'VERIFIED', 'ACTIVE', 'FAULTY', 'RETIRED', 'REJECTED')


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


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
    op.execute(f"""
        CREATE TABLE net_fibers (
            id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   uuid         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            cable_id    uuid         NOT NULL REFERENCES net_cables(id) ON DELETE CASCADE,
            fiber_no    integer      NOT NULL CHECK (fiber_no >= 1),
            status      varchar(20)  NOT NULL DEFAULT 'FREE' CHECK (status IN {_in(FIBER_STATUSES)}),
            attributes  jsonb        NOT NULL DEFAULT '{{}}'::jsonb,
            created_at  timestamptz  NOT NULL DEFAULT now(),
            updated_at  timestamptz  NOT NULL DEFAULT now(),
            CONSTRAINT uq_net_fibers_cable_no UNIQUE (cable_id, fiber_no)
        )
    """)
    op.execute("CREATE INDEX ix_net_fibers_tenant ON net_fibers (tenant_id)")
    _rls("net_fibers")

    op.execute(f"""
        CREATE TABLE net_connections (
            id                uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         uuid         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            source_asset_id   uuid         NOT NULL REFERENCES net_assets(id) ON DELETE CASCADE,
            dest_asset_id     uuid         NOT NULL REFERENCES net_assets(id) ON DELETE CASCADE,
            source_port_id    uuid         REFERENCES net_ports(id) ON DELETE SET NULL,
            dest_port_id      uuid         REFERENCES net_ports(id) ON DELETE SET NULL,
            via_cable_id      uuid         REFERENCES net_cables(id) ON DELETE SET NULL,
            fiber_id          uuid         REFERENCES net_fibers(id) ON DELETE SET NULL,
            connection_type   varchar(20)  NOT NULL DEFAULT 'FEED' CHECK (connection_type IN {_in(CONNECTION_TYPES)}),
            lifecycle_status  varchar(20)  NOT NULL DEFAULT 'ACTIVE' CHECK (lifecycle_status IN {_in(LIFECYCLE_STATES)}),
            design_id         uuid,
            attributes        jsonb        NOT NULL DEFAULT '{{}}'::jsonb,
            source_table      varchar(50),
            source_id         uuid,
            created_by        uuid         REFERENCES users(id) ON DELETE SET NULL,
            created_at        timestamptz  NOT NULL DEFAULT now(),
            updated_at        timestamptz  NOT NULL DEFAULT now(),
            deleted_at        timestamptz,
            deleted_by        uuid         REFERENCES users(id) ON DELETE SET NULL,
            CONSTRAINT ck_net_connections_not_self CHECK (source_asset_id <> dest_asset_id)
        )
    """)
    # Trace walks both ways; utilisation counts children of a source
    op.execute("CREATE INDEX ix_net_connections_source ON net_connections (source_asset_id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX ix_net_connections_dest ON net_connections (dest_asset_id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX ix_net_connections_cable ON net_connections (via_cable_id) WHERE via_cable_id IS NOT NULL")
    op.execute("CREATE INDEX ix_net_connections_tenant ON net_connections (tenant_id)")
    op.execute("""
        CREATE UNIQUE INDEX uq_net_connections_source ON net_connections (tenant_id, source_table, source_id)
        WHERE source_table IS NOT NULL
    """)
    # One live manual link per pair and cable: a hand-made duplicate is a 409
    op.execute("""
        CREATE UNIQUE INDEX uq_net_connections_manual_pair ON net_connections
            (tenant_id, source_asset_id, dest_asset_id, coalesce(via_cable_id, '00000000-0000-0000-0000-000000000000'::uuid))
        WHERE source_table IS NULL AND deleted_at IS NULL AND design_id IS NULL
    """)
    _rls("net_connections")

    conn = op.get_bind()
    for stmt in SYNC_STATEMENTS:
        conn.execute(sa.text(stmt), {"tid": None})


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS net_connections")
    op.execute("DROP TABLE IF EXISTS net_fibers")
