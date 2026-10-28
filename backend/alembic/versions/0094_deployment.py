"""
Network GIS Phase 10 — deployment, as-built, promotion to the live network.

- net_assets.design_geom / asbuilt_geom: as net_cables already has. At
  deployment the designed position is kept in design_geom; the field's
  as-built capture goes to asbuilt_geom AND becomes geom (what the map and
  lengths use), so the variance report compares design with as-built.
- deployments: one per deployed design version — who started it, when it
  was promoted. Installation progress itself is each row's lifecycle
  (CONSTRUCTION → INSTALLED → TESTING → VERIFIED), recorded with its actor
  by the audit trigger (0092); no second status column.
- Feature keys deployment.update, asbuilt.capture, network.promote (plan
  §3.9), no grants copied: admins only until granted.
- The audit trigger (0092) learns one more action: a row whose design_id
  goes from a design to NULL was PROMOTED; and such an entry keeps the
  design's id, so it shows in the design's history as well as the asset's.

Revision ID: 0094
Revises: 0093
"""

import sqlalchemy as sa
from alembic import op

revision      = '0094'
down_revision = '0093'
branch_labels = None
depends_on    = None

def _audit_function(promote: bool) -> str:
    """network_audit_row(), as 0092 wrote it, optionally with the promote rule."""
    promote_case = """
                    WHEN d_old ->> 'design_id' IS NOT NULL AND d_new ? 'design_id'
                         AND d_new ->> 'design_id' IS NULL THEN 'promote'""" if promote else ""
    design_ref = "coalesce(n ->> 'design_id', o ->> 'design_id')" if promote else "row ->> 'design_id'"
    return f"""
        CREATE OR REPLACE FUNCTION network_audit_row() RETURNS trigger AS $$
        DECLARE
            -- updated_at / updated_by are bookkeeping: the entry has its own time and actor
            o jsonb := CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) - 'updated_at' - 'updated_by' END;
            n jsonb := CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) - 'updated_at' - 'updated_by' END;
            row jsonb := coalesce(n, o);
            dsg text;
            changed text[];
            k text;
            d_old jsonb := '{{}}';
            d_new jsonb := '{{}}';
            act text;
        BEGIN
            IF coalesce(current_setting('app.audit_bulk', TRUE), '') = 'off' THEN
                RETURN NULL;
            END IF;
            dsg := {design_ref};
            IF TG_OP = 'UPDATE' THEN
                FOR k IN SELECT jsonb_object_keys(n) LOOP
                    IF o -> k IS DISTINCT FROM n -> k THEN
                        changed := array_append(changed, k);
                        d_old := d_old || jsonb_build_object(k, o -> k);
                        d_new := d_new || jsonb_build_object(k, n -> k);
                    END IF;
                END LOOP;
                IF changed IS NULL THEN
                    RETURN NULL;                      -- only updated_at moved
                END IF;
                act := CASE
                    WHEN d_new ? 'deleted_at' AND d_new ->> 'deleted_at' IS NOT NULL THEN 'delete'
                    WHEN d_new ? 'deleted_at' THEN 'restore'{promote_case}
                    WHEN changed <@ ARRAY['geom', 'length_m'] THEN 'move'
                    WHEN changed <@ ARRAY['lifecycle_status'] THEN 'lifecycle'
                    ELSE 'update' END;
                o := d_old;
                n := d_new;
            ELSE
                act := CASE TG_OP WHEN 'INSERT' THEN 'create' ELSE 'delete' END;
            END IF;
            INSERT INTO network_audit_log (tenant_id, entity_type, entity_id, entity_code, design_id, action,
                                           actor_id, actor_label, changed_fields, old_data, new_data)
            VALUES ((row ->> 'tenant_id')::uuid, TG_ARGV[0], (row ->> 'id')::uuid, row ->> 'asset_code',
                    dsg::uuid, act,
                    nullif(current_setting('app.user_id', TRUE), '')::uuid,
                    coalesce(nullif(current_setting('app.actor_label', TRUE), ''), 'System'),
                    changed, o, n);
            RETURN NULL;
        END
        $$ LANGUAGE plpgsql
    """


KEYS = (
    ('deployment.update', 'Update deployment progress', 'Start a deployment and record installation, testing and verification'),
    ('asbuilt.capture', 'Capture as-built geometry', 'Record where devices and cables were actually installed'),
    ('network.promote', 'Promote to the live network', 'Hand a verified deployment over to the network in service'),
)


def upgrade() -> None:
    op.execute(_audit_function(promote=True))
    op.execute("ALTER TABLE net_assets ADD COLUMN design_geom geometry(Geometry, 4326), "
               "ADD COLUMN asbuilt_geom geometry(Geometry, 4326)")
    op.execute("""
        CREATE TABLE deployments (
            id           uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    uuid          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            design_id    uuid          NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
            version_id   uuid          REFERENCES design_versions(id) ON DELETE SET NULL,
            status       varchar(20)   NOT NULL DEFAULT 'IN_PROGRESS' CHECK (status IN ('IN_PROGRESS', 'PROMOTED')),
            note         text,
            started_by   uuid          REFERENCES users(id) ON DELETE SET NULL,
            started_at   timestamptz   NOT NULL DEFAULT clock_timestamp(),
            promoted_by  uuid          REFERENCES users(id) ON DELETE SET NULL,
            promoted_at  timestamptz,
            summary      jsonb
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_deployments_open ON deployments (design_id) WHERE status = 'IN_PROGRESS'")
    op.execute("ALTER TABLE deployments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE deployments FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON deployments
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)
    conn = op.get_bind()
    for key, label, desc in KEYS:
        conn.execute(sa.text("""
            INSERT INTO feature_permissions (feature_key, feature_label, module, description)
            VALUES (:k, :l, 'network', :d) ON CONFLICT (feature_key) DO NOTHING
        """), {"k": key, "l": label, "d": desc})


def downgrade() -> None:
    conn = op.get_bind()
    for key, _l, _d in KEYS:
        for t in ('department_feature_grants', 'role_feature_overrides', 'feature_permissions'):
            conn.execute(sa.text(f"DELETE FROM {t} WHERE feature_key = :k"), {"k": key})
    op.execute(_audit_function(promote=False))
    op.execute("DROP TABLE IF EXISTS deployments")
    op.execute("ALTER TABLE net_assets DROP COLUMN IF EXISTS asbuilt_geom, DROP COLUMN IF EXISTS design_geom")
