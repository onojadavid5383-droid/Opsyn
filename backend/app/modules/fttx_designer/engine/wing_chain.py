"""Verbatim port of the wing-chain cascade-ordering math and the repair move
ledger from ``FTTx Designer — dual PON integrated.py``: the repair move
ledger (``reset_repair_move_ledger``, ``_repair_budget_left``,
``_record_repair_move``), ``_ordered_wing_fats``, ``_wing_chain_violations``,
``_wing_chain_objective``, ``_optimal_wing_order``, ``_wing_chain_is_valid``,
``_wing_chain_cost``, ``_apply_explicit_wing_order``,
``_best_valid_wing_insertion``, ``_current_wings_without``.

Split into its own module because it is shared by ``wing_assignment.py``
(``create_fdt_wing_cascades`` calls ``_optimal_wing_order``/
``_wing_chain_violations``) and by ``repair/wing_repair.py`` (a later
sub-phase — ``_repair_wing_membership_by_swap``/``_repair_wing_chain_continuity``
call ``_apply_explicit_wing_order``/``_wing_chain_cost``/
``_best_valid_wing_insertion``), so it must not depend on either.

Note: ``DROP_LENGTH_TOLERANCE`` is one of the 8 tunables the pipeline
overrides per-run (see runtime_config.py's docstring) — read through
``runtime_config.DROP_LENGTH_TOLERANCE``.
"""

from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Tuple

from . import runtime_config as rc
from .config import MAX_MOVES_PER_FAT, PON_WINGS, CapacityProfile, PONArchitecture, CAPACITY_PROFILES
from .distance_oracle import _network_distance
from .domain import FAT, FDT, RoadSegment
from .errors import ValidationError
from .fdt_generation import _apply_fat_traceability
from .hop_limits import _b2b_endpoint, b2b_hop_limit
from .cascade import _project_tag
from .homepass_assignment import _parse_homepass_value
from .spatial_utils import DistanceCalculator
from .topology import RoadTopologyEngine

# ── Repair move ledger [Fix 7] ───────────────────────────────────────────────
# Relay repair, chain repair and wing-swap repair all move FATs, and on the
# reference run they were undoing each other: FAT-09A-02 was swapped
# FDT-09 <-> FDT-19 twice inside one pass and then moved directly, while
# FAT-21A-02 appeared in 28 separate repair actions. Every pass reported
# stable=False and the loop exhausted its budget. A shared budget makes the
# churn terminate.
_REPAIR_MOVE_LEDGER: Dict[str, int] = {}


def reset_repair_move_ledger() -> None:
    _REPAIR_MOVE_LEDGER.clear()


def _repair_budget_left(fat: 'FAT') -> bool:
    return _REPAIR_MOVE_LEDGER.get(getattr(fat, 'name', ''), 0) < MAX_MOVES_PER_FAT


def _record_repair_move(*fats) -> None:
    for fat in fats:
        name = getattr(fat, 'name', '')
        if name:
            _REPAIR_MOVE_LEDGER[name] = _REPAIR_MOVE_LEDGER.get(name, 0) + 1


def _fat_sequence_number(fat: FAT) -> int:
    try:
        return int(getattr(fat, 'fat_sequence', '') or 999)
    except Exception:
        return 999


def _ordered_wing_fats(fdt: FDT, wing_label: str) -> List[FAT]:
    """Return one wing in its current cascade order, preserving list order as fallback."""
    order_index = {id(fat): idx for idx, fat in enumerate(fdt.fats)}
    return sorted(
        [fat for fat in fdt.fats if fat.wing == wing_label],
        key=lambda fat: (_fat_sequence_number(fat), order_index.get(id(fat), 9999)),
    )


