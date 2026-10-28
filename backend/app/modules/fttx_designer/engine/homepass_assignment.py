"""Verbatim port of the homepass-to-road assignment stage from
``FTTx Designer — dual PON integrated.py``: ``_parse_homepass_value``,
``safe_homepass_sum``, ``_line_intersects_other_roads``,
``assign_homepasses_to_roads``, and ``_apply_coverage_trim`` (the V5
coverage-percentage trim step that runs immediately after homepass
assignment, per the pipeline's own call order — CLAUDE.md:
"assign_homepasses_to_roads [+ coverage trim] → generate_fats").

No logic changes from the source script — only the QGIS types, which now
come from ``engine.geometry_compat`` instead of ``qgis.core``.

Note: ``MAX_BOX_TO_CUSTOMER_DISTANCE`` and ``HOMEPASS_FIELD_NAME`` are two
of the 8 tunables the pipeline overrides per-run (see runtime_config.py's
docstring) — read through ``runtime_config.X``, never imported by bare
name, so a run-configured value actually reaches this module.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from . import runtime_config as rc
from .domain import Homepass, RoadSegment
from .geometry_compat import QgsGeometry, QgsSpatialIndex, QgsVectorLayer
from .perf_logger import PerformanceLogger
from .spatial_utils import DistanceCalculator, SpatialIndexManager


def _parse_homepass_value(value) -> int:
    """Convert homepass field value to integer. Handles text/mixed types safely.

    Rule: SUM(homepass) per FAT, not COUNT(points). Values must be numeric.
    If conversion fails, treat as 0.
    """
    try:
        hp = float(value)
    except (ValueError, TypeError):
        return 0
    return int(hp)


def safe_homepass_sum(features, field_name: str) -> int:
    """Sum homepass values from a list of features safely.

    IMPORTANT: Uses SUM(homepass values), NOT COUNT(points).
    Null or non-numeric values contribute 0.
    """
    total = 0
    for f in features:
        try:
            value = f[field_name]
        except Exception:
            value = None
        hp = _parse_homepass_value(value)
        total += hp
    return total


def _line_intersects_other_roads(line_geom: QgsGeometry,
                                 candidate_road_id: int,
                                 roads: Dict[int, RoadSegment],
                                 road_index: Optional[QgsSpatialIndex]) -> bool:
    """Return True if line truly crosses any road except candidate_road_id.

    Uses crosses() instead of intersects() to exclude roads that merely
    touch at a shared endpoint (e.g. the target road itself meeting an
    adjacent road at a junction).  Bounding-box pre-filter is still used
    for performance, but only geometries that actually cross the line
    (not just overlap in bbox) are counted.
    """
    if not line_geom or line_geom.isEmpty():
        return False
    bbox = line_geom.boundingBox()
    if road_index:
        candidate_ids = road_index.intersects(bbox)
    else:
        candidate_ids = list(roads.keys())
    for rid in candidate_ids:
        if rid == candidate_road_id:
            continue
        road = roads.get(rid)
        if not road or not road.geometry or road.geometry.isEmpty():
            continue
        # crosses() is True only when the interiors intersect but neither
        # geometry is wholly contained — exactly what a genuine road crossing
        # looks like.  touching at a single endpoint (junction) returns False.
        if line_geom.crosses(road.geometry):
            return True
    return False


# =============================================================================
# HOMEPASS PROCESSING AND ROAD ASSIGNMENT
# =============================================================================

def assign_homepasses_to_roads(homepass_layer: QgsVectorLayer,
                               road_layer: QgsVectorLayer,
                               roads: Dict[int, RoadSegment],
                               index_mgr: SpatialIndexManager,
                               dist_calc: DistanceCalculator,
                               logger: PerformanceLogger) -> List[Homepass]:
    """Assign each homepass to road frontage using top-3 nearest + crossing filter."""
    logger.start_module("Homepass Assignment")

    homepasses = []
    # build or retrieve index for the road layer instead of using layer.parent()
    road_index = index_mgr.get_index(road_layer)

    features = list(homepass_layer.getFeatures())
    original_total = safe_homepass_sum(features, rc.HOMEPASS_FIELD_NAME)

    hp_field_idx = homepass_layer.fields().indexOf(rc.HOMEPASS_FIELD_NAME)

    for feat in features:
        geom = feat.geometry()
        if not geom or geom.isEmpty():
            continue

        point = geom.asPoint()
        point_geom = QgsGeometry.fromPointXY(point)

        if hp_field_idx >= 0:
            hp_val = _parse_homepass_value(feat.attribute(hp_field_idx))
        else:
            hp_val = 0

        candidate_ids = road_index.nearestNeighbor(point, 5)
        best_road_id = None
        best_dist = float('inf')

        for rid in candidate_ids:
            if rid not in roads:
                continue
            road = roads[rid]
            road_geom = road.geometry
            near_pt = road_geom.nearestPoint(point_geom).asPoint()
            d = dist_calc.distance_points(point, near_pt)
            # Only consider roads within a reasonable service distance
            if d > rc.MAX_BOX_TO_CUSTOMER_DISTANCE:
                continue
            access_line = QgsGeometry.fromPolylineXY([point, near_pt])
            if _line_intersects_other_roads(access_line, rid, roads, road_index):
                continue
            # ── [FIX-DCW-2] Dual-carriageway side penalty ────────────────────
            # If this road is one carriageway of a dual pair, check whether the
            # homepass is physically closer to the PARTNER carriageway.  When it
            # is, we use a penalised comparison distance so the correct-side
            # carriageway wins — but we store only the raw (unpenalised) d in
            # best_dist so distance_to_road on the Homepass object is never
            # inflated to a bogus 299m+ value that trips drop-distance validation.
            # We do NOT hard-skip — the fallback path is preserved for median-gap
            # buildings that have no better reachable road.
            _dcw_cmp_d = d   # comparison distance (may be penalised)
            if road.dual_cw_partner is not None:
                _partner = roads.get(road.dual_cw_partner)
                if _partner and not _partner.geometry.isEmpty():
                    _partner_near_pt = _partner.geometry.nearestPoint(point_geom).asPoint()
                    _d_partner = dist_calc.distance_points(point, _partner_near_pt)
                    if _d_partner < d:
                        # Homepass is closer to partner side — penalise comparison only
                        _dcw_cmp_d = d + rc.MAX_BOX_TO_CUSTOMER_DISTANCE
            # ── END [FIX-DCW-2] ───────────────────────────────────────────────
            if _dcw_cmp_d < best_dist:
                best_dist = d          # store RAW distance — not the penalised value
                best_road_id = rid

        # Fallback: among all candidates pick the geometrically nearest road
        # that is reachable (no road crossing), ignoring distance cap.
        # This ensures we never silently assign to the wrong street.
        if best_road_id is None and candidate_ids:
            fallback_best_id = None
            fallback_best_dist = float('inf')
            for rid in candidate_ids:
                if rid not in roads:
                    continue
                road = roads[rid]
                near_pt = road.geometry.nearestPoint(point_geom).asPoint()
                d = dist_calc.distance_points(point, near_pt)
                access_line = QgsGeometry.fromPolylineXY([point, near_pt])
                if _line_intersects_other_roads(access_line, rid, roads, road_index):
                    continue
                if d < fallback_best_dist:
                    fallback_best_dist = d
                    fallback_best_id = rid
            # If still nothing passes crossing check, take the absolute nearest
            if fallback_best_id is None:
                for rid in candidate_ids:
                    if rid not in roads:
                        continue
                    near_pt = roads[rid].geometry.nearestPoint(point_geom).asPoint()
                    d = dist_calc.distance_points(point, near_pt)
                    if d < fallback_best_dist:
                        fallback_best_dist = d
                        fallback_best_id = rid
            if fallback_best_id is not None:
                best_road_id = fallback_best_id
                best_dist = fallback_best_dist

        if best_road_id is not None and best_road_id in roads:
            road = roads[best_road_id]
            hp = Homepass(
                fid=feat.id(),
                geometry=point,
                customer_count=hp_val,
                road_id=best_road_id,
                distance_to_road=best_dist
            )
            homepasses.append(hp)
            road.homepasses.append(hp)
            road.total_customers += hp_val

    # verify sum consistency
    assigned_total = sum(hp.customer_count for hp in homepasses)
    if assigned_total != original_total:
        logger.log(
            f"WARNING [HOMEPASS_MISMATCH]: assigned total {assigned_total} "
            f"differs from original {original_total}"
        )

    logger.end_module("Homepass Assignment")
    logger.log(f"Processed {len(homepasses)} homepasses, total customers: {assigned_total}")

    return homepasses


# =============================================================================
# V5: COVERAGE TRIMMING (Part 1)
# =============================================================================

def _apply_coverage_trim(homepasses: List['Homepass'],
                         roads: Dict[int, 'RoadSegment'],
                         coverage_pct: int,
                         logger: 'PerformanceLogger') -> List['Homepass']:
    """Per-road proportional homepass trimming for coverage % < 100.

    Sorts each road's homepasses by physical position along road (lineLocatePoint)
    and retains a spatially-contiguous prefix whose customer count sum meets the
    per-road quota.  Partial homepass records are cloned with a reduced
    customer_count to hit the quota exactly.

    CRITICAL: After trimming, each RoadSegment's .homepasses list and
    .total_customers counter are rewritten to match the retained set so that
    generate_fats() — which reads road.homepasses / road.total_customers
    directly — operates only on the trimmed demand.
    """
    if coverage_pct >= 100:
        return homepasses

    logger.log(f"Coverage trim: retaining {coverage_pct}% of homepasses per road")
    by_road: Dict[int, List] = defaultdict(list)
    for hp in homepasses:
        by_road[hp.road_id].append(hp)

    retained = []
    retained_by_road: Dict[int, List] = defaultdict(list)

    for road_id, road_hps in by_road.items():
        road_geom = roads[road_id].geometry if roads.get(road_id) else None
        if road_geom:
            road_hps.sort(
                key=lambda h: road_geom.lineLocatePoint(
                    QgsGeometry.fromPointXY(h.geometry)
                )
            )
        road_total = sum(_parse_homepass_value(h.customer_count) for h in road_hps)
        quota = max(0, round(road_total * coverage_pct / 100))
        running = 0
        for hp in road_hps:
            if running >= quota:
                break
            hp_val = _parse_homepass_value(hp.customer_count)
            take = min(hp_val, quota - running)
            if take == hp_val:
                retained.append(hp)
                retained_by_road[road_id].append(hp)
            else:
                # Partial clone — preserves geometry, reduces customer count
                partial = Homepass(
                    fid=hp.fid,
                    geometry=hp.geometry,
                    customer_count=take,
                    road_id=hp.road_id,
                    distance_to_road=hp.distance_to_road,
                )
                retained.append(partial)
                retained_by_road[road_id].append(partial)
            running += take

    # ── CRITICAL: write trimmed lists back into RoadSegment objects ────────────
    # generate_fats() reads road.homepasses and road.total_customers directly;
    # it does NOT use the homepasses list returned from assign_homepasses_to_roads.
    # Roads not present in retained_by_road had all their homepasses trimmed away.
    for road_id, road in roads.items():
        trimmed_hps = retained_by_road.get(road_id, [])
        road.homepasses = trimmed_hps
        road.total_customers = sum(_parse_homepass_value(h.customer_count) for h in trimmed_hps)

    before_hp  = sum(_parse_homepass_value(hp.customer_count) for hp in homepasses)
    after_hp   = sum(_parse_homepass_value(hp.customer_count) for hp in retained)
    logger.log(
        f"Coverage trim: {len(homepasses)} → {len(retained)} homepass records, "
        f"customers {before_hp} → {after_hp} ({coverage_pct}% target). "
        f"Road segments updated: {len(retained_by_road)}/{len(roads)}"
    )
    return retained
