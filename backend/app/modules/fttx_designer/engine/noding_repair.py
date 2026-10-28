"""Road graph noding diagnosis and repair toolkit.

When B2B cables show implausible detours (routed distance >> straight-line),
it's almost always a cut in the routing graph — road segments that don't
properly connect at intersections. This module identifies those defects and
provides repair guidance.

The two defect classes that cause detours:

  T_UNNODED: A line endpoint lies on another line's interior with NO vertex
  there. Only line noding (unaryUnion) closes this. These are the primary
  cause of block-perimeter detours.

  NEAR_MISS: A line endpoint sits within gap tolerance of another line, but
  that line already has a vertex there. These are usually healable by
  MASTER_GRAPH_TOPOLOGY_TOLERANCE but sometimes need manual snapping.

Usage:
    from .noding_repair import diagnose_b2b_detour_causes, generate_noding_repair_layer

    # Get detailed diagnosis
    diagnosis = diagnose_b2b_detour_causes(
        b2b_suspects,      # From audit_b2b_detours()
        road_layer,
        fats,
        fdts,
        dist_calc,
        logger
    )

    # Generate a repair layer to load in QGIS
    repair_layer = generate_noding_repair_layer(
        road_layer,
        dist_calc,
        logger
    )
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from .geometry_compat import (
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsSpatialIndex,
    QgsVectorLayer,
)
from .spatial_utils import DistanceCalculator
from .perf_logger import PerformanceLogger
from .config import NODING_AUDIT_GAP_TOL, MASTER_GRAPH_TOPOLOGY_TOLERANCE


def diagnose_b2b_detour_causes(
    b2b_suspects: List[Dict],
    road_layer: QgsVectorLayer,
    fats: List[Any],
    fdts: List[Any],
    dist_calc: DistanceCalculator,
    logger: PerformanceLogger,
) -> Dict[str, Any]:
    """Cross-reference B2B detours with road-graph noding defects.

    For each implausible B2B cable, tries to identify which road junction
    defect is forcing the detour. Returns a diagnosis dict with:
      - suspects_near_noding_defects: hops whose endpoints are near cuts
      - defects_affecting_routes: which noding issues impact B2B cables
      - repair_priority: ordered list of (defect, affected_hops_count)
    """
    logger.start_module("B2B Detour Diagnosis")

    # Build device lookup
    device_coords: Dict[str, Tuple[float, float]] = {}
    for fat in fats:
        if getattr(fat, 'name', None) and getattr(fat, 'geometry', None):
            pt = fat.geometry
            device_coords[fat.name] = (round(pt.x(), 6), round(pt.y(), 6))
    for fdt in fdts:
        if getattr(fdt, 'name', None) and getattr(fdt, 'geometry', None):
            pt = fdt.geometry
            device_coords[fdt.name] = (round(pt.x(), 6), round(pt.y(), 6))

    # Audit the road layer for noding defects
    defects = _audit_noding_defects(road_layer, dist_calc, logger)

    # Map suspects to nearby defects
    suspect_matches: Dict[str, List[Dict]] = {}
    for suspect in b2b_suspects:
        name = suspect.get('name', '')
        routed = suspect.get('routed', 0.0)
        suspect_pt = QgsPointXY(suspect.get('x', 0.0), suspect.get('y', 0.0))

        # Find all defects within 500m of the cable start point
        # (rough perimeter of the detour zone)
        nearby = []
        for defect in defects:
            defect_pt = QgsPointXY(defect['x'], defect['y'])
            d = dist_calc.distance_points(suspect_pt, defect_pt)
            if d < min(routed * 0.5, 500.0):  # Heuristic: within half the routed distance
                nearby.append((d, defect))
        if nearby:
            nearby.sort(key=lambda x: x[0])
            suspect_matches[name] = [d[1] for d in nearby[:3]]

    # Aggregate repair priorities
    defect_impact_count: Dict[Tuple[float, float], int] = defaultdict(int)
    for matches in suspect_matches.values():
        for defect in matches:
            key = (defect['x'], defect['y'])
            defect_impact_count[key] += 1

    repair_priority = sorted(
        ((d, count) for (coords, count) in defect_impact_count.items()
         for d in defects if (d['x'], d['y']) == coords),
        key=lambda x: -x[1]
    )

    diagnosis = {
        'total_suspects': len(b2b_suspects),
        'suspects_near_defects': len(suspect_matches),
        'total_defects': len(defects),
        'defect_breakdown': {
            'T_UNNODED': sum(1 for d in defects if d['kind'] == 'T_UNNODED'),
            'NEAR_MISS': sum(1 for d in defects if d['kind'] == 'NEAR_MISS'),
        },
        'suspect_matches': suspect_matches,
        'repair_priority': repair_priority[:20],  # Top 20 defects by impact
    }

    # Log summary and repair plan
    logger.log(
        f"[B2B-DETOUR-DIAGNOSIS] {diagnosis['suspects_near_defects']}/{diagnosis['total_suspects']} "
        f"suspects traced to noding defects"
    )
    logger.log(
        f"[B2B-DETOUR-DIAGNOSIS] Road graph has {diagnosis['defect_breakdown']['T_UNNODED']} T_UNNODED "
        f"+ {diagnosis['defect_breakdown']['NEAR_MISS']} NEAR_MISS defects"
    )
    if repair_priority:
        logger.log("[B2B-DETOUR-DIAGNOSIS] Top repair priorities:")
        for defect, impact_count in repair_priority[:5]:
            logger.log(
                f"    {defect['kind']} at POINT({defect['x']:.2f} {defect['y']:.2f}) "
                f"(gap={defect['gap_m']}m) affects {impact_count} B2B cable(s)"
            )

    logger.end_module("B2B Detour Diagnosis")
    return diagnosis


def _audit_noding_defects(
    road_layer: QgsVectorLayer,
    dist_calc: DistanceCalculator,
    logger: PerformanceLogger,
    gap_tol: float = NODING_AUDIT_GAP_TOL,
) -> List[Dict]:
    """Fast re-implementation of audit_road_layer_noding for diagnosis."""
    feats: List[Tuple[int, QgsGeometry]] = []
    for f in road_layer.getFeatures():
        g = f.geometry()
        if g and not g.isEmpty():
            feats.append((f.id(), g))

    if not feats:
        return []

    endpoints: List[Tuple[int, QgsPointXY]] = []
    exact: Dict[Tuple[float, float], set] = defaultdict(set)

    for fid, g in feats:
        parts = g.asMultiPolyline() if g.isMultipart() else [g.asPolyline()]
        for part in parts:
            if not part or len(part) < 2:
                continue
            for p in (part[0], part[-1]):
                endpoints.append((fid, p))
                exact[(round(p.x(), 6), round(p.y(), 6))].add(fid)

    idx = QgsSpatialIndex()
    geoms: Dict[int, QgsGeometry] = {}
    for fid, g in feats:
        geoms[fid] = g
        ft = QgsFeature(fid)
        ft.setGeometry(g)
        idx.addFeature(ft)

    defects: List[Dict] = []
    for fid, p in endpoints:
        key = (round(p.x(), 6), round(p.y(), 6))
        if len(exact.get(key, ())) > 1:
            continue
        p_geom = QgsGeometry.fromPointXY(p)
        try:
            neighbours = idx.nearestNeighbor(p, 6)
        except Exception:
            continue
        for other in neighbours:
            if other == fid:
                continue
            og = geoms.get(other)
            if og is None:
                continue
            try:
                d = og.distance(p_geom)
            except Exception:
                continue
            if d > gap_tol:
                continue
            try:
                nearest_v = og.closestVertex(p)[0]
            except Exception:
                continue
            v_gap = dist_calc.distance_points(p, nearest_v)
            kind = 'NEAR_MISS' if v_gap <= gap_tol else 'T_UNNODED'
            defects.append({
                'kind': kind,
                'fid': fid,
                'other_fid': other,
                'gap_m': round(d, 3),
                'vertex_gap': round(v_gap, 3),
                'x': p.x(),
                'y': p.y(),
            })
            break

    return defects


def generate_noding_repair_layer(
    road_layer: QgsVectorLayer,
    dist_calc: DistanceCalculator,
    logger: PerformanceLogger,
    output_path: Optional[str] = None,
) -> Optional[QgsVectorLayer]:
    """Create a point layer marking every noding defect for QGIS inspection.

    Returns a QgsVectorLayer with points at each defect, attributed with
    defect type, gap measurements, and WKT coordinates. Can be saved as a
    shapefile or GeoPackage for field review.

    If output_path is provided, writes to that file; otherwise returns an
    in-memory layer.
    """
    defects = _audit_noding_defects(road_layer, dist_calc, logger)

    if not defects:
        logger.log("No noding defects found; repair layer is empty")
        return None

    records = []
    for defect in defects:
        records.append({
            'geometry': QgsGeometry.fromPointXY(
                QgsPointXY(defect['x'], defect['y'])
            ),
            'defect_type': defect['kind'],
            'gap_m': defect['gap_m'],
            'vertex_gap_m': defect['vertex_gap'],
            'fid': defect['fid'],
            'other_fid': defect['other_fid'],
            'wkt': f"POINT({defect['x']:.2f} {defect['y']:.2f})",
        })

    repair_layer = QgsVectorLayer.from_records(
        records,
        crs=road_layer.crs(),
        layer_id="noding_defects",
    )

    logger.log(
        f"Generated noding repair layer: {len(defects)} defect(s) "
        f"({sum(1 for d in defects if d['kind'] == 'T_UNNODED')} T_UNNODED, "
        f"{sum(1 for d in defects if d['kind'] == 'NEAR_MISS')} NEAR_MISS)"
    )

    return repair_layer


def generate_repair_instructions(
    diagnosis: Dict[str, Any],
    logger: PerformanceLogger,
) -> str:
    """Generate human-readable QGIS repair instructions."""
    instructions = (
        "\n=== QGIS Road Graph Noding Repair Instructions ===\n\n"
        "1. OPEN THE REPAIR LAYER:\n"
        "   - Load the noding_defects layer in QGIS\n"
        "   - Enable Labels to show defect types and WKT coordinates\n\n"
        "2. PRIORITIZE REPAIRS (see coordinates below):\n"
    )

    for defect, impact_count in diagnosis.get('repair_priority', [])[:10]:
        instructions += (
            f"   [{defect['kind']}] POINT({defect['x']:.2f} {defect['y']:.2f}) "
            f"gap={defect['gap_m']}m affects {impact_count} cable(s)\n"
        )

    instructions += (
        "\n3. REPAIR STRATEGIES:\n"
        "   T_UNNODED (most critical):\n"
        "      a) Noding via Vector menu > Geometry > Node Lines\n"
        "      b) Or manually add vertices at the reported points\n\n"
        "   NEAR_MISS:\n"
        "      a) Snap line endpoints: Vector > Geometry > Snap Geometries\n"
        "      b) Or manually extend/trim lines to exact junction points\n\n"
        "4. VALIDATE:\n"
        "   - After each repair, re-run the design\n"
        "   - B2B detour ratios should drop to <2.5x\n"
        "   - Check the [NODING-AUDIT] log for remaining defects\n"
    )

    return instructions
