# OpSyn Module Restructuring — Phased Implementation Plan

**Document Version:** 1.0  
**Date:** 2026-10-09  
**Status:** Implementation Ready  
**Reference:** Module_Restructuring_Plan.md

---

## Overview

This document breaks down the OpSyn module restructuring into small, focused phases. Each phase has **one primary task** that can be completed, tested, and deployed independently.

**Total Phases:** 42  
**Estimated Timeline:** 16-20 weeks (depending on team size and parallel work)

---

## Phase Grouping

| Group | Phases | Focus | Duration |
|-------|--------|-------|----------|
| **Foundation** | 1-5 | Database schema, base services | 2 weeks |
| **Tasks Unification** | 6-15 | Unified task interface and UI | 3 weeks |
| **Engineering: Infrastructure** | 16-20 | Existing infrastructure cleanup | 1 week |
| **Engineering: Auto Design** | 21-25 | FTTx Designer integration | 2 weeks |
| **Engineering: Manual Design** | 26-32 | Manual design tools and validation | 3 weeks |
| **Engineering: BOQ** | 33-35 | Bill of Quantities management | 1.5 weeks |
| **Engineering: Deployment** | 36-39 | Deployment tracking and as-built | 2 weeks |
| **Integration & Polish** | 40-42 | End-to-end testing and refinement | 1.5 weeks |

---

## Foundation Phases (Weeks 1-2)

### Phase 1: Database Schema — Design & BOQ Tables
**Task:** Create new database tables for project designs, BOQ, products, and deployment tracking

**Deliverables:**
- Migration: `0092_engineering_design_schema.sql`
  - Enhance existing `designs` table with new fields
  - Create `boq_items` table
  - Create `products` catalog table
  - Add indexes for performance

**Acceptance Criteria:**
- Migration runs cleanly on dev database
- All tables have proper RLS policies
- Foreign key relationships validated
- Indexes created for common queries

**Files Changed:**
- `backend/alembic/versions/0092_engineering_design_schema.py`

**Estimated Time:** 2 days

---

### Phase 2: Database Schema — Deployment & As-Built Tables
**Task:** Create deployment tracking and as-built documentation tables

**Deliverables:**
- Migration: `0093_engineering_deployment_schema.sql`
  - Create `project_deployment` table
  - Create `deployment_milestones` table
  - Create `project_as_built` table
  - Create `as_built_items` table
  - Create `as_built_variance_log` table

**Acceptance Criteria:**
- Migration runs cleanly
- RLS policies applied
- Foreign keys to projects validated
- Geometry columns for as-built items created

**Files Changed:**
- `backend/alembic/versions/0093_engineering_deployment_schema.py`

**Estimated Time:** 2 days

---

### Phase 3: Seed Data — Product Catalog
**Task:** Create initial product catalog for BOQ non-design items

**Deliverables:**
- Migration: `0094_seed_product_catalog.sql`
- Product categories: Labor, Consumables, Equipment Rental, Permits, Services
- ~50 common products seeded with standard costs

**Acceptance Criteria:**
- Products inserted for all tenants
- Categories properly assigned
- Costs are reasonable defaults
- Products marked as active

**Files Changed:**
- `backend/alembic/versions/0094_seed_product_catalog.py`

**Estimated Time:** 1 day

---

### Phase 4: Backend Models — Engineering Module
**Task:** Create SQLAlchemy ORM models for new engineering tables

**Deliverables:**
- New file: `backend/app/modules/engineering/models.py`
- Models for: BOQItem, Product, ProjectDeployment, DeploymentMilestone, ProjectAsBuilt, AsBuiltItem

**Acceptance Criteria:**
- All models inherit from Base
- Relationships properly defined
- Type hints complete
- `__allow_unmapped__ = True` set

**Files Changed:**
- `backend/app/modules/engineering/models.py` (new)
- `backend/app/modules/engineering/__init__.py` (new)

**Estimated Time:** 2 days

---

### Phase 5: Backend Schemas — Pydantic Validation
**Task:** Create Pydantic schemas for API request/response validation

**Deliverables:**
- New file: `backend/app/modules/engineering/schemas.py`
- Schemas for: BOQCreate, BOQResponse, ProductCreate, DeploymentCreate, AsBuiltCreate

