"""Verbatim port of the pure-algorithm Underground-deployment functions from
``FTTx Designer — dual PON integrated.py``: ``place_ug_structures``,
``route_duct_segments``, ``route_duct_segments_with_ledger``,
``_build_underground_boq``.

No logic changes from the source script — only the QGIS types and
cross-module imports.

Deliberately excluded from this module (and not yet ported anywhere):
``_load_existing_ug_structures`` and the full ``UndergroundStrategy``
class. Both are irreducibly built on ``QgsProject.instance().
mapLayersByName(...)`` — resolving "the existing handhole/manhole layer the
user picked, by name, from the currently-open project" — a desktop-GUI
layer-selection paradigm with no equivalent in a stateless web backend (an
"existing structures" upload would need its own resolution path in the
wizard, decided in Phase 3/4, not assumed here). The four functions above
have no such dependency — they operate purely on already-resolved
``RoadSegment``/``FDT``/``DomeClosure``/``SupportStructure`` objects (plus,
for ``_build_underground_boq``, an already-constructed ``QgsVectorLayer``)
— so they port cleanly now, ahead of the strategy class that will
eventually call them.

``_build_underground_boq`` uses ``QgsFeature(boq_layer.fields())`` (the
same bound-construction pattern ``boq.py`` already relies on) plus
``boq_layer.addFeature(feat)`` — a single-feature counterpart to
``dataProvider().addFeatures([...])`` added to the ``geometry_compat``
``QgsVectorLayer`` shim alongside this port.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from ..cascade import _project_tag
from ..config import CORRIDOR_ANGLE_THRESHOLD, TOPOLOGY_SNAP_TOLERANCE, FTTXConfig
from ..domain import DomeClosure, DuctRoute, FDT, HandholeStructure, ManholeStructure, RoadSegment, SupportStructure
from ..errors import FTTXError
from ..geometry_compat import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer
from ..perf_logger import PerformanceLogger
from ..spatial_utils import DistanceCalculator

if TYPE_CHECKING:
    from ..cable_routing import CableRouter
    from ..topology import RoadTopologyEngine
    from .duct_occupancy import DuctOccupancyLedger


def place_ug_structures(
    roads: Dict[int, 'RoadSegment'],
    topo: Optional['RoadTopologyEngine'],
    fdts: List['FDT'],
    closures: List['DomeClosure'],
    config: 'FTTXConfig',
    dist_calc: 'DistanceCalculator',
    logger: 'PerformanceLogger',
) -> List[SupportStructure]:
    """Place proposed underground structures according to the spec's eight triggers.

    Trigger  Source in existing data
    -------  -------------------------------------------------------
    1  Regular user spacing      Walk chainage along every road geometry
    2  Major intersections       degree >= 3 nodes in topo._nodes
    3  > 45° bends               bearing_diff > CORRIDOR_ANGLE_THRESHOLD at degree-2 nodes
    4  FDT locations             fdt.snapped_geometry or fdt.geometry
    5  Closure locations         closure.snapped_geometry or closure.geometry
    6  Branching points          same as intersections (covered by trigger 2)
    7  Long pulling sections     gap > spacing * 2 between consecutive triggers
    8  Road crossings            injected at every place two road geometries cross

    Candidates are deduplicated at ``TOPOLOGY_SNAP_TOLERANCE * 3`` metres.
    """
    SNAP_DEDUP = TOPOLOGY_SNAP_TOLERANCE * 3
    struct_type = config.ug_infrastructure_type   # "handhole" | "manhole"
    spacing     = config.ug_spacing_m

    candidates: List[QgsPointXY] = []

    # ---- Trigger 2 + 6: intersections / branching (degree >= 3) ----
    if topo is not None:
        for nid, ndata in topo._nodes.items():
            if topo._node_degree(nid) >= 3:
                candidates.append(ndata['point'])

        # ---- Trigger 3: > 45° bends at degree-2 nodes ----
        for nid, ndata in topo._nodes.items():
            if topo._node_degree(nid) != 2:
                continue
            edge_ids = list(ndata['edges'])
            if len(edge_ids) < 2:
                continue
            e1 = topo._edges.get(edge_ids[0], {})
            e2 = topo._edges.get(edge_ids[1], {})
            b1 = e1.get('bearing', 0.0)
            b2 = e2.get('bearing', 0.0)
            diff = abs(b1 - b2)
            if diff > 180:
                diff = 360 - diff
            if diff > CORRIDOR_ANGLE_THRESHOLD:
                candidates.append(ndata['point'])

    # ---- Trigger 4: at each FDT ----
    for fdt in fdts:
        pt = fdt.snapped_geometry if fdt.snapped_geometry else fdt.geometry
        if pt:
            candidates.append(pt)

    # ---- Trigger 5: at each closure ----
    for closure in closures:
        pt = closure.snapped_geometry if closure.snapped_geometry else closure.geometry
        if pt:
            candidates.append(pt)

    # ---- Trigger 1: regular spacing along every road ----
    for road in roads.values():
        geom = road.geometry
        if not geom or geom.isEmpty():
            continue
        length = geom.length()
        pos = spacing
        while pos < length:
            pt_geom = geom.interpolate(pos)
            if pt_geom and not pt_geom.isEmpty():
                candidates.append(pt_geom.asPoint())
            pos += spacing

    # ---- Deduplicate by snap tolerance ----
    structures: List[SupportStructure] = []
    accepted_pts: List[QgsPointXY] = []

    for pt in candidates:
        too_close = any(
            dist_calc.distance_points(pt, existing) < SNAP_DEDUP
            for existing in accepted_pts
        )
        if too_close:
            continue

        sid = len(structures)
        if struct_type == "manhole":
            s = ManholeStructure(
                id=sid, geometry=pt, status="proposed",
                mh_id=f"MH-{sid + 1:04d}",
            )
        else:
            s = HandholeStructure(
                id=sid, geometry=pt, status="proposed",
                hh_id=f"HH-{sid + 1:04d}",
            )
        structures.append(s)
        accepted_pts.append(pt)

    logger.log(
        f"  place_ug_structures: {len(candidates)} candidates → "
        f"{len(structures)} deduplicated {struct_type}s placed"
    )
    return structures


def route_duct_segments(
    structures: List[SupportStructure],
    roads: Dict[int, 'RoadSegment'],
    cable_router: 'CableRouter',
    config: 'FTTXConfig',
    logger: 'PerformanceLogger',
) -> List[DuctRoute]:
    """Connect consecutive SupportStructures with duct route segments.

    Structures are sorted by their nearest road and chainage so the routing
    order follows the physical road sequence rather than arbitrary insertion
    order.  Each consecutive pair becomes one ``DuctRoute``.

    Strict Mode raises ``FTTXError`` on any empty path.
    Assisted Mode logs and skips the gap.
    """
    if len(structures) < 2:
        logger.log("route_duct_segments: fewer than 2 structures — no segments generated.")
        return []

    # Assign a sort key: (road proximity, position along that road)
    def _sort_key(s: SupportStructure):
        best_road = None
        best_dist = float('inf')
        best_pos  = 0.0
        pt_geom   = QgsGeometry.fromPointXY(s.geometry)
        for road in roads.values():
            if not road.geometry or road.geometry.isEmpty():
                continue
            dist = road.geometry.distance(pt_geom)
            if dist < best_dist:
                best_dist = dist
                best_road = road.road_id if hasattr(road, 'road_id') else 0
                best_pos  = road.geometry.lineLocatePoint(pt_geom)
        return (best_road or 0, best_pos)

    sorted_s = sorted(structures, key=_sort_key)

    routes: List[DuctRoute] = []
    rid = 0
    for i in range(len(sorted_s) - 1):
        a = sorted_s[i]
        b = sorted_s[i + 1]

        geom, length = cable_router.find_shortest_path_points(a.geometry, b.geometry)

        if geom is None or geom.isEmpty():
            msg = (
                f"route_duct_segments: no road path between "
                f"structure {a.id} ({a.structure_type}) → "
                f"structure {b.id} ({b.structure_type})."
            )
            if config.ug_routing_mode == "strict":
                raise FTTXError(
                    f"[STRICT MODE] {msg} "
                    f"Add existing infrastructure or switch to Assisted Mode."
                )
            logger.log(f"WARNING [ROUTING_FAILURE]: {msg} Skipping segment.")
            continue

        rid += 1
        routes.append(DuctRoute(
            start_structure    = a,
            end_structure      = b,
            geometry           = geom,
            length             = length,
            duct_type          = config.ug_duct_type,
            duct_diameter      = config.ug_duct_diameter_mm,
            duct_ways          = config.ug_duct_ways,
            installation_method= config.ug_installation_method,
            spare_pct          = config.ug_spare_capacity_pct,
            status             = "proposed",
            route_id           = _project_tag("DR", f"{rid:04d}"),
        ))

    logger.log(
        f"route_duct_segments: generated {len(routes)} duct route segments "
        f"({sum(r.length for r in routes):.1f} m total)"
    )
    return routes


def route_duct_segments_with_ledger(
    structures: List[SupportStructure],
    roads: Dict[int, 'RoadSegment'],
    cable_router: 'CableRouter',
    config: 'FTTXConfig',
    ledger: Optional['DuctOccupancyLedger'],
    logger: 'PerformanceLogger',
) -> List[DuctRoute]:
    """route_duct_segments + occupancy-aware routing.

    Extends the base ``route_duct_segments`` with two ledger operations:

    1. After generating routes, calls ``ledger.apply_to_routes()`` to
       populate ``occupied`` and ``duct_ways`` from persisted data.

    2. For segments that are at capacity (``spare_ways() == 0``), attempts
       an alternate path via the cable router's secondary graph.  If no
       alternate exists and ``config.ug_routing_mode == 'strict'``, raises
       ``FTTXError``.  In Assisted Mode the segment is flagged
       ``status = "capacity_exceeded"`` and logged.

    If ``ledger`` is None (occupancy disabled or open failed), falls back
    to plain ``route_duct_segments`` with no occupancy logic.
    """
    # Base routing
    routes = route_duct_segments(structures, roads, cable_router, config, logger)

    if not routes or ledger is None or not ledger.is_open():
        return routes

    # Apply persisted occupancy
    ledger.apply_to_routes(routes)

    # Check capacity and flag / fail over-capacity segments
    at_capacity: List[DuctRoute] = []
    for route in routes:
        if route.spare_ways() == 0 and route.occupied > 0:
            at_capacity.append(route)

    if at_capacity:
        logger.log(
            f"OccupancyLedger: {len(at_capacity)} segment(s) at or over capacity:"
        )
        for r in at_capacity:
            msg = (
                f"  route {r.route_id}: {r.occupied}/{r.duct_ways} ways used "
                f"({r.duct_type} {r.duct_diameter}mm)"
            )
            logger.log(msg)
            if config.ug_routing_mode == "strict":
                raise FTTXError(
                    f"[STRICT MODE] Duct at capacity: {msg}. "
                    f"Install additional duct or switch to Assisted Mode."
                )
            # Assisted mode: mark segment for attention but continue
            r.status = "capacity_exceeded"

    # Save updated routes back to ledger
    ledger.save_routes(routes)

    # Log summary
    summary = ledger.summary()
    logger.log(
        f"OccupancyLedger summary: {summary.get('routes', 0)} routes, "
        f"{summary.get('occupied_ways', 0)}/{summary.get('total_ways', 0)} ways used, "
        f"{summary.get('spare_ways', 0)} spare"
    )
    return routes


def _build_underground_boq(
    boq_layer: 'QgsVectorLayer',
    structures: List[SupportStructure],
    duct_routes: List[DuctRoute],
    config: 'FTTXConfig',
    logger: 'PerformanceLogger',
) -> None:
    """Append underground BOQ rows to the shared BOQ layer.

    Quantities derived strictly from generated design — never hard-coded.

    Item                          Derivation
    -------------------------     ------------------------------------------
    HDPE/uPVC duct (m)            sum of all duct_route.length
    Proposed handholes (no.)      count structures where type == 'handhole'
    Proposed manholes (no.)       count structures where type == 'manhole'
    Pull rope (m)                 total duct length × 1.05 (5 % waste factor)
    Warning tape (m)              total duct length
    Marker tape (no.)             total duct length ÷ 50 m intervals
    Duct couplers (no.)           number of duct route segments
    End caps (no.)                number of structures × duct_ways
    """
    total_duct_m   = sum(r.length for r in duct_routes)
    n_handholes    = sum(1 for s in structures if s.structure_type == "handhole")
    n_manholes     = sum(1 for s in structures if s.structure_type == "manhole")
    n_segments     = len(duct_routes)
    n_structures   = len(structures)

    items = [
        (f"{config.ug_duct_type} Duct ({config.ug_duct_diameter_mm}mm)",
            round(total_duct_m, 2),    "m"),
        ("Proposed Handholes",      n_handholes,                       "no."),
        ("Proposed Manholes",       n_manholes,                        "no."),
        ("Pull Rope",               round(total_duct_m * 1.05, 2),    "m"),
        ("Warning Tape",            round(total_duct_m, 2),            "m"),
        ("Marker Tape",             int(total_duct_m / 50) + 1,       "no."),
        ("Duct Couplers",           n_segments,                        "no."),
        ("End Caps",                n_structures * config.ug_duct_ways,"no."),
    ]

    boq_layer.startEditing()
    for item_name, qty, unit in items:
        feat = QgsFeature(boq_layer.fields())
        # Write into the 'street_name' field as item name, level_type = 'UNDERGROUND'
        # so the BOQ layer schema stays unchanged (no new columns needed in Phase 3)
        try:
            attrs = ["UNDERGROUND", item_name, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, 0, 0.0, 0, 0.0]
            feat.setAttributes(attrs)
            feat.setAttribute("total_standard_length", float(qty) if unit == "m" else 0.0)
            feat.setAttribute("street_name", f"{item_name}: {qty} {unit}")
        except Exception:
            pass
        boq_layer.addFeature(feat)
    boq_layer.commitChanges()

    logger.log(
        f"_build_underground_boq: {len(items)} items — "
        f"{total_duct_m:.1f} m duct, "
        f"{n_handholes} HH, {n_manholes} MH"
    )
