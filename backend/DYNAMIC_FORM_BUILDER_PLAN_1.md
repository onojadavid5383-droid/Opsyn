# Universal Dynamic Data Collection Framework
## Auto-sync Form Builder to Database Schema

**Project:** OpSyn V1.1  
**Feature:** Universal Data Collection System with Mobile (KoboCollect) Integration  
**Date:** 2026-09-27

---

## Executive Summary

Build a **universal data collection framework** where organizations define their own data models for ANY entity type through a visual form builder, with automatic database schema synchronization.

**Vision:** Organizations control their data destiny. Whether collecting customer information, onboarding staff, registering assets, or conducting field surveys via mobile app - they design the forms, we handle the database complexity.

**Examples:**
- HR: "Staff Onboarding" form with fields: `employee_id`, `department`, `salary_grade`, `blood_group`
- Operations: "Equipment Registry" form with fields: `serial_number`, `purchase_date`, `warranty_expiry`, `location`
- Sales: "Customer Acquisition" form with fields: `lead_source`, `company_size`, `budget`, `decision_maker`
- Field Ops: "Site Survey" form (mobile) with fields: `gps_coordinates`, `site_photo`, `signal_strength`, `obstacles`

**Mobile Integration Ready:** Architecture designed to support KoboCollect-style offline data collection, with sync capabilities when field technicians return to connectivity.

---

## Current State Analysis

### What Exists

Your form builder has:
- `form_schemas` - Form definitions with **module** field (customer, infrastructure, pipeline, field_ops, generic)
- `form_schema_versions` - Immutable snapshots  
- `field_definitions` - 24 field types with validation
- `form_associations` - Links forms to contexts (modules, pipeline stages, departments)
- `form_submissions` - Data stored as JSONB

**Key Insight:** The `module` field in `form_schemas` already supports multiple domains:
- `customer` - Customer data collection
- `infrastructure` - Network infrastructure assets
- `pipeline` - Project pipeline stages
- `field_ops` - Field operations and surveys
- `generic` - Any custom entity type

### The Gap

Form fields are metadata only. No actual database columns are created. All data lives in JSONB blobs with no SQL-level validation or queryability.

### The Opportunity

Transform form_schemas into a **universal entity definition system** where each schema represents a data collection template for ANY business entity.

---

## Solution Architecture

### Universal Entity Model: Dynamic Tables Per Schema

**Core Principle:** Every `FormSchema` is a reusable entity definition that generates its own database table when published.

Create one PostgreSQL table per published form schema:

**Table naming:** `tenant_{tenant_id}_{machine_name}_data`

**Examples Across Different Domains:**

| Entity Type | Machine Name | Generated Table |
|-------------|-------------|----------------|
| Customer Onboarding | `customer_onboarding` | `tenant_abc_customer_onboarding_data` |
| Staff Registration | `staff_registration` | `tenant_abc_staff_registration_data` |
| Equipment Inventory | `equipment_inventory` | `tenant_abc_equipment_inventory_data` |
| Site Survey (Mobile) | `site_survey` | `tenant_abc_site_survey_data` |
| Department Creation | `department_master` | `tenant_abc_department_master_data` |
| Vendor Management | `vendor_profile` | `tenant_abc_vendor_profile_data` |

**Module Classification:**
- `customer` - Customer-facing forms
- `infrastructure` - Asset and network infrastructure
- `hr` - Human resources and staff management (NEW)
- `operations` - General operational data (NEW)
- `field_ops` - Mobile field data collection
- `generic` - Anything else

### Field Type Mapping (KoboCollect Compatible)

Designed to align with KoboCollect/ODK field types for future mobile app integration:

