"""
Network GIS Phase 5 — auto design (Track A).

- fttx_design_runs.design_id: the design an engine run was made for
  (Auto design queues a run from the design's own inputs). Nullable: runs
  made in the standalone FTTx Designer have none.
- fttx_design_runs.design_version_id: the design version the run's output
  became (set when the output is written into the design's working set,
  by an auto run or by "Import existing run").
- net_cables.route_method gains DIRECT: a straight line by design — the
  engine's drop cables run from the FAT straight to the premises. Neither
  road-routed nor hand-drawn, so validation does not flag it.

Revision ID: 0091
Revises: 0090
"""

from alembic import op

revision      = '0091'
down_revision = '0090'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE fttx_design_runs
            ADD COLUMN design_id         uuid REFERENCES designs(id) ON DELETE SET NULL,
            ADD COLUMN design_version_id uuid REFERENCES design_versions(id) ON DELETE SET NULL
    """)
    op.execute("CREATE INDEX ix_fttx_design_runs_design ON fttx_design_runs (design_id, created_at DESC) WHERE design_id IS NOT NULL")

    op.execute("ALTER TABLE net_cables DROP CONSTRAINT IF EXISTS net_cables_route_method_check")
    op.execute("""
        ALTER TABLE net_cables ADD CONSTRAINT net_cables_route_method_check
        CHECK (route_method IN ('ROAD_GRAPH', 'MANUAL_GEOMETRY', 'IMPORTED', 'DIRECT'))
    """)


def downgrade() -> None:
    # DIRECT only ever marks engine drops inside design working sets; they
    # read as hand-drawn on the older schema, with the original kept
    op.execute("""
        UPDATE net_cables
        SET route_method = 'MANUAL_GEOMETRY',
            attributes   = attributes || '{"route_method_before_downgrade": "DIRECT"}'::jsonb
        WHERE route_method = 'DIRECT'
    """)
    op.execute("ALTER TABLE net_cables DROP CONSTRAINT IF EXISTS net_cables_route_method_check")
    op.execute("""
        ALTER TABLE net_cables ADD CONSTRAINT net_cables_route_method_check
        CHECK (route_method IN ('ROAD_GRAPH', 'MANUAL_GEOMETRY', 'IMPORTED'))
    """)
    op.execute("DROP INDEX IF EXISTS ix_fttx_design_runs_design")
    op.execute("ALTER TABLE fttx_design_runs DROP COLUMN IF EXISTS design_version_id, DROP COLUMN IF EXISTS design_id")
