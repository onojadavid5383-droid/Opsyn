# OpSyn Network GIS Unification Plan
### Network Map + FTTx Designer + Infrastructure → one GIS engineering unit

**Prepared:** 2026-09-25 · **Revision 2:** decisions D1–D7 applied (§4)
**Status:** Phases 1–3 (GIS foundation, asset catalogue, topology/trace/utilisation) implemented 2026-09-26; Phase 3 awaiting review, Phase 4 not started. D4 was revised on 2026-09-25: the legacy logic stays (see §4).
**Source brief:** "OP SYN — Network GIS + FTTx Engineering Platform, Master Implementation Plan" (50 sections)
**Method:** I read the source directly: backend modules `infrastructure`, `fttx_designer`, `projects`, `customers`, `smartolt`, `dashboard`, `all_modules`, `tasks/*`; migrations 0001–0086; the frontend map, infrastructure, FTTx designer, dashboard and project pages; and `docs/plans/FTTx_Designer_Web_Integration_Plan.md`.

**Working rule:** each phase ends with an implementation summary, then work STOPS until you approve the next phase.
**Verification per phase:** backend `pytest` (scratch venv, `--confcutdir=tests/unit`); frontend `npm run typecheck && npm run lint && npm test -- --no-file-parallelism && npm run build`; for every new migration, `alembic upgrade head` → `downgrade -1` → `upgrade head`; map interaction checks through the existing Playwright + Edge screenshot tooling (jsdom has no WebGL).

---

## 1. Phase 0 audit: what exists today

### 1.1 The problem: three GIS silos that don't share data

| Silo | Where | Storage | Geometry | Knows about the others? |
|---|---|---|---|---|
| **A. Legacy infrastructure** | `infrastructure_sites`, `infrastructure_nodes`, `infrastructure_routes`, `infra_ports`, `infra_subscribers` | Relational | `latitude`/`longitude` NUMERIC. **Routes have no geometry**: a generic from-node → to-node link with no road routing (no Dijkstra) | No |
| **B. FTTH assets (uploaded)** | `cabinets`, `olts`, `splitter_boxes` (0069–0074) + upload/staging/deletion/audit sessions | Relational | PostGIS `geometry(Point,4326)` + GiST | Only splitter → cabinet and splitter → parent splitter |
| **C. FTTx Designer** | `fttx_design_runs`, `fttx_design_run_layers`, `fttx_design_run_outputs` (0085) | **JSONB blobs** (GeoJSON inputs and outputs, BOQ, optical summary) | Inside JSON only; nothing is spatially queryable | No. There is no `project_id` and nothing is written into A or B |

What this means in practice:
- A generated FAT is JSON inside a run row. It can't be shown on the network map, edited, traced or promoted.
- `GET /infrastructure/map` returns every row of A and B in one unfiltered payload.
- The FTTx wizard shows a BOQ row count and a DED download, but no map.

### 1.2 What depends on silo A (important for D4)

| Dependent | Uses | Action in Phase 1 |
|---|---|---|
| `InfrastructurePage.tsx` Sites/Nodes/Routes tabs + `api/index.ts` site/node/route calls | CRUD | Remove tabs and API calls |
| `infrastructure/router.py` sites/nodes/routes/summary/map endpoints | CRUD + map payload | Remove CRUD; `/map` + `/summary` re-read from `net_assets` |
| `tasks/infrastructure_sync.py` (SmartOLT port sync) | `InfrastructureNode` where `node_type='OLT'`, `ip_address` | Repoint to `net_assets` OLT (`attributes.ip_address`) |
| `tasks/capacity_monitor.py`, `infra_ports`, `infra_capacity_alerts`, `infra_monitoring_config` | node/site FKs | Repoint to `net_assets` / `net_ports` |
| `dashboard/router.py`, `tasks/metric_snapshots.py`, `all_modules.py` (org summary, capacity SQL) | node/site counts | Repoint the counts to `net_assets` |
| `dashboard/MapPanel.tsx` → `infrastructure/map` | map payload | Keeps working (the endpoint stays, data source changes) |
| `scripts/seed.py` | seeds sites/nodes | Seed `net_assets` instead |

### 1.3 What we reuse

| Capability | Existing asset | Decision |
|---|---|---|
| PostGIS | `postgis/postgis:16-3.4`, `geoalchemy2`, GiST pattern in 0074 | Keep |
| Multi-tenancy | `tenant_id` + RLS policies, `get_db()` RLS injection | Keep. Every new table gets tenant + RLS in its own migration |
| RBAC | `check_permission("feature.key")`, feature-key seed migrations (0083) | Keep. New keys in §3.9 |
| Audit | `infrastructure_audit_log` | Generalise into the network audit trail |
| Upload / staging / commit | `InfraUploadSession` → staging → commit | Keep. Commit retargets to `net_assets` |
| FTTx engine | `fttx_designer/engine/**` (QGIS-free via `geometry_compat`), Celery task `fttx_design_run`, GeoJSON layer upload (`geojson_io.build_input_layers`) | Keep unchanged. Add input/output adapters. Its road graph + Dijkstra `CableRouter` becomes the routing service for **all** cable connections (auto and manual) |
| Notifications, tasks | notification module, task engine | Reuse to notify reviewers in the design/BOQ approval flow |
| Incidents | `outage_incidents`, SmartOLT handler | Link to assets (Phase 11) |
| Frontend state / UI | zustand, TanStack Query, glass/tokens, IBM Plex, lucide, `LayerPanel`, `MapInspector`, `MapSearch`, `mapPalette`, basemap source list + fallback logic | Reuse the logic and UI panels. **Replace the Leaflet canvas with MapLibre (D1)** |

### 1.4 Gaps

No unified asset model or lifecycle; no FDT/FAT/closure/pole/manhole/ONU tables; no LINESTRING cables; no topology; no design ↔ project link or versions; no bbox/zoom map API or vector tiles; no map editing.

---

## 2. Target architecture

