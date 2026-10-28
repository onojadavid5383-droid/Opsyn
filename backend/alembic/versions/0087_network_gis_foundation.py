"""Network GIS Phase 1: unified asset core (net_assets, net_cables, net_ports)

The PostGIS source of truth for physical plant (Network GIS plan §3.1–3.2):

  net_assets  point-like assets, POP … CUSTOMER_ENDPOINT
  net_cables  cables with real LineString geometry; length_m is kept by a
              trigger from ST_Length(geom::geography), never by the client
  net_ports   ports on an asset (empty for now: the legacy infra_ports hang
              off infrastructure_nodes, which stay where they are — D4)

Every table: tenant_id + FORCE RLS (same policy as 0086), soft delete,
CHECKs mirroring app/modules/network/{lifecycle,asset_types}.py, GiST on
geometry, trigram (pg_trgm) on code/name for search.

Also:
  - feature keys network.view / network.edit; every existing
    infrastructure.view / .edit grant is copied to the new key, so nobody
    loses access they already had
  - backfill of the uploaded olts / cabinets / splitter_boxes into
    net_assets (app/modules/network/backfill.py, idempotent)

Deliberately NOT touched (decision D4 revised 2026-09-25): the legacy
infrastructure_sites / nodes / routes tables and their consumers.

Downgrade drops the three tables and the two feature keys. The source
upload tables are never modified, so nothing is lost either way.

Revision ID: 0087
Revises: 0086
Create Date: 2026-09-25
"""

from alembic import op
import sqlalchemy as sa

from app.modules.network.asset_types import (
    ASSET_TYPE_CODES, CABLE_CATEGORY_CODES, CREATION_METHODS, INSTALLATION_TYPES,
    PORT_STATUSES, PORT_TYPES,
)

# Frozen at this revision; 0088 adds 'IMPORTED'.
ROUTE_METHODS = ('ROAD_GRAPH', 'MANUAL_GEOMETRY')
from app.modules.network.backfill import BACKFILL_STATEMENTS
from app.modules.network.lifecycle import LIFECYCLE_STATES

revision      = '0087'
down_revision = '0086'
branch_labels = None
depends_on    = None

_TABLES = ('net_assets', 'net_cables', 'net_ports')


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


