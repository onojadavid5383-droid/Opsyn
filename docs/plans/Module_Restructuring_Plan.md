# OpSyn Module Restructuring Plan

**Document Version:** 1.0  
**Date:** 2026-10-09  
**Author:** System Design Team  
**Status:** Draft for Review

---

## Executive Summary

This document outlines the architectural restructuring of OpSyn's Task, Project, and Engineering modules to create a more intuitive and scalable operational intelligence platform. The restructuring consolidates internal and external task management under a unified Task module, while repositioning the Engineering module as the central hub for infrastructure and project lifecycle management.

---

## 1. Current State Analysis

### 1.1 Existing Architecture

**Current Module Structure:**

| Module | Purpose | Key Features |
|--------|---------|--------------|
| **Tasks** | Internal task management | Kanban boards, assignment, workflow, comments, dependencies |
| **Projects** | External task handling | Pipeline templates, stages, approvals, department routing |
| **Engineering** | Infrastructure records | Sites, nodes, OLTs, ports, GIS/map data, capacity monitoring |

### 1.2 Current Pain Points

1. **Cognitive Split:** Users must navigate between Tasks and Projects to understand their full workload
2. **Unclear Boundaries:** The internal vs. external distinction is implementation-focused, not user-focused
3. **Engineering Scope:** Currently limited to infrastructure assets without project design/deployment lifecycle
4. **Design Workflow Gap:** No structured flow from design → BOQ → deployment → as-built documentation

---

## 2. Proposed Architecture

### 2.1 New Module Structure

```
┌─────────────────────────────────────────────────────────────┐
│                         TASKS MODULE                         │
│  Unified task management for all operational work           │
├─────────────────────────────────────────────────────────────┤
│  ├─ Internal Tasks (department-specific work)               │
│  └─ External Tasks (cross-department workflows)             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      ENGINEERING MODULE                      │
│  Complete infrastructure & project lifecycle management     │
├─────────────────────────────────────────────────────────────┤
│  ├─ Infrastructure                                          │
│  │   ├─ Sites & Nodes                                       │
│  │   ├─ OLTs & Ports                                        │
│  │   ├─ GIS/Map View                                        │
│  │   └─ Capacity Monitoring                                 │
│  │                                                           │
│  └─ Projects                                                 │
│      ├─ Design                                               │
│      │   ├─ Auto Design (AI-assisted network design)        │
│      │   └─ Manual Design (engineer-created designs)        │
│      │                                                       │
│      ├─ BOQ (Bill of Quantities)                            │
│      │   ├─ Design-linked items                             │
│      │   └─ Products (non-design items)                     │
│      │                                                       │
│      └─ Deployment                                           │
│          ├─ Proposed (approved, ready to deploy)            │
│          └─ As-Built (post-deployment documentation)        │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Design Specifications

### 3.1 Tasks Module (Restructured)

#### 3.1.1 Unified Task Interface

**Top-Level Navigation:**
```
Tasks
├─ My Tasks (personal view)
├─ All Tasks
│   ├─ Internal Tasks (tab/filter)
│   └─ External Tasks (tab/filter)
├─ Department Inbox
├─ Board Views (Kanban/Pipeline/Status)
├─ Calendar & Gantt
└─ Analytics
```

#### 3.1.2 Task Scope Discrimination

**Database Schema (Minimal Changes):**
- Leverage existing `task_scope` field: `{"internal", "external"}`
- Retain `source_app` field for tracking task origin
- Keep existing `pipeline_stage` for unified workflow tracking

**UI Differentiation:**
```typescript
// Visual indicators
Internal Tasks: 
  - Badge: "Internal" (blue)
  - Icon: Building/Department icon
  - Routing: Within department only

External Tasks:
  - Badge: "External" (green)  
  - Icon: Transfer/Exchange icon
  - Routing: Cross-department workflows
  - Auto-generates project when needed
```

#### 3.1.3 Unified Board View

**Board Configuration:**
```
[ All Tasks ] [ Internal ] [ External ] [ My Tasks ]
     ↑ Tabs/Filters

Columns: New | Assigned | In Progress | Review | Done | Archived
         (Pipeline stages apply to both internal and external)
```

**Card Display:**
- Show scope badge on each card
- Display department routing history for external tasks
- Highlight cross-department handoffs

---

### 3.2 Engineering Module (Expanded)

#### 3.2.1 Top-Level Structure

**Navigation:**
```
Engineering
├─ Infrastructure
│   ├─ Map View
│   ├─ Sites & Nodes
│   ├─ OLT Management
│   ├─ Capacity Monitoring
│   ├─ Uploads
│   └─ Audit
│
└─ Projects
    ├─ Design
    │   ├─ Auto Design
    │   └─ Manual Design
    │
    ├─ BOQ (Bill of Quantities)
    │   ├─ Design Items
    │   └─ Products
    │
    └─ Deployment
        ├─ Proposed
        └─ As-Built