def _wing_chain_violations(
    fdt: FDT,
    wing_fats: List[FAT],
    dist_calc: Optional['DistanceCalculator'] = None,
    topo: Optional['RoadTopologyEngine'] = None,
) -> List[Tuple[int, FAT, float, float, str]]:
    """Return FATs whose cascade hop breaks the physical cable-length rule.

    Each item is ``(index, fat, distance, limit, previous_device_name)``.

    [Fix 4] Limits come from b2b_hop_limit() so this agrees with the routing
    warning and the hard validation gate by construction.
    [Fix 5] Endpoints come from _b2b_endpoint() so the distance measured here
    is the same run the cable router will build.
    """
    violations: List[Tuple[int, FAT, float, float, str]] = []
    if not wing_fats:
        return violations

    fdt_pt = _b2b_endpoint(fdt)
    if not fdt_pt:
        return violations

    first = wing_fats[0]
    first_pt = _b2b_endpoint(first)
    first_limit = b2b_hop_limit(0)
    first_dist = _network_distance(
        fdt_pt,
        first_pt,
        road_a_id=fdt.primary_road_id,
        road_b_id=first.road_id,
        topo=topo,
        dist_calc=dist_calc,
    )
    if first_dist > first_limit + rc.DROP_LENGTH_TOLERANCE:
        violations.append((0, first, first_dist, first_limit, fdt.name))

    for idx in range(1, len(wing_fats)):
        prev_fat = wing_fats[idx - 1]
        fat = wing_fats[idx]
        prev_pt = _b2b_endpoint(prev_fat)
        fat_pt = _b2b_endpoint(fat)
        hop_limit = b2b_hop_limit(idx)
        hop_dist = _network_distance(
            prev_pt,
            fat_pt,
            road_a_id=prev_fat.road_id,
            road_b_id=fat.road_id,
            topo=topo,
            dist_calc=dist_calc,
        )
        if hop_dist > hop_limit + rc.DROP_LENGTH_TOLERANCE:
            violations.append((idx, fat, hop_dist, hop_limit, prev_fat.name))
    return violations


def _wing_chain_objective(
    fdt: FDT,
    wing_fats: List[FAT],
    dist_calc: Optional['DistanceCalculator'] = None,
    topo: Optional['RoadTopologyEngine'] = None,
) -> Tuple[float, float]:
    """[Fix 2] Objective for choosing a wing's cascade order.

    NOTE the name: a pre-existing ``_wing_chain_cost`` further down this file
    returns a bare total length and is still used by the wing-split search.
    This one returns a (worst_excess, total) tuple. They must not share a name —
    the later definition would shadow the earlier one and every caller here
    would silently get the wrong objective, or crash unpacking a float.

    Returns ``(worst_excess, total_length)``:
      worst_excess  largest amount by which any single hop overshoots its own
                    limit, 0.0 if the chain is fully compliant. This is the
                    primary term because the validation gate is a per-hop
                    maximum, not a sum.
      total_length  total chain length, the tiebreaker among compliant orders
                    so we do not pay extra cable for no reason.
    """
    if not wing_fats:
        return 0.0, 0.0

    fdt_pt = _b2b_endpoint(fdt)
    if not fdt_pt:
        return float('inf'), float('inf')

    worst_excess = 0.0
    total = 0.0
    prev_pt = fdt_pt
    prev_road = fdt.primary_road_id
    for idx, fat in enumerate(wing_fats):
        fat_pt = _b2b_endpoint(fat)
        hop = _network_distance(
            prev_pt, fat_pt,
            road_a_id=prev_road, road_b_id=fat.road_id,
            topo=topo, dist_calc=dist_calc,
        )
        total += hop
        excess = hop - b2b_hop_limit(idx)
        if excess > worst_excess:
            worst_excess = excess
        prev_pt = fat_pt
        prev_road = fat.road_id
    return worst_excess, total