_COMMON_OBJECT_COLUMNS = """
    lifecycle_status  varchar(20)  NOT NULL DEFAULT 'PLANNED'
                      CHECK (lifecycle_status IN {lifecycle}),
    creation_method   varchar(20)  NOT NULL DEFAULT 'MANUAL'
                      CHECK (creation_method IN {creation}),
    project_id        uuid         REFERENCES projects(id) ON DELETE SET NULL,
    design_id         uuid,
    lineage_id        uuid         NOT NULL DEFAULT gen_random_uuid(),
    attributes        jsonb        NOT NULL DEFAULT '{{}}'::jsonb,
    source_table      varchar(50),
    source_id         uuid,
    created_by        uuid         REFERENCES users(id) ON DELETE SET NULL,
    updated_by        uuid         REFERENCES users(id) ON DELETE SET NULL,
    created_at        timestamptz  NOT NULL DEFAULT now(),
    updated_at        timestamptz  NOT NULL DEFAULT now(),
    deleted_at        timestamptz,
    deleted_by        uuid         REFERENCES users(id) ON DELETE SET NULL
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    common = _COMMON_OBJECT_COLUMNS.format(
        lifecycle=_in(LIFECYCLE_STATES), creation=_in(CREATION_METHODS),
    )

    # ── net_assets ───────────────────────────────────────────────
    op.execute(f"""
        CREATE TABLE net_assets (
            id           uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    uuid          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            asset_code   varchar(100)  NOT NULL CHECK (length(trim(asset_code)) > 0),
            asset_type   varchar(30)   NOT NULL CHECK (asset_type IN {_in(ASSET_TYPE_CODES)}),
            name         varchar(200),
            description  text,
            geom         geometry(Geometry, 4326) NOT NULL CHECK (ST_IsValid(geom)),
            parent_id    uuid          REFERENCES net_assets(id) ON DELETE SET NULL
                                       CHECK (parent_id IS DISTINCT FROM id),
            capacity      integer      CHECK (capacity >= 0),
            used_capacity integer      CHECK (used_capacity >= 0),
            {common}
        )
    """)

    # ── net_cables ───────────────────────────────────────────────
    op.execute(f"""
        CREATE TABLE net_cables (
            id                 uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          uuid          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            asset_code         varchar(100)  NOT NULL CHECK (length(trim(asset_code)) > 0),
            cable_category     varchar(20)   NOT NULL CHECK (cable_category IN {_in(CABLE_CATEGORY_CODES)}),
            name               varchar(200),
            description        text,
            geom               geometry(LineString, 4326) NOT NULL CHECK (ST_NPoints(geom) >= 2),
            design_geom        geometry(LineString, 4326),
            asbuilt_geom       geometry(LineString, 4326),
            fiber_count        integer       CHECK (fiber_count > 0),
            length_m           numeric(12, 2),
            installation_type  varchar(20)   CHECK (installation_type IN {_in(INSTALLATION_TYPES)}),
            route_method       varchar(20)   NOT NULL DEFAULT 'ROAD_GRAPH'
                                             CHECK (route_method IN {_in(ROUTE_METHODS)}),
            source_asset_id    uuid          REFERENCES net_assets(id) ON DELETE SET NULL,
            dest_asset_id      uuid          REFERENCES net_assets(id) ON DELETE SET NULL,
            {common}
        )
    """)

    # length_m always comes from the stored geometry, in metres on the spheroid
    op.execute("""
        CREATE FUNCTION net_cables_set_length() RETURNS trigger AS $$
        BEGIN
            NEW.length_m := round(ST_Length(NEW.geom::geography)::numeric, 2);
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER net_cables_length
        BEFORE INSERT OR UPDATE OF geom ON net_cables
        FOR EACH ROW EXECUTE FUNCTION net_cables_set_length()
    """)

    # ── net_ports ────────────────────────────────────────────────
    op.execute(f"""
        CREATE TABLE net_ports (
            id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       uuid         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            asset_id        uuid         NOT NULL REFERENCES net_assets(id) ON DELETE CASCADE,
            port_label      varchar(30)  NOT NULL,
            port_no         integer      CHECK (port_no >= 0),
            port_type       varchar(20)  NOT NULL CHECK (port_type IN {_in(PORT_TYPES)}),
            direction       varchar(4)   NOT NULL DEFAULT 'BIDI' CHECK (direction IN ('IN', 'OUT', 'BIDI')),
            total_capacity  integer      CHECK (total_capacity >= 0),
            used_capacity   integer      CHECK (used_capacity >= 0),
            status          varchar(20)  NOT NULL DEFAULT 'FREE' CHECK (status IN {_in(PORT_STATUSES)}),
            attributes      jsonb        NOT NULL DEFAULT '{{}}'::jsonb,
            source_table    varchar(50),
            source_id       uuid,
            created_at      timestamptz  NOT NULL DEFAULT now(),
            updated_at      timestamptz  NOT NULL DEFAULT now(),
            CONSTRAINT uq_net_ports_asset_label UNIQUE (asset_id, port_label)
        )
    """)

    # ── Indexes ──────────────────────────────────────────────────
    for table in ('net_assets', 'net_cables'):
        op.execute(f"CREATE INDEX ix_{table}_geom_gist ON {table} USING GIST (geom)")
        op.execute(f"CREATE INDEX ix_{table}_code_trgm ON {table} USING GIN (asset_code gin_trgm_ops)")
        op.execute(f"CREATE INDEX ix_{table}_name_trgm ON {table} USING GIN (name gin_trgm_ops)")
        op.execute(f"CREATE INDEX ix_{table}_tenant_status ON {table} (tenant_id, lifecycle_status) WHERE deleted_at IS NULL")
        op.execute(f"CREATE INDEX ix_{table}_design ON {table} (design_id) WHERE design_id IS NOT NULL")
        op.execute(f"CREATE INDEX ix_{table}_lineage ON {table} (lineage_id)")
        op.execute(f"""
            CREATE UNIQUE INDEX uq_{table}_source ON {table} (tenant_id, source_table, source_id)
            WHERE source_table IS NOT NULL
        """)

    # Codes are unique per tenant + type among live rows, and per design
    # inside a design's working set.
    op.execute("""
        CREATE UNIQUE INDEX uq_net_assets_live_code ON net_assets (tenant_id, asset_type, asset_code)
        WHERE design_id IS NULL AND deleted_at IS NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_net_assets_design_code ON net_assets (tenant_id, design_id, asset_type, asset_code)
        WHERE design_id IS NOT NULL AND deleted_at IS NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_net_cables_live_code ON net_cables (tenant_id, asset_code)
        WHERE design_id IS NULL AND deleted_at IS NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_net_cables_design_code ON net_cables (tenant_id, design_id, asset_code)
        WHERE design_id IS NOT NULL AND deleted_at IS NULL
    """)
    op.execute("CREATE INDEX ix_net_assets_tenant_type ON net_assets (tenant_id, asset_type) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX ix_net_assets_parent ON net_assets (parent_id) WHERE parent_id IS NOT NULL")
    op.execute("CREATE INDEX ix_net_cables_tenant_category ON net_cables (tenant_id, cable_category) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX ix_net_cables_endpoints ON net_cables (source_asset_id, dest_asset_id)")
    op.execute("CREATE INDEX ix_net_ports_asset ON net_ports (asset_id)")
    op.execute("CREATE INDEX ix_net_ports_tenant ON net_ports (tenant_id)")

    # ── RLS (same policy shape as 0086) ──────────────────────────
    for table in _TABLES:
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

    # ── Feature keys ─────────────────────────────────────────────
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO feature_permissions (feature_key, feature_label, module, description)
        VALUES
          ('network.view', 'View network map', 'network',
           'View the network map, search assets and inspect them'),
          ('network.edit', 'Edit live network', 'network',
           'Create, change and retire assets in the live network')
        ON CONFLICT (feature_key) DO NOTHING
    """))
    for old, new in (('infrastructure.view', 'network.view'), ('infrastructure.edit', 'network.edit')):
        conn.execute(sa.text("""
            INSERT INTO department_feature_grants (tenant_id, department_id, feature_key, min_role_level, granted_by)
            SELECT tenant_id, department_id, :new, min_role_level, granted_by
            FROM department_feature_grants WHERE feature_key = :old
            ON CONFLICT (tenant_id, department_id, feature_key) DO NOTHING
        """), {"old": old, "new": new})
        conn.execute(sa.text("""
            INSERT INTO role_feature_overrides (tenant_id, role_id, feature_key, is_granted)
            SELECT tenant_id, role_id, :new, is_granted
            FROM role_feature_overrides WHERE feature_key = :old
            ON CONFLICT (tenant_id, role_id, feature_key) DO NOTHING
        """), {"old": old, "new": new})

    # ── Backfill uploaded assets (all tenants) ───────────────────
    for stmt in BACKFILL_STATEMENTS:
        conn.execute(sa.text(stmt), {"tid": None})


def downgrade() -> None:
    conn = op.get_bind()
    for key in ('network.view', 'network.edit'):
        conn.execute(sa.text("DELETE FROM department_feature_grants WHERE feature_key = :k"), {"k": key})
        conn.execute(sa.text("DELETE FROM role_feature_overrides WHERE feature_key = :k"), {"k": key})
        conn.execute(sa.text("DELETE FROM feature_permissions WHERE feature_key = :k"), {"k": key})

    op.execute("DROP TABLE IF EXISTS net_ports")
    op.execute("DROP TABLE IF EXISTS net_cables")
    op.execute("DROP FUNCTION IF EXISTS net_cables_set_length()")
    op.execute("DROP TABLE IF EXISTS net_assets")
    # pg_trgm is left installed: other objects may come to depend on it.
