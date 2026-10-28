"""Verbatim port of the pure-algorithm Drainage-deployment functions from
``FTTx Designer — dual PON integrated.py``: ``place_drainage_splitters``,
``_build_drainage_boq``.

No logic changes from the source script — only the QGIS types and
cross-module imports.

Deliberately excluded from this module (same reasoning as
``underground.py``'s docstring): ``_load_channel_layer`` (a
``QgsProject.instance().mapLayersByName(...)`` lookup — desktop-GUI
layer-selection, no web equivalent yet) and the full ``DrainageStrategy``
class (whose ``load_structures``/``create_extra_output_layers`` are built
on that lookup plus the still-deferred
``_create_drainage_output_layers``/``_populate_drainage_layers``).
``place_drainage_splitters`` itself only needs an already-resolved
``channel_layer`` object — agnostic to how the caller obtained it — so it
ports cleanly now.
"""

from __future__ import annotations

from typing import Dict, List

from ..config import TOPOLOGY_SNAP_TOLERANCE, FTTXConfig
from ..domain import DrainageSplitterStructure, DuctRoute, SupportStructure
from ..geometry_compat import QgsFeature, QgsPointXY, QgsVectorLayer
from ..perf_logger import PerformanceLogger
from ..spatial_utils import DistanceCalculator


def place_drainage_splitters(
    channel_layer: 'QgsVectorLayer',
    config: 'FTTXConfig',
    dist_calc: 'DistanceCalculator',
    logger: 'PerformanceLogger',
) -> List[DrainageSplitterStructure]:
    """Place DrainageSplitter structures along drainage channel geometry.

    Placement rules (mirror underground triggers adapted for channels):
      1. Regular spacing (config.dr_spacing_m) along each channel feature
      2. At channel junctions — where features share an endpoint within
         TOPOLOGY_SNAP_TOLERANCE (same logic as road intersections)
      3. At channel endpoints (start / end of each feature)

    Candidates are deduplicated at TOPOLOGY_SNAP_TOLERANCE × 3.
    """
    SNAP_DEDUP = TOPOLOGY_SNAP_TOLERANCE * 3
    spacing    = config.dr_spacing_m

    candidates: List[QgsPointXY] = []

    # ---- Trigger 1: regular spacing along each channel segment ----
    for feat in channel_layer.getFeatures():
        geom = feat.geometry()
        if not geom or geom.isEmpty():
            continue
        length = geom.length()
        # Start endpoint
        v = geom.asPolyline() if not geom.isMultipart() else geom.asMultiPolyline()[0]
        if v:
            candidates.append(v[0])
            candidates.append(v[-1])
        # Regular spacing
        pos = spacing
        while pos < length:
            pt_geom = geom.interpolate(pos)
            if pt_geom and not pt_geom.isEmpty():
                candidates.append(pt_geom.asPoint())
            pos += spacing

    # ---- Trigger 2: channel junctions — endpoints within snap tolerance ----
    # Build list of all endpoints, then group within SNAP_DEDUP
    endpoint_map: Dict[str, List[QgsPointXY]] = {}
    for feat in channel_layer.getFeatures():
        geom = feat.geometry()
        if not geom or geom.isEmpty():
            continue
        v = geom.asPolyline() if not geom.isMultipart() else geom.asMultiPolyline()[0]
        if not v:
            continue
        for pt in [v[0], v[-1]]:
            key = f"{round(pt.x(), 1)},{round(pt.y(), 1)}"
            endpoint_map.setdefault(key, []).append(pt)

    # Any bucket with > 1 point is a junction
    for pts_at_junction in endpoint_map.values():
        if len(pts_at_junction) > 1:
            # Use centroid of coincident points
            cx = sum(p.x() for p in pts_at_junction) / len(pts_at_junction)
            cy = sum(p.y() for p in pts_at_junction) / len(pts_at_junction)
            candidates.append(QgsPointXY(cx, cy))

    # ---- Deduplicate ----
    structures: List[DrainageSplitterStructure] = []
    accepted_pts: List[QgsPointXY] = []

    for pt in candidates:
        too_close = any(
            dist_calc.distance_points(pt, ep) < SNAP_DEDUP
            for ep in accepted_pts
        )
        if too_close:
            continue
        sid = len(structures)
        structures.append(DrainageSplitterStructure(
            id=sid, geometry=pt, status="proposed"
        ))
        accepted_pts.append(pt)

    logger.log(
        f"place_drainage_splitters: {len(candidates)} candidates → "
        f"{len(structures)} deduplicated splitters placed"
    )
    return structures


def _build_drainage_boq(
    boq_layer: 'QgsVectorLayer',
    structures: List[SupportStructure],
    duct_routes: List[DuctRoute],
    config: 'FTTXConfig',
    logger: 'PerformanceLogger',
) -> None:
    """Append drainage BOQ rows to the shared BOQ layer."""
    total_duct_m = sum(r.length for r in duct_routes)
    n_splitters  = len(structures)
    n_segments   = len(duct_routes)

    items = [
        (f"{config.dr_duct_type} Duct ({config.dr_duct_diameter_mm}mm)",
            round(total_duct_m, 2), "m"),
        ("Drainage Splitters",   n_splitters,                      "no."),
        ("Pull Rope",            round(total_duct_m * 1.05, 2),    "m"),
        ("Warning Tape",         round(total_duct_m, 2),            "m"),
        ("Duct Couplers",        n_segments,                        "no."),
        ("End Caps",             n_splitters * config.dr_duct_ways, "no."),
    ]

    boq_layer.startEditing()
    for item_name, qty, unit in items:
        feat = QgsFeature(boq_layer.fields())
        try:
            feat.setAttributes(
                ["DRAINAGE", f"{item_name}: {qty} {unit}",
                 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, 0, 0.0, 0, 0.0]
            )
            feat.setAttribute("total_standard_length",
                              float(qty) if unit == "m" else 0.0)
        except Exception:
            pass
        boq_layer.addFeature(feat)
    boq_layer.commitChanges()

    logger.log(
        f"_build_drainage_boq: {len(items)} items — "
        f"{total_duct_m:.1f} m duct, {n_splitters} splitters"
    )
