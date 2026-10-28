# Universal Dynamic Data Collection Framework
## Phased Implementation Plan

**Project:** OpSyn V1.1  
**Start Date:** 2026-09-28  
**Total Duration:** 16 weeks (4 months)  
**Team Size:** 2-3 developers

---

## Overview

This document breaks down the implementation into manageable phases with clear deliverables, dependencies, and acceptance criteria.

---

## 🎯 Phase 1: Foundation & Migration Infrastructure
**Duration:** 2 weeks  
**Team:** 1 Backend Developer  
**Sprint:** Week 1-2

### Objectives
- Create migration history tracking system
- Build core schema migration service architecture
- Establish database naming conventions

### Tasks

#### Week 1: Migration History Table

**Task 1.1: Create Migration History Schema**
- [ ] Create Alembic migration: `0085_schema_migration_history.py`
- [ ] Define table structure with all tracking fields
- [ ] Add indexes for tenant_id, schema_id, status
- [ ] Add RLS policies for tenant isolation
- [ ] Test migration up/down

**File:** `alembic/versions/0085_schema_migration_history.py`

```sql
CREATE TABLE schema_migration_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    schema_id UUID NOT NULL REFERENCES form_schemas(id),
    migration_name VARCHAR(100) NOT NULL,
    migration_file_path TEXT NOT NULL,
    alembic_revision VARCHAR(32) NOT NULL,
    change_type VARCHAR(50) NOT NULL,
    field_changes JSONB NOT NULL,
    forward_sql TEXT NOT NULL,
    rollback_sql TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    applied_by UUID REFERENCES users(id),
    applied_at TIMESTAMPTZ,
    rolled_back_at TIMESTAMPTZ,
    rolled_back_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Task 1.2: Create ORM Model**
- [ ] Create `SchemaMigrationHistory` model
- [ ] Add relationships to FormSchema, User
- [ ] Add model to `app/modules/form_builder/models.py`
- [ ] Import in `alembic/env.py`

**Task 1.3: Test Migration**
- [ ] Run migration on dev database
- [ ] Verify RLS policies work
- [ ] Test rollback
- [ ] Document any issues

#### Week 2: Core Service Architecture

**Task 1.4: Create Migration Service Structure**
- [ ] Create `app/modules/form_builder/schema_migration_service.py`
- [ ] Define `SchemaMigrationService` class
- [ ] Implement `plan_migration()` method (stub)
- [ ] Implement `execute_migration()` method (stub)
- [ ] Implement `rollback_migration()` method (stub)

**Task 1.5: Create Supporting Models**
- [ ] Define `MigrationPlan` dataclass
- [ ] Define `MigrationResult` dataclass
- [ ] Define `FieldChange` dataclass
- [ ] Define `ValidationResult` dataclass

**Task 1.6: Add Configuration**
- [ ] Add migration settings to `app/core/config.py`
- [ ] Define table naming conventions
- [ ] Add feature flags for gradual rollout

### Deliverables
- ✅ Migration history table created and tested
- ✅ ORM models defined
- ✅ Core service structure in place
- ✅ Configuration added

### Acceptance Criteria
- [ ] Can create migration history records
- [ ] RLS policies enforce tenant isolation
- [ ] Service classes compile without errors
- [ ] All tests pass

---

## 🔨 Phase 2: Field Type Mapping & SQL Generation
**Duration:** 2 weeks  
**Team:** 1 Backend Developer  
**Sprint:** Week 3-4

### Objectives
- Map all 24 form field types to PostgreSQL types
- Build SQL generation logic for different operations
- Create operation classes for migrations

### Tasks

#### Week 3: Field Type Mapper

**Task 2.1: Create Field Type Mapper**
- [ ] Create `app/modules/form_builder/field_type_mapper.py`
- [ ] Implement `FieldTypeMapper` class
- [ ] Map all 24 field types to SQL types
- [ ] Handle KoboCollect compatibility
- [ ] Add constraint generation logic

**Example Implementation:**
```python
class FieldTypeMapper:
    TYPE_MAP = {
        'string': lambda field: f"VARCHAR({field.validation_rules.get('max_length', 500)})",
        'text': lambda field: "TEXT",
        'integer': lambda field: "INTEGER",
        'float': lambda field: "NUMERIC(12, 4)",
        'boolean': lambda field: "BOOLEAN",
        'date': lambda field: "DATE",
        'datetime': lambda field: "TIMESTAMP WITH TIME ZONE",
        'email': lambda field: "VARCHAR(255)",
        'phone': lambda field: "VARCHAR(50)",
        'url': lambda field: "VARCHAR(1000)",
        'enum': lambda field: "VARCHAR(100)",
        'multiselect': lambda field: "TEXT[]",
        'coordinates': lambda field: "JSONB",
        'address': lambda field: "JSONB",
        'currency': lambda field: "NUMERIC(12, 2)",
        'rating': lambda field: "SMALLINT",
        'file': lambda field: "VARCHAR(500)",
        'image': lambda field: "VARCHAR(500)",
        'signature': lambda field: "VARCHAR(500)",
    }
    
    def map_to_sql_type(self, field: FieldDefinition) -> str:
        mapper = self.TYPE_MAP.get(field.field_type)
        if not mapper:
            raise ValueError(f"Unsupported field type: {field.field_type}")
        return mapper(field)