```

---

### 3.2.2 Projects Subsection: Design

#### A. Auto Design (FTTx Designer Integration)

**Purpose:** Automated network design using the integrated FTTx Designer engine for FTTx/GPON deployment

**Existing Integration:** OpSyn already has a complete FTTx Designer automation integrated (migrations 0085-0091, Network GIS Phase 5), which:
- Accepts road networks, homepass locations, and existing pole structures
- Runs a sophisticated topology/cascade/routing engine via Celery
- Generates optimized FDTs (Fibre Distribution Terminals), FATs (Fibre Access Terminals), cable routes, and support structures
- Calculates Bill of Quantities (BOQ) automatically
- Produces detailed engineering documents (DED reports)
- Supports aerial deployment with underground/drainage strategies in development

**Enhanced Features (Integrated with Projects):**
- **Design Container:** Links FTTx runs to project lifecycle (existing: `designs` and `design_versions` tables)
- **Input Management:** Upload road networks, homepasses, poles, buildings, pickups (GeoJSON, Shapefile, KML, GeoPackage)
- **Configuration Wizard:** Deployment type (aerial/underground/drainage), splitter patterns, distance constraints, cascade architecture
- **Engine Parameters:**
  - Max box-to-box distance, max box-to-customer distance
  - Splitter patterns (1:2, 1:4, 1:8, 1:16, 1:32)
  - Cascade architecture (PCC/Legacy), PON architecture (Single/Dual)
  - Coverage percentage, growth reserve
  - Pole spacing, marker intervals
- **Live Network Integration:** Existing poles from infrastructure database are offered as structures
- **Boundary-Based Design:** Draw coverage area on map; engine designs within boundary
- **Real-time Progress:** Celery task with progress updates (topology → FAT → FDT → wings → routing → BOQ → validation)
- **Results Visualization:** Interactive map preview of generated network (FDTs, FATs, cables, poles)
- **BOQ Auto-Generation:** Material quantities calculated from design output
- **Version Control:** Each run creates a design version; previous states preserved

**Database Schema (Already Implemented):**
```sql
-- Core design container (migration 0090_design_container.py)
CREATE TABLE designs (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    name VARCHAR(200) NOT NULL,
    design_status VARCHAR(30) DEFAULT 'draft',
    -- 'draft' | 'under_review' | 'approved' | 'rejected' | 'archived'
    boundary GEOMETRY(Polygon, 4326),
    project_id UUID REFERENCES projects(id),
    ...
);

CREATE TABLE design_versions (
    id UUID PRIMARY KEY,
    design_id UUID NOT NULL REFERENCES designs(id),
    version_number INTEGER NOT NULL,
    creation_method VARCHAR(30) NOT NULL, -- 'AUTO' | 'MANUAL' | 'IMPORTED'
    is_current BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    ...
);

-- FTTx engine runs (migration 0085_fttx_designer_runs.py)
CREATE TABLE fttx_design_runs (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    design_id UUID REFERENCES designs(id),
    design_version_id UUID REFERENCES design_versions(id),
    name VARCHAR(200),
    status VARCHAR(20), -- 'draft' | 'queued' | 'running' | 'completed' | 'failed'
    config JSONB NOT NULL, -- Full FTTx engine parameters
    progress_pct INTEGER DEFAULT 0,
    progress_message VARCHAR(200),
    celery_task_id VARCHAR(100),
    result_summary JSONB,
    ...
);

CREATE TABLE fttx_design_run_outputs (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES fttx_design_runs(id),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    output_layers JSONB NOT NULL, -- FDTs, FATs, cables, poles, etc.
    boq_rows JSONB,
    boq_fdt_rows JSONB,
    optical_loss_summary JSONB,
    ...
);

-- Network assets (live and design) - existing infrastructure integration
CREATE TABLE net_assets (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    design_id UUID REFERENCES designs(id), -- NULL = live network
    asset_type VARCHAR(20), -- 'FAT' | 'FDT' | 'POLE' | 'CLOSURE' | 'CABINET' | 'OLT'
    asset_code VARCHAR(100),
    lifecycle_status VARCHAR(30), -- 'DESIGN' | 'PROPOSED' | 'APPROVED' | 'ORDERED' | 'INSTALLED' | 'LIVE' | 'DECOMMISSIONED'
    geom GEOMETRY(Point, 4326),
    properties JSONB,
    ...
);

