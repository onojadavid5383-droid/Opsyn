"""Engineering module: BOQ and Products schema for Phase 1

Adds tables for Bill of Quantities management and product catalog:
- products: catalog of items for BOQ (labor, consumables, equipment, permits, services)
- project_boq: BOQ container linked to project and design
- boq_items: line items in BOQ (from design or products)

Also enhances designs table with fields needed for engineering workflow.

Revision ID: 0099
Revises: 0098
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision      = '0099'
down_revision = '0098'
branch_labels = None
depends_on    = None

BOQ_STATUSES = ('draft', 'submitted', 'approved', 'rejected')
PRODUCT_CATEGORIES = ('labor', 'consumable', 'equipment_rental', 'permit', 'service', 'material')
ITEM_SOURCES = ('design', 'product')


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
    # Add deployment-related fields to designs table
    op.add_column('designs', sa.Column('deployment_status', sa.String(30),
                                       server_default='not_ready', nullable=False))
    op.add_column('designs', sa.Column('coverage_area_sqkm', sa.Numeric(10, 2)))
    op.add_column('designs', sa.Column('estimated_homes_passed', sa.Integer()))

    # Add CHECK constraint for deployment_status
    op.execute("""
        ALTER TABLE designs ADD CONSTRAINT designs_deployment_status_check
        CHECK (deployment_status IN ('not_ready', 'proposed', 'in_deployment', 'completed', 'as_built_documented'))
    """)

    # Create products catalog table
    op.execute(f"""
        CREATE TABLE products (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            product_code varchar(100) NOT NULL,
            product_name varchar(200) NOT NULL,
            category varchar(100) NOT NULL CHECK (category IN {_in(PRODUCT_CATEGORIES)}),
            description text,
            unit varchar(50) NOT NULL,
            standard_cost numeric(15, 2),
            supplier varchar(200),
            lead_time_days integer,
            specifications jsonb DEFAULT '{{}}'::jsonb,
            is_active boolean NOT NULL DEFAULT true,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE(tenant_id, product_code)
        )
    """)
    op.execute("CREATE INDEX ix_products_tenant ON products (tenant_id)")
    op.execute("CREATE INDEX ix_products_category ON products (tenant_id, category) WHERE is_active = true")
    op.execute("CREATE INDEX ix_products_code ON products (tenant_id, product_code)")
    _rls('products')

    # Create project BOQ table
    op.execute(f"""
        CREATE TABLE project_boq (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            design_id uuid REFERENCES designs(id) ON DELETE SET NULL,
            boq_number varchar(50),
            boq_status varchar(30) NOT NULL DEFAULT 'draft' CHECK (boq_status IN {_in(BOQ_STATUSES)}),
            total_material_cost numeric(15, 2) DEFAULT 0,
            total_product_cost numeric(15, 2) DEFAULT 0,
            total_cost numeric(15, 2) DEFAULT 0,
            notes text,
            submitted_by uuid REFERENCES users(id) ON DELETE SET NULL,
            approved_by uuid REFERENCES users(id) ON DELETE SET NULL,
            submitted_at timestamptz,
            approved_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_project_boq_project ON project_boq (project_id)")
    op.execute("CREATE INDEX ix_project_boq_design ON project_boq (design_id)")
    op.execute("CREATE INDEX ix_project_boq_status ON project_boq (tenant_id, boq_status)")
    _rls('project_boq')

    # Create BOQ items table
    op.execute(f"""
        CREATE TABLE boq_items (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            boq_id uuid NOT NULL REFERENCES project_boq(id) ON DELETE CASCADE,
            item_source varchar(20) NOT NULL CHECK (item_source IN {_in(ITEM_SOURCES)}),
            design_item_id uuid,
            product_id uuid REFERENCES products(id) ON DELETE SET NULL,
            item_code varchar(100),
            item_name varchar(200) NOT NULL,
            description text,
            quantity numeric(15, 3) NOT NULL,
            unit varchar(50) NOT NULL,
            unit_cost numeric(15, 2),
            total_cost numeric(15, 2),
            supplier varchar(200),
            lead_time_days integer,
            specifications jsonb DEFAULT '{{}}'::jsonb,
            notes text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_boq_items_boq ON boq_items (boq_id)")
    op.execute("CREATE INDEX ix_boq_items_source ON boq_items (boq_id, item_source)")
    op.execute("CREATE INDEX ix_boq_items_product ON boq_items (product_id)")
    _rls('boq_items')


def downgrade() -> None:
    # Drop BOQ tables
    op.execute("DROP TABLE IF EXISTS boq_items CASCADE")
    op.execute("DROP TABLE IF EXISTS project_boq CASCADE")
    op.execute("DROP TABLE IF EXISTS products CASCADE")

    # Remove columns from designs table
    op.drop_column('designs', 'estimated_homes_passed')
    op.drop_column('designs', 'coverage_area_sqkm')
    op.drop_column('designs', 'deployment_status')
