"""Verbatim port of the network-distance oracle plumbing from
``FTTx Designer — dual PON integrated.py``: the module-level
``_DISTANCE_ORACLE`` singleton, ``install_distance_oracle()``,
``clear_distance_oracle()``, and ``_network_distance()`` — "the single
source of truth for how far apart two device anchors really are" used by
FAT/FDT capacity rebalancing, wing repair, and cable routing alike (grep
confirms 30+ call sites spanning fat_generation through cable_routing).

Split into its own module rather than folded into ``cable_routing.py``
(where ``NetworkDistanceOracle`` itself, the concrete oracle
``CableRouter`` installs, will live once that module is ported) precisely
*because* ``fat_generation.py``'s ``_rebalance_fats_for_capacity`` needs
``_network_distance()`` long before ``CableRouter``/``NetworkDistanceOracle``
exist in the pipeline's own dependency order. ``_network_distance()`` only
ever calls ``.distance(pt_a, pt_b)`` on whatever object was installed — pure
duck typing, no import of ``NetworkDistanceOracle`` needed here — so this
module has no forward reference to ``cable_routing.py`` to worry about.
"""

from __future__ import annotations

import math
from typing import Optional

from .geometry_compat import QgsPointXY

# Module-level singleton. _network_distance() and friends are called from
# every layer of the pipeline (FAT/FDT capacity repair, wing chain repair,
# cable routing) and none of them can sanely thread an oracle reference
# through every call site — so, exactly as in the source script, this stays
# a single global, reset once per run by install_distance_oracle()/
# clear_distance_oracle() from the pipeline orchestrator.
_DISTANCE_ORACLE: Optional[object] = None


def install_distance_oracle(oracle: Optional[object]) -> None:
    """Make ``oracle`` authoritative for every _network_distance() call."""
    global _DISTANCE_ORACLE
    _DISTANCE_ORACLE = oracle


def clear_distance_oracle() -> None:
    """Reset between runs so a Single->Dual->Single sequence in one session
    can never route against a stale road graph."""
    global _DISTANCE_ORACLE
    _DISTANCE_ORACLE = None


def _network_distance(
    pt_a: QgsPointXY,
    pt_b: QgsPointXY,
    road_a_id: Optional[int] = None,
    road_b_id: Optional[int] = None,
    topo: Optional['RoadTopologyEngine'] = None,
    dist_calc: Optional['DistanceCalculator'] = None,
) -> float:
    """Single source of truth for how far apart two device anchors really are.

    [Fix 1] Resolution order:
      1. NetworkDistanceOracle — the CableRouter master graph, i.e. the exact
         measurement that produces the cable written to the output layer.
      2. RoadTopologyEngine.weighted_shortest_path — legacy estimate, used only
         before the master graph has been built.
      3. Straight line — last resort.

    The v13 "fast paths" (same-road or < 50 m returns straight-line) were
    removed. They existed to avoid a per-call Dijkstra; the oracle caches one
    cost array per source vertex, so that cost is now paid at most once per
    device rather than once per query, and the approximation buys nothing.

    Note for callers: this function reports the length of the CABLE RUN
    between two anchors, including any frontage offset at either end, because
    that is the quantity every hard limit in this file is expressed in.
    """
    # Compute straight-line distance once
    if dist_calc is not None:
        straight = dist_calc.distance_points(pt_a, pt_b)
    else:
        straight = math.sqrt((pt_a.x() - pt_b.x()) ** 2 + (pt_a.y() - pt_b.y()) ** 2)

    # [Fix 1] PRIMARY PATH: the routing graph. This is the only measurement that
    # describes the cable actually produced downstream, so it wins whenever it
    # can answer. Everything below it is legacy fallback for the window before
    # the master graph exists.
    if _DISTANCE_ORACLE is not None:
        measured = _DISTANCE_ORACLE.distance(pt_a, pt_b)
        if measured is not None:
            # The graph cannot return a path shorter than the straight line;
            # if it does, the endpoints resolved to the same vertex and the
            # straight line is the better answer.
            return max(measured, straight)

    # ── Legacy fallback, used only before install_distance_oracle() ───────
    # [Fix 1] The two straight-line fast paths that used to sit here are gone.
    # "Same road -> straight-line" was never safe: two points on one curved or
    # looping segment are not Euclidean-close along the road. "< 50 m ->
    # straight-line" silently capped every short-range comparison. Both existed
    # to dodge the cost of weighted_shortest_path; the oracle above removes that
    # cost, so the approximations no longer buy anything.
    #
    # SLOW PATH: full topology-aware Dijkstra.
    if topo is not None:
        try:
            _, path_dist = topo.weighted_shortest_path(
                pt_a,
                pt_b,
                start_road_id=road_a_id,
                end_road_id=road_b_id,
            )
            if path_dist > 0:
                return path_dist
        except Exception:
            pass

    return straight
