# Output Contracts

Use these formats to keep outputs professional and consistent.

## compact-agent-prompt

```text
You are implementing Opsyn, a modular operational intelligence platform.

Task: [one concrete deliverable]

Source of truth:
- Stack: React 18 + TS 5 + Vite 5; FastAPI 0.115 + Python 3.12; PostgreSQL 16 + Redis 7 + Alembic.
- Module boundary: [domain-specific rule]
- Security: [RBAC/scope/transaction/audit rule]

Files to create/update:
1. path - purpose
2. path - purpose

Implementation requirements:
- [specific requirement]
- [specific requirement]

Acceptance criteria:
- [observable result]
- [test result]

Return only:
- changed files with code blocks,
- tests,
- commands to verify.
```

## implementation-ticket

```markdown
# [Domain] [Deliverable]

## Objective
[One sentence]

## Impacted files
- `path`: [purpose]

## Sequence
1. [step]
2. [step]

## Requirements
- [requirement]

## Acceptance criteria
- [criteria]

## Verification
```bash
[commands]
```
```

## debug-brief

```markdown
# Debug Brief: [failure]

## Symptom
[Exact error or failing behavior]

## Likely root cause
[Specific cause tied to file/module]

## Patch
[Exact replacement code or diff]

## Regression test
[Test to prevent recurrence]

## Verify
```bash
[commands]
```
```

## code-response

For code generation, use this order:

1. `Assumptions` only if needed.
2. `Files changed` list.
3. Code blocks labeled with exact paths.
4. Tests.
5. Verification commands.
6. Notes on follow-up dependencies.

Avoid long explanations unless debugging requires it.