| Form Type | PostgreSQL Type | KoboCollect Equivalent | Use Case |
|-----------|----------------|----------------------|----------|
| string | VARCHAR(500) | text | Short text input |
| text | TEXT | textarea | Long text, notes |
| integer | INTEGER | integer | Counts, IDs |
| float | NUMERIC(12,4) | decimal | Measurements, ratings |
| boolean | BOOLEAN | select_one (yes/no) | Yes/No questions |
| date | DATE | date | Birth dates, deadlines |
| datetime | TIMESTAMPTZ | datetime | Timestamps with timezone |
| time | TIME | time | Time of day |
| email | VARCHAR(255) | email (custom validation) | Email addresses |
| phone | VARCHAR(50) | phone (custom validation) | Phone numbers |
| url | VARCHAR(1000) | text + url validation | Website links |
| enum | VARCHAR(100) + CHECK | select_one | Single choice dropdown |
| multiselect | TEXT[] | select_multiple | Multiple choice |
| radio | VARCHAR(100) + CHECK | select_one (radio) | Radio button choice |
| file | VARCHAR(500) | file | Document upload |
| image | VARCHAR(500) | image | Photo capture |
| signature | VARCHAR(500) | signature | Digital signature |
| coordinates | JSONB | geopoint | GPS location (lat/lng) |
| address | JSONB | text (structured) | Full address |
| currency | NUMERIC(12,2) | decimal | Money values |
| rating | SMALLINT | range | Star/numeric rating |
| lookup | UUID + FK | select_one_from_file | Reference another entity |
| computed | TEXT | calculate | Derived/calculated field |
| section_header | N/A | note | Visual separator |

**Mobile-First Additions (Future):**
- `geotrace` - GPS path/route
- `geoshape` - GPS area/polygon
- `barcode` - Barcode/QR scanner
- `audio` - Audio recording
- `video` - Video recording

---

## Implementation Phases

### Phase 1: Migration History Table

Create tracking table for all schema changes:

```sql
CREATE TABLE schema_migration_history (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    schema_id UUID NOT NULL,
    migration_name VARCHAR(100),
    alembic_revision VARCHAR(32),
    change_type VARCHAR(50),
    field_changes JSONB,
    forward_sql TEXT,
    rollback_sql TEXT,
    status VARCHAR(20),
    applied_by UUID,
    applied_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### Phase 2: Migration Service

Create `app/modules/form_builder/schema_migration_service.py`:

```python
class SchemaMigrationService:
    async def plan_migration(
        schema_id: UUID,
        field_changes: list
    ) -> MigrationPlan:
        # Preview SQL without executing
        pass
    
    async def execute_migration(
        migration_plan: MigrationPlan
    ) -> MigrationResult:
        # Generate and run Alembic migration
        pass
    
    async def rollback_migration(
        migration_id: UUID
    ) -> RollbackResult:
        # Revert migration
        pass
```

### Phase 3: Alembic Generator

Build programmatic migration file creator:

```python
class AlembicMigrationGenerator:
    def generate_migration_file(
        migration_name: str,
        operations: list,
        tenant_id: UUID
    ) -> str:
        # Create file in alembic/versions/
        # Return file path
        pass
```

### Phase 4: API Updates

Modify field creation endpoint:

**Before:**
```python
@router.post("/schemas/{id}/fields")
async def create_field(...):
    field = FieldDefinition(...)
    db.add(field)
    await db.commit()
    return field
```

**After:**
```python
@router.post("/schemas/{id}/fields")
async def create_field(...):
    field = FieldDefinition(...)
    db.add(field)
    await db.flush()
    
    if schema.status == "published":
        # Schema has database table
        plan = await migration_service.plan_migration(
            schema_id,
            [FieldChange(action="add", field=field)]
        )
        return {
            "field": field,
            "requires_migration": True,
            "migration_plan": {
                "sql": plan.forward_sql,
                "duration": "< 1s"
            }
        }
    
    await db.commit()
    return {"field": field}
```

Add new endpoints:

```python
@router.post("/schemas/{id}/execute-migration")
async def execute_migration(...):
    # User confirmed, run the migration
    pass

@router.get("/schemas/{id}/migration-history")
async def get_migration_history(...):
    # List all migrations for schema
    pass

@router.post("/migrations/{id}/rollback")
async def rollback_migration(...):
    # Revert migration
    pass