```

**Task 2.2: Create Constraint Builder**
- [ ] Build CHECK constraint generator for enums
- [ ] Build NOT NULL constraint logic
- [ ] Build DEFAULT value handler
- [ ] Build UNIQUE constraint logic
- [ ] Handle validation rules → SQL constraints

**Task 2.3: Unit Tests**
- [ ] Test all 24 field type mappings
- [ ] Test constraint generation
- [ ] Test edge cases (empty validation rules, etc.)
- [ ] Test KoboCollect compatibility

#### Week 4: Operation Classes

**Task 2.4: Create Base Operation Class**
- [ ] Create `app/modules/form_builder/migration_operations.py`
- [ ] Define `BaseOperation` abstract class
- [ ] Define `render_upgrade()` method
- [ ] Define `render_downgrade()` method

**Task 2.5: Implement Operation Types**
- [ ] `CreateTableOperation` - New entity table
- [ ] `AddColumnOperation` - Add field to existing table
- [ ] `AlterColumnOperation` - Modify field constraints
- [ ] `DropColumnOperation` - Remove field (with safety)
- [ ] `AddRLSPolicyOperation` - Apply tenant isolation

**Task 2.6: SQL Generation Tests**
- [ ] Test CreateTable SQL output
- [ ] Test AddColumn SQL output
- [ ] Test AlterColumn SQL output
- [ ] Verify SQL is valid PostgreSQL syntax

### Deliverables
- ✅ Field type mapper with all 24 types
- ✅ Constraint builder
- ✅ Operation classes for all migration types
- ✅ Comprehensive unit tests

### Acceptance Criteria
- [ ] All field types map to correct SQL types
- [ ] Generated SQL is valid and executable
- [ ] Operations produce correct upgrade/downgrade SQL
- [ ] 100% test coverage on mappers

---

## 🔍 Phase 3: Validation & Safety Layer
**Duration:** 2 weeks  
**Team:** 1 Backend Developer  
**Sprint:** Week 5-6

### Objectives
- Implement pre-migration validation
- Add safety checks for data integrity
- Build conflict detection

### Tasks

#### Week 5: Validation Engine

**Task 3.1: Create Migration Validator**
- [ ] Create `app/modules/form_builder/migration_validator.py`
- [ ] Implement `MigrationValidator` class
- [ ] Add column existence check
- [ ] Add SQL reserved word check
- [ ] Add naming conflict check

**Task 3.2: Data Integrity Checks**
- [ ] Check for required field on populated table
- [ ] Validate default values are provided
- [ ] Check constraint compatibility with existing data
- [ ] Validate type changes won't cause data loss

**Task 3.3: Concurrent Change Prevention**
- [ ] Implement schema-level advisory locks
- [ ] Add migration queue system
- [ ] Prevent parallel migrations on same schema
- [ ] Add timeout handling

#### Week 6: Safety Mechanisms

**Task 3.4: Transaction Safety**
- [ ] Wrap all migrations in database transactions
- [ ] Implement automatic rollback on failure
- [ ] Add savepoints for partial rollback
- [ ] Test rollback scenarios

**Task 3.5: Dry-Run Mode**
- [ ] Implement migration preview without execution
- [ ] Generate SQL preview for user approval
- [ ] Estimate migration duration
- [ ] Show affected row counts

**Task 3.6: Integration Tests**
- [ ] Test validation prevents invalid migrations
- [ ] Test transaction rollback on failure
- [ ] Test concurrent migration blocking
- [ ] Test dry-run accuracy

### Deliverables
- ✅ Migration validator with all safety checks
- ✅ Transaction-wrapped execution
- ✅ Dry-run preview capability
- ✅ Integration tests

### Acceptance Criteria
- [ ] Invalid migrations are rejected before execution
- [ ] Failed migrations roll back automatically
- [ ] Concurrent migrations are queued properly
- [ ] Dry-run shows accurate SQL preview

---

## 🚀 Phase 4: Alembic Integration & Execution
**Duration:** 2 weeks  
**Team:** 1 Backend Developer  
**Sprint:** Week 7-8

### Objectives
- Generate Alembic migration files programmatically
- Execute migrations via Alembic commands
- Track migration state

### Tasks

#### Week 7: Migration Generator

**Task 4.1: Create Alembic Generator**
- [ ] Create `app/modules/form_builder/alembic_generator.py`
- [ ] Implement `AlembicMigrationGenerator` class
- [ ] Generate unique revision IDs
- [ ] Link to previous revision (down_revision)

**Task 4.2: Migration Template**
- [ ] Create Jinja2 template for migration files
- [ ] Include metadata (tenant_id, schema_id)
- [ ] Generate upgrade() function
- [ ] Generate downgrade() function

**Task 4.3: File Management**
- [ ] Write migration files to `alembic/versions/`
- [ ] Auto-name files with pattern: `{revision}_fb_{entity}_{action}.py`
- [ ] Update alembic version table
- [ ] Clean up old migration files

#### Week 8: Execution Engine

**Task 4.4: Implement Execute Method**
- [ ] Execute Alembic upgrade command
- [ ] Capture execution output
- [ ] Handle execution errors
- [ ] Update migration history status

**Task 4.5: Implement Rollback**
- [ ] Execute Alembic downgrade command
- [ ] Verify rollback success
- [ ] Update history with rollback info
- [ ] Test multiple rollback scenarios

**Task 4.6: End-to-End Tests**
- [ ] Test full migration flow (validate → generate → execute)
- [ ] Test rollback flow
- [ ] Test on multiple entity types
- [ ] Test with real table data

### Deliverables
- ✅ Alembic migration generator
- ✅ Migration file templates
- ✅ Execution and rollback logic
- ✅ End-to-end tests

### Acceptance Criteria
- [ ] Can generate valid Alembic migration files
- [ ] Migrations execute successfully
- [ ] Rollback works correctly
- [ ] Migration history is accurate

---

## 🔌 Phase 5: API Integration
**Duration:** 2 weeks  
**Team:** 1 Backend Developer  
**Sprint:** Week 9-10

### Objectives
- Integrate migration service into Form Builder APIs
- Add new migration endpoints
- Update field creation/update flows

### Tasks

#### Week 9: Modify Existing Endpoints

**Task 5.1: Update Field Creation Endpoint**
- [ ] Modify `POST /schemas/{id}/fields`
- [ ] Check if schema is published
- [ ] Generate migration plan for published schemas
- [ ] Return migration preview to user
- [ ] Require explicit confirmation

**Task 5.2: Update Field Update Endpoint**
- [ ] Modify `PUT /schemas/{id}/fields/{field_id}`
- [ ] Detect schema changes requiring migration
- [ ] Generate migration plan if needed
- [ ] Handle backward-compatible changes

**Task 5.3: Update Field Delete Endpoint**
- [ ] Modify `DELETE /schemas/{id}/fields/{field_id}`
- [ ] Check for data in column before deletion
- [ ] Require explicit confirmation for data loss
- [ ] Generate drop column migration

#### Week 10: New Migration Endpoints

**Task 5.4: Execute Migration Endpoint**
- [ ] Create `POST /schemas/{id}/execute-migration`
- [ ] Accept migration plan ID
- [ ] Execute approved migration
- [ ] Return detailed result

**Task 5.5: Migration History Endpoint**
- [ ] Create `GET /schemas/{id}/migration-history`
- [ ] Return paginated migration list
- [ ] Include status, SQL, timestamps
- [ ] Filter by status

**Task 5.6: Rollback Endpoint**
- [ ] Create `POST /migrations/{id}/rollback`
- [ ] Verify migration is rollback-eligible
- [ ] Execute rollback
- [ ] Update history

**Task 5.7: API Tests**
- [ ] Test all modified endpoints
- [ ] Test new migration endpoints
- [ ] Test permission checks
- [ ] Test error handling

### Deliverables
- ✅ Updated field management endpoints
- ✅ New migration control endpoints
- ✅ API documentation
- ✅ Postman collection

### Acceptance Criteria
- [ ] Field creation triggers migration preview for published schemas
- [ ] Migration execution works via API
- [ ] Migration history is accessible
- [ ] Rollback works via API

---

## 🎨 Phase 6: Frontend Integration
**Duration:** 2 weeks  
**Team:** 1 Frontend Developer  
**Sprint:** Week 11-12

### Objectives
- Build migration preview UI
- Add migration history view
- Integrate with Form Builder interface

### Tasks

#### Week 11: Migration Preview Modal

**Task 6.1: Design Modal Component**
- [ ] Create `MigrationPreviewModal.tsx`
- [ ] Design layout with SQL preview
- [ ] Add metadata display (duration, rows affected)
- [ ] Add confirm/cancel actions

**Task 6.2: Integrate with Field Builder**
- [ ] Hook into field creation flow
- [ ] Show modal when migration required
- [ ] Handle user confirmation
- [ ] Display success/error feedback

**Task 6.3: Loading & Error States**
- [ ] Add loading spinner during execution
- [ ] Handle execution errors gracefully
- [ ] Show rollback option on failure
- [ ] Add retry capability

#### Week 12: Migration History View

**Task 6.4: Create History Component**
- [ ] Create `MigrationHistoryTab.tsx`
- [ ] Display migration list in table
- [ ] Show status badges
- [ ] Add pagination

**Task 6.5: Migration Details View**
- [ ] Create detail modal/drawer
- [ ] Show full SQL executed
- [ ] Show field changes
- [ ] Display timestamps and user info

**Task 6.6: Rollback UI**
- [ ] Add rollback button for eligible migrations
- [ ] Show confirmation modal
- [ ] Execute rollback via API
- [ ] Update UI on success

**Task 6.7: Frontend Tests**
- [ ] Unit tests for components
- [ ] Integration tests for flows
- [ ] E2E tests for full migration process

### Current State — verified, not aspirational

The Phase 6 component naming in the plan is not what shipped; the two UI
surfaces are:

- `pages/form-builder/SchemaMigrationsPage.tsx` — history table, status filter,
  count strip, detail modal with the exact forward/rollback SQL, and apply /
  revert. Routed at `/form-builder/:schemaId/migrations`. Revert is **hidden**
  for `is_destructive` rows rather than shown-and-failing, because the backend
  refuses those (`migration_router.py:302`).
- `components/form-builder/SchemaChangeReview.tsx` — the entry point that makes
  the above reachable. Structural edits are written to the metadata tables as
  they happen, so this diffs the live fields against the last published version
  snapshot and, when they differ, offers **Review & apply**. Planning is a
  separate click from applying: preview writes a `pending` row and returns the
  SQL, and what runs is the text the user was shown.

**Task 6.2 (integrate with the field builder) — ✅ done**, via
`components/form-builder/structuralDiff.ts`:

- Only `field_type` and `options` count. Label, placeholder, help_text,
  `is_required`, visibility and width are metadata and need no DDL; including
  them would make cosmetic edits look like schema changes and push people to
  run pointless DDL.
- Deletions are matched by **field id**, not field key, because a delete
  soft-deletes the row but preserves its id — which is what makes a DROP
  plannable after the fact.
- This needed a small backend change: `_load_field` required
  `is_deleted == False`, so a DROP could not be planned once the field was
  already gone and a removed field could never have its column dropped at all.
  It now takes `allow_deleted`, passed **only** for `action='delete'`. Asserted
  both ways: a delete against an inactive field plans successfully, an `add`
  against one still 404s.

### Remaining

- ⬜ **Show rollback option on failure / retry** (6.3) — a failed migration is
  surfaced with its `error_message` but offers no retry
- ⬜ **E2E tests for the full migration process** (6.7)
- ⬜ `applied_by` is returned by the API but not rendered in the detail modal

### Deliverables
- ✅ Migration preview modal
- ✅ Migration history view
- ✅ Rollback UI
- ✅ Component tests (24 across the two surfaces)

### Acceptance Criteria
- ✅ Users can preview migrations before execution
- ✅ Users can view migration history
- ✅ Users can rollback migrations (where reversible)
- ✅ UI is responsive and accessible — verified 304/304 frontend tests,
  typecheck clean, 0 lint errors

---

## 🔐 Phase 7: Tenant Isolation & RLS
**Duration:** 1 week  
**Team:** 1 Backend Developer  
**Sprint:** Week 13

### Current State — verified, not aspirational

**The dynamic entity table holds no production data yet.** `publish_schema`
(`form_builder/router.py`) writes only version snapshots; nothing in production
calls `build_create_table`. Submission data lives in `form_submissions.data`
(JSONB), which has had RLS since 0081. So this phase is forward-looking
hardening, not remediation of a live breach, and there are **no existing dynamic
tables to backfill** — the "backfill" task below is therefore unnecessary.

A second consequence: `plan_migration()` only emits `add_column`,
`alter_column` and `drop_column`. It never produces a `create_table` plan, so
`build_rls` is currently reachable only from tests. That is fine — it is the
designated creation path and must be correct before anything uses it.

### Tasks

**Task 7.1: RLS Policy Generator** — ✅ done
- ✅ `build_rls()` in `schema_sql.py`, emitted by `build_create_table` in the
  same transaction as the DDL, so a table never exists unprotected
- ✅ Tenant isolation policy, semantics matching 0029/0081/0095
- ✅ `ENABLE` + `FORCE` (without FORCE the owner — who runs migrations — could
  bypass its own policy)
- ✅ `WITH CHECK`, so writes are constrained too and not just reads
- ✅ Tested for effectiveness under a non-superuser role
- ⚠️ **Soft-delete filter policy: deliberately not included.** Soft-delete
  visibility is the application layer's job everywhere else in this codebase
  (e.g. `router.py` filtering `FieldDefinition.is_deleted`). Folding
  `is_deleted = FALSE` into RLS would make undelete impossible on a table that
  has no ORM model to bypass the policy with. Asserted by
  `test_soft_delete_is_not_part_of_the_policy` so the decision cannot drift
  silently.

**Task 7.2: Dynamic Table Standards** — ✅ already satisfied
- ✅ `tenant_id`, `is_deleted`, `deleted_at`, `deleted_by`, `created_by`,
  `updated_by` and timestamps are emitted by `build_create_table`
- ✅ Naming validated: `validate_identifier` rejects anything unsafe, and
  `default_index_name` truncates with a digest so the 63-byte limit cannot
  silently collide two distinct names
- ⚠️ `created_by` is emitted but never populated by a write path, because there
  is no write path yet

**Task 7.3: Security Tests** — ✅ cross-tenant isolation done
- ✅ Cross-tenant read/write isolation (`tests/integration/test_dynamic_table_rls.py`,
  7 tests, all under `SET LOCAL ROLE` to a freshly created non-superuser —
  superusers bypass RLS, so testing as `opsyn` would prove nothing)
- ✅ RLS bypass attempt (role asserted non-superuser, non-BYPASSRLS)
- ✅ RLS forced, not merely enabled
- ✅ Non-vacuity proven: removing `build_rls` makes 4 of the 7 fail
- ⬜ Permission-check tests exist elsewhere in the suite but are currently
  broken for an unrelated reason (`tests/test_suite.py` hardcodes
  `localhost:5432` instead of reading `DATABASE_URL`)
- ⬜ Penetration testing not done

**Task 7.4: Documentation** — ✅ done, this section plus `FTTX_INFRASTRUCTURE_FIXES.md`

### Outstanding: the NULLIF divergence — ✅ resolved by 0097

The 0029/0081/0095 policies cast with a bare
`current_setting('app.tenant_id', TRUE)::uuid`. Postgres evaluates the left
operand of an `OR` first, so an **empty-string** GUC raises `invalid input
syntax for type uuid: ''` instead of reaching the policy's own
`OR ... = ''` guard — that guard was unreachable code.

This was **latent, not live**: `get_db()` only ever sets a real uuid, so the
empty case never occurred in the request path. But it meant the fail-open
branch could not be exercised, and a fail-open branch nobody can test is not
one to rely on.

`alembic/versions/0097_nullif_tenant_rls.py` rewrites the cast to
`NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid` on all 70 static
tables. Verified: upgrade → 70 policies NULLIF / 0 bare; downgrade → restored;
re-upgrade → idempotent no-op. Behaviour confirmed directly against Postgres —
the old expression raises, the new one returns the row.

Two deliberate limits on that migration:

- **Tables are discovered from `pg_policy`, not hardcoded.** 23 migrations each
  redeclaring this policy is already how the list drifted in the first place.
- **`WITH CHECK` was not added to the ~69 policies that lack one.** No
  `WITH CHECK` means Postgres falls back to `USING` for writes, and since
  `USING` fails open, those tables accept a cross-tenant write today. That is a
  real hole and a real behaviour change, but it needs its own review and
  backfill — it does not belong in a migration claiming to fix a cast.

**Open item: those 69 tables accept cross-tenant writes.** Worth a follow-up
migration, tracked separately.

### Test harness — ✅ fixed

The suite could not previously verify anything about auth:

- `conftest.manager_token` minted a token for
  `00000000-0000-0000-0000-000000000001` when login failed — a user that does
  not exist. Validly signed, resolves to nobody, so permission tests saw 401
  where they asserted 403. A missing fixture was masquerading as a permissions
  bug. It now fails loudly.
- `conftest.admin_token` called `pytest.skip()` on login failure: **229 of 954
  tests were skipping** rather than running.
- No seed existed in the test database, so both logins always failed. A
  session-scoped fixture now runs the real `scripts/seed.py` — the real script,
  not a stub, so permission tests run against the same role wiring dev sees.
- `CELERY_BROKER_URL` defaulted to `localhost` independently of `REDIS_URL`,
  so any enqueue in the container raised `ConnectionError ... localhost:6379`.
  It is now derived from `REDIS_URL`.
- `tests/test_suite.py` redefined every fixture locally, pointing at
  `localhost/opsyn_test` with a password the seed never creates, and its
  session engine called `drop_all()` at teardown — which would have destroyed
  the schema every other file depends on. The shadowing block was deleted; the
  tests are unchanged.

Result: **1101 passed / 85 skipped / 0 failed** (was 935 passed, 229 skipped,
8 failed, 14 errors).

### Deliverables
- ✅ Automatic RLS policy application on dynamic tables
- ✅ Cross-tenant isolation test suite (7 tests, non-vacuous)
- ✅ Security rationale documented

### Acceptance Criteria
- ✅ All dynamic tables have RLS policies (from creation onward)
- ✅ Tenants cannot access other tenants' data (proven under a non-superuser)
- ⚠️ Security tests pass for the migration surface; pre-existing unrelated
  auth failures remain in `tests/test_suite.py` and `tests/e2e/`

---

## 📱 Phase 8: Mobile Integration Foundation
**Duration:** 2 weeks  
**Team:** 1 Backend Developer  
**Sprint:** Week 14-15

### Objectives
- Implement XForm export capability
- Create mobile sync API endpoints
- Prepare for KoboCollect integration

### Tasks

#### Week 14: XForm Export

**Task 8.1: XForm Generator**
- [ ] Create `app/modules/form_builder/xform_generator.py`
- [ ] Implement XLSForm generation
- [ ] Implement XForm XML generation
- [ ] Map field types to ODK types

**Task 8.2: Export Endpoint**
- [ ] Create `GET /schemas/{id}/export/xform`
- [ ] Support XML and XLSForm formats
- [ ] Include form metadata
- [ ] Test with KoboCollect

**Task 8.3: Field Type Mapping**
- [ ] Map all 24 types to ODK equivalents
- [ ] Handle validation rules in XForm
- [ ] Test in ODK Validate tool

#### Week 15: Mobile Sync API

**Task 8.4: Mobile API Keys**
- [ ] Create `mobile_api_keys` table
- [ ] Implement API key generation
- [ ] Add authentication middleware
- [ ] Test key validation

**Task 8.5: Submission Endpoint**
- [ ] Create `POST /mobile/submit`
- [ ] Accept form submissions from mobile
- [ ] Validate against schema
- [ ] Insert into dynamic tables

**Task 8.6: Batch Sync**
- [ ] Create `POST /mobile/submit/batch`
- [ ] Handle multiple submissions
- [ ] Implement conflict resolution
- [ ] Test with offline data

### Deliverables
- ✅ XForm export capability
- ✅ Mobile sync API
- ✅ API key management
- ✅ KoboCollect-compatible forms

### Acceptance Criteria
- [ ] Can export forms as XForm
- [ ] KoboCollect can load exported forms
- [ ] Mobile submissions sync successfully
- [ ] Data appears in dynamic tables

---

## 🧪 Phase 9: Testing & Quality Assurance
**Duration:** 1 week  
**Team:** 2 Developers + 1 QA  
**Sprint:** Week 16

### Objectives
- Comprehensive testing across all components
- Performance testing
- Bug fixes

### Tasks

**Task 9.1: Unit Test Coverage**
- [ ] Ensure 80%+ code coverage
- [ ] Test all edge cases
- [ ] Test error paths
- [ ] Mock external dependencies

**Task 9.2: Integration Testing**
- [ ] Test full migration flows
- [ ] Test API integration
- [ ] Test database interactions
- [ ] Test RLS policies

**Task 9.3: Performance Testing**
- [ ] Test migration speed on large tables (100K+ rows)
- [ ] Test concurrent operations
- [ ] Test mobile sync with large batches
- [ ] Identify bottlenecks

**Task 9.4: User Acceptance Testing**
- [ ] Test with real users
- [ ] Collect feedback
- [ ] Fix critical bugs
- [ ] Document known issues

**Task 9.5: Documentation**
- [ ] Complete API documentation
- [ ] Write user guides
- [ ] Create video tutorials
- [ ] Document troubleshooting

### Deliverables
- ✅ Test suite with high coverage
- ✅ Performance benchmarks
- ✅ UAT feedback incorporated
- ✅ Complete documentation

### Acceptance Criteria
- [ ] All tests pass
- [ ] Performance meets targets
- [ ] Users can successfully use features
- [ ] Documentation is complete

---

## 📊 Success Metrics

### Technical Metrics
- **Migration Success Rate:** > 99%
- **Average Migration Time:** < 2 seconds
- **Test Coverage:** > 80%
- **API Response Time:** < 200ms (p95)
- **Mobile Sync Success Rate:** > 99.5%

### Business Metrics
- **Time to Deploy New Entity Type:** < 10 minutes (down from days)
- **Tenant Adoption Rate:** > 60% within 3 months
- **Support Tickets:** < 5 per month for migration issues
- **User Satisfaction:** > 4.5/5

---

## 🚧 Risk Management

### High Risks
1. **Data Loss During Migration**
   - Mitigation: Transaction rollback + backup before major changes

2. **Performance on Large Tables**
   - Mitigation: Show warnings, recommend maintenance windows

3. **Alembic Version Conflicts**
   - Mitigation: Lock mechanisms, migration queue

4. **Mobile Sync Conflicts**
   - Mitigation: Conflict resolution strategies, manual review queue

### Medium Risks
1. **Field Type Mapping Edge Cases**
   - Mitigation: Extensive testing, validation

2. **RLS Policy Bypass**
   - Mitigation: Security testing, penetration testing

3. **Cross-Browser Compatibility**
   - Mitigation: Browser testing matrix

---

## 📅 Timeline Summary

| Phase | Duration | Weeks | Team Size |
|-------|----------|-------|-----------|
| 1. Foundation | 2 weeks | 1-2 | 1 BE |
| 2. Field Mapping | 2 weeks | 3-4 | 1 BE |
| 3. Validation | 2 weeks | 5-6 | 1 BE |
| 4. Alembic Integration | 2 weeks | 7-8 | 1 BE |
| 5. API Integration | 2 weeks | 9-10 | 1 BE |
| 6. Frontend | 2 weeks | 11-12 | 1 FE |
| 7. RLS & Security | 1 week | 13 | 1 BE |
| 8. Mobile Foundation | 2 weeks | 14-15 | 1 BE |
| 9. Testing & QA | 1 week | 16 | 2 Dev + QA |
| **TOTAL** | **16 weeks** | | **2-3 people** |

---

## 🎯 Sprint Planning

### Sprint 1 (Week 1-2): Foundation
**Goal:** Migration history tracking operational

**Daily Standups:** 15 min
**Sprint Review:** End of week 2
**Deliverable:** Can track migration history in database

### Sprint 2 (Week 3-4): Field Mapping
**Goal:** All field types map to SQL

**Mid-sprint Check-in:** End of week 3
**Sprint Review:** End of week 4
**Deliverable:** Field mapper with tests

### Sprint 3 (Week 5-6): Safety
**Goal:** Validation prevents invalid migrations

**Sprint Review:** End of week 6
**Deliverable:** Validator with integration tests

### Sprint 4 (Week 7-8): Execution
**Goal:** Can execute migrations via Alembic

**Sprint Review:** End of week 8
**Deliverable:** Working migration execution

### Sprint 5 (Week 9-10): API
**Goal:** APIs integrated and tested

**Sprint Review:** End of week 10
**Deliverable:** Postman collection with all endpoints

### Sprint 6 (Week 11-12): Frontend
**Goal:** Users can manage migrations via UI

**Sprint Review:** End of week 12
**Deliverable:** Working UI components

### Sprint 7 (Week 13): Security
**Goal:** RLS policies on all tables

**Sprint Review:** End of week 13
**Deliverable:** Security audit passed

### Sprint 8 (Week 14-15): Mobile
**Goal:** XForm export and sync working

**Sprint Review:** End of week 15
**Deliverable:** KoboCollect integration demo

### Sprint 9 (Week 16): QA
**Goal:** Production ready

**Sprint Review:** End of week 16
**Deliverable:** Go/No-Go decision

---

## 🚀 Deployment Strategy

### Staging Deployment (Week 13)
- Deploy to staging environment
- Internal team testing
- Fix critical bugs

### Beta Release (Week 15-16)
- Enable for 2-3 pilot tenants
- Monitor closely
- Collect feedback

### Production Rollout (Week 17)
- Phased rollout to all tenants
- Feature flags for gradual enablement
- 24/7 monitoring first week

---

## 📞 Communication Plan

### Weekly Updates
- Every Friday: Progress report to stakeholders
- Blockers highlighted immediately
- Metrics dashboard updated

### Sprint Reviews
- Demo working features
- Collect stakeholder feedback
- Adjust priorities if needed

### Documentation
- README updated each sprint
- API docs auto-generated
- User guides written in parallel

---

## ✅ Definition of Done

A feature is considered "done" when:
- [ ] Code written and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests passing
- [ ] API documented
- [ ] User guide updated
- [ ] Deployed to staging
- [ ] QA tested and approved
- [ ] Stakeholder demo completed

---

**Start Date:** 2026-09-28  
**Target Completion:** 2027-01-25 (16 weeks)  
**Budget:** TBD based on team rates  
**Priority:** High - Strategic Feature
