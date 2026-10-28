"""
Network GIS Phase 8 — versioning and the network audit trail.

- network_audit_log: one row per change to a network asset, cable or
  connection (live network and design working sets alike), written by a
  trigger so no path can skip it (API edits, design operations, uploads,
  backfills). An update records only the fields that changed (old → new);
  geometry is stored as GeoJSON. The actor comes from the transaction's
  app.user_id / app.actor_label (design/audit.set_actor), else "System".
  Bulk replacements (auto design, import, restore) set app.audit_bulk = off
  for their transaction and write ONE summary row instead of thousands.
- network_audit_trail: a view over network_audit_log and the existing
  infrastructure_audit_log (which stays as it is, decision D4), so an
  asset's History reads one list.
- design_versions.snapshot_counts / frozen_at: a version is "frozen" when
  its snapshot is taken (it is then immutable); the counts let the version
  list show what each held without unpacking the snapshot.

Revision ID: 0092
Revises: 0091
"""

from alembic import op

revision      = '0092'
down_revision = '0091'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE network_audit_log (
            id              uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       uuid          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            entity_type     varchar(20)   NOT NULL CHECK (entity_type IN ('asset', 'cable', 'connection', 'design')),
            entity_id       uuid,
            entity_code     varchar(200),
            design_id       uuid,
            action          varchar(30)   NOT NULL,
            actor_id        uuid          REFERENCES users(id) ON DELETE SET NULL,
            actor_label     varchar(200)  NOT NULL DEFAULT 'System',
            -- clock_timestamp(), not now(): the rows one transaction writes must keep their order
            occurred_at     timestamptz   NOT NULL DEFAULT clock_timestamp(),
            changed_fields  text[],
            old_data        jsonb,
            new_data        jsonb
        )
    """)
    op.execute("CREATE INDEX ix_network_audit_entity ON network_audit_log (entity_id, occurred_at DESC)")
    op.execute("CREATE INDEX ix_network_audit_design ON network_audit_log (design_id, occurred_at DESC) WHERE design_id IS NOT NULL")
    op.execute("CREATE INDEX ix_network_audit_tenant ON network_audit_log (tenant_id, occurred_at DESC)")
    op.execute("ALTER TABLE network_audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE network_audit_log FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON network_audit_log
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)

    op.execute("""
        CREATE FUNCTION network_audit_row() RETURNS trigger AS $$
        DECLARE
            -- updated_at / updated_by are bookkeeping: the entry has its own time and actor
            o jsonb := CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) - 'updated_at' - 'updated_by' END;
            n jsonb := CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) - 'updated_at' - 'updated_by' END;
            row jsonb := coalesce(n, o);
            changed text[];
            k text;
            d_old jsonb := '{}';
            d_new jsonb := '{}';
            act text;
        BEGIN
            IF coalesce(current_setting('app.audit_bulk', TRUE), '') = 'off' THEN
                RETURN NULL;
            END IF;
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
                    WHEN d_new ? 'deleted_at' THEN 'restore'
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
                    (row ->> 'design_id')::uuid, act,
                    nullif(current_setting('app.user_id', TRUE), '')::uuid,
                    coalesce(nullif(current_setting('app.actor_label', TRUE), ''), 'System'),
                    changed, o, n);
            RETURN NULL;
        END
        $$ LANGUAGE plpgsql
    """)
    for table, kind in (("net_assets", "asset"), ("net_cables", "cable"), ("net_connections", "connection")):
        op.execute(f"""
            CREATE TRIGGER {table}_audit AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION network_audit_row('{kind}')
        """)

    op.execute("""
        CREATE VIEW network_audit_trail AS
        SELECT id, tenant_id, entity_type, entity_id, entity_code, design_id, action, actor_id, actor_label,
               occurred_at, changed_fields, old_data, new_data, 'network'::text AS source
        FROM network_audit_log
        UNION ALL
        SELECT id, tenant_id, asset_type, asset_id, asset_key,
               CASE WHEN asset_type IN ('design', 'design_input') THEN asset_id END,
               action, actor_id, actor_label, "timestamp", NULL::text[], old_data, new_data, 'infrastructure'::text
        FROM infrastructure_audit_log
    """)

    op.execute("ALTER TABLE design_versions ADD COLUMN snapshot_counts jsonb, ADD COLUMN frozen_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE design_versions DROP COLUMN IF EXISTS frozen_at, DROP COLUMN IF EXISTS snapshot_counts")
    op.execute("DROP VIEW IF EXISTS network_audit_trail")
    for table in ("net_assets", "net_cables", "net_connections"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_audit ON {table}")
    op.execute("DROP FUNCTION IF EXISTS network_audit_row()")
    op.execute("DROP TABLE IF EXISTS network_audit_log")
