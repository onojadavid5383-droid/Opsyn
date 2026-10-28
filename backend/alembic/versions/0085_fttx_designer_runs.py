"""FTTx Designer — Phase 3 (1/1): design run tables

Backs the web port of the standalone QGIS "FTTx Designer" script
(see app/modules/fttx_designer/engine/, ported across Phase 2). A design
run replaces one interactive "Run Network Design" click in the desktop
tool: the user uploads road/homepass/pole (+ optional building/pickup)
layers as GeoJSON, the pipeline runs as a Celery task
(app/modules/fttx_designer/engine/pipeline.run_fttx_design), and the
result — FDT/FAT/cable/closure layers, BOQ rows, optical loss summary —
is persisted for the frontend to poll and render.

Three tables:
  fttx_design_runs         — one row per run: config, status, progress
  fttx_design_run_layers   — one row per uploaded input layer (road,
                              homepass, pole, building, pickup), keyed by
                              (run_id, layer_key) so re-uploading a layer
                              replaces the previous one
  fttx_design_run_outputs  — one row per completed run: the populated
                              output layers (as GeoJSON), BOQ rows, and
                              optical loss summary — everything
                              pipeline.PipelineResult produced, serialized

GeoJSON was chosen for input layers (over Shapefile/GeoPackage) so the
upload boundary needs no new parsing dependency (fiona/geopandas) — RFC
7946 GeoJSON is always WGS84 (EPSG:4326), which also means the pipeline's
CRS-reprojection step (the source script's validate_selected_layers,
still deferred as of Phase 2 — see engine/validation.py's docstring) can
be a single, deterministic EPSG:4326 -> UTM reprojection via pyproj,
rather than the arbitrary multi-CRS handling the desktop tool needs.

RLS follows the same tenant-isolation pattern already used throughout
(e.g. 0030_dept_rbac_tables.py's role_feature_overrides): every table
carries its own tenant_id (denormalized onto the child tables, not just
inherited through a join) so each table's policy is self-contained.

Revision ID: 0085
Revises: 0084
Create Date: 2026-09-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0085'
down_revision = '0084'
branch_labels = None
depends_on    = None


def _tenant_isolation_policy(table_name: str) -> str:
    return f"""
        CREATE POLICY tenant_isolation ON {table_name}
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """


def upgrade() -> None:
    # ── fttx_design_runs ──────────────────────────────────────────────────
    op.create_table(
        'fttx_design_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=True),
        # draft | layers_pending | ready | queued | running | completed | failed | cancelled
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        # Serialized FTTXConfig overrides (deployment_type, cascade_architecture,
        # pon_architecture, coverage_pct, optical_enabled, ...) — see
        # engine/config.py's FTTXConfig for the full field set. Only fields the
        # user actually chose in the wizard need to be present; the task applies
        # them on top of FTTXConfig()'s own defaults.
        sa.Column('config', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('progress_pct', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('progress_message', sa.String(200), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('celery_task_id', sa.String(100), nullable=True),
        # Cheap counts for list views, without loading fttx_design_run_outputs'
        # full GeoJSON — {fat_count, fdt_count, closure_count, b2b_cable_count,
        # b2c_cable_count, homepass_count, optical_pass/marginal/fail/invalid}.
        sa.Column('result_summary', postgresql.JSONB(), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index('ix_fttx_design_runs_tenant', 'fttx_design_runs', ['tenant_id'])
    op.create_index('ix_fttx_design_runs_status', 'fttx_design_runs', ['status'])

    op.execute("ALTER TABLE fttx_design_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE fttx_design_runs FORCE ROW LEVEL SECURITY")
    op.execute(_tenant_isolation_policy('fttx_design_runs'))

    # ── fttx_design_run_layers ───────────────────────────────────────────
    op.create_table(
        'fttx_design_run_layers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('fttx_design_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        # 'road' | 'homepass' | 'pole' | 'building' | 'pickup' — matches the
        # engine pipeline's `layers` dict keys exactly (see pipeline.py).
        sa.Column('layer_key', sa.String(20), nullable=False),
        sa.Column('original_filename', sa.String(500), nullable=True),
        sa.Column('feature_count', sa.Integer(), nullable=True),
        # The uploaded GeoJSON FeatureCollection, verbatim (WGS84) — the
        # Celery task re-parses this into a QgsVectorLayer and reprojects
        # to the run's target UTM zone at execution time, never at upload
        # time, so a later upload of a different layer can still determine
        # the correct shared UTM zone from the full set.
        sa.Column('geojson', postgresql.JSONB(), nullable=False),
        sa.Column('uploaded_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('uploaded_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index('ix_fttx_design_run_layers_tenant', 'fttx_design_run_layers', ['tenant_id'])
    op.create_index('ix_fttx_design_run_layers_run', 'fttx_design_run_layers', ['run_id'])
    op.create_unique_constraint(
        'uq_fttx_design_run_layers_run_key',
        'fttx_design_run_layers', ['run_id', 'layer_key'],
    )

    op.execute("ALTER TABLE fttx_design_run_layers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE fttx_design_run_layers FORCE ROW LEVEL SECURITY")
    op.execute(_tenant_isolation_policy('fttx_design_run_layers'))

    # ── fttx_design_run_outputs ──────────────────────────────────────────
    op.create_table(
        'fttx_design_run_outputs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('fttx_design_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        # {layer_key: GeoJSON FeatureCollection} for every layer key in
        # pipeline._OUTPUT_LAYER_SCHEMAS (fdt, fat, b2b, b2c, closure,
        # pole_output, pickup_point, feeder, closure_cable) — see
        # engine/pipeline.py and the GeoJSON serializer that builds this.
        sa.Column('output_layers', postgresql.JSONB(), nullable=False),
        sa.Column('boq_rows', postgresql.JSONB(), nullable=True),
        sa.Column('boq_fdt_rows', postgresql.JSONB(), nullable=True),
        sa.Column('optical_loss_summary', postgresql.JSONB(), nullable=True),
        sa.Column('project_identity', postgresql.JSONB(), nullable=True),
        # Full PerformanceLogger output for this run — the same text a
        # desktop run writes to fttx_run_*.log.
        sa.Column('log_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index('ix_fttx_design_run_outputs_tenant', 'fttx_design_run_outputs', ['tenant_id'])
    op.create_unique_constraint(
        'uq_fttx_design_run_outputs_run', 'fttx_design_run_outputs', ['run_id'],
    )

    op.execute("ALTER TABLE fttx_design_run_outputs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE fttx_design_run_outputs FORCE ROW LEVEL SECURITY")
    op.execute(_tenant_isolation_policy('fttx_design_run_outputs'))

    # ── Permissions ───────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO feature_permissions (feature_key, feature_label, module, description) VALUES
        ('fttx_designer.view', 'View FTTx Designer Runs',  'fttx_designer', 'View FTTx network design runs and their results'),
        ('fttx_designer.edit', 'Run FTTx Designer',        'fttx_designer', 'Create, configure, and execute FTTx network design runs')
        ON CONFLICT (feature_key) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DELETE FROM feature_permissions WHERE feature_key IN ('fttx_designer.view', 'fttx_designer.edit')")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON fttx_design_run_outputs")
    op.drop_constraint('uq_fttx_design_run_outputs_run', 'fttx_design_run_outputs', type_='unique')
    op.drop_index('ix_fttx_design_run_outputs_tenant', table_name='fttx_design_run_outputs')
    op.drop_table('fttx_design_run_outputs')

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON fttx_design_run_layers")
    op.drop_constraint('uq_fttx_design_run_layers_run_key', 'fttx_design_run_layers', type_='unique')
    op.drop_index('ix_fttx_design_run_layers_run', table_name='fttx_design_run_layers')
    op.drop_index('ix_fttx_design_run_layers_tenant', table_name='fttx_design_run_layers')
    op.drop_table('fttx_design_run_layers')

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON fttx_design_runs")
    op.drop_index('ix_fttx_design_runs_status', table_name='fttx_design_runs')
    op.drop_index('ix_fttx_design_runs_tenant', table_name='fttx_design_runs')
    op.drop_table('fttx_design_runs')