**Acceptance Criteria:**
- All required fields validated
- Optional fields properly typed
- Response schemas include computed fields
- Enum types for status fields

**Files Changed:**
- `backend/app/modules/engineering/schemas.py` (new)

**Estimated Time:** 2 days

---

## Tasks Unification Phases (Weeks 3-5)

### Phase 6: Backend — Task Scope Indexing
**Task:** Add database indexes for task scope queries

**Deliverables:**
- Migration: `0095_task_scope_indexes.sql`
- Indexes on `tasks(task_scope, status, department_id)`
- Indexes on `tasks(task_scope, assignee_user_id, status)`

**Acceptance Criteria:**
- Indexes created without errors
- Query performance improved (test with EXPLAIN)

**Files Changed:**
- `backend/alembic/versions/0095_task_scope_indexes.py`

**Estimated Time:** 0.5 days

---

### Phase 7: Backend API — Unified Task List Endpoint
**Task:** Update task list endpoint to support scope filtering

**Deliverables:**
- Update `GET /api/v1/tasks` to accept `scope` query parameter
- Values: `internal`, `external`, `all` (default)
- Filter logic in service layer

**Acceptance Criteria:**
- Endpoint returns correct tasks for each scope
- Existing API consumers still work (backward compatible)
- Scope filter combines with other filters (status, department)

**Files Changed:**
- `backend/app/modules/tasks/router.py`
- `backend/app/modules/tasks/service.py`

**Estimated Time:** 1 day

---

### Phase 8: Backend API — Unified Task Board Endpoint
**Task:** Update Kanban board endpoint to support scope filtering

**Deliverables:**
- Update `GET /api/v1/tasks/board` to accept `scope` query parameter
- Group tasks by scope when scope=all

**Acceptance Criteria:**
- Board returns correct grouped tasks
- Pipeline stages apply to both scopes
- Performance acceptable with 1000+ tasks

**Files Changed:**
- `backend/app/modules/tasks/router.py`
- `backend/app/modules/tasks/service.py`

**Estimated Time:** 1 day

---

### Phase 9: Backend API — Task Creation with Scope
**Task:** Ensure task creation enforces scope field

**Deliverables:**
- Update `POST /api/v1/tasks` to require `task_scope` field
- Validate scope enum: `internal` | `external`
- Default to `internal` for backward compatibility

**Acceptance Criteria:**
- Invalid scope values rejected with 422
- Scope properly stored in database
- Audit logs capture scope

**Files Changed:**
- `backend/app/modules/tasks/router.py`
- `backend/app/modules/tasks/schemas.py`

**Estimated Time:** 0.5 days

---

### Phase 10: Frontend API Client — Task Scope Support
**Task:** Update frontend API client to support scope filtering

**Deliverables:**
- Update `frontend/src/api/tasks.api.ts`
- Add `scope` parameter to list and board functions
- TypeScript types updated

**Acceptance Criteria:**
- API client properly encodes scope parameter
- Types match backend contract
- No breaking changes to existing calls

**Files Changed:**
- `frontend/src/api/tasks.api.ts`
- `frontend/src/types/task.types.ts`

**Estimated Time:** 0.5 days

---

### Phase 11: Frontend Components — Scope Badge
**Task:** Create visual scope indicator component

**Deliverables:**
- New component: `frontend/src/components/tasks/ScopeBadge.tsx`
- Blue badge for Internal, Green badge for External
- Icons for each scope type

**Acceptance Criteria:**
- Badge displays correctly on task cards
- Colors match design system
- Accessible (proper aria labels)

**Files Changed:**
- `frontend/src/components/tasks/ScopeBadge.tsx` (new)

**Estimated Time:** 0.5 days

---

### Phase 12: Frontend Components — Task Card Updates
**Task:** Add scope badge to existing task card component

**Deliverables:**
- Update `TaskCard.tsx` to display scope badge
- Show department routing history for external tasks

**Acceptance Criteria:**
- Badge appears on all task cards
- External tasks show routing history
- Internal tasks don't show routing info

