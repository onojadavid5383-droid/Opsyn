"""Verbatim port of the pure-algorithm Hybrid-deployment functions from
``FTTx Designer — dual PON integrated.py``: ``_classify_road_zones``,
``_find_handover_points``.

No logic changes from the source script — only the QGIS types and
cross-module imports.

Deliberately excluded from this module (same reasoning as
``underground.py``/``drainage.py``'s docstrings): ``_load_boundary_layer``
(a ``QgsProject.instance().mapLayersByName(...)`` lookup) and the full
``HybridStrategy`` class. Both functions here only need an already-resolved
``boundary_layer`` object (or none, for ``_classify_road_zones`` — "no
boundary layer" is itself a valid, handled case, defaulting every road to
aerial) — agnostic to how the caller obtained it — so they port cleanly
now.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..domain import RoadSegment
from ..geometry_compat import QgsGeometry, QgsPointXY, QgsSpatialIndex, QgsVectorLayer
from ..perf_logger import PerformanceLogger
from ..spatial_utils import DistanceCalculator

# One of the pipeline's 8 per-run tunables (see runtime_config.py) is NOT
# involved here — TOPOLOGY_SNAP_TOLERANCE is a static config constant, not
# mutable-8, so a bare import (not `rc.`-qualified) is correct.
from ..config import TOPOLOGY_SNAP_TOLERANCE


def _classify_road_zones(
    roads: Dict[int, 'RoadSegment'],
    boundary_layer: Optional['QgsVectorLayer'],
    aerial_field: str,
    aerial_value: str,
    logger: 'PerformanceLogger',
) -> Tuple[Dict[int, 'RoadSegment'], Dict[int, 'RoadSegment']]:
    """Split roads into aerial_roads and underground_roads by zone polygon.

    A road is classified as aerial if its midpoint falls inside any
    polygon feature whose ``aerial_field`` value equals ``aerial_value``.
    Roads outside all polygons, or when no boundary layer exists, default
    to aerial.

    Returns
    -------
    (aerial_roads, underground_roads)  — both are subsets of ``roads``
    """
    if boundary_layer is None:
        logger.log("  HybridStrategy: no boundary layer — all roads treated as aerial")
        return dict(roads), {}

    # Build spatial index for boundary polygons
    b_index = QgsSpatialIndex()
    b_geoms: Dict[int, QgsGeometry] = {}
    b_field_vals: Dict[int, str] = {}
    field_idx = boundary_layer.fields().indexOf(aerial_field)

    for feat in boundary_layer.getFeatures():
        geom = feat.geometry()
        if geom and not geom.isEmpty():
            b_index.addFeature(feat)
            b_geoms[feat.id()] = geom
            if field_idx >= 0:
                b_field_vals[feat.id()] = str(feat.attributes()[field_idx])
            else:
                b_field_vals[feat.id()] = aerial_value  # assume aerial if field missing

    aerial_roads: Dict[int, 'RoadSegment'] = {}
    underground_roads: Dict[int, 'RoadSegment'] = {}

    for rid, road in roads.items():
        geom = road.geometry
        if not geom or geom.isEmpty():
            aerial_roads[rid] = road
            continue

        # Use road midpoint for zone classification
        mid_geom = geom.interpolate(geom.length() / 2.0)
        if mid_geom.isEmpty():
            aerial_roads[rid] = road
            continue

        mid_pt = mid_geom.asPoint()
        candidates = b_index.intersects(mid_geom.boundingBox())

        is_aerial = True  # default
        for fid in candidates:
            bgeom = b_geoms.get(fid)
            if bgeom and bgeom.contains(mid_geom):
                zone_val = b_field_vals.get(fid, aerial_value)
                is_aerial = (zone_val == aerial_value)
                break

        if is_aerial:
            aerial_roads[rid] = road
        else:
            underground_roads[rid] = road

    logger.log(
        f"  _classify_road_zones: {len(aerial_roads)} aerial roads, "
        f"{len(underground_roads)} underground roads"
    )
    return aerial_roads, underground_roads


def _find_handover_points(
    aerial_roads: Dict[int, 'RoadSegment'],
    underground_roads: Dict[int, 'RoadSegment'],
    dist_calc: 'DistanceCalculator',
    logger: 'PerformanceLogger',
) -> List[QgsPointXY]:
    """Locate zone boundary handover points (aerial ↔ underground transitions).

    A handover point is the nearest endpoint pair between an aerial road
    and an adjacent underground road.  These become dual-type structures
    (a pole with a handhole mount) in the BOQ — tracked in the structure
    list as a PoleStructure with ``remarks = "handover"``.
    """
    SNAP_DEDUP = TOPOLOGY_SNAP_TOLERANCE * 4
    handover_pts: List[QgsPointXY] = []
    accepted: List[QgsPointXY] = []

    def _endpoints(road: 'RoadSegment') -> List[QgsPointXY]:
        if not road.geometry or road.geometry.isEmpty():
            return []
        v = road.geometry.asPolyline() if not road.geometry.isMultipart() \
            else road.geometry.asMultiPolyline()[0]
        return [v[0], v[-1]] if v else []

    for aerial_road in aerial_roads.values():
        a_pts = _endpoints(aerial_road)
        for ug_road in underground_roads.values():
            u_pts = _endpoints(ug_road)
            for apt in a_pts:
                for upt in u_pts:
                    d = dist_calc.distance_points(apt, upt)
                    if d < TOPOLOGY_SNAP_TOLERANCE * 6:
                        # midpoint between the two endpoints
                        mid = QgsPointXY(
                            (apt.x() + upt.x()) / 2,
                            (apt.y() + upt.y()) / 2,
                        )
                        too_close = any(
                            dist_calc.distance_points(mid, ep) < SNAP_DEDUP
                            for ep in accepted
                        )
                        if not too_close:
                            handover_pts.append(mid)
                            accepted.append(mid)

    logger.log(
        f"  _find_handover_points: {len(handover_pts)} handover locations identified"
    )
    return handover_pts