```
                 ┌────────────── Frontend (React + MapLibre GL) ──────────────┐
                 │ /network  one map, 3 modes: NETWORK · DESIGN · DEPLOYMENT  │
                 │ MVT sources for the network · GeoJSON source for the       │
                 │ design being edited · terra-draw for editing               │
                 └──────────────────────────┬─────────────────────────────────┘
                                            │ typed REST + MVT
┌───────────────────────────────────────────┴───────────────────────────────┐
│ FastAPI                                                                   │
│  network/     assets · cables · connections · trace · utilisation         │
│  gis/         tiles (ST_AsMVT) · features · search · snap · route         │
│  design/      designs · inputs · versions · operations · BOQ · validation │
│  approval/    design + BOQ approval workflow (standalone, D3)             │
│  deployment/  progress · as-built · promotion                             │
│        ▲                   fttx_designer/engine (unchanged)               │
│        │  input_adapter ─► pipeline / CableRouter / boq / validation ─► output_adapter
└────────┼──────────────────────────────────────────────────────────────────┘
         ▼
 PostgreSQL + PostGIS: single source of truth
 net_assets · net_cables · net_ports · net_fibers · net_connections
 designs · design_inputs · design_versions · design_operations · approvals
```

Invariants:
1. PostGIS tables are the source of truth. The run JSONB becomes an archive.
2. Auto and manual assets are the same row type. They differ only in `creation_method`.
3. Topology lives in `net_connections`, never inferred from proximity.
4. **Cable connections between infrastructure are routed along the road graph (Dijkstra, the engine's `CableRouter`).** Straight-line "generic" links are removed (D4). A free-drawn cable is allowed, but it is flagged `route_method=MANUAL_GEOMETRY` and raises a validation warning.
5. Engineering maths runs only in the backend.
6. Nothing is hard-deleted: soft delete plus audit. Promotion changes lifecycle state and never copies the row.

---

## 3. Core design

### 3.1 Asset and cable tables

**`net_assets`** has one row per point-like asset: `id` UUID · `tenant_id` · `asset_code` (e.g. `FAT-0014`, unique per tenant + scope) · `asset_type` (POP, SITE, ROOM, RACK, OLT, ROUTER, SWITCH, WDM, ODF, CABINET, FDT, FAT, SPLITTER, CLOSURE, ENCLOSURE, POLE, MANHOLE, HANDHOLE, ONU, CUSTOMER_ENDPOINT) · `name`, `description` · `geom geometry(Geometry,4326)` GiST · `lifecycle_status` · `creation_method` (AUTO, MANUAL, IMPORTED, FIELD) · `parent_id` (containment only) · `project_id` · `design_id` (NULL = live network) · `lineage_id` (stable across versions) · `attributes` JSONB (validated per type by a Pydantic registry) · `capacity`, `used_capacity` · `source_table/source_id` (backfill provenance) · created/updated by/at · soft-delete columns.

**`net_cables`** has the same core columns plus `geom LineString`, `design_geom`, `asbuilt_geom`, `cable_category` (FEEDER, DISTRIBUTION, DROP, BOX_TO_BOX, CLOSURE_FDT, PICKUP, INTERNAL), `fiber_count`, `length_m` (server-side `ST_Length(geom::geography)`), `installation_type`, `route_method` (ROAD_GRAPH, MANUAL_GEOMETRY), `source_asset_id`, `dest_asset_id`.

### 3.2 Topology

`net_ports` (replaces `infra_ports`), `net_fibers` (lazy, TIA-598 colours), `net_connections` (source/dest asset + port, `via_cable_id`, `fiber_id`, `connection_type`, lifecycle, `design_id`). Tracing uses a recursive CTE with a depth cap and a cycle guard.

### 3.3 Lifecycle and visual mapping

Lifecycle states: DRAFT, PLANNED, DESIGNED, UNDER_REVIEW, APPROVED, CONSTRUCTION, INSTALLED, TESTING, VERIFIED, ACTIVE, FAULTY, RETIRED, REJECTED. They are defined once in `network/lifecycle.py` together with the allowed transitions, and mirrored in `shared-types`.

The frontend has one `lib/network/statusStyle.ts` that emits **MapLibre style expressions** (`match` on `asset_type` × `lifecycle_status`), so every layer shares the same rules. Proposed = dashed line / hollow icon; active = solid; review = halo; construction = amber ring; rejected = 40% opacity; faulty = red badge. Colour is never the only signal.

NETWORK mode shows `lifecycle_status IN (ACTIVE, FAULTY, VERIFIED) AND design_id IS NULL`.

### 3.4 Designs, per-design inputs, versions

- **`designs`**: `project_id`, `name`, `boundary geometry(Polygon)`, `status` (DRAFT, GENERATED, MODIFIED, VALIDATING, UNDER_REVIEW, APPROVED, REJECTED, SUPERSEDED, DEPLOYED), `current_version_id`, `engine_config` JSONB.
- **`design_inputs` (D6, uploaded per design)**: `design_id`, `layer_key` (road, homepass, pole, building, pickup, existing_structure), `geom` GiST, `properties` JSONB, `upload_id`. It is filled from GeoJSON/Excel uploads through the existing upload/staging pattern and the engine's `geojson_io` validation. Roads here form the Dijkstra graph for every cable routed in that design, auto or manual.
- **Working set** = the `net_*` rows with `design_id = X`.
- **`design_versions`**: `version_no`, `parent_version_id`, `creation_method`, `label`, immutable gzip `snapshot` of the working set, `boq_snapshot`, `validation_summary`, `optical_summary`. Restore = snapshot → working set, recorded as a new version.
- `fttx_design_runs.design_id` (nullable FK) links an engine run to the version it produced.

### 3.5 Auto and manual are independent tracks (D2)

Both tracks depend only on the design container (Phase 4) and on the shared **design services**: routing, BOQ and validation over the working set. Neither depends on the other.

| Situation | Behaviour |
|---|---|
| Start with Manual | Draw assets and cables; BOQ and validation are computed from the working set exactly as for auto designs |
| Start with Auto | The engine generates the working set (creation_method=AUTO) |
| Run Auto on a design that already has content | The current state is snapshotted as a version first, then the engine output **replaces** the working set as a new version (confirm dialog). Nothing is lost; the old version can be restored |
| Manual edits after Auto | Normal manual operations + local recalculation (D7) |
| Switch back and forth | Allowed at any time. The toolbar offers `Auto Design` and `Manual Design` side by side |

Later (not in scope now): "Auto-fill around locked manual assets", which passes manual assets to the engine as fixed existing infrastructure.

### 3.6 Engine adapters

- **Input adapter:** `design_inputs` + `designs.boundary` + live POLE/MANHOLE/FDT/OLT inside the boundary → the FeatureCollections `build_input_layers()` already accepts.
- **Output adapter:** engine layers → `net_*` rows. The mapping:

| Engine output | Target |
|---|---|
| FDT, FAT, Closure, proposed poles/handholes | `net_assets` |
| Feeder_Cable, Box_to_Box, Closure_to_FDT, pickup, drops | `net_cables` (`route_method=ROAD_GRAPH`) |
| `FAT.parent_fdt`, cable `fdt_id`, wing/sequence | `net_connections` + FAT `attributes` |
| splitter pattern | SPLITTER child assets + ports |
| BOQ / BOQ_FDT_detail | `design_versions.boq_snapshot` |
| Validation_Results + perf_logger findings | `design_validation_issues` |
| optical_loss_summary | `design_versions.optical_summary` |

- **Hydrator:** DB rows → engine domain objects. Used by the BOQ service, the validation service and local recalculation, so manual designs get the same engine BOQ and validation.

### 3.7 Edit operations API

`POST /designs/{id}/operations { op, ... }` supports ADD_ASSET, MOVE_ASSET, DELETE_ASSET, UPDATE_ATTRS, DRAW_CABLE (default `route: "road_graph"` → server computes the Dijkstra path between endpoints), EDIT_CABLE_GEOM, SPLIT_CABLE, EXTEND_CABLE, CONNECT, DISCONNECT.

Each op is validated server-side, applied in one transaction, and logged in `design_operations` together with its inverse. Undo/redo run on the server. The response returns changed features plus BOQ and validation deltas.

### 3.8 Map stack (D1: MapLibre GL)

- **Libraries:** `maplibre-gl` (BSD-3) with a thin in-house React wrapper (`MapCanvas`, a context holding the map instance, declarative `<Source>`/`<Layer>` components). I'm not adding `react-map-gl`, to avoid an extra dependency layer; the wrapper stays under ~300 lines. For editing: `terra-draw` + `terra-draw-maplibre-gl-adapter` (MIT), which gives point/line/select modes, vertex editing and snapping hooks. Measuring uses turf-free server calls or a tiny local haversine used only for display.
- **Basemap:** OSM raster source in a MapLibre style. The existing `OSM_TILE_SOURCES` fallback list (openstreetmap.org → openstreetmap.de, 8 s timeout, remembered in sessionStorage) is ported into a `useResilientRasterSource` hook. Dark mode uses raster paint properties (`raster-saturation`, `raster-brightness-max`, `raster-contrast`) instead of the CSS filter. CSP: add `worker-src blob:` and `child-src blob:` for MapLibre workers, and keep both OSM hosts in `img-src`/`connect-src`.
- **Data delivery:**
  - Live network: **MVT vector tiles from day one**, `GET /gis/tiles/{layer_group}/{z}/{x}/{y}.mvt` built with `ST_AsMVT`/`ST_AsMVTGeom`, zoom bands per layer, a Redis tile cache with per-tenant keys, and invalidation by bbox on writes.
  - Active design working set: `GET /designs/{id}/features` as GeoJSON (hundreds to low thousands of features), because edits need fast local patching.
  - Customers/ONUs: clustered at low zoom server-side in the MVT (`ST_ClusterDBSCAN`/grid), raw at street zoom.
- **Zoom bands** (one server-side layer registry, also served to the LayerPanel): ≤11 POP/OLT/FDT/feeder · 12–14 +FAT/distribution/poles · 15–17 +drops/ONU/endpoints · ≥18 +splitters/ports.
- **Dashboard MiniMap** stays on Leaflet until Phase 11, then moves to the MapLibre wrapper and the Leaflet deps are removed. There is one map library per screen and never two parallel implementations of the same screen.
- **Testing:** `maplibre-gl` is mocked in vitest (jsdom has no WebGL); real rendering and interaction are checked with the Playwright + Edge tooling.

### 3.9 Permissions (new feature keys)

| Key | Viewer | Engineer | Reviewer | Line manager | Field | Admin |
|---|---|---|---|---|---|---|
| `network.view` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `network.edit` | | | | | | ✓ |
| `design.edit`, `design.generate` | | ✓ | | | | ✓ |
| `design.review` (engineering review) | | | ✓ | | | ✓ |
| `design.approve` (line manager) | | | | ✓ | | ✓ |
| `boq.review`, `boq.approve` | | | ✓ | ✓ | | ✓ |
| `deployment.update`, `asbuilt.capture` | | | | | ✓ | ✓ |
| `network.promote` | | | | ✓ | | ✓ |

`infrastructure.view` implies `network.view`.

### 3.10 Approval workflow (D3: standalone, pipeline link later)

New `approval/` module, not tied to the project pipeline:
- `approval_requests`: `subject_type` (DESIGN_VERSION | BOQ), `subject_id`, `design_id`, `status`, `current_step`, `submitted_by/at`, and `pipeline_stage_id` (nullable and unused for now; it is the reserved hook for linking to project pipeline stages later).
- `approval_steps`: ordered steps per subject type: **Design** = ENGINEERING_REVIEW → LINE_MANAGER_APPROVAL; **BOQ** = BOQ_REVIEW → BOQ_APPROVAL. Each step records decision, comment, actor and time.
- Rules: design submission requires validation to have no ERRORs. An approved design version is locked. The BOQ can only be submitted against an **approved** design version, and its snapshot is frozen at submission. **Deployment requires both an approved design and an approved BOQ.** A rejection at any step sends the item back to revision; the next submit creates a new design version or BOQ revision.
- Reviewers are notified through the existing notifications module (optionally with a task created through the task engine).

---

## 4. Decisions (recorded 2026-09-25)

| # | Decision | Effect on the plan |
|---|---|---|
| D1 | **MapLibre GL** | §3.8. New `/network` map is MapLibre + terra-draw; MVT from Phase 1; the Leaflet scale spike is dropped; Leaflet is removed after the MiniMap migrates (Phase 11) |
| D2 | **Auto and manual design are independent; either can be used at any time** | §3.5. Phase 4 builds the shared design container + BOQ/validation services; Phase 5 (Auto) and Phase 6 (Manual) are parallel tracks with no dependency on each other |
| D3 | **Design and BOQ have their own approval, not the project pipeline (link in future)** | §3.10. New standalone approval module with a reserved `pipeline_stage_id` hook |
| D4 | ~~Clear the legacy generic sites/nodes/routes logic~~ **Revised 2026-09-25: leave the legacy logic in place; it will be reviewed later** | The `net_*` model is built alongside it. The legacy tables, endpoints, UI tabs and all seven dependents in §1.2 (SmartOLT sync, capacity monitor, metric snapshots, dashboard counts, org summary, `/infrastructure/map`, `/infrastructure/summary`) are untouched and keep reading `infrastructure_*`. New cables are still road-graph routed (§2 invariant 4) |
| D5 | **Skip customer location for now** | No `customers` geometry or link. CUSTOMER_ENDPOINT/ONU assets exist on their own; the customer ↔ network link is deferred and listed as a future extension |
| D6 | **Homepass/road inputs uploaded per design** | `design_inputs` table (§3.4) |
| D7 | **Local recalculation in v1; full re-clustering only via "Regenerate area"** | Phase 7 |

**D4 as implemented:** no legacy table is renamed or dropped and no legacy endpoint is removed. Rows from the uploaded `olts`/`cabinets`/`splitter_boxes` tables are mirrored into `net_assets` (migration 0087, idempotent); `infra_ports` stay with the legacy nodes they belong to, so `net_ports` starts empty.

---

## 5. Data migration map

| Old | New | Notes |
|---|---|---|
| `olts`, `cabinets`, `splitter_boxes` | `net_assets` (OLT, CABINET/ODF, SPLITTER), `parent_id` from `cabinet_id`, `net_connections` from `parent_splitter_id` | idempotent via `(source_table, source_id)` unique index; ambiguous values preserved in `attributes.legacy_*`, never guessed |
| `infra_ports` | `net_ports` | only ports whose node can be resolved; the rest are listed in a reconciliation report |
| `infrastructure_sites/nodes/routes` | **not migrated**, archived as `legacy_infrastructure_*` (D4) | endpoints, UI tabs, and seed code removed |
| `infra_subscribers` | not migrated (D5); left untouched | revisit with the customer link |
| `fttx_design_run_outputs` | optional per-run "Import as design" action → design + V1 | nothing deleted |

Old upload tables (`olts`, `cabinets`, `splitter_boxes`) stay for one release with dual-write from upload commit, then become read-only. All migrations are reversible.

---

## 6. Phased implementation plan

```
P0 Audit ✅
P1 GIS foundation (MapLibre, net_assets, MVT, legacy clean-up)
P2 Network asset catalogue
P3 Topology · trace · utilisation
P4 Design container + inputs + shared design services (BOQ, validation, routing)
        ├── P5 Track A: Auto design ───┐   independent, either order,
        └── P6 Track B: Manual design ─┘   both use the P4 services
P7 Hybrid local recalculation
P8 Versioning · compare · restore · audit
P9 Design & BOQ approval (standalone)
P10 Deployment · as-built · promotion to live
P11 Operations + scale hardening + Leaflet removal
```

### Phase 1: GIS foundation (MapLibre + unified asset core + legacy clean-up)
**Backend**
- `modules/network/` (models, schemas, `lifecycle.py`, `asset_types.py`, service, router) and `modules/gis/` (`layer_registry.py`, `tiles_router.py`, `search_router.py`).
- Migrations: `net_assets`, `net_cables`, `net_ports` (GiST, RLS, CHECKs, trigram index on code/name), new feature keys, backfill from `olts`/`cabinets`/`splitter_boxes`/`infra_ports`, archive-rename of the legacy tables.
- APIs: `/network/assets` CRUD, `GET /gis/layers`, `GET /gis/tiles/{group}/{z}/{x}/{y}.mvt`, `GET /gis/bounds`, `GET /network/search`.
- ~~Legacy clean-up (D4)~~ dropped from Phase 1 by the D4 revision: the legacy logic and its dependents are left as they are.

**Frontend**
- Add deps: `maplibre-gl`, `terra-draw`, `terra-draw-maplibre-gl-adapter`.
- `features/network-map/`: `MapCanvas` wrapper, `useResilientRasterSource`, `ModeSwitch` (NETWORK live; DESIGN/DEPLOYMENT shown as upcoming), `LayerPanel` driven by `/gis/layers`, MVT asset/cable layers styled through `statusStyle.ts`, `SelectionManager` (feature-state highlight), generic `AssetInspector`, `MapSearch` (fly-to + select + inspect), `MapStatusBar` (coords, zoom, scale), route `/network`.
- Navigation "Network map" (sidebar, bottom nav, dashboard "Open full map") points to `/network`; `InfrastructurePage` and its legacy Map tab are unchanged (D4 revised). The nginx CSP already allowed MapLibre (`worker-src blob:`, both OSM hosts), so it needed no change.

**Tests:** lifecycle transitions; MVT tile generation (feature count per zoom band, tenant isolation); backfill idempotency; repointed tasks (sync, capacity monitor) against `net_assets`; frontend statusStyle, LayerPanel, search with the MapLibre mock; Playwright render screenshot.
**Acceptance:** `/network` renders the real migrated OLTs/cabinets/splitters from PostGIS through vector tiles; search → zoom → select → inspect works; the dashboard, SmartOLT sync and capacity monitor still work; no legacy route logic remains.

### Phase 2: Network asset catalogue
- Per-type attribute schemas: POP, OLT, ODF, CABINET, FDT, FAT, SPLITTER, CLOSURE, ENCLOSURE, POLE, MANHOLE, HANDHOLE, ONU, CUSTOMER_ENDPOINT; cable categories; asset-code generator per (tenant, type).
- Upload commit dual-writes to `net_assets`; new upload types for poles/manholes/handholes/FDT/FAT/cables (GeoJSON/Excel through the staging flow).
- Frontend: sprite sheet per asset type (shape + glyph + status ring, generated from the lucide/custom SVGs), cable line styles per category (width + dash + casing), type-specific inspector sections via an `inspectorRegistry`, asset registry table in `/infrastructure` reading `net_assets`.
- **Acceptance:** every major FTTx asset and cable type can be stored, rendered and inspected, with distinct symbology and lifecycle styling.
- **As implemented (2026-09-26):** one attribute registry (`network/attributes.py`) drives API validation, upload columns and the inspector (served as `GET /network/catalogue`); generated codes `<PREFIX>-NNNN` under an advisory lock (`network/codes.py`); cable CRUD (`/network/cables`); network upload types (POP, ODF, FDT, FAT, closure, enclosure, pole, manhole, handhole, ONU, customer end point, cable) from Excel or GeoJSON through the existing staging flow (`network/upload.py`), with `GET /infrastructure/upload-types` + templates; OLT/cabinet/splitter upload commit and bulk deletion dual-write `net_assets`; migration 0088 adds `route_method = IMPORTED` for as-built cable geometry. Frontend: catalogue-driven inspector for assets and cables (details view + edit, splitter port diagram), `/network?asset=|cable=` deep links, Infrastructure → Network register tab, spec-driven upload page. The per-type sprite sheet was delivered in Phase 1 (runtime-rendered marker images).

### Phase 3: Topology, trace, utilisation
- `net_fibers`, `net_connections`; `GET /network/assets/{id}/connections|upstream|downstream|trace` (ordered hops + merged geometry); `network/utilisation.py` (FAT/FDT/splitter/OLT-PON capacity, used, available, %) exposed per asset and as MVT properties.
- Frontend: `TracePanel`, trace highlight layer (other features dimmed through feature-state), inspector Connections + utilisation bar, context-menu trace actions.
- **Acceptance:** an ONU/FAT traces to OLT/POP along stored connections, highlighted on the map; utilisation comes from the service.
- **As implemented (2026-09-26):** migration 0089 (`net_connections`, `net_fibers`, RLS). Connections come only from explicit data: hand-made, or derived by `network/topology.py` rules from cable endpoints, uploaded splitter cabinet / parent-splitter links and a FAT's `parent_fdt_code`; the derived set is re-synced after every asset/cable/upload/deletion write and cannot be deleted directly (409, change the source data). Trace = recursive CTE with depth/row caps and cycle guard, returning ordered hops, the path to the nearest OLT/POP/SITE, cable length and map geometry. One utilisation definition (ports / FAT ports / connected assets / recorded) serves the API and the MVT tiles (`util_pct`); the tile revision includes connections. Fibres listed virtually in TIA-598 colours, stored once a status is recorded. Frontend: inspector Capacity (with its basis), Connections (fed from / feeds, add by hand, trace buttons), cable Fibres; trace layer (network dimmed, logical links dashed) + trace panel; right-click menu; capacity-ring view. Deviation: trace highlight uses its own GeoJSON source plus dimming instead of feature-state.

### Phase 4: Design container, per-design inputs, shared design services
- Tables: `designs` (with boundary), `design_inputs`, `design_versions`, `design_validation_issues`, `design_operations` (schema only; used in Phase 6).
- Input upload per design (D6): road/homepass/pole/building/pickup GeoJSON/Excel → staging → `design_inputs`, with validation reusing `geojson_io`.
- **Shared services, used by both tracks:** the hydrator (DB → engine domain), a routing service (Dijkstra `CableRouter` over the design's roads: `POST /designs/{id}/route {from, to}`), a BOQ service (engine `boq.py` over the working set), and a validation service (engine `validation.py` + topology checks).
- APIs: `POST/GET /projects/{id}/designs`, `GET/PATCH /designs/{id}`, `POST /designs/{id}/inputs/{layer_key}`, `GET /designs/{id}/features`, `GET /designs/{id}/summary`, `GET /designs/{id}/boq`, `POST /designs/{id}/validate`.
- Frontend: project page "Open Network Map" + Design tab; `/network?mode=design&design=`: design header (project · version · status), boundary draw/upload, inputs layer group, summary strip (homepasses, FDT, FAT, splitters, closures, cable km, BOQ total, warnings, errors), `ValidationPanel` with "View on map", toolbar showing **Auto Design** and **Manual Design** as equal entry points.
- **Acceptance:** a design can be created, its inputs uploaded and seen on the map, and BOQ/validation computed for whatever is in its working set.
- **As implemented (2026-09-27):** migration 0090 (`designs`, `design_input_uploads`, `design_inputs`, `design_versions`, `design_validation_issues`, `design_operations`, all RLS; `design_id` FKs on `net_assets`/`net_cables`/`net_connections` with ON DELETE CASCADE; feature key `design.edit`, granted like `fttx_designer.edit`). `modules/design/`: input parser reusing the network upload readers (all-or-nothing, homepass counts normalised to `customers`), engine bridge (design inputs → engine layers in UTM, LRU-cached per inputs revision, engine globals under one lock), hydrator (working set → engine FDT/FAT/closure/cable objects), routing service (engine `CableRouter` Dijkstra over the design's roads, 422 when no route, never a straight-line fallback), BOQ service (SQL quantities + the engine's `populate_boq_layer` per street; no unit rates exist, so the "BOQ total" is a line count), validation service (engine rule values from the design's config/capacity profile + topology + boundary checks, stored per run, summary on the version). A design in VALIDATING/UNDER_REVIEW/APPROVED/SUPERSEDED/DEPLOYED is frozen (409 on inputs/boundary/config changes). "Boundary from inputs" = convex hull + 30 m (concave hull took 55 s on road linework). Frontend: project "Network designs" tab (list, create, open on map); `/network?mode=design&design=` with the design panel (project · version · status, boundary draw/from inputs/clear, six input layers with counts, map switch, upload replace/add, remove), the live network dimmed and not clickable, a shaded mask outside the boundary, inputs and working set on the map (working set in the live symbology), toolbar (Auto/Manual design as equal entry points, Validate, Issues, BOQ), summary strip, validation drawer with "View on map", BOQ drawer (quantities + engine street rows). Deviation: boundary drawing is a small built-in tool, not terra-draw (not installed; Phase 6 decides for the edit tools).

### Phase 5: Track A, auto design (independent of Phase 6)
- Input and output adapters (§3.6); `fttx_design_runs.design_id`; `POST /designs/{id}/generate` queues the existing Celery task and snapshots the prior state first (§3.5); `GET /designs/{id}/generate/status`; "Import existing run as design".
- Frontend: Auto Design drawer reusing the config form extracted from `FttxDesignerWizardPage` (moved into a shared component; the wizard uses it too), progress polling, auto fit-to-bounds on completion.
- **Tests:** golden adapter test (fixture engine output → expected rows and connections); generate → DB → tiles/features integration test; existing engine tests unchanged.
- **Acceptance:** Project → Design → Auto Design → the engine runs → PostGIS rows → the map shows the design and zooms to it, with BOQ and validation.
- **As implemented (2026-09-27):** migration 0091 (`fttx_design_runs.design_id` + `design_version_id`; route method `DIRECT` for the engine's drops, FAT straight to the premises — neither road-routed nor hand-drawn). `design/adapters.py` = the pure output adapter (golden-tested; mirror of the hydrator: FDT/FAT/closure/pole rows with the attribute keys the hydrator reads, a SPLITTER child per FAT with the engine's `1x9`/`1x8` kept verbatim, FEED connections FDT→FAT and closure→FDT, existing poles matched by position to what the run was given). `design/auto_design.py`: input adapter (roads within 100 m of the boundary, homepasses inside it, live POLE assets offered as existing structures), `POST /designs/{id}/generate` (aerial only; refuses while a run is active or, without `replace`, when the working set has content; commits before queueing; broker down → 503 and the run marked failed), `GET …/generate/status` (live Celery progress), `GET …/importable-runs` + `POST …/import-run` (copies the inputs a design lacks, adopts the run's settings). The EXISTING Celery task runs the engine unchanged and, for a design run, `apply_output()`: snapshot (gzip JSON) of the old working set onto the current version, replace, new version (AUTO/IMPORTED) with `boq_snapshot` (engine street + FDT BOQ), `optical_summary`, the engine's own Validation_Results kept as `validation_summary.engine_findings`, then the shared validation. Validation: a drop needs only its FAT end, a feeder from a named pickup only its closure end. Frontend: Auto design drawer (settings form extracted from the FTTx Designer wizard into `components/fttx`, used by both; input check; confirm-replace; progress polling; result; import a run), toolbar run badge, map fits the new version, engine findings in the Issues drawer. Deviations: FDT splitters and splitter ports are not created (the engine output carries only the FAT splitter type; live splitters keep ports as attributes too); the pickup point stays an input, not an asset.

### Phase 6: Track B, manual design (independent of Phase 5)
- Operations endpoint with inverses (§3.7), server-side undo/redo, `POST /gis/snap` (road with side offset, pole, asset, cable vertex, boundary; reusing engine `spatial_utils`/`structures`/`topology` helpers), DRAW_CABLE routed along roads by default.
- Frontend: `DesignToolbar` (Select, Pan, Measure, Add ▾, Move, Delete, Draw cable, Connect, Edit/Split/Extend, Undo/Redo) on one terra-draw adapter plus a `useEditTool` state machine; snap preview; keyboard shortcuts; `MapContextMenu` (empty map / asset / cable).
- **Tests:** op + inverse round-trip tests; snap/route service tests; tool state-machine tests.
- **Acceptance:** an engineer can build an FDT → FAT → drop design entirely by hand, with road-routed cables, BOQ and validation, and undo/redo that survives a reload. This works with no auto run ever made.
- **As implemented (2026-09-27):** `design/operations.py`: ADD_ASSET, MOVE_ASSET, DELETE_ASSET, UPDATE_ATTRS, DRAW_CABLE (road graph by default, exact device ends; drops straight/DIRECT), DELETE_CABLE, EDIT_CABLE_GEOM, SPLIT_CABLE (optionally placing a closure at the cut), EXTEND_CABLE, CONNECT, DISCONNECT. A feeding cable between two devices records the FEED link and gives a FAT the FDT heading its chain (`parent_fdt_code`), so a hand-built PCC chain validates like an engine one. Every operation is logged with before/after row images (a generic tracker: created / updated / deleted rows per table, geometry as hex EWKB); undo writes the before images back, redo the after images — exact, never re-routed, server-side so they survive a reload; a new operation drops the redo branch; a new version (auto/import) clears the log. `design/snap.py` (`POST /designs/{id}/snap`, design-scoped rather than `/gis/snap`): device, input pole, homepass, pickup, live device, cable vertex, 3 m beside the nearest road, boundary. Frontend: a pure tool state machine (`editMachine.ts`), the map edit layer (click resolution + server snap, rubber band, snap ring, right-click edit menu), a vertical tool rail with type chips, road/straight toggle, hint card, measure, undo/redo with labels, keyboard shortcuts. Deviation: vertex dragging is "Redraw the line" (click new points), not terra-draw handles.

### Phase 7: Hybrid local recalculation (D7)
- `design/recalc.py`: op → affected set (moved asset's cables, connections, FAT-reach customers) → hydrate → reroute via `CableRouter` → lengths → BOQ → validation → deltas. "Regenerate area" = full engine run → new version.
- Frontend patches the query cache from deltas and animates the BOQ strip.
- **Acceptance:** the brief's "move FAT-0014" scenario: cable geometry, length, BOQ and validation all update, for both auto- and manually-created assets.
- **As implemented (2026-09-27):** `design/recalc.py`. Moving a device recalculates its cables inside the same operation (so undo reverts them): road-routed cables are routed again with the engine's CableRouter between the devices they join (a device with no road route keeps its line, ends moved, marked hand-drawn and noted); drops are redrawn straight to the same customer point (a customer now out of reach shows as DROP_TOO_LONG — never re-assigned); hand-drawn / as-built lines keep their shape and only the moved end follows (`recalc: false` gives that for every cable). Every operation, undo and redo answers with a delta: the changed features and removed ids, the BOQ lines changed (before → after), the issues new and resolved. The client patches the map cache from it (no reload of the working set), pulses the changed figures on the summary strip, shows a change ribbon and lists the recalculated cables with before → after lengths. "Regenerate" = auto design (Phase 5): a full engine run, a new version; offered in the tool card whenever an edit leaves new issues. Found in testing: the engine router joins an off-road point to the network at a road node, so a device dropped mid-block can route a long way round — devices snap beside the road when clicked near one (snap reach now equal to the snap radius; it was 2.5×, which pulled a mid-block click onto a street 46 m away).

### Phase 8: Versioning, compare, restore, audit
- Snapshot/list/compare/restore endpoints; `network_audit_log` (generalises `infrastructure_audit_log`, which stays and is unioned by a view).
- Frontend: version switcher, compare overlay (added / removed / moved with ghost-to-new arrow), asset History tab.
- **Acceptance:** no design state is ever lost.
- **As implemented (2026-09-27):** migration 0092. `network_audit_log` written by a row trigger on net_assets / net_cables / net_connections (every path: API edits, design operations, uploads, backfills); an update records only the changed fields (old → new, geometry as GeoJSON; updated_at/updated_by ignored), `clock_timestamp()` keeps one transaction's rows in order; the actor comes from the request (`audited()` on the network and design write endpoints stamps app.user_id / app.actor_label), else System; bulk replacements (auto design, import, restore) switch the trigger off for their transaction and write one summary row. `network_audit_trail` view = network_audit_log ∪ infrastructure_audit_log (unchanged, D4); a legacy entry duplicating a trigger entry for the same change is folded into it. Versions (`design/versions.py`): the current version is the working state; freezing stores working set + inputs + boundary + settings (gzip JSON format 2, geometry as hex EWKB) and makes it immutable; frozen on save (named), before replacing/removing inputs, before auto design / import, before restore. Restore = the frozen state (same row ids) back as a NEW version (RESTORED), the replaced state kept. Compare matches by (kind, type, code) → added / removed / moved (distance) / changed (fields, cable length and previous line). Codes are never reused: the generator also counts codes of hard-deleted rows from the audit log (found in testing — a new FAT took a deleted FAT's code and compared as "moved"). Frontend: Versions drawer (save, list with what each held, view read-only, compare with current, restore after confirming; History tab for the design or one feature), compare overlay (removed red dashed, added green halo, moved ghost + arrow, rerouted cable's old line amber) with a key and jump-to list, History section in the live asset inspector, History button in design popups.

### Phase 9: Design & BOQ approval (standalone, D3)
- `approval/` module (§3.10): submit/approve/reject per step, validation gate, version lock, BOQ frozen at submission, notifications.
- Frontend: Submit dialog with the validation summary; a review panel with per-asset comments; approval timeline; BOQ approval view (quantities and diff against the previous BOQ revision); permission-gated actions.
- **Acceptance:** only a design version with an approved design **and** an approved BOQ can move to deployment.
- **As implemented (2026-09-30):** migration 0093 (`approval_requests` with the reserved `pipeline_stage_id`, `approval_steps`, `approval_comments`; one open request per design and subject; feature keys design.review / design.approve / boq.review / boq.approve with no grants copied — admins only until granted). `modules/approval/`: submitting a design runs validation (any ERROR refuses it; a design with no devices too), freezes the current version and locks the design (UNDER_REVIEW); steps ENGINEERING_REVIEW → LINE_MANAGER_APPROVAL, each decided only by a holder of its key (the same check as a route permission) and never by the person who submitted it (admins excepted); sending back needs a reason and starts a new current version for the revision (the reviewed one stays exactly as reviewed). The BOQ can be submitted only for the approved version; its quantities and street rows are frozen in the request as a numbered revision, compared with the previous revision; BOQ_REVIEW → BOQ_APPROVAL. Withdraw (submitter), reopen an approved design (new version; the approval stays on record). `gate()` = the current version's design approved AND a BOQ approved for it — what deployment checks. Reviewers and submitters are notified in-app. Timestamps use `clock_timestamp()` and requests are ordered by revision, so several steps in one transaction keep their order. Lifecycle tie-in: submitting sets the rows UNDER_REVIEW, a final design approval sets them APPROVED, and a reject / withdraw / reopen returns them to DESIGNED, so the deployment gate reads the same truth as the design status. Frontend: Review drawer (deployment gate chips, check-then-submit with the validation result, timelines per design version and BOQ revision, Approve / Send back with a reason — shown only when allowed, withdraw, reopen, BOQ quantities with changes since the last revision, comments pinned to a device / cable / spot and shown as pins on the map, resolvable).

### Phase 10: Deployment, as-built, promotion
- `POST /designs/{id}/deploy`; per-asset installation status (field role); as-built geometry kept alongside the design geometry, with a variance report; progress roll-ups per project/FDT; DEPLOYMENT map mode; QA → VERIFIED → `POST /designs/{id}/promote` (ACTIVE, `design_id` → NULL, no duplication).
- **Acceptance:** the brief's §48 end-to-end scenario, except the customer-link steps deferred by D5.
- **As implemented (2026-10-05):** migration 0094 — `net_assets.design_geom` / `asbuilt_geom`, the `deployments` table (status IN_PROGRESS | PROMOTED, one open deployment per design, RLS, `clock_timestamp()`), feature keys `deployment.update` / `asbuilt.capture` / `network.promote` (no grants copied — admins only until granted), and the audit trigger rebuilt to record a **promote** action (the audit function is parameterised, `dsg := coalesce(n->>'design_id', o->>'design_id')`, so the promoted row keeps its design id in the trail). `net_assets`/`net_cables` row images in the operation log and the version snapshots carry both geometry columns. `modules/deployment/`: **deploy** only through the Phase 9 gate (design version AND its BOQ approved) and only from APPROVED — one bulk update moves every row to CONSTRUCTION and keeps the designed position in `design_geom`, then writes the deployment record and one audit summary. **progress** takes `{items, action install|test|verify|fail, note}` and only legal lifecycle steps (CONSTRUCTION → INSTALLED → TESTING → VERIFIED, and TESTING → INSTALLED on a failure that needs a note); anything else comes back refused with its reason, so the field can't skip the chain. **as-built** writes `asbuilt_geom` and the new `geom` (cables get `route_method = IMPORTED`) and never touches `design_geom`. The **variance report** is designed against as-built: cable length (+ metres and %), device displacement. **Roll-ups**: counts per state, % installed and % verified, FATs installed x / y, cable km installed / planned, per-FDT (FATs installed, verified), `ready_to_promote` with the number still to verify. **promote** needs everything VERIFIED and no live-code clash (409 lists them), freezes the state as the version labelled "Promoted to the live network", then per row VERIFIED → ACTIVE and `design_id` → NULL with `lineage_id` = the row's own id, so `sync_derived_connections` rebuilds topology and the design's DEPLOYED and the deployment's PROMOTED with an audit summary and notifications. The design's rows move to `net_assets`/`net_cables` as they are — the same ids, so they simply appear in NETWORK mode with no copy. Frontend: **DEPLOYMENT** mode in the design panel (only once the gate can open), every device ringed and every cable overdrawn in its install state, the Deployment drawer (start with a field note, the progress bar and legend, % installed / verified, FATs and cable km, the per-FDT table, the field table filtered by state with bulk install / test / verify / fail, as-built capture by clicking the map for a device or along a cable's real route, the variance table, and promote behind a confirmation that says it cannot be undone). Deviations found in testing: the design features serializer exposes `geom` only — `design_geom`/`asbuilt_geom` are read through the deployment endpoint's variance, not as feature properties; a promotion writes one `promote` audit row per row *and* a summary row, so the design history shows the summary once.

### Phase 11: Operations, scale hardening, clean-up
- `outage_incidents.asset_id` + geometry; SmartOLT events resolve to OLT/ONU assets and mark them FAULTY; downstream trace computes the impacted endpoints; operations layers (incidents, LOS, power, outages, field work).
- Load test with 100k assets (tile latency, cache hit rate); move the dashboard MiniMap to MapLibre; remove the Leaflet deps; make the legacy upload tables read-only.
- Deliverables (brief §47): architecture, schema + ERD, API, lifecycle, migration, testing, setup, maintenance, performance, limitations, extension points (customer link D5, pipeline link D3, auto-fill around locked assets).

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| Clearing sites/nodes breaks SmartOLT sync, the capacity monitor or the dashboard | Repoint all seven dependents (§1.2) in the same phase; regression tests for each before the endpoints are removed |
| The engine's repair passes assume batch invariants | v1 recalculation only reroutes and recounts; re-clustering = full regenerate → new version |
| The output adapter loses engine semantics | Keep all engine attributes in `attributes`; golden adapter test; raw output archived |
| MapLibre needs WebGL: old GPUs, remote desktops, jsdom tests | Detect and show a clear message if WebGL is unavailable; mock in unit tests; Playwright for real rendering |
| MVT cache staleness after edits | Invalidate by bbox on every write; design working sets use GeoJSON, not tiles |
| RLS forgotten on a new table | Test asserting RLS is enabled on every `net_*`, `design*`, `approval*` table |
| Your uncommitted working-tree changes | I won't commit; each phase lists the files it touched |
| 8 GB RAM machine | `--no-file-parallelism`, raised tsc heap, engine only against small fixtures locally |

## 8. Files

**Modified:** `App.tsx`, `pages/infrastructure/InfrastructurePage.tsx`, `api/index.ts`, `api/design.api.ts`, `pages/projects/ProjectDetailPage.tsx`, `pages/fttx-designer/FttxDesignerWizardPage.tsx` (form extraction), `infrastructure/router.py` + `upload_service.py`, `network/{router,service,cable_service,attributes,codes,upload,topology,topology_service,utilisation}.py`, `network/audit.py`, `design/{__init__,models,inputs,engine_bridge,hydrator,adapters,auto_design,operations,snap,recalc,versions,audit,boq_service,validation_service,routing_service,schemas,service,router}.py`, `approval/{__init__,service,router}.py`, `deployment/{__init__,service,router}.py`, `tasks/infrastructure_sync.py`, `tasks/capacity_monitor.py`, `tasks/metric_snapshots.py`, `tasks/fttx_design_run.py`, `dashboard/router.py`, `all_modules.py` (org summary; OutageIncident in Phase 11), `fttx_designer/models.py` + router, `scripts/seed.py`, `infrastructure/nginx/nginx.conf` (CSP), `shared-types/index.ts`, `package.json`.

**Not modified:** `fttx_designer/engine/**` core algorithms, `geometry_compat/**`, auth/tenant middleware, task-engine internals, existing migrations 0001–0086, the glass/token system, the `customers` module (D5).
