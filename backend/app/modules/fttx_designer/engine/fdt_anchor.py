"""Verbatim port of the FDT anchor/distance utilities from
``FTTx Designer — dual PON integrated.py``: ``_network_distance_is_reliable``,
``_distance_to_fdt_anchor``, ``_compute_fdt_anchor_from_fats``,
``_recompute_fdt_anchor``, ``_renumber_fdt_wings``, ``_fat_sequence_number``.

No logic changes from the source script — only the QGIS types and
cross-module imports.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from . import distance_oracle as _distance_oracle_mod
from .cascade import _project_tag
from .config import CAPACITY_PROFILES, PONArchitecture, CapacityProfile
from .distance_oracle import _network_distance
from .domain import FAT, FDT, RoadSegment
from .errors import ValidationError
from .geometry_compat import QgsGeometry, QgsPointXY
from .spatial_utils import DistanceCalculator
from .topology import RoadTopologyEngine
from .wing_geometry import _angular_split_wings


def _network_distance_is_reliable(
    pt_a: QgsPointXY,
    pt_b: QgsPointXY,
    road_a_id: Optional[int],
    road_b_id: Optional[int],
    topo: Optional['RoadTopologyEngine'],
) -> bool:
    """True only if a real road-graph path was found (not a straight-line guess).

    FAST PATH (v13-fix): same-road or nearby points are always considered
    reliable — the straight-line approximation is accurate enough at this
    scale, and skipping Dijkstra here removes O(total_fats) redundant graph
    searches from _enforce_fdt_boundaries.
    """
    # [Fix 1] A real answer from the routing graph is the strongest form of
    # reliable there is — it IS the shipped measurement, not an approximation
    # of it. Checked before the topo guard because the oracle does not need
    # RoadTopologyEngine at all.
    if _distance_oracle_mod._DISTANCE_ORACLE is not None:
        if _distance_oracle_mod._DISTANCE_ORACLE.distance(pt_a, pt_b) is not None:
            return True

    if topo is None:
        return False
    # [Fix 1] Legacy same-road / <50 m shortcuts removed here for the same
    # reason as in _network_distance: they reported "reliable" for a number
    # that was a straight-line guess.
    try:
        geom, path_dist = topo.weighted_shortest_path(
            pt_a,
            pt_b,
            start_road_id=road_a_id,
            end_road_id=road_b_id,
        )
        return geom is not None and not geom.isEmpty() and path_dist > 0
    except Exception:
        return False


def _distance_to_fdt_anchor(
    fat: FAT,
    fdt: FDT,
    dist_calc: Optional['DistanceCalculator'] = None,
    topo: Optional['RoadTopologyEngine'] = None,
    roads: Optional[Dict[int, 'RoadSegment']] = None,
) -> float:
    """Distance from a FAT to an FDT anchor, preferring road-graph distance when available."""
    fat_pt = fat.snapped_geometry or fat.geometry
    fdt_pt = fdt.snapped_geometry or fdt.geometry
    if not fat_pt or not fdt_pt:
        return float('inf')

    return _network_distance(
        fat_pt,
        fdt_pt,
        road_a_id=fat.road_id,
        road_b_id=fdt.primary_road_id,
        topo=topo,
        dist_calc=dist_calc,
    )


def _compute_fdt_anchor_from_fats(
    fats: List['FAT'],
    primary_road_obj: Optional['RoadSegment'] = None,
) -> Optional[QgsPointXY]:
    """THE single authoritative FDT anchor calculation.

    anchor = centroid(all FATs currently assigned to the FDT), snapped onto
    the primary road when one is available.

    This replaces every prior FDT-placement scheme that only looked at a
    *subset* of the FAT group (the two boundary FATs, or the min/max
    ``lineLocatePoint`` span of primary-road FATs only): those all treat
    the FDT as if it sits exactly between two extreme points, which pulls
    it off-centre the moment the FAT cluster is lopsided or includes
    borrowed FATs from a side street. The centroid uses every FAT the FDT
    actually serves, so it is stable regardless of cluster shape, and it
    does not care whether a FAT happens to be "primary" or "borrowed."

    Every function that needs to (re)position an FDT — initial placement,
    dead-end-adjacent standard placement, post-absorption/relay
    recomputation — must call this one function rather than deriving its
    own midpoint. Returns ``None`` only when there are no FAT geometries
    to anchor to at all.
    """
    valid_fats = [f for f in fats if f.geometry is not None]
    if not valid_fats:
        return None

    cx = sum(f.geometry.x() for f in valid_fats) / len(valid_fats)
    cy = sum(f.geometry.y() for f in valid_fats) / len(valid_fats)
    centroid = QgsPointXY(cx, cy)

    if (primary_road_obj is not None
            and primary_road_obj.geometry
            and not primary_road_obj.geometry.isEmpty()):
        snapped = primary_road_obj.geometry.nearestPoint(
            QgsGeometry.fromPointXY(centroid))
        if snapped and not snapped.isEmpty():
            return snapped.asPoint()

    return centroid


def _recompute_fdt_anchor(
    fdt: FDT,
    roads: Optional[Dict[int, 'RoadSegment']] = None,
) -> None:
    """Re-anchor an FDT using the single authoritative rule: centroid of
    ALL its FATs, snapped to the primary road.

    v16 fix: previously re-anchored to the midpoint of the min/max
    ``lineLocatePoint`` span of the FAT group along the primary road —
    a 1-D span midpoint, not a true centroid, and one that ignores any
    FAT not sitting on the primary road_id. That is the same class of
    defect as the old wing-split logic (a single linear projection
    standing in for the FDT's real spatial position) and could silently
    re-introduce an off-centre anchor after this function runs, even
    though _angular_split_wings() itself was already fixed.
    """
    if not fdt.fats:
        return

    primary_road_id = fdt.primary_road_id
    primary_road = roads.get(primary_road_id) if roads and primary_road_id is not None else None

    anchor = _compute_fdt_anchor_from_fats(fdt.fats, primary_road)
    if anchor is not None:
        fdt.geometry = anchor


def _renumber_fdt_wings(
    fdt: FDT,
    dist_calc: Optional['DistanceCalculator'] = None,
    profile: Optional['CapacityProfile'] = None,
) -> None:
    """Reassign wing labels, sequence numbers, and names for an FDT after ownership changes.

    Single-PON (default profile): identical to the original two-wing logic.
    Dual-PON: nested reuse of ``_angular_split_wings`` (outer cut at 8 →
    PON1/PON2, inner cut at 4 → A/B and C/D each) — see spec §9. Wing/PON
    state is always fully re-derived here, never patched.
    """
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    if len(fdt.fats) > profile.max_fat_per_fdt:
        raise ValidationError(
            f"{fdt.name}: {len(fdt.fats)} FATs exceeds cap of {profile.max_fat_per_fdt}"
        )

    # v16 fix (was: fall back to a count-based half/half split when no
    # anchor was set): a fixed FDT anchor cannot go stale here — this
    # function's own job is to keep the anchor current after an ownership
    # change, using the one authoritative rule (centroid of the FDT's
    # current FAT set). It is not allowed to silently fall back to
    # ``ordered_fats[:split]``/``[split:]`` distance-count splitting,
    # which has no concept of direction at all: two FATs on opposite
    # sides of the FDT but similar distances would land in the same half.
    # A raw (unsnapped) centroid is always computable from FAT geometries
    # alone, so the only genuine failure case is an FDT with no FAT
    # geometries at all, which fails loudly instead of producing a
    # geographically-wrong wing split.
    anchor = fdt.snapped_geometry or _compute_fdt_anchor_from_fats(fdt.fats)
    if anchor is None:
        raise ValidationError(
            f"{fdt.name}: cannot renumber wings — no FAT has a usable geometry"
        )
    fdt.geometry = anchor

    def _fat_sort_key(fat: FAT):
        if dist_calc is not None:
            return dist_calc.distance_points(anchor, fat.snapped_geometry or fat.geometry)
        p = fat.snapped_geometry or fat.geometry
        dx, dy = p.x() - anchor.x(), p.y() - anchor.y()
        return math.sqrt(dx * dx + dy * dy)

    wings_by_label: Dict[str, List[FAT]] = {}
    if profile.pon_count == 1:
        wing_a, wing_b = _angular_split_wings(
            anchor, list(fdt.fats), dist_calc, max_per_wing=profile.max_fat_per_wing,
        )
        wings_by_label = {"A": wing_a, "B": wing_b}
    else:
        # Outer cut (unmodified function, reused): whole FAT population -> two
        # PON halves, capped at 8 each. Inner cut (same function, reused again):
        # each PON half -> its two wings, capped at 4 each. See spec §9/§A.5 —
        # spatial/topological, not fill-priority.
        pon1_fats, pon2_fats = _angular_split_wings(
            anchor, list(fdt.fats), dist_calc, max_per_wing=profile.max_fat_per_wing * 2,
        )
        wing_a, wing_b = _angular_split_wings(
            anchor, pon1_fats, dist_calc, max_per_wing=profile.max_fat_per_wing,
        )
        wing_c, wing_d = _angular_split_wings(
            anchor, pon2_fats, dist_calc, max_per_wing=profile.max_fat_per_wing,
        )
        wings_by_label = {"A": wing_a, "B": wing_b, "C": wing_c, "D": wing_d}

    for wing_label in profile.wings:
        wings_by_label[wing_label].sort(key=_fat_sort_key)
        if len(wings_by_label[wing_label]) > profile.max_fat_per_wing:
            raise ValidationError(
                f"{fdt.name}: wing {wing_label} overflow after rebalance "
                f"({len(wings_by_label[wing_label])} > {profile.max_fat_per_wing})"
            )

    for wing_label in profile.wings:
        for seq, fat in enumerate(wings_by_label[wing_label], start=1):
            fat.wing = wing_label
            fat.wing_id = wing_label
            fat.parent_fdt = fdt.name
            fat.fdt_serial = fdt.fdt_serial
            fat.fat_sequence = f"{seq:02d}"
            fat.fat_full_code = _project_tag("FAT", f"{fdt.fdt_serial}{wing_label}", f"{seq:02d}")
            fat.name = fat.fat_full_code

    fdt.wing_a_count = len(wings_by_label.get("A", []))
    fdt.wing_b_count = len(wings_by_label.get("B", []))
    fdt.wing_c_count = len(wings_by_label.get("C", []))
    fdt.wing_d_count = len(wings_by_label.get("D", []))
    # PON-major concatenation order — never interleaved (spec §7/§A.2).
    fdt.fats = [fat for label in profile.wings for fat in wings_by_label[label]]


def _fat_sequence_number(fat: FAT) -> int:
    try:
        return int(getattr(fat, 'fat_sequence', '') or 999)
    except Exception:
        return 999