CREATE TABLE net_cables (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    design_id UUID REFERENCES designs(id),
    cable_category VARCHAR(30), -- 'FEEDER' | 'DISTRIBUTION' | 'DROP'
    from_asset_id UUID REFERENCES net_assets(id),
    to_asset_id UUID REFERENCES net_assets(id),
    geom GEOMETRY(LineString, 4326),
    cable_type VARCHAR(50),
    fibre_count INTEGER,
    ...
);
```

**UI Flow (Existing and Enhanced):**
1. **Create Auto Design:**
   - Navigate to Engineering > Projects > Design > Auto Design
   - Create new design with name and boundary (draw on map)
   - Upload input layers (roads, homepasses, poles) or import from existing sources
   - Configure engine parameters (deployment type, splitter ratios, distances)
   - Preview input layers on map with validation summary

2. **Run Auto Design:**
   - Launch FTTx Designer engine (Celery task)
   - Monitor progress with real-time updates (topology analysis, FAT generation, FDT placement, cable routing)
   - View pipeline stage checklist
   - Receive notifications on completion/failure

3. **Review Results:**
   - Interactive map preview (FDTs, FATs, cables, poles, closures)
   - Layer controls with visibility toggles
   - Click assets to inspect properties
   - BOQ table with material quantities
   - Validation findings list (warnings, errors)
   - Design metrics (total FDTs, FATs, cable length, homes passed)

4. **Iterate or Approve:**
   - Adjust parameters and re-run (creates new version)
   - Compare versions
   - Export results (GeoPackage, Shapefile, GeoJSON)
   - Generate DED (Detailed Engineering Design) report
   - Submit for review or approve

#### B. Manual Design (Enhanced CAD/GIS Integration)

**Purpose:** Engineer-controlled design with integrated CAD, QGIS, and Google Earth Pro capabilities, leveraging existing network equipment and infrastructure

**Core Principle:** Manual design builds upon the same network map infrastructure used by Auto Design, providing engineers with direct control over asset placement and cable routing using familiar GIS/CAD paradigms while accessing all equipment already integrated into the system.

**Integrated Equipment & Infrastructure (Already Available):**
From the existing `net_assets` and infrastructure database:
- **Active Network Equipment:**
  - OLTs (Optical Line Terminals) with port inventory
  - Cabinets and splitter boxes
  - FATs and FDTs from previous designs
  - Poles with coordinates and attributes
  - Manholes, handholes, chambers
  - Fibre routes and capacity data
  
- **Infrastructure Sites:**
  - POPs (Points of Presence)
  - Hubs and data centers
  - Network nodes
  - Geographic coverage areas

**Drawing Capabilities (Multi-Paradigm Approach):**

**1. AutoCAD-Style Drawing:**
- **Precision Tools:**
  - Coordinate input (latitude/longitude, UTM)
  - Distance and bearing input
  - Snap to grid/existing assets
  - Perpendicular/parallel line tools
  - Offset and fillet commands
  - Array and mirror for symmetric layouts
  
- **Layer Management:**
  - Separate layers for cables, assets, annotations, construction
  - Layer visibility and lock controls
  - Style and symbology per layer
  
- **Measurement & Annotation:**
  - Distance measurement along routes
  - Area calculation for coverage zones
  - Elevation profiles (where terrain data available)
  - Text labels and dimension lines

**2. QGIS-Style Geospatial Analysis:**
- **Spatial Operations:**
  - Buffer zones around assets
  - Service area polygons
  - Line-of-sight analysis
  - Proximity analysis (find assets within X meters)
  - Topology validation (gaps, overlaps, dangles)
  
- **Attribute Management:**
  - Field calculator for computed properties
  - Join attributes from tables
  - Classify and symbolize by attributes
  - Query builder for filtering
  
- **Geoprocessing:**
  - Clip design to boundary
  - Merge/dissolve cable segments
  - Intersection and union operations
  - Shortest path routing along road network

**3. Google Earth Pro-Style 3D Visualization:**
- **Terrain Integration:**
  - Drape cables over terrain surface
  - Calculate cable length accounting for elevation
  - Pole height visualization
  - Underground vs. aerial route distinction
  
- **Basemap Layers:**
  - Satellite imagery
  - Street maps
  - Terrain/topographic maps
  - Hybrid overlays
  
- **Measurement Tools:**
  - Ground distance vs. 3D distance
  - Elevation profiles along routes
  - Viewshed analysis from pole locations

**Design Workflow:**

**Phase 1: Setup & Context**
```typescript
// Manual design initialization
1. Create Design
   - Name and description
   - Draw design boundary on map
   - Set project reference (if applicable)
   - Select base layers (satellite, streets, terrain)