**Files Changed:**
- `frontend/src/pages/tasks/components/TaskCard.tsx`

**Estimated Time:** 1 day

---

### Phase 13: Frontend UI — Unified Task List Filters
**Task:** Add scope filter tabs to task list page

**Deliverables:**
- Update `TasksPage.tsx` with tab controls
- Tabs: All Tasks | Internal | External
- Filter state managed in URL query params

**Acceptance Criteria:**
- Tabs switch between scopes smoothly
- URL reflects current filter
- Tab counts show task numbers per scope

**Files Changed:**
- `frontend/src/pages/tasks/TasksPage.tsx`
- `frontend/src/pages/tasks/components/TaskFilters.tsx`

**Estimated Time:** 1 day

---

### Phase 14: Frontend UI — Unified Kanban Board
**Task:** Update Kanban board to support scope filtering

**Deliverables:**
- Update `KanbanBoard.tsx` with scope filter
- Visual distinction for mixed-scope columns
- Scope badge on each card

**Acceptance Criteria:**
- Board filters by scope correctly
- Cards display scope badge
- Drag-and-drop still works

**Files Changed:**
- `frontend/src/pages/tasks/components/KanbanBoard.tsx`
- `frontend/src/pages/tasks/components/KanbanColumn.tsx`

**Estimated Time:** 1.5 days

---

### Phase 15: Frontend UI — Task Creation Modal Update
**Task:** Add scope selector to task creation modal

**Deliverables:**
- Update `NewTaskModal.tsx` with scope radio buttons
- Show/hide external-specific fields conditionally
- Default to internal scope

**Acceptance Criteria:**
- Scope selector appears in modal
- External scope enables department routing fields
- Internal scope hides routing fields
- Form validation enforces scope rules

**Files Changed:**
- `frontend/src/pages/tasks/components/NewTaskModal.tsx`

**Estimated Time:** 1 day

---

## Engineering: Infrastructure Phases (Week 6)

### Phase 16: Navigation — Engineering Module Structure
**Task:** Create top-level Engineering navigation with Infrastructure and Projects subsections

**Deliverables:**
- Update `frontend/src/layouts/navigation.ts`
- Two main items: Infrastructure, Projects
- Projects has nested items: Design, BOQ, Deployment

**Acceptance Criteria:**
- Navigation shows correctly in sidebar
- Permissions check for visibility
- Active state highlights correctly

**Files Changed:**
- `frontend/src/layouts/navigation.ts`
- `frontend/src/App.tsx` (route additions)

**Estimated Time:** 1 day

---

### Phase 17: Frontend Routes — Engineering Module
**Task:** Set up routing for Engineering module pages

**Deliverables:**
- Routes for Engineering > Infrastructure (existing)
- Routes for Engineering > Projects subsections
- Lazy loading for code splitting

**Acceptance Criteria:**
- All routes accessible
- Lazy loading works
- 404 handling for invalid routes

**Files Changed:**
- `frontend/src/App.tsx`

**Estimated Time:** 0.5 days

---

### Phase 18: Frontend UI — Infrastructure Section Landing
**Task:** Create Infrastructure section landing page

**Deliverables:**
- New page: `frontend/src/pages/engineering/InfrastructureLanding.tsx`
- Quick links to Map, Sites, Uploads, Audit
- Recent activity summary

**Acceptance Criteria:**
- Page loads correctly
- Links navigate to correct pages
- Summary shows real data

**Files Changed:**
- `frontend/src/pages/engineering/InfrastructureLanding.tsx` (new)

**Estimated Time:** 1 day

---

### Phase 19: Frontend UI — Projects Section Landing
**Task:** Create Projects section landing page

**Deliverables:**
- New page: `frontend/src/pages/engineering/ProjectsLanding.tsx`
- Quick links to Design, BOQ, Deployment
- Project statistics

**Acceptance Criteria:**
- Page loads correctly
- Links navigate to correct sections
- Statistics display accurately

**Files Changed:**
- `frontend/src/pages/engineering/ProjectsLanding.tsx` (new)

**Estimated Time:** 1 day

---

### Phase 20: RBAC — Engineering Permissions
**Task:** Create and seed engineering module permissions

