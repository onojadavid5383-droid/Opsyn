---
name: opsyn-script-agent
description: generate, debug, refactor, and review implementation scripts for the opsyn operational intelligence platform. use this skill when the user asks a claude agent to create frontend, backend, database, devops, migration, test, seed, api, rbac, audit, notification, outage, task, staff, onboarding, or report code from the opsyn implementation plan; debug failing scripts; minimize token usage; continue phased delivery; or produce concise prompts for coding agents.
---

# Opsyn Script Agent

## Purpose

Use this skill to act as a focused engineering agent for Opsyn. Generate production-ready implementation scripts, debug failures, and keep prompts and outputs compact enough for coding-agent workflows.

Opsyn is a three-tier operational intelligence platform:
- Frontend: React 18, TypeScript 5, Vite 5, Zustand, React Query, Zod.
- Backend: Python 3.12, FastAPI 0.115, SQLAlchemy async, Pydantic v2, Alembic, Celery.
- Data: PostgreSQL 16, Redis 7.

Load only the reference file needed for the current task:
- For architecture, files, domains, phases, API contracts, and the April 2026 project status audit, read `references/opsyn-project-reference.md`.
- For script-generation/debugging output formats, read `references/output-contracts.md`.
- For context-budget rules, read `references/token-minimization.md`.

## Default Operating Rules

1. Treat the Opsyn implementation plan and the April 2026 project status audit as the source of truth.
2. Preserve strict module boundaries. Do not import another domain module's internals.
3. Put business logic in backend services, not routers or frontend components.
4. Enforce RBAC and scope server-side. Frontend guards are only UX.
5. Wrap backend writes in transactions. Avoid partial writes.
6. Scrub `password_hash` and secrets from logs, audit states, and examples.
7. Prefer small, independently testable files over broad rewrites.
8. Match the existing stack exactly unless the user explicitly requests a change.
9. When details are missing, make the safest implementation assumption and state it briefly.
10. Never generate placeholder-heavy code as final output. Include concrete imports, types, errors, and tests where relevant.

## Current Baseline

Assume the following unless the user provides newer code or instructions:

- Completed: Docker Compose/dev environment, frontend high-fidelity Opsyn Brand prototype, module/file architecture, and database schema.
- In progress: FastAPI staff creation pipeline, task backend grouping logic, and GIS integration through XON inventory/KoboCollect snapping.
- Not done: Celery notification triggers, full audit mutation middleware, Kubernetes production manifests, and complete RBAC hardening across all endpoints.

Prioritize active-development code over regenerating completed foundations. Keep future-phase work behind clean interfaces or explicit follow-up tickets unless requested.

## Workflow Decision

Determine the user intent first:

- **Generate script/code**: follow the generation workflow.
- **Debug script/error**: follow the debugging workflow.
- **Minimize prompt/token usage**: follow the compression workflow.
- **Plan next implementation step**: follow the phase workflow.
- **Review existing code**: follow the review workflow.

## Generation Workflow

1. Identify the target tier, domain, phase, status bucket (completed, active, future), and files.
2. Read `references/opsyn-project-reference.md` only if the needed contract or file map is not already known from the prompt.
3. Produce a compact implementation plan with impacted files.
4. Generate code in dependency order:
   - Backend: models -> schemas -> policy -> service -> router -> tests -> migration/seed.
   - Frontend: types -> api -> hook/store -> components -> page -> tests.
   - DevOps: env -> compose/docker -> make target -> CI step.
5. Include minimal verification commands.
6. Call out any assumptions or required secrets/env values.

## Debugging Workflow

1. Ask for or infer the failing command, stack trace, file path, and expected behavior.
2. Classify the failure: dependency, import path, schema mismatch, async/session, RBAC/scope, migration, API contract, frontend state, build, or test.
3. Trace the failure through the Opsyn connectivity map.
4. Return:
   - root cause,
   - exact patch or replacement code,
   - why the fix works,
   - regression test,
   - verification command.
5. Keep the fix local to the owning module unless a contract change is unavoidable.

## Compression Workflow

Use this when asked to minimize token usage or prepare prompts for coding agents.

1. Preserve constraints before details.
2. Replace repeated architecture prose with references to file paths and contracts.
3. Keep only task-relevant domain facts.
4. Emit one of these formats:
   - `compact-agent-prompt`, for Claude/Cursor/Codex style coding agents.
   - `implementation-ticket`, for one focused deliverable.
   - `debug-brief`, for failures.
5. Never remove security, RBAC, transaction, or module-boundary rules.

## Phase Workflow

Map work to the 10 Opsyn phases and the April 2026 status audit. Do not start a later phase if it depends on missing earlier foundations. For each phase task, produce:

- objective,
- impacted files,
- implementation sequence,
- acceptance criteria,
- tests,
- verification commands.

## GIS Integration Rule

When the user mentions XON inventory, KoboCollect, snapping, field assets, GIS, map coordinates, OLT locations, or inventory sync, keep the implementation modular. Prefer integration adapters, explicit schemas, and bounded APIs. Do not leak GIS concerns into staff, task, or outage internals except through typed service calls or event payloads.

## Review Workflow

Review against these gates:

- architecture and module boundaries,
- typed API contracts,
- RBAC/scope enforcement,
- async transaction safety,
- audit logging and secret scrubbing,
- error handling and status codes,
- frontend state/query correctness,
- tests and migration quality,
- token efficiency of the generated prompt or script.

## Output Discipline

Use concise, direct engineering output. Avoid restating the entire architecture. Prefer patches, file trees, and commands. For large tasks, split work into small deliverables and provide the first executable slice.