2. Load Context
   - Display existing network equipment within/near boundary
   - Show live poles, cabinets, OLTs, cables
   - Load road networks for routing
   - Import building/homepass data if available
   - Display infrastructure sites (POPs, hubs)
```

**Phase 2: Asset Placement**
```typescript
// Drawing tools activated
3. Place Distribution Points (FDTs)
   - Click to place or enter coordinates
   - Snap to existing poles/structures
   - Auto-populate from equipment catalog
   - Set properties: name, capacity, splitter config, serving area
   
4. Place Access Points (FATs)
   - Draw along roads or paths
   - Use array tool for regular spacing
   - Link to upstream FDT
   - Calculate customers served
   
5. Place Support Structures
   - Select pole type from catalog
   - Click to place on map
   - Snap to existing poles
   - Set height, type, capacity
   - Mark as existing or proposed
```

**Phase 3: Cable Routing**
```typescript
6. Route Cables
   - Draw cable routes manually (polyline tool)
   - Auto-route along roads using network
   - Snap to placed assets (FDTs, FATs, poles)
   - Set cable properties:
     * Cable type (feeder, distribution, drop)
     * Fibre count
     * Installation method (aerial, underground, duct)
     * Start/end connections
   
7. Topology Rules
   - Validate connectivity (all assets connected)
   - Check for loops or dead ends
   - Verify cascade hierarchy (OLT → FDT → FAT → Customer)
   - Ensure no overlapping routes (unless intentional)