```

### Phase 5: Validation Layer

Safety checks before migration:

1. Check column name doesn't exist
2. Check not SQL reserved word
3. If required field, ensure default value provided
4. Lock schema during migration

```python
class MigrationValidator:
    async def validate_add_column(
        table_name: str,
        column_name: str,
        field_def: FieldDefinition
    ) -> ValidationResult:
        errors = []
        
        if await self._column_exists(table_name, column_name):
            errors.append("Column already exists")
        
        if column_name.upper() in SQL_RESERVED_WORDS:
            errors.append("SQL reserved keyword")
        
        if field_def.is_required and not field_def.default_value:
            row_count = await self._count_rows(table_name)
            if row_count > 0:
                errors.append(f"Cannot add required field without default. {row_count} rows exist.")
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors
        )
```

### Phase 6: Transaction Safety

All migrations in transactions:

```python
async def execute_migration(self, plan: MigrationPlan):
    async with self.db.begin():
        try:
            # Lock schema
            await self.db.execute(
                text("SELECT * FROM form_schemas WHERE id = :id FOR UPDATE"),
                {"id": plan.schema_id}
            )
            
            # Generate migration file
            file_path = self.generator.generate_migration_file(...)
            
            # Run Alembic upgrade
            command.upgrade(config, "head")
            
            # Log success
            history = SchemaMigrationHistory(
                status="applied",
                applied_at=datetime.utcnow()
            )
            self.db.add(history)
            
        except Exception as e:
            # Transaction rolls back automatically
            raise MigrationError(str(e))
```

### Phase 7: RLS Policies

Every dynamic table gets tenant isolation:

```sql
ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table_name}
USING (
    tenant_id = current_setting('app.tenant_id', TRUE)::uuid
);
```

### Phase 8: Frontend Integration

Migration preview modal:

```tsx
const MigrationPreviewModal = ({ plan, onConfirm, onCancel }) => (
  <Modal title="Database Change Required">
    <Alert type="warning">
      This will alter the database table structure.
    </Alert>
    
    <CodeBlock language="sql">
      {plan.sql_preview}
    </CodeBlock>
    
    <MetadataGrid>
      <Item label="Duration" value={plan.duration} />
      <Item label="Rows Affected" value={plan.affected_rows} />
      <Item label="Reversible" value={plan.reversible ? "Yes" : "No"} />
    </MetadataGrid>
    
    <ButtonGroup>
      <Button onClick={onCancel}>Cancel</Button>
      <Button variant="primary" onClick={onConfirm}>
        Apply Migration
      </Button>
    </ButtonGroup>
  </Modal>
);
```

---

## Security Considerations

1. **SQL Injection:** All table/column names validated via regex
2. **Permissions:** Only `forms.admin` can trigger migrations
3. **Tenant Isolation:** RLS on all dynamic tables
4. **Audit Trail:** Log every migration with user and timestamp

---

## Testing Strategy

**Unit Tests:**
- Field type to SQL mapping
- SQL generation correctness
- Validation logic

**Integration Tests:**
- Full migration flow
- Rollback scenarios
- Failure recovery

**Edge Cases:**
- Adding required field to populated table
- Duplicate column names
- Reserved SQL keywords
- Large table modifications

---

## Rollout Plan

1. **Week 1-2:** Build core service
2. **Week 3-4:** API integration
3. **Week 5-6:** Safety and validation
4. **Week 7:** UI components
5. **Week 8:** Internal testing
6. **Week 9-10:** Beta with pilot tenants
7. **Week 11:** General availability

---

## Known Limitations

1. Cannot change field type after creation
2. Cannot rename columns
3. Large tables may require maintenance window
4. Depends on Alembic functionality

---

## Success Metrics

- Migration success rate > 99%
- Execution time < 2 seconds
- Zero data loss
- User satisfaction > 4.5/5

---

## Development Checklist

- [ ] Create migration history table
- [ ] Build SchemaMigrationService
- [ ] Implement AlembicMigrationGenerator
- [ ] Add validation layer
- [ ] Update API endpoints
- [ ] Apply RLS policies
- [ ] Build frontend components
- [ ] Write tests
- [ ] Create documentation

---

**Timeline:** 7-8 weeks  
**Risk:** Medium-High  
**Impact:** High
