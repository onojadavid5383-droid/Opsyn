"""Network GIS Phase 4: design container, per-design inputs, versions, issues

designs                  one design per project area: boundary polygon, status,
                         engine_config (FTTXConfig overrides), current version
design_input_uploads     one row per uploaded input file (batch)
design_inputs            the design's own road / homepass / pole / building /
                         pickup / existing_structure features (decision D6)
design_versions          numbered versions; V1 is created with the design.
                         snapshot/compare/restore arrive in Phase 8
design_validation_issues structured issues from the validation service
design_operations        edit operation log — schema only, used in Phase 6

Also: the design_id columns net_assets / net_cables / net_connections have
carried since 0087/0089 get their foreign key to designs (ON DELETE
CASCADE — a design's working set belongs to it), and the feature key
design.edit (granted wherever fttx_designer.edit already is).

Every table: tenant_id + FORCE RLS (policy as 0086–0089), CHECKs frozen
here. Downgrade removes everything above and the foreign keys; the net_*
rows are untouched.

Revision ID: 0090
Revises: 0089
Create Date: 2026-09-26
"""

from alembic import op
import sqlalchemy as sa

revision      = '0090'
down_revision = '0089'
branch_labels = None
depends_on    = None

DESIGN_STATUSES = ('DRAFT', 'GENERATED', 'MODIFIED', 'VALIDATING', 'UNDER_REVIEW', 'APPROVED',
                   'REJECTED', 'SUPERSEDED', 'DEPLOYED')
