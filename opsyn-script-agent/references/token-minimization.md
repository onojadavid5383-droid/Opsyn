# Token Minimization Rules

## Preserve These Always

- Target phase and domain.
- Exact files to create or edit.
- Stack versions.
- API route and response contract.
- DB table and migration requirement.
- RBAC role level, scope, hierarchy, and transaction rules.
- Audit and secret-scrubbing rules.
- Test and verification commands.

## Remove or Compress

- Marketing descriptions of Opsyn.
- Repeated file-tree sections unrelated to the task.
- Long database schemas for unrelated domains.
- Full endpoint lists when only one endpoint is being implemented.
- Generic coding best practices that any coding agent already knows.
- Redundant reminders after the first mention.

## Prompt Compression Pattern

Before:
"Opsyn is a full-spectrum operational intelligence command platform..."

After:
"Implement for Opsyn. Follow modular DDD: frontend api/hook/page, backend router/service/schema/model/policy, PostgreSQL via Alembic, RBAC server-side."

## Context Budget Targets

- Single bug fix: 250-600 tokens.
- Single backend endpoint: 700-1,200 tokens.
- Single frontend page/hook/API slice: 700-1,200 tokens.
- Full domain module: 1,500-2,500 tokens.
- Multi-phase plan: 1,000-1,800 tokens.

## Compact Script Request Template

```text
Implement [feature] for Opsyn [domain], Phase [n].
Files: [exact files].
Contract: [endpoint/schema/table].
Rules: server-side RBAC [role/scope], transaction for writes, audit mutations, no cross-domain internals.
Return code, tests, and commands only.
```

## Compact Debug Request Template

```text
Debug Opsyn [domain].
Command: [command]
Error: [stack trace]
Expected: [behavior]
Relevant files: [paths]
Rules: preserve module boundaries, async SQLAlchemy, FastAPI dependencies, RBAC/scope.
Return root cause, patch, test, verify command.
```

## Status-Aware Prompt Compression

Use the April 2026 audit to avoid wasting tokens:

- Replace completed foundation detail with: `Foundations done: compose stack, brand prototype, module tree, DB schema.`
- For active implementation, keep concrete files and contracts for staff pipeline, task board grouping, or GIS adapters.
- For future phases, say `interface only` unless asked for full implementation.
- Never include the full 10-phase roadmap when the task targets one active slice.

### Active Staff Pipeline Compact Prompt

```text
Implement Opsyn Phase 5 staff creation pipeline.
Files: modules/staff/{router,service,schemas,models,policy,validators}.py, dependencies/permissions.py, tests/integration/test_staff_routes.py.
Flow: auth -> require_role(4) -> Pydantic -> scope -> hierarchy -> uniqueness -> transaction users+staff_profiles -> audit -> staff.created event -> invite task stub/interface.
Rules: async SQLAlchemy, rollback on failure, 401/403/422/409 mapping, scrub password_hash.
Return code, tests, commands only.
```

### Active Task Board Compact Prompt

```text
Implement Opsyn Phase 6 task board grouping.
Files: modules/tasks/{router,service,schemas,models}.py, tests/integration/test_task_routes.py.
Endpoint: GET /api/v1/tasks/board -> {overdue,today,this_week,next_week,no_deadline,backlog}.
Rules: filter by caller scope, index tasks(deadline,status,department_id), async SQLAlchemy, APIResponse wrapper.
Return code, tests, commands only.
```

### GIS Integration Compact Prompt

```text
Design modular Opsyn GIS adapter for XON inventory + KoboCollect snapping.
Keep separate from staff/tasks internals. Expose typed service calls/events for outage intelligence, regions, and field operations.
Return bounded module layout, schemas, adapter interfaces, tests, and migration notes.
```