**Deliverables:**
- Migration: `0096_engineering_permissions.sql`
- Permissions:
  - `engineering.designs.view`
  - `engineering.designs.create`
  - `engineering.designs.edit`
  - `engineering.designs.approve`
  - `engineering.boq.view`
  - `engineering.boq.create`
  - `engineering.boq.approve`
  - `engineering.deployments.view`
  - `engineering.deployments.manage`
  - `engineering.as_built.create`
  - `engineering.as_built.verify`

**Acceptance Criteria:**
- All permissions seeded
- Default roles assigned appropriate permissions
- Permission checks work in backend

**Files Changed:**
- `backend/alembic/versions/0096_engineering_permissions.py`

**Estimated Time:** 1 day

---

## Engineering: Auto Design Phases (Weeks 7-8)

### Phase 21: Backend Service — Design Service Foundation
**Task:** Create design service layer for CRUD operations

**Deliverables:**
- New file: `backend/app/modules/engineering/design_service.py`
- Functions: create_design, get_design, list_designs, update_design, delete_design
- Integration with existing designs table

**Acceptance Criteria:**
- All CRUD operations work
- RLS properly enforced
- Transactions handle errors correctly

**Files Changed:**
- `backend/app/modules/engineering/design_service.py` (new)

**Estimated Time:** 2 days

---

### Phase 22: Backend API — Design CRUD Endpoints
**Task:** Create REST API endpoints for design management

**Deliverables:**
- New router: `backend/app/modules/engineering/design_router.py`
- Endpoints:
  - `GET /api/v1/engineering/designs`
  - `POST /api/v1/engineering/designs`
  - `GET /api/v1/engineering/designs/{id}`
  - `PUT /api/v1/engineering/designs/{id}`
  - `DELETE /api/v1/engineering/designs/{id}`

**Acceptance Criteria:**
- All endpoints return correct status codes
- Validation errors are clear
- Permissions enforced

**Files Changed:**
- `backend/app/modules/engineering/design_router.py` (new)
- `backend/main.py` (register router)

**Estimated Time:** 2 days

---

### Phase 23: Backend Integration — Link FTTx Designer to Design Container
**Task:** Update FTTx Designer to create design versions when runs complete

**Deliverables:**
- Update `backend/app/modules/design/auto_design.py`
- Create `design_version` record when FTTx run succeeds
- Link `fttx_design_runs.design_version_id`

**Acceptance Criteria:**
- Completed runs create design versions
- Version number increments correctly
- Run output linked to version

**Files Changed:**
- `backend/app/modules/design/auto_design.py`
- `backend/app/modules/design/service.py`

**Estimated Time:** 1.5 days

---

### Phase 24: Frontend API Client — Design API
**Task:** Create frontend API client for design operations

**Deliverables:**
- New file: `frontend/src/api/design.api.ts`
- Functions for all design CRUD operations
- TypeScript types

**Acceptance Criteria:**
- API client works for all operations
- Error handling implemented
- Types match backend schemas

**Files Changed:**
- `frontend/src/api/design.api.ts` (new)
- `frontend/src/types/design.types.ts` (new)

**Estimated Time:** 1 day

---

### Phase 25: Frontend UI — Design List Page
**Task:** Create page to list all designs

**Deliverables:**
- New page: `frontend/src/pages/engineering/DesignListPage.tsx`
- Table with filters (status, type, date)
- Actions: View, Edit, Delete, Run Auto Design

**Acceptance Criteria:**
- Page displays designs correctly
- Filters work
- Actions trigger correct operations
- Pagination implemented

**Files Changed:**
- `frontend/src/pages/engineering/DesignListPage.tsx` (new)

**Estimated Time:** 2 days

---

## Engineering: Manual Design Phases (Weeks 9-11)

### Phase 26: Frontend Components — Drawing Toolbar
**Task:** Create CAD-style drawing toolbar component

**Deliverables:**
- New component: `frontend/src/components/design/DrawingToolbar.tsx`
- Tools: Select, Point, Line, Polygon, Snap, Measure, Edit
- Tool state management

**Acceptance Criteria:**
- Toolbar displays correctly
- Tool selection works
- Active tool highlighted
- Icons clear and accessible