```

**Phase 4: Validation & Refinement**
```typescript
8. Run Validation Checks
   - Distance constraints (max FDT-to-FAT, FAT-to-customer)
   - Capacity checks (don't exceed splitter ratios)
   - Topology checks (connectivity, cascade levels)
   - Standards compliance (burial depth, pole spacing)
   
9. Optimize
   - Adjust routes for efficiency
   - Rebalance customer assignments
   - Minimize cable length
   - Review cost implications
   
10. Calculate BOQ
    - Extract all assets from design
    - Count equipment (FDTs, FATs, poles, splitters, closures)
    - Measure cable lengths by type
    - Link to product catalog for non-design items
```

**Technical Implementation:**

**Frontend Components:**
```typescript
// Engineering > Projects > Design > Manual Design

ManualDesignWorkspace.tsx
├─ DesignMapCanvas (MapLibre GL JS with terrain, basemap switching)
├─ DesignToolbar
│  ├─ DrawingTools (point, line, polygon, snap, measure)
│  ├─ SelectionTools (select, move, edit vertices)
│  ├─ AnalysisTools (buffer, proximity, route)
│  └─ ViewTools (2D/3D, basemap, layers)
├─ AssetPalette (equipment catalog - drag to place)
├─ LayerPanel (visibility, style, order)
├─ PropertiesPanel (selected asset attributes)
├─ ValidationPanel (real-time constraint checking)
└─ DesignInspector (asset list, relationships, metrics)
```

**Drawing Engine Integration:**
- **Leaflet.PM or MapLibre Draw:** For basic shapes, snapping, vertex editing
- **Turf.js:** Spatial analysis (buffers, intersections, shortest paths)
- **MapLibre GL JS:** Vector tiles, 3D terrain, basemap sources
- **Custom Canvas Overlay:** Precision CAD-style drawing with coordinate input

**Data Model:**
```sql
-- Manual design uses the SAME net_assets and net_cables tables as auto design
-- Differentiator: creation_method in design_versions

-- Manual design actions
CREATE TABLE design_edit_log (
    id UUID PRIMARY KEY,
    design_id UUID NOT NULL REFERENCES designs(id),
    design_version_id UUID NOT NULL REFERENCES design_versions(id),
    action_type VARCHAR(30), -- 'asset_added' | 'asset_moved' | 'asset_deleted' | 'cable_routed' | 'property_changed'
    target_type VARCHAR(30), -- 'asset' | 'cable'
    target_id UUID,
    changes JSONB,
    edited_by UUID REFERENCES users(id),
    edited_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Validation Engine:**
```python
# backend/app/modules/design/validation_service.py (already exists)
# Enhanced with manual design rules

def validate_manual_design(design_id: uuid.UUID) -> ValidationResult:
    """
    Checks:
    - All FDTs connected to feeder cables
    - All FATs connected to distribution cables
    - Distance constraints (configurable per tenant)
    - Capacity constraints (splitter ratios)
    - Topology (no orphaned assets, valid cascade)
    - Standards compliance
    """
    findings = []
    # ... validation logic
    return ValidationResult(is_valid=len(findings)==0, findings=findings)
```

**UI Flow:**
1. **Create Manual Design:**
   - Engineering > Projects > Design > Manual Design > New
   - Enter name, description, select project (optional)
   - Draw boundary on map or skip for unbounded
   - Choose base map (satellite, street, terrain, hybrid)

2. **Design Environment Setup:**
   - Map loads with existing network equipment visible
   - Asset palette shows equipment catalog (OLTs, FDTs, FATs, poles, cables, closures)
   - Layer panel shows design layers + live network layers (dimmed)
   - Drawing toolbar activates

3. **Create Design:**
   - **Place Assets:** Click tool → click map → properties dialog → confirm
   - **Draw Cables:** Polyline tool → click waypoints → snap to assets → set properties
   - **Use Templates:** Load standard design patterns (star, tree, ring topologies)
   - **Import from AutoCAD/QGIS:** Upload DXF, Shapefile, GeoJSON with layer mapping

4. **Validate & Iterate:**
   - Real-time validation hints (red highlights for violations)
   - Run full validation check
   - Review findings panel
   - Adjust design to fix issues

5. **Calculate BOQ:**
   - Click "Generate BOQ" button
   - System extracts all design assets and cables
   - Quantities calculated automatically
   - Open BOQ editor to add products

6. **Save & Approve:**
   - Save as draft (version created)
   - Submit for review
   - Reviewer markup tools
   - Approval workflow

---

### 3.2.3 Projects Subsection: BOQ (Bill of Quantities)

**Purpose:** Generate material and cost estimates from approved designs

#### A. Design-Linked Items

**Source:** Automatically pulled from approved project designs

**Features:**
- **Auto-Generation:** Parse design_items → BOQ line items
- **Quantity Rollup:** Aggregate quantities by item type
- **Unit Costs:** Apply pricing from product catalog
- **Cost Estimation:** Calculate total material cost
- **Real-time Sync:** Update BOQ when design changes (before final approval)

#### B. Products (Non-Design Items)

**Purpose:** Items needed for project but not in design (consumables, tools, services)

**Examples:**
- Installation labor
- Testing equipment rental
- Trenching/ducting
- Permits and fees
- Safety equipment
- Documentation/training

**Database Schema:**
```sql
CREATE TABLE project_boq (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    project_id UUID NOT NULL REFERENCES projects(id),
    design_id UUID REFERENCES project_designs(id),
    
    boq_status VARCHAR(30) DEFAULT 'draft', -- 'draft' | 'submitted' | 'approved' | 'rejected'
    total_material_cost NUMERIC(15, 2),
    total_product_cost NUMERIC(15, 2),
    total_cost NUMERIC(15, 2),
    
    submitted_by UUID REFERENCES users(id),
    approved_by UUID REFERENCES users(id),
    submitted_at TIMESTAMPTZ,
    approved_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE boq_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    boq_id UUID NOT NULL REFERENCES project_boq(id) ON DELETE CASCADE,
    
    item_source VARCHAR(20) NOT NULL, -- 'design' | 'product'
    design_item_id UUID REFERENCES design_items(id),
    product_id UUID REFERENCES products(id),
    
    item_code VARCHAR(100),
    item_name VARCHAR(200) NOT NULL,
    description TEXT,
    quantity NUMERIC(15, 3) NOT NULL,
    unit VARCHAR(50) NOT NULL,
    unit_cost NUMERIC(15, 2),
    total_cost NUMERIC(15, 2),
    
    supplier VARCHAR(200),
    lead_time_days INTEGER,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    
    product_code VARCHAR(100) UNIQUE NOT NULL,
    product_name VARCHAR(200) NOT NULL,
    category VARCHAR(100), -- 'consumable' | 'labor' | 'equipment_rental' | 'permit' | 'service'
    description TEXT,
    unit VARCHAR(50) NOT NULL,
    standard_cost NUMERIC(15, 2),
    
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**UI Flow:**
1. **BOQ Creation:**
   - Link to approved design
   - Auto-import design items
   - Add product items from catalog
   - Apply unit costs
   - Review totals

2. **BOQ Approval:**
   - Submit for finance/procurement review
   - Approval workflow
   - Export to PDF/Excel

---

### 3.2.4 Projects Subsection: Deployment

#### A. Proposed Projects

**Purpose:** Approved projects ready for deployment

**Entry Criteria:**
- Design approved ✓
- BOQ approved ✓
- Budget allocated ✓
- Resources assigned ✓

**Features:**
- **Deployment Planning:** Schedule, team assignment, milestones
- **Resource Allocation:** Assign crews, equipment, materials
- **Progress Tracking:** Linked to task system
- **Milestone Management:** Key checkpoints and approvals
- **Risk Register:** Track blockers and issues

**Database Schema:**
```sql
ALTER TABLE projects ADD COLUMN deployment_status VARCHAR(30) DEFAULT 'not_ready';
-- 'not_ready' | 'proposed' | 'in_deployment' | 'completed' | 'as_built_documented'

CREATE TABLE project_deployment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    project_id UUID NOT NULL REFERENCES projects(id),
    
    deployment_type VARCHAR(30), -- 'new_build' | 'upgrade' | 'extension'
    planned_start_date DATE,
    planned_end_date DATE,
    actual_start_date DATE,
    actual_end_date DATE,
    
    assigned_crew_id UUID REFERENCES teams(id),
    crew_lead_id UUID REFERENCES users(id),
    
    deployment_status VARCHAR(30) DEFAULT 'planned', -- 'planned' | 'active' | 'paused' | 'completed'
    completion_pct INTEGER DEFAULT 0,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE deployment_milestones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    deployment_id UUID NOT NULL REFERENCES project_deployment(id) ON DELETE CASCADE,
    
    milestone_name VARCHAR(200) NOT NULL,
    milestone_order INTEGER NOT NULL,
    due_date DATE,
    completed_date DATE,
    status VARCHAR(30) DEFAULT 'pending', -- 'pending' | 'in_progress' | 'completed' | 'blocked'
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**UI Flow:**
1. **View Proposed Projects:**
   - List of approved, deployment-ready projects
   - Filter by region, type, priority
   - View design and BOQ summaries

2. **Initiate Deployment:**
   - Create deployment plan
   - Assign crew and resources
   - Set milestones
   - Generate deployment tasks
   - Move to "In Deployment"

#### B. As-Built Documentation

**Purpose:** Final documentation of deployed infrastructure

**Entry Criteria:**
- Deployment completed ✓
- Site acceptance testing passed ✓
- Physical verification done ✓

**Features:**
- **As-Built Design:** Actual deployed configuration vs. original design
- **Variance Reporting:** Document deviations from design
- **Photo Documentation:** Site photos, equipment labels
- **Testing Results:** Acceptance test reports
- **Infrastructure Registration:** Update infrastructure database
- **GIS Layer:** Add as-built to map

**Database Schema:**
```sql
CREATE TABLE project_as_built (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    project_id UUID NOT NULL REFERENCES projects(id),
    deployment_id UUID NOT NULL REFERENCES project_deployment(id),
    design_id UUID REFERENCES project_designs(id),
    
    as_built_status VARCHAR(30) DEFAULT 'in_progress', -- 'in_progress' | 'submitted' | 'verified' | 'finalized'
    
    -- Design variance
    design_variance_pct NUMERIC(5, 2),
    variance_notes TEXT,
    
    -- Documentation
    as_built_data JSONB, -- Actual deployed configuration
    test_results JSONB,
    photos JSONB, -- Array of photo URLs
    
    -- Approval
    submitted_by UUID REFERENCES users(id),
    verified_by UUID REFERENCES users(id),
    submitted_at TIMESTAMPTZ,
    verified_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE as_built_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    as_built_id UUID NOT NULL REFERENCES project_as_built(id) ON DELETE CASCADE,
    design_item_id UUID REFERENCES design_items(id),
    
    item_type VARCHAR(50) NOT NULL,
    item_name VARCHAR(200) NOT NULL,
    actual_quantity NUMERIC(15, 3),
    variance_quantity NUMERIC(15, 3),
    
    actual_location GEOMETRY(Point, 4326),
    installed_date DATE,
    serial_numbers TEXT[],
    
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**UI Flow:**
1. **Create As-Built Record:**
   - Import original design
   - Document actual deployment
   - Mark variances
   - Upload photos and test results

2. **As-Built Verification:**
   - Field team verification
   - Senior engineer review
   - Finalize documentation
   - Update infrastructure database
   - Close project

---

## 4. Migration Strategy

### 4.1 Database Migration Plan

**Phase 1: New Schema (Additive Only)**
```sql
-- Add new tables without touching existing ones
-- migration: 0084_engineering_projects_schema.sql
```

**Phase 2: Data Seeding**
- Create default product catalog
- Seed design templates
- Create initial workflow configurations

**Phase 3: Backend Service Layer**
- Implement design service
- Implement BOQ service
- Implement deployment service
- Implement as-built service

**Phase 4: Frontend Implementation**
- Engineering module UI
- Projects subsection navigation
- Design interfaces (auto + manual)
- BOQ management UI
- Deployment tracking UI
- As-built documentation UI

**Phase 5: Integration**
- Link existing projects to new workflow
- Task generation from deployment milestones
- Infrastructure database updates from as-built

**Phase 6: Data Migration (If Needed)**
- Migrate existing project data to new structure
- Preserve audit history
- Validate data integrity

### 4.2 Backward Compatibility

**Preserve Existing Functionality:**
- All existing Task APIs remain functional
- All existing Project APIs remain functional
- No breaking changes to external integrations
- Maintain webhook contracts

**Deprecation Path:**
- Mark old endpoints as deprecated (not removed)
- Dual-write to old and new structures during transition
- Provide migration timeline to API consumers

---

## 5. UI/UX Design Guidelines

### 5.1 Tasks Module Navigation

**Before:**
```
- Tasks (internal only)
- Projects (external only)
```

**After:**
```
Tasks
├─ My Tasks
├─ All Tasks
│   └─ Filter: [ Internal ] [ External ]
├─ Department Inbox
└─ Analytics
```

### 5.2 Engineering Module Navigation

**Before:**
```
Engineering (infrastructure only)
```

**After:**
```
Engineering
├─ Infrastructure
│   └─ (existing features)
└─ Projects ← NEW
    ├─ Design
    ├─ BOQ
    └─ Deployment
```

### 5.3 Visual Design Patterns

**Task Scope Badges:**
```
[Internal] → Blue badge, building icon
[External] → Green badge, transfer icon
```

**Project Lifecycle Status:**
```
Design Stage     → Purple
BOQ Stage        → Orange
Proposed         → Blue
In Deployment    → Yellow
As-Built         → Green
```

**Navigation Breadcrumbs:**
```
Engineering > Projects > Design > Auto Design > [Design Name]
Engineering > Projects > Deployment > Proposed > [Project Name]
```

---

## 6. API Contracts

### 6.1 Tasks API (Updated)

**Unified Task Listing:**
```http
GET /api/v1/tasks?scope={internal|external|all}
GET /api/v1/tasks/board?scope={internal|external|all}
```

**Task Creation (Scope Required):**
```http
POST /api/v1/tasks
{
  "title": "string",
  "task_scope": "internal|external",
  "department_id": "uuid",
  ...
}
```

### 6.2 Engineering Projects API (New)

**Design Management:**
```http
POST /api/v1/engineering/designs
GET /api/v1/engineering/designs/{id}
PUT /api/v1/engineering/designs/{id}
POST /api/v1/engineering/designs/{id}/approve
POST /api/v1/engineering/designs/{id}/auto-generate
```

**BOQ Management:**
```http
POST /api/v1/engineering/boq
GET /api/v1/engineering/boq/{id}
POST /api/v1/engineering/boq/{id}/items
POST /api/v1/engineering/boq/{id}/approve
GET /api/v1/engineering/boq/{id}/export
```

**Deployment Management:**
```http
GET /api/v1/engineering/deployments/proposed
POST /api/v1/engineering/deployments
PUT /api/v1/engineering/deployments/{id}/milestones
GET /api/v1/engineering/deployments/{id}/progress
```

**As-Built Documentation:**
```http
POST /api/v1/engineering/as-built
PUT /api/v1/engineering/as-built/{id}
POST /api/v1/engineering/as-built/{id}/verify
POST /api/v1/engineering/as-built/{id}/finalize
```

---

## 7. RBAC Considerations

### 7.1 New Permissions

```typescript
// Design permissions
"engineering.designs.view"
"engineering.designs.create"
"engineering.designs.edit"
"engineering.designs.approve"
"engineering.designs.auto_generate"

// BOQ permissions
"engineering.boq.view"
"engineering.boq.create"
"engineering.boq.edit"
"engineering.boq.approve"

// Deployment permissions
"engineering.deployments.view"
"engineering.deployments.create"
"engineering.deployments.manage"
"engineering.deployments.assign_crew"

// As-Built permissions
"engineering.as_built.view"
"engineering.as_built.create"
"engineering.as_built.verify"
"engineering.as_built.finalize"
```

### 7.2 Role Assignments

| Role | Design | BOQ | Deployment | As-Built |
|------|--------|-----|------------|----------|
| Network Engineer | Create, Edit | View | View | Create, Edit |
| Senior Engineer | Create, Edit, Approve | View, Approve | View, Manage | Verify |
| Engineering Manager | All | All | All | All |
| Field Technician | View | View | View assigned | Create, Edit |
| Finance/Procurement | - | View, Approve | View | - |

---

## 8. Testing Strategy

### 8.1 Unit Tests

- Task scope filtering logic
- BOQ calculation algorithms
- Design validation rules
- As-built variance calculations

### 8.2 Integration Tests

- Task creation flow (internal vs external)
- Design → BOQ → Deployment pipeline
- Infrastructure database updates from as-built
- Cross-module task generation

### 8.3 E2E Tests

**Critical User Journeys:**
1. Create external task → View in unified board
2. Create auto design → Generate BOQ → Approve → Propose deployment
3. Initiate deployment → Track progress → Document as-built
4. Create manual design → Review → Approve → Link to project

---

## 9. Performance Considerations

### 9.1 Database Indexes

```sql
-- Task scope queries
CREATE INDEX idx_tasks_scope ON tasks(task_scope, status, department_id);
CREATE INDEX idx_tasks_scope_assignee ON tasks(task_scope, assignee_user_id, status);

-- Design queries
CREATE INDEX idx_designs_status ON project_designs(design_status, project_id);
CREATE INDEX idx_designs_type ON project_designs(design_type, tenant_id);

-- BOQ queries
CREATE INDEX idx_boq_project ON project_boq(project_id, boq_status);
CREATE INDEX idx_boq_items_source ON boq_items(boq_id, item_source);

-- Deployment queries
CREATE INDEX idx_deployment_status ON project_deployment(deployment_status, planned_start_date);
CREATE INDEX idx_as_built_status ON project_as_built(as_built_status, project_id);
```

### 9.2 Caching Strategy

- Cache design templates
- Cache product catalog
- Cache BOQ calculations (invalidate on item changes)
- Cache deployment progress calculations

---

## 10. Documentation Requirements

### 10.1 User Documentation

- **User Guide:** "Working with Tasks" (internal vs external)
- **User Guide:** "Engineering Projects Workflow"
- **User Guide:** "Creating Auto Designs"
- **User Guide:** "BOQ Management"
- **User Guide:** "Deployment Tracking"
- **User Guide:** "As-Built Documentation"

### 10.2 Technical Documentation

- API documentation (Swagger/OpenAPI updates)
- Database schema diagrams
- Service architecture diagrams
- Migration runbooks

---

## 11. Success Metrics

### 11.1 User Adoption

- % of users using unified task view vs. legacy views
- Task view switching frequency (internal ↔ external)
- Time spent in Engineering > Projects section

### 11.2 Operational Efficiency

- Time from design approval to deployment initiation
- BOQ generation time (auto vs. manual)
- As-built documentation completion rate
- Design-to-deployment cycle time

### 11.3 Data Quality

- As-built variance percentage (target: <5%)
- BOQ accuracy (actual vs. estimated costs)
- Infrastructure database completeness from as-built

---

## 12. Risk Assessment

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| User confusion during transition | High | Medium | Phased rollout, in-app guidance, training |
| Data migration errors | Critical | Low | Extensive testing, rollback plan, dual-write period |
| Performance degradation | Medium | Low | Load testing, query optimization, caching |
| Incomplete as-built adoption | Medium | Medium | Workflow enforcement, training, audits |
| API breaking changes | High | Low | Backward compatibility layer, deprecation timeline |

---

## 13. Implementation Timeline

**Phase 1 (Weeks 1-2): Planning & Design**
- Finalize UI mockups
- Review database schema
- API contract approval

**Phase 2 (Weeks 3-5): Backend Foundation**
- Database migration (0084)
- Service layer implementation
- API endpoints

**Phase 3 (Weeks 6-9): Frontend Implementation**
- Tasks module restructuring
- Engineering > Projects subsections
- Design interfaces

**Phase 4 (Weeks 10-11): Integration & Testing**
- E2E testing
- Performance testing
- Security review

**Phase 5 (Week 12): Deployment**
- Staging deployment
- User acceptance testing
- Production rollout

**Phase 6 (Week 13+): Monitoring & Iteration**
- User feedback collection
- Bug fixes
- Feature refinements

---

## 14. Approval & Sign-Off

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Product Owner | | | |
| Engineering Lead | | | |
| UX/UI Lead | | | |
| Database Architect | | | |
| QA Lead | | | |

---

## Appendix A: Database Schema Diagrams

```
[Visual diagrams to be added in final version]

- Task scope relationship diagram
- Engineering projects ERD
- Design → BOQ → Deployment flow
- Infrastructure linkage diagram
```

---

## Appendix B: UI Mockups

```
[Wireframes to be added in final version]

- Unified task board
- Engineering module navigation
- Auto design interface
- BOQ management screen
- Deployment tracking dashboard
- As-built documentation form
```

---

## Appendix C: Migration Scripts

```
[SQL migration scripts to be added during implementation]

- 0084_engineering_projects_schema.sql
- 0085_task_scope_indexes.sql
- 0086_product_catalog_seed.sql
```

---

**Document Control:**
- Version: 1.0
- Last Updated: 2026-10-09
- Next Review: 2026-10-16
- Distribution: Product, Engineering, UX Teams
