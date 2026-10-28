---
name: project-opsyn-status
description: Opsyn corrective implementation plan current status — what's been built vs. what remains
metadata:
  type: project
---

Phase 0 (Multi-Tenant Foundation) — COMPLETE as of 2026-05-12. Migrations 0027-0033 add tenants table, tenant_id FKs on all tables, RLS policies, activity_timeline, infrastructure_sites/nodes/routes. TenantMiddleware, get_db() RLS injection, JWT tenant_id claims all done.

Phase 1 (RBAC & Frontend Plumbing) — COMPLETE. RBAC tables (feature_permissions, department_feature_grants, role_feature_overrides) done in 0030. check_permission() dependency in permissions.py. All routers migrated off require_role(). Notification store + 30s polling hook in hooks/index.ts. API interceptors in api/client.ts. Shared UI components done.

**Phase 2, Stage 1 (Task Engine Corrections S2.1.1–S2.1.5) — COMPLETE as of 2026-05-12**

What was done:
- Migration 0034: block_reason TEXT, ticket_number VARCHAR(20), estimated_hours FLOAT, form_submission_id UUID added to tasks; UNIQUE(tenant_id, ticket_number) constraint + ix_tasks_ticket_number index
- Task ORM model: tenant_id, block_reason, ticket_number, estimated_hours, form_submission_id mapped columns added
- _generate_ticket_number(db): per-tenant TSK-YYYY-NNNN generator using MAX(CAST(RIGHT(...,4) AS INTEGER)) — RLS auto-scopes to tenant
- TaskService.create(): sets tenant_id=caller.tenant_id, ticket_number, estimated_hours; clone() also generates new ticket_number
- Action endpoints: POST /tasks/{id}/start, /submit-review, /block (body: block_reason), /unblock, /done (intelligent S2.1.3), /archive
- GET /tasks/status-board: 7-column status board endpoint
- shared-types/index.ts: TaskStatus updated to 7 real states; Task interface enriched (ticket_number, block_reason, estimated_hours, pipeline_id, stage_id, responsible_user, dependencies, previous_state); TaskStatusBoard type added; AddCommentRequest, TransitionRequest, TaskDependency, CommentType, ApprovalAction added
- tasks.api.ts: getStatusBoard, start, submitReview, block, unblock, done, archive methods added
- TaskCard.tsx: ticket_number badge (top, monospace, copy-on-click); blocked tasks show block_reason tooltip
- TaskDetailModal.tsx: copyable ticket_number badge in header above title
- StatusKanbanBoard.tsx: new component — 7 status columns using KanbanColumn; blocked column is red
- TasksPage.tsx: "Status Board" tab added (index 1, lazy-fetches via status-board endpoint only when tab is active)

**Phase 2, Stages 2-4 — NOT STARTED (pending Stage 1 approval gate)**

Remaining items:
- S2.2.1: ticket_number on projects, expand project_type ENUM, Team Lead gate
- S2.2.x: ProjectDetailPage, PipelineStageRail, ProjectCard, AdvanceStageModal/PushBackModal
- S2.3.1-3.4: 2-phase onboarding (manager_approved_by column, PATCH /manager-approve, PUT /staff/{id}), OnboardingPage two-phase UI
- S2.4.x: IntelStrip live KPI bar + complete settings API endpoints

**Why:** Corrective implementation plan dated May 2026. Strict gate — must get approval before Stage 2.

**How to apply:** Do NOT proceed to Stage 2 until user explicitly approves Stage 1 completion.

Key file locations:
- Backend: /backend/app/modules/tasks/router.py (task service + endpoints — now updated)
- Backend: /backend/app/modules/all_modules.py (onboarding, outage, org, roles models + routers)
- Migrations: /backend/alembic/versions/ (latest: 0034)
- Frontend hooks: /frontend/src/hooks/index.ts
- Frontend API client: /frontend/src/api/client.ts
- Frontend shared types: /frontend/shared-types/index.ts (authoritative for frontend)
