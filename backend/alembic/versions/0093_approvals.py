"""
Network GIS Phase 9 — design and BOQ approval (standalone, decision D3).

- approval_requests: one submission of a design version (DESIGN_VERSION) or
  of its BOQ (BOQ, a numbered revision with its quantities frozen in
  payload). status PENDING → APPROVED | REJECTED | WITHDRAWN.
  pipeline_stage_id is the reserved hook for linking to project pipeline
  stages later (unused, D3).
- approval_steps: the ordered steps of a request — Design: engineering
  review → line manager approval; BOQ: BOQ review → BOQ approval — each
  with the feature key that may decide it, the decision, comment, actor, time.
- approval_comments: review comments, on the design or pinned to an asset,
  a cable or a point; resolvable.
- Feature keys design.review, design.approve, boq.review, boq.approve.
  No grants are copied: approving is a separate power from editing, so
  until an administrator grants them (Settings → permissions) only admins
  hold them.

Revision ID: 0093
Revises: 0092
"""

import sqlalchemy as sa
from alembic import op

revision      = '0093'
down_revision = '0092'
branch_labels = None
depends_on    = None

TABLES = ('approval_comments', 'approval_steps', 'approval_requests')
KEYS = (
    ('design.review', 'Review network designs', 'Engineering review of a submitted design version'),
    ('design.approve', 'Approve network designs', 'Line manager approval of a reviewed design version'),
    ('boq.review', 'Review design BOQs', 'Review of a BOQ submitted against an approved design'),
    ('boq.approve', 'Approve design BOQs', 'Final approval of a reviewed BOQ'),
)


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
    op.execute("""
        CREATE TABLE approval_requests (
            id                 uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          uuid          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            design_id          uuid          NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
            subject_type       varchar(20)   NOT NULL CHECK (subject_type IN ('DESIGN_VERSION', 'BOQ')),
            subject_id         uuid          NOT NULL,
            revision           integer       NOT NULL,
            status             varchar(20)   NOT NULL DEFAULT 'PENDING'
                                             CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN')),
            current_step       integer       NOT NULL DEFAULT 1,
            note               text,
            payload            jsonb         NOT NULL DEFAULT '{}'::jsonb,
            pipeline_stage_id  uuid,
            submitted_by       uuid          REFERENCES users(id) ON DELETE SET NULL,
            submitted_at       timestamptz   NOT NULL DEFAULT clock_timestamp(),
            decided_at         timestamptz
        )
    """)
    op.execute("CREATE INDEX ix_approval_requests_design ON approval_requests (design_id, submitted_at DESC)")
    # One open request per design and subject type
    op.execute("""
        CREATE UNIQUE INDEX uq_approval_requests_pending ON approval_requests (design_id, subject_type)
        WHERE status = 'PENDING'
    """)
    op.execute("""
        CREATE TABLE approval_steps (
            id           uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    uuid          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            request_id   uuid          NOT NULL REFERENCES approval_requests(id) ON DELETE CASCADE,
            step_no      integer       NOT NULL,
            step_key     varchar(40)   NOT NULL,
            label        varchar(100)  NOT NULL,
            feature_key  varchar(60)   NOT NULL,
            status       varchar(20)   NOT NULL DEFAULT 'WAITING'
                                       CHECK (status IN ('WAITING', 'PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')),
            decided_by   uuid          REFERENCES users(id) ON DELETE SET NULL,
            decided_at   timestamptz,
            comment      text,
            CONSTRAINT uq_approval_steps_no UNIQUE (request_id, step_no)
        )
    """)
    op.execute("""
        CREATE TABLE approval_comments (
            id           uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    uuid          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            request_id   uuid          NOT NULL REFERENCES approval_requests(id) ON DELETE CASCADE,
            design_id    uuid          NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
            asset_id     uuid,
            cable_id     uuid,
            target_code  varchar(200),
            geom         geometry(Point, 4326),
            body         text          NOT NULL CHECK (length(trim(body)) > 0),
            author_id    uuid          REFERENCES users(id) ON DELETE SET NULL,
            created_at   timestamptz   NOT NULL DEFAULT clock_timestamp(),
            resolved_at  timestamptz,
            resolved_by  uuid          REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    op.execute("CREATE INDEX ix_approval_comments_request ON approval_comments (request_id, created_at)")
    for t in TABLES:
        _rls(t)

    conn = op.get_bind()
    for key, label, desc in KEYS:
        conn.execute(sa.text("""
            INSERT INTO feature_permissions (feature_key, feature_label, module, description)
            VALUES (:k, :l, 'design', :d) ON CONFLICT (feature_key) DO NOTHING
        """), {"k": key, "l": label, "d": desc})


def downgrade() -> None:
    conn = op.get_bind()
    for key, _l, _d in KEYS:
        for t in ('department_feature_grants', 'role_feature_overrides', 'feature_permissions'):
            conn.execute(sa.text(f"DELETE FROM {t} WHERE feature_key = :k"), {"k": key})
    for t in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t}")
