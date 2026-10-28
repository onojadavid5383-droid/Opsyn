# Opsyn Project Capability Study

**Assessment date:** 2026-08-18  
**Repository:** `Wiseslim/Opsyn`  
**Branch:** `main`  
**Snapshot:** `d6348f8` (`feat: update Opsyn workflow and platform modules`)  
**Assessment method:** Source inspection, route and component inventory, migration review, test/configuration review, and targeted static validation. This document describes what the codebase supports; it is not a claim that every external integration or production deployment has been exercised.

## 1. Executive Summary

Opsyn is a multi-tenant operational intelligence platform for FTTx/ISP operations. The current codebase includes a working-shaped full-stack system with:

- Tenant registration, authentication, activation, password recovery, JWT sessions, and tenant isolation.
- Role-based access control, permissions, departments, regions, teams, staff management, and organisation settings.
- A task workflow engine covering internal/external work, assignment, department routing, approvals, audit history, comments, dependencies, archiving, and soft deletion.
- Project management with configurable pipeline templates, stages, approvals, push-back, progress, timelines, and automatic project creation from external tasks.
- FTTx infrastructure records, GIS/map data, network capacity, ports, cabinets, OLTs, splitter boxes, fibre routes, uploads, deletion workflows, and audit history.
- Outage management, SmartOLT polling/integration, SLA checks, linked tasks, and customer notification workflows.
- Customer records, dynamic customer fields, customer forms, payment requests and confirmations.
- Two form systems: a legacy context-form system and a newer versioned Form Builder.
- Notifications, reports, activity/audit views, onboarding, shifts, swap requests, webhooks, and Celery background processing.
- A React/Vite frontend exposing the major operational workflows through routed pages.

The project is substantial and beyond a prototype. However, several conclusions require qualification:

1. Source presence does not prove production readiness.
2. Database, Redis, Celery, external messaging, SmartOLT, and OAuth/integration behavior still require environment-backed validation.
3. Some paths contain explicit stubs, fallback behavior, TODOs, or broad exception handling.
4. Several navigation items are intentionally disabled or marked as beta/coming soon.
5. The older `IMPLEMENTATION_REPORT.md` is a historical Phase 5 report, not a complete description of this snapshot.

## 2. Evidence Inventory

The current repository contains:

| Area | Evidence found |
|---|---:|
| Backend router modules | 22 |
| Alembic migration files | 66, with the chain extending through `0083` |
| Backend test files named `test_*.py` | 18 |
| Frontend test/spec files found under `src` | 4 |
| Runtime orchestration | PostgreSQL/PostGIS, Redis, FastAPI, Celery worker, Celery Beat, React frontend |

Primary evidence locations:

- Backend application: `backend/app/`
- Backend entry point: `backend/main.py`
- Database migrations: `backend/alembic/versions/`
- Backend tests: `backend/tests/`
- Frontend routes: `frontend/src/App.tsx`
- Frontend API clients: `frontend/src/api/`
- Docker development stack: `docker-compose.yml`
- Production stack: `docker-compose.prod.yml`
- Historical Phase 5 report: `IMPLEMENTATION_REPORT.md`
- Development history: `DEVELOPMENT_LOG.md`

## 3. Capabilities Implemented in the Current Snapshot

### 3.1 Authentication and tenancy

The authentication and tenant foundation supports:

- Tenant registration through the auth API.
- Login and JWT access-token authentication.
- Refresh-token handling and logout.
- Account activation flows.
- Password reset flows.
- Authenticated tenant context.
- Tenant-aware database queries and PostgreSQL row-level-security migrations.
- Automatic tenant setup/provisioning through the tenant setup service.

Tenant provisioning is designed to create baseline organisation data such as default roles, departments, permissions, grants, a region, and legacy forms.

Relevant areas:

- `backend/app/modules/auth/`
- `backend/app/modules/tenants/`
- `backend/app/dependencies/`
- `backend/alembic/versions/`

### 3.2 Staff, organisation, roles, and permissions

The platform supports administration of the organisation itself:

- Staff creation, listing, editing, and status changes.
- Department, team, and region management.
- Role creation and role assignment.
- Permission definitions and feature grants.
- User scope management.
- Organisation settings and branding.
- Staff performance views and related reporting.
- Department-level ownership used by task routing and project pipelines.

Relevant areas:

- `backend/app/modules/staff/`
- `backend/app/modules/organisation/`
- `backend/app/modules/roles/`
- `backend/app/modules/permissions/`
- `backend/app/modules/settings/`
- `frontend/src/pages/staff/`
- `frontend/src/pages/roles/`

### 3.3 Task workflow engine

The task system is the most mature workflow area. It supports:

#### Task creation and views