**Files Changed:**
- `frontend/src/components/design/DrawingToolbar.tsx` (new)

**Estimated Time:** 2 days

---

### Phase 27: Frontend Components — Asset Palette
**Task:** Create equipment catalog palette for drag-and-drop

**Deliverables:**
- New component: `frontend/src/components/design/AssetPalette.tsx`
- Categories: OLTs, FDTs, FATs, Poles, Cabinets, Closures
- Search and filter
- Drag to map functionality

**Acceptance Criteria:**
- Palette displays equipment from catalog
- Search filters assets
- Drag-and-drop to map works
- Asset properties loaded on drop

**Files Changed:**
- `frontend/src/components/design/AssetPalette.tsx` (new)

**Estimated Time:** 2 days

---

### Phase 28: Frontend Components — Properties Panel
**Task:** Create panel to edit selected asset properties

**Deliverables:**
- New component: `frontend/src/components/design/PropertiesPanel.tsx`
- Form fields for asset attributes
- Real-time validation
- Save/Cancel buttons

**Acceptance Criteria:**
- Panel shows selected asset properties
- Fields are editable
- Validation runs on blur
- Changes saved to backend

**Files Changed:**
- `frontend/src/components/design/PropertiesPanel.tsx` (new)

**Estimated Time:** 2 days

---

### Phase 29: Frontend Map — MapLibre Drawing Integration
**Task:** Integrate MapLibre Draw for geometry editing

**Deliverables:**
- Install `@mapbox/mapbox-gl-draw`
- Configure drawing controls
- Handle draw events (create, update, delete)
- Snap to existing assets

**Acceptance Criteria:**
- Drawing tools work on map
- Geometries saved correctly
- Snap functionality works
- Undo/redo available

**Files Changed:**
- `frontend/src/components/design/ManualDesignMap.tsx` (new)
- `package.json` (add dependency)

**Estimated Time:** 3 days

---

### Phase 30: Frontend Map — Coordinate Input System
**Task:** Add precision coordinate input dialog

**Deliverables:**
- New component: `frontend/src/components/design/CoordinateInputDialog.tsx`
- Input formats: Lat/Long (decimal), UTM, DMS
- Distance and bearing calculator
- Validate coordinates

**Acceptance Criteria:**
- Dialog opens on keyboard shortcut
- All input formats work
- Coordinates place asset correctly
- Validation prevents invalid input

**Files Changed:**
- `frontend/src/components/design/CoordinateInputDialog.tsx` (new)

**Estimated Time:** 2 days

---

### Phase 31: Backend Service — Manual Design Validation
**Task:** Create validation service for manual designs

**Deliverables:**
- New file: `backend/app/modules/engineering/manual_validation.py`
- Checks:
  - Connectivity (all assets connected)
  - Distance constraints
  - Capacity constraints
  - Topology rules (no loops, valid cascade)

**Acceptance Criteria:**
- Validation runs on design
- Returns list of findings with severity
- Performance acceptable for 1000+ assets

**Files Changed:**
- `backend/app/modules/engineering/manual_validation.py` (new)

**Estimated Time:** 3 days

---

### Phase 32: Frontend UI — Manual Design Workspace
**Task:** Create complete manual design workspace page

**Deliverables:**
- New page: `frontend/src/pages/engineering/ManualDesignWorkspace.tsx`
- Integrate: Map, Toolbar, Palette, Properties Panel, Layer Panel
- Save/Load design state
- Real-time validation hints

**Acceptance Criteria:**
- All components work together
- Design state persists
- Validation runs automatically
- Performance acceptable

**Files Changed:**
- `frontend/src/pages/engineering/ManualDesignWorkspace.tsx` (new)

**Estimated Time:** 3 days

---

## Engineering: BOQ Phases (Weeks 12-13)

### Phase 33: Backend Service — BOQ Generation Service
**Task:** Create service to extract BOQ from designs

**Deliverables:**
- New file: `backend/app/modules/engineering/boq_service.py`
- Functions:
  - generate_boq_from_design (extracts all assets and cables)
  - calculate_quantities (rollup by item type)
  - apply_unit_costs (link to product catalog)
  - calculate_totals