def _optimal_wing_order(
    fdt: FDT,
    wing_fats: List[FAT],
    dist_calc: Optional['DistanceCalculator'] = None,
    topo: Optional['RoadTopologyEngine'] = None,
) -> List[FAT]:
    """[Fix 2] Order one wing so the longest hop is as short as possible.

    Replaces the radial sort ``sorted(wing, key=_dist_from_fdt)`` that used to
    decide cascade order. That sort made consecutive chain members RADIAL
    neighbours, which says nothing about road distance between them: two FATs
    at a similar radius but on different branches ended up adjacent in the
    chain, and the cable between them ran back through the FDT junction and out
    again. The fingerprint on the reference run was unmistakable — 26 of 48
    wings had their longest hop as the LAST hop, where chance is about 12, and
    16 of 23 gate violations sat at hop 3 or 4.

    With MAX_FAT_PER_WING = 4 the permutation space is at most 24 orders per
    wing, so this is solved exactly rather than heuristically. The greedy
    nearest-neighbour walk that v16 deleted is deliberately NOT restored: it was
    removed for producing zig-zag cascades, and that objection was partly right
    even though it was diagnosed against a broken distance function. Exhaustive
    search over a 4-element set is both cheaper to reason about and strictly
    better than greedy.

    Above the exhaustive threshold (only reachable if MAX_FAT_PER_WING is
    raised) it falls back to greedy nearest-hop plus 2-opt, which is the same
    objective approached heuristically rather than a different objective.
    """
    n = len(wing_fats)
    if n <= 1:
        return list(wing_fats)

    if n <= 6:
        best_order = None
        best_cost = None
        for perm in itertools.permutations(wing_fats):
            cost = _wing_chain_objective(fdt, list(perm), dist_calc=dist_calc, topo=topo)
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_order = list(perm)
        return best_order if best_order is not None else list(wing_fats)

    # ── Heuristic path for oversized wings ───────────────────────────────
    fdt_pt = _b2b_endpoint(fdt)

    def _hop(a_pt, a_road, fat):
        return _network_distance(
            a_pt, _b2b_endpoint(fat),
            road_a_id=a_road, road_b_id=fat.road_id,
            topo=topo, dist_calc=dist_calc,
        )

    remaining = list(wing_fats)
    order: List[FAT] = []
    cur_pt, cur_road = fdt_pt, fdt.primary_road_id
    while remaining:
        nxt = min(remaining, key=lambda f: _hop(cur_pt, cur_road, f))
        order.append(nxt)
        remaining.remove(nxt)
        cur_pt, cur_road = _b2b_endpoint(nxt), nxt.road_id

    best_cost = _wing_chain_objective(fdt, order, dist_calc=dist_calc, topo=topo)
    improved = True
    while improved:
        improved = False
        for i in range(len(order) - 1):
            for j in range(i + 1, len(order)):
                cand = order[:i] + list(reversed(order[i:j + 1])) + order[j + 1:]
                cand_cost = _wing_chain_objective(fdt, cand, dist_calc=dist_calc, topo=topo)
                if cand_cost < best_cost:
                    order, best_cost, improved = cand, cand_cost, True
    return order


def _wing_chain_is_valid(
    fdt: FDT,
    wing_fats: List[FAT],
    dist_calc: Optional['DistanceCalculator'] = None,
    topo: Optional['RoadTopologyEngine'] = None,
) -> bool:
    return not _wing_chain_violations(fdt, wing_fats, dist_calc=dist_calc, topo=topo)


def _wing_chain_cost(
    fdt: FDT,
    wing_fats: List[FAT],
    dist_calc: Optional['DistanceCalculator'] = None,
    topo: Optional['RoadTopologyEngine'] = None,
) -> float:
    if not wing_fats:
        return 0.0
    total = 0.0
    fdt_pt = fdt.snapped_geometry or fdt.geometry
    first = wing_fats[0]
    total += _network_distance(
        fdt_pt,
        first.snapped_geometry or first.geometry,
        road_a_id=fdt.primary_road_id,
        road_b_id=first.road_id,
        topo=topo,
        dist_calc=dist_calc,
    )
    for idx in range(1, len(wing_fats)):
        prev_fat = wing_fats[idx - 1]
        fat = wing_fats[idx]
        total += _network_distance(
            prev_fat.snapped_geometry or prev_fat.geometry,
            fat.snapped_geometry or fat.geometry,
            road_a_id=prev_fat.road_id,
            road_b_id=fat.road_id,
            topo=topo,
            dist_calc=dist_calc,
        )
    return total


