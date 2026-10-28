# Opsyn Project Reference

## Engineering Philosophy

Opsyn is a full-spectrum operational intelligence command platform. It is the single source of truth for workforce decisions, real-time network monitoring, incident command, and operational analytics.

Core principle: every file is a standalone module; every module owns its domain; every module is independently testable and replaceable. Frontend, backend, and database are independently deployable artifacts connected only by typed API contracts.

## Stack

- Frontend: React 18, TypeScript 5, Vite 5.
- Backend: Python 3.12, FastAPI 0.115.
- Data: PostgreSQL 16, Redis 7, Alembic.
- Background jobs: Celery with Redis broker.

## Domains

| Domain | Frontend | Backend | DB |
|---|---|---|---|
| Auth | auth/ | modules/auth/ | users, refresh_tokens |
| Staff | staff/ | modules/staff/ | users, staff_profiles |
| Organisation | org/ | modules/organisation/ | departments, teams, regions |
| Roles | roles/ | modules/roles/ | roles, permissions, user_scopes |
| Tasks | tasks/ | modules/tasks/ | tasks, task_comments, task_tags |
| Projects | projects/ | modules/projects/ | projects, project_tasks |
| Outage | outage/ | modules/outage/ | outage_incidents, outage_assignments |
| Onboarding | onboarding/ | modules/onboarding/ | staff_onboarding_requests |
| Audit | audit/ | modules/audit/ | audit_logs |
| Notifications | notifications/ | modules/notifications/ | notifications |
| Reports | reports/ | modules/reports/ | read-only views + exports |

## Backend Layout

`apps/backend/`
- `main.py`: app factory, lifespan, CORS, middleware.
- `app/core/`: config, database, Redis, security, exceptions, logging, Celery, constants.
- `app/middleware/`: auth, CORS, rate limit, audit, request ID, timing.
- `app/dependencies/`: auth, permissions, pagination, filters.
- `app/modules/<domain>/`: router, service, schemas, models, policy when needed.
- `app/events/`: event bus and handlers.
- `alembic/`: migrations.
- `tests/`: unit, integration, e2e.

Backend rule: routers handle HTTP and dependencies; services own business logic and transactions; policies own authorization decisions; schemas own validation; models own persistence.

## Frontend Layout

`apps/frontend/src/`
- `api/`: Axios client and per-domain API files.
- `store/`: Zustand global state.
- `hooks/`: React Query and domain hooks.
- `guards/`: route protection.
- `layouts/`: shell layouts.
- `components/`: shared UI.
- `pages/`: route-level page components.
- `types/`: TypeScript contracts.
- `utils/`: pure utilities.

Frontend rule: no business authorization logic. Hide UI optimistically, but rely on backend enforcement.

## Critical Backend Flow: Staff Creation

POST `/api/v1/staff` must execute:
1. JWT extraction in `middleware/auth_middleware.py`.
2. Current user load in `dependencies/auth.py`.
3. Role gate `require_role(4)` in `dependencies/permissions.py`.
4. Pydantic validation in `modules/staff/schemas.py`.
5. Scope check in `modules/staff/policy.py can_create()`.
6. Hierarchy rule in `can_assign_role()`.
7. Uniqueness checks in `modules/staff/validators.py`.
8. Single DB transaction inserting `users` and `staff_profiles`.
9. Audit write to `audit_logs`.
10. Event emit `staff.created`.
11. Celery invite task.

Failures: 401 auth, 403 role/scope/hierarchy, 422 validation, 409 uniqueness, 500 rollback.

## Critical Frontend Flow: Kanban Board Load

1. `TasksPage.tsx` mounts.
2. `useTaskBoard()` triggers React Query.
3. `tasks.api.ts` sends GET `/api/v1/tasks/board`.
4. `interceptors.ts` injects JWT.
5. `modules/tasks/router.py` receives request.
6. `modules/tasks/service.py list_by_deadline()` groups tasks.
7. Response shape: `overdue`, `today`, `this_week`, `next_week`, `no_deadline`, `backlog`.
8. `KanbanBoard.tsx`, `KanbanColumn.tsx`, and `TaskCard.tsx` render.

## RBAC Rules

Every protected request checks:
1. token valid,
2. user active,
3. role level sufficient,
4. user in scope,
5. hierarchy safe,
6. Pydantic payload valid,
7. business rule valid,
8. transaction commits.

Role levels:
- Admin: 5, system-wide.
- Manager: 4, own department and teams.
- Team Lead: 3, own team view and onboarding request.
- NOC Operator, MEC Reviewer, Executive Viewer: 2.
- Staff: 1, own profile only.

## API Conventions

