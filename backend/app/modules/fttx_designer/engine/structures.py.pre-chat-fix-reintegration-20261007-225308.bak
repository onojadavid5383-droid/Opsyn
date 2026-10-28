"""Verbatim port of the support-structure stage from
``FTTx Designer — dual PON integrated.py``: ``_layer_to_structures``,
``distribute_points_around_pole``, ``_place_pole_for_group``,
``propose_aerial_poles``, ``snap_to_structures``, ``snap_to_poles``,
``calculate_offset_point``, ``assign_pole_tags``,
``_restamp_snapped_structure_names``.

The last two are the pole-naming pass (added in the boq.py sub-phase,
once its street-name-lookup dependencies existed to port): it runs after
``snap_to_structures`` has already stamped each FAT/FDT's raw pole label
into ``.structure_name``, walks poles street-by-street from their nearest
pickup point, classifies each into a canonical type, and overwrites the
pole's own `.name` with a project-tagged serial (NP-ABBR-001, ...).
``_restamp_snapped_structure_names`` then re-copies the now-canonical name
back onto every FAT/FDT that had snapped to it, since the FAT/FDT's
`.structure_name` was copied by value before the rename happened.

No logic changes from the source script — only the QGIS types (now from
``engine.geometry_compat``) and cross-module imports.

Note: ``MAX_BOX_TO_CUSTOMER_DISTANCE``, ``DROP_LENGTH_TOLERANCE``, and
``SNAP_OFFSET_DISTANCE`` are 3 of the 8 tunables the pipeline overrides
per-run (see runtime_config.py's docstring) — every direct reference reads
``runtime_config.X``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from . import runtime_config as rc
from .config import (
    FAT_OFFSET_RADIUS as _DEFAULT_FAT_OFFSET_RADIUS,
    MAX_FAT_PER_STRUCTURE,
    MAX_FDT_PER_STRUCTURE,
    FTTXConfig,
    WingType,
)
from .cascade import _classify_pole_type, _project_tag
from .domain import (
    DomeClosure,
    FAT,
    FDT,
    ChamberStructure,
    DrainageSplitterStructure,
    HandholeStructure,
    Homepass,
    ManholeStructure,
    PoleStructure,
    RoadSegment,
    SupportStructure,
)
from .fat_generation import _offset_point_by_side, _point_side_of_road
from .geometry_compat import (
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsSpatialIndex,
    QgsVectorLayer,
)
from .perf_logger import PerformanceLogger
from .spatial_utils import DistanceCalculator, SpatialIndexManager
from .street_utils import _build_road_to_street_map, _build_street_bboxes, _street_position


def _layer_to_structures(layer: QgsVectorLayer,
                         structure_type: str = "pole") -> List[SupportStructure]:
    """Convert any QgsVectorLayer of point features into a list of
    ``SupportStructure`` objects so snapping code is deployment-agnostic.

    The correct concrete subclass is selected from ``structure_type``.
    Non-point geometries are silently skipped.
    """
    cls_map = {
        "pole": PoleStructure,
        "handhole": HandholeStructure,
        "manhole": ManholeStructure,
        "chamber": ChamberStructure,
        "drainage": DrainageSplitterStructure,
    }
    cls = cls_map.get(structure_type, SupportStructure)  # noqa: F841 (kept for parity with source)

    # Same candidate-field convention already used for the Tagged_Poles output
    # layer (see populate_output_layers) — reused here, not reinvented, so a
    # structure's .name means the same thing everywhere it's read. Left ""
    # when the source layer has no such field: Tagged_Poles' own sequential
    # "Tag" numbering (e.g. "Pole-001") is computed independently, per street,
    # after this point, so it is NOT reproduced here as a synthetic fallback —
    # doing so would risk a label that looks authoritative but disagrees with
    # what the map/Tagged_Poles layer actually shows for the same structure.
    field_names = [f.name() for f in layer.fields()]
    name_field = next(
        (cand for cand in ("Name", "name", "label", "Label", "id", "ID")
         if cand in field_names),
        None,
    )

    structures: List[SupportStructure] = []
    for i, feat in enumerate(layer.getFeatures()):
        geom = feat.geometry()
        if not geom or geom.isEmpty():
            continue
        pt = geom.asPoint()
        name = str(feat[name_field]) if name_field else ""
        if structure_type == "pole":
            structures.append(PoleStructure(id=i, geometry=pt, status="existing", name=name, raw_name=name))
        elif structure_type == "handhole":
            structures.append(HandholeStructure(id=i, geometry=pt, status="existing", name=name, raw_name=name))
        elif structure_type == "manhole":
            structures.append(ManholeStructure(id=i, geometry=pt, status="existing", name=name, raw_name=name))
        elif structure_type == "chamber":
            structures.append(ChamberStructure(id=i, geometry=pt, status="existing", name=name, raw_name=name))
        elif structure_type == "drainage":
            structures.append(DrainageSplitterStructure(id=i, geometry=pt, status="existing", name=name, raw_name=name))
        else:
            structures.append(SupportStructure(
                id=i, structure_type=structure_type,
                geometry=pt, status="existing", name=name, raw_name=name
            ))
    return structures


def distribute_points_around_pole(pole_point: QgsPointXY, fat_count: int,
                                  radius: float = _DEFAULT_FAT_OFFSET_RADIUS) -> List[QgsPointXY]:
    """Return a list of points evenly spaced in a circle around pole_point.

    fat_count: number of offsets required.
    radius: distance from pole center in meters.

    PRESERVED QUIRK (not fixed), matching the source exactly: in the
    original script this default is ``= FAT_OFFSET_RADIUS``, a module
    global bound once when the function is defined (module import time) —
    a run-configured ``FTTXConfig.fat_offset_radius`` override happening
    later via ``_apply_config_to_globals()`` never reaches this default,
    because Python default-argument values are evaluated once at function
    definition, not per call. The one real call site
    (``snap_to_structures``'s fan-out pass) never passes ``radius``
    explicitly, so in practice this function always uses the compile-time
    0.5 m default regardless of run configuration — same here.
    """
    pts: List[QgsPointXY] = []
    if fat_count <= 0:
        return pts
    for i in range(fat_count):
        angle = 2 * math.pi * i / fat_count
        x = pole_point.x() + radius * math.cos(angle)
        y = pole_point.y() + radius * math.sin(angle)
        pts.append(QgsPointXY(x, y))
    return pts


# =============================================================================
# POLE SNAPPING WITH OFFSET
# =============================================================================

def _place_pole_for_group(
    group: List[FAT],
    road: 'RoadSegment',
    hp_by_fid: Dict[int, 'Homepass'],
    config: 'FTTXConfig',
    dist_calc: 'DistanceCalculator',
) -> Optional[QgsPointXY]:
    """Find a point on *road* that keeps every customer behind every FAT in
    *group* within reach, for a new pole ``propose_aerial_poles()`` wants
    to add.

    Starts at the group's chainage midpoint (clamped onto the road). If that
    spot doesn't reach every customer, walks outward along the road — up to
    ``config.pole_proposal_search_radius_m`` in either direction — looking
    for a spot that does, and returns the closest such spot found.

    Reach is judged against the LIVE ``MAX_BOX_TO_CUSTOMER_DISTANCE`` /
    ``DROP_LENGTH_TOLERANCE`` globals (project-configurable via
    ``FTTXConfig.max_box_to_customer_distance`` — see
    ``_apply_config_to_globals``), never a distance hardcoded in this
    function, so a project with a different drop-length policy is honored
    automatically.

    Returns ``None`` if no reachable spot exists within the search radius —
    the caller must not fabricate an unreachable pole.
    """
    if not group or not road.geometry or road.geometry.isEmpty():
        return None

    road_geom = road.geometry
    road_len = road_geom.length()

    customer_pts: List[QgsPointXY] = []
    for fat in group:
        for hp_id in fat.customers:
            hp = hp_by_fid.get(hp_id)
            if hp:
                customer_pts.append(hp.geometry)

    ideal_chain = sum(
        road_geom.lineLocatePoint(QgsGeometry.fromPointXY(f.geometry))
        for f in group
    ) / len(group)
    ideal_chain = max(0.0, min(ideal_chain, road_len))
    ideal_pt = road_geom.interpolate(ideal_chain).asPoint()

    if not customer_pts:
        # No customer data to validate against (e.g. relay FATs) — the
        # chainage midpoint is the best available placement.
        return ideal_pt

    limit = rc.MAX_BOX_TO_CUSTOMER_DISTANCE + rc.DROP_LENGTH_TOLERANCE

    def _max_reach(pt: QgsPointXY) -> float:
        return max(dist_calc.distance_points(pt, c) for c in customer_pts)

    if _max_reach(ideal_pt) <= limit:
        return ideal_pt

    # Ideal spot doesn't reach everyone — search outward along the road
    # within the configured "convenient reach" radius for a spot that does.
    radius = max(config.pole_proposal_search_radius_m, 0.0)
    step = 2.0
    best_pt, best_reach = None, float('inf')
    offset = step
    while offset <= radius:
        for direction in (-1, 1):
            chain = ideal_chain + direction * offset
            if chain < 0 or chain > road_len:
                continue
            pt = road_geom.interpolate(chain).asPoint()
            reach = _max_reach(pt)
            if reach <= limit:
                return pt
            if reach < best_reach:
                best_pt, best_reach = pt, reach
        offset += step

    return None


def propose_aerial_poles(
    roads: Dict[int, 'RoadSegment'],
    existing_structures: List[SupportStructure],
    fats: List[FAT],
    homepasses: List['Homepass'],
    config: 'FTTXConfig',
    dist_calc: 'DistanceCalculator',
    logger: 'PerformanceLogger',
) -> List[SupportStructure]:
    """Propose extra poles where existing pole spacing can't support the FAT
    density between them.

    Trigger, per road: two consecutive existing poles more than
    ``config.pole_max_spacing_m`` apart (default 60m) AND more FATs sit
    between them than the two bounding poles could legally hold at
    ``MAX_FAT_PER_STRUCTURE`` each — e.g. 6 FATs stranded between two poles
    that can only host 2 each between them.

    This function only decides WHERE new poles should go and flags why
    (logged) — it never assigns a specific FAT to a specific pole. That
    stays snap_to_structures()'s job (the occupancy-capped greedy pass), so
    the two can never disagree about who ends up where. Each candidate site
    is validated by ``_place_pole_for_group`` against live customer-reach
    distance before being proposed, so a pole is never proposed somewhere a
    FAT couldn't legally reach its customers from.
    """
    logger.start_module("Aerial Pole Proposing")

    if not config.allow_proposed_poles:
        logger.log("propose_aerial_poles: disabled (allow_proposed_poles=False) — skipped.")
        logger.end_module("Aerial Pole Proposing")
        return []

    existing_poles = [s for s in existing_structures if s.structure_type == "pole"]
    if len(existing_poles) < 2:
        logger.log("propose_aerial_poles: fewer than 2 existing poles — nothing to bridge.")
        logger.end_module("Aerial Pole Proposing")
        return []

    hp_by_fid: Dict[int, 'Homepass'] = {}
    for hp in homepasses:
        if hp.fid not in hp_by_fid:
            hp_by_fid[hp.fid] = hp

    # ---- Bucket existing poles by nearest road, chainage-sorted ----
    poles_by_road: Dict[int, List[Tuple[float, SupportStructure]]] = defaultdict(list)
    for pole in existing_poles:
        pt_geom = QgsGeometry.fromPointXY(pole.geometry)
        best_road = None
        best_dist = float('inf')
        for road in roads.values():
            if not road.geometry or road.geometry.isEmpty():
                continue
            d = road.geometry.distance(pt_geom)
            if d < best_dist:
                best_dist = d
                best_road = road
        if best_road is None:
            continue
        chainage = best_road.geometry.lineLocatePoint(pt_geom)
        poles_by_road[best_road.id].append((chainage, pole))

    for road_id in poles_by_road:
        poles_by_road[road_id].sort(key=lambda t: t[0])

    # ---- Bucket FATs by road, chainage-sorted (demand + cluster source) ----
    fats_by_road: Dict[int, List[Tuple[float, FAT]]] = defaultdict(list)
    for fat in fats:
        road = roads.get(fat.road_id)
        if not road or not road.geometry or road.geometry.isEmpty():
            continue
        chainage = road.geometry.lineLocatePoint(QgsGeometry.fromPointXY(fat.geometry))
        fats_by_road[fat.road_id].append((chainage, fat))
    for road_id in fats_by_road:
        fats_by_road[road_id].sort(key=lambda t: t[0])

    proposed: List[SupportStructure] = []
    unreachable_groups = 0
    next_id = max((s.id for s in existing_structures), default=-1) + 1
    bounding_capacity = MAX_FAT_PER_STRUCTURE * 2   # what the two bounding poles can hold together

    for road_id, ordered_poles in poles_by_road.items():
        road = roads.get(road_id)
        if not road or len(ordered_poles) < 2:
            continue
        fat_positions = fats_by_road.get(road_id, [])

        for (chain_a, pole_a), (chain_b, pole_b) in zip(ordered_poles, ordered_poles[1:]):
            gap = dist_calc.distance_points(pole_a.geometry, pole_b.geometry)
            if gap < config.pole_max_spacing_m:
                continue

            demand = [fat for (c, fat) in fat_positions if chain_a <= c <= chain_b]
            if len(demand) <= bounding_capacity:
                continue   # gap is wide but demand is low — the two existing poles suffice

            total_poles_needed = -(-len(demand) // MAX_FAT_PER_STRUCTURE)  # ceil
            extra_needed = max(total_poles_needed - 2, 1)

            logger.log(
                f"[POLE_PROPOSED] road {road_id}: {gap:.1f}m gap between existing "
                f"poles carries {len(demand)} FAT(s) (bounding poles can only hold "
                f"{bounding_capacity} at {MAX_FAT_PER_STRUCTURE}/pole) — "
                f"proposing {extra_needed} pole(s)."
            )

            # Target the chainage-middle slice of the demand — the FATs the
            # two bounding poles are least likely to reach — and split it
            # into extra_needed evenly-sized, chainage-contiguous clusters,
            # one per new pole. The exact split doesn't have to match what
            # snap_to_structures() later assigns (it decides the real
            # FAT-to-pole match by distance + occupancy); this only needs to
            # anchor each new pole's proposed location near real demand.
            overflow_count = min(len(demand), extra_needed * MAX_FAT_PER_STRUCTURE)
            edge = max((len(demand) - overflow_count) // 2, 0)
            middle = demand[edge: edge + overflow_count] or demand

            base, rem = divmod(len(middle), extra_needed)
            idx = 0
            for i in range(extra_needed):
                size = base + (1 if i < rem else 0)
                if size <= 0:
                    continue
                group = middle[idx: idx + size]
                idx += size

                pole_pt = _place_pole_for_group(group, road, hp_by_fid, config, dist_calc)
                if pole_pt is None:
                    unreachable_groups += 1
                    logger.log(
                        f"WARNING [POLE_PROPOSAL_UNREACHABLE]: road {road_id} — no pole "
                        f"site within {config.pole_proposal_search_radius_m:.0f}m of the "
                        f"ideal spot keeps all {len(group)} FAT(s) in this cluster within "
                        f"customer reach; those FAT(s) will fall back to unsnapped "
                        f"placement in snap_to_structures()."
                    )
                    continue

                s = PoleStructure(
                    id=next_id,
                    geometry=pole_pt,
                    status="proposed",
                    remarks=(
                        f"pole-proposed: relieves {len(group)} FAT(s) in a "
                        f"{gap:.0f}m gap on road {road_id}"
                    ),
                )
                next_id += 1
                proposed.append(s)

    logger.log(
        f"propose_aerial_poles: {len(proposed)} pole(s) proposed"
        + (f", {unreachable_groups} cluster(s) had no reachable site within "
           f"{config.pole_proposal_search_radius_m:.0f}m" if unreachable_groups else "")
        + "."
    )
    logger.end_module("Aerial Pole Proposing")
    return proposed


def snap_to_structures(fdts: List[FDT],
                       fats: List[FAT],
                       homepasses: List[Homepass],
                       structures: List[SupportStructure],
                       roads: Dict[int, RoadSegment],
                       dist_calc: DistanceCalculator,
                       logger: PerformanceLogger) -> Tuple[List[FDT], List[FAT]]:
    """Snap FDT and FAT points to the nearest SupportStructure with offset.

    Replaces the aerial-only ``snap_to_poles``.  Accepts any list of
    ``SupportStructure`` subclass instances — poles, handholes, manholes,
    drainage splitters — so the same snapping logic works for every
    deployment strategy.

    A lightweight in-memory spatial index is built directly from the
    ``structures`` list, removing the dependency on a QGIS layer.
    """
    logger.start_module("Structure Snapping")

    # -----------------------------------------------------------------
    # Build in-memory spatial index from structure list
    # -----------------------------------------------------------------
    struct_index = QgsSpatialIndex()
    struct_geoms: Dict[int, QgsGeometry] = {}
    struct_pts: Dict[int, QgsPointXY] = {}

    for s in structures:
        pt_geom = QgsGeometry.fromPointXY(s.geometry)
        feat = QgsFeature(s.id)
        feat.setGeometry(pt_geom)
        struct_index.addFeature(feat)
        struct_geoms[s.id] = pt_geom
        struct_pts[s.id] = s.geometry

    # keep a flat mapping id → SupportStructure for BOQ/type queries
    struct_by_id: Dict[int, SupportStructure] = {s.id: s for s in structures}

    # alias for inner logic — identical algorithm to original snap_to_poles
    pole_index = struct_index
    pole_geoms = struct_geoms

    # -----------------------------------------------------------------
    # Per-structure occupancy ledger (business rule: at most one FDT and
    # at most two FATs per pole/structure — never more than three devices
    # total). Shared between the FDT and FAT assignment passes below, and
    # both passes assign greedily by GLOBAL nearest-distance order rather
    # than per-device independent "nearest wins" — the latter is biased by
    # iteration order and can let an early device claim a slot a later,
    # option-less device actually needed.
    # -----------------------------------------------------------------
    occupancy: Dict[int, Dict[str, int]] = defaultdict(lambda: {"fdt": 0, "fat": 0})

    # -----------------------------------------------------------------
    # FDT snapping: collect every (distance, fdt, pole) candidate, then
    # assign nearest-first, skipping any pole already holding an FDT.
    # -----------------------------------------------------------------
    fdt_candidates: List[Tuple[float, FDT, int, QgsPointXY]] = []
    for fdt in fdts:
        candidate_poles = pole_index.nearestNeighbor(fdt.geometry, 5)
        for pole_id in candidate_poles:
            pole_geom = pole_geoms.get(pole_id)
            if not pole_geom:
                continue
            pole_point = pole_geom.asPoint()
            if fdt.zone_geometry and fdt.zone_geometry.contains(pole_geom):
                dist = dist_calc.distance_points(fdt.geometry, pole_point)
                fdt_candidates.append((dist, fdt, pole_id, pole_point))

    fdt_candidates.sort(key=lambda t: t[0])
    assigned_fdt_ids: Set[int] = set()
    for _dist, fdt, pole_id, pole_point in fdt_candidates:
        if id(fdt) in assigned_fdt_ids:
            continue
        if occupancy[pole_id]["fdt"] >= MAX_FDT_PER_STRUCTURE:
            continue
        fdt.snapped_geometry = pole_point
        fdt.structure_name = struct_by_id[pole_id].name
        occupancy[pole_id]["fdt"] += 1
        assigned_fdt_ids.add(id(fdt))

    for fdt in fdts:
        if id(fdt) not in assigned_fdt_ids:
            logger.log(
                f"WARNING [NO_POLE_IN_ZONE]: {fdt.name} — no suitable pole found in "
                f"FDT zone (every candidate pole was either outside the zone or "
                f"already at the {MAX_FDT_PER_STRUCTURE}-FDT structure cap)"
            )

    # Build homepass lookup for customer-aware FAT snapping.
    hp_by_fid: Dict[int, Homepass] = {}
    for hp in homepasses:
        if hp.fid not in hp_by_fid:
            hp_by_fid[hp.fid] = hp

    # -----------------------------------------------------------------
    # FAT snapping: collect every (distance, fat, pole) candidate that
    # passes the zone + customer-drop-distance checks, then assign
    # nearest-first, skipping any pole already at MAX_FAT_PER_STRUCTURE.
    # A FAT that never finds a feasible pole within its candidate set
    # (occupancy exhausted or genuinely out of reach) falls back to its
    # own unsnapped geometry — same behavior as before this change.
    # -----------------------------------------------------------------
    eligible_fats: List[FAT] = []
    fat_candidates: List[Tuple[float, FAT, int, QgsPointXY]] = []
    for fat in fats:
        parent_fdt = next((fdt for fdt in fdts if fat in fdt.fats), None)
        if not parent_fdt:
            continue
        eligible_fats.append(fat)

        assigned_points = [hp_by_fid[hp_id].geometry for hp_id in fat.customers if hp_id in hp_by_fid]
        road = roads.get(fat.road_id)

        candidate_poles = pole_index.nearestNeighbor(fat.geometry, 15)
        for pole_id in candidate_poles:
            pole_geom = pole_geoms.get(pole_id)
            if not pole_geom:
                continue
            pole_point = pole_geom.asPoint()
            if not (parent_fdt.zone_geometry and parent_fdt.zone_geometry.contains(pole_geom)):
                continue
            candidate_start = pole_point
            if road:
                candidate_start = calculate_offset_point(
                    pole_point, road.geometry, fat.wing, dist_calc
                )
            if assigned_points:
                max_drop = max(
                    dist_calc.distance_points(candidate_start, hp_point)
                    for hp_point in assigned_points
                )
                if max_drop > (rc.MAX_BOX_TO_CUSTOMER_DISTANCE + rc.DROP_LENGTH_TOLERANCE):
                    continue
            dist = dist_calc.distance_points(fat.geometry, pole_point)
            fat_candidates.append((dist, fat, pole_id, pole_point))

    fat_candidates.sort(key=lambda t: t[0])
    assigned_fat_ids: Set[int] = set()
    pole_to_fats: Dict[int, List[FAT]] = defaultdict(list)
    for _dist, fat, pole_id, pole_point in fat_candidates:
        if id(fat) in assigned_fat_ids:
            continue
        if occupancy[pole_id]["fat"] >= MAX_FAT_PER_STRUCTURE:
            continue
        fat.snapped_geometry = pole_point
        fat.structure_name = struct_by_id[pole_id].name
        occupancy[pole_id]["fat"] += 1
        assigned_fat_ids.add(id(fat))
        pole_to_fats[pole_id].append(fat)

    for fat in eligible_fats:
        if id(fat) not in assigned_fat_ids:
            logger.log(
                f"WARNING [NO_POLE_IN_ZONE]: {fat.name} — no suitable pole found in "
                f"FDT zone (every candidate pole was either out of customer reach, "
                f"outside the zone, or already at the {MAX_FAT_PER_STRUCTURE}-FAT "
                f"structure cap)"
            )
            fat.snapped_geometry = fat.geometry

    # second pass: visually fan out FATs sharing the same structure (now
    # capped at MAX_FAT_PER_STRUCTURE by the occupancy ledger above, so this
    # is purely cosmetic offsetting, never a capacity decision)
    for pole_id, group in pole_to_fats.items():
        if len(group) > 1:
            pole_pt = pole_geoms[pole_id].asPoint()
            offsets = distribute_points_around_pole(pole_pt, len(group))
            # sort by wing so all A's get first offsets, then B's
            sorted_group = sorted(group, key=lambda f: f.wing)
            for fat, new_pt in zip(sorted_group, offsets):
                fat.snapped_geometry = new_pt

    # final pass: compute offset_geometry now that snapped_geometry has been
    # finalized (with possible small displacements)
    for fat in fats:
        road = roads.get(fat.road_id)
        assigned_points = [hp_by_fid[hp_id].geometry for hp_id in fat.customers if hp_id in hp_by_fid]

        if fat.snapped_geometry and road:
            fat.offset_geometry = calculate_offset_point(
                fat.snapped_geometry, road.geometry, fat.wing, dist_calc
            )

        if assigned_points:
            start_point = fat.offset_geometry or fat.snapped_geometry or fat.geometry
            max_drop = max(dist_calc.distance_points(start_point, hp_point) for hp_point in assigned_points)
            if max_drop > (rc.MAX_BOX_TO_CUSTOMER_DISTANCE + rc.DROP_LENGTH_TOLERANCE):
                # Fall back to unsnapped FAT placement to preserve strict drop rule.
                # This reverts an earlier successful structure snap, so the
                # structure_name recorded for reporting must be cleared too —
                # the FAT is genuinely no longer mounted on that structure.
                fat.snapped_geometry = fat.geometry
                fat.structure_name = ""
                if road:
                    fat.offset_geometry = calculate_offset_point(
                        fat.geometry, road.geometry, fat.wing, dist_calc
                    )
                else:
                    fat.offset_geometry = None

                fallback_start = fat.offset_geometry or fat.snapped_geometry or fat.geometry
                fallback_max = max(
                    dist_calc.distance_points(fallback_start, hp_point)
                    for hp_point in assigned_points
                )
                if fallback_max > (rc.MAX_BOX_TO_CUSTOMER_DISTANCE + rc.DROP_LENGTH_TOLERANCE):
                    # Keep run alive; route validation will still enforce the same limit.
                    fat.offset_geometry = fat.geometry
                    logger.log(
                        f"WARNING [NO_VALID_FAT_LOCATION]: {fat.name} — best reachable drop "
                        f"is {fallback_max:.2f}m "
                        f"(limit {rc.MAX_BOX_TO_CUSTOMER_DISTANCE + rc.DROP_LENGTH_TOLERANCE:.2f}m)"
                    )

    logger.end_module("Structure Snapping")

    return fdts, fats


def snap_to_poles(fdts: List[FDT],
                  fats: List[FAT],
                  homepasses: List[Homepass],
                  pole_layer: QgsVectorLayer,
                  roads: Dict[int, RoadSegment],
                  index_mgr: SpatialIndexManager,
                  dist_calc: DistanceCalculator,
                  logger: PerformanceLogger) -> Tuple[List[FDT], List[FAT]]:
    """Backward-compatible shim: converts pole_layer → List[PoleStructure]
    then delegates to ``snap_to_structures``.

    All aerial-mode call sites continue to work unchanged.
    """
    structures = _layer_to_structures(pole_layer, "pole")
    return snap_to_structures(fdts, fats, homepasses, structures, roads, dist_calc, logger)


def calculate_offset_point(point: QgsPointXY, road_geom: QgsGeometry,
                          wing: str, dist_calc: DistanceCalculator) -> QgsPointXY:
    """Calculate frontage-side offset using side-of-line first, wing fallback."""
    side_sign = _point_side_of_road(point, road_geom)
    if side_sign == 0:
        # A and C are both "right side" wings (PON1/PON2 respectively); B
        # and D are both "left side" — see WingType. Was hardcoded to
        # A-only, which meant a Dual-PON wing-C FAT landing exactly on the
        # road centreline fell through to the wrong (left) side.
        side_sign = 1 if wing in (WingType.A.value, WingType.C.value) else -1
    return _offset_point_by_side(point, road_geom, side_sign, rc.SNAP_OFFSET_DISTANCE)


def assign_pole_tags(structures: List['SupportStructure'],
                     road_layer: 'QgsVectorLayer',
                     closures: List['DomeClosure'],
                     logger: PerformanceLogger) -> None:
    """Classify every pole's raw label into a canonical type (NP/PP/Nitel/
    Third_party_pole/POLE) and overwrite `.name` with a project-tagged,
    sequentially numbered code (NP-ABBR-001, ...), walking each street from
    its nearest pickup point to the street's far end, street by street in
    the same alphabetical order FDT numbering already uses. Each type gets
    its own serial counter that runs continuously across the whole project
    (never resets per street). Mutates `structures` in place; callers must
    re-stamp any already-copied FAT/FDT.structure_name afterward (see
    _restamp_snapped_structure_names)."""
    poles = [s for s in structures if s.structure_type == "pole"]
    if not poles:
        return

    road_to_street, street_order = _build_road_to_street_map(road_layer)
    road_si = QgsSpatialIndex()
    for rf in road_layer.getFeatures():
        rg = rf.geometry()
        if rg and not rg.isEmpty():
            road_si.addFeature(rf)

    poles_by_street: Dict[str, List['SupportStructure']] = defaultdict(list)
    for pole in poles:
        nearest = road_si.nearestNeighbor(pole.geometry, 1)
        road_id = nearest[0] if nearest else None
        poles_by_street[road_to_street.get(road_id, "UNASSIGNED")].append(pole)

    street_bboxes = _build_street_bboxes(road_layer, road_to_street)
    pickup_points = [c.pickup_geometry for c in closures if c.pickup_geometry]

    streets_sorted = [s for s in street_order if s in poles_by_street]
    if "UNASSIGNED" in poles_by_street and "UNASSIGNED" not in streets_sorted:
        streets_sorted.append("UNASSIGNED")

    counters: Dict[str, int] = defaultdict(int)
    unmatched: List[str] = []

    for street in streets_sorted:
        street_poles = poles_by_street[street]
        if pickup_points:
            cx = sum(p.geometry.x() for p in street_poles) / len(street_poles)
            cy = sum(p.geometry.y() for p in street_poles) / len(street_poles)
            anchor = min(pickup_points, key=lambda p: math.hypot(p.x() - cx, p.y() - cy))
            street_poles.sort(key=lambda sp: math.hypot(
                sp.geometry.x() - anchor.x(), sp.geometry.y() - anchor.y()))
        else:
            bbox = street_bboxes.get(street)
            street_poles.sort(key=lambda sp: _street_position(sp.geometry, bbox))

        for pole in street_poles:
            type_code, matched = _classify_pole_type(pole)
            if not matched:
                unmatched.append(pole.raw_name or pole.name)
            counters[type_code] += 1
            pole.name = _project_tag(type_code, f"{counters[type_code]:03d}")

    if unmatched:
        logger.log(
            f"WARNING [POLE_TYPE_UNRECOGNIZED]: {len(unmatched)} pole(s) had "
            f"an unrecognized type label and were tagged generically "
            f"(POLE-...): {sorted(set(unmatched))[:20]}"
        )
    logger.log(f"Tagged {len(poles)} pole(s): " +
               ", ".join(f"{k}={v}" for k, v in sorted(counters.items())))


def _restamp_snapped_structure_names(fdts: List['FDT'], fats: List['FAT'],
                                     structures: List['SupportStructure']) -> None:
    """Re-copy FAT/FDT.structure_name from the (now canonically retagged)
    pole they were snapped to. snap_to_structures() copies .name by value
    at snap time, before assign_pole_tags() renames the pole, so without
    this the FAT/FDT fields — and the DED report's "Mounting Structure"
    column, which reads them directly — would keep showing the stale raw
    label. Matched by snapped point geometry since FAT/FDT don't retain the
    structure's id, only the exact point they were snapped onto."""
    name_by_point = {
        (round(s.geometry.x(), 6), round(s.geometry.y(), 6)): s.name
        for s in structures if s.structure_type == "pole"
    }
    for fdt in fdts:
        if fdt.snapped_geometry:
            key = (round(fdt.snapped_geometry.x(), 6), round(fdt.snapped_geometry.y(), 6))
            if key in name_by_point:
                fdt.structure_name = name_by_point[key]
        for fat in fdt.fats:
            if fat.snapped_geometry:
                key = (round(fat.snapped_geometry.x(), 6), round(fat.snapped_geometry.y(), 6))
                if key in name_by_point:
                    fat.structure_name = name_by_point[key]
