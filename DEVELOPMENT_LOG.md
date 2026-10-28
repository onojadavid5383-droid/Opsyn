# Opsyn — Development Session Log

> **Powered by SlimTech** · Platform: FTTx Operational Intelligence  
> Last updated: 2026-08-18
> Stack: FastAPI · PostgreSQL 16 · SQLAlchemy 2.0 async · React 18 · TypeScript · Zustand · React Query · Celery · Redis · Leaflet · Docker

---

## Table of Contents

1. [Sprint 2 — Infrastructure & Onboarding (prior session)](#sprint-2)
2. [Sprint 3 — Webhooks, Form Builder, SmartOLT, Shifts, Notifications](#sprint-3)
3. [Sprint 4, Stages 1–2 — GIS Map & Live Badges](#sprint-4-s1-s2)
4. [Sprint 4, Stage 3 — Capacity Monitoring Engine & Coverage Tools](#sprint-4-s3)
5. [Sprint 4, Stage 4 — Reports Suite, Auth Flows, Integration Tests](#sprint-4-s4)
6. [Phase 7 — Production Hardening & DevOps](#phase-7)
7. [Implementation Plan Phase 1 — Critical Backend Fixes](#impl-phase-1)
8. [Implementation Plan Phase 2 — Frontend Fixes & Enterprise Navigation](#impl-phase-2)
9. [Implementation Plan Phase 3 — Architecture & Feature Completion](#impl-phase-3)
10. [Full File Inventory](#file-inventory)
11. [Architecture Reference](#architecture)

---

## Sprint 2 — Infrastructure & Onboarding {#sprint-2}

> Completed prior to the main session log. Summary only.

- **Infrastructure Map** — FTTx asset registry: `InfrastructureSite` (POPs), `InfrastructureNode` (OLT/AGG/CORE), `InfrastructureRoute` (fibre) ORM models + CRUD API
- **Onboarding Auto-Provisioning** — `PATCH /onboarding/{id}/approve` atomically creates `User` + `StaffProfile`, generates invite JWT, emits `onboarding.approved` event → Celery sends invite email
- **Enhanced Reports** — Real MTTR from `resolved_at`, per-severity MTTR, infrastructure counts, task completion rate
- **Account Activation** — `POST /auth/activate` + `POST /auth/reset-password`; `ActivatePage.tsx` reads `?token=`, sets password, issues session
- **Live Dashboard** — `GET /dashboard/summary` aggregating staff/tasks/outages/infra/projects/notifications; `DashboardPage` rewritten to use real data with 30s polling

---

## Sprint 3 — Webhooks, Form Builder, SmartOLT, Shifts, Notifications {#sprint-3}

### S3.1 & S3.2 — Dynamic Form Builder

**Migration 0037** — new tables: `form_schemas`, `form_fields`, `form_field_dependencies`, `form_submissions`; RLS on all; FK `tasks.form_submission_id`, `projects.form_submission_id`

**Backend**
- `app/modules/forms/models.py` — FormSchema, FormField, FormFieldDependency, FormSubmission ORM
- `app/modules/forms/validator.py` — 10 field types, field-level 422 errors
- `app/modules/forms/router.py` — `GET /forms/{context}`, admin CRUD, publish, dependencies, `POST /forms/submit`, `GET /forms/submissions/{entity_type}/{entity_id}`
- `setup_service.py` extended to seed 4 blank schemas per tenant (lead/task/project/onboarding)

**Frontend**
- `components/forms/CoordinatesField.tsx` — 3 input modes: Manual lat/lng, GPS (`navigator.geolocation`), Paste string
- `components/forms/FormFieldRenderer.tsx` — renders 10 field types
- `components/forms/DynamicForm.tsx` — full renderer; resolves show/hide/require dependencies; client-side validation; maps 422 errors
- `pages/forms/FormBuilderPage.tsx` — admin builder: add/edit/delete/reorder fields, publish, dependency rules
- `App.tsx` — `/settings/forms/:context` route
- `AppShell.tsx` — "Form Builder" link in settings sidebar
- `NewTaskModal.tsx` + `ProjectsPage` — 2-step flows (create → optional `DynamicForm`)

---

### S3.3 & S3.4 — Webhook Receiver + Management UI

**Migration 0038** — `webhook_api_keys` (tenant-scoped, HMAC-signed)

**Backend — `app/modules/webhooks/router.py`**

| Route | Purpose |
|-------|---------|
| `GET/POST /webhooks/keys` | Admin: list/create API keys |
| `DELETE /webhooks/keys/{id}` | Admin: revoke key |
| `POST /webhooks/receive` | Receiver: HMAC-SHA256 verify → domain handler |

Domain handlers:
- **HR**: `staff.hired` → create User+StaffProfile; `staff.terminated` → deactivate; `staff.transferred` → update dept
- **Finance**: `project.budget_approved/rejected` → timeline event
- **Sales**: `lead.won/created` → create Project (PRJ ticket)
- **Field Tech**: `outage.detected` → dedup+create OutageIncident; `outage.resolved` → resolve
- **Coverage**: `coverage.expanded/degraded` → timeline on region

**Frontend — `SettingsPage` webhooks tab**
- Table of active keys (app_name, created_at, Revoke button)
- One-time secret modal with copy-to-clipboard and amber warning banner
- New Key modal with app name dropdown

---

### S3.4 — SmartOLT Integration

**Migration 0039** — `smartolt_config`, `smartolt_olt_map`; `outage_incidents` extended with: `source`, `smartolt_event_id`, `affected_customer_ids`, `affected_subscribers`, `sla_deadline`, `breached_sla`, `linked_task_id`

**Backend**
- `app/modules/smartolt/handler.py` — 7-step pipeline: event_type guard → dedup → OLT→region map → classify severity → affected customers → find on-call NOC → create OutageIncident + Task + timeline + notification
- `app/tasks/smartolt_polling.py` — `poll_smartolt_alarms()` Celery task every 60s; Redis-diff for new alarms
- `app/tasks/sla_checker.py` — `check_sla_breaches()` every 5 min; sets `breached_sla=True`; 80% elapsed → warning entry + assignee notification

**Frontend**
- `OutageDetailPage.tsx` — OUT reference badge, severity/status chips, SLA countdown bar (turns red <30min), affected_subscribers count, 3 tabs: Timeline / Affected Customers / Linked Task; Resolve + Notify Customers buttons
- `OutagePage` — SLA countdown chip column, Subs column, row click → detail page

---

### S3.5 — NOC Shift Scheduler & Customer Notifications

**Migration 0040** — `shifts`, `shift_assignments`, `shift_swap_requests`, `outage_notification_rules`, `outage_notification_log`

**Backend**
- `app/modules/shifts/router.py` — GET/POST/DELETE `/shifts`, GET `/shifts/weekly?week_start=`, GET/POST `/shifts/assignments`, PATCH `.../status`, GET/POST/PATCH `/shifts/swap-requests`
  - Swap approval: cancels original assignment, creates new one atomically
- `app/tasks/customer_notifications.py` — `send_outage_notifications(outage_id, tenant_id)` Celery task; evaluates `outage_notification_rules`; renders template tokens `{reference}/{title}/{severity}/{status}/{olt}/{subscribers}`; Termii SMS/WhatsApp + SMTP email; logs to `outage_notification_log`
- `settings/router.py` — CRUD + `/test/{id}` for `outage_notification_rules`

**Frontend**
- `ShiftSchedulerPage.tsx` — weekly grid (staff rows × 7 day cols), week navigation, assign/cancel modals, shift legend, stats bar, conflict detection (409 → toast)
- `SettingsPage` — 'notification-rules' tab: list/create/edit/delete/test rules; channels checkboxes (SMS/Email/WhatsApp), severity dropdown, subscriber threshold, template textarea, is_auto/is_active toggles

---

## Sprint 4, Stages 1–2 — GIS Map & Live Badges {#sprint-4-s1-s2}

### S4.1 — Infrastructure Data Model (Migration 0041)

New tables: `infra_ports`, `infra_subscribers`, `infra_capacity_alerts`, `infra_monitoring_config`, `infra_alert_rules`; `is_monitored BOOL` added to `infrastructure_sites`; RLS on all.

**Backend additions to `infrastructure/router.py`**
- `GET /infrastructure/map` — one-shot payload: sites + nodes + routes + utilisation % + alert flags
- `GET /infrastructure/utilisation` — per-site capacity heatmap data
- `GET/POST/PATCH/DELETE /infrastructure/nodes/{id}/ports`
- `GET/PATCH /infrastructure/capacity-alerts`
- `app/tasks/infrastructure_sync.py` — `sync_smartolt_ports()` every 15 min; UPSERT `infra_ports` via `ON CONFLICT DO UPDATE`

---

### S4.2 — GIS Infrastructure Map

**`frontend/src/pages/infrastructure/InfraMapView.tsx`** (new file)

> react-leaflet pinned to `4.2.1 --legacy-peer-deps` (v5 requires React 19; project uses React 18.3.1)

5 Leaflet overlay layers via `LayersControl.Overlay`:

| Layer | Data source | Visual |
|-------|-------------|--------|
| Network Sites | `GET /infrastructure/sites` | `CircleMarker` coloured by site_type |
| OLT Nodes | `GET /infrastructure/nodes` | `CircleMarker` coloured by status |
| Fibre Routes | `GET /infrastructure/routes` | `Polyline` |
| Capacity Utilisation | `GET /infrastructure/utilisation` | `Circle` halo — radius ∝ capacity % |
| Coverage Demand | `GET /infrastructure/subscribers` | `CircleMarker` coloured by service_type |

```ts
function subscriberColor(serviceType: string): string {
  switch (serviceType.toUpperCase()) {
    case 'FTTH':     return '#38bdf8';
    case 'FTTB':     return '#818cf8';
    case 'FTTC':     return '#fb923c';
    case 'WIRELESS': return '#facc15';
    default:         return '#94a3b8';
  }
}
```

Stats strip: Sites · OLT Nodes · Routes · Active Alerts · Subscribers  
Legend: site types, node types, utilisation scale, subscriber service types

`InfrastructurePage` (`pages/index.tsx`) — 'map' tab added, lazy-loads `InfraMapView` in `Suspense`.

---

## Sprint 4, Stage 3 — Capacity Monitoring Engine & Coverage Tools {#sprint-4-s3}

### Migration 0042

Adds `efficiency_score NUMERIC(5,2)` and `efficiency_computed_at TIMESTAMPTZ` to `staff_profiles`.

---

### Capacity Monitor Celery Task

**`app/tasks/capacity_monitor.py`** (new)

```python
@shared_task(name="infrastructure.check_capacity", bind=True, max_retries=2)
def check_capacity_thresholds(self):
    asyncio.run(_run_checks())
```

Logic:
- Iterates all active `InfraMonitoringConfig` rows
- Computes `utilisation_pct = (used_capacity / total_capacity) * 100`
- Deduplicates alerts within `check_interval_minutes` window
- Creates `InfraCapacityAlert` on warn/critical threshold breach
- Evaluates matching `InfraAlertRule` rows:
  ```python
  _OPS = {"gt": lambda a,b: a>b, "gte": ..., "lt": ..., "lte": ..., "eq": ...}
  ```
- Creates Task when `action_type='create_task'` with params from `action_params` JSONB

---

### Staff Efficiency Scoring

**`app/tasks/staff_efficiency.py`** (new)

```python
# 30-day lookback per staff member
score = (completion_rate * 40) + (sla_adherence * 30) + (resolution_speed * 30)
resolution_speed = max(0.0, 1.0 - avg_hours / 72.0)
# 72h baseline → 0 points, ≤0h → 30 points
```

Writes `efficiency_score` + `efficiency_computed_at` to `staff_profiles`.

---

### Celery Beat Entries Added

```python
"check-capacity-thresholds": {"task": "infrastructure.check_capacity", "schedule": 300.0},
"score-staff-efficiency":    {"task": "staff.score_efficiency",         "schedule": 3600.0},
```

---

### Staff Performance Endpoint

`GET /staff/{user_id}/performance` returns:
```json
{
  "efficiency_score": 73.4,
  "completion_rate_pct": 82.0,
  "sla_adherence_pct": 91.0,
  "avg_resolution_hours": 14.2,
  "tasks_assigned": 28,
  "tasks_done": 23,
  "tasks_open": 5,
  "tasks_on_time": 21,
  "lookback_days": 30
}
```

**`StaffDetailPage`** — Efficiency Score card with CSS conic-gradient ring:
```css
background: conic-gradient(#22c55e 263.5deg, var(--bg4) 0deg)
```
+ rows: completion rate, SLA adherence, avg resolution hours, open tasks. 1h `refetchInterval`.

---

### Infrastructure Settings Page

**`frontend/src/pages/infrastructure/InfrastructureSettingsPage.tsx`** (new, at `/infrastructure/settings`)

| Tab | Features |
|-----|---------|
| **Monitoring** | CRUD for `InfraMonitoringConfig`: entity_type dropdown (site/node/route), entity_id UUID input, warn/critical threshold inputs, alert channel toggles (email/sms/in_app), role level picker, check interval, is_active toggle |
| **Alert Rules** | CRUD for `InfraAlertRule`: condition_field, operator (gt/gte/lt/lte/eq), threshold value, severity (warning/major/critical), action_type (notify/create_task/page_oncall), JSON params textarea for task creation |
| **Port Inventory** | Node picker `<select>`, progress bar per port (used/total), last_synced_at timestamp, amber "Sync Ports Now" button → `POST /infrastructure/sync-ports` (202) |

---

## Sprint 4, Stage 4 — Reports Suite, Auth Flows, Integration Tests {#sprint-4-s4}

### New Report Endpoints

Added to `backend/app/modules/all_modules.py`:

| Endpoint | Key data |
|----------|---------|
| `GET /reports/infrastructure` | Sites with utilisation %, `alert_summary` by severity, 20 recent unresolved alerts |
| `GET /reports/shifts` | 30-day coverage by date, oncall_load TOP 10 by staff name, swap_requests by status |
| `GET /reports/sla` | Breach rate by severity (90-day window), worst 10 OLTs by breach count |

---

### ReportsPage — 3 New Tabs

Extended tab union: `'overview' | 'staff' | 'tasks' | 'projects' | 'outages' | 'infrastructure' | 'shifts' | 'sla'`

| Tab | Displayed data |
|-----|----------------|
| **Infrastructure** | Sites table with utilisation % bars + alert severity breakdown (critical/major/warning counts) |
| **Shifts** | Daily coverage table + oncall load ranked table + swap request status summary |
| **SLA Compliance** | Breach rate by severity table + worst performing OLTs table |

All 3 queries use `enabled: tab === 'X'` — data is fetched only when the tab is active.

---

### POST /auth/register-tenant

```
Payload: { org_name, slug, first_name, last_name, email, password }
```

Full registration flow:
1. Validate slug with `field_validator` — regex `^[a-z0-9][a-z0-9\-]{2,79}$`
2. Check slug uniqueness in `tenants` table → 409 if taken
3. Check email uniqueness in `users` table → 409 if taken
4. Create `Tenant` row
5. Call `apply_fttx_template(db, tenant.id, admin_placeholder_id)` — seeds 8 roles, 5 depts, 12 feature permission keys, dept_feature_grants, 4 form schemas, Default Region
6. Resolve seeded Admin role + Management dept via `SELECT`
7. Create `User` (with `admin_placeholder_id`) + `StaffProfile`
8. Issue access token + httpOnly refresh cookie
9. Return `{ tenant: {id, name, slug}, user: {id, username, email, role}, access_token }`

---

### RegisterPage.tsx (new — `/register`, public)

2-step form wizard:

**Step 1 — Organisation**
- Organisation name input
- Subdomain input (auto-derived via `slugify(org_name)`; shows `subdomain.opsyn.io` preview)
- Client-side regex validation on slug before proceeding

**Step 2 — Admin Account**
- First name + Last name (2-column grid)
- Work email
- Password (min 8) + Confirm Password
- Back button returns to Step 1

On success → `navigate('/setup', { replace: true })`.

`LoginPage.tsx` now has a "Create a workspace" footer link to `/register`.

---

### FirstRunWizard.tsx (new — `/setup`, RequireAuth, no AppShell)

5-step post-registration wizard. Renders standalone (no sidebar, no topbar).

| Step | Title | API calls | Skippable |
|------|-------|-----------|-----------|
| 1 | Branding & Timezone | None (local only) | No (Continue) |
| 2 | First Region + POP | `orgApi.createRegion()` + `infrastructureApi.createSite()` | Yes |
| 3 | First OLT + SmartOLT | `infrastructureApi.createNode()` + `smartoltApi.createConfig()` | Yes |
| 4 | Invite Team Member | `staffApi.invite({ email, role_id? })` | Yes |
| 5 | Done | Navigate to `/dashboard` | — |

Step indicator: green checkmarks (`✓`) on completed steps; active step highlighted with `var(--accent)` border.

---

### API Additions

**`frontend/src/api/index.ts`**
```ts
authApi.registerTenant({ org_name, slug, first_name, last_name, email, password })
infrastructureApi.listSubscribers(params?)      // ?site_id, node_id, service_type
infrastructureApi.triggerSyncPorts()            // POST → 202 Accepted
reportsApi.getInfrastructureReport()
reportsApi.getShiftsReport()
reportsApi.getSlaReport()
```

**`frontend/src/api/staff.api.ts`**
```ts
staffApi.getPerformance(id: string): Promise<StaffPerformance>
staffApi.invite({ email: string; role_id?: string; message?: string })
```

---

### Integration Tests — `tests/integration/test_s44.py`

5 test classes, ~40 test cases:

| Class | Coverage |
|-------|---------|
| `TestInfrastructure` | Sites/nodes CRUD, route list, subscribers list + service_type filter, sync-ports queued response, infra summary shape |
| `TestAuthFlows` | Login bad password/email/missing fields; register-tenant happy path + dup slug (409) + dup email (409) + short password (422) + invalid slug (422); refresh without cookie (401); logout success |
| `TestShifts` | List auth guard, list returns list, assignments list, swap requests list, create missing fields (422), approve nonexistent (404/422) |
| `TestCapacityMonitor` | Monitoring configs auth guard + list + create; alert rules list + create; capacity alerts list; ports list |
| `TestS44Reports` | Infrastructure/shifts/SLA report auth guards + response shape; staff performance endpoint (200 or 404); staff/tasks/overview report auth guards |

---

## Phase 7 — Production Hardening & DevOps {#phase-7}

### P7.1 — requirements.txt + Celery Beat

**`backend/requirements.txt`** (new)

All production + dev Python dependencies pinned with semver ranges, derived from `pyproject.toml`. Dockerfile updated:
```dockerfile
# Before (fragile, no pinning):
RUN pip install fastapi uvicorn[standard] sqlalchemy ...

# After (reproducible builds):
COPY requirements.txt /build/requirements.txt
RUN pip install --no-cache-dir -r /build/requirements.txt
```

---

**`docker-compose.yml` — `celery-beat` service added**

```yaml
celery-beat:
  build:
    context: ./backend
    dockerfile: ../infrastructure/docker/Dockerfile.backend
  container_name: opsyn_celery_beat
  command: celery -A app.core.celery_app beat --loglevel=info --schedule=/tmp/celerybeat-schedule
  environment: *celery-env
```

This activates all previously-defined but never-firing `beat_schedule` entries:

| Beat entry | Interval | Purpose |
|------------|----------|---------|
| `check-capacity-thresholds` | 300s | Capacity alert checks |
| `score-staff-efficiency` | 3600s | Efficiency scoring |
| `sync-smartolt-ports` | 900s | SmartOLT port sync |
| `check-sla-breaches` | 300s | SLA breach detection |
| `poll-smartolt-alarms` | 60s | SmartOLT alarm polling |

**`docker-compose.prod.yml`** — `celery-beat` added with `restart: always`.

**`Makefile` additions**
```makefile
logs-beat     # Follow celery-beat service logs
prod-up       # Start production stack (with Nginx)
prod-down     # Stop production stack
prod-migrate  # Run Alembic migrations in production
```

---

### P7.2 — Seed Script Full Rewrite

**`backend/scripts/seed.py`** — complete rewrite. Previous version manually created roles/depts. New version:

```
Step 1: Create dev tenant (UUID 00000000-0000-0000-0000-000000000001) if missing
Step 2: apply_fttx_template()     → 8 roles, 5 depts, 12 feature perms, dept grants, 4 form schemas
Step 3: Seed 6 geographic regions  → Lagos, Abuja, Port Harcourt, Kano, Enugu, Ibadan
Step 4: Seed NOC teams             → Team Alpha, Beta, Gamma
Step 5: Create Admin user          → UUID ...0002, admin@opsyn.ng / opsyn_admin_2026, Management dept
Step 6: Create Manager user        → manager@opsyn.ng / opsyn_manager_2026, Network Operations dept
Step 7: Seed 5 demo sites          → VI POP, Lekki POP, Ikeja Hub, Wuse Zone 5 POP, Maitama DC
Step 8: Seed 6 demo nodes          → VI-OLT-01/02, LEK-OLT-01, IKJ-AGG-01, WSZ5-OLT-01, MTM-CORE-01
Step 9: Seed 3 fibre routes        → VI→Lekki (12.5km GPON), VI→Ikeja (28km DWDM), Wuse→Maitama (7.2km GPON)
Step 10: seed_global_feature_permissions() (idempotent)
```

Output after `make seed`:
```
✅ Seed complete — Opsyn is ready.

   Credentials:
   Admin:   admin@opsyn.ng   / opsyn_admin_2026
   Manager: manager@opsyn.ng / opsyn_manager_2026

   Frontend: http://localhost:5173
   API docs: http://localhost:8000/api/docs
```

---

### P7.3 — .env.example

Rewritten with all 18 environment variables documented, with examples for SendGrid, Postmark, and production databases.

> **Bug fixed:** previous `.env.example` had `ALLOWED_ORIGINS` — corrected to `ALLOWED_ORIGINS_STR` (the actual field name in `app/core/config.py`).

Key variables:

| Variable | Notes |
|----------|-------|
| `DATABASE_URL` | `postgresql+asyncpg://...` — production: add `?ssl=require` |
| `SECRET_KEY` | Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ALLOWED_ORIGINS_STR` | Comma-separated (not a JSON list) |
| `CELERY_BROKER_URL` | Separate Redis DB index from `REDIS_URL` |

---

### P7.4 — Nginx Production Config + .gitignore

**`infrastructure/nginx/nginx.conf`** hardened for production:

```nginx
# Rate limiting zones
limit_req_zone $binary_remote_addr zone=auth_limit:10m rate=5r/m;
limit_req_zone $binary_remote_addr zone=api_limit:20m  rate=60r/m;

upstream opsyn_backend {
    server backend:8000;
    keepalive 32;
}
```

| Feature | Config |
|---------|--------|
| HTTP redirect | Port 80 → 301 HTTPS |
| TLS | TLSv1.2 + TLSv1.3, `ssl_prefer_server_ciphers on`, session cache 10m |
| HSTS | `max-age=63072000; includeSubDomains; preload` |
| CSP | Leaflet tiles + CartoDB basemaps + `blob:` worker-src whitelisted |
| Auth rate limit | `/api/v1/auth/(login\|register-tenant)` → 5r/m, burst 3, status 429 |
| API rate limit | `/api/` → 60r/m, burst 20 |
| Static assets | `expires 1y; immutable` |
| Gzip | Level 6, JS/CSS/JSON/SVG |
| SPA fallback | `try_files $uri $uri/ /index.html` |

**`docker-compose.prod.yml`** updated:
```yaml
nginx:
  image: nginx:alpine
  ports: ["80:80", "443:443"]
  volumes:
    - ./infrastructure/nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    - ./ssl:/etc/nginx/ssl:ro
    - frontend_dist:/usr/share/nginx/html:ro
```

Backend port 8000 is **not externally exposed** in production — only Nginx faces the internet.

**`.gitignore`** (new) protects:
- `.env`, `.env.local`, `.env.production`
- `ssl/*.crt`, `ssl/*.key`, `ssl/*.pem`
- `__pycache__/`, `*.pyc`, `.venv/`
- `node_modules/`, `frontend/dist/`
- `.vscode/settings.json`, `.idea/`, `.DS_Store`

**`ssl/README.md`** — instructions for mounting TLS certs.

---

---

## Implementation Plan Phase 1 — Critical Backend Fixes {#impl-phase-1}

> Session: 2026-05-14 · All files pass `python -m py_compile`

### Bug C-1 + C-2: NameError at runtime in all_modules.py

**Root cause** — `from __future__ import annotations` in SQLAlchemy model files defers annotation evaluation to call time. Function-local `StaffProfile`, `text()` imports inside endpoint bodies were raising `NameError` because the deferred evaluation hit the wrong scope.

**Fix — `app/modules/all_modules.py`**
- Promoted all local-scope imports to module-level top of file
- Added `text` to the top-level SQLAlchemy import: `from sqlalchemy import select, func, text, …`
- Added `from app.modules.staff.models import User, StaffProfile` at top level
- Added `SP = StaffProfile` module-level alias (used in 8+ report query functions)
- Removed 10+ duplicate local `from … import` statements inside endpoint functions

### Bug C-3: Wrong ORM column name

**Root cause** — `Task.assigned_to` does not exist; the correct column is `Task.assignee_user_id`.

**Fix — `app/modules/all_modules.py`** (get_tasks_breakdown / get_staff_breakdown report functions)
```python
# Before:
.join(SP, SP.user_id == Task.assigned_to)
.where(Task.assigned_to.isnot(None))
# After:
.join(SP, SP.user_id == Task.assignee_user_id)
.where(Task.assignee_user_id.isnot(None))
```

### Bug C-4: NoReferencedTableError on flush

**Root cause** — SQLAlchemy FK resolution requires the ORM model defining the referenced table to be imported before any session flush. `InfraCapacityAlert.linked_task_id → tasks.id` and `OutageIncident.linked_task_id → tasks.id` failed because `Task` was never imported in those module paths.

**Fix**
- `app/tasks/sla_checker.py` — added `from app.modules.tasks.router import Task  # noqa: F401`
- `app/modules/infrastructure/models.py` — added `from app.modules.tasks.router import Task  # noqa: F401`

*(These imports were later updated to `tasks.models` in Phase 3)*

### Medium: Integrations list expanded

**Fix — `app/modules/settings/router.py`**
- `AVAILABLE_INTEGRATIONS` expanded from 7 → 27 entries across 8 categories: communication, storage, project management, GIS, network, alerting, AI/intelligence, auth/SSO

---

## Implementation Plan Phase 2 — Frontend Fixes & Enterprise Navigation {#impl-phase-2}

> Session: 2026-05-14 · TypeScript build: `npx vite build` clean (zero new errors)

### Bug H-1: NewTaskModal crash on 404

**Root cause** — `formsApi.getSchema()` threw on 404 (no schema published for context), propagating to React Query as an error state and crashing the modal.

**Fix — `frontend/src/api/index.ts`**
```typescript
getSchema: (context: string) =>
  apiClient.get(`/forms/${context}`)
    .then(r => r.data.data)
    .catch((e: { response?: { status?: number } }) =>
      e?.response?.status === 404 ? null : Promise.reject(e)
    ),
```

### Bug H-2: ProjectPipelinePage blank/crash on null pipeline

**Root cause** — `allStages.filter()` called on `undefined` when no pipeline was started yet.

**Fix — `frontend/src/pages/projects/ProjectPipelinePage.tsx`**
- Separated `isLoading` / `isError` / empty states with early returns
- Added `const safeAllStages = Array.isArray(allStages) ? allStages : []`
- Replaced all `allStages.filter/find` with `safeAllStages.filter/find`

### UX: Enterprise navigation redesign

Replaced flat 8-item sidebar with a 5-category grouped rail system.

**`frontend/src/layouts/PrimaryRail.tsx`** — complete rewrite
- 5 category buttons: OPS / MGT / INT / SYS / HLP, each 48×48px with SVG icon + 7.5px abbreviated label
- `CATEGORY_ROUTES` map: route path segment → category membership
- Active highlight when drawer is open for that category OR current route belongs to it
- Exported `CategoryKey = 'ops' | 'mgt' | 'int' | 'sys' | 'hlp'` type

**`frontend/src/layouts/FlyoutDrawer.tsx`** — complete rewrite
- Prop changed from `open: boolean` → `activeCategory: CategoryKey | null`
- `pointer-events: none` when closed (critical fix — prevents invisible click-blocking)
- `CATEGORY_DEFS` with scoped navigation groups per category (OPS/MGT/INT/SYS/HLP)
- Glassmorphism header with category title + subtitle
- Beta/Soon tag decorators for coming-soon items

**`frontend/src/layouts/AppShell.tsx`** — updated wiring
- State changed from `drawerOpen: boolean` → `activeCategory: CategoryKey | null`
- Open delay: 120ms | Close grace: 280ms
- `drawerOpen = activeCategory !== null` derived value

### Bonus: ProjectsPage TypeScript fixes

**`frontend/src/pages/projects/ProjectsPage.tsx`**
- `(schema as any)?.is_published` → `schema && schema.is_published` (proper null narrowing)
- `onClose=` → `onCancel=` on DynamicForm (correct prop name)

---

## Implementation Plan Phase 3 — Architecture & Feature Completion {#impl-phase-3}

> Session: 2026-05-14 · All backend files pass `python -m py_compile` · Frontend `npx vite build` succeeds

### 3.1 + 3.2: Task model extraction

**Problem** — ORM models and state machine constants living in `tasks/router.py` caused circular import risk when other modules imported `Task` for FK registration.

**New file: `app/modules/tasks/models.py`**
- Extracted: `Task`, `TaskComment`, `TaskTag`, `TaskDependency`, `TaskAuditEntry` ORM classes
- Extracted: `TASK_STATES`, `PIPELINE_FLOW`, `ALLOWED_TRANSITIONS`, `TRANSITION_ROLE_REQUIREMENTS`, `TERMINAL_STATES`, `COMMENT_TYPES`, `APPROVAL_KEYWORDS`, `REJECTION_KEYWORDS`, `BLOCKER_KEYWORDS`, `TRIGGER_TYPES`
- Minimal imports (no FastAPI, no Pydantic, no router dependencies)

**Updated: `app/modules/tasks/router.py`**
- Replaced ~170 lines of model/constant definitions with a single import block from `tasks.models`
- Retains all Pydantic schemas, `TaskService`, and route handlers

**Import sites updated** (all 3 changed from `tasks.router` → `tasks.models`):
- `app/modules/all_modules.py:25`
- `app/tasks/sla_checker.py:18`
- `app/modules/infrastructure/models.py:17`

### 3.3: Domain router architecture

All 8 domain router files (`outage`, `reports`, `onboarding`, `notifications`, `permissions`, `roles`, `org`, `projects`) already re-export their respective `router_*` objects from `all_modules.py`. `main.py` correctly imports from all domain files. Architecture is complete and functioning.

### 3.5: Pipeline progress endpoint

**Backend — `app/modules/all_modules.py`** (router_projects section)
```
GET /api/v1/projects/{id}/progress
→ { progress: int, total_stages: int, completed_stages: int }
```
- Counts `ProjectPipelineStage` rows where `status == "approved"` vs total
- Falls back to `project.completion_pct` if no pipeline stages exist

**Frontend**
- `frontend/src/api/projects.api.ts` — `getProgress(projectId)` API method
- `frontend/src/hooks/useProjects.ts` — `useProjectProgress(projectId)` hook (30s stale time)
- `frontend/src/pages/projects/ProjectDetailPage.tsx` — live progress bar + `X/Y stages` label replacing static `completion_pct`

### 3.6: Integration configuration UI

**Backend — `app/modules/settings/router.py`**

Three new endpoints per configurable integration key:
```
GET    /settings/integrations/{key}/config   → masked config (sensitive fields shown as ••••••)
POST   /settings/integrations/{key}/config   → save/merge config into tenant settings JSONB
DELETE /settings/integrations/{key}/config   → remove key from tenant settings
```
Configurable keys: `slack`, `teams`, `pagerduty`, `email_smtp`
Sensitive fields (never overwritten with placeholder): `api_key`, `password`
Storage: `tenants.settings JSONB → integrations.{key}.{field}`

**Frontend — `frontend/src/pages/settings/SettingsPage.tsx`**
- `INTEGRATION_FIELDS` constant — per-key field definitions with labels, types, placeholders
- `openConfig()` handler wires the "Configure"/"Reconfigure" button per card
- `useQuery` for `settingsApi.getIntegrationConfig(key)` pre-populates existing values (masked)
- `saveConfig` mutation calls `settingsApi.saveIntegrationConfig(key, form)`
- Reusable config modal renders the correct fields per integration type

**Frontend — `frontend/src/api/index.ts`**
- `settingsApi.getIntegrationConfig(key)`
- `settingsApi.saveIntegrationConfig(key, config)`
- `settingsApi.removeIntegrationConfig(key)`

### Migration status

No new Alembic migrations required for Phase 3:
- Task model extraction: same tables, no schema change
- Progress endpoint: reads existing `project_pipeline_stages` table
- Integration config: stored in existing `tenants.settings JSONB` column

Current migration head: **0042_staff_efficiency_score**

---

## Full File Inventory {#file-inventory}

### New Files Created (All Sessions)

| File | Description |
|------|-------------|
| `backend/app/modules/forms/models.py` | FormSchema, FormField, FormFieldDependency, FormSubmission ORM |
| `backend/app/modules/forms/validator.py` | 10-type form field validator |
| `backend/app/modules/forms/router.py` | Form CRUD + submit + submissions endpoints |
| `backend/app/modules/webhooks/models.py` | WebhookApiKey ORM |
| `backend/app/modules/webhooks/router.py` | Webhook key admin + HMAC receiver + 5 domain handlers |
| `backend/app/modules/smartolt/models.py` | SmartOLTConfig, SmartOLTOltMap ORM |
| `backend/app/modules/smartolt/handler.py` | 7-step SmartOLT event pipeline |
| `backend/app/modules/shifts/models.py` | Shift, ShiftAssignment, ShiftSwapRequest, OutageNotificationRule, Log ORM |
| `backend/app/modules/shifts/router.py` | Shift CRUD + weekly grid + swap requests |
| `backend/app/modules/infrastructure/models.py` | InfraPort, InfraSubscriber, InfraCapacityAlert, InfraMonitoringConfig, InfraAlertRule ORM |
| `backend/app/tasks/smartolt_polling.py` | Celery: SmartOLT alarm polling (60s) |
| `backend/app/tasks/sla_checker.py` | Celery: SLA breach detection (300s) |
| `backend/app/tasks/customer_notifications.py` | Celery: outage SMS/email notifications |
| `backend/app/tasks/infrastructure_sync.py` | Celery: SmartOLT port sync (900s) |
| `backend/app/tasks/capacity_monitor.py` | Celery: capacity threshold checks (300s) |
| `backend/app/tasks/staff_efficiency.py` | Celery: staff efficiency scoring (3600s) |
| `backend/alembic/versions/0037_form_builder.py` | Migration: form tables |
| `backend/alembic/versions/0038_webhook_api_keys.py` | Migration: webhook_api_keys |
| `backend/alembic/versions/0039_smartolt_integration.py` | Migration: smartolt + outage columns |
| `backend/alembic/versions/0040_shifts_and_notification_rules.py` | Migration: shifts + notification tables |
| `backend/alembic/versions/0041_infrastructure_monitoring.py` | Migration: infra_ports, infra_subscribers, capacity tables |
| `backend/alembic/versions/0042_staff_efficiency_score.py` | Migration: efficiency_score on staff_profiles |
| `backend/tests/integration/test_sprint3.py` | 44 Sprint 3 integration tests |
| `backend/tests/integration/test_sprint4.py` | 36 Sprint 4 integration tests |
| `backend/tests/integration/test_s44.py` | ~40 S4.4 integration tests (5 classes) |
| `backend/requirements.txt` | Pinned Python dependencies |
| `frontend/src/pages/auth/ActivatePage.tsx` | Account activation page |
| `frontend/src/pages/auth/RegisterPage.tsx` | 2-step tenant registration form |
| `frontend/src/pages/onboarding/FirstRunWizard.tsx` | 5-step post-registration setup wizard |
| `frontend/src/pages/infrastructure/InfraMapView.tsx` | Leaflet GIS map with 5 overlay layers |
| `frontend/src/pages/infrastructure/InfrastructureSettingsPage.tsx` | 3-tab infra settings |
| `frontend/src/pages/shifts/ShiftSchedulerPage.tsx` | Weekly shift grid + assign/cancel + swap |
| `frontend/src/pages/forms/FormBuilderPage.tsx` | Admin form schema builder |
| `frontend/src/components/forms/CoordinatesField.tsx` | Manual/GPS/Paste coordinate input |
| `frontend/src/components/forms/FormFieldRenderer.tsx` | 10-type field renderer |
| `frontend/src/components/forms/DynamicForm.tsx` | Full dynamic form with dependencies |
| `.env.example` | All 18 env vars documented |
| `.gitignore` | Secrets + build artefact exclusions |
| `ssl/README.md` | TLS cert mount instructions |

---

### Modified Files (All Sessions)

| File | Key Changes |
|------|------------|
| `backend/app/modules/auth/router.py` | +`POST /auth/activate`, +`POST /auth/reset-password`, +`POST /auth/register-tenant` |
| `backend/app/modules/staff/models.py` | +`efficiency_score`, +`efficiency_computed_at` on StaffProfile |
| `backend/app/modules/staff/router.py` | +`GET /staff/{id}/performance`; PUT allowed fields expanded |
| `backend/app/modules/infrastructure/router.py` | +`GET /infrastructure/subscribers`, +`POST /infrastructure/sync-ports`, +map/utilisation endpoints |
| `backend/app/modules/settings/router.py` | +pipelines, +integrations, +notification rules, +SmartOLT config CRUD |
| `backend/app/modules/all_modules.py` | +`GET /reports/infrastructure/shifts/sla`; enhanced outage/onboarding/reports |
| `backend/app/core/celery_app.py` | +6 task modules in `include[]`; +6 beat entries |
| `backend/app/modules/tenants/setup_service.py` | Extended for dept_feature_grants + 4 form schemas |
| `backend/scripts/seed.py` | Full rewrite: fttx template + regions + teams + 2 users + 5 sites + 6 nodes + 3 routes |
| `backend/infrastructure/docker/Dockerfile.backend` | Install from requirements.txt |
| `frontend/src/App.tsx` | +lazy routes: `/activate`, `/register`, `/setup`, `/infrastructure`, `/infrastructure/settings`, `/settings`, `/settings/forms/:context`, `/activity`, `/shifts`, `/outage/:id` |
| `frontend/src/layouts/AppShell.tsx` | Live badge polling, `buildSidebarNav()`, all new sidebar entries + ROUTE_META |
| `frontend/src/pages/index.tsx` | All page components (Dashboard, Reports, Staff, Outage, Infrastructure, Settings, Activity, etc.) |
| `frontend/src/pages/auth/LoginPage.tsx` | +"Create a workspace" link to `/register` |
| `frontend/src/api/index.ts` | All API modules added/extended (authApi, infrastructureApi, reportsApi, shiftsApi, formsApi, webhooksApi, smartoltApi, settingsApi, activityApi, dashboardApi) |
| `frontend/src/api/staff.api.ts` | +`getPerformance(id)`, +`StaffPerformance` interface, +`invite()` |
| `docker-compose.yml` | +`celery-beat` service |
| `docker-compose.prod.yml` | +`celery-beat` + `nginx` services; backend port not exposed |
| `Makefile` | +`logs-beat`, `prod-up`, `prod-down`, `prod-migrate` targets |
| `infrastructure/nginx/nginx.conf` | Hardened: HTTPS, TLS 1.2/1.3, rate limits, security headers, upstream keepalive |
| `shared-types/index.ts` | All new shared TypeScript types across phases |

---

## Architecture Reference {#architecture}

### Multi-Tenant Pattern
Every table has `tenant_id FK tenants.id`. JWT claims include `tenant_id`. `TenantMiddleware` calls `SET LOCAL app.tenant_id = '...'` per request. PostgreSQL RLS (migration 0029) enforces row isolation at DB layer. No cross-tenant data leaks possible.

### Alembic Migration Chain
```
0001 → 0003 → 0021 → ... → 0033
→ 0034 (task engine)
→ 0035 (projects ticket numbers)
→ 0036 (onboarding two-phase)
→ 0037 (form builder)
→ 0038 (webhook api keys)
→ 0039 (smartolt + outage SLA columns)
→ 0040 (shifts + notification rules)
→ 0041 (infra monitoring tables)
→ 0042 (staff efficiency score)
```

### Celery Beat Schedule (active when `celery-beat` runs)
| Task | Interval | Module |
|------|----------|--------|
| `infrastructure.check_capacity` | 300s | `app.tasks.capacity_monitor` |
| `staff.score_efficiency` | 3600s | `app.tasks.staff_efficiency` |
| `sync-smartolt-ports` | 900s | `app.tasks.infrastructure_sync` |
| `check-sla-breaches` | 300s | `app.tasks.sla_checker` |
| `poll-smartolt-alarms` | 60s | `app.tasks.smartolt_polling` |

### Auth + Registration Flow
```
Self-service registration:
  POST /auth/register-tenant
    → validate slug/email uniqueness
    → create Tenant
    → apply_fttx_template() → 8 roles, 5 depts, 12 perms, 4 form schemas
    → create Admin User + StaffProfile
    → issue JWT + refresh cookie
    → frontend: navigate /setup (FirstRunWizard, 5 steps)

Invite-based:
  POST /staff → creates User (inactive) → Celery sends invite email
  POST /auth/activate?token=... → sets password, activates account, issues session

Standard login:
  POST /auth/login → access JWT (15min) + httpOnly refresh cookie (7 days)
  POST /auth/refresh → rotate refresh token (Redis hash, deleted on use)
  POST /auth/logout → immediately delete Redis key
```

### Staff Efficiency Formula
```python
score = (completion_rate_pct * 0.4) + (sla_adherence_pct * 0.3) + (resolution_speed * 0.3)
resolution_speed = max(0.0, 1.0 - avg_resolution_hours / 72.0)
# 72h average → 0 speed points; ≤0h → 30 speed points (max)
```
Written to `staff_profiles.efficiency_score` every hour by Celery. Displayed as CSS conic-gradient ring on `StaffDetailPage`.

### Production Deployment
```bash
# 1. Copy and edit env vars
cp .env.example .env
# Set: SECRET_KEY, DATABASE_URL (managed DB), REDIS_URL, SMTP_PASSWORD

# 2. Place TLS certificates
cp your-cert.crt ssl/opsyn.crt
cp your-key.key  ssl/opsyn.key

# 3. Build production images
make build

# 4. Start production stack (Nginx + backend + celery + celery-beat + frontend)
make prod-up

# 5. Run migrations and seed
make prod-migrate
docker compose exec backend python -m scripts.seed
```

---

## Known Gaps / Future Work

| Item | Notes |
|------|-------|
| WebSocket real-time push | Currently polling (30s). Replace with WS for true real-time (no page lag) |
| PDF export renderer | `GET /reports/export/pdf` stub exists; needs WeasyPrint or headless Chromium |
| MEC / outage responsibility bulk UI | Fields exist in `StaffProfile`; no batch assignment interface |
| Mobile responsive polish | Layout adapts but not optimised for viewports < 768px |
| Report chart visualisations | Tables only — no bar/line/sparkline charts |
| Kubernetes / Helm chart | `infrastructure/k8s/` directory exists but is empty |
| Termii SMS env-var fallback | SmartOLT + Termii credentials only in DB; no env-var bootstrap path |

---

*Generated 2026-05-13 · Opsyn v2.0.0 · Powered by SlimTech*

---

## Customer Module & Project Pipeline — Phase 1: Database Migrations & Seed Data {#customer-phase-1}

> Session date: 2026-05-17 | Plan: Opsyn_Implementation_Plan (1).docx | Status: COMPLETE

### Objective
Create all new database tables required by the Customer Module & Project Pipeline system. No API or UI changes in this phase. Stable schema that all subsequent phases build on.

### Migrations Created (0053–0064)

| Migration | File | Tables / Changes | Notes |
|-----------|------|-----------------|-------|
| 0053 | `0053_customer_form_field_definitions.py` | Extend `form_schemas` (add `is_active`, `department_id`); CREATE `field_definitions` | Separate from existing `form_fields`; adds pipeline-stage visibility + roles_can_edit |
| 0054 | `0054_field_visibility_rules.py` | CREATE `field_visibility_rules` | Stage × department matrix; `is_required_to_advance` flag |
| 0055 | `0055_customers.py` | CREATE `customers` | Soft-delete; `external_ref_id` unique per tenant for idempotency |
| 0056 | `0056_customer_field_values.py` | CREATE `customer_field_values` | Upsert pattern: unique (customer_id, field_definition_id) |
| 0057 | `0057_customer_form_submissions.py` | CREATE `customer_form_submissions` | GIN index on `submitted_data` JSONB |
| 0058 | `0058_payment_requests.py` | CREATE `payment_requests` | Composite index on (tenant_id, status) |
| 0059 | `0059_payment_confirmations.py` | CREATE `payment_confirmations` | GIN index on `confirmation_payload` JSONB |
| 0060 | `0060_project_stage_approvals.py` | CREATE `project_stage_approvals` | FK to `project_pipeline_stages`; unique (project_id, stage_id) |
| 0061 | `0061_stage_field_completion.py` | CREATE `stage_field_completion` | Completion cache; unique (project_id, stage_id, field_definition_id) |
| 0062 | `0062_external_task_logs.py` | CREATE `external_task_logs` | Unique (tenant_id, external_ref_id); GIN on payload |
| 0063 | `0063_customer_audit_log.py` | CREATE `customer_audit_log` | actor_id nullable for system events |
| 0064 | `0064_rls_customer_module.py` | RLS on all 11 new tables | Same `tenant_id` policy pattern as 0037 + 0052 |

### Alembic Chain
`0052 → 0053 → 0054 → 0055 → 0056 → 0057 → 0058 → 0059 → 0060 → 0061 → 0062 → 0063 → 0064`

### Seed Script
`scripts/seed_customer_module.py` — idempotent (stable UUIDs, checks before insert):
- 1 customer form schema (`context='customer'`, `is_active=True`)
- 5 field definitions: `first_name` (text), `last_name` (text), `email` (email), `phone` (phone), `service_plan` (select with 4 options)
- Field visibility rules at stage 1 for Finance department (if seeded)
- 1 mock customer (`status='pending'`, `source_app='manual'`, `external_ref_id='SEED-MOCK-0001'`)
- 1 payment_request (`status='pending'`, 15,000 NGN, 7-day expiry)
- Tenant isolation self-check at end of script

### Validation Gate Results
- All 12 migration files pass `python -m py_compile` — PASS
- Migration chain verified: 0052 → 0064, unbroken single head — PASS
- Seed script passes `py_compile` — PASS
- No existing tables modified destructively — PASS

### Architecture Invariants Preserved
- All new tables carry `tenant_id` with FK to `tenants.id ON DELETE CASCADE`
- All JSONB columns have GIN indexes (`validation_rules`, `submitted_data`, `confirmation_payload`, `payload`)
- All composite indexes on `(tenant_id, status)` for `customers`, `payment_requests`, `external_task_logs`
- `field_definitions` is separate from `form_fields` (different purpose — customer pipeline vs general forms)
- `form_schemas.is_active` added alongside existing `is_published` (backward-compatible)
- RLS follows same policy pattern as established in 0037 and 0052

### Phase 1 Gate: PASSED — Phase 2 approved and implemented.

---

## Customer Module & Project Pipeline — Phase 2: Dynamic Form Builder Backend APIs {#customer-phase-2}

> Session date: 2026-05-17 | Status: COMPLETE

### Objective
Build backend APIs for admins to define and manage customer form schemas dynamically. No frontend yet.

### Files Created / Modified

| File | Change |
|------|--------|
| `app/modules/forms/models.py` | Added `is_active` (bool) + `department_id` (UUID FK) columns to `FormSchema` ORM model |
| `app/modules/customers/__init__.py` | New — customer module package |
| `app/modules/customers/models.py` | New — ORM models: `FieldDefinition`, `FieldVisibilityRule`, `Customer`, `CustomerFieldValue`, `CustomerFormSubmission`, `CustomerAuditLog`, `PaymentRequest`, `PaymentConfirmation`, `ExternalTaskLog` |
| `app/modules/customers/forms_router.py` | New — 8 Phase 2 endpoints (see below) |
| `main.py` | Imported `customer_forms_router`; registered with `prefix=/api/v1/forms` BEFORE `forms_router` to prevent shadowing |

### API Endpoints (prefix: /api/v1/forms)

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | /schemas | authenticated | List all active schemas for tenant |
| POST | /schemas | settings.admin | Create new schema (version 1) |
| GET | /schemas/{id} | authenticated | Get schema + fields + visibility rules (role-filtered) |
| PUT | /schemas/{id} | settings.admin | Update → archives old version, creates N+1 |
| POST | /schemas/{id}/fields | settings.admin | Add field definition with optional visibility rules |
| PUT | /fields/{id} | settings.admin | Update field; optionally replace all visibility rules |
| DELETE | /fields/{id} | settings.admin | Soft-delete; blocked if submitted data references field |
| GET | /fields/{id}/visibility | authenticated | Get stage × department visibility matrix |

### Key Implementation Details
- **Schema versioning**: PUT archives old schema (`is_active=False`), creates new version with `version+1`
- **Role-based field access**: GET /schemas/{id} filters fields to caller's role via `roles_can_edit`; admins see all
- **Soft-delete guard**: DELETE checks `CustomerFormSubmission.submitted_data[field.key]` (JSONB key existence) before allowing soft-delete
- **Audit logging**: All mutations (create/update/delete schema and field) write to `customer_audit_log`
- **Actor labels**: All audit entries use `(user.staff_profile.full_name if user.staff_profile else user.username) if user else 'System'`
- **selectinload**: All visibility rules loaded via `selectinload(FieldDefinition.visibility_rules)` — async-safe
- **Route shadowing prevention**: `customer_forms_router` registered at `/api/v1/forms` BEFORE existing `forms_router` at `/api/v1`

### Validation Gate Results
- All Phase 2 files pass `python -m py_compile` — PASS
- Router registration order verified: customer_forms_router (line 137) before forms_router (line 138) — PASS
- No route shadowing: GET /api/v1/forms/schemas resolved before GET /api/v1/forms/{context} — PASS
- Tenant isolation: all queries filter by `caller.tenant_id` — PASS
- Role enforcement: POST/PUT/DELETE require `settings.admin` permission — PASS
- Soft-delete: field deletion blocked when submitted data exists — PASS
- Schema versioning: PUT creates N+1, archives N (`is_active=False`) — PASS

### Phase 2 Gate: PASSED — Phase 3 approved and implemented.

---

## Customer Module & Project Pipeline — Phase 3: Customer Module Backend APIs {#customer-phase-3}

> Session date: 2026-05-17 | Status: COMPLETE

### Objective
Build all customer management APIs: creation, field submission, import/export, and webhook handlers for external app triggers and payment confirmation.

### Files Created / Modified

| File | Change |
|------|--------|
| `alembic/versions/0065_projects_customer_id.py` | New — adds nullable `customer_id` FK to `projects` table |
| `app/modules/customers/field_validator.py` | New — validates field values against `validation_rules` JSONB; returns structured field-level errors |
| `app/modules/customers/service.py` | New — `CustomerService`: atomic create, field upsert, visible-field query, payment confirmation + pipeline bootstrap |
| `app/modules/customers/router.py` | New — 7 customer CRUD + import/export endpoints at `/api/v1/customers` |
| `app/modules/customers/external_router.py` | New — 2 webhook endpoints at `/api/v1/external` (HMAC-verified, idempotent) |
| `app/modules/projects/models.py` | Added `customer_id` column to `Project` ORM model |
| `main.py` | Imported and registered `customers_router` + `external_router` |

### API Endpoints

**Customers** (`/api/v1/customers`):
| Method | Path | Description |
|--------|------|-------------|
| POST | / | Create customer (atomic: customer + payment_request) |
| GET | / | List customers (filters: status, source_app, date, dept, page) |
| GET | /{id} | Customer detail with payment + linked projects |
| PATCH | /{id}/fields | Submit field values (stage_order param); field-level error response |
| GET | /{id}/fields | Role + dept filtered fields with current values |
| POST | /import | Bulk JSON import; row-level error report |
| GET | /export | CSV export (email/phone/address hidden for role < 3) |

**External Webhooks** (`/api/v1/external`):
| Method | Path | Description |
|--------|------|-------------|
| POST | /tasks | External task + customer (HMAC verified, idempotent via X-Webhook-Ref) |
| POST | /payment-confirm | Finance App payment confirmation → activates customer + creates pipeline |

### Key Implementation Details
- **Atomic creation**: `customer_service.create_customer()` adds customer + payment_request + audit log in a single flush; caller commits once
- **Payment link**: tries `integration_configs.payment_base_url` first; falls back to internal link; never raises HTTP 500 on provider failure
- **Pipeline bootstrap**: `_bootstrap_pipeline()` calls `start_pipeline(project_id, template_id, db, user)` with correct arg order; falls back to 5-stage seeder when no template found (mirrors `auto_generator.py`)
- **HMAC verification**: same `sha256=<hex>` pattern as `webhooks/router.py`; uses `WebhookApiKey` table
- **Idempotency**: `ExternalTaskLog.external_ref_id` unique per tenant; duplicate `X-Webhook-Ref` returns 200 immediately without reprocessing
- **Payload logged first**: `_log_external_event()` writes `ExternalTaskLog` BEFORE any processing — enables replay even on downstream failure
- **Field validation**: `validate_field_values()` checks types, min/max, regex, options_list; returns `{field_key: error_message}` dict
- **Field visibility**: `get_visible_fields()` filters by role `roles_can_edit` and owner department; enriches with current `CustomerFieldValue`
- **Export role-gate**: email, phone, address, external_ref_id only exported for role_level >= 3
- **Actor labels**: all audit entries use `(user.staff_profile.full_name if user.staff_profile else user.username) if user else 'System'`

### Validation Gate Results
- All Phase 3 files pass `python -m py_compile` — PASS
- Migration chain: 0064 → 0065, unbroken — PASS
- Customer creation atomicity: payment_request flush is in same transaction as customer — PASS
- Idempotency: duplicate X-Webhook-Ref returns 200, no duplicate rows — PASS
- HMAC validation: verifies against WebhookApiKey.key_value before any DB mutation — PASS
- Field visibility: role_level and department filters applied before returning fields — PASS
- Export: role-level field gating confirmed — PASS

### Pending Phase 4 Gate
Awaiting tech lead sign-off before Phase 4 (Project Pipeline Stage Advancement & Approvals) begins.

---

## Repository Status Reconciliation — 2026-08-18

This entry records the current repository state after reviewing the implementation, migrations, tests, and deployment configuration. Historical phase entries above are retained as session history.

### Verified Repository State

- The `main` branch points to commit `5334893` (`Phase 5 Enterprise Workflow Engine — full implementation`).
- The Alembic migration chain continues through `0083`, beyond the Phase 5 report's stopping point at `0050`.
- Migrations `0066`–`0075` cover pipeline-stage approval requirements, infrastructure upload/deletion sessions, cabinets, OLTs, splitter boxes, staging, audit logging, RLS/indexes, and user soft-delete support.
- Migrations `0076`–`0083` add the Form Builder v2 schema, versioning, field definitions, associations, submissions, seed data, and admin permissions.
- `backend/main.py` registers the customer, infrastructure, Form Builder, tasks, projects, webhooks, and shifts routers.
- Backend implementation is present for task workflow and dual approval, customer APIs and HMAC webhooks, infrastructure asset upload/deletion workflows, and Form Builder v2.
- Frontend pages are present for infrastructure upload/deletion/audit, Form Builder, customer workflows, task inbox, reports, shifts, and setup flows.
- Tests are present for task workflow, infrastructure phases 2–4 and 7–8, Form Builder, and earlier integration suites.

### Documentation Reconciliation

The earlier Phase 3 entry says Phase 4 is awaiting approval. That statement is now historical: the repository contains the subsequent approval migration and implementation. The phase documentation should be expanded or cross-linked to describe the completed pipeline approval work.

`IMPLEMENTATION_REPORT.md` also describes only migrations `0043`–`0050`. It should be updated to cover the Customer Module, infrastructure asset workflows, and Form Builder v2, or explicitly state that it is a Phase 5-only report.

The repository contains both the legacy `app/modules/forms` system and the newer `app/modules/form_builder` system. Their ownership, migration history, and intended usage should be documented to prevent future route and schema confusion.

### Validation Status

This review verified source files, migration filenames, test locations, and configuration presence. It did not run the full backend test suite, frontend build, database migration upgrade, or Docker startup. Historical `PASS` statements in earlier entries should therefore not be treated as current runtime verification.

### Current Known Gaps

- WebSocket real-time updates; the current UI relies on polling.
- PDF report rendering.
- Bulk MEC/outage responsibility assignment UI.
- Mobile responsive polish below 768px.
- Report chart visualisations.
- Kubernetes/Helm deployment manifests.
- Termii environment-variable fallback.
- Migration integrity tests currently need to be extended beyond the older `0043`–`0051` range to cover the current head.