- Internal tasks that remain within a department.
- External tasks that can route between departments.
- Automatic project generation for external tasks.
- Task list pagination.
- Kanban/status board views.
- Pipeline board views.
- Personal task lists.
- Department inbox for unassigned external tasks.
- Deleted-task administration view.
- Archive search.

#### Assignment and routing

- Initial assignment.
- Reassignment.
- Forwarding to another user.
- Push-back to the sender.
- Department-to-department forwarding.
- Return to a previous department.
- Escalation to a department manager.
- Assignment history and department routing history.

#### State and completion workflow

- Start, review submission, block, unblock, completion, reopening, and archiving actions.
- Pipeline-stage synchronization with task status.
- Dual completion approval: assignee confirmation followed by creator approval.
- Rejection of a completion claim.
- Soft deletion and restoration.
- Super-admin hard purge path.
- Project completion checks based on linked task state.

#### Collaboration and traceability

- Task comments and threaded replies.
- User mentions and mention notifications.
- `@archive[...]` references to archived work.
- Comment resolve, approve, and reject operations.
- Task dependencies.
- Unified timeline.
- Audit records.
- Assignment, rejection, approval, and routing records.
- Deadline reminders through Celery.

Relevant areas:

- `backend/app/modules/tasks/models.py`
- `backend/app/modules/tasks/router.py`
- `backend/app/modules/tasks/service.py`
- `backend/app/modules/projects/auto_generator.py`
- `frontend/src/pages/tasks/`
- `frontend/src/api/tasks.api.ts`
- `backend/alembic/versions/0043_task_workflow_engine.py` through `0052_rls_phase5_tables.py`

### 3.4 Projects and configurable pipelines

Projects are supported as operational containers for work. The project/pipeline area includes:

- Project creation and editing.
- Project ticket numbers.
- Automatic project generation from external tasks.
- Linkage between source tasks and generated projects.
- Department ownership.
- Pipeline templates and configurable stages.
- Workflow edges and stage transitions.
- Stage advancement.
- Stage approval and push-back.
- Progress calculations.
- Project comments, timelines, and activity.
- Department notifications around pipeline movement.
- Customer-linked project fields and stage requirements.

Relevant areas:

- `backend/app/modules/projects/`
- `backend/app/modules/organisation/workflow_router.py`
- `frontend/src/pages/projects/`
- Migrations `0060`, `0061`, `0065`, and `0066`

### 3.5 FTTx infrastructure and GIS operations

The infrastructure module models and operates network assets, including:

- Sites, POPs, hubs, data centres, and nodes.
- OLTs and OLT ports.
- Cabinets and splitter boxes.
- Fibre routes and geographic coordinates.
- Subscriber coverage records.
- Port inventory and utilisation.
- Capacity alerts and alert resolution.
- GIS/map payloads for frontend visualisation.
- Infrastructure audit history.
- Bulk upload validation and staging.
- Bulk deletion workflows with deletion sessions.
- SmartOLT port synchronisation.

Relevant areas:

- `backend/app/modules/infrastructure/`
- `frontend/src/pages/infrastructure/`
- Migrations `0067` through `0074`

### 3.6 Outages, monitoring, SLA, and notifications

The outage and monitoring areas provide:

- Outage creation and management.
- Severity classification.
- OLT alarm handling and deduplication.
- OLT-to-region mapping.
- Linked outage tasks.
- SLA deadlines and breach checks.
- NOC notifications.
- Customer notification configuration and delivery paths.
- Scheduled SmartOLT polling.
- Scheduled SLA checking.
- Customer notification background tasks.

Relevant areas:

- `backend/app/modules/outage/`
- `backend/app/modules/smartolt/`
- `backend/app/tasks/smartolt_polling.py`
- `backend/app/tasks/sla_checker.py`
- `backend/app/tasks/customer_notifications.py`
- `backend/app/modules/notifications/`

Actual delivery requires the relevant credentials and services, described in Section 6.

### 3.7 Webhooks and external event intake

The webhook module supports:

- HMAC-SHA256 webhook key creation.
- Key listing and revocation.
- Signed webhook reception.
- Sales lead events.
- HR hired, terminated, and transferred events.
- Finance project/budget events.
- Field-tech outage events.
- Coverage events.
- Inventory and integration-related handlers.

Sales events are routed through the external-task workflow and can create an automatic project. Other handlers have their own event-processing paths.

Relevant area: `backend/app/modules/webhooks/router.py`.

### 3.8 Customer and payment operations

The later migration and module additions provide support for:

- Customer records.
- Customer-specific field definitions and values.
- Field visibility rules.
- Customer form submissions.
- Customer audit history.
- Customer-to-project relationships.
- Payment requests.
- Payment confirmations.
- Customer-facing workflow data used by projects and forms.

Relevant areas:

- `backend/app/modules/customers/`
- `frontend/src/pages/customers/`
- Migrations `0053` through `0065`

### 3.9 Forms and Form Builder

