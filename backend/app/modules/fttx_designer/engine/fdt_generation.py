"""Verbatim port of the FDT generation stage from
``FTTx Designer — dual PON integrated.py``: ``_fat_sort_key``,
``_roads_touch``, ``_get_touching_road_ids``, ``_find_borrow_candidate``,
``_candidate_inside_committed_group``, ``_find_relay_borrow_candidate``,
``_borrow_candidate_with_relay``, ``generate_fdts`` (the "Dead-End-First,
Walk-Forward" algorithm — the largest single function in the pipeline),
``_apply_fat_traceability``, and ``_make_fdt``.

No logic changes from the source script — only the QGIS types (now from
``engine.geometry_compat``) and cross-module imports.

Note: ``MAX_BOX_TO_BOX_DISTANCE`` is one of the 8 tunables the pipeline
overrides per-run (see runtime_config.py's docstring); every direct
reference below reads ``runtime_config.MAX_BOX_TO_BOX_DISTANCE``.
``FDT_MAX_RADIUS``, by contrast, is a *derived* constant
(``FDT_MAX_RADIUS = MAX_BOX_TO_BOX_DISTANCE`` at config.py's import time)
that ``_apply_config_to_globals()`` in the source script never itself
re-derives when it overrides ``MAX_BOX_TO_BOX_DISTANCE`` — so
``FDT_MAX_RADIUS`` silently keeps its original default even on a
run-configured box-to-box distance. That is a quirk of the source, not
something this port corrects (a "verbatim port" preserves the original's
own inconsistencies rather than silently fixing them); ``FDT_MAX_RADIUS``
is therefore imported as a plain static constant from config.py, exactly
like the source's own bare module-global reference.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Set, Tuple

from . import runtime_config as rc
from .cascade import _project_tag
from .config import CAPACITY_PROFILES, FDT_MAX_RADIUS, MAX_FAT_PER_WING, CapacityProfile, PONArchitecture, RoadClass, _balanced_partition_sizes
from .distance_oracle import _network_distance
from .domain import FAT, FDT, RoadSegment
from .errors import ValidationError
from .geometry_compat import QgsGeometry, QgsPointXY, QgsSpatialIndex
from .hop_limits import _b2b_endpoint, b2b_hop_limit
from .perf_logger import PerformanceLogger
from .spatial_utils import DistanceCalculator
from .topology import RoadTopologyEngine


def _fat_sort_key(fat: FAT) -> Tuple[int, int, float, float, int]:
    """Deterministic FAT ordering key used for naming and sequencing."""
    return (
        int(fat.cascade_order),
        int(fat.road_id),
        round(float(fat.geometry.x()), 6),
        round(float(fat.geometry.y()), 6),
        int(fat.total_customers)
    )


# =============================================================================
# FDT GENERATION
# =============================================================================

def _roads_touch(road_a, road_b) -> bool:
    """True if two road segments share an endpoint or meet at a junction.

    Uses touches() + intersects() combo:
    - touches() catches clean T/X junctions where geometries share a boundary point
    - intersects() fallback catches roads that slightly overlap due to digitising error
      but we exclude crossing roads using NOT crosses() to avoid false positives
    """
    if not road_a.geometry or not road_b.geometry:
        return False
    ga, gb = road_a.geometry, road_b.geometry
    # touches() is True when boundaries meet but interiors don't overlap
    if ga.touches(gb):
        return True
    # Some OSM exports have a tiny gap (<0.5m); use distance threshold
    return ga.distance(gb) < 0.5


def _get_touching_road_ids(road_id: int, roads: dict, road_index) -> list:
    """Return IDs of roads that physically touch (share a junction with) road_id.

    Only direct neighbours — no multi-hop expansion — so the search stays
    local and doesn't pull in FATs from across the city.
    """
    target = roads.get(road_id)
    if not target or target.geometry.isEmpty():
        return []
    bbox = target.geometry.boundingBox()
    bbox.grow(1.0)          # tiny buffer just to catch floating-point edge gaps
    result = []
    for rid in road_index.intersects(bbox):
        if rid == road_id:
            continue
        nb = roads.get(rid)
        if nb and _roads_touch(target, nb):
            result.append(rid)
    return result


def _find_borrow_candidate(
        last_fat: FAT,
        wing_fats: List[FAT],
        committed_fat_ids: Set[int],
        fats_by_road: Dict[int, List[FAT]],
        roads: Dict[int, 'RoadSegment'],
        topo: 'RoadTopologyEngine',
        junction_nid: int,
        junction_pt: QgsPointXY,
        dist_calc: Optional['DistanceCalculator'] = None,
        emitted_fdt_anchors: Optional[List[QgsPointXY]] = None,
) -> Optional[FAT]:
    """Return the best unowned FAT to extend a Wing B sequence across the junction.

    Context: Wing B on a dead-end road cascades FROM the FDT TOWARD the junction.
    The last FAT in Wing B is the junction-closest dead-end FAT.  The borrow
    must continue PAST the junction onto the parent/crescent road.

    Selection rules (applied in order):
    1.  FAT must not already be committed to any FDT group (ownership lock — Fix 1).
    2.  FAT must be on a road sharing the exact junction node (Fix 2).
    3.  FAT must be within BORROW_MAX_HOP_DISTANCE of *last_fat*.
    4.  Direction rule (Fix 5 — corrected for junction-crossing context):
        The cascade on the dead-end travels FROM deep inside the dead-end
        TOWARD the junction.  A valid borrow candidate sits on the far side of
        the junction, i.e. it is farther from the dead-end's road and closer to
        (or past) the junction from the last_fat's perspective.
        Concretely: the candidate must be CLOSER to the junction than last_fat
        OR on a different road than last_fat (i.e. already past the junction).
        This replaces the general dot-product direction check which used the
        dead-end's own cascade direction and wrongly rejected junction-side FATs.
    5.  If any already-emitted FDT anchor is closer to the candidate along the
        road graph than the current borrower's anchor, reject it.  This prevents
        a later dead-end FDT from stealing FATs that already sit inside an earlier
        FDT's territory.
    6.  Among passing candidates, pick the one NEAREST to last_fat (proximity
        rule — always borrow the next closest FAT, not an arbitrary one).
    """
    last_pt = last_fat.snapped_geometry or last_fat.geometry

    # Distance from last_fat to junction — used in direction rule (step 4)
    if dist_calc is not None:
        last_to_junc = dist_calc.distance_points(last_pt, junction_pt)
    else:
        last_to_junc = math.sqrt(
            (last_pt.x() - junction_pt.x()) ** 2 +
            (last_pt.y() - junction_pt.y()) ** 2
        )

    best_fat  = None
    best_dist = float('inf')

    # Collect candidate FATs from all roads that share the junction node
    if not (topo and topo._nodes and topo._edges):
        return None

    junction_road_ids = set()
    for rid, edge in topo._edges.items():
        if junction_nid in (edge['start'], edge['end']):
            junction_road_ids.add(rid)

    for road_id in junction_road_ids:
        if road_id == last_fat.road_id:
            continue  # don't borrow from own (dead-end) road

        road_fat_list = fats_by_road.get(road_id, [])
        for candidate in road_fat_list:
            # ── [FIX-DCW-3] Dual-carriageway median penalty ───────────────────
            # Penalise — do not hard-block — FATs from the opposite carriageway.
            #
            # Both carriageways share the junction node, so junction_road_ids
            # contains both CA and CB.  A naive hard-block on "donor.partner in
            # junction_road_ids" blocks CA too (because CA.partner=CB is in the
            # set), making it impossible to borrow from either side.
            #
            # Correct rule: if donor D's partner is ALSO in junction_road_ids
            # AND the partner is not the dead-end road itself, apply a large
            # distance penalty so proximity ranking still selects the correct-side
            # carriageway (CA) over the median-crossing one (CB), while preserving
            # CB as a fallback when CA has no available FATs.
            #
            # MEDIAN_CROSS_PENALTY is large enough to beat any realistic FAT
            # spacing (MAX_FAT_TO_FAT_DISTANCE = 150m) so the correct-side
            # carriageway always wins when both are candidates.
            # This is additive — the Fix 1/2/5 chain below is fully preserved.
            _MEDIAN_CROSS_PENALTY = 10_000.0   # m-equivalent
            _donor_road = roads.get(road_id) if roads else None
            _dcw_rank_penalty = 0.0
            if _donor_road is not None and _donor_road.dual_cw_partner is not None:
                _partner_rid = _donor_road.dual_cw_partner
                if (_partner_rid in junction_road_ids
                        and _partner_rid != last_fat.road_id):
                    _dcw_rank_penalty = _MEDIAN_CROSS_PENALTY
            # ── END [FIX-DCW-3] ───────────────────────────────────────────────
            # Fix 1: ownership lock
            if id(candidate) in committed_fat_ids:
                continue

            cand_pt = candidate.snapped_geometry or candidate.geometry

            # Fix 2 / Step 3: hop distance from last_fat to candidate.
            # This is the actual sequential box-to-box cable length, so use the
            # stricter FAT-to-FAT cap instead of the wider FDT grouping radius.
            dist = _network_distance(
                last_pt,
                cand_pt,
                road_a_id=last_fat.road_id,
                road_b_id=candidate.road_id,
                topo=topo,
                dist_calc=dist_calc,
            )
            # Hard reject: this is the actual cable length, not a proxy for it.
            # [Fix 4] Resolved through b2b_hop_limit() like every other hop
            # check. This is a FAT->FAT hop, so it was silently enforcing 150m
            # (BORROW_MAX_HOP_DISTANCE) while the shipping gate accepted 250m —
            # the same repair-vs-gate drift Fix 4 exists to remove.
            if dist > b2b_hop_limit(1):
                continue

            # Fix 5 (corrected): junction-crossing direction rule.
            # The candidate is on a DIFFERENT road than the dead-end, so it is
            # already past the junction by definition — no dot-product needed.
            # Additional proximity filter: prefer candidates closest to the
            # junction point itself (they are the natural extension of the
            # cascade that just crossed the junction mouth).
            cand_to_junc = _network_distance(
                cand_pt,
                junction_pt,
                road_a_id=road_id,
                topo=topo,
                dist_calc=dist_calc,
            )

            # Reciprocal-borrow guard: if an already-emitted FDT anchor is
            # closer to this candidate than the current borrower's anchor, the
            # candidate is deemed to lie inside an earlier FDT's territory and
            # must be rejected.
            borrower_anchor_dist = _network_distance(
                cand_pt,
                last_pt,
                road_a_id=road_id,
                road_b_id=last_fat.road_id,
                topo=topo,
                dist_calc=dist_calc,
            )
            if emitted_fdt_anchors:
                closer_to_emitted_anchor = False
                for anchor_pt in emitted_fdt_anchors:
                    if _network_distance(
                        cand_pt,
                        anchor_pt,
                        road_a_id=road_id,
                        topo=topo,
                        dist_calc=dist_calc,
                    ) < borrower_anchor_dist:
                        closer_to_emitted_anchor = True
                        break
                if closer_to_emitted_anchor:
                    continue

            # Rank by: (distance from last_fat, distance from junction)
            # Primary sort is proximity to last_fat; junction proximity breaks ties.
            # _dcw_rank_penalty (from FIX-DCW-3) is added to dist so opposite-
            # carriageway candidates rank behind correct-side candidates while
            # still remaining eligible as a fallback when no correct-side FAT exists.
            rank = (dist + _dcw_rank_penalty, cand_to_junc)
            best_rank = (best_dist, float('inf')) if best_fat is None else (
                best_dist,
                _network_distance(
                    (best_fat.snapped_geometry or best_fat.geometry),
                    junction_pt,
                    road_a_id=best_fat.road_id,
                    topo=topo,
                    dist_calc=dist_calc,
                )
            )
            if rank < best_rank:
                best_dist = dist
                best_fat  = candidate

    return best_fat


# =============================================================================
#  RELAY-BORROW EXTENSION  (2026-07-22)
# -----------------------------------------------------------------------------
#  Adds boundary-aware direct borrow + 1-hop relay/pass-through swap so that
#  no borrow crosses a previously-committed FDT's territory, and every borrow
#  is the geometrically closest legal choice.
# =============================================================================

def _candidate_inside_committed_group(
        candidate: 'FAT',
        emitted_groups: List[Tuple[List['FAT'], int]],
        topo: 'RoadTopologyEngine',
        dist_calc: Optional['DistanceCalculator'],
        acceptor_last_fat: 'FAT',
) -> Optional[int]:
    """Return index of committed group whose territory contains *candidate*,
    or None. A group 'contains' the candidate when SOME FAT of that group is
    strictly closer (network distance) to the candidate than the acceptor's
    anchor FAT is."""
    if not emitted_groups:
        return None
    cand_pt = candidate.snapped_geometry or candidate.geometry
    acc_pt  = acceptor_last_fat.snapped_geometry or acceptor_last_fat.geometry
    d_to_acceptor = _network_distance(
        cand_pt, acc_pt,
        road_a_id=candidate.road_id,
        road_b_id=acceptor_last_fat.road_id,
        topo=topo, dist_calc=dist_calc,
    )
    for gi, (grp_fats, _rid) in enumerate(emitted_groups):
        for f in grp_fats:
            fp = f.snapped_geometry or f.geometry
            d = _network_distance(
                cand_pt, fp,
                road_a_id=candidate.road_id, road_b_id=f.road_id,
                topo=topo, dist_calc=dist_calc,
            )
            if d < d_to_acceptor:
                return gi
    return None


def _find_relay_borrow_candidate(
        last_fat: 'FAT',
        acceptor_junction_pt: 'QgsPointXY',
        acceptor_junction_nid: int,
        emitted_groups: List[Tuple[List['FAT'], int]],
        committed_fat_ids: Set[int],
        fats_by_road: Dict[int, List['FAT']],
        roads: Dict[int, 'RoadSegment'],
        topo: 'RoadTopologyEngine',
        dist_calc: Optional['DistanceCalculator'],
        logger: 'PerformanceLogger',
) -> Optional[Tuple['FAT', int, 'FAT']]:
    """1-hop relay: acceptor absorbs fat_B (junction-closest FAT of an
    adjacent committed group); that group absorbs fat_C (a more-distant
    uncommitted FAT that is closer to the committed group than to acceptor).

    Returns (fat_take, group_index, fat_give_back) or None.
    Preserves MAX_BOX_TO_BOX_DISTANCE on every hop and MIN_FAT_PER_FDT of the
    donor group (1-for-1 swap)."""
    from .config import RELAY_MAX_HOP_DISTANCE

    last_pt = last_fat.snapped_geometry or last_fat.geometry

    best_swap  = None
    best_score = float('inf')

    for gi, (grp_fats, grp_rid) in enumerate(emitted_groups):
        # Reject groups whose nearest FAT is out of sequential box-to-box reach.
        min_d_to_group = min(
            _network_distance(
                last_pt, (f.snapped_geometry or f.geometry),
                road_a_id=last_fat.road_id, road_b_id=f.road_id,
                topo=topo, dist_calc=dist_calc,
            ) for f in grp_fats
        )
        if min_d_to_group > RELAY_MAX_HOP_DISTANCE:
            continue

        # Pick FAT-B: acceptor-closest member of this committed group.
        fat_b, fat_b_d = None, float('inf')
        for f in grp_fats:
            fp = f.snapped_geometry or f.geometry
            d = _network_distance(
                last_pt, fp,
                road_a_id=last_fat.road_id, road_b_id=f.road_id,
                topo=topo, dist_calc=dist_calc,
            )
            if d <= RELAY_MAX_HOP_DISTANCE and d < fat_b_d:
                fat_b, fat_b_d = f, d
        if fat_b is None:
            continue

        # Anchors used to reach FAT-C after FAT-B leaves the group.
        b_anchor_fats = [f for f in grp_fats if f is not fat_b] or grp_fats

        # Pick FAT-C: uncommitted FAT, in cable reach of some B-anchor,
        # and genuinely closer to B than to A (otherwise direct-borrow
        # would already have picked it).
        fat_c, fat_c_d = None, float('inf')
        for rid, cand_list in fats_by_road.items():
            for cand in cand_list:
                if id(cand) in committed_fat_ids or cand is fat_b:
                    continue
                cp = cand.snapped_geometry or cand.geometry
                d_to_b = min(
                    _network_distance(
                        cp, (bf.snapped_geometry or bf.geometry),
                        road_a_id=cand.road_id, road_b_id=bf.road_id,
                        topo=topo, dist_calc=dist_calc,
                    ) for bf in b_anchor_fats
                )
                if d_to_b > RELAY_MAX_HOP_DISTANCE:
                    continue
                d_to_a = _network_distance(
                    cp, last_pt,
                    road_a_id=cand.road_id, road_b_id=last_fat.road_id,
                    topo=topo, dist_calc=dist_calc,
                )
                if d_to_b >= d_to_a:
                    continue
                if d_to_b < fat_c_d:
                    fat_c, fat_c_d = cand, d_to_b
        if fat_c is None:
            continue

        score = fat_b_d + fat_c_d
        if score < best_score:
            best_score = score
            best_swap  = (fat_b, gi, fat_c)

    if best_swap is None:
        return None

    fat_b, gi, fat_c = best_swap
    logger.log(
        f"RELAY-BORROW: acceptor takes {getattr(fat_b, 'name', id(fat_b))} "
        f"from committed group #{gi} (road {emitted_groups[gi][1]}); "
        f"group absorbs {getattr(fat_c, 'name', id(fat_c))} in exchange "
        f"(swap-cost {best_score:.0f} m)."
    )
    return best_swap


def _borrow_candidate_with_relay(
        *, last_fat, wing_fats, committed_fat_ids, fats_by_road, roads, topo,
        junction_nid, junction_pt, dist_calc, emitted_fdt_anchors,
        emitted_groups, logger,
):
    """Try direct borrow first (with boundary check), fall back to relay."""
    direct = _find_borrow_candidate(
        last_fat=last_fat, wing_fats=wing_fats,
        committed_fat_ids=committed_fat_ids,
        fats_by_road=fats_by_road, roads=roads, topo=topo,
        junction_nid=junction_nid, junction_pt=junction_pt,
        dist_calc=dist_calc, emitted_fdt_anchors=emitted_fdt_anchors,
    )
    if direct is not None:
        owner_gi = _candidate_inside_committed_group(
            direct, emitted_groups, topo, dist_calc, last_fat,
        )
        if owner_gi is None:
            return ('direct', direct)
        logger.log(
            f"Direct borrow candidate {getattr(direct, 'name', id(direct))} "
            f"falls inside committed group #{owner_gi} boundary — "
            f"attempting relay swap."
        )

    swap = _find_relay_borrow_candidate(
        last_fat=last_fat,
        acceptor_junction_pt=junction_pt,
        acceptor_junction_nid=junction_nid,
        emitted_groups=emitted_groups,
        committed_fat_ids=committed_fat_ids,
        fats_by_road=fats_by_road, roads=roads, topo=topo,
        dist_calc=dist_calc, logger=logger,
    )
    if swap is not None:
        return ('relay', swap)
    return None

# ── END RELAY-BORROW EXTENSION ───────────────────────────────────────────────


def generate_fdts(fats: List[FAT],
                  logger: PerformanceLogger,
                  roads: Optional[Dict[int, 'RoadSegment']] = None,
                  dist_calc: Optional['DistanceCalculator'] = None,
                  topo: Optional['RoadTopologyEngine'] = None,
                  profile: Optional['CapacityProfile'] = None) -> List[FDT]:
    """Generate FDTs using a Dead-End-First, Walk-Forward algorithm.

    Algorithm
    ---------
    Step 0  Index FATs by road and sort by cascade_order.
    Step 1  Build exact junction topology from topo engine (road_nodes,
            junction_roads).  Falls back to no-topology mode gracefully.
    Step 2  Classify dead-end roads:
            • Self-sufficient (≥ MIN_FAT_PER_FDT FATs) → processed normally.
            • Non-self-sufficient → absorbed into parent road at junction.
              Multiple dead-ends at the same junction node are pooled first;
              if their combined count ≥ MIN they form their own FDT group
              (Step-2 dual dead-end rule) instead of being injected.
    Step 3  Group roads by corridor_id; order roads within each corridor
            by BFS walk using junction topology.
    Step 4  Walk each corridor (low-rank first) accumulating FATs into a
            running group and emitting an FDT every time the group hits
            MAX_FAT_PER_FDT.  Dead-end FATs are injected at their junction
            position along the parent road using normalised cascade_order.
    Step 5  At corridor end, if remainder < MIN_FAT_PER_FDT: try to pass
            overflow to the higher-rank parent corridor at the terminal node.
            If no viable parent exists: log as isolated and emit anyway.
    Step 6  Isolated roads (corridor_id == -1) are walked individually.
    Step 7  Orphaned dead-end FATs (no parent road found) are emitted as
            isolated groups with an error log entry.
    Step 8  Build FDT objects; primary_road_id is tracked explicitly
            (= the road the walk was on when the group opened) — no
            majority-vote over borrowed FAT road_ids needed.
    """
    logger.start_module("FDT Generation")
    if not fats:
        return []

    # Architecture-aware capacity ceiling (spec §21/§22 "MUST CHANGE — become
    # profile.max_fat_per_fdt/profile.min_fat_per_fdt, threaded not global").
    # Shadowing the module-level constants as locals threads the profile
    # through every one of this function's ~40 internal chunk-sizing call
    # sites without touching each individually — safe because this function
    # never declares them `global`, and Single-PON's default profile carries
    # the exact same numeric values, so behaviour is byte-identical unless a
    # Dual-PON profile is explicitly passed in.
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]

    # [Dual-PON borrow-locality fix] Every grouping/merge pass below (corridor
    # walk, dead-end injection, both underfilled BFS/geographic-recalibration
    # passes) is tuned around Single-PON's 7-8 FAT scale — that target
    # matches the natural FAT density of one local road segment, so those
    # passes stay local. Naively doubling the target to Dual-PON's 14-16
    # forces the exact same walk/BFS machinery to sweep ~2x the geography to
    # hit it, chaining merges across junctions/roads that belong to
    # different natural FDT territories (confirmed on real runs: one FDT's
    # cascade running straight through a neighbouring FDT's streets).
    #
    # Fix: always run the grouping computation below at the Single-PON scale
    # — byte-identical to what a real Single-PON run produces on the same
    # road network — then pair two locally-adjacent Single-PON-sized groups
    # into one physical Dual-PON box afterward (see
    # _pair_pon_groups_into_dual_fdts, invoked just before Step 8), instead
    # of asking this walk to reach twice as far on its own. The real
    # profile values are restored right before Step 8 so the emitted FDT
    # objects (and the two-way validation below) are still checked against
    # the actually-selected architecture's ceiling.
    _grouping_profile = (CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
                         if profile.pon_count == 2 else profile)
    MAX_FAT_PER_FDT = _grouping_profile.max_fat_per_fdt
    MIN_FAT_PER_FDT = _grouping_profile.min_fat_per_fdt
    # Found in a later audit sweep: the customer-capacity ceiling check
    # (fdt.total_customers > MAX_FDT_CAPACITY) was missed from the original
    # shadow list — a real bug, since a valid 16-FAT/128-customer Dual-PON
    # group would otherwise be rejected by the bare Single-PON 64 limit.
    MAX_FDT_CAPACITY = _grouping_profile.max_fdt_capacity

    def _footprint_aware_partition(
        fats_ordered: List['FAT'], total: int, min_size: int, max_size: int,
    ) -> Tuple[List[int], bool]:
        """[Cost-reduction fix] Among every K mathematically valid for
        `total` (spec §3/§4), _balanced_partition_sizes always returns the
        LOWEST one — correct when geography is uniform, but on real,
        unevenly-dense road networks that alone regularly produces FDTs
        whose members are spread far enough apart that no wing sequencing
        can keep every box-to-box hop under MAX_BOX_TO_BOX_DISTANCE.
        Confirmed directly against real QGIS runs on this project: the
        large majority of FDTs affected, and the violations traced
        specifically to this function's own per-corridor/per-merge sizing
        decision — not to the post-generation capacity rebalancer, which
        already got this same treatment in an earlier round but turned out
        to almost never be the FDT-formation path actually exercised
        (`generate_fdts()` usually needs zero post-hoc pooling; the
        decisions that matter are made right here).

        Evaluates every valid K's resulting chunks — sliced from
        `fats_ordered` in the SAME order the caller already walks/pools
        them in (corridor walk order for _walk_fat_seq, road_id+
        cascade_order for the two underfilled-group merge passes below) —
        and prefers whichever K keeps every chunk's own worst-case
        footprint (max pairwise straight-line distance among its members)
        smallest. Falls back to the plain lowest-K answer whenever only
        one K is valid, or a larger K doesn't measurably help (5m
        improvement threshold, ties toward the lower K) — this never
        trades device count away for no real geographic benefit. Single
        authoritative implementation shared by all three call sites so
        they can't drift out of sync with each other or with the
        (separately implemented, same-pattern) version in
        _rebalance_fdts_for_capacity.
        """
        if total <= 0 or dist_calc is None:
            return _balanced_partition_sizes(total, min_size, max_size)
        k_min = -(-total // max_size) if max_size else 0
        k_max = total // min_size if min_size else 0
        if k_min <= 0 or k_min > k_max or k_min == k_max:
            return _balanced_partition_sizes(total, min_size, max_size)

        def _footprint(chunk: List['FAT']) -> float:
            if len(chunk) <= 1:
                return 0.0
            pts = [f.snapped_geometry or f.geometry for f in chunk]
            worst = 0.0
            for i in range(len(pts)):
                for j in range(i + 1, len(pts)):
                    d = dist_calc.distance_points(pts[i], pts[j])
                    if d > worst:
                        worst = d
            return worst

        best_sizes, best_worst = None, None
        for k in range(k_min, k_max + 1):
            base, remainder = divmod(total, k)
            sizes = [base + 1 if i < remainder else base for i in range(k)]
            idx = 0
            worst = 0.0
            for size in sizes:
                chunk = fats_ordered[idx: idx + size]
                idx += size
                fp = _footprint(chunk)
                if fp > worst:
                    worst = fp
            if best_worst is None or worst < best_worst - 5.0:
                best_sizes, best_worst = sizes, worst
        return best_sizes, True

    # Fix 1: Global ownership lock — tracks every FAT id that has been
    # committed to an FDT group.  Any borrow logic must check this set
    # before taking a FAT so no FAT can belong to two FDT groups.
    committed_fat_ids: Set[int] = set()

    def _commit_group(group: List[FAT]) -> None:
        """Mark all FATs in a finalised group as owned."""
        for f in group:
            committed_fat_ids.add(id(f))

    # ── 0. Index and sort FATs by road ───────────────────────────────────
    fats_by_road: Dict[int, List[FAT]] = defaultdict(list)
    for fat in fats:
        fats_by_road[fat.road_id].append(fat)
    for rid in fats_by_road:
        fats_by_road[rid].sort(key=_fat_sort_key)
    all_fat_road_ids: Set[int] = set(fats_by_road.keys())

    # ── 1. Junction topology ──────────────────────────────────────────────
    # junction_roads[nid] = set of all road IDs meeting at that node
    # road_nodes[rid]     = (start_nid, end_nid)
    junction_roads: Dict[int, Set[int]] = defaultdict(set)
    road_nodes: Dict[int, Tuple[int, int]] = {}

    if topo and topo._edges and topo._nodes:
        for rid, edge in topo._edges.items():
            sn, en = edge['start'], edge['end']
            road_nodes[rid] = (sn, en)
            junction_roads[sn].add(rid)
            junction_roads[en].add(rid)

    def _junction_pos(junc_pt: QgsPointXY, road: 'RoadSegment') -> float:
        """Normalised 0–1 position of junc_pt along road geometry."""
        if not road or not road.geometry or road.geometry.isEmpty():
            return 0.5
        length = road.geometry.length()
        if length <= 0:
            return 0.5
        t = road.geometry.lineLocatePoint(QgsGeometry.fromPointXY(junc_pt))
        return t / length

    # result_groups is built up throughout; finalised in step 8
    result_groups: List[Tuple[List[FAT], int]] = []

    # ── 2. Inner Dead-End Logic (5 <= K <= 8 FATs) ──
    # Enhancement: when a dead-end has more than 4 FATs the FDT is placed
    # INSIDE the dead-end road.  Wing A receives the 4 deepest FATs (farthest
    # from junction).  Wing B receives the remaining dead-end FATs plus FATs
    # borrowed from the parent road to fill Wing B up to MAX_FAT_PER_WING=4.
    #
    # Borrow guard: we only take FATs from the parent road when the parent
    # retains >= MIN_FAT_PER_FDT FATs after lending.  This prevents the
    # double-assignment collision visible in the reference image where the
    # same parent FATs appear in both the dead-end FDT's Wing B and the
    # parent road's own FDT group.
    #
    # Borrowed FATs are tagged with a sentinel attribute
    # `_borrowed_from_parent = True` so assign_wings_per_fdt can order them
    # correctly at the far (junction) end of Wing B rather than the near end.
    inner_dead_end_rids = set()
    emitted_fdt_anchors: List[QgsPointXY] = []
    if roads and topo and topo._nodes:
        for rid in sorted(all_fat_road_ids):
            road = roads.get(rid)
            if not (road and road.is_dead_end):
                continue
            fat_list = fats_by_road.get(rid, [])
            # FIXED [Phase-3a]: was  if not (5 <= len(fat_list) <= 8): continue
            # Hard-capping at 8 silently dropped dead-ends with 9+ FATs out of
            # inner dead-end logic.  The correct upper bound is MAX_FAT_PER_FDT
            # (the physical limit of any FDT group), not the coincidental value 8.
            if not (5 <= len(fat_list) <= MAX_FAT_PER_FDT):
                continue

            sn, en = road_nodes.get(rid, (None, None))
            if sn is None:
                continue

            sn_deg = len(topo._nodes.get(sn, {}).get('edges', set()))
            en_deg = len(topo._nodes.get(en, {}).get('edges', set()))
            junc_nid = sn if sn_deg >= en_deg else en
            junc_pt = topo._nodes[junc_nid]['point']

            # Identify the parent road (non-dead-end road at the junction)
            parent_rid = None
            for nb_rid in junction_roads.get(junc_nid, set()):
                nb_road = roads.get(nb_rid)
                if nb_road and not nb_road.is_dead_end and nb_rid != rid:
                    if nb_rid in all_fat_road_ids and parent_rid is None:
                        parent_rid = nb_rid
                    elif parent_rid is None:
                        parent_rid = nb_rid

            # ── Borrow FATs from touching roads to complete Wing B ─────────
            # Wing A = 4 deepest dead-end FATs (fixed).
            # Wing B needs up to (MAX_FAT_PER_WING - (len(fat_list) - 4)) FATs
            # borrowed from roads that share the junction node.
            #
            # Self-sufficiency rule (N = 7 or 8):
            #   N=8 -> Wing A=4, Wing B=4 -- fully packed, zero borrowing needed.
            #   N=7 -> Wing A=4, Wing B=3 -- meets MIN_FAT_PER_FDT (7), no borrow.
            #   Both form a complete standalone FDT group with dead-end FATs only.
            #   Borrowing for N>=MIN_FAT_PER_FDT would pull foreign FATs into an
            #   already-valid group and cause the FAT-bleed collision.
            #
            # Only N=5 (needs 3) and N=6 (needs 2) genuinely require borrowing.
            #
            # NEW borrow selection (Fixes 1, 2, 5):
            #   Instead of selecting from parent road by exclusion radius, we use
            #   _find_borrow_candidate which:
            #     • enforces ownership lock (Fix 1)
            #     • requires the donor road share the exact junction node (Fix 2)
            #     • selects the nearest FAT AHEAD of the cascade direction (Fix 5)
            #   This prevents FATs from the wrong end of a crescent / parent road
            #   being grabbed, and prevents double-ownership across FDT groups.
            borrowed: List[FAT] = []
            dead_end_count = len(fat_list)   # N (5-8)

            # Self-sufficient: N >= MIN -- form the group with dead-end FATs only
            if dead_end_count >= MIN_FAT_PER_FDT:
                group_fats = fat_list[:]
                result_groups.append((group_fats, rid))
                _commit_group(group_fats)  # Fix 1: lock ownership immediately
                if junc_pt is not None:
                    emitted_fdt_anchors.append(junc_pt)
                logger.log(
                    f"Inner dead-end road {rid}: {dead_end_count} FATs >= MIN "
                    f"{MIN_FAT_PER_FDT} -- self-sufficient, no borrowing needed "
                    f"-> standalone inner FDT group"
                )
                inner_dead_end_rids.add(rid)
                continue   # skip the borrow block entirely

            wing_b_dead_end_count = dead_end_count - 4    # FATs already in Wing B from dead-end
            wing_b_needed = MAX_FAT_PER_WING - wing_b_dead_end_count  # slots to fill
            wing_b_needed = max(0, wing_b_needed)

            if wing_b_needed > 0:
                # Sort dead-end FATs by distance to junction: index 0 = nearest junction
                de_sorted_by_junc = sorted(
                    fat_list,
                    key=lambda f: (
                        dist_calc.distance_points(f.geometry, junc_pt)
                        if dist_calc else
                        math.sqrt((f.geometry.x() - junc_pt.x()) ** 2 +
                                  (f.geometry.y() - junc_pt.y()) ** 2)
                    )
                )

                # Build the Wing B dead-end sequence ordered so that the
                # junction-CLOSEST FAT is LAST (index -1).  The borrow must
                # extend past the junction, so last_fat_in_seq must be the FAT
                # physically nearest the junction mouth.
                #
                # de_sorted_by_junc[0] = closest to junction (smallest distance)
                # de_sorted_by_junc[-1] = deepest into dead-end
                #
                # Wing B dead-end portion = the (dead_end_count - 4) FATs nearest
                # the junction (they sit between the FDT and the junction mouth).
                # We keep them ordered junction-closest LAST so that
                # wing_b_sequence_so_far[-1] is the anchor for the borrow search.
                wing_b_junc_portion: List[FAT] = de_sorted_by_junc[:wing_b_dead_end_count]
                # Reverse so junction-closest is at index -1
                wing_b_sequence_so_far: List[FAT] = list(reversed(wing_b_junc_portion))

                # FIXED [Phase-3b]: Iteratively pick the next best borrow candidate
                # (Fix 5 direction-aware) with per-slot blocked-set retry.
                #
                # Previously the loop used `break` when the best candidate's donor
                # road was too depleted, aborting the entire borrow attempt even
                # when other candidates on different non-depleted donor roads existed.
                # Now each slot carries a local slot_blocked_ids set; candidates that
                # fail the donor-depletion check are added to it and the retry loop
                # calls _find_borrow_candidate again (passing the merged blocked set)
                # until a valid candidate is found or all reachable ones are exhausted.
                for _slot in range(wing_b_needed):
                    if wing_b_sequence_so_far:
                        last_fat_in_seq = wing_b_sequence_so_far[-1]
                    else:
                        # No Wing B dead-end FATs — anchor at junction-closest dead-end FAT.
                        last_fat_in_seq = de_sorted_by_junc[0] if de_sorted_by_junc else fat_list[0]

                    # Per-slot set of candidate ids rejected for donor depletion.
                    slot_blocked_ids: Set[int] = set()
                    slot_filled = False

                    for _retry in range(20):   # generous cap; realistic networks << 20
                        _effective_blocked = committed_fat_ids | slot_blocked_ids

                        result = _borrow_candidate_with_relay(
                            last_fat            = last_fat_in_seq,
                            wing_fats           = wing_b_sequence_so_far,
                            committed_fat_ids   = _effective_blocked,
                            fats_by_road        = fats_by_road,
                            roads               = roads,
                            topo                = topo,
                            junction_nid        = junc_nid,
                            junction_pt         = junc_pt,
                            dist_calc           = dist_calc,
                            emitted_fdt_anchors = emitted_fdt_anchors,
                            emitted_groups      = result_groups,
                            logger              = logger,
                        )

                        if result is None:
                            logger.log(
                                f"Inner dead-end road {rid}: no reachable borrow "
                                f"candidate (direct or relay) for slot "
                                f"{_slot + 1}/{wing_b_needed}."
                            )
                            break

                        kind, payload = result

                        if kind == 'direct':
                            candidate       = payload
                            donor_road_id   = candidate.road_id
                            donor_remaining = len(
                                [f for f in fats_by_road.get(donor_road_id, [])
                                 if id(f) not in committed_fat_ids]
                            ) - 1
                            if donor_remaining < MIN_FAT_PER_FDT:
                                logger.log(
                                    f"Inner dead-end road {rid}: donor road "
                                    f"{donor_road_id} would retain only "
                                    f"{donor_remaining} FATs — blocking "
                                    f"{getattr(candidate, 'name', id(candidate))} "
                                    f"for slot {_slot + 1}, retrying."
                                )
                                slot_blocked_ids.add(id(candidate))
                                continue
                            borrowed.append(candidate)
                            candidate._borrowed_from_parent = True
                            candidate._allocation_trace     = "borrowed"
                            wing_b_sequence_so_far.append(candidate)
                            fats_by_road[donor_road_id] = [
                                f for f in fats_by_road[donor_road_id]
                                if id(f) != id(candidate)
                            ]
                            logger.log(
                                f"Inner dead-end road {rid}: borrowed FAT from "
                                f"road {donor_road_id} for Wing B slot "
                                f"{_slot + 1} (donor retains {donor_remaining} "
                                f">= MIN {MIN_FAT_PER_FDT})."
                            )
                            slot_filled = True
                            break

                        # kind == 'relay'  → apply 1-for-1 swap on committed group
                        fat_take, gi, fat_give = payload
                        donor_group_fats, donor_group_rid = result_groups[gi]
                        donor_group_fats.remove(fat_take)
                        donor_group_fats.append(fat_give)
                        result_groups[gi] = (donor_group_fats, donor_group_rid)

                        committed_fat_ids.discard(id(fat_take))
                        committed_fat_ids.add(id(fat_give))

                        fats_by_road[fat_give.road_id] = [
                            f for f in fats_by_road[fat_give.road_id]
                            if id(f) != id(fat_give)
                        ]

                        fat_take._allocation_trace     = "relay-swap-out"
                        fat_give._allocation_trace     = "relay-swap-in"
                        fat_take._borrowed_from_parent = True

                        borrowed.append(fat_take)
                        wing_b_sequence_so_far.append(fat_take)
                        slot_filled = True
                        break

                    if not slot_filled:
                        break  # no candidate found even after retries; stop borrowing

                if not borrowed:
                    logger.log(
                        f"Inner dead-end road {rid}: no FATs could be borrowed — "
                        f"Wing B will use dead-end FATs only."
                    )

            group_fats = fat_list + borrowed
            result_groups.append((group_fats, rid))
            _commit_group(group_fats)  # Fix 1: lock all FATs in this group
            if junc_pt is not None:
                emitted_fdt_anchors.append(junc_pt)
            logger.log(
                f"Inner dead-end road {rid}: {len(fat_list)} dead-end FATs + "
                f"{len(borrowed)} borrowed from parent {parent_rid} "
                f"→ standalone inner FDT group ({len(group_fats)} total)"
            )
            inner_dead_end_rids.add(rid)

    for rid in inner_dead_end_rids:
        fats_by_road.pop(rid, None)
        all_fat_road_ids.discard(rid)

    # ── 2. Dead-end classification ────────────────────────────────────────
    # Pool ALL non-self-sufficient dead-ends per junction node FIRST, then
    # decide: combined ≥ MIN → standalone group(s); else inject into parent.
    junction_de_pool: Dict[int, List[FAT]] = defaultdict(list)   # nid → FATs
    junction_parent: Dict[int, Optional[int]] = {}               # nid → parent rid
    absorbed_rids: Set[int] = set()

    if roads and topo and topo._nodes:
        for rid in sorted(all_fat_road_ids):
            road = roads.get(rid)
            if not (road and road.is_dead_end):
                continue
            fat_list = fats_by_road.get(rid, [])
            if not fat_list or len(fat_list) >= MIN_FAT_PER_FDT:
                continue  # self-sufficient or no FATs: process normally

            sn, en = road_nodes.get(rid, (None, None))
            if sn is None:
                continue  # road absent from topo graph — leave in normal pool

            sn_deg = len(topo._nodes.get(sn, {}).get('edges', set()))
            en_deg = len(topo._nodes.get(en, {}).get('edges', set()))
            junc_nid = sn if sn_deg >= en_deg else en

            junction_de_pool[junc_nid].extend(fat_list)
            absorbed_rids.add(rid)

            if junc_nid not in junction_parent:
                parent_rid = None
                for nb_rid in junction_roads.get(junc_nid, set()):
                    nb_road = roads.get(nb_rid)
                    if nb_road and not nb_road.is_dead_end and nb_rid != rid:
                        if nb_rid in all_fat_road_ids and parent_rid is None:
                            parent_rid = nb_rid
                        elif parent_rid is None:
                            parent_rid = nb_rid
                junction_parent[junc_nid] = parent_rid

    # Remove absorbed dead-ends from normal processing pool
    for rid in absorbed_rids:
        fats_by_road.pop(rid, None)
        all_fat_road_ids.discard(rid)

    # dead_end_inject[parent_rid] = [(position_0_1, fat_list, source_rid), ...]
    # source_rid identifies the physical branch/dead-end road the injected
    # FATs came from, so the corridor walk can keep branch clusters intact
    # and never split a single branch's FATs across two FDT groups.
    dead_end_inject: Dict[int, List[Tuple[float, List[FAT], int]]] = defaultdict(list)
    # overflow_inject[parent_rid] = [(position_0_1, fat_list, source_rid), ...]
    # Like dead_end_inject but for non-dead-end child overflow — FATs are merged
    # at the junction position on the parent road rather than blindly prepended.
    overflow_inject: Dict[int, List[Tuple[float, List[FAT], int]]] = defaultdict(list)
    # orphan_pending[nid] = FATs with no identifiable parent
    orphan_pending: Dict[int, List[FAT]] = defaultdict(list)
    # result_groups is built up throughout; finalised in step 8 (already initialized in step 2a)

    for junc_nid, pool in junction_de_pool.items():
        if not pool:
            continue
        parent_rid = junction_parent.get(junc_nid)

        if len(pool) >= MIN_FAT_PER_FDT:
            # Step-2 dual dead-end rule: emit standalone group(s) at junction
            p_primary = pool[0].road_id
            for i in range(0, len(pool), MAX_FAT_PER_FDT):
                chunk = pool[i:i + MAX_FAT_PER_FDT]
                if chunk:
                    result_groups.append((chunk, p_primary))
                    _commit_group(chunk)  # Fix 1: lock ownership
                    logger.log(
                        f"Dead-end junction {junc_nid}: {len(chunk)} combined "
                        f"FATs → standalone FDT group")
        elif parent_rid is not None and parent_rid in all_fat_road_ids:
            parent_road = roads.get(parent_rid) if roads else None
            junc_pt = topo._nodes[junc_nid]['point']
            pos = _junction_pos(junc_pt, parent_road)
            _pool_src_rid = pool[0].road_id
            for fat in pool:
                fat._allocation_trace = "absorbed"
            dead_end_inject[parent_rid].append((pos, list(pool), _pool_src_rid))
            logger.log(
                f"Dead-end junction {junc_nid}: {len(pool)} FATs absorbed "
                f"into road {parent_rid} at pos {pos:.2f}")
        else:
            orphan_pending[junc_nid].extend(pool)
            logger.log(
                f"Dead-end junction {junc_nid}: {len(pool)} FATs orphaned "
                f"(no parent road with FATs found)")

    # ── 3. Build spanning tree over all roads with FATs ─────────────────────
    # BFS from the highest-rank road in each connected component establishes
    # parent→child relationships.  Processing in REVERSE BFS order (leaves
    # first, root last) means every road passes its unavoidable remainder up
    # to its parent, so FATs accumulate continuously with no corridor
    # boundaries breaking the flow.

    _rank: Dict[RoadClass, int] = {
        RoadClass.SERVICE: 0, RoadClass.UNKNOWN: 1, RoadClass.DEAD_END: 2,
        RoadClass.TERTIARY: 3, RoadClass.DUAL_CARRIAGEWAY: 4,
        RoadClass.SECONDARY: 4, RoadClass.PRIMARY: 5,
    }

    def _road_rank(rid: int) -> int:
        road = roads.get(rid) if roads else None
        return _rank.get(road.road_class, 1) if road else 1

    parent_of: Dict[int, Optional[int]] = {}   # rid → parent rid (None = root)
    process_order: List[int] = []              # BFS order (root first)

    visited_tree: Set[int] = set()
    # Seed BFS from highest-rank roads so they become roots / parents
    for start_rid in sorted(all_fat_road_ids, key=_road_rank, reverse=True):
        if start_rid in visited_tree:
            continue
        bfs_q: List[int] = [start_rid]
        parent_of[start_rid] = None
        visited_tree.add(start_rid)
        while bfs_q:
            next_q: List[int] = []
            for rid in bfs_q:
                process_order.append(rid)
                sn, en = road_nodes.get(rid, (None, None))
                if sn is None:
                    continue
                for nid in (sn, en):
                    for nb_rid in junction_roads.get(nid, set()):
                        if nb_rid in all_fat_road_ids and nb_rid not in visited_tree:
                            # ENHANCEMENT: never cross the dual-carriageway median in
                            # the spanning tree.  Partner carriageways share junction
                            # nodes by topology but must serve their own FATs
                            # independently — linking them here causes overflow FATs
                            # to be routed across the median and FATs from both sides
                            # to land in the same FDT group.
                            _nb_rd = roads.get(nb_rid) if roads else None
                            if _nb_rd and _nb_rd.dual_cw_partner == rid:
                                continue
                            visited_tree.add(nb_rid)
                            parent_of[nb_rid] = rid
                            next_q.append(nb_rid)
            bfs_q = next_q

    # Roads with no junction topology are isolated roots
    for rid in sorted(all_fat_road_ids):
        if rid not in visited_tree:
            parent_of[rid] = None
            process_order.append(rid)

    # road_overflow[rid] = (FAT, primary_road_id, branch_id) tuples passed up from child roads
    road_overflow: Dict[int, List[Tuple[FAT, int, int]]] = defaultdict(list)

    def _walk_fat_seq(
        fat_seq: List[Tuple[FAT, int, int]],
        prepend: Optional[List[Tuple[FAT, int, int]]] = None,
    ) -> Optional[Tuple[List[FAT], int]]:
        """Walk (fat, road_id, branch_id) triples with look-ahead optimal group sizing.

        Instead of greedy MAX-fill (which produces avoidable underfilled tails),
        we plan group sizes over the full sequence before walking, via the
        single authoritative _balanced_partition_sizes(total, MIN, MAX)
        (spec §2/§3/§9) — correct for any MIN/MAX pair, not just the
        Single-PON case where MAX-1 happens to equal MIN.

        BRANCH-BOUNDARY ENHANCEMENT: the raw `sizes` plan above is computed purely
        from totals and may place a cut index in the middle of a contiguous run of
        FATs that all share the same `branch_id` (i.e. all come from the same
        physical road / injected branch).  Cutting there would split one branch's
        FATs across two adjacent FDT groups — the exact cross-bleed seen between
        FDT-0021/0023 and FDT-0010/0012.  Before walking, every proposed cut index
        is snapped to the nearest branch-run boundary (where branch_id changes),
        provided the resulting chunk sizes still satisfy MIN_FAT_PER_FDT.  If a
        single branch run is itself smaller than MIN and cannot be merged without
        violating a neighbouring boundary, it is kept intact as an indivisible
        "atom" — attached wholly to the chunk it falls within, even if that chunk
        slightly exceeds MAX (soft-cap tolerance) — rather than being torn apart.

        Returns (remainder_fats, primary_road_id) only when the tail group is
        unavoidably < MIN (i.e. the corridor total cannot be partitioned into
        all-valid groups), so the caller can pass it to a parent corridor.
        Returns None when every group emitted is ≥ MIN.
        """
        full = (prepend or []) + fat_seq
        total = len(full)
        if total == 0:
            return None

        # [FIX spec §2] The old MAX-fill/deficit-conversion math implicitly
        # assumed MAX_FAT_PER_FDT - 1 == MIN_FAT_PER_FDT (true for Single-PON's
        # 8/7, false for Dual-PON's 16/14) and could emit invalid partitions
        # like 16+12 or 16+13 where valid ones (14+14, 14+15) exist.
        # _balanced_partition_sizes is the single authoritative, architecture-
        # agnostic replacement (spec §9).
        # [Cost-reduction fix] this is the PRIMARY FDT-sizing decision for
        # most corridors (confirmed against real QGIS runs: the large
        # majority of FDTs are formed directly here, with the post-
        # generation capacity rebalancer never needing to touch them at
        # all) — so it's also the primary place a naive lowest-K choice
        # produces geographically sprawling groups. _footprint_aware_partition
        # picks a higher K instead whenever doing so keeps every resulting
        # chunk meaningfully more compact; falls back to identical
        # lowest-K behaviour otherwise.
        sizes, _walk_exact = _footprint_aware_partition(
            [e[0] for e in full], total, MIN_FAT_PER_FDT, MAX_FAT_PER_FDT
        )

        # ── Branch-run boundary detection ──────────────────────────────────
        # run_boundary[i] is True if index i is the START of a new branch run
        # (i.e. full[i].branch_id != full[i-1].branch_id, or i == 0).
        branch_ids = [b for _, _, b in full]
        run_starts: List[int] = [0]
        for i in range(1, total):
            if branch_ids[i] != branch_ids[i - 1]:
                run_starts.append(i)

        def _nearest_run_start(cut: int, lo: int, hi: int) -> int:
            """Nearest run-start index to `cut`, within (lo, hi] inclusive."""
            best, best_dist = None, None
            for rs in run_starts:
                if lo < rs <= hi:
                    d = abs(rs - cut)
                    if best_dist is None or d < best_dist:
                        best, best_dist = rs, d
            return best if best is not None else cut

        # ── Snap raw cut points to branch-run boundaries where safe ─────────
        # Cut points are the cumulative sums of `sizes` (exclusive of 0 and total).
        raw_cuts = []
        acc = 0
        for s in sizes[:-1]:
            acc += s
            raw_cuts.append(acc)

        adjusted_cuts: List[int] = []
        prev_cut = 0
        for ci, cut in enumerate(raw_cuts):
            # search window: the snapped cut must keep the left chunk within
            # [MIN, MAX] of the size budget, and not cross the previous
            # adjusted cut.
            lo = prev_cut + MIN_FAT_PER_FDT
            hi = min(prev_cut + MAX_FAT_PER_FDT, total)
            snapped = _nearest_run_start(cut, lo - 1, hi)  # lo-1 so lo itself is eligible
            left_size = snapped - prev_cut
            right_remaining = total - snapped
            right_ok = ((right_remaining >= MIN_FAT_PER_FDT or ci == len(raw_cuts) - 1)
                        and right_remaining <= MAX_FAT_PER_FDT)
            if MIN_FAT_PER_FDT <= left_size <= MAX_FAT_PER_FDT and right_ok:
                adjusted_cuts.append(snapped)
                prev_cut = snapped
            else:
                # Snapping within [MIN, MAX] would create an undersized or
                # oversized chunk — keep the original cut.  The branch run
                # straddling it stays split across the boundary (unavoidable
                # for branches that can't be re-homed without violating the
                # group-size limits).
                if cut not in run_starts:
                    _split_branch = branch_ids[cut - 1] if cut > 0 else None
                    logger.log(
                        f"Boundary-snap: cut at index {cut} could not be "
                        f"moved to a branch-run boundary (snapped candidate "
                        f"{snapped} would give left={left_size}, "
                        f"right={right_remaining}); branch '{_split_branch}' "
                        f"split across this cut.")
                adjusted_cuts.append(cut)
                prev_cut = cut

        sizes = []
        prev = 0
        for c in adjusted_cuts:
            sizes.append(c - prev)
            prev = c
        sizes.append(total - prev)
        sizes = [s for s in sizes if s > 0]

        def _anchor_distance(anchor_fat: FAT, candidate_fat: FAT) -> float:
            """Distance from an anchor FAT to a candidate FAT.

            [Fix 1] This was the fourth of the four disagreeing distance
            measures: along-road when both FATs shared a road, straight-line
            otherwise. Neither described the cable that would be built between
            them, so FDT_MAX_RADIUS was being enforced against a number that
            had no relationship to the constraint it exists to protect. It now
            resolves through _network_distance like everything else, which
            means the routing graph answers it whenever the oracle is live.

            Expect this to bind slightly harder than before: a network distance
            is never shorter than the straight line it replaces, so marginal
            groups that used to stay open will now close. That is the intended
            direction — the old measure was optimistic, and the optimism was
            paid for downstream in oversized box-to-box cables.

            Note on scope: FDT_MAX_RADIUS bounds each FAT's distance from the
            GROUP ANCHOR, which does not by itself bound the distance between
            two consecutive FATs in a cascade chain (that can reach twice the
            radius even in the Euclidean case). Chain hops are constrained
            directly downstream by _optimal_wing_order and
            _repair_wing_membership_by_swap; this check is only here to keep a
            group geographically coherent.
            """
            if dist_calc is None:
                return float('inf')

            anchor_pt = _b2b_endpoint(anchor_fat)
            candidate_pt = _b2b_endpoint(candidate_fat)
            if anchor_pt is None or candidate_pt is None:
                return float('inf')
            return _network_distance(
                anchor_pt,
                candidate_pt,
                road_a_id=anchor_fat.road_id,
                road_b_id=candidate_fat.road_id,
                topo=topo,
                dist_calc=dist_calc,
            )

        idx = 0
        # [Deferred fix] The oversized-chunk safety net below used to emit its
        # sub-chunks directly and `continue` past the FDT_MAX_RADIUS
        # enforcement loop, so any chunk larger than MAX_FAT_PER_FDT was split
        # purely by COUNT and received no geographic protection at all. Two
        # "Boundary-snap produced oversized chunk" lines appeared on the
        # reference run, so this path does execute on real data. Sub-chunks are
        # now fed back through the same enforcement loop as every other chunk.
        pending: List[Tuple[List[Tuple[FAT, int, int]], bool]] = []
        for i, size in enumerate(sizes):
            chunk = full[idx: idx + size]
            idx += size
            if not chunk:
                continue
            is_last = (i == len(sizes) - 1)

            if len(chunk) > MAX_FAT_PER_FDT:
                logger.log(
                    f"Boundary-snap produced oversized chunk "
                    f"({len(chunk)} > MAX {MAX_FAT_PER_FDT}); "
                    f"sub-splitting at MAX size, then applying "
                    f"FDT_MAX_RADIUS enforcement to each sub-chunk."
                )
                for j in range(0, len(chunk), MAX_FAT_PER_FDT):
                    sub = chunk[j:j + MAX_FAT_PER_FDT]
                    if not sub:
                        continue
                    sub_is_last = is_last and (j + MAX_FAT_PER_FDT >= len(chunk))
                    pending.append((sub, sub_is_last))
                continue

            pending.append((chunk, is_last))

        for chunk, is_last in pending:

            # Early-close when the next FAT is too far from the current group
            # anchor.  This keeps branch-heavy corridors from leaking into a
            # distant FDT group simply because the walk reached them later.
            grouped_entries: List[Tuple[FAT, int, int]] = []
            current_anchor: Optional[FAT] = None
            entry_idx = 0
            while entry_idx < len(chunk):
                entry = chunk[entry_idx]
                fat = entry[0]
                road_id = entry[1]
                branch_id = entry[2]
                is_injected = (branch_id != road_id)

                if is_injected:
                    branch_block: List[Tuple[FAT, int, int]] = []
                    while entry_idx < len(chunk):
                        block_entry = chunk[entry_idx]
                        if block_entry[2] != branch_id:
                            break
                        branch_block.append(block_entry)
                        entry_idx += 1

                    # [Bug #2 fix] Radius check is now UNCONDITIONAL — never
                    # gated by current group size. The old
                    # `len(grouped_entries) >= MIN_FAT_PER_FDT` gate meant the
                    # first several FATs added to every group got zero
                    # geographic protection at all, letting a single far-away
                    # branch get silently absorbed and producing exactly the
                    # oversized (389m/358m/350m) box-to-box cables reported.
                    # Geography and capacity are two different constraints and
                    # are now resolved in two different places: this function
                    # only protects FDT_MAX_RADIUS compactness (closing a
                    # group the moment it's violated, at ANY size, even 1);
                    # hitting MIN_FAT_PER_FDT is handled entirely downstream —
                    # first by the existing topology/geographic consolidation
                    # passes a few hundred lines below (both already capped at
                    # MAX_BOX_TO_BOX_DISTANCE), and finally by
                    # _rebalance_fdts_for_capacity() in the main pipeline.
                    if (current_anchor is not None
                            and _anchor_distance(current_anchor, branch_block[0][0]) > FDT_MAX_RADIUS):
                        distance_m = _anchor_distance(current_anchor, branch_block[0][0])
                        logger.log(
                            f"[FDT_BOUNDARY_ENFORCEMENT]: branch {branch_id} "
                            f"{distance_m:.1f}m from current anchor (exceeds "
                            f"FDT_MAX_RADIUS {FDT_MAX_RADIUS}m); closing current "
                            f"group ({len(grouped_entries)} FAT(s)) and starting "
                            f"new group with this branch"
                        )
                        grp_fats = [f for f, _, _ in grouped_entries]
                        grp_primary = grouped_entries[0][1]
                        # Always commit directly here — the walk continues
                        # immediately afterward with branch_block as the new
                        # group, so there is no unresolved "tail" to hand back
                        # to the parent corridor. [Important correctness note]
                        # the old is_last/min_size "return to parent" branch
                        # that used to sit here was UNREACHABLE dead code
                        # under the previous size-gated check (that gate
                        # guaranteed len(grp_fats) >= MIN_FAT_PER_FDT >=
                        # min_size whenever this branch fired, so the `else`
                        # never ran) — but simply deleting the size gate
                        # without also removing that dead branch would have
                        # made it reachable at small sizes, and taking it here
                        # would silently abandon every remaining entry in this
                        # chunk (branch_block and everything after it) without
                        # ever emitting or returning them. Unconditional
                        # commit is what's actually correct at a mid-walk
                        # close; "return to parent" stays reserved for the
                        # true end-of-chunk flush further below, which is the
                        # only point where nothing is left unprocessed.
                        result_groups.append((grp_fats, grp_primary))
                        _commit_group(grp_fats)

                        grouped_entries = list(branch_block)
                        current_anchor = branch_block[0][0]
                        continue

                    if len(branch_block) < MIN_FAT_PER_FDT:
                        logger.log(
                            f"WARNING [FDT_BRANCH_UNDERFILLED]: branch {branch_id} "
                            f"contains only {len(branch_block)} FAT(s); allowing standalone branch group"
                        )

                    grouped_entries.extend(branch_block)
                    if current_anchor is None:
                        current_anchor = branch_block[0][0]
                    continue

                if not grouped_entries:
                    grouped_entries.append(entry)
                    current_anchor = fat
                    entry_idx += 1
                    continue

                # [Bug #2 fix] Same unconditional-radius / always-commit
                # treatment as the branch-injection case above — see the
                # detailed comment there for why the old is_last/min_size
                # "return to parent" branch had to be replaced with an
                # unconditional commit rather than just deleting the size
                # gate on its own.
                if (current_anchor is not None
                        and _anchor_distance(current_anchor, fat) > FDT_MAX_RADIUS):
                    distance_m = _anchor_distance(current_anchor, fat)
                    logger.log(
                        f"[FDT_BOUNDARY_ENFORCEMENT]: {fat.name} is "
                        f"{distance_m:.0f}m from current group anchor (exceeds "
                        f"FDT_MAX_RADIUS {FDT_MAX_RADIUS}m); closing current "
                        f"group ({len(grouped_entries)} FAT(s)) and starting "
                        f"new group"
                    )
                    grp_fats = [f for f, _, _ in grouped_entries]
                    grp_primary = grouped_entries[0][1]
                    result_groups.append((grp_fats, grp_primary))
                    _commit_group(grp_fats)

                    grouped_entries = [entry]
                    current_anchor = fat
                else:
                    grouped_entries.append(entry)

                entry_idx += 1

            if grouped_entries:
                grp_fats = [f for f, _, _ in grouped_entries]
                grp_primary = grouped_entries[0][1]
                min_size = MIN_FAT_PER_FDT - 1 if any(bool(e[1]) for e in grouped_entries) else MIN_FAT_PER_FDT
                if not is_last or len(grp_fats) >= min_size:
                    result_groups.append((grp_fats, grp_primary))
                    _commit_group(grp_fats)
                else:
                    return (grp_fats, grp_primary)
        return None

    # ── 4. Walk spanning tree leaves → root ───────────────────────────────
    # Reverse BFS order = leaves first, root last.  Each road processes its
    # own FATs (merged with any dead-end injections) plus overflow received
    # from child roads, applies look-ahead optimal sizing, emits valid groups,
    # and passes any unavoidable remainder up to its parent road.
    for rid in reversed(process_order):
        own_fats = fats_by_road.get(rid, [])
        injections = dead_end_inject.get(rid, [])

        # ENHANCEMENT: overflow from child roads is merged at the geographic junction
        # position rather than blindly prepended.  This prevents overflow FATs from
        # a child road that connects near the END of the parent road from appearing
        # inside the FIRST FDT group (start of parent road), which is the root cause
        # of boundary invasion between adjacent FDT groups.
        ov_injections = overflow_inject.get(rid, [])
        all_injections = injections + ov_injections

        if all_injections:
            max_co = max((f.cascade_order for f in own_fats), default=0)
            # Avoid division by zero when own_fats is empty (pure overflow road)
            _norm_denom = max_co if max_co > 0 else 1000
            pos_list_r: List[Tuple[float, bool, FAT, int]] = []
            for fat in own_fats:
                norm = fat.cascade_order / _norm_denom
                pos_list_r.append((norm, False, fat, rid))

            # ── FIX B/C: resolve junction point on parent geometry so each
            # branch's FATs cascade junction-nearest-first, and give every
            # injection atom a unique epsilon so (i) intra-branch order is
            # deterministic regardless of OSM digitisation direction, and
            # (ii) two branches meeting the parent road at the same node
            # never interleave inside _walk_fat_seq's boundary-snap window.
            _parent_road = roads.get(rid) if roads else None
            _parent_geom = (_parent_road.geometry
                            if _parent_road is not None
                            and not _parent_road.geometry.isEmpty()
                            else None)
            _parent_len = _parent_geom.length() if _parent_geom is not None else 0.0

            _eps_per_fat    = 1e-6   # ordering within one branch
            _eps_per_branch = 1e-4   # separation between branches at same junction
            _branches_at_pos: Dict[float, int] = {}

            for inj in all_injections:
                inj_pos, inj_fats, inj_src_rid = inj

                # Resolve the physical junction point on the parent road so we
                # can order branch FATs by distance-to-junction (junction-nearest
                # sits next to the parent-road FAT that shares the cascade with it).
                _junc_pt = None
                if _parent_geom is not None and _parent_len > 0:
                    _g = _parent_geom.interpolate(inj_pos * _parent_len)
                    if _g is not None and not _g.isEmpty():
                        try:
                            _junc_pt = _g.asPoint()
                        except Exception:
                            _junc_pt = None

                if _junc_pt is not None:
                    inj_fats_sorted = sorted(
                        inj_fats,
                        key=lambda f, _jp=_junc_pt: (f.geometry.x() - _jp.x()) ** 2
                                                  + (f.geometry.y() - _jp.y()) ** 2,
                    )
                else:
                    inj_fats_sorted = list(inj_fats)

                # Per-junction branch counter → disjoint epsilon range so two
                # branches meeting at the same node never mix.
                _key = round(inj_pos, 6)
                _bidx = _branches_at_pos.get(_key, 0)
                _branches_at_pos[_key] = _bidx + 1
                _base = inj_pos + _bidx * _eps_per_branch

                for k, fat in enumerate(inj_fats_sorted):
                    pos_list_r.append(
                        (_base + (k + 1) * _eps_per_fat, True, fat, inj_src_rid)
                    )

            pos_list_r.sort(key=lambda x: (x[0], x[1]))
            own_seq: List[Tuple[FAT, int, int]] = [
                (fat, rid, branch_id) for _, _, fat, branch_id in pos_list_r
            ]
        else:
            own_seq = [(fat, rid, rid) for fat in own_fats]

        prepend_ov = road_overflow.get(rid, [])
        if not own_seq and not prepend_ov:
            continue

        remainder = _walk_fat_seq(own_seq, prepend_ov if prepend_ov else None)

        if remainder is not None:
            rem_fats, rem_primary = remainder
            parent = parent_of.get(rid)
            if parent is not None:
                # ENHANCEMENT: route overflow into overflow_inject (position-aware)
                # when the junction shared between rid and parent is discoverable.
                # Falls back to road_overflow (blind prepend) when topology is absent.
                _routed_via_pos = False
                if roads and topo and topo._nodes:
                    _sn_c, _en_c = road_nodes.get(rid, (None, None))
                    _sn_p, _en_p = road_nodes.get(parent, (None, None))
                    if _sn_c is not None and _sn_p is not None:
                        _shared = None
                        if _sn_c in (_sn_p, _en_p):
                            _shared = _sn_c
                        elif _en_c in (_sn_p, _en_p):
                            _shared = _en_c
                        if _shared is not None and _shared in topo._nodes:
                            _jpt = topo._nodes[_shared]['point']
                            _prd = roads.get(parent)
                            if _prd and not _prd.geometry.isEmpty():
                                _pos = _junction_pos(_jpt, _prd)
                                overflow_inject[parent].append((_pos, rem_fats, rid))
                                _routed_via_pos = True
                if not _routed_via_pos:
                    road_overflow[parent].extend(
                        (fat, rem_primary, rid) for fat in rem_fats)
                logger.log(
                    f"Road {rid}: {len(rem_fats)} remainder FATs "
                    f"→ parent road {parent}")
            else:
                logger.log(
                    f"Road {rid}: {len(rem_fats)} remainder FATs "
                    f"(root) — deferred to combination pass")
                result_groups.append((rem_fats, rem_primary))

    # ── Orphaned dead-end FATs ─────────────────────────────────────────────
    for nid, fat_list in orphan_pending.items():
        if not fat_list:
            continue
        p_rid = fat_list[0].road_id
        logger.log(
            f"Junction {nid}: {len(fat_list)} orphaned dead-end FATs "
            f"— deferred to combination pass")
        # Use optimal sizing so orphan groups also minimise underfilled chunks
        oq, or_ = divmod(len(fat_list), MAX_FAT_PER_FDT)
        if or_ == 0:
            o_sizes = [MAX_FAT_PER_FDT] * oq
        elif or_ >= MIN_FAT_PER_FDT:
            o_sizes = [MAX_FAT_PER_FDT] * oq + [or_]
        else:
            o_def = MIN_FAT_PER_FDT - or_
            if o_def <= oq:
                o_sizes = ([MAX_FAT_PER_FDT] * (oq - o_def)
                           + [MIN_FAT_PER_FDT] * (o_def + 1))
            else:
                o_sizes = [MAX_FAT_PER_FDT] * oq + ([or_] if or_ > 0 else [])
        oidx = 0
        for o_size in o_sizes:
            chunk = fat_list[oidx: oidx + o_size]
            oidx += o_size
            if chunk:
                result_groups.append((chunk, p_rid))

    # ── Post-pass: combine underfilled groups via junction topology ────────
    # BFS-finds connected components of underfilled groups, pools their FATs,
    # and re-walks at MAX so only a truly isolated terminal group stays small.

    # Index: road_id → result_groups index (first group that owns that road)
    road_to_group: Dict[int, int] = {}
    for gi, (gfats, _) in enumerate(result_groups):
        for fat in gfats:
            road_to_group.setdefault(fat.road_id, gi)

    def _adj_group_ids(gi: int) -> Set[int]:
        gfats, prid = result_groups[gi]
        # Include both individual FAT road_ids AND the group's primary_road_id.
        # FATs injected from dead-ends keep their original (dead-end) road_id, so
        # checking only fat.road_id can miss the parent road's junctions entirely.
        check_rids: Set[int] = {fat.road_id for fat in gfats}
        if prid is not None:
            check_rids.add(prid)
        adj: Set[int] = set()
        for rid in check_rids:
            sn, en = road_nodes.get(rid, (None, None))
            if sn is None:
                continue
            for nid in (sn, en):
                for nb_rid in junction_roads.get(nid, set()):
                    other_gi = road_to_group.get(nb_rid)
                    if other_gi is not None and other_gi != gi:
                        # ENHANCEMENT: never combine groups across the dual-carriageway
                        # median.  The neighbour road is across the median when its
                        # dual_cw_partner is one of the roads in the current group.
                        _nb_r = roads.get(nb_rid) if roads else None
                        if _nb_r and _nb_r.dual_cw_partner in check_rids:
                            continue
                        adj.add(other_gi)
        return adj

    underfilled_gis: Set[int] = {
        gi for gi, (g, _) in enumerate(result_groups)
        if g and len(g) < MIN_FAT_PER_FDT
    }

    # ENHANCEMENT: geographic centroid of each group — used to prevent the BFS
    # from merging underfilled groups that are topologically adjacent but
    # geographically far apart.  Without this guard, two underfilled groups on
    # roads that happen to share a distant junction are merged, then re-split in
    # a way that interleaves FATs from geographically separate areas (boundary
    # invasion).  We allow merging only when the group centroids are within
    # MAX_BOX_TO_BOX_DISTANCE of each other.
    def _group_centroid(gi: int) -> Tuple[float, float]:
        fats = result_groups[gi][0]
        if not fats:
            return (0.0, 0.0)
        return (sum(f.geometry.x() for f in fats) / len(fats),
                sum(f.geometry.y() for f in fats) / len(fats))

    def _dual_cw_linked(gi1: int, gi2: int) -> bool:
        """True when any road in gi1 is the dual-carriageway partner of any road in gi2."""
        if not roads:
            return False
        rids2 = {fat.road_id for fat in result_groups[gi2][0]}
        for fat in result_groups[gi1][0]:
            r = roads.get(fat.road_id)
            if r and r.dual_cw_partner in rids2:
                return True
        return False

    _MAX_COMBINE_DIST_SQ = rc.MAX_BOX_TO_BOX_DISTANCE * rc.MAX_BOX_TO_BOX_DISTANCE

    visited_gis: Set[int] = set()
    consumed_gis: Set[int] = set()
    new_groups: List[Tuple[List[FAT], int]] = []

    for start in sorted(underfilled_gis):
        if start in visited_gis:
            continue
        component: List[int] = []
        stack = [start]
        while stack:
            gi = stack.pop()
            if gi in visited_gis:
                continue
            visited_gis.add(gi)
            if gi in underfilled_gis:
                component.append(gi)
                _c_gi = _group_centroid(gi)
                for adj_gi in _adj_group_ids(gi):
                    if adj_gi in underfilled_gis and adj_gi not in visited_gis:
                        _c_adj = _group_centroid(adj_gi)
                        _dx = _c_gi[0] - _c_adj[0]
                        _dy = _c_gi[1] - _c_adj[1]
                        if _dx * _dx + _dy * _dy <= _MAX_COMBINE_DIST_SQ:
                            stack.append(adj_gi)
        if not component:
            continue
        pool: List[FAT] = []
        p_rid = result_groups[component[0]][1]
        for gi in component:
            pool.extend(result_groups[gi][0])
            consumed_gis.add(gi)
        # ENHANCEMENT: sort by (road_id, cascade_order) so FATs from the same
        # road stay together.  The original _fat_sort_key sorts by cascade_order
        # first — since cascade_order is road-local (not global), FATs from two
        # different roads with numerically similar cascade_orders would interleave,
        # creating groups that span geographically separate locations.
        pool.sort(key=lambda f: (f.road_id, f.cascade_order))
        # Same authoritative sizing as _walk_fat_seq (spec §2/§9) — no
        # duplicated MAX-1==MIN assumption. [Cost-reduction fix] footprint-
        # aware K selection here too — this pass merges fragments across
        # multiple roads/branches, exactly where a naive lowest-K choice
        # is most likely to force geographically distant FATs together.
        p_sizes, _p_exact = _footprint_aware_partition(
            pool, len(pool), MIN_FAT_PER_FDT, MAX_FAT_PER_FDT
        )
        pidx = 0
        for p_size in p_sizes:
            chunk = pool[pidx: pidx + p_size]
            pidx += p_size
            if chunk:
                new_groups.append((chunk, p_rid))

    result_groups = (
        [(g, p) for gi, (g, p) in enumerate(result_groups)
         if gi not in consumed_gis and g]
        + new_groups
    )

    # ── Second combination pass: pure geographic proximity (topology-independent) ─
    # The first BFS pass only merges groups that are topologically connected via
    # road junctions.  When groups sit on roads with OSM topology gaps, isolated
    # road segments, or roads not present in the topology graph, they survive the
    # first pass as separate underfilled groups even though they are physically
    # within box-to-box cable distance of each other.
    #
    # This pass uses a pure DFS over centroid-to-centroid distance
    # (≤ MAX_BOX_TO_BOX_DISTANCE) — no topology required.  It recalibrates the
    # group count so that the result is as close to MIN_FAT_PER_FDT as possible,
    # consistent with the maximum cable-reach constraint that determines which FATs
    # a single FDT can realistically serve.
    _still_underfilled: List[int] = [
        gi for gi, (g, _) in enumerate(result_groups)
        if g and len(g) < MIN_FAT_PER_FDT
    ]

    if _still_underfilled:
        _geo_visited: Set[int] = set()
        _geo_consumed: Set[int] = set()
        _geo_new_groups: List[Tuple[List[FAT], int]] = []

        for _start_gi in _still_underfilled:
            if _start_gi in _geo_visited:
                continue

            # DFS over geographic proximity — chain groups within cable reach.
            _geo_comp: List[int] = []
            _geo_stack: List[int] = [_start_gi]
            while _geo_stack:
                _gi = _geo_stack.pop()
                if _gi in _geo_visited:
                    continue
                _geo_visited.add(_gi)
                _geo_comp.append(_gi)
                _cx, _cy = _group_centroid(_gi)
                for _other_gi in _still_underfilled:
                    if _other_gi in _geo_visited:
                        continue
                    # ENHANCEMENT: never combine groups across the dual-carriageway
                    # median — even if they are within cable-reach distance.
                    if _dual_cw_linked(_gi, _other_gi):
                        continue
                    _ox, _oy = _group_centroid(_other_gi)
                    _ddx = _cx - _ox
                    _ddy = _cy - _oy
                    if _ddx * _ddx + _ddy * _ddy <= _MAX_COMBINE_DIST_SQ:
                        _geo_stack.append(_other_gi)

            if len(_geo_comp) <= 1:
                continue  # single isolated group — nothing to combine with

            _geo_pool: List[FAT] = []
            _geo_p_rid = result_groups[_geo_comp[0]][1]
            for _gi2 in _geo_comp:
                _geo_pool.extend(result_groups[_gi2][0])
                _geo_consumed.add(_gi2)

            _geo_pool.sort(key=lambda f: (f.road_id, f.cascade_order))

            # Same authoritative sizing as _walk_fat_seq (spec §2/§9) — no
            # duplicated MAX-1==MIN assumption. [Cost-reduction fix]
            # footprint-aware K selection — confirmed directly against a
            # real QGIS run that THIS specific pass is a major FDT-
            # formation path (102 underfilled fragments merged into 14
            # FDTs in one run), making it one of the highest-leverage
            # places for a naive lowest-K choice to force distant FATs
            # together.
            _gn = len(_geo_pool)
            _g_sizes, _g_exact = _footprint_aware_partition(
                _geo_pool, _gn, MIN_FAT_PER_FDT, MAX_FAT_PER_FDT
            )

            _gidx = 0
            for _g_size in _g_sizes:
                _chunk = _geo_pool[_gidx: _gidx + _g_size]
                _gidx += _g_size
                if _chunk:
                    _geo_new_groups.append((_chunk, _geo_p_rid))

            logger.log(
                f"Geographic recalibration: merged {len(_geo_comp)} underfilled groups "
                f"({_gn} FATs) → {len(_g_sizes)} group(s)")

        if _geo_consumed:
            result_groups = (
                [(g, p) for gi, (g, p) in enumerate(result_groups)
                 if gi not in _geo_consumed and g]
                + _geo_new_groups
            )

    # Log any still-underfilled groups as truly isolated — no combinable neighbour
    for g, p in result_groups:
        if g and len(g) < MIN_FAT_PER_FDT:
            logger.log(
                f"Road {p}: truly isolated — {len(g)} FATs (min {MIN_FAT_PER_FDT})")
            logger.log(
                f"WARNING [FDT_UNDERFILLED]: Road {p} truly isolated: "
                f"{len(g)} FATs (min {MIN_FAT_PER_FDT})")

    # ── Dual-PON pairing: combine two Single-PON-sized groups into one box ──
    # Everything above (Steps 0-7) just ran at the Single-PON scale (see the
    # _grouping_profile shadow at the top of this function), so every group
    # in result_groups is already a tight, local, already-validated 7-8 FAT
    # cluster — exactly what a real Single-PON run would have produced.
    #
    # For Dual-PON, one physical FDT box needs two such clusters (wings A/B
    # from one, C/D from the other). Pair them here, but ONLY when they
    # genuinely sit inside one boundary: sharing a road junction, or — OSM
    # topology-gap fallback, same rationale as the geographic-recalibration
    # pass above — within a single MAX_BOX_TO_BOX_DISTANCE hop of each
    # other. This is deliberately the same single-hop reach Single-PON
    # already trusts everywhere else in this module, never the doubled
    # MAX_BOX_TO_BOX_DISTANCE*2 reach (or multi-hop chaining) that produced
    # the reckless, cross-territory borrowing this replaces.
    #
    # A group with no boundary-eligible partner (a genuinely isolated
    # pocket) is left unpaired, as its own small standalone group — the
    # existing downstream _rebalance_fdts_for_capacity() rescue path
    # (bounded search, last-resort pooling, single global-final-exception
    # flag) already handles that rare case correctly; this step does not
    # need to force a match.
    def _pair_pon_groups_into_dual_fdts(
        groups: List[Tuple[List['FAT'], int]],
    ) -> List[Tuple[List['FAT'], int]]:
        if profile.pon_count != 2 or len(groups) < 2:
            return groups

        n = len(groups)
        max_size = profile.max_fat_per_fdt

        def _centroid(gi: int) -> Tuple[float, float]:
            gfats = groups[gi][0]
            return (sum(f.geometry.x() for f in gfats) / len(gfats),
                    sum(f.geometry.y() for f in gfats) / len(gfats))

        def _road_ids(gi: int) -> Set[int]:
            gfats, prid = groups[gi]
            rids = {f.road_id for f in gfats}
            if prid is not None:
                rids.add(prid)
            return rids

        group_rids = [_road_ids(gi) for gi in range(n)]
        group_centroids = [_centroid(gi) for gi in range(n)]

        def _shares_junction(i: int, j: int) -> bool:
            for rid in group_rids[i]:
                sn, en = road_nodes.get(rid, (None, None))
                if sn is None:
                    continue
                for nid in (sn, en):
                    if group_rids[j] & junction_roads.get(nid, set()):
                        return True
            return False

        def _hop_dist(i: int, j: int) -> float:
            cx1, cy1 = group_centroids[i]
            cx2, cy2 = group_centroids[j]
            if dist_calc is not None:
                return dist_calc.distance_points(
                    QgsPointXY(cx1, cy1), QgsPointXY(cx2, cy2))
            return math.sqrt((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2)

        order = sorted(range(n), key=lambda i: len(groups[i][0]))
        paired: Set[int] = set()
        result: List[Tuple[List['FAT'], int]] = []

        for i in order:
            if i in paired:
                continue
            paired.add(i)

            best_j, best_dist, best_topo = None, float('inf'), False
            for j in range(n):
                if j == i or j in paired:
                    continue
                if len(groups[i][0]) + len(groups[j][0]) > max_size:
                    continue
                topo_adj = _shares_junction(i, j)
                dist = _hop_dist(i, j)
                if not topo_adj and dist > rc.MAX_BOX_TO_BOX_DISTANCE:
                    continue
                if dist < best_dist:
                    best_j, best_dist, best_topo = j, dist, topo_adj

            if best_j is not None:
                paired.add(best_j)
                fats_i, rid_i = groups[i]
                fats_j, rid_j = groups[best_j]
                combined = fats_i + fats_j
                result.append((combined, rid_i))
                logger.log(
                    f"Dual-PON pairing: road {rid_i} group ({len(fats_i)} FATs) "
                    f"+ road {rid_j} group ({len(fats_j)} FATs) -> "
                    f"{len(combined)} FATs total "
                    f"(boundary={'junction-adjacent' if best_topo else f'{best_dist:.0f}m hop'})"
                )
            else:
                result.append(groups[i])
                logger.log(
                    f"Dual-PON pairing: road {groups[i][1]} group "
                    f"({len(groups[i][0])} FATs) has no boundary-eligible "
                    f"partner — left as its own standalone group."
                )

        return result

    result_groups = _pair_pon_groups_into_dual_fdts(result_groups)

    # Restore the real profile ceiling for Step 8 and the two-way validation
    # below — grouping above intentionally ran at the Single-PON scale (see
    # the _grouping_profile comment near the top of this function).
    MAX_FAT_PER_FDT = profile.max_fat_per_fdt
    MIN_FAT_PER_FDT = profile.min_fat_per_fdt
    MAX_FDT_CAPACITY = profile.max_fdt_capacity

    # ── 8. Build FDT objects ───────────────────────────────────────────────
    fdts: List[FDT] = []
    for counter, (group_fats, primary_road_id) in enumerate(result_groups, start=1):
        if not group_fats:
            continue
        if len(group_fats) > MAX_FAT_PER_FDT:
            raise ValidationError(
                f"Group has {len(group_fats)} FATs, "
                f"exceeds MAX_FAT_PER_FDT ({MAX_FAT_PER_FDT})")
        fdt = _make_fdt(group_fats, counter, primary_road_id=primary_road_id, roads=roads)
        if fdt.total_customers > MAX_FDT_CAPACITY:
            raise ValidationError(
                f"{fdt.name} has {fdt.total_customers} customers, "
                f"exceeds {MAX_FDT_CAPACITY}")
        _apply_fat_traceability(
            fdt,
            dist_calc=dist_calc,
            topo=topo,
            roads=roads,
        )
        fdts.append(fdt)
        logger.log(
            f"Road {primary_road_id} -> {fdt.name} "
            f"({fdt.total_fat} FAT, {fdt.total_customers} customers)")

    # ── Two-way validation ────────────────────────────────────────────────
    # Confirm FAT count is conserved and actual FDT count sits within the
    # theoretically valid range:
    #   min_fdts = floor(total_fats / MAX)  — if every FDT is fully packed
    #   max_fdts = ceil (total_fats / MIN)  — if every FDT carries MIN FATs
    total_fat_input = len(fats)
    total_fat_output = sum(fdt.total_fat for fdt in fdts)
    if total_fat_input != total_fat_output:
        logger.log(
            f"CRITICAL: FAT count mismatch — input {total_fat_input}, "
            f"output {total_fat_output}")
        logger.log(
            f"WARNING [FDT_FAT_MISMATCH]: FAT count mismatch: "
            f"input {total_fat_input} → output {total_fat_output}")

        # DIAGNOSTIC: identify the specific FAT(s) responsible for the
        # mismatch by name, rather than just the aggregate counts.  Compares
        # multisets of FAT.name between input and emitted FDT groups so
        # missing FATs (dropped during boundary-snap/walk) and duplicated
        # FATs (double-committed) are both surfaced.
        input_names = Counter(f.name for f in fats)
        output_names = Counter(
            f.name for fdt in fdts for f in fdt.fats)
        missing = input_names - output_names
        duplicated = output_names - input_names
        if missing:
            for name, cnt in missing.items():
                logger.log(f"  MISSING FAT: {name} (x{cnt}) — present in "
                           f"input but absent from all FDT groups")
                logger.log(f"  WARNING [FDT_FAT_MISSING]: {name} dropped during FDT generation")
        if duplicated:
            for name, cnt in duplicated.items():
                logger.log(f"  DUPLICATED FAT: {name} (x{cnt}) — appears in "
                           f"FDT groups more times than in input")
                logger.log(f"  WARNING [FDT_FAT_DUPLICATED]: {name} appears in {cnt} extra FDT group(s)")
        if not missing and not duplicated:
            logger.log("  (count differs but no name-level diff found — "
                       "check for FATs with duplicate .name values)")

    if total_fat_input > 0:
        min_fdts = total_fat_input // MAX_FAT_PER_FDT or 1
        max_fdts = -(-total_fat_input // MIN_FAT_PER_FDT)  # ceiling division
        actual_fdt_count = len(fdts)
        underfilled_count = sum(1 for fdt in fdts if fdt.total_fat < MIN_FAT_PER_FDT)
        logger.log(
            f"Two-way check: {total_fat_input} FATs → valid FDT range "
            f"[{min_fdts}, {max_fdts}], actual {actual_fdt_count} FDTs, "
            f"{underfilled_count} underfilled (truly isolated)")
        if not (min_fdts <= actual_fdt_count <= max_fdts):
            logger.log(
                f"WARNING [FDT_COUNT_OUT_OF_RANGE]: expected {min_fdts}–{max_fdts} "
                f"FDTs for {total_fat_input} FATs, got {actual_fdt_count}")

    logger.end_module("FDT Generation")
    logger.log(f"Generated {len(fdts)} FDTs")
    return fdts


def _apply_fat_traceability(fdt: FDT,
                            dist_calc: Optional['DistanceCalculator'] = None,
                            topo: Optional['RoadTopologyEngine'] = None,
                            roads: Optional[Dict[int, 'RoadSegment']] = None) -> None:
    """Set per-FAT traceability fields for the FDT that owns this group."""
    if not fdt or not fdt.fats:
        return

    fdt_anchor = fdt.snapped_geometry or fdt.geometry
    for fat in fdt.fats:
        fat.physical_fdt = fdt.name
        fat.logical_fdt = fdt.name
        allocation_hint = getattr(fat, '_allocation_trace', None)
        if allocation_hint in {"borrowed", "absorbed"}:
            fat.allocation_type = allocation_hint
        elif getattr(fat, '_borrowed_from_parent', False):
            fat.allocation_type = "borrowed"
        else:
            fat.allocation_type = "native"

        if fdt_anchor and fat.geometry is not None:
            fat.network_dist_to_fdt = _network_distance(
                fdt_anchor,
                fat.snapped_geometry or fat.geometry,
                road_a_id=fat.road_id,
                road_b_id=fdt.primary_road_id,
                topo=topo,
                dist_calc=dist_calc,
            )
        else:
            fat.network_dist_to_fdt = 0.0


def _make_fdt(group_fats: List[FAT], counter: int,
              primary_road_id: Optional[int] = None,
              roads: Optional[Dict] = None) -> FDT:
    """Create a single FDT object from a FAT group.

    Ensures downstream modules always receive:
    - fdt.fats populated with the member FAT objects
    - fdt.zone_geometry as a polygon covering the FDT service cluster
    """
    if not group_fats:
        raise ValidationError("Cannot create FDT from an empty FAT group")

    # FDT point: centroid of PRIMARY-road FATs only, then snapped to that road.
    # Using all FATs (including borrowed cross-road neighbours) biases the
    # centroid toward side streets and produces a wrong snap position even
    # after nearestPoint — the projected point ends up at the wrong end of
    # the primary road.
    _primary_anchor = ([f for f in group_fats if f.road_id == primary_road_id]
                       if primary_road_id is not None else [])
    anchor_fats = _primary_anchor if _primary_anchor else group_fats

    cx = sum(f.geometry.x() for f in anchor_fats) / len(anchor_fats)
    cy = sum(f.geometry.y() for f in anchor_fats) / len(anchor_fats)
    centroid = QgsPointXY(cx, cy)
    fdt_point = centroid  # default — overwritten below if road snap succeeds

    if primary_road_id is not None and roads:
        road = roads.get(primary_road_id)
        if road and road.geometry and not road.geometry.isEmpty():
            snapped = road.geometry.nearestPoint(QgsGeometry.fromPointXY(centroid))
            if snapped and not snapped.isEmpty():
                fdt_point = snapped.asPoint()

    total_customers = sum(f.total_customers for f in group_fats)
    # Wing assignment is applied later per FDT by assign_wings_per_fdt.
    wing_a_count = 0
    wing_b_count = 0

    # Build a robust polygon zone around the FAT cluster.
    # We use convex hull + generous buffer so pole snapping and route validation
    # can work with sparse groups (1-2 FATs) and elongated alignments.
    pts = [QgsPointXY(f.geometry.x(), f.geometry.y()) for f in group_fats]
    pts.append(fdt_point)
    zone_geom = QgsGeometry.fromMultiPointXY(pts).convexHull().buffer(rc.MAX_BOX_TO_BOX_DISTANCE, 12)
    if not zone_geom or zone_geom.isEmpty():
        zone_geom = QgsGeometry.fromPointXY(fdt_point).buffer(rc.MAX_BOX_TO_BOX_DISTANCE, 12)

    fdt_serial = f"{counter:04d}"
    fdt_code = _project_tag("FDT", fdt_serial)
    for fat in group_fats:
        fat.physical_fdt = fdt_code
    return FDT(
        name=fdt_code,
        geometry=fdt_point,
        total_customers=total_customers,
        total_fat=len(group_fats),
        wing_a_count=wing_a_count,
        wing_b_count=wing_b_count,
        fdt_code=fdt_code,
        fdt_serial=fdt_serial,
        fats=list(group_fats),
        zone_geometry=zone_geom,
        primary_road_id=primary_road_id,
    )