def _apply_explicit_wing_order(
    fdt: FDT,
    wing_a: List[FAT],
    wing_b: List[FAT],
    dist_calc: Optional['DistanceCalculator'] = None,
    topo: Optional['RoadTopologyEngine'] = None,
    roads: Optional[Dict[int, 'RoadSegment']] = None,
    wings: Optional[Dict[str, List[FAT]]] = None,
    profile: Optional['CapacityProfile'] = None,
) -> None:
    """Persist a known-valid wing order without re-sorting by FDT distance.

    Backward-compatible: every existing call site passes ``wing_a``/``wing_b``
    positionally and is untouched (behaves identically to before). Dual-PON
    callers pass ``wings={"A": [...], "B": [...], "C": [...], "D": [...]}``
    instead (C/D omitted or empty under Single-PON) — when ``wings`` is given
    it takes precedence over the positional ``wing_a``/``wing_b`` args.
    fdt.fats is stored PON-major (A,B,C,D) — never interleaved.
    """
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    if wings is None:
        wings = {"A": wing_a, "B": wing_b}
    # Any wing this architecture has that the caller didn't mention (e.g. a
    # legacy positional A/B-only call on a Dual-PON FDT) is preserved as-is
    # from the FDT's current membership — never silently emptied. This is
    # what makes every pre-existing positional call site safe to leave
    # untouched even once Dual-PON is active.
    for wing_label in profile.wings:
        if wing_label not in wings:
            wings[wing_label] = _ordered_wing_fats(fdt, wing_label)

    for wing_label in wings:
        if len(wings[wing_label]) > profile.max_fat_per_wing:
            raise ValidationError(
                f"{fdt.name}: wing {wing_label} overflow "
                f"({len(wings[wing_label])} > {profile.max_fat_per_wing})"
            )
        if wing_label not in profile.wings and wings[wing_label]:
            raise ValidationError(
                f"{fdt.name}: wing {wing_label} not valid for architecture "
                f"with wings {profile.wings}"
            )

    for wing_label in profile.wings:
        for seq, fat in enumerate(wings.get(wing_label, []), start=1):
            fat.wing = wing_label
            fat.wing_id = wing_label
            fat.parent_fdt = fdt.name
            fat.logical_fdt = fdt.name
            fat.fdt_serial = fdt.fdt_serial
            fat.fat_sequence = f"{seq:02d}"
            fat.fat_full_code = _project_tag("FAT", f"{fdt.fdt_serial}{wing_label}", f"{seq:02d}")
            fat.name = fat.fat_full_code

    fdt.wing_a_count = len(wings.get("A", []))
    fdt.wing_b_count = len(wings.get("B", []))
    fdt.wing_c_count = len(wings.get("C", []))
    fdt.wing_d_count = len(wings.get("D", []))
    fdt.fats = [fat for label in profile.wings for fat in wings.get(label, [])]
    fdt.total_fat = len(fdt.fats)
    fdt.total_customers = sum(_parse_homepass_value(f.total_customers) for f in fdt.fats)
    _apply_fat_traceability(fdt, dist_calc=dist_calc, topo=topo, roads=roads)


def _best_valid_wing_insertion(
    fdt: FDT,
    candidate: FAT,
    dist_calc: Optional['DistanceCalculator'] = None,
    topo: Optional['RoadTopologyEngine'] = None,
    remove_fat: Optional[FAT] = None,
    pon: int = 1,
    profile: Optional['CapacityProfile'] = None,
) -> Optional[Tuple[float, List[FAT], List[FAT]]]:
    """Find the lowest-cost valid wing order after inserting ``candidate``.

    Scoped to ``pon``'s two wings only (PON_WINGS[pon]) — a Dual-PON repair
    never considers wings outside the candidate's already-resolved PON (spec
    §A.6). Default ``pon=1`` reproduces the original A/B-only search exactly.
    """
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    wing_lo, wing_hi = PON_WINGS[pon]
    base_lo = [fat for fat in _ordered_wing_fats(fdt, wing_lo)
               if fat is not candidate and fat is not remove_fat]
    base_hi = [fat for fat in _ordered_wing_fats(fdt, wing_hi)
               if fat is not candidate and fat is not remove_fat]
    best: Optional[Tuple[float, List[FAT], List[FAT]]] = None

    for wing_label, base in [(wing_lo, base_lo), (wing_hi, base_hi)]:
        if len(base) >= profile.max_fat_per_wing:
            continue
        for pos in range(len(base) + 1):
            trial = base[:pos] + [candidate] + base[pos:]
            trial_lo = trial if wing_label == wing_lo else list(base_lo)
            trial_hi = trial if wing_label == wing_hi else list(base_hi)
            if not _wing_chain_is_valid(fdt, trial_lo, dist_calc=dist_calc, topo=topo):
                continue
            if not _wing_chain_is_valid(fdt, trial_hi, dist_calc=dist_calc, topo=topo):
                continue
            cost = (
                _wing_chain_cost(fdt, trial_lo, dist_calc=dist_calc, topo=topo)
                + _wing_chain_cost(fdt, trial_hi, dist_calc=dist_calc, topo=topo)
            )
            if best is None or cost < best[0]:
                best = (cost, trial_lo, trial_hi)
    return best


def _current_wings_without(
    fdt: FDT,
    removed: Optional[FAT],
    pon: int = 1,
) -> Tuple[List[FAT], List[FAT]]:
    """Return the two wings of ``pon`` (default PON1 = A/B, unchanged from
    the original behaviour) with ``removed`` filtered out."""
    wing_lo, wing_hi = PON_WINGS[pon]
    return (
        [fat for fat in _ordered_wing_fats(fdt, wing_lo) if fat is not removed],
        [fat for fat in _ordered_wing_fats(fdt, wing_hi) if fat is not removed],
    )