- Prefix all endpoints with `/api/v1/`.
- Wrap responses in `APIResponse<T>`.
- Validate request bodies with Pydantic v2.
- Protected endpoints require `Authorization: Bearer <JWT>`.
- Enforce role level with FastAPI dependencies, not ad hoc frontend checks.

Important endpoints:
- Auth: `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/reset-password`.
- Staff: `/staff`, `/staff/{id}`, `/staff/{id}/status`, `/staff/{id}/tasks`, `/staff/{id}/audit`.
- Org: `/departments`, `/teams`, `/regions`.
- RBAC: `/roles`, `/roles/{id}/assign`, `/user-scopes`, `/permissions`.
- Tasks: `/tasks`, `/tasks/{id}`, `/tasks/{id}/status`, `/tasks/{id}/comments`, `/tasks/board`, `/tasks/my`.
- Outages: `/outages`, `/outages/{id}/resolve`.
- Onboarding: `/onboarding`, `/onboarding/{id}/approve`, `/onboarding/{id}/reject`.
- Audit/reports: `/audit-logs`, `/audit-logs/export`, `/reports/summary`, `/reports/export/pdf`.
- Health: `/health`.

## Database Rules

- UUID primary keys generated by `gen_random_uuid()`.
- Timestamps are `TIMESTAMPTZ`.
- Use Alembic for all schema changes.
- Never return password hashes.
- Scrub `password_hash` from audit JSONB states.
- `audit_logs` is append-only.

Hot indexes to remember:
- `tasks(deadline, status, department_id)` for kanban board.
- `audit_logs(created_at)` for recent activity.
- Unique indexes on username, email, staff_code, role name, permission key, region code.

## Implementation Phases

1. Monorepo and DevOps foundation.
2. Database foundation.
3. Auth module.
4. Organisation core.
5. Staff management.
6. Task manager.
7. Outage monitor and projects.
8. Onboarding and notifications.
9. Audit, reports, and intelligence.
10. Testing, security, and production.

Do not generate code that depends on a later phase unless earlier phase prerequisites are present or included in the deliverable.

## Environment Variables

Backend: `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, `ALGORITHM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `FROM_EMAIL`, `FRONTEND_URL`, `ENVIRONMENT`, `ALLOWED_ORIGINS`, `CELERY_BROKER_URL`.

Frontend: `VITE_API_BASE_URL`, `VITE_APP_NAME`, `VITE_POLLING_INTERVAL`.

## Security Defaults

- Bcrypt cost 12.
- Access token expiry 15 minutes.
- Refresh token expiry 7 days.
- Store refresh token hashes in Redis and rotate on use.
- Rate limit login to 5 attempts per 15 minutes per IP.
- Send invite links using signed one-time tokens. Do not email plaintext passwords.
- Add security headers in production.

## Project Status Audit: April 2026

Treat this status audit as the current delivery baseline when generating, debugging, or compressing Opsyn coding-agent prompts.

### Completed foundations

- DevOps and environment foundation exists: Docker Compose stack for FastAPI, PostgreSQL, Redis, Celery, and React is defined.
- Frontend UI/UX prototype exists: high-fidelity interactive Opsyn Brand experience using green, teal, cyan, and blue gradient language.
- Information architecture exists: frontend and backend file trees and module boundaries are established.
- Data modeling exists: full database schema is defined for all 11 core modules with UUID primary keys and timestamp conventions.

### Active development priorities

Prioritize these areas unless the user specifies otherwise:

1. **Core Staff Pipeline**: implement the full Python/FastAPI 11-step staff creation pipeline, including RBAC, scope, hierarchy, uniqueness, transaction safety, audit write, event emit, and Celery invite dispatch.
2. **Task Management Backend**: implement `modules/tasks/service.py list_by_deadline()` and related API/schema/test logic for kanban buckets and future Gantt support.
3. **GIS Integration**: treat XON inventory and KoboCollect snapping as active integration sub-projects that may feed Opsyn regions, outage intelligence, project monitoring, and field operations. Keep GIS work modular; do not mix it into staff/tasks internals. Prefer a dedicated `modules/gis/` or integration adapter if implementation is requested.

### Future-phase work not yet complete

Do not assume these are already implemented unless the user provides code proving it:

- Phase 8 notifications: Celery email notification triggers and templates.
- Phase 9 audit: full mutation-interceptor audit logging across POST/PUT/PATCH/DELETE.
- Phase 10 production: Kubernetes manifests, production monitoring, hardening, and full CI/CD deploy path.
- Security hardening: complete five-layer server-side dependency-injection enforcement for RBAC across all protected endpoints.

### Status-aware generation rule

When generating code, start from completed foundations and build only the next missing slice. Do not regenerate completed architecture unless asked. Prefer production implementation for active priorities and explicit stubs/interfaces only for future-phase dependencies.
