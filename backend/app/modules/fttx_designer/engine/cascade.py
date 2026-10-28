"""Verbatim port of the FAT cascading stage from
``FTTx Designer — dual PON integrated.py``: the device-tag helpers
(``_legacy_alpha_code``, ``_project_tag``, ``_normalize_pole_token``,
``_classify_pole_type``), ``insert_intermediate_fats``, ``create_fat_cascade``
(PCC mode), ``create_legacy_cascade``/``_override_legacy_connections``
(Legacy mode), and ``_walk_cascade_chain``.

No logic changes from the source script — only the QGIS types (now from
``engine.geometry_compat``) and cross-module imports.

Note: ``PROJECT_ABBREVIATION`` is one of the 8 tunables the pipeline
overrides per-run (see runtime_config.py's docstring) — ``_project_tag``
reads it through ``runtime_config.PROJECT_ABBREVIATION``, never a bare
import, so a run-configured project abbreviation actually reaches every
tag generated here.

Deliberately excluded from this module (unlike the plan document's literal
module boundary, which groups "legacy FDT-to-FAT routing" here too):
``route_legacy_fdt_to_fats_by_road``. It has a hard dependency on
``CableRouter``/``_enforce_exact_cable_endpoints`` (cable_routing.py, ported
in a later sub-phase) and is only ever invoked once the CableRouter exists
in the pipeline's own dependency order — keeping it here would create a
forward reference from cascade.py to cable_routing.py for no benefit, so it
is ported alongside CableRouter instead.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Dict, List, Tuple

from . import runtime_config as rc
from .config import MAX_FAT_TO_FAT_DISTANCE
from .domain import FAT, RoadSegment, SupportStructure
from .geometry_compat import QgsGeometry
from .perf_logger import PerformanceLogger
from .spatial_utils import DistanceCalculator


def insert_intermediate_fats(start_fat: FAT, end_fat: FAT,
                            road_geom: QgsGeometry,
                            dist_calc: DistanceCalculator,
                            base_counter: int) -> List[FAT]:
    """Insert intermediate FATs when distance exceeds maximum"""
    distance = dist_calc.distance_along_road(road_geom, start_fat.geometry, end_fat.geometry)
    num_intermediate = math.ceil(distance / MAX_FAT_TO_FAT_DISTANCE) - 1

    if num_intermediate <= 0:
        return []

    # Calculate positions along road
    start_pos = road_geom.lineLocatePoint(QgsGeometry.fromPointXY(start_fat.geometry))
    end_pos = road_geom.lineLocatePoint(QgsGeometry.fromPointXY(end_fat.geometry))

    intermediate_fats = []
    for i in range(1, num_intermediate + 1):
        # Interpolate position
        t = i / (num_intermediate + 1)
        pos = start_pos + t * (end_pos - start_pos)

        # Get point at position. `pos` is already an absolute chainage
        # (start_pos/end_pos came straight from lineLocatePoint(), which is
        # not a 0-1 fraction) — interpolate() takes that directly.
        point_geom = road_geom.interpolate(pos)
        if point_geom:
            point = point_geom.asPoint()

            # Create intermediate FAT — a pure cable-relay device, never a
            # customer-serving FAT (spec: FAT-MIN-CAPACITY corrective fix).
            # See FAT.is_relay for why this must never enter the
            # customer-capacity rule or the FAT rebalancer's dissolve logic.
            fat = FAT(
                name=f"FAT_{base_counter + i:06d}_INT",
                geometry=point,
                road_id=start_fat.road_id,
                total_customers=0,  # No customers
                cascade_order=int(pos * 1000),
                from_device="",
                to_device="",
                wing="",
                is_relay=True,
            )

            # Set connections
            if i == 1:
                fat.from_device = start_fat.name
            else:
                fat.from_device = intermediate_fats[-1].name

            if i == num_intermediate:
                fat.to_device = end_fat.name
            else:
                fat.to_device = ""  # Will be set by next FAT

            intermediate_fats.append(fat)

    # Update connections
    for i in range(len(intermediate_fats)):
        if i < len(intermediate_fats) - 1:
            intermediate_fats[i].to_device = intermediate_fats[i + 1].name

    return intermediate_fats


def create_fat_cascade(fats: List[FAT],
                       roads: Dict[int, RoadSegment],
                       dist_calc: DistanceCalculator,
                       logger: PerformanceLogger) -> List[FAT]:
    """Create linear cascade of FATs along roads"""
    logger.start_module("FAT Cascading")

    # Group FATs by road
    fats_by_road = defaultdict(list)
    for fat in fats:
        fats_by_road[fat.road_id].append(fat)

    cascaded_fats = []

    for road_id, road_fats in fats_by_road.items():
        # Sort by cascade order (position along road)
        road_fats.sort(key=lambda f: f.cascade_order)

        # Determine road direction
        road_geom = roads[road_id].geometry

        # Create cascade chain.
        # from_device / to_device are intentionally left as "" for the first
        # FAT on each road — create_fdt_wing_cascades will wire the full
        # FDT-outward chain once wing assignment and naming are complete.
        # Setting from_device="FDT" here would use a literal string that
        # never matches fdt.name (e.g. "FDT-01"), breaking the head-detection
        # in route_fdt_to_fats.
        for i, fat in enumerate(road_fats):
            fat.from_device = road_fats[i - 1].name if i > 0 else ""
            fat.to_device   = road_fats[i + 1].name if i < len(road_fats) - 1 else ""

            # Check distance between consecutive FATs
            if i > 0:
                prev_fat = road_fats[i - 1]
                distance = dist_calc.distance_along_road(road_geom, prev_fat.geometry, fat.geometry)

                if distance > MAX_FAT_TO_FAT_DISTANCE:
                    # Need to insert intermediate FATs
                    logger.log(
                        f"WARNING [FAT_DISTANCE_EXCEEDED]: {prev_fat.name}-{fat.name} "
                        f"distance {distance:.2f}m exceeds maximum {MAX_FAT_TO_FAT_DISTANCE}m"
                    )

                    # Insert intermediate FATs
                    intermediate_fats = insert_intermediate_fats(
                        prev_fat, fat, road_geom, dist_calc, len(cascaded_fats)
                    )
                    cascaded_fats.extend(intermediate_fats)

        cascaded_fats.extend(road_fats)

    logger.end_module("FAT Cascading")
    logger.log(f"Cascaded {len(cascaded_fats)} FATs")

    return cascaded_fats


# =============================================================================
# V5: LEGACY CASCADE HELPERS
# =============================================================================

def _legacy_alpha_code(n: int) -> str:
    """Convert 0-indexed integer to Excel-style alphabetic code.

    0→A, 1→B, …, 25→Z, 26→AA, 27→AB, …, 51→AZ, 52→BA, …
    """
    result = ""
    n += 1  # convert to 1-indexed
    while n > 0:
        n, r = divmod(n - 1, 26)
        result = chr(65 + r) + result
    return result


def _project_tag(*parts: str) -> str:
    """Join tag segments with '-', inserting PROJECT_ABBREVIATION as the
    second segment when one is configured for this run.

    _project_tag("FDT", "01") -> "FDT-01", or "FDT-KKO-01" when
    PROJECT_ABBREVIATION == "KKO". Single choke point for every device-tag
    format in the pipeline so all tag sites stay in sync.
    """
    segs = [parts[0]]
    if rc.PROJECT_ABBREVIATION:
        segs.append(rc.PROJECT_ABBREVIATION)
    segs.extend(parts[1:])
    return "-".join(segs)


def _normalize_pole_token(s: str) -> str:
    """Lowercase and strip everything but letters/digits, so "N/P",
    "nepa Pole", and "NEPA_POLE" all normalize to the same lookup key."""
    return re.sub(r"[^a-z0-9]", "", (s or "").strip().lower())


# Raw pole-label variants seen in the field, mapped to a canonical type
# code. Keys are pre-normalized via _normalize_pole_token (lowercase,
# letters/digits only) so spacing/punctuation/case differences collapse to
# the same entry. Extend this dict if new spelling variants turn up.
_POLE_TYPE_KEYWORDS: Dict[str, str] = {
    # NEPA / high-tension pole -> "NP"
    "np": "NP", "nepapole": "NP", "ht": "NP", "hightension": "NP",
    # Proposed pole -> "PP"
    "pp": "PP", "proposepole": "PP", "nppp": "PP",
    # Nitel pole -> "Nitel"
    "nitel": "Nitel",
    # Third-party pole -> "Third_party_pole"
    "3rdparty": "Third_party_pole", "3pp": "Third_party_pole", "3rdpp": "Third_party_pole",
}


def _classify_pole_type(pole: 'SupportStructure') -> Tuple[str, bool]:
    """Classify a pole's raw label into a canonical type code for tagging.

    Returns (type_code, matched). Software-proposed poles (status ==
    "proposed", created by propose_aerial_poles() with no raw name) are
    always "PP" regardless of text. Everything else is classified from
    raw_name via _POLE_TYPE_KEYWORDS; an unrecognized label falls back to
    the generic "POLE" bucket with matched=False so the caller can log it.
    """
    if pole.status == "proposed":
        return "PP", True
    code = _POLE_TYPE_KEYWORDS.get(_normalize_pole_token(pole.raw_name or pole.name))
    return (code, True) if code else ("POLE", False)


def create_legacy_cascade(fats: List['FAT'],
                          roads: Dict[int, 'RoadSegment'],
                          dist_calc: 'DistanceCalculator',
                          logger: 'PerformanceLogger') -> List['FAT']:
    """Legacy mode: every FAT connects directly to its parent FDT (no FAT-to-FAT chains).

    Sets from_device to a placeholder "FDT" (overridden to the real FDT name
    after generate_fdts / assign_wings_per_fdt run).  cascade_order is
    preserved for naming; no intermediate FATs are inserted.
    """
    logger.start_module("Legacy FAT Cascade")
    for fat in fats:
        fat.from_device = "FDT"   # placeholder; overridden later
        fat.to_device   = ""
    logger.log(f"Legacy cascade: {len(fats)} FATs set to direct-FDT connections")
    logger.end_module("Legacy FAT Cascade")
    return fats


def _override_legacy_connections(fdts: List['FDT'], logger: 'PerformanceLogger') -> None:
    """Post-wing-assignment fix: reset every FAT to a direct FDT connection.

    Called only in LEGACY mode after assign_wings_per_fdt has run (and
    potentially set from_device to another FAT in wing-chain logic).
    Assigns 1-indexed fdt_port for traceability.
    """
    logger.log("Legacy: overriding FAT connections to direct-FDT links")
    for fdt in fdts:
        for i, fat in enumerate(fdt.fats, start=1):
            fat.from_device = fdt.name
            fat.to_device   = ""
            fat.fdt_port    = i   # 1-indexed port number


def _walk_cascade_chain(fdt: 'FDT', wing: str, fat_by_name: Dict) -> List['FAT']:
    """Walk from_device chain for one PCC wing, returning FATs in cascade order."""
    head = next(
        (f for f in fdt.fats if f.wing == wing and f.from_device == fdt.name),
        None
    )
    if not head:
        return []
    chain = [head]
    while chain[-1].to_device:
        nxt = fat_by_name.get(chain[-1].to_device)
        if not nxt or nxt in chain:
            break
        chain.append(nxt)
    return chain