There are two form implementations in the repository.

#### Legacy context forms

The legacy system supports forms associated with contexts such as leads, tasks, projects, and onboarding. It includes field management, publishing, dependencies, rendering, validation, and submission lookup.

Relevant areas:

- `backend/app/modules/forms/`
- `frontend/src/pages/forms/`
- `frontend/src/components/forms/`

#### Canonical versioned Form Builder

The newer Form Builder supports:

- Form schema CRUD.
- Field CRUD and ordering.
- Multiple field types.
- Draft, published, and archived schema states.
- Immutable form-version snapshots.
- Renderer configuration.
- Context associations.
- Draft saves.
- Dry-run validation.
- Final submissions.
- Submission approval and rejection.
- JSON export.
- Conditional logic.
- Role-based visibility and editability.
- Uniqueness checks.
- Pipeline-stage requirements.
- Historical, version-aware submissions.

Relevant areas:

- `backend/app/modules/form_builder/`
- `frontend/src/pages/form-builder/`
- `frontend/src/components/form-builder/`
- `frontend/src/api/form-builder.api.ts`
- Migrations `0076` through `0083`

### 3.10 Other operational modules

The repository also contains routes and frontend surfaces for:

- Dashboard and operational summaries.
- Reports.
- Activity feeds and audit logs.
- Onboarding.
- Notifications.
- Shifts and shift-swap requests.
- Settings and integrations.
- Organisation workflow configuration.
- Staff efficiency/performance.

These are represented by router modules under `backend/app/modules/` and routed pages under `frontend/src/pages/`.

### 3.11 Frontend application

The React/Vite frontend currently exposes pages for:

- Authentication, registration, activation, and setup.
- Dashboard.
- Tasks, task boards, inbox, deleted tasks, analytics, and task details.
- Projects and project pipelines.
- Outages.
- Staff and performance.
- Roles, permissions, onboarding, notifications, activity, and audit.
- Reports and organisation workflow configuration.
- Infrastructure maps, settings, uploads, deletions, and audit.
- Shifts and swap requests.
- Customers and customer forms.
- Legacy forms and the new Form Builder.

The frontend API layer includes clients for tasks, projects, staff, customers, and Form Builder operations.

## 4. Database and Runtime Architecture

The migration chain currently extends through `0083` and covers:

- Core application schema.
- Tenant and RLS support.
- Task workflow tables and approval history.
- Customer and payment tables.
- Project pipeline and stage requirements.
- Infrastructure upload, deletion, audit, and network asset tables.
- Legacy form table renaming.
- Canonical Form Builder schema, versions, associations, submissions, and seed permissions.

The Docker development stack defines five major runtime services:

1. PostgreSQL 16 with PostGIS.
2. Redis 7.
3. FastAPI backend.
4. Celery worker.
5. Celery Beat scheduler.
6. React frontend is also defined as a container in the compose file; the project documentation describes the stack as five service categories because worker/scheduler are grouped operationally.

The backend declares Python 3.12, FastAPI, SQLAlchemy async, Alembic, PostgreSQL async support, Redis, Celery, Sentry, pytest, Ruff, and mypy. The frontend declares Vite, TypeScript, React Query, Vitest, ESLint, and the associated UI/testing libraries.

## 5. Tests and Current Verification Evidence

Tests are present for:

- Migration-chain checks.
- Task service and task router behavior.
- Infrastructure phases and bulk operations.
- Form Builder routes, submissions, and validation.
- Authentication, staff, permissions, onboarding, reports, shifts, and capacity monitoring.
- Frontend task and workflow components.

The repository exposes these validation commands:

```powershell
# Backend, from backend/
python -m compileall -q app
pytest

# Frontend, from frontend/
npm.cmd run typecheck
npm.cmd run build
npm.cmd run test
npm.cmd run lint
```

For this study, the repository was inspected and the snapshot was confirmed clean and synchronized with `origin/main`. Backend compilation and frontend typechecking/building have been used during the preceding project review, but this study did not execute the full database-backed pytest suite, browser tests, or external integrations.

Therefore, the correct status is **source-supported and statically validated in key areas**, not **fully production-verified**.

## 6. Intended but Incomplete, Partial, or Unverified Work

### 6.1 Confirmed partial implementations or technical debt

The following items are visible in source and should not be presented as fully complete:

- Pipeline event output has missing department display metadata in at least one path, including `to_department_name` being left as `None`.
- Pipeline comment author display can use UUID strings rather than joined human-readable names.
- The pipeline seed script uses a generated UUID for `created_by` and contains an explicit TODO around ownership.
- Dashboard on-call reporting is represented as a stub or approximation based on active staff counts.
- Some permission-related code is marked as a stub even though permission enforcement exists elsewhere.
- Customer project creation can fall back to a generic pipeline rather than always using the configured tenant pipeline.
- SmartOLT linked-task creation catches broad exceptions and can return `None`, which risks hiding integration failures.
- The SmartOLT linked-task path uses an assignment field that must be checked against the newer task model at runtime.
- Some generated build and bytecode artifacts have existed in the repository history; they should not be treated as source-level product features.