**Acceptance Criteria:**
- BOQ generates correctly from designs
- Quantities accurate
- Costs calculated properly
- Performance acceptable

**Files Changed:**
- `backend/app/modules/engineering/boq_service.py` (new)

**Estimated Time:** 3 days

---

### Phase 34: Backend API — BOQ Management Endpoints
**Task:** Create REST API for BOQ operations

**Deliverables:**
- New router: `backend/app/modules/engineering/boq_router.py`
- Endpoints:
  - `POST /api/v1/engineering/boq` (create from design)
  - `GET /api/v1/engineering/boq/{id}`
  - `POST /api/v1/engineering/boq/{id}/items` (add product)
  - `PUT /api/v1/engineering/boq/{id}/items/{item_id}`
  - `DELETE /api/v1/engineering/boq/{id}/items/{item_id}`
  - `POST /api/v1/engineering/boq/{id}/approve`
  - `GET /api/v1/engineering/boq/{id}/export` (Excel/PDF)

**Acceptance Criteria:**
- All endpoints work correctly
- Approval workflow enforced
- Export generates valid files

**Files Changed:**
- `backend/app/modules/engineering/boq_router.py` (new)

**Estimated Time:** 2 days

---

### Phase 35: Frontend UI — BOQ Management Page
**Task:** Create BOQ editing and approval interface

**Deliverables:**
- New page: `frontend/src/pages/engineering/BOQPage.tsx`
- Sections:
  - Design Items (read-only, from design)
  - Products (editable, add/remove)
  - Cost Summary
- Actions: Add Product, Edit Quantity, Approve, Export

**Acceptance Criteria:**
- BOQ displays correctly
- Products can be added/edited
- Totals calculate automatically
- Export downloads file
- Approval workflow works

**Files Changed:**
- `frontend/src/pages/engineering/BOQPage.tsx` (new)
- `frontend/src/api/boq.api.ts` (new)

**Estimated Time:** 3 days

---

## Engineering: Deployment Phases (Weeks 14-15)

### Phase 36: Backend Service — Deployment Service
**Task:** Create service for deployment tracking

**Deliverables:**
- New file: `backend/app/modules/engineering/deployment_service.py`
- Functions:
  - create_deployment (from approved design+BOQ)
  - update_progress
  - manage_milestones
  - generate_deployment_tasks (link to task system)

**Acceptance Criteria:**
- Deployments created correctly
- Progress tracking works
- Milestones managed properly
- Tasks generated in task system

**Files Changed:**
- `backend/app/modules/engineering/deployment_service.py` (new)

**Estimated Time:** 2 days

---

### Phase 37: Backend API — Deployment Endpoints
**Task:** Create REST API for deployment operations

**Deliverables:**
- New router: `backend/app/modules/engineering/deployment_router.py`
- Endpoints:
  - `POST /api/v1/engineering/deployments` (initiate)
  - `GET /api/v1/engineering/deployments/proposed` (list ready)
  - `GET /api/v1/engineering/deployments/{id}`
  - `PUT /api/v1/engineering/deployments/{id}/progress`
  - `POST /api/v1/engineering/deployments/{id}/milestones`
  - `PUT /api/v1/engineering/deployments/{id}/milestones/{milestone_id}`

**Acceptance Criteria:**
- All endpoints work
- Progress updates persist
- Milestones ordered correctly

**Files Changed:**
- `backend/app/modules/engineering/deployment_router.py` (new)

**Estimated Time:** 2 days

---

### Phase 38: Backend Service — As-Built Service
**Task:** Create service for as-built documentation

**Deliverables:**
- New file: `backend/app/modules/engineering/as_built_service.py`
- Functions:
  - create_as_built_record (import from deployment)
  - document_variance (compare design vs actual)
  - upload_photos
  - update_infrastructure_database (promote to live network)

**Acceptance Criteria:**
- As-built records created
- Variance calculated correctly
- Photos stored and linked
- Infrastructure database updated

**Files Changed:**
- `backend/app/modules/engineering/as_built_service.py` (new)

**Estimated Time:** 3 days

---

### Phase 39: Frontend UI — Deployment Tracking Dashboard
**Task:** Create deployment tracking and as-built documentation interface