INPUT_LAYERS = ('road', 'homepass', 'pole', 'building', 'pickup', 'existing_structure')
CREATION = ('AUTO', 'MANUAL', 'IMPORTED', 'RESTORED', 'INITIAL')
SEVERITIES = ('ERROR', 'WARNING', 'INFO')
NEW_TABLES = ('design_operations', 'design_validation_issues', 'design_versions',
              'design_inputs', 'design_input_uploads', 'designs')


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
        CREATE TABLE designs (
            id                 uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          uuid          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            project_id         uuid          NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name               varchar(200)  NOT NULL CHECK (length(trim(name)) > 0),
            description        text,
            boundary           geometry(MultiPolygon, 4326) CHECK (boundary IS NULL OR ST_IsValid(boundary)),
            status             varchar(20)   NOT NULL DEFAULT 'DRAFT' CHECK (status IN {_in(DESIGN_STATUSES)}),
            current_version_id uuid,
            engine_config      jsonb         NOT NULL DEFAULT '{{}}'::jsonb,
            created_by         uuid          REFERENCES users(id) ON DELETE SET NULL,
            updated_by         uuid          REFERENCES users(id) ON DELETE SET NULL,
            created_at         timestamptz   NOT NULL DEFAULT now(),
            updated_at         timestamptz   NOT NULL DEFAULT now(),
            deleted_at         timestamptz,
            deleted_by         uuid          REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    op.execute("CREATE INDEX ix_designs_project ON designs (project_id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX ix_designs_tenant ON designs (tenant_id)")
    op.execute("CREATE INDEX ix_designs_boundary_gist ON designs USING GIST (boundary)")

    op.execute(f"""
        CREATE TABLE design_input_uploads (
            id             uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      uuid          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            design_id      uuid          NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
            layer_key      varchar(30)   NOT NULL CHECK (layer_key IN {_in(INPUT_LAYERS)}),
            filename       varchar(500),
            file_hash      varchar(64),
            feature_count  integer       NOT NULL DEFAULT 0,
            mode           varchar(10)   NOT NULL DEFAULT 'replace' CHECK (mode IN ('replace', 'append')),
            uploaded_by    uuid          REFERENCES users(id) ON DELETE SET NULL,
            uploaded_at    timestamptz   NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_design_input_uploads_design ON design_input_uploads (design_id, layer_key)")

    op.execute(f"""
        CREATE TABLE design_inputs (
            id          uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   uuid          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            design_id   uuid          NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
            layer_key   varchar(30)   NOT NULL CHECK (layer_key IN {_in(INPUT_LAYERS)}),
            geom        geometry(Geometry, 4326) NOT NULL CHECK (ST_IsValid(geom)),
            properties  jsonb         NOT NULL DEFAULT '{{}}'::jsonb,
            upload_id   uuid          REFERENCES design_input_uploads(id) ON DELETE SET NULL,
            created_at  timestamptz   NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_design_inputs_design_layer ON design_inputs (design_id, layer_key)")
    op.execute("CREATE INDEX ix_design_inputs_geom_gist ON design_inputs USING GIST (geom)")

    op.execute(f"""
        CREATE TABLE design_versions (
            id                 uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          uuid          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            design_id          uuid          NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
            version_no         integer       NOT NULL CHECK (version_no >= 1),
            parent_version_id  uuid          REFERENCES design_versions(id) ON DELETE SET NULL,
            creation_method    varchar(20)   NOT NULL DEFAULT 'INITIAL' CHECK (creation_method IN {_in(CREATION)}),
            label              varchar(200),
            snapshot           bytea,
            boq_snapshot       jsonb,
            validation_summary jsonb,
            optical_summary    jsonb,
            created_by         uuid          REFERENCES users(id) ON DELETE SET NULL,
            created_at         timestamptz   NOT NULL DEFAULT now(),
            CONSTRAINT uq_design_versions_no UNIQUE (design_id, version_no)
        )
    """)
    op.execute("""
        ALTER TABLE designs ADD CONSTRAINT fk_designs_current_version
        FOREIGN KEY (current_version_id) REFERENCES design_versions(id) ON DELETE SET NULL
    """)

    op.execute(f"""
        CREATE TABLE design_validation_issues (
            id          uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   uuid          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            design_id   uuid          NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
            version_id  uuid          REFERENCES design_versions(id) ON DELETE SET NULL,
            severity    varchar(10)   NOT NULL CHECK (severity IN {_in(SEVERITIES)}),
            code        varchar(60)   NOT NULL,
            rule        varchar(200),
            message     text          NOT NULL,
            asset_id    uuid,
            cable_id    uuid,
            geom        geometry(Geometry, 4326),
            metadata    jsonb         NOT NULL DEFAULT '{{}}'::jsonb,
            created_at  timestamptz   NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_design_validation_issues_design ON design_validation_issues (design_id, severity)")

    op.execute("""
        CREATE TABLE design_operations (
            id          uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   uuid          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            design_id   uuid          NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
            seq         bigint        NOT NULL,
            op          varchar(30)   NOT NULL,
            payload     jsonb         NOT NULL DEFAULT '{}'::jsonb,
            inverse     jsonb,
            created_by  uuid          REFERENCES users(id) ON DELETE SET NULL,
            created_at  timestamptz   NOT NULL DEFAULT now(),
            undone_at   timestamptz,
            CONSTRAINT uq_design_operations_seq UNIQUE (design_id, seq)
        )
    """)

    for table in NEW_TABLES:
        _rls(table)

    # A design's working set belongs to it
    for table in ('net_assets', 'net_cables', 'net_connections'):
        op.execute(f"""
            ALTER TABLE {table} ADD CONSTRAINT fk_{table}_design
            FOREIGN KEY (design_id) REFERENCES designs(id) ON DELETE CASCADE
        """)

    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO feature_permissions (feature_key, feature_label, module, description)
        VALUES ('design.edit', 'Create and edit network designs', 'design',
                'Create designs, upload their inputs, draw boundaries and run BOQ and validation')
        ON CONFLICT (feature_key) DO NOTHING
    """))
    conn.execute(sa.text("""
        INSERT INTO department_feature_grants (tenant_id, department_id, feature_key, min_role_level, granted_by)
        SELECT tenant_id, department_id, 'design.edit', min_role_level, granted_by
        FROM department_feature_grants WHERE feature_key = 'fttx_designer.edit'
        ON CONFLICT (tenant_id, department_id, feature_key) DO NOTHING
    """))
    conn.execute(sa.text("""
        INSERT INTO role_feature_overrides (tenant_id, role_id, feature_key, is_granted)
        SELECT tenant_id, role_id, 'design.edit', is_granted
        FROM role_feature_overrides WHERE feature_key = 'fttx_designer.edit'
        ON CONFLICT (tenant_id, role_id, feature_key) DO NOTHING
    """))


def downgrade() -> None:
    conn = op.get_bind()
    for t in ('department_feature_grants', 'role_feature_overrides', 'feature_permissions'):
        conn.execute(sa.text(f"DELETE FROM {t} WHERE feature_key = 'design.edit'"))
    for table in ('net_assets', 'net_cables', 'net_connections'):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS fk_{table}_design")
    op.execute("ALTER TABLE designs DROP CONSTRAINT IF EXISTS fk_designs_current_version")
    for table in NEW_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
