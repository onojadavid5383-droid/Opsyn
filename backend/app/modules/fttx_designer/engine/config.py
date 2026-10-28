"""Verbatim port of the configuration layer from
``FTTx Designer — dual PON integrated.py`` (module-level tunable constants,
``FTTXConfig``, and every enum/dataclass it depends on:
``CascadeArchitecture``, ``PONArchitecture``, ``CapacityProfile``,
``DeploymentType``, ``RoadClass``, ``WingType``).

No logic changes from the source script — only the QGIS-specific imports
(none were needed here; this layer has zero QGIS dependency in the original
file) and the module boundary itself changed. Per CLAUDE.md's own framing in
the source repo, these module-level constants are a single family: the
pipeline orchestrator (``pipeline.py``, ported in Phase 2) overrides them
per-run via ``_apply_config_to_globals()``/``_restore_globals()`` reading
from an ``FTTXConfig`` instance, then restores these defaults afterward — so
they stay together in one module rather than split by topic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# =============================================================================
# CONFIGURATION PARAMETERS
# =============================================================================

MIN_FAT_CAPACITY = 7
MAX_FAT_CAPACITY = 8
# Tail-borrow threshold (spec: "toward the end of the road there are less
# customers ... can be borrowed onto the next street"): a road-end FAT with
# fewer than this many customers is a candidate to merge into a neighbouring
# road's boundary FAT instead of standing alone. Half of MAX_FAT_CAPACITY —
# below this a FAT is meaningfully underfilled, not just imperfectly packed.
FAT_TAIL_BORROW_THRESHOLD = MAX_FAT_CAPACITY // 2
MAX_FDT_CAPACITY = 64
MAX_BOX_TO_BOX_DISTANCE = 250  # meters
FDT_MAX_RADIUS = MAX_BOX_TO_BOX_DISTANCE  # max distance from the current group anchor before a new FDT group starts
MAX_BOX_TO_CUSTOMER_DISTANCE = 150  # meters
DROP_LENGTH_TOLERANCE = 1.0  # meters; tolerance for snap offsets and geometry precision
SNAP_OFFSET_DISTANCE = 1  # meters
MAX_DEVICE_ROAD_ANCHOR_DISTANCE = 25.0  # meters; reject devices assigned to distant roads
MAX_FAT_PER_FDT = 8
MIN_FAT_PER_FDT = 7  # minimum FATs per FDT; underfilled FDTs borrow from connected roads
MAX_CUSTOMERS_PER_FAT = 8
MAX_FAT_TO_FAT_DISTANCE = 250
MAX_FAT_PER_WING = 4
# Physical structure occupancy cap — every pole/handhole/manhole/chamber can
# host at most one FDT and at most two FATs (three devices total). Enforced
# by snap_to_structures()'s occupancy ledger and by propose_aerial_poles()
# when deciding how many extra poles a dense gap needs. Not a GUI-exposed
# setting (same category as MAX_FAT_PER_WING) — it's a physical/business
# rule, not a per-project tuning knob.
MAX_FAT_PER_STRUCTURE = 2
MAX_FDT_PER_STRUCTURE = 1
# Closure/feeder aerial-hardware accounting (compute_cable_pole_hardware()):
# how close a real pole must sit to a closure-to-FDT or pickup-to-closure
# cable's routed line to count as "on" that path, and how far apart two
# such poles must be before the SECOND one gets its own tensioning
# clamp/hook-and-belt kit. A cable does not get hardware at every pole it
# happens to pass — only at its two physical ends and at intermediate
# poles spaced POLE_TENSION_INTERVAL_M or more apart; anything closer just
# rides over the pole with no extra hardware.
POLE_PATH_TOLERANCE_M = 6.0
POLE_TENSION_INTERVAL_M = 40.0
BORROW_MAX_HOP_DISTANCE = min(MAX_BOX_TO_BOX_DISTANCE, MAX_FAT_TO_FAT_DISTANCE)
RELAY_MAX_HOP_DISTANCE = BORROW_MAX_HOP_DISTANCE
SPLITTER_PATTERN = ["1x9", "1x9", "1x9", "1x8"]

# ── Box-to-box hop limits [Fix 4: threshold coherence] ───────────────────────
# These previously disagreed across three sites, so repair was optimising
# against a limit nobody checked while the gate passed hops repair considered
# broken:
#   _wing_chain_violations           FDT->FAT 250 m, FAT->FAT 150 m
#   route_fdt_to_fats warning        250 m for every hop
#   validate_box_to_box_cable_...    250 m for every hop
# On the reference run that split showed up as 28 hops flagged by repair vs 23
# rejected by the gate. All three now resolve their limit through
# b2b_hop_limit() so they can never drift apart again.
#
# STRICT_FAT_TO_FAT_HOP applies MAX_FAT_TO_FAT_DISTANCE to FAT->FAT hops.
# With the limit at 250 m, both FDT->FAT and FAT->FAT hops share the requested
# maximum box-to-box distance.
STRICT_FAT_TO_FAT_HOP = True

# [Fix 8] Some hops are long because the geography is genuinely long: a river
# crossing, a highway, a stretch of road with no homepasses. A hard raise on
# those makes the tool unusable on real data, so the gate can be switched from
# "abort" to "complete, but register every surviving violation as a costed
# engineering exception". Cables are flagged in core_info and listed in the log
# either way; this only decides whether the run finishes.
ALLOW_DOCUMENTED_B2B_EXCEPTIONS = False
B2B_EXCESS_COST_PER_M = 65.0  # $/m, 8-core cable; used only for reporting

# [Fix 7] Convergence control. Repair passes were oscillating: the same FAT was
# swapped out and back inside one pass, and the ownership signature never
# stabilised across all five passes. A move must now beat the status quo by a
# real margin, and no single FAT may be shuffled indefinitely.
MIN_REPAIR_GAIN_M = 5.0  # metres of true improvement required to accept a move
MAX_MOVES_PER_FAT = 6  # per run, across relay + chain + wing-swap repair

SCRIPT_VERSION = "2026-09-04-v11-routing-graph-noding"

# closure / dome configuration
MAX_FDT_PER_8CORE = 4  # maximum FDTs served by one 8-core distribution cable
CLOSURE_SMALL_CAPACITY = 24  # cores for small-capacity feed cable
CLOSURE_LARGE_CAPACITY = 48  # cores for large-capacity feed cable
# A 24-core closure has 24/8=3 cables, each serving 4 FDTs max = 12 FDTs total.
# A 48-core closure has 48/8=6 cables, each serving 4 FDTs max = 24 FDTs total.
# Threshold: if FDT count > 12, use 48-core; otherwise 24-core.
CLOSURE_24_CORE_THRESHOLD = (CLOSURE_SMALL_CAPACITY // 8) * MAX_FDT_PER_8CORE

# Standard TIA/EIA-598-C 12-fibre colour code. Buffer tubes are coloured
# from this same sequence (Blue/Orange/Green/Brown for the first four —
# see generate_core_list()), and each core WITHIN a buffer is coloured by
# its 1-based position in the buffer using this same 12-colour cycle. One
# list, reused for both, so buffer colour and core colour can never drift
# out of sync with each other.
CORE_COLOR_CODE = [
    "Blue", "Orange", "Green", "Brown", "Slate", "White",
    "Red", "Black", "Yellow", "Violet", "Rose", "Aqua",
]


def _core_color(core_number: int) -> str:
    """True fibre colour for a 1-based core position within its buffer."""
    return CORE_COLOR_CODE[(core_number - 1) % len(CORE_COLOR_CODE)]


def _closure_size_for(fdt_count: int, cores_per_fdt: int = 2) -> int:
    """Return the closure feed capacity (24 or 48 cores) that fits
    ``fdt_count`` FDTs at ``cores_per_fdt`` cores each.

    Replaces the single-PON-only ``CLOSURE_24_CORE_THRESHOLD`` module
    constant (baked in at import time from cores_per_fdt=2) with a function
    evaluated per closure at generation/rebalancing time — the threshold
    itself moves with the architecture (12 FDTs for Single-PON's 2
    cores/FDT, 6 FDTs for Dual-PON's 4 cores/FDT) instead of staying fixed
    at a Single-PON-only number. See spec §13/Blocker 10.
    """
    threshold = CLOSURE_SMALL_CAPACITY // cores_per_fdt
    return CLOSURE_LARGE_CAPACITY if fdt_count > threshold else CLOSURE_SMALL_CAPACITY


# Pickup point generation / clustering
# Approximate number of closures each generated pickup should serve.  Larger
# values yield fewer pickup points but longer feeder runs.
CLOSURES_PER_PICKUP = 8

# name of attribute field containing homepass/customer count
HOMEPASS_FIELD_NAME = "Name"  # change as needed

# short project code woven into every generated device tag (FDT-KKO-01, ...)
# when set; overridden per-run from FTTXConfig.project_abbreviation via
# _apply_config_to_globals(). Empty string = today's unprefixed tag format.
PROJECT_ABBREVIATION = ""

# radius used when multiple FATs share the same pole (meters)
FAT_OFFSET_RADIUS = 0.5

# Layer names (exact match required). Carried over from the QGIS script's
# manual layer-selection dialog; in the web app, layer roles are assigned at
# upload time (see fttx_input_datasets.layer_role) rather than looked up by
# name — kept here only because FTTXConfig-adjacent code before the Phase 2
# rewrite of validate_and_load_layers may still reference them.
LAYER_NAMES = {
    'road': 'roads',
    'homepass': 'homepass',
    'pole': 'poles',
}
OPTIONAL_LAYER_CANDIDATES = {
    'building': ['buildings', 'building', 'Buildings', 'Building'],
    'pickup': ['pickup', 'pickup_point', 'Pickup', 'PickupPoint'],  # optional layer for pickup point cabinets
}
FAST_MODE_DEFAULT = True  # enable performance-friendly clustering by default

# =============================================================================
# OPTICAL POWER BUDGET CONFIGURATION
# Documented defaults for the optical loss-budget / power-trace engine (see
# "OPTICAL POWER BUDGET & TRACE ENGINE" section, ported to engine/optical.py
# in Phase 4). These are read through FTTXConfig.optical_* fields at run
# time — nothing below is hardcoded into the trace/calculation functions
# themselves.
# =============================================================================

# Splitter loss library. Each entry gives the insertion loss (dB) for every
# output role a splitter of that type can produce. "1x2" and every 1x9/1x8
# entry mirror the wing-cascade topology already produced by SPLITTER_PATTERN
# above: FDT -> 1x2 -> wing head; wing chain -> 1x9 (cascade+local) x3 -> 1x8
# (local only, terminal — no cascade port).
SPLITTER_LIBRARY: Dict[str, Dict[str, Any]] = {
    "1x2": {
        "outputs": 2,
        "roles": {"cascade": 3.6},  # FDT -> wing head; both wing outputs equal
    },
    "1x9": {
        "outputs": 9,
        "local_ports": 8,
        "roles": {"cascade": 2.1, "local": 16.3},
    },
    "1x8": {
        "outputs": 8,
        "local_ports": 8,
        "roles": {"local": 10.5},  # terminal splitter — no cascade output
    },
}

# Fibre attenuation, per wavelength, in dB per kilometre.
FIBER_ATTEN_DB_PER_KM: Dict[str, float] = {
    "1310": 0.35,  # upstream
    "1490": 0.25,  # downstream
}
OPTICAL_WAVELENGTHS: Tuple[str, ...] = ("1310", "1490")

SPLICE_LOSS_DB: float = 0.05  # per splice
CONNECTOR_LOSS_DB: float = 0.30  # per connector/interface
ENGINEERING_MARGIN_DB: float = 2.0

# Optical budget classes (ITU-T G.984.2 / G.987.2-style PON power classes).
OPTICAL_BUDGET_DB: Dict[str, float] = {
    "B+": 28.0,
    "C+": 32.0,
    "D": 35.0,
}
DEFAULT_OPTICAL_BUDGET_CLASS: str = "B+"
DEFAULT_OLT_LAUNCH_POWER_DBM: float = 5.0

# Design-margin status thresholds (dB). margin >= PASS -> PASS;
# MARGINAL <= margin < PASS -> MARGINAL; margin < MARGINAL -> FAIL.
OPTICAL_MARGIN_PASS_DB: float = 3.0
OPTICAL_MARGIN_MARGINAL_DB: float = 0.0

# =============================================================================
# ROAD TOPOLOGY ANALYSIS CONSTANTS
# Govern the topology engine that runs before any FAT/FDT/routing logic.
# All values are in metres or degrees as noted.
# =============================================================================

# Endpoint snapping: dangling road ends within this radius are merged into one
# shared node, healing the topology gaps that plague OSM Nigeria exports.
TOPOLOGY_SNAP_TOLERANCE: float = 1.5

# Corridor detection: two consecutive road segments belong to the same
# topological corridor if their bearing deviation is below this threshold.
CORRIDOR_ANGLE_THRESHOLD: float = 45.0

# Dual-carriageway detection thresholds
DUAL_CW_MAX_SEPARATION: float = 30.0  # lateral distance between carriageways (m)
DUAL_CW_BEARING_TOLERANCE: float = 20.0  # max bearing diff to be considered parallel
DUAL_CW_MIN_LENGTH_RATIO: float = 0.55  # shorter/longer length ratio lower bound
# [FIX-DCW-1] Tightened from 0.35 → 0.55 to prevent
# short intersection stub segments from being falsely
# paired as dual-carriageway partners in OSM Nigeria
# fragmented road exports.

# A corridor must be at least this long (m) before topology-inference can
# upgrade it to PRIMARY class without an OSM highway=primary tag.
MIN_PRIMARY_CORRIDOR_LEN: float = 300.0

# Edge-weight multipliers used in the topology-aware Dijkstra.
# Higher weights penalise routing through those road classes.
ROUTING_WEIGHTS: Dict[str, float] = {
    'PRIMARY': 1.0,
    'SECONDARY': 1.4,
    'TERTIARY': 2.0,
    'DEAD_END': 3.5,  # heavy penalty — cable should not enter a dead-end
    'DUAL_CARRIAGEWAY': 1.2,
    'SERVICE': 4.5,
    'UNKNOWN': 2.0,
}

# Routing recovery: virtual connector edges injected during topology analysis
# to bridge small OSM topology gaps (> TOPOLOGY_SNAP_TOLERANCE but < this value).
# These give the router a high-cost but valid alternative to a straight-line.
VIRTUAL_CONNECTOR_RADIUS: float = 8.0  # m — max gap healed by virtual edge
VIRTUAL_CONNECTOR_PENALTY: float = 2000.0  # m-equivalent extra cost per virtual hop
# 2000 m ensures virtual connectors are only used when NO road path exists at all.
# Any real road path (even 500 m of tertiary road) is cheaper than one virtual hop.

# ── Routing-graph noding [B2B detour fix] ───────────────────────────────────
# The CableRouter master graph — the one that actually emits B2B cable
# geometry AND backs NetworkDistanceOracle — used to be built with
# QgsGraphBuilder(crs), whose topologyTolerance argument defaults to 0.0.
# Every junction whose two ways did not share a bit-identical vertex was a
# hard cut in that graph, so Dijkstra routed correctly around a whole block
# for two boxes 60 m apart. The topology engine healed its own graph and
# never touched this one, which is why the map and the attribute table
# agreed on the wrong number.
#
# Two defect classes have to be closed, and they need different fixes:
#   NEAR_MISS   two endpoints a few cm apart  -> topologyTolerance
#   T_UNNODED   an endpoint on another line's interior with no vertex there
#               -> line noding (unaryUnion); tolerance cannot help, there is
#                  no vertex to snap to
# T_UNNODED is the one that produces block-perimeter detours.
NODE_ROADS_FOR_ROUTING: bool = True

# Keep this equal to TOPOLOGY_SNAP_TOLERANCE. Raising it toward
# VIRTUAL_CONNECTOR_RADIUS welds opposite carriageways of a dual carriageway
# into one line and silently shortens every crossing hop.
MASTER_GRAPH_TOPOLOGY_TOLERANCE: float = TOPOLOGY_SNAP_TOLERANCE  # 1.5 m

# Post-run detour audit thresholds. A genuinely long hop (river crossing,
# dual carriageway, no-frontage stretch) sits near routed/straight 1.0–1.6.
# A graph cut produces a large routed length over a tiny straight line.
B2B_DETOUR_RATIO_LIMIT: float = 2.5
B2B_DETOUR_ABS_LIMIT: float = 120.0  # m — ignore short hops, ratio is noisy there

# Radius used by audit_road_layer_noding() when hunting unnoded junctions.
NODING_AUDIT_GAP_TOL: float = 8.0

# Turn-penalty costs added to Dijkstra edge weight when the cable changes direction.
# Discourages backtracking and unrealistic zigzag paths without forcing strict routing.
TURN_PENALTY_SLIGHT: float = 5.0  # bearing change  < 30°
TURN_PENALTY_MODERATE: float = 20.0  # bearing change 30–90°
TURN_PENALTY_SHARP: float = 50.0  # bearing change 90–150°
TURN_PENALTY_REVERSAL: float = 150.0  # bearing change > 150° (near-U-turn)

# Maps raw OSM highway=* values to our five-class taxonomy.
OSM_HIGHWAY_CLASS_MAP: Dict[str, str] = {
    'motorway': 'PRIMARY', 'motorway_link': 'PRIMARY',
    'trunk': 'PRIMARY', 'trunk_link': 'PRIMARY',
    'primary': 'PRIMARY', 'primary_link': 'PRIMARY',
    'secondary': 'SECONDARY', 'secondary_link': 'SECONDARY',
    'tertiary': 'TERTIARY', 'tertiary_link': 'TERTIARY',
    'residential': 'TERTIARY', 'unclassified': 'TERTIARY',
    'living_street': 'TERTIARY',
    'service': 'SERVICE', 'track': 'SERVICE',
    'path': 'SERVICE', 'footway': 'SERVICE',
    'cycleway': 'SERVICE',
}


class CascadeArchitecture(Enum):
    """Cascade wiring architecture selection."""
    PCC = "pcc"
    LEGACY = "legacy"


class PONArchitecture(Enum):
    """PON cascading architecture selection — 1 PON (single splitter, wings
    A/B, 64 customers/FDT) or 2 PON (dual splitter, wings A/B/C/D, 128
    customers/FDT). SINGLE_PON is the default and reproduces today's
    behavior byte-for-byte."""
    SINGLE_PON = "single_pon"
    DUAL_PON = "dual_pon"


@dataclass(frozen=True)
class CapacityProfile:
    """Architecture-resolved capacity bounds for one run. Never mutated;
    resolved fresh from FTTXConfig.pon_architecture at the start of
    run_fttx_design, so there is no cross-run caching / staleness risk."""
    pon_count: int
    wings: Tuple[str, ...]  # e.g. ("A","B") or ("A","B","C","D")
    max_fat_per_wing: int  # 4, unaffected by architecture
    max_fat_per_fdt: int  # 8 (single) or 16 (dual)
    max_fdt_capacity: int  # 64 (single) or 128 (dual)
    cores_per_fdt: int  # 2 (single) or 4 (dual)
    min_fat_per_fdt: int  # donor/viability floor — kept at 7 for both
    # architectures per the explicit policy
    # default (no cost argument for scaling it;
    # see spec §15). Revisit only on explicit
    # product sign-off.


# PON -> its two wing labels, and wing -> its owning PON index. Single source
# of truth — no independent A/B/C/D list should be introduced elsewhere.
PON_WINGS: Dict[int, Tuple[str, str]] = {1: ("A", "B"), 2: ("C", "D")}
WING_TO_PON: Dict[str, int] = {"A": 1, "B": 1, "C": 2, "D": 2}

CAPACITY_PROFILES: Dict['PONArchitecture', CapacityProfile] = {
    PONArchitecture.SINGLE_PON: CapacityProfile(
        pon_count=1, wings=("A", "B"),
        max_fat_per_wing=MAX_FAT_PER_WING,
        max_fat_per_fdt=MAX_FAT_PER_FDT,
        max_fdt_capacity=MAX_FDT_CAPACITY,
        cores_per_fdt=2,
        min_fat_per_fdt=MIN_FAT_PER_FDT,
    ),
    PONArchitecture.DUAL_PON: CapacityProfile(
        pon_count=2, wings=("A", "B", "C", "D"),
        max_fat_per_wing=MAX_FAT_PER_WING,
        max_fat_per_fdt=MAX_FAT_PER_FDT * 2,
        max_fdt_capacity=MAX_FDT_CAPACITY * 2,
        cores_per_fdt=4,
        # Product decision (supersedes the earlier "keep at 7" default):
        # a Dual-PON FDT should sit in the 14-16 FAT / 112-128 customer
        # range, not just "at least 7". Two boxes' worth of capacity in one
        # enclosure is a bigger capital commitment, so the viability bar is
        # raised to match — applies to both the donor floor and the
        # new-FDT-viability role (spec §15's "differentiated" alternative
        # was not chosen; this is the uniform-14 option instead).
        min_fat_per_fdt=14,
    ),
}


def get_capacity_profile(pon_architecture: 'PONArchitecture') -> CapacityProfile:
    """Resolve the CapacityProfile for a run. Call fresh at the start of
    run_fttx_design (and nowhere cached across runs) so a Single->Dual->Single
    sequence in the same session can never leak state."""
    return CAPACITY_PROFILES[pon_architecture]


def _balanced_partition_sizes(total: int, min_size: int, max_size: int) -> Tuple[List[int], bool]:
    """Single, architecture-agnostic capacity-balancing partitioner.

    Replaces the old ``MAX_FAT_PER_FDT - 1 == MIN_FAT_PER_FDT`` assumption
    (true only for Single-PON's 8/7, false for Dual-PON's 16/14 — see spec
    §2/§9) with a generalized algorithm driven purely by ``min_size`` /
    ``max_size``, so it is correct for both Single-PON (7-8) and Dual-PON
    (14-16), and for the FAT customer allocator (7-8) too — one authoritative
    implementation, no duplicated architecture-specific math (spec §9).

    Given ``total`` items to be split into groups of size in
    ``[min_size, max_size]``:

      1. ``k_min = ceil(total / max_size)`` — fewest groups possible if every
         group were packed to MAX.
      2. ``k_max = floor(total / min_size)`` — most groups possible if every
         group only just cleared MIN.
      3. Any integer K in ``[k_min, k_max]`` satisfies
         ``K*min_size <= total <= K*max_size`` and can therefore be filled
         with every group inside ``[min_size, max_size]`` using a plain
         ``base, base+1`` split (``base = total // K``).
      4. Preference among valid K values: the LOWEST valid K wins, full
         stop — matching the spec's explicit, repeatedly-stated rule
         ("prefer the lowest valid number of FDTs... minimizes FDT
         equipment, closure/pickup infrastructure, closure-to-FDT cables,
         unnecessary material" — spec §1/§3/§21). An earlier version of
         this function instead searched the whole [k_min, k_max] range for
         the K with the smallest remainder (evenest split), because that
         happens to reproduce the spec's own 182-at-14..16 worked example
         (13 groups of exactly 14, remainder 0) over the equally-legal
         12-group split (16,16,15x10, remainder 2). But that "prefer
         evenest" rule is wrong in general: on a wide [k_min, k_max] range
         (e.g. 1345 items at min=7/max=8, where k_min=169 but the evenest
         split sits at k=192) it inflates the device count by dozens of
         boxes purely to shave the remainder — the opposite of the stated
         objective. Lowest-K is the version that actually stays consistent
         with the spec's own reasoning at real-world scale. Net effect:
         for the specific 182-item Dual-PON example this now returns 12
         FDTs (16,16,15,15,15,15,15,15,15,15,15,15) instead of the spec's
         stated 13x14 — both are mathematically valid, but 12 is fewer
         boxes, which is the actual, stated goal. See the accompanying
         report for the full explanation of this discrepancy.

    Returns ``(sizes, exact)``:
      - ``exact`` is True when every group in ``sizes`` satisfies
        ``min_size <= size <= max_size``.
      - ``exact`` is False only when NO valid K exists at all (total is too
        small/awkward to split into all-valid groups). In that case the
        items are packed MAX-first into ``k_min - 1`` full groups, and the
        single unavoidable remainder is isolated into exactly one final
        (undersized) group — this is the sole legitimate "global final"
        exception case (spec §11/§12), never spread across multiple groups.
    """
    if total <= 0:
        return [], True
    if min_size <= 0:
        min_size = 1
    if max_size < min_size:
        max_size = min_size

    if total <= max_size:
        # Fits in a single group outright — valid unless it's below the
        # minimum, in which case it IS the unavoidable undersized case
        # (e.g. a road/corridor whose total demand never reaches MIN).
        return [total], total >= min_size

    k_min = -(-total // max_size)  # ceil(total / max_size)
    k_max = total // min_size  # floor(total / min_size)

    if k_min > k_max:
        # No K makes every group valid. Pack MAX-first so the shortfall is
        # isolated into exactly one final tail group rather than spread
        # thin across every group (spec §11/§12: single global exception).
        k = k_min
        sizes = [max_size] * (k - 1)
        tail = total - max_size * (k - 1)
        sizes.append(tail)
        return sizes, (min_size <= tail <= max_size)

    k = k_min  # lowest valid K -> fewest devices (spec §1/§3/§21)
    base, remainder = divmod(total, k)
    sizes = [base + 1 if i < remainder else base for i in range(k)]
    return sizes, True


class DeploymentType(Enum):
    """Physical deployment medium — controls which strategy is active."""
    AERIAL = "aerial"
    UNDERGROUND = "underground"
    DRAINAGE = "drainage"
    HYBRID = "hybrid"


class B2BRoutingMode(Enum):
    """Geometry source for aerial box-to-box cable hops."""
    ROAD = "road"
    POLE_TO_POLE = "pole_to_pole"


@dataclass
class FTTXConfig:
    """User-configurable runtime settings."""
    max_box_to_box_distance: float = MAX_BOX_TO_BOX_DISTANCE
    max_box_to_customer_distance: float = MAX_BOX_TO_CUSTOMER_DISTANCE
    drop_length_tolerance: float = DROP_LENGTH_TOLERANCE
    snap_offset_distance: float = SNAP_OFFSET_DISTANCE
    max_device_road_anchor_distance: float = MAX_DEVICE_ROAD_ANCHOR_DISTANCE
    fat_offset_radius: float = FAT_OFFSET_RADIUS
    splitter_pattern: List[str] = field(default_factory=lambda: SPLITTER_PATTERN.copy())
    homepass_field_name: str = HOMEPASS_FIELD_NAME
    # Project identity: project_name is shown on the DED report cover page;
    # project_abbreviation (sanitized upstream to alnum-upper) is woven into
    # every generated device tag via _project_tag(). Both blank = unchanged
    # legacy tag format / default report title.
    project_name: str = ""
    project_abbreviation: str = ""
    enable_closure_generation: bool = True
    fast_mode: bool = FAST_MODE_DEFAULT
    # V5 additions
    coverage_pct: int = 100
    growth_reserve_pct: int = 0
    cascade_architecture: CascadeArchitecture = CascadeArchitecture.PCC
    # PON cascading architecture — 1 PON (default, 64C/FDT) or 2 PON (128C/FDT).
    # Legacy + Dual-PON is not a supported combination (see CascadeArchitecture
    # .LEGACY handling); the UI must keep the two mutually exclusive.
    pon_architecture: PONArchitecture = PONArchitecture.SINGLE_PON
    # Phase 2: deployment type
    deployment_type: DeploymentType = DeploymentType.AERIAL
    b2b_routing_mode: B2BRoutingMode = B2BRoutingMode.ROAD
    # Explicit per-run opt-in: over-limit B2B hops remain listed and costed
    # as engineering exceptions instead of failing the design.
    allow_documented_b2b_exceptions: bool = False
    # Underground options (used by UndergroundStrategy — Phase 3)
    ug_infrastructure_type: str = "handhole"  # "handhole" | "manhole"
    ug_spacing_m: float = 80.0  # structure spacing along road
    ug_routing_mode: str = "assisted"  # "strict" | "assisted"
    ug_duct_type: str = "HDPE"  # "HDPE" | "uPVC" | "GI" | "Microduct"
    ug_duct_diameter_mm: int = 50
    ug_duct_ways: int = 4
    ug_installation_method: str = "direct_buried"
    ug_spare_capacity_pct: int = 20
    ug_existing_handholes_layer: Optional[str] = None  # layer name string
    ug_existing_manholes_layer: Optional[str] = None
    # Phase 4: aerial accessory BOQ
    marker_interval_m: float = 50.0  # cable marker tag interval in metres
    # Phase 9: Aerial pole proposing — fills gaps between existing poles
    # when FAT density in the gap exceeds what the bounding poles can
    # legally hold under MAX_FAT_PER_STRUCTURE.
    allow_proposed_poles: bool = True
    pole_max_spacing_m: float = 60.0  # trigger: consecutive existing-pole gap above this
    pole_proposal_search_radius_m: float = 80.0  # max search radius for a customer-reachable pole site
    # Phase 7a: Drainage options
    dr_channel_layer: Optional[str] = None  # drainage channel polyline layer name
    dr_spacing_m: float = 60.0  # splitter spacing along channel
    dr_duct_type: str = "HDPE"
    dr_duct_diameter_mm: int = 40
    dr_duct_ways: int = 2
    # Phase 7b: Hybrid options
    hy_boundary_layer: Optional[str] = None  # polygon layer defining aerial/UG zones
    hy_aerial_field: str = "zone_type"  # field name containing zone type value
    hy_aerial_value: str = "aerial"  # field value that marks aerial zone
    # Phase 8: Duct occupancy ledger
    occupancy_gpkg_path: Optional[str] = None  # path to persistent GeoPackage ledger
    occupancy_enabled: bool = True  # False → skip ledger (aerial/legacy runs)
    # Optical power budget engine (PCC architecture only — see build_optical_paths).
    optical_enabled: bool = True
    olt_launch_power_dbm: float = DEFAULT_OLT_LAUNCH_POWER_DBM
    optical_budget_class: str = DEFAULT_OPTICAL_BUDGET_CLASS  # "B+" | "C+" | "D"
    optical_splitter_library: Dict[str, Dict[str, Any]] = field(
        default_factory=lambda: {k: dict(v, roles=dict(v["roles"])) for k, v in SPLITTER_LIBRARY.items()}
    )
    optical_fiber_atten_db_per_km: Dict[str, float] = field(
        default_factory=lambda: FIBER_ATTEN_DB_PER_KM.copy()
    )
    optical_splice_loss_db: float = SPLICE_LOSS_DB
    optical_connector_loss_db: float = CONNECTOR_LOSS_DB
    optical_engineering_margin_db: float = ENGINEERING_MARGIN_DB
    optical_margin_pass_db: float = OPTICAL_MARGIN_PASS_DB
    optical_margin_marginal_db: float = OPTICAL_MARGIN_MARGINAL_DB
    # Per-hop trace rows can reach into the millions on a 100k-homepass
    # design (rows ≈ customers × hops × wavelengths) — off switch for large
    # runs where only the per-customer/FAT/FDT summaries are needed.
    optical_trace_table_enabled: bool = True


# =============================================================================
# ROAD CLASS TAXONOMY
# Defined here (before the data-classes) so RoadSegment can reference it.
# =============================================================================

class RoadClass(Enum):
    """Five-class road taxonomy used by the topology engine."""
    PRIMARY = "PRIMARY"  # motorway, trunk, primary
    SECONDARY = "SECONDARY"  # secondary, secondary_link
    TERTIARY = "TERTIARY"  # residential, unclassified, tertiary
    DEAD_END = "DEAD_END"  # segment that terminates at a degree-1 node
    DUAL_CARRIAGEWAY = "DUAL_CARRIAGEWAY"  # one side of a paired divided road
    SERVICE = "SERVICE"  # service lanes, tracks, paths
    UNKNOWN = "UNKNOWN"  # no tag and insufficient topology signal


class WingType(Enum):
    A = "A"  # Right side — PON1
    B = "B"  # Left side — PON1
    C = "C"  # Right side — PON2 (Dual-PON only)
    D = "D"  # Left side — PON2 (Dual-PON only)
