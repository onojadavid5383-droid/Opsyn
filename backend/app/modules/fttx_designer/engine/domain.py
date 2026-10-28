"""Verbatim port of the in-memory pipeline domain model from
``FTTx Designer — dual PON integrated.py`` — ``RoadSegment``, ``Homepass``,
``FAT``, ``DomeClosure``, ``CableSegment``, ``FDT``, ``SupportStructure`` (+
its five subclasses), ``DuctRoute``.

No logic changes from the source script — only the geometry field types
(``QgsGeometry``/``QgsPointXY``/``QgsFeature``), which are now the
Shapely-backed adapters in ``engine.geometry_compat`` instead of
``qgis.core`` (see the integration plan's "compatibility shim, not full
rewrite" strategy, §4.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import ROUTING_WEIGHTS, RoadClass
from .geometry_compat import QgsFeature, QgsGeometry, QgsPointXY


@dataclass
class RoadSegment:
    """Represents a road segment with its properties.

    Topology fields (populated by RoadTopologyEngine before any FAT/FDT logic):
        road_class            – inferred or tag-driven road classification
        is_dead_end           – True when one endpoint is a degree-1 node
        dead_end_junction_pt  – the high-degree endpoint (junction end) of a dead-end
        corridor_id           – corridor chain this segment belongs to (-1 = unassigned)
        dual_cw_partner       – road_id of the paired carriageway, or None
        routing_weight        – Dijkstra edge-weight multiplier from ROUTING_WEIGHTS
        snapped_start/end     – corrected endpoint after endpoint-snap repair
    """
    id: int
    geometry: QgsGeometry
    fid: int
    length: float = 0.0
    homepasses: List[QgsFeature] = field(default_factory=list)
    total_customers: int = 0
    fat_count: int = 0
    fats: list = field(default_factory=list)  # List['FAT'] — plain `list` to avoid
    # dataclasses' forward-reference resolution (which needs FAT defined first)
    # tripping over a sys.modules[cls.__module__] lookup that some embedded/
    # debugger-attached Python consoles leave unresolved. No runtime behavior
    # change — dataclasses never enforces field types, only inspects them for
    # ClassVar/InitVar, so this is purely a type-hint precision trade for
    # invocation-method robustness. See FTTXConfig.pon_architecture fix note.
    # --- topology fields ---
    road_class: RoadClass = RoadClass.UNKNOWN
    is_dead_end: bool = False
    dead_end_junction_pt: Optional[QgsPointXY] = None
    corridor_id: int = -1
    dual_cw_partner: Optional[int] = None
    routing_weight: float = ROUTING_WEIGHTS['UNKNOWN']
    snapped_start: Optional[QgsPointXY] = None
    snapped_end: Optional[QgsPointXY] = None


@dataclass
class Homepass:
    """Represents a homepass point with customer count"""
    fid: int
    geometry: QgsPointXY
    customer_count: int
    road_id: Optional[int] = None
    distance_to_road: float = 0.0
    fat_id: Optional[str] = None
    # Set when a sparse road-end cluster is merged into a neighbouring road's
    # boundary FAT (tail-borrow, see generate_fats) — records the ORIGINAL
    # road_id for traceability/logging after .road_id is rewritten to the
    # accepting road. None for every homepass that was never borrowed.
    borrowed_from_road: Optional[int] = None


@dataclass
class FAT:
    """Fiber Access Terminal"""
    name: str
    geometry: QgsPointXY
    road_id: int
    total_customers: int
    cascade_order: int
    from_device: str
    to_device: str
    wing: str  # 'A' or 'B'
    wing_id: str = ""
    parent_fdt: str = ""
    fdt_serial: str = ""
    fat_sequence: str = ""
    fat_full_code: str = ""
    splitter_type: str = ""
    customers: List[int] = field(default_factory=list)
    customer_allocations: Dict[int, int] = field(default_factory=dict)  # fid -> count (for split points)
    snapped_geometry: Optional[QgsPointXY] = None
    offset_geometry: Optional[QgsPointXY] = None
    fdt_port: int = 0  # 1-indexed direct FDT port in legacy mode; 0 in PCC
    # ── Provenance / traceability (capacity-absorption model) ──────────
    physical_fdt: str = ""
    logical_fdt: str = ""
    allocation_type: str = "native"  # "native" | "borrowed" | "absorbed"
    network_dist_to_fdt: float = 0.0
    # True ONLY for the single, explicitly-tracked global final FAT that is
    # legitimately allowed to sit below MIN_FAT_CAPACITY (spec §11). Never
    # inferred from road/corridor/branch boundaries.
    is_global_final_fat_exception: bool = False
    # True ONLY for a cable-relay/intermediate FAT created by
    # insert_intermediate_fats() to bridge a MAX_FAT_TO_FAT_DISTANCE gap
    # between two real customer-serving FATs. These are structurally NOT
    # customer aggregation points — they exist purely so the cable route
    # has a device every MAX_FAT_TO_FAT_DISTANCE — and are always created
    # with total_customers=0 by design. They must be excluded from the
    # FAT-MIN/MAX customer-capacity rule (never merged, dissolved, or
    # flagged as the final exception on that basis), but otherwise
    # participate normally in FDT membership, wings, and cascading. Set
    # exactly once, at construction, in insert_intermediate_fats().
    is_relay: bool = False
    # Human-readable identity of the physical structure (pole/handhole/...)
    # this FAT is mounted on — stamped by snap_to_structures from
    # SupportStructure.name. "" when unsnapped (see snap_to_structures'
    # fallback paths). Reporting-only; never read by design/routing logic.
    structure_name: str = ""


@dataclass
class DomeClosure:
    """Intermediate dome closure feeding a cluster of FDTs

    Attributes:
        pickup_geometry: location of the pickup point feeding this closure (if any)
        zone_geometry: polygon representing this closure's service area.  Used
            for strict zone-based assignment of FDTs.  This is computed after
            closures are generated and may be a Voronoi cell or a buffered
            convex hull depending on configuration.
    """
    name: str
    geometry: QgsPointXY
    fdts: list = field(default_factory=list)  # List['FDT'] — see RoadSegment.fats note
    total_fdt: int = 0
    feed_capacity: int = 0  # 24 or 48 cores
    snapped_geometry: Optional[QgsPointXY] = None
    pickup_geometry: Optional[QgsPointXY] = None
    pickup_name: Optional[str] = None
    zone_geometry: Optional[QgsGeometry] = None


@dataclass
class CableSegment:
    """Represents a cable segment between devices"""
    name: str
    start_device: str
    end_device: str
    geometry: QgsGeometry
    length: float
    fdt_id: str
    core_info: Dict = field(default_factory=dict)  # holds fiber tracing details
    tap_points: List[Dict] = field(default_factory=list)  # {fat_name, tap_position_m, core_pair}


@dataclass
class FDT:
    """Fiber Distribution Terminal"""
    name: str
    geometry: QgsPointXY
    total_customers: int
    total_fat: int
    wing_a_count: int
    wing_b_count: int
    fdt_code: str = ""
    fdt_serial: str = ""
    fats: List[FAT] = field(default_factory=list)
    zone_geometry: Optional[QgsGeometry] = None
    snapped_geometry: Optional[QgsPointXY] = None
    primary_road_id: Optional[int] = None
    # Dual-PON additive fields — mirror wing_a_count/wing_b_count exactly.
    # Defaulted so every existing positional FDT(...) call site keeps
    # compiling unchanged; always 0 under SINGLE_PON.
    wing_c_count: int = 0
    wing_d_count: int = 0
    # True ONLY for the single, explicitly-tracked global final FDT that is
    # legitimately allowed to sit below profile.min_fat_per_fdt (spec §12).
    # Never inferred from road/corridor/branch/isolated-group boundaries.
    is_global_final_fdt_exception: bool = False
    # See FAT.structure_name — same convention, stamped by snap_to_structures.
    structure_name: str = ""


# =============================================================================
# SUPPORT STRUCTURE HIERARCHY  (Phase 1)
# =============================================================================

@dataclass
class SupportStructure:
    """Base class for any physical structure that FATs, FDTs, or closures
    attach to.  In Aerial mode this is always a Pole.  In Underground/Drainage
    modes it will be a Handhole, Manhole, Chamber, or DrainageSplitter.

    All snapping logic operates on ``geometry``; deployment-specific code
    reads ``structure_type`` for BOQ and output-layer population.
    """
    id: int
    structure_type: str  # "pole" | "handhole" | "manhole" | "chamber" | "drainage"
    geometry: QgsPointXY
    status: str = "existing"  # "existing" | "proposed"
    capacity: Optional[int] = None
    host_device: Optional[str] = None
    route_id: Optional[str] = None
    chainage: float = 0.0
    offset: float = 0.0
    remarks: str = ""
    # Human-readable identity from the source layer's own name field (see
    # _layer_to_structures) — distinct from `id`, which is just this
    # structure's enumeration index within the input layer, not a name.
    # Used by snap_to_structures to stamp FAT/FDT.structure_name for
    # reporting (DED report generator) — never used for design decisions.
    # For poles, assign_pole_tags() later overwrites this with a canonical
    # tag (NP-ABBR-001, ...); raw_name below preserves the original.
    name: str = ""
    # Original label copied verbatim at read time, before any canonical
    # retagging — kept for traceability even after `name` is overwritten.
    raw_name: str = ""


@dataclass
class PoleStructure(SupportStructure):
    """Aerial deployment — a telegraph/utility pole."""
    structure_type: str = field(default="pole", init=False)


@dataclass
class HandholeStructure(SupportStructure):
    """Underground deployment — small below-grade access chamber."""
    structure_type: str = field(default="handhole", init=False)
    hh_id: str = ""


@dataclass
class ManholeStructure(SupportStructure):
    """Underground deployment — full-depth man-entry chamber."""
    structure_type: str = field(default="manhole", init=False)
    mh_id: str = ""


@dataclass
class ChamberStructure(SupportStructure):
    """Underground deployment — generic existing chamber."""
    structure_type: str = field(default="chamber", init=False)


@dataclass
class DrainageSplitterStructure(SupportStructure):
    """Drainage deployment — splitter mounted inside drainage infrastructure."""
    structure_type: str = field(default="drainage", init=False)


@dataclass
class DuctRoute:
    """A single duct segment between two consecutive SupportStructures.

    Generated by ``route_duct_segments()`` and written to the
    ``Underground_Duct_Route`` output layer.
    """
    start_structure: SupportStructure
    end_structure: SupportStructure
    geometry: QgsGeometry
    length: float
    duct_type: str = "HDPE"
    duct_diameter: int = 50
    duct_ways: int = 4
    installation_method: str = "direct_buried"
    spare_pct: int = 20
    occupied: int = 0
    status: str = "proposed"
    route_id: str = ""

    def spare_ways(self) -> int:
        """Ways available for new cables (floor of spare_pct %)."""
        return max(0, int(self.duct_ways * self.spare_pct / 100))