**Deliverables:**
- New pages:
  - `frontend/src/pages/engineering/DeploymentListPage.tsx`
  - `frontend/src/pages/engineering/DeploymentDetailPage.tsx`
  - `frontend/src/pages/engineering/AsBuiltFormPage.tsx`
- Features:
  - Proposed projects list
  - Deployment progress tracking
  - Milestone management
  - As-built documentation form
  - Photo upload
  - Variance reporting

**Acceptance Criteria:**
- Pages display correctly
- Progress updates work
- Milestones manageable
- As-built form validates
- Photos upload successfully

**Files Changed:**
- Multiple new pages (listed above)
- `frontend/src/api/deployment.api.ts` (new)

**Estimated Time:** 4 days

---

## Integration & Polish Phases (Weeks 16-17)

### Phase 40: Testing — End-to-End Workflow
**Task:** Test complete workflow from design to as-built

**Deliverables:**
- E2E test suite:
  1. Create project
  2. Create auto design (FTTx run)
  3. Review and approve design
  4. Generate BOQ
  5. Add products to BOQ
  6. Approve BOQ
  7. Initiate deployment
  8. Track progress
  9. Document as-built
  10. Verify infrastructure database updated

**Acceptance Criteria:**
- All steps complete without errors
- Data flows correctly between modules
- No data loss or corruption
- Performance acceptable

**Files Changed:**
- `backend/tests/integration/test_engineering_workflow.py` (new)
- `frontend/cypress/e2e/engineering_workflow.cy.ts` (new)

**Estimated Time:** 3 days

---

### Phase 41: Documentation — User Guide
**Task:** Create user documentation for Engineering module

**Deliverables:**
- User guides:
  - "Creating Auto Designs"
  - "Manual Design Tools"
  - "BOQ Management"
  - "Deployment Tracking"
  - "As-Built Documentation"
- Screenshots and walkthroughs
- Video tutorials (optional)

**Acceptance Criteria:**
- All features documented
- Screenshots clear and current
- Step-by-step instructions provided
- Troubleshooting section included

**Files Changed:**
- `docs/user-guides/engineering-auto-design.md` (new)
- `docs/user-guides/engineering-manual-design.md` (new)
- `docs/user-guides/engineering-boq.md` (new)
- `docs/user-guides/engineering-deployment.md` (new)

**Estimated Time:** 3 days

---

### Phase 42: Migration — Data Migration from Old Structure
**Task:** Migrate existing project data to new structure (if needed)

**Deliverables:**
- Migration script: `scripts/migrate_projects_to_engineering.py`
- Map old projects table to new design/deployment tables
- Preserve audit history
- Validate data integrity

**Acceptance Criteria:**
- All existing projects migrated
- No data loss
- Relationships preserved
- Audit trail intact
- Rollback plan tested

**Files Changed:**
- `scripts/migrate_projects_to_engineering.py` (new)
- `backend/alembic/versions/0097_data_migration.py` (new)

**Estimated Time:** 2 days

---

## Phase Dependencies

```
Foundation (1-5) → All other phases depend on this

Tasks Unification (6-15)
├─ Phase 6-9: Backend changes
├─ Phase 10-11: API client and components
└─ Phase 12-15: Frontend UI (depends on 10-11)

Engineering: Infrastructure (16-20)
├─ Depends on: Phase 1-5
└─ Phase 16-17: Navigation structure required for all other phases

Engineering: Auto Design (21-25)
├─ Depends on: Phase 1-5, 16-20
├─ Phase 21-22: Backend foundation
└─ Phase 23-25: Integration and UI

Engineering: Manual Design (26-32)
├─ Depends on: Phase 1-5, 16-20, 21-24
├─ Phase 26-28: UI components
├─ Phase 29-30: Map integration
├─ Phase 31: Validation
└─ Phase 32: Workspace (depends on 26-31)

Engineering: BOQ (33-35)
├─ Depends on: Phase 1-5, 16-25
└─ Can partially parallel with Phase 26-32

Engineering: Deployment (36-39)
├─ Depends on: Phase 1-5, 16-35
└─ Sequential (each builds on previous)

Integration & Polish (40-42)
├─ Depends on: All previous phases
└─ Sequential
```

