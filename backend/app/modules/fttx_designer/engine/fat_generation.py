"""Verbatim port of the FAT generation stage from
``FTTx Designer — dual PON integrated.py``: the FAT-placement geometry
helpers (``_point_side_of_road``, ``_is_near_road_junction``,
``_offset_point_by_side``, ``_line_intersects_buildings`` — confirmed by
grep to be needed only here, not by topology.py), ``generate_fats``,
``split_cluster_by_capacity``, ``create_fat_from_homepasses``, and the
global FAT capacity rebalancer ``_rebalance_fats_for_capacity``.

No logic changes from the source script — only the QGIS types (now from
``engine.geometry_compat``) and the cross-module helper imports (now real
Python imports instead of same-file references).

Note: ``MAX_BOX_TO_CUSTOMER_DISTANCE`` and ``SNAP_OFFSET_DISTANCE`` are two
of the 8 tunables the pipeline overrides per-run (see runtime_config.py's
docstring) — every live read goes through ``runtime_config.X``. The one
exception, matching the source exactly, is ``_offset_point_by_side``'s
default parameter value: in the original script that default was also
bound once at function-definition time (long before a run's config
override ever executes), so its own internal call site always re-passed
the then-current global explicitly rather than relying on the default —
reproduced here the same way.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from . import runtime_config as rc
from .config import (
    FAT_TAIL_BORROW_THRESHOLD,
    MAX_FAT_CAPACITY,
    MAX_FAT_TO_FAT_DISTANCE,
    MIN_FAT_CAPACITY,
    SNAP_OFFSET_DISTANCE as _DEFAULT_SNAP_OFFSET_DISTANCE,
    RoadClass,
    _balanced_partition_sizes,
)
from .distance_oracle import _network_distance
from .domain import FAT, Homepass, RoadSegment
from .errors import ValidationError
from .geometry_compat import (
    QgsGeometry,
    QgsPointXY,
    QgsSpatialIndex,
    QgsVectorLayer,
)
from .homepass_assignment import _line_intersects_other_roads, _parse_homepass_value
from .perf_logger import PerformanceLogger
from .spatial_utils import DistanceCalculator, SpatialIndexManager
from .topology import RoadTopologyEngine, _road_vertices

MAX_FAT_REBALANCE_ITERATIONS = 50


# =============================================================================
# FAT-PLACEMENT GEOMETRY HELPERS
# =============================================================================

def _line_intersects_buildings(line_geom: QgsGeometry,
                               building_index: Optional[QgsSpatialIndex],
                               building_geoms: Dict[int, QgsGeometry]) -> bool:
    """Return True if line intersects any building geometry."""
    if not line_geom or line_geom.isEmpty() or not building_index:
        return False
    for bid in building_index.intersects(line_geom.boundingBox()):
        bgeom = building_geoms.get(bid)
        if bgeom and not bgeom.isEmpty() and line_geom.intersects(bgeom):
            return True
    return False


def _point_side_of_road(point: QgsPointXY, road_geom: QgsGeometry) -> int:
    """Return +1 (left), -1 (right), 0 (undetermined) relative to road direction."""
    if not road_geom or road_geom.isEmpty():
        return 0
    try:
        _d, _pt, _idx, left_of = road_geom.closestSegmentWithContext(point)
        if left_of > 0:
            return 1
        if left_of < 0:
            return -1
    except Exception:
        pass
    return 0


def _is_near_road_junction(point: QgsPointXY,
                           road_geom: QgsGeometry,
                           dist_calc: DistanceCalculator,
                           threshold_m: float = 10.0) -> bool:
    """Corner-house check: point is near segment start/end nodes."""
    vertices = _road_vertices(road_geom)
    if len(vertices) < 2:
        return False
    d_start = dist_calc.distance_points(point, vertices[0])
    d_end = dist_calc.distance_points(point, vertices[-1])
    return min(d_start, d_end) <= threshold_m


def _offset_point_by_side(point: QgsPointXY,
                          road_geom: QgsGeometry,
                          side_sign: int,
                          offset_distance: float = _DEFAULT_SNAP_OFFSET_DISTANCE) -> QgsPointXY:
    """Offset point perpendicular to nearest road segment toward side_sign."""
    if side_sign == 0:
        return point
    vertices = _road_vertices(road_geom)
    if len(vertices) < 2:
        return point

    road_point = road_geom.nearestPoint(QgsGeometry.fromPointXY(point))
    best_seg = None
    best_dist = float('inf')
    for i in range(len(vertices) - 1):
        seg = QgsGeometry.fromPolylineXY([vertices[i], vertices[i + 1]])
        d = seg.distance(road_point)
        if d < best_dist:
            best_dist = d
            best_seg = (vertices[i], vertices[i + 1])
    if not best_seg:
        return point

    pt1, pt2 = best_seg
    dx = pt2.x() - pt1.x()
    dy = pt2.y() - pt1.y()
    length = math.sqrt(dx * dx + dy * dy)
    if length <= 0:
        return point
    dx /= length
    dy /= length

    # Left side relative to segment direction.
    if side_sign > 0:
        perp_x, perp_y = -dy, dx
    else:
        perp_x, perp_y = dy, -dx

    return QgsPointXY(
        point.x() + perp_x * offset_distance,
        point.y() + perp_y * offset_distance
    )


# =============================================================================
# FAT GENERATION
# =============================================================================

def generate_fats(roads: Dict[int, RoadSegment],
                  road_layer: QgsVectorLayer,
                  index_mgr: SpatialIndexManager,
                  building_layer: Optional[QgsVectorLayer],
                  dist_calc: DistanceCalculator,
                  logger: PerformanceLogger,
                  topo: Optional['RoadTopologyEngine'] = None) -> List[FAT]:
    """Generate FATs for each road segment using demand-driven allocation with advanced spatial constraints.

    When ``topo`` is provided, a tail-borrow pass (Pass 2 below) runs between
    cluster-building and FAT materialisation: a sparse road-end cluster can
    merge into a neighbouring road's boundary cluster across a real junction,
    subject to road-class and capacity guards. ``topo=None`` reproduces the
    original per-road-only behaviour exactly (no merging attempted).
    """
    logger.start_module("FAT Generation")

    road_index = index_mgr.get_index(road_layer)
    building_index = None
    building_geoms: Dict[int, QgsGeometry] = {}
    if building_layer:
        building_index = index_mgr.build_index(building_layer, cache_geoms=True)
        building_geoms = index_mgr.geometries.get(building_layer.id(), {})

    fats: List[FAT] = []
    fat_counter = 1

    # ── Pass 1: build capacity-safe homepass clusters per road ──────────────
    # Same demand-driven greedy-fill allocation as before, unchanged. FAT
    # objects are NOT created yet — Pass 2 needs to inspect/merge clusters
    # across roads before anything is materialised.
    road_clusters: Dict[int, List[List[Homepass]]] = {}
    road_geoms: Dict[int, QgsGeometry] = {}
    road_required_fat: Dict[int, int] = {}

    for road_id in sorted(roads.keys()):
        road = roads[road_id]
        if not road.homepasses or road.total_customers == 0:
            continue

        road_geom = road.geometry
        road_geoms[road_id] = road_geom

        # Sort homepasses along road for deterministic allocation
        homepasses = sorted(
            road.homepasses,
            key=lambda hp: road_geom.lineLocatePoint(QgsGeometry.fromPointXY(hp.geometry))
        )

        # [Gap-aware clustering fix] Pass 1 used to run ONE greedy
        # customer-count walk across the whole road, oblivious to physical
        # distance: two homepasses separated by a real coverage gap (a park,
        # undeveloped land, a river — anything with zero frontage) could
        # still end up bridged by a single FAT, or a FAT boundary could fall
        # at an arbitrary point inside the gap, purely by chance of where
        # the running customer count happened to cross a target_load
        # threshold. Splitting the sorted homepass list into segments
        # wherever the along-road distance between two consecutive
        # homepasses exceeds MAX_FAT_TO_FAT_DISTANCE forces every such gap
        # to become a deliberate FAT boundary — no FAT's own customers are
        # ever split across a gap wider than the cable itself is allowed to
        # span. Each segment is then partitioned independently with the
        # same balanced demand-driven sizing as before (spec §10), so a
        # segment too small to reach MIN_FAT_CAPACITY on its own correctly
        # falls back to the same single-undersized-tail exception used for
        # the true road-end case (_balanced_partition_sizes, spec §11/§12).
        #
        # This cannot shrink a genuine, unavoidable gap — two homepass
        # clusters on opposite sides of a gap wider than
        # MAX_BOX_TO_BOX_DISTANCE are still exactly that far apart after
        # this change, and closing that kind of gap needs a device in it,
        # not a smarter partition. What this does fix is the walk silently
        # wandering across a gap it never needed to cross, and it turns
        # every gap-driven FAT boundary into a deliberate, logged decision
        # instead of an accident of arithmetic.
        segments: List[List[Homepass]] = []
        if homepasses:
            current_segment = [homepasses[0]]
            for prev_hp, hp in zip(homepasses, homepasses[1:]):
                gap = (
                    road_geom.lineLocatePoint(QgsGeometry.fromPointXY(hp.geometry))
                    - road_geom.lineLocatePoint(QgsGeometry.fromPointXY(prev_hp.geometry))
                )
                if gap > MAX_FAT_TO_FAT_DISTANCE:
                    segments.append(current_segment)
                    current_segment = []
                current_segment.append(hp)
            segments.append(current_segment)

        if len(segments) > 1:
            logger.log(
                f"Road {road_id}: {len(segments)} coverage segment(s) detected "
                f"(homepass gap(s) > {MAX_FAT_TO_FAT_DISTANCE:.0f}m) — "
                f"partitioning FATs per segment instead of across the whole road."
            )

        # Build capacity-safe groups per segment using the same demand-driven
        # allocation as before (unchanged math), just scoped to one
        # gap-free stretch of road at a time. Homepass weights are still
        # respected and may be split across FATs within a segment.
        clusters: List[List[Homepass]] = []
        required_fat = 0

        for seg_homepasses in segments:
            seg_customers = int(sum(
                max(_parse_homepass_value(hp.customer_count), 0) for hp in seg_homepasses
            ))
            if seg_customers <= 0:
                continue

            # Balanced demand-driven FAT sizing (spec §10): the old greedy
            # target_load formula (fill to MAX, reserving exactly 1 customer
            # per remaining slot) mathematically forces a MAX...MAX+leftover
            # shape — e.g. 22 customers -> 8+8+6, 17 -> 8+9(invalid, clamped
            # to 8+8+1) even though a valid 7-8 distribution exists
            # (22 -> 8+7+7). _balanced_partition_sizes tests the true
            # partition space and only falls back to a MAX-first/undersized
            # -tail split when no all-valid distribution exists at all (the
            # legitimate final-FAT exception).
            seg_sizes, seg_exact = _balanced_partition_sizes(
                seg_customers, MIN_FAT_CAPACITY, MAX_FAT_CAPACITY
            )
            required_fat += len(seg_sizes)
            if not seg_exact:
                logger.log(
                    f"Road {road_id}: segment of {seg_customers} customers cannot "
                    f"be split into all-{MIN_FAT_CAPACITY}-{MAX_FAT_CAPACITY} FATs; "
                    f"unavoidable tail of {seg_sizes[-1]} customers on last FAT "
                    f"(pending tail-borrow / global final-FAT exception check)."
                )

            seg_remaining = seg_customers
            hp_idx = 0
            hp_remaining = _parse_homepass_value(seg_homepasses[0].customer_count)
            if hp_remaining < 0:
                hp_remaining = 0

            for target_load in seg_sizes:
                if target_load <= 0:
                    raise ValidationError(
                        f"Road {road_id}: invalid FAT target load {target_load}"
                    )

                cluster: List[Homepass] = []
                cluster_load = 0

                while cluster_load < target_load:
                    if hp_idx >= len(seg_homepasses):
                        raise ValidationError(
                            f"Road {road_id}: ran out of homepasses during strict FAT allocation"
                        )

                    hp = seg_homepasses[hp_idx]
                    if hp_remaining <= 0:
                        hp_idx += 1
                        if hp_idx < len(seg_homepasses):
                            hp_remaining = _parse_homepass_value(seg_homepasses[hp_idx].customer_count)
                            if hp_remaining < 0:
                                hp_remaining = 0
                        continue

                    take = min(hp_remaining, target_load - cluster_load)
                    cluster.append(
                        Homepass(
                            fid=hp.fid,
                            geometry=hp.geometry,
                            customer_count=take,
                            road_id=hp.road_id,
                            distance_to_road=hp.distance_to_road,
                            fat_id=hp.fat_id
                        )
                    )
                    cluster_load += take
                    hp_remaining -= take
                    seg_remaining -= take

                clusters.append(cluster)

            if seg_remaining != 0:
                raise ValidationError(
                    f"Road {road_id}: unallocated customers after FAT grouping: {seg_remaining}"
                )

        road.fat_count = required_fat
        road_required_fat[road_id] = required_fat
        road_clusters[road_id] = clusters

    # ── Pass 2: tail-borrow ──────────────────────────────────────────────────
    # "Toward the end of the road there are less customers ... can be
    # borrowed onto the next street." Merge a sparse road-end cluster into a
    # neighbouring road's boundary cluster at their shared junction, guarded
    # by all of:
    #   - topology only, never straight-line proximity — a building can
    #     never be crossed because the walk never leaves the road network;
    #   - road class — never borrow across a PRIMARY/SECONDARY/
    #     DUAL_CARRIAGEWAY neighbour ("didn't cross ... major road or dual
    #     carriage");
    #   - capacity — only if the FULL tail fits in the neighbour's remaining
    #     room; no partial borrow. This makes the pass strictly safe: it can
    #     only ever improve a road's FAT fill or leave it untouched, never
    #     produce a worse outcome than today;
    #   - distance/crossing — the merge is tried, then explicitly checked
    #     against MAX_BOX_TO_CUSTOMER_DISTANCE for every homepass in the
    #     merged cluster (create_fat_from_homepasses's own candidate search
    #     falls back silently on a bad fit rather than raising, so this pass
    #     verifies itself and reverts instead of trusting that fallback);
    #   - a road never lends its only remaining cluster — always keeps at
    #     least one FAT of its own.
    borrow_log: List[str] = []
    if topo is not None and getattr(topo, '_edges', None) and getattr(topo, '_nodes', None):
        junction_roads: Dict[int, Set[int]] = defaultdict(set)
        road_nodes: Dict[int, Tuple[int, int]] = {}
        for rid, edge in topo._edges.items():
            sn, en = edge['start'], edge['end']
            road_nodes[rid] = (sn, en)
            junction_roads[sn].add(rid)
            junction_roads[en].add(rid)

        MAJOR = (RoadClass.PRIMARY, RoadClass.SECONDARY, RoadClass.DUAL_CARRIAGEWAY)

        def _cluster_customers(cluster: List[Homepass]) -> int:
            return sum(_parse_homepass_value(hp.customer_count) for hp in cluster)

        def _cluster_centroid(cluster: List[Homepass]) -> QgsPointXY:
            xs = [hp.geometry.x() for hp in cluster]
            ys = [hp.geometry.y() for hp in cluster]
            return QgsPointXY(sum(xs) / len(xs), sum(ys) / len(ys))

        for road_id in sorted(road_clusters.keys()):
            nodes = road_nodes.get(road_id)
            if nodes is None:
                continue
            sn, en = nodes

            for is_start in (True, False):
                clusters = road_clusters[road_id]
                if len(clusters) < 2:
                    break  # must keep at least one FAT of its own
                boundary_idx = 0 if is_start else len(clusters) - 1
                boundary_cluster = clusters[boundary_idx]
                boundary_load = _cluster_customers(boundary_cluster)
                if boundary_load == 0 or boundary_load >= FAT_TAIL_BORROW_THRESHOLD:
                    continue

                junction_nid = sn if is_start else en
                candidates = [
                    nb for nb in junction_roads.get(junction_nid, set())
                    if nb != road_id
                    and nb in road_clusters
                    and roads.get(nb) is not None
                    and roads[nb].road_class not in MAJOR
                ]
                if not candidates:
                    continue

                tail_pt = _cluster_centroid(boundary_cluster)
                candidates.sort(
                    key=lambda nb: (dist_calc.distance_points(tail_pt, _cluster_centroid(
                        road_clusters[nb][0 if road_nodes.get(nb, (None, None))[0] == junction_nid
                                          else len(road_clusters[nb]) - 1]
                    )), nb)
                )

                for nb_id in candidates:
                    nb_sn, nb_en = road_nodes.get(nb_id, (None, None))
                    if nb_sn == junction_nid:
                        nb_boundary_idx = 0
                    elif nb_en == junction_nid:
                        nb_boundary_idx = len(road_clusters[nb_id]) - 1
                    else:
                        continue  # defensive — shouldn't happen given junction_roads is consistent

                    nb_clusters = road_clusters[nb_id]
                    nb_boundary_cluster = nb_clusters[nb_boundary_idx]
                    nb_load = _cluster_customers(nb_boundary_cluster)
                    if nb_load + boundary_load > MAX_FAT_CAPACITY:
                        continue  # doesn't fully fit — no partial borrow

                    # Tentative merge: rewrite borrowed homepasses' road_id to
                    # the accepting road (keeps the existing "hp.road_id must
                    # match fat.road_id" invariant intact) while recording
                    # the original road_id in borrowed_from_road for tracing.
                    borrowed_hps = [
                        Homepass(
                            fid=hp.fid, geometry=hp.geometry,
                            customer_count=hp.customer_count, road_id=nb_id,
                            distance_to_road=hp.distance_to_road, fat_id=hp.fat_id,
                            borrowed_from_road=hp.borrowed_from_road
                            if hp.borrowed_from_road is not None else road_id,
                        )
                        for hp in boundary_cluster
                    ]
                    merged_cluster = (nb_boundary_cluster + borrowed_hps if nb_boundary_idx == len(nb_clusters) - 1
                                       else borrowed_hps + nb_boundary_cluster)

                    tentative_fat = create_fat_from_homepasses(
                        merged_cluster, nb_id, 0, road_geoms[nb_id], dist_calc,
                        roads=roads, road_index=road_index,
                        building_index=building_index, building_geoms=building_geoms,
                    )
                    max_drop = max(
                        dist_calc.distance_points(hp.geometry, tentative_fat.geometry)
                        for hp in merged_cluster
                    )
                    if max_drop > rc.MAX_BOX_TO_CUSTOMER_DISTANCE:
                        continue  # bad fit — try next candidate, or give up on this end

                    # Accept the merge.
                    nb_clusters[nb_boundary_idx] = merged_cluster
                    del clusters[boundary_idx]
                    borrows_msg = (
                        f"Road {road_id}: {'start' if is_start else 'end'}-of-road tail "
                        f"({boundary_load} customer(s)) borrowed onto road {nb_id} at "
                        f"junction {junction_nid} — neighbour FAT now {nb_load + boundary_load} customer(s)"
                    )
                    borrow_log.append(borrows_msg)
                    break  # stop trying other candidates for this end

    for msg in borrow_log:
        logger.log(msg)

    # ── Pass 3: materialise FAT objects with advanced spatial validation ────
    for road_id in sorted(road_clusters.keys()):
        road = roads[road_id]
        road_geom = road_geoms[road_id]
        clusters = road_clusters[road_id]
        required_fat = road_required_fat[road_id]  # original demand-derived count, for the summary log only

        local_fats: List[FAT] = []
        for c in clusters:
            fat = create_fat_from_homepasses(
                c, road_id, fat_counter, road_geom, dist_calc,
                roads=roads, road_index=road_index,
                building_index=building_index, building_geoms=building_geoms
            )
            local_fats.append(fat)
            fat_counter += 1

        # Post-borrow count check: the ACTUAL cluster count may now differ
        # from the original demand-derived `required_fat` (a donor road lost
        # a cluster, an acceptor road's boundary cluster grew but its count
        # is unchanged) — validate against len(clusters), not required_fat.
        if len(local_fats) != len(clusters):
            raise ValidationError(
                f"Road {road_id}: created {len(local_fats)} FATs but expected {len(clusters)}"
            )

        # Validate all FATs meet constraints
        for fat, cluster in zip(local_fats, clusters):
            if fat.total_customers > MAX_FAT_CAPACITY:
                raise ValidationError(
                    f"FAT {fat.name} has {fat.total_customers} customers, exceeds {MAX_FAT_CAPACITY}"
                )
            if fat.total_customers <= 0:
                raise ValidationError(f"FAT {fat.name} is empty")

            # Validate drop distance and crossing constraints (advanced features)
            # Allow outlier customers that exceed drop distance (report as warnings)
            outliers = []
            for hp in cluster:
                if hp.road_id != fat.road_id:
                    raise ValidationError(f"FAT {fat.name} has cross-street assignment for customer {hp.fid}")
                d = dist_calc.distance_points(hp.geometry, fat.geometry)
                if d > rc.MAX_BOX_TO_CUSTOMER_DISTANCE:
                    outliers.append((hp.fid, d))
                    logger.log(
                        f"WARNING [DROP_DISTANCE_EXCEEDED]: FAT {fat.name}-Customer {hp.fid} "
                        f"distance {d:.2f}m exceeds {rc.MAX_BOX_TO_CUSTOMER_DISTANCE}m (data quality issue)"
                    )
                    continue

                # Check for road/building crossing (with corner exception)
                is_corner = _is_near_road_junction(hp.geometry, road_geom, dist_calc, 10.0)
                link = QgsGeometry.fromPolylineXY([fat.geometry, hp.geometry])
                crosses_road = _line_intersects_other_roads(link, road_id, roads, road_index)
                crosses_building = _line_intersects_buildings(link, building_index, building_geoms)

                if is_corner:
                    if crosses_building:
                        logger.log(
                            f"WARNING [GEOMETRY_CROSSING]: FAT {fat.name}-Customer {hp.fid} "
                            f"path crosses building (corner location)"
                        )
                else:
                    if crosses_road or crosses_building:
                        logger.log(
                            f"WARNING [GEOMETRY_CROSSING]: FAT {fat.name}-Customer {hp.fid} "
                            f"path crosses {'road' if crosses_road else 'building'}"
                        )

            if outliers:
                logger.log(
                    f"FAT {fat.name} has {len(outliers)} outlier customer(s) exceeding drop distance: "
                    f"{[fid for fid, _ in outliers]}"
                )

        logger.log(
            f"Road {road_id} → {road.total_customers} customers → {required_fat} FAT required → {len(local_fats)} FAT created"
        )
        fats.extend(local_fats)

    logger.end_module("FAT Generation")
    logger.log(f"Generated {len(fats)} FATs" + (f" ({len(borrow_log)} tail-borrow merge(s))" if borrow_log else ""))

    # Global consistency check
    total_fat_customers = sum(int(f.total_customers) for f in fats)
    total_road_customers = sum(int(r.total_customers) for r in roads.values())
    if total_fat_customers != total_road_customers:
        raise ValidationError(
            f"FAT/customer mismatch: FAT total={total_fat_customers}, "
            f"road total={total_road_customers}"
        )

    # ── Underfilled-tail diagnostic (informational only) ────────────────────
    # generate_fats()'s own per-road balanced allocation + tail-borrow is a
    # local, first-pass optimization (spec §23 Pass 1/Pass 2). It does NOT
    # own final-exception determination any more — that responsibility
    # belongs entirely to the dedicated global stage,
    # _rebalance_fats_for_capacity() (spec §16/§17), which runs next in the
    # pipeline and clears/re-derives is_global_final_fat_exception itself.
    # This is a log-only heads-up so the size of the repair job is visible
    # before that stage even starts.
    low_fats = [f for f in fats if f.total_customers < MIN_FAT_CAPACITY]
    if low_fats:
        logger.log(
            f"{len(low_fats)} FAT(s) below minimum ({MIN_FAT_CAPACITY}) after "
            f"per-road allocation + tail-borrow; deferred to global FAT "
            f"capacity balancing: {[(f.name, f.total_customers) for f in low_fats]}"
        )

    return fats


def split_cluster_by_capacity(homepasses: List[Homepass], max_capacity: int) -> List[List[Homepass]]:
    """Split a cluster of homepasses into multiple groups respecting capacity.

    Uses SUM(homepass values), not COUNT(points). max_capacity is the max
    sum per group.
    """
    groups = []
    current_group = []
    current_customers = 0  # SUM of homepass values in current_group

    for hp in homepasses:
        remaining = _parse_homepass_value(hp.customer_count)
        if remaining <= 0:
            continue

        # Split one homepass into chunks when it exceeds FAT capacity.
        while remaining > 0:
            chunk = min(remaining, max_capacity)
            hp_part = Homepass(
                fid=hp.fid,
                geometry=hp.geometry,
                customer_count=chunk,
                road_id=hp.road_id,
                distance_to_road=hp.distance_to_road,
                fat_id=hp.fat_id
            )

            if current_customers + chunk <= max_capacity:
                current_group.append(hp_part)
                current_customers += chunk
            else:
                if current_group:
                    groups.append(current_group)
                current_group = [hp_part]
                current_customers = chunk

            remaining -= chunk

    if current_group:
        groups.append(current_group)

    return groups


def create_fat_from_homepasses(homepasses: List[Homepass], road_id: int,
                               counter: int, road_geom: QgsGeometry,
                               dist_calc: Optional[DistanceCalculator] = None,
                               roads: Optional[Dict[int, RoadSegment]] = None,
                               road_index: Optional[QgsSpatialIndex] = None,
                               building_index: Optional[QgsSpatialIndex] = None,
                               building_geoms: Optional[Dict[int, QgsGeometry]] = None) -> FAT:
    """Create a FAT from a list of homepasses"""
    # Calculate centroid of homepasses
    points = [hp.geometry for hp in homepasses]
    centroid_x = sum(p.x() for p in points) / len(points)
    centroid_y = sum(p.y() for p in points) / len(points)
    centroid = QgsPointXY(centroid_x, centroid_y)

    # Default placement is road-projected centroid.
    projected = road_geom.nearestPoint(QgsGeometry.fromPointXY(centroid))
    proj_point = projected.asPoint()

    # Determine dominant frontage side and place FAT on that side.
    side_votes: List[int] = []
    for hp in homepasses:
        s = _point_side_of_road(hp.geometry, road_geom)
        if s != 0:
            side_votes.append(1 if s > 0 else -1)
    side_sign = 1 if not side_votes or sum(side_votes) >= 0 else -1
    side_point = _offset_point_by_side(proj_point, road_geom, side_sign, rc.SNAP_OFFSET_DISTANCE)

    def _candidate_passes_crossing(cand: QgsPointXY) -> bool:
        """Check that links from candidate to all customers avoid road/building crossing (with corner exception)."""
        if roads is None or road_index is None:
            return True
        for hp in homepasses:
            is_corner = _is_near_road_junction(hp.geometry, road_geom, dist_calc, 10.0)
            link = QgsGeometry.fromPolylineXY([cand, hp.geometry])
            crosses_road = _line_intersects_other_roads(link, road_id, roads, road_index)
            crosses_building = _line_intersects_buildings(
                link, building_index or None, building_geoms or {}
            )
            if is_corner:
                if crosses_building:
                    return False
            else:
                if crosses_road or crosses_building:
                    return False
        return True

    fat_point = side_point
    if dist_calc:
        # Prefer side-point, then projected, then centroid.
        # Must satisfy both drop limit AND crossing constraints (no road/building crossing).
        candidates = [side_point, proj_point, centroid]
        best_pt = side_point
        best_max = float('inf')
        for cand in candidates:
            max_drop = 0.0
            for hp in homepasses:
                d = dist_calc.distance_points(hp.geometry, cand)
                if d > max_drop:
                    max_drop = d
            if max_drop > rc.MAX_BOX_TO_CUSTOMER_DISTANCE:
                continue
            if not _candidate_passes_crossing(cand):
                continue
            if max_drop < best_max:
                best_max = max_drop
                best_pt = cand
                break
        else:
            # No candidate passed both constraints; use projected (matches _cluster_fat_point)
            best_pt = proj_point
            if not _candidate_passes_crossing(best_pt):
                best_pt = centroid
        fat_point = best_pt

    # Get cascade order (based on position along road).
    # FIXED [Phase-1a]: use fat_point (the actual chosen FAT location — side-offset,
    # projected, or centroid) rather than the raw projected centroid.
    # Previously, cascade_order was computed from `projected` (always the centroid
    # snapped to road centre-line) while fat_point may be the side-offset copy of that
    # snap.  lineLocatePoint(projected) and lineLocatePoint(fat_point) diverge on
    # curved / L-shaped roads, causing the two boundary FATs resolved later in
    # assign_wings_per_fdt to land at inconsistent positions and pulling the FDT
    # toward the wrong end of the road.
    cascade_order = int(road_geom.lineLocatePoint(
        QgsGeometry.fromPointXY(fat_point)) * 1000)

    # SUM of homepass values (not count of points)
    total_customers = sum(_parse_homepass_value(hp.customer_count) for hp in homepasses)

    # customer_allocations: fid -> count for this FAT (supports split points across FATs)
    customer_allocations = {hp.fid: _parse_homepass_value(hp.customer_count) for hp in homepasses}

    return FAT(
        # Temporary deterministic placeholder, replaced by strict
        # hierarchical FAT code after FDT/wing assignment.
        name=f"TEMP-FAT-{counter:06d}",
        geometry=fat_point,
        road_id=road_id,
        total_customers=total_customers,
        cascade_order=cascade_order,
        from_device="",
        to_device="",
        wing="",
        customers=[hp.fid for hp in homepasses],
        customer_allocations=customer_allocations
    )


def _rebalance_fats_for_capacity(
    fats: List['FAT'],
    roads: Dict[int, 'RoadSegment'],
    road_layer: 'QgsVectorLayer',
    index_mgr: 'SpatialIndexManager',
    building_layer: Optional['QgsVectorLayer'],
    dist_calc: Optional['DistanceCalculator'],
    logger: 'PerformanceLogger',
    topo: Optional['RoadTopologyEngine'] = None,
    max_iterations: int = MAX_FAT_REBALANCE_ITERATIONS,
) -> List['FAT']:
    """Global, convergent FAT customer-capacity rebalancer.

    generate_fats() only resolves ONE unavoidable underfilled tail per
    design, via its own per-road balanced allocation plus a cross-road
    tail-borrow pass. Real designs routinely finish with several separately
    -unavoidable per-road/per-branch remainders, which
    validate_capacity_and_absorption_model() is right to reject — that hard
    gate is not the bug; the missing global repair stage is. This function
    is that second, dedicated stage: it dissolves underfilled FATs into
    geographically compatible neighbours (same road preferred, then
    network-distance-ranked — spec §10), moving actual Homepass-level
    customer ownership rather than just overwriting total_customers (spec
    §11), respects the same geometry/crossing guards
    create_fat_from_homepasses already enforces (spec §9), and iterates to
    convergence with a hard iteration cap (spec §18).

    Four FAT states are handled explicitly, never lumped into one generic
    "underfilled" bucket (corrective spec §6):
      A. customers == 0        -> EMPTY. Dissolved immediately and
                                   unconditionally, every iteration, before
                                   victim selection. Never a repair
                                   candidate, never a final exception.
      B. 0 < customers < MIN   -> UNDERFILLED. Attempted repair via the
                                   pool -> _balanced_partition_sizes ->
                                   re-derive pattern.
      C. MIN <= customers <=   -> VALID. Eligible donor/receiver/merge-pool
         MAX                      material.
      D. customers > MAX       -> INVALID OVERFULL. Defensively split
                                   before the main loop even starts (should
                                   never arrive this way from generate_fats,
                                   but never assumed).

    A single underfilled FAT that cannot currently be repaired is recorded
    in `blocked_victims` and skipped for the REST of that pass — it does
    NOT terminate the whole rebalancer (corrective spec §5/§11); other
    victims keep getting attempted. The blocked set is cleared whenever the
    population actually changes (a dissolve or a successful repair), so a
    FAT blocked early can be retried once new merge material appears.

    Operates purely at the FAT/Homepass level — it never touches FDT
    membership; that is _rebalance_fdts_for_capacity's separate job in the
    hierarchy (customer/homepass -> FAT -> FDT -> wing -> cascade -> cable).
    Runs strictly between generate_fats()/tail-borrow and FAT cascading.
    """
    if not fats:
        return fats

    logger.log("[FAT-REBALANCE] Starting global FAT capacity balancing")

    # Never trust a stale exception flag from an earlier stage — only the
    # final-exception block below may set it, and only once, at the end.
    for fat in fats:
        fat.is_global_final_fat_exception = False

    total_customers_before = sum(f.total_customers for f in fats)
    fats_before = len(fats)
    underfilled_before = sum(1 for f in fats if 0 < f.total_customers < MIN_FAT_CAPACITY)
    empty_seen_before = sum(1 for f in fats if f.total_customers <= 0)
    logger.log(
        f"[FAT-REBALANCE] Before: FATs={fats_before}, "
        f"underfilled={underfilled_before}, customers={total_customers_before}"
    )
    if empty_seen_before:
        logger.log(f"[FAT-REBALANCE] Empty FATs detected: {empty_seen_before}")
    if underfilled_before == 0 and empty_seen_before == 0:
        logger.log("[FAT-REBALANCE] Nothing to repair.")
        logger.log(
            f"[FAT-REBALANCE] After: FATs={fats_before}, underfilled=0, "
            f"customers={total_customers_before}. Capacity: PASS"
        )
        return fats

    # ── Global fid -> Homepass index (true original geometry/road_id) ──────
    # so a dissolved FAT's allocation is re-materialised from its REAL
    # original homepass position, never an approximation (spec §11/§14).
    fid_to_homepass: Dict[int, 'Homepass'] = {}
    for road in roads.values():
        for hp in road.homepasses:
            fid_to_homepass[hp.fid] = hp

    road_index = index_mgr.get_index(road_layer) if road_layer is not None else None
    building_index = None
    building_geoms: Dict[int, 'QgsGeometry'] = {}
    if building_layer is not None and index_mgr is not None:
        building_index = index_mgr.indices.get(building_layer.id())
        if building_index is None:
            building_index = index_mgr.build_index(building_layer, cache_geoms=True)
        building_geoms = index_mgr.geometries.get(building_layer.id(), {})

    def _fat_homepasses(fat: 'FAT') -> List['Homepass']:
        """This FAT's actual homepass allocation (its own share of each
        fid — never the fid's full original count, since a homepass can be
        split across FATs), reconstructed from customer_allocations."""
        out = []
        for fid, count in fat.customer_allocations.items():
            src = fid_to_homepass.get(fid)
            if src is None or count <= 0:
                continue
            out.append(Homepass(
                fid=src.fid, geometry=src.geometry, customer_count=count,
                road_id=src.road_id, distance_to_road=src.distance_to_road,
                fat_id=fat.name, borrowed_from_road=src.borrowed_from_road,
            ))
        return out

    def _majority_road_id(homepasses: List['Homepass']) -> Optional[int]:
        counts: Dict[int, int] = {}
        for hp in homepasses:
            if hp.road_id is not None:
                counts[hp.road_id] = counts.get(hp.road_id, 0) + 1
        if not counts:
            return None
        return max(counts.items(), key=lambda kv: kv[1])[0]

    def _coalesce_by_fid(homepasses: List['Homepass']) -> List['Homepass']:
        """Merge same-fid entries into one before handing them to
        create_fat_from_homepasses.

        A single original homepass can legitimately be split across
        multiple FATs (that's exactly what customer_allocations/split
        points exist for). Once rebalancing pools several FATs together,
        _fat_homepasses() can therefore produce two separate entries for
        the SAME fid (each carrying a different partial count) inside one
        pool — and if both land in the same new target chunk,
        create_fat_from_homepasses's `{hp.fid: count for hp in homepasses}`
        dict comprehension silently keeps only the LAST one, discarding the
        other's customers (total_customers still sums correctly since it
        iterates the full list — customer_allocations is what desyncs).
        Coalescing here — summing counts for a duplicate fid into a single
        entry — is what the spec §14/§15 invariant check
        (customer_allocations sum == total_customers) is guarding against.
        """
        merged: Dict[int, 'Homepass'] = {}
        for hp in homepasses:
            existing = merged.get(hp.fid)
            if existing is None:
                merged[hp.fid] = hp
            else:
                merged[hp.fid] = Homepass(
                    fid=hp.fid, geometry=existing.geometry,
                    customer_count=existing.customer_count + hp.customer_count,
                    road_id=existing.road_id, distance_to_road=existing.distance_to_road,
                    fat_id=existing.fat_id, borrowed_from_road=existing.borrowed_from_road,
                )
        return list(merged.values())

    _rebuild_counter = [0]

    def _rebuild(target: 'FAT', homepasses: List['Homepass']) -> None:
        """Recompute geometry, road association, cascade_order, and
        customer allocation for `target` from a materially-changed
        homepass membership — via the same create_fat_from_homepasses
        machinery generate_fats() itself uses, never a hand-rolled
        shortcut (spec §14)."""
        homepasses = _coalesce_by_fid(homepasses)
        _rebuild_counter[0] += 1
        new_road_id = _majority_road_id(homepasses) or target.road_id
        road = roads.get(new_road_id)
        road_geom = road.geometry if road is not None else None
        if road_geom is None or road_geom.isEmpty():
            xs = [hp.geometry.x() for hp in homepasses]
            ys = [hp.geometry.y() for hp in homepasses]
            target.geometry = QgsPointXY(sum(xs) / len(xs), sum(ys) / len(ys))
            target.road_id = new_road_id
            target.total_customers = sum(hp.customer_count for hp in homepasses)
            target.customers = [hp.fid for hp in homepasses]
            target.customer_allocations = {hp.fid: hp.customer_count for hp in homepasses}
            return
        rebuilt = create_fat_from_homepasses(
            homepasses, new_road_id, _rebuild_counter[0], road_geom,
            dist_calc=dist_calc, roads=roads,
            road_index=road_index, building_index=building_index,
            building_geoms=building_geoms,
        )
        target.geometry = rebuilt.geometry
        target.road_id = new_road_id
        target.cascade_order = rebuilt.cascade_order
        target.total_customers = rebuilt.total_customers
        target.customers = rebuilt.customers
        target.customer_allocations = rebuilt.customer_allocations
        # FAT identity/name is deliberately left untouched here — generate_fats
        # already marks every FAT with a temporary placeholder name at this
        # pipeline stage (rebuilt downstream into the final hierarchical
        # code after FDT/wing assignment, spec §15), so there is nothing
        # meaningful to rename yet.

    def _net_dist(a: 'FAT', b: 'FAT') -> float:
        return _network_distance(
            a.snapped_geometry or a.geometry, b.snapped_geometry or b.geometry,
            road_a_id=a.road_id, road_b_id=b.road_id,
            topo=topo, dist_calc=dist_calc,
        )

    def _dissolve_empty(fats_list: List['FAT']) -> Tuple[List['FAT'], bool]:
        """STATE A: total_customers <= 0 is NOT an underfilled FAT to be
        repaired — it's an empty object with nothing to redistribute, and
        must be removed unconditionally (corrective spec §2/§3). Verifies
        no phantom demand is hidden in customer_allocations before deleting
        it, so this can never silently violate customer conservation."""
        survivors: List['FAT'] = []
        removed_any = False
        for f in fats_list:
            if f.is_relay:
                # Cable-relay FATs don't exist yet at this pipeline stage
                # (they're only created later by create_fat_cascade's
                # insert_intermediate_fats), but this guard is defensive:
                # a relay FAT's total_customers=0 is by design, never a
                # dissolve candidate, no matter when this function runs.
                survivors.append(f)
                continue
            if f.total_customers <= 0:
                alloc_sum = sum(f.customer_allocations.values()) if f.customer_allocations else 0
                if alloc_sum != 0:
                    raise ValidationError(
                        f"[FAT-REBALANCE] {f.name} has total_customers=0 but "
                        f"customer_allocations sums to {alloc_sum} — refusing "
                        f"to dissolve it, since that would silently destroy "
                        f"{alloc_sum} customer(s) of hidden demand."
                    )
                f.is_global_final_fat_exception = False
                logger.log(
                    f"[FAT-REBALANCE] Empty FAT dissolved: {f.name} "
                    f"customers=0 reason=EMPTY_FAT_NO_CUSTOMER_ALLOCATION"
                )
                removed_any = True
            else:
                survivors.append(f)
        return survivors, removed_any

    def _split_overfull(fats_list: List['FAT']) -> List['FAT']:
        """STATE D defensive guard: generate_fats() already caps every FAT
        at MAX_FAT_CAPACITY, but this function must never assume an
        upstream invariant holds — split any FAT that somehow arrives over
        MAX before the main loop even starts, using the same balanced
        partitioner and rebuild machinery as everything else here."""
        out: List['FAT'] = []
        for f in fats_list:
            if f.total_customers <= MAX_FAT_CAPACITY:
                out.append(f)
                continue
            sizes, _ = _balanced_partition_sizes(
                f.total_customers, MIN_FAT_CAPACITY, MAX_FAT_CAPACITY
            )
            homepasses = _fat_homepasses(f)
            homepasses.sort(key=lambda hp: dist_calc.distance_points(hp.geometry, f.geometry)
                             if dist_calc is not None else 0.0)
            idx = 0
            new_fats: List['FAT'] = []
            for size in sizes:
                chunk: List['Homepass'] = []
                have = 0
                while have < size and idx < len(homepasses):
                    hp = homepasses[idx]
                    idx += 1
                    take = min(hp.customer_count, size - have)
                    if take <= 0:
                        continue
                    chunk.append(Homepass(
                        fid=hp.fid, geometry=hp.geometry, customer_count=take,
                        road_id=hp.road_id, distance_to_road=hp.distance_to_road,
                        fat_id=hp.fat_id, borrowed_from_road=hp.borrowed_from_road,
                    ))
                    leftover = hp.customer_count - take
                    if leftover > 0:
                        homepasses.insert(idx, Homepass(
                            fid=hp.fid, geometry=hp.geometry, customer_count=leftover,
                            road_id=hp.road_id, distance_to_road=hp.distance_to_road,
                            fat_id=hp.fat_id, borrowed_from_road=hp.borrowed_from_road,
                        ))
                    have += take
                new_fats.append(chunk)
            f_chunk, extra_chunks = new_fats[0], new_fats[1:]
            _rebuild(f, f_chunk)
            out.append(f)
            for chunk in extra_chunks:
                clone = FAT(
                    name=f"{f.name}-SPLIT{len(extra_chunks)}", geometry=f.geometry,
                    road_id=f.road_id, total_customers=0, cascade_order=0,
                    from_device="", to_device="", wing="",
                )
                _rebuild(clone, chunk)
                out.append(clone)
                logger.log(
                    f"[FAT-REBALANCE] {f.name} exceeded MAX — overflow split "
                    f"into {clone.name} ({clone.total_customers} customers)"
                )
        return out

    fats = list(fats)
    fats, _ = _dissolve_empty(fats)
    fats = _split_overfull(fats)
    if empty_seen_before:
        logger.log(f"[FAT-REBALANCE] Active FATs after empty-FAT cleanup: {len(fats)}")

    # spec §5/§11: a FAT that can't currently be repaired is recorded here
    # and skipped for the rest of THIS pass — it must never abort the whole
    # rebalancer. Cleared whenever the population actually changes, so a
    # previously-blocked FAT gets retried once new merge material exists.
    blocked_victims: Set[str] = set()

    for _iteration in range(max_iterations):
        fats, dissolved_empty_this_pass = _dissolve_empty(fats)
        if dissolved_empty_this_pass:
            blocked_victims.clear()

        underfilled = [
            f for f in fats
            if 0 < f.total_customers < MIN_FAT_CAPACITY and f.name not in blocked_victims
        ]
        if not underfilled:
            break

        victim = min(underfilled, key=lambda f: f.total_customers)
        # spec §10: same-road candidates rank ahead of every other road,
        # network-distance-ranked within each tier — never raw Euclidean.
        candidates = sorted(
            (f for f in fats if f.name != victim.name),
            key=lambda f: (0 if f.road_id == victim.road_id else 1, _net_dist(victim, f)),
        )

        pool = [victim]
        sizes, exact = _balanced_partition_sizes(
            victim.total_customers, MIN_FAT_CAPACITY, MAX_FAT_CAPACITY
        )
        blocked: List[str] = []
        for candidate in candidates:
            if exact:
                break
            hop = _net_dist(victim, candidate)
            if hop > rc.MAX_BOX_TO_CUSTOMER_DISTANCE * 4:
                # spec §9: reject a candidate that would create a physically
                # unreasonable drop/box relationship, keep searching.
                blocked.append(
                    f"{candidate.name}: rejected, network distance "
                    f"{hop:.0f}m exceeds allowed reach"
                )
                continue
            pool.append(candidate)
            pool_total = sum(f.total_customers for f in pool)
            sizes, exact = _balanced_partition_sizes(pool_total, MIN_FAT_CAPACITY, MAX_FAT_CAPACITY)

        if len(pool) == 1 or not exact:
            # spec §5/§11/§13: blocked, NOT terminal. Record it, move on to
            # the next weakest still-eligible victim in this same pass —
            # only run out of victims (underfilled empty) or hit
            # max_iterations ends the loop, never a single failed search.
            blocked_victims.add(victim.name)
            logger.log(
                f"[FAT-REBALANCE-BLOCKED] {victim.name} = "
                f"{victim.total_customers} customers"
            )
            for line in blocked[:5]:
                logger.log(f"  {line}")
            continue

        # Keep the identity of the largest (healthiest) pool members as the
        # surviving FAT containers, dissolving the smallest ones — mirrors
        # "merge FAT-A's demand into FAT-B" rather than the reverse.
        pool_sorted_for_identity = sorted(pool, key=lambda f: f.total_customers, reverse=True)
        target_fats = pool_sorted_for_identity[:len(sizes)]
        dissolved = pool_sorted_for_identity[len(sizes):]

        pool_homepasses: List['Homepass'] = []
        for f in pool:
            pool_homepasses.extend(_fat_homepasses(f))
        pool_homepasses.sort(key=lambda hp: dist_calc.distance_points(hp.geometry, victim.geometry)
                              if dist_calc is not None else 0.0)

        idx = 0
        for i, size in enumerate(sizes):
            chunk_hps: List['Homepass'] = []
            chunk_customers = 0
            while chunk_customers < size and idx < len(pool_homepasses):
                hp = pool_homepasses[idx]
                idx += 1
                take = min(hp.customer_count, size - chunk_customers)
                if take <= 0:
                    continue
                chunk_hps.append(Homepass(
                    fid=hp.fid, geometry=hp.geometry, customer_count=take,
                    road_id=hp.road_id, distance_to_road=hp.distance_to_road,
                    fat_id=hp.fat_id, borrowed_from_road=hp.borrowed_from_road,
                ))
                leftover = hp.customer_count - take
                if leftover > 0:
                    pool_homepasses.insert(idx, Homepass(
                        fid=hp.fid, geometry=hp.geometry, customer_count=leftover,
                        road_id=hp.road_id, distance_to_road=hp.distance_to_road,
                        fat_id=hp.fat_id, borrowed_from_road=hp.borrowed_from_road,
                    ))
                chunk_customers += take
            target = target_fats[i]
            before = target.total_customers
            _rebuild(target, chunk_hps)
            # spec §8: a repartition operation must never itself create a
            # new empty FAT — every size in `sizes` is > 0 by construction
            # of _balanced_partition_sizes, so this is a defensive assert,
            # not an expected path.
            if target.total_customers <= 0:
                raise ValidationError(
                    f"[FAT-REBALANCE] Repartition produced an empty FAT "
                    f"({target.name}) from a non-empty pool — internal "
                    f"invariant violated."
                )
            logger.log(
                f"[FAT-REBALANCE] {target.name}: {before} -> "
                f"{target.total_customers} customers ({len(chunk_hps)} homepass-parts)"
            )

        for f in dissolved:
            logger.log(f"[FAT-REBALANCE] {f.name} ({f.total_customers} customers) dissolved")
        dissolved_names = {f.name for f in dissolved}
        fats = [f for f in fats if f.name not in dissolved_names]

        logger.log(
            f"[FAT-REBALANCE] pool-rebalance: {[f.name for f in pool]} -> "
            f"{len(sizes)} FAT(s), sizes={sizes}"
        )
        # Population changed — a previously-blocked victim may be
        # repairable now (spec §11: don't let one stale block linger).
        blocked_victims.clear()

    # ── Final empty-FAT cleanup + audit (spec §2/§16) ───────────────────────
    fats, _ = _dissolve_empty(fats)
    empty_remaining = [f for f in fats if f.total_customers <= 0]
    if empty_remaining:
        raise ValidationError(
            f"[FAT-EMPTY-AUDIT] {len(empty_remaining)} empty FAT(s) survived "
            f"rebalancing: {[f.name for f in empty_remaining]}"
        )

    # ── Per-FAT allocation invariant (spec §14/§15) ─────────────────────────
    for f in fats:
        alloc_sum = sum(f.customer_allocations.values())
        if alloc_sum != f.total_customers:
            raise ValidationError(
                f"[FAT-REBALANCE] Allocation mismatch: {f.name} "
                f"total_customers={f.total_customers} but customer_allocations "
                f"sums to {alloc_sum}"
            )

    # ── Customer conservation invariant (hard gate — spec §4/§12) ──────────
    total_customers_after = sum(f.total_customers for f in fats)
    if total_customers_after != total_customers_before:
        raise ValidationError(
            f"[FAT-REBALANCE] Customer conservation violated: before="
            f"{total_customers_before}, after={total_customers_after}, "
            f"diff={total_customers_after - total_customers_before}"
        )
    logger.log("[FAT-REBALANCE] Customer conservation: PASS")

    # ── Single explicit global final FAT exception (spec §17/§18) ──────────
    still_low = [f for f in fats if 0 < f.total_customers < MIN_FAT_CAPACITY]
    if len(still_low) == 1:
        still_low[0].is_global_final_fat_exception = True
        logger.log(
            f"[FAT-REBALANCE] Global final FAT exception: {still_low[0].name} "
            f"({still_low[0].total_customers} customers) — no further legal "
            f"repair exists; flagged as the single permitted exception."
        )
    elif len(still_low) > 1:
        for f in still_low:
            logger.log(
                f"WARNING [FAT_BELOW_MINIMUM]: {f.name} has {f.total_customers} "
                f"customers (< {MIN_FAT_CAPACITY}); {len(still_low)} FATs remain "
                f"below minimum after exhausting all legal rebalancing — only "
                f"ONE global final-FAT exception is permitted. This design "
                f"will fail hard-gate validation."
            )

    underfilled_after = len(still_low)
    logger.log(f"[FAT-REBALANCE] Empty FATs remaining: 0")
    logger.log(f"[FAT-REBALANCE] FATs below minimum: {underfilled_after}")
    logger.log(
        f"[FAT-REBALANCE] After: FATs={len(fats)}, underfilled={underfilled_after}, "
        f"customers={total_customers_after}. "
        f"Capacity: {'PASS' if underfilled_after <= 1 else 'FAIL'}"
    )

    return fats