### 6.2 Disabled, beta, or explicitly future-facing frontend areas

The navigation/UI contains items that are not fully available:

- AI Insights.
- Trend Analysis.
- Documentation.
- Tutorials.
- FAQ.
- Support Center.
- Release Notes.
- Some integrations marked `coming_soon`.
- MTTR Analytics labelled as beta rather than a fully established product area.

These are intended product surfaces, but the current code should be described as placeholder, disabled, beta, or future work depending on the specific page.

### 6.3 Operational behavior that remains unverified

The following require a real environment and cannot be confirmed by source inspection alone:

- Clean execution of all Alembic migrations against a fresh PostgreSQL/PostGIS database.
- Cross-tenant RLS enforcement using real database sessions and representative roles.
- Redis connectivity, rate limiting, and cache behavior.
- Celery worker registration, task execution, retry behavior, and Beat scheduling.
- SmartOLT polling, alarm ingestion, port synchronisation, and outage linkage.
- SMTP/email provider delivery.
- Termii SMS/WhatsApp delivery.
- Slack, Teams, PagerDuty, or other notification integrations where configured.
- Webhook signatures, tenant headers, API keys, and real external payloads.
- Production container builds, registry images, TLS certificate mounts, and Nginx startup.
- Complete browser workflows across desktop and mobile layouts.
- Full end-to-end behavior with seeded tenant, staff, department, role, and infrastructure data.

### 6.4 Documentation still incomplete

The existing `README.md` is a short product description and does not function as a complete operator or developer guide. It does not fully document:

- Local setup prerequisites.
- Environment variables and secrets.
- Migration/bootstrap order.
- Seed commands.
- Available API domains and routes.
- Celery worker/Beat operation.
- External integration setup.
- Test matrix and known limitations.
- Production deployment and rollback procedures.

`IMPLEMENTATION_REPORT.md` is useful as a historical Phase 5 report, but it stops at the Phase 5 scope and does not cover the later migration and module additions through `0083`.

## 7. Recommended Completion Priorities

### Priority 1: Prove the runtime

- Run the complete Docker stack from a clean database.
- Apply all migrations through `0083`.
- Execute backend tests with PostgreSQL and Redis available.
- Execute frontend tests and lint.
- Exercise authentication, tenant provisioning, task routing, project pipeline, infrastructure upload, outage creation, and Form Builder submission in a browser.

### Priority 2: Close correctness gaps

- Replace placeholder pipeline display metadata with real department/user joins.
- Fix seed ownership so pipeline records are created by a real tenant user.
- Replace broad SmartOLT exception swallowing with logged, observable failures.
- Reconcile SmartOLT task assignment fields with the current task model.
- Make customer project pipeline selection deterministic and configuration-driven.
- Replace dashboard/on-call stubs with the intended operational calculation.

### Priority 3: Finish product surfaces

- Implement or remove the disabled AI/help/support/release-note navigation items.
- Decide whether MTTR analytics is ready for production or should remain explicitly beta.
- Document all integrations and environment requirements.
- Add browser-level smoke tests for the most important operational flows.

### Priority 4: Repository hygiene

- Keep generated `__pycache__` and build artifacts out of source control where possible.
- Add or verify ignore rules for generated files.
- Keep the implementation/status report updated when migrations or modules are added.
- Separate historical plans from current operational documentation.

## 8. Final Classification

### Implemented in source

Authentication, tenancy, RBAC, staff/organisation management, task workflows, project pipelines, infrastructure management, outages, notifications, webhooks, customers/payments, forms, reports, shifts, background task definitions, database migrations, Docker orchestration, and the main frontend routes.

### Partially implemented

Some pipeline display metadata, dashboard/on-call calculations, seed ownership, customer pipeline selection, SmartOLT linked-task error handling, and selected analytics/help/integration surfaces.

### Intended but not complete or disabled

AI insights, trend analysis, documentation/help center, tutorials, FAQ, support center, release notes, selected coming-soon integrations, and beta analytics areas.

### Unverified

Production deployment, clean migration rollout, database RLS under real workloads, full test suite, external integrations, scheduled Celery operation, and complete browser-level workflows.

## 9. Bottom Line

Opsyn can currently serve as a broad internal operations platform with a strong task/project workflow core and significant FTTx infrastructure capability. The codebase contains the major pieces needed for a deployable product, but the remaining work is concentrated in runtime verification, integration hardening, completion of explicitly disabled product surfaces, documentation, and replacing a small number of stubs/fallbacks with production-grade behavior.