---

## Parallel Work Opportunities

With a team of 2-3 developers:

**Week 1-2 (Foundation):**
- Developer 1: Phase 1-2 (Database schemas)
- Developer 2: Phase 3-5 (Seed data, models, schemas)

**Week 3-5 (Tasks Unification):**
- Developer 1: Phase 6-9 (Backend API)
- Developer 2: Phase 10-15 (Frontend implementation)

**Week 6 (Engineering Infrastructure):**
- All developers: Phase 16-20 (Small tasks, can be distributed)

**Week 7-8 (Auto Design):**
- Developer 1: Phase 21-23 (Backend services)
- Developer 2: Phase 24-25 (Frontend API and UI)

**Week 9-11 (Manual Design):**
- Developer 1: Phase 26-28, 31 (UI components and validation)
- Developer 2: Phase 29-30, 32 (Map integration and workspace)

**Week 12-13 (BOQ):**
- Developer 1: Phase 33-34 (Backend)
- Developer 2: Phase 35 (Frontend)

**Week 14-15 (Deployment):**
- Developer 1: Phase 36-38 (Backend services)
- Developer 2: Phase 39 (Frontend UI)

**Week 16-17 (Integration & Polish):**
- Developer 1: Phase 40 (Testing)
- Developer 2: Phase 41 (Documentation)
- All developers: Phase 42 (Migration)

---

## Risk Mitigation

### High-Risk Phases

**Phase 23:** FTTx Designer integration
- **Risk:** Breaking existing FTTx Designer functionality
- **Mitigation:** Extensive testing with existing designs, rollback plan

**Phase 29:** MapLibre Draw integration
- **Risk:** Performance issues with large designs, browser compatibility
- **Mitigation:** Performance testing with 1000+ assets, progressive enhancement

**Phase 31:** Manual design validation
- **Risk:** Complex validation logic, false positives/negatives
- **Mitigation:** Extensive unit tests, phased rollout with validation warnings before errors

**Phase 42:** Data migration
- **Risk:** Data loss, corruption, downtime
- **Mitigation:** Dry-run on staging, comprehensive rollback plan, backup before migration

### Checkpoints

**Checkpoint 1 (After Phase 5):** Foundation Complete
- All database tables created
- Models and schemas working
- Ready for feature development

**Checkpoint 2 (After Phase 15):** Tasks Unification Complete
- Unified task interface working
- User acceptance testing
- Deploy to staging

**Checkpoint 3 (After Phase 25):** Auto Design Integration Complete
- FTTx Designer linked to new structure
- Existing functionality preserved
- Deploy to production (phased)

**Checkpoint 4 (After Phase 32):** Manual Design Complete
- Full manual design workflow working
- Validation accurate
- User training completed

**Checkpoint 5 (After Phase 39):** All Features Complete
- End-to-end workflow tested
- Ready for final integration phase

**Checkpoint 6 (After Phase 42):** Production Ready
- All data migrated
- Documentation complete
- Go-live approved

---

## Success Metrics

### Per Phase
- ✅ All acceptance criteria met
- ✅ Code reviewed and approved
- ✅ Tests passing (unit, integration)
- ✅ Deployed to dev environment
- ✅ Demo to stakeholders

### Overall Project
- ✅ All 42 phases completed
- ✅ Zero data loss during migration
- ✅ Performance targets met (page load < 2s, API response < 500ms)
- ✅ User adoption: >80% of users using new interface within 2 weeks
- ✅ Zero critical bugs in production first month

---

## Notes

- Each phase is designed to be **independently deployable** (where possible)
- Phases can be **re-ordered** within their group if dependencies allow
- **Feature flags** recommended for frontend phases to enable gradual rollout
- **Database migrations** should be backwards compatible during transition period
- **API versioning** not required if backward compatibility maintained
- **User training** should happen after each major group completes (Tasks, Auto Design, Manual Design)

---

**Document Control:**
- Version: 1.0
- Last Updated: 2026-10-09
- Next Review: After each checkpoint
- Distribution: Engineering Team, Product Owner, QA Team
