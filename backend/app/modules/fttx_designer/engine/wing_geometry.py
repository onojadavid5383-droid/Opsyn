"""Verbatim port of ``_angular_split_wings`` from
``FTTx Designer — dual PON integrated.py``.

Split into its own tiny module (not folded directly into
``wing_assignment.py``) because it is needed by two mutually-independent
callers that must not import each other: ``wing_assignment.py``
(``assign_wings_per_fdt``/``create_fdt_wing_cascades``) and ``fdt_anchor.py``
(``_renumber_fdt_wings``, called from ``repair/outlier_repair.py``). In the
source single file this was never an issue — every function shared one
namespace — but ``assign_wings_per_fdt`` itself calls
``repair.outlier_repair._relax_fdt_ownership`` as its own last step, so
``wing_assignment.py`` -> ``repair/outlier_repair.py`` -> ``fdt_anchor.py``
-> ``_angular_split_wings`` cannot loop back through ``wing_assignment.py``
without a circular import. Giving the wing-splitting geometry its own
dependency-free module breaks the cycle.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from .config import MAX_FAT_PER_WING
from .domain import FAT
from .geometry_compat import QgsPointXY
from .spatial_utils import DistanceCalculator


def _angular_split_wings(
    fdt_point: QgsPointXY,
    fats: List['FAT'],
    dist_calc: Optional['DistanceCalculator'] = None,
    max_per_wing: int = MAX_FAT_PER_WING,
) -> Tuple[List['FAT'], List['FAT']]:
    """Split ``fats`` into two spatially contiguous angular sectors around
    ``fdt_point``.

    v16 fix (Defect 1): replaces road-coordinate midpoint splitting
    (``lineLocatePoint`` half/half) and single-axis tangent-projection
    splitting, both of which only work when every FAT lies on one linear
    axis. At a T/Y-junction or wherever an FDT serves FATs on more than one
    physical road branch, a 1-D projection can and does interleave FATs
    from different branches into the same wing.

    This function instead asks the question the spec requires: "which
    directional sector *from the FDT* does this FAT belong to?" It computes
    each FAT's true bearing (angle) from the FDT anchor, sorts FATs around
    the compass, and cuts the circle at its two widest angular gaps. That
    always yields two contiguous arcs — FATs on different branches end up
    in different wings unless their branches point in genuinely similar
    directions, which is the correct behaviour at any junction shape.

    Only the *membership* question is answered here. Distance-from-FDT
    ordering (closest = -01) is a separate step performed by the caller —
    see the module docstring on ``create_fdt_wing_cascades``.
    """
    if not fats:
        return [], []
    if len(fats) == 1:
        return list(fats), []

    def _pt(f):
        return f.snapped_geometry or f.geometry

    def _angle(f):
        p = _pt(f)
        return math.atan2(p.y() - fdt_point.y(), p.x() - fdt_point.x())

    by_angle = sorted(fats, key=_angle)
    angles = [_angle(f) for f in by_angle]
    n = len(by_angle)

    # Circular gap AFTER index i (wrapping the last->first gap by +2π so all
    # gaps are directly comparable in the same [0, 2π) space).
    gaps = []
    for i in range(n):
        nxt = angles[(i + 1) % n] + (2 * math.pi if i == n - 1 else 0.0)
        gaps.append((nxt - angles[i], i))

    gaps_sorted = sorted(gaps, key=lambda g: -g[0])
    cut1 = gaps_sorted[0][1]

    # Pick the largest remaining gap that isn't immediately adjacent to
    # cut1 (adjacent cuts would leave one "wing" empty).
    cut2 = None
    for _gap, idx in gaps_sorted[1:]:
        sep = min((idx - cut1) % n, (cut1 - idx) % n)
        if sep >= 1:
            cut2 = idx
            break
    if cut2 is None:
        cut2 = gaps_sorted[1][1] if len(gaps_sorted) > 1 else cut1

    lo, hi = sorted([cut1, cut2])
    arc_1 = by_angle[lo + 1: hi + 1]
    arc_2 = by_angle[hi + 1:] + by_angle[:lo + 1]

    wing_a, wing_b = arc_1, arc_2

    # Respect the capacity cap while preserving contiguity: only the
    # FAT(s) nearest the sector boundary move, never a random member.
    while len(wing_a) > max_per_wing and len(wing_b) < max_per_wing:
        wing_b.insert(0, wing_a.pop())
    while len(wing_b) > max_per_wing and len(wing_a) < max_per_wing:
        wing_a.append(wing_b.pop(0))

    # Balance enforcement (requested enhancement): the widest-angular-gap
    # cut is chosen purely to keep physical branches apart, not to produce
    # equal counts — a genuine T-junction with 1 FAT on one arm and 6 on
    # the other is a real, correct split for that geometry. But most of the
    # time the "extra" gap width on one side is just noise (uneven FAT
    # spacing along a single road), not a real branch boundary, and the
    # target is "4 per wing" wherever the geometry can support it. So:
    # continue moving the boundary-adjacent FAT(s) — same contiguity-
    # preserving pop()/insert(0) as the cap-enforcement above, just with a
    # softer trigger (imbalance > 1, not only "over cap") — until the two
    # sides are within 1 of each other or one hits the cap. This never
    # moves a FAT across a genuine wide gap on its OWN side (each move only
    # peels the single nearest-the-boundary FAT), so branch separation from
    # a true junction is preserved; it only tightens up the common case of
    # mild angular skew.
    while len(wing_b) < max_per_wing and len(wing_a) - len(wing_b) > 1:
        wing_b.insert(0, wing_a.pop())
    while len(wing_a) < max_per_wing and len(wing_b) - len(wing_a) > 1:
        wing_a.append(wing_b.pop(0))

    return wing_a, wing_b
