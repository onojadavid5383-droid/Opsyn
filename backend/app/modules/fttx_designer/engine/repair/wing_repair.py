"""Verbatim port of the wing-chain repair passes from
``FTTx Designer — dual PON integrated.py``: ``_repair_wing_membership_by_swap``
(Fix 6 — cheapest repair, same-FDT wing swap/move), ``_repair_wing_chain_continuity``
(final safety net — reorder/move/swap/cascade to fix a broken cascade hop),
``_cascade_relay_repair`` (multi-hop DFS relay used by the continuity repair
when nothing simpler works).

No logic changes from the source script — only the QGIS types and
cross-module imports.

PRESERVED BUG, not fixed: ``_cascade_relay_repair``'s local ``anchor_dist()``
helper calls ``_fdt_to_fdt_distance(...)`` inside a ``try/except Exception``
— that name is referenced exactly once and **never defined anywhere in the
21,001-line source file** (confirmed by grep; the source's own
``# type: ignore[name-defined]`` comment on that line acknowledges it). At
runtime this always raises ``NameError``, which the surrounding
``except Exception`` silently swallows, so ``anchor_dist()`` always falls
through to the plain straight-line fallback
(``dist_calc.distance(fdt_a.geometry, fdt_b.geometry)``) rather than the
network-distance-ranked neighbour ordering the code appears to intend. A
verbatim port preserves this exactly — silently "fixing" it here would
change which neighbour FDTs this repair pass tries first, a real behavior
change outside this port's scope. Flagged for the user's separate decision
on whether to fix it upstream (with its own golden-output re-verification).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..config import MIN_REPAIR_GAIN_M, PON_WINGS, WING_TO_PON, CapacityProfile, PONArchitecture, CAPACITY_PROFILES
from ..domain import FAT, FDT, RoadSegment
from ..errors import ValidationError
from ..fdt_anchor import _distance_to_fdt_anchor
from ..perf_logger import PerformanceLogger
from ..spatial_utils import DistanceCalculator
from ..topology import RoadTopologyEngine
from ..wing_chain import (
    _apply_explicit_wing_order,
    _best_valid_wing_insertion,
    _current_wings_without,
    _optimal_wing_order,
    _ordered_wing_fats,
    _record_repair_move,
    _repair_budget_left,
    _wing_chain_objective,
    _wing_chain_violations,
)


def _repair_wing_membership_by_swap(
    fdts: List[FDT],
    logger: PerformanceLogger,
    roads: Optional[Dict[int, 'RoadSegment']] = None,
    dist_calc: Optional['DistanceCalculator'] = None,
    topo: Optional['RoadTopologyEngine'] = None,
    profile: Optional['CapacityProfile'] = None,
    max_passes: int = 6,
) -> int:
    """[Fix 6] Move or swap a FAT between the two wings of ONE PON of ONE FDT.

    This is the cheapest repair in the file and it should be tried before any of
    the ones that move FATs between FDTs, because it changes nothing those
    passes care about:
      • FDT ownership is untouched, so FDT capacity cannot be violated
      • the PON boundary is never crossed (spec §A.6)
      • no other FDT is perturbed, so it cannot start an oscillation

    It targets the specific failure the angular split leaves behind: two FATs
    that are close in bearing from the anchor but far apart by road end up in
    the same wing, and no amount of re-ordering inside that wing can fix it
    (see _optimal_wing_order). Sending one of them to the sibling wing can.

    Returns the number of accepted changes.
    """
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    if not fdts:
        return 0

    def _pair_cost(fdt: FDT, wa: List[FAT], wb: List[FAT]) -> Tuple[float, float]:
        ea, ta = _wing_chain_objective(fdt, wa, dist_calc=dist_calc, topo=topo)
        eb, tb = _wing_chain_objective(fdt, wb, dist_calc=dist_calc, topo=topo)
        return max(ea, eb), ta + tb

    total_applied = 0
    for _pass in range(max_passes):
        applied_this_pass = 0

        for fdt in fdts:
            for pon, (label_a, label_b) in PON_WINGS.items():
                if label_a not in profile.wings or label_b not in profile.wings:
                    continue

                wa = _optimal_wing_order(fdt, _ordered_wing_fats(fdt, label_a),
                                         dist_calc=dist_calc, topo=topo)
                wb = _optimal_wing_order(fdt, _ordered_wing_fats(fdt, label_b),
                                         dist_calc=dist_calc, topo=topo)
                if not wa and not wb:
                    continue

                base_excess, base_total = _pair_cost(fdt, wa, wb)
                if base_excess <= 0.0:
                    continue   # this PON's wings are already compliant

                best = None   # (excess, total, new_wa, new_wb, description)

                # ── candidate 1: relocate one FAT to the sibling wing ──────
                for src, dst, src_label, dst_label in (
                    (wa, wb, label_a, label_b),
                    (wb, wa, label_b, label_a),
                ):
                    if len(dst) >= profile.max_fat_per_wing:
                        continue
                    for fat in src:
                        if not _repair_budget_left(fat):
                            continue
                        new_src = _optimal_wing_order(
                            fdt, [f for f in src if f is not fat],
                            dist_calc=dist_calc, topo=topo)
                        new_dst = _optimal_wing_order(
                            fdt, list(dst) + [fat],
                            dist_calc=dist_calc, topo=topo)
                        if src_label == label_a:
                            cand_a, cand_b = new_src, new_dst
                        else:
                            cand_a, cand_b = new_dst, new_src
                        exc, tot = _pair_cost(fdt, cand_a, cand_b)
                        key = (exc, tot)
                        if best is None or key < (best[0], best[1]):
                            best = (exc, tot, cand_a, cand_b,
                                    f"move {fat.name} {src_label}->{dst_label}",
                                    (fat,))

                # ── candidate 2: exchange one FAT for another ──────────────
                for fat_a in wa:
                    for fat_b in wb:
                        if not (_repair_budget_left(fat_a) and _repair_budget_left(fat_b)):
                            continue
                        cand_a = _optimal_wing_order(
                            fdt, [f for f in wa if f is not fat_a] + [fat_b],
                            dist_calc=dist_calc, topo=topo)
                        cand_b = _optimal_wing_order(
                            fdt, [f for f in wb if f is not fat_b] + [fat_a],
                            dist_calc=dist_calc, topo=topo)
                        exc, tot = _pair_cost(fdt, cand_a, cand_b)
                        key = (exc, tot)
                        if best is None or key < (best[0], best[1]):
                            best = (exc, tot, cand_a, cand_b,
                                    f"swap {fat_a.name} <-> {fat_b.name} "
                                    f"({label_a}/{label_b})",
                                    (fat_a, fat_b))

                if best is None:
                    continue

                exc, tot, cand_a, cand_b, description, moved = best
                # [Fix 7] Require a real improvement, not any epsilon. Accepting
                # marginal gains is what let the FDT-level repairs trade the
                # same FAT back and forth for five straight passes.
                improves_excess = exc < base_excess - MIN_REPAIR_GAIN_M
                same_excess_shorter = (
                    abs(exc - base_excess) <= 1e-6 and tot < base_total - MIN_REPAIR_GAIN_M
                )
                if not (improves_excess or same_excess_shorter):
                    continue

                for fat in cand_a:
                    fat.wing = label_a
                    fat.wing_id = label_a
                for fat in cand_b:
                    fat.wing = label_b
                    fat.wing_id = label_b

                wings = {label_a: cand_a, label_b: cand_b}
                try:
                    _apply_explicit_wing_order(
                        fdt, [], [], dist_calc=dist_calc, topo=topo, roads=roads,
                        wings=wings, profile=profile,
                    )
                except ValidationError as exc_err:
                    logger.log(
                        f"WING-SWAP rejected on {fdt.name} PON{pon}: {exc_err}"
                    )
                    continue

                _record_repair_move(*moved)
                applied_this_pass += 1
                total_applied += 1
                logger.log(
                    f"WING-SWAP {fdt.name} PON{pon}: {description}; "
                    f"worst hop excess {base_excess:.1f}m -> {exc:.1f}m, "
                    f"chain total {base_total:.1f}m -> {tot:.1f}m"
                )

        if applied_this_pass == 0:
            break

    if total_applied:
        logger.log(
            f"Wing-membership swap repair complete — {total_applied} change(s)."
        )
    return total_applied


def _repair_wing_chain_continuity(
    fdts: List[FDT],
    logger: PerformanceLogger,
    roads: Optional[Dict[int, 'RoadSegment']] = None,
    dist_calc: Optional['DistanceCalculator'] = None,
    topo: Optional['RoadTopologyEngine'] = None,
    max_passes: int = 20,
    profile: Optional['CapacityProfile'] = None,
) -> None:
    """Final safety net: no FAT may remain after a broken wing-chain hop.

    Earlier grouping/absorption logic can still move a FAT because it is closer
    to an FDT anchor, while the actual cascade jump from the previous FAT is too
    long.  This pass repairs that by inserting each bad FAT into the closest FDT
    wing where every consecutive hop is legal.  If all nearby FDTs are full it
    tries a 1-for-1 relay swap.  If no legal placement exists, it raises instead
    of exporting a visibly wrong outlier.

    Dual-PON: violation detection loops every wing in profile.wings (so a
    broken C/D hop is no longer silently ignored). Repair actions resolve the
    candidate's PON from its current wing label and scope insertion search to
    that PON's two wings only (spec §A.6) — a repair never moves a FAT across
    the PON1/PON2 boundary. The other PON's wings are always carried through
    unchanged when persisting a new order, never dropped.
    """
    if not fdts:
        return

    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]

    def _other_pon_wings(fdt: FDT, pon: int) -> Dict[str, List[FAT]]:
        """Wings belonging to the PON *not* being repaired, unchanged."""
        other = {1: 2, 2: 1}.get(pon)
        if other is None or other not in PON_WINGS:
            return {}
        wlo, whi = PON_WINGS[other]
        return {wlo: _ordered_wing_fats(fdt, wlo), whi: _ordered_wing_fats(fdt, whi)}

    def _apply_pon_scoped(fdt: FDT, pon: int, wing_lo_fats: List[FAT], wing_hi_fats: List[FAT]) -> None:
        wlo, whi = PON_WINGS[pon]
        wings = _other_pon_wings(fdt, pon)
        wings[wlo] = wing_lo_fats
        wings[whi] = wing_hi_fats
        _apply_explicit_wing_order(fdt, [], [], dist_calc=dist_calc, topo=topo, roads=roads,
                                    wings=wings, profile=profile)

    repairs = 0
    for _pass in range(max_passes):
        violations = []
        for fdt in fdts:
            for wing_label in profile.wings:
                wing_fats = _ordered_wing_fats(fdt, wing_label)
                for idx, fat, dist, limit, prev_name in _wing_chain_violations(
                    fdt, wing_fats, dist_calc=dist_calc, topo=topo
                ):
                    violations.append((dist - limit, fdt, wing_label, idx, fat, dist, limit, prev_name))

        if not violations:
            logger.log(f"Wing-chain continuity repair complete — {repairs} repair(s).")
            return

        violations.sort(key=lambda item: item[0], reverse=True)
        applied = False

        for _, source, wing_label, _, bad_fat, bad_dist, limit, prev_name in violations:
            if bad_fat not in source.fats:
                continue

            # [Fix 7] Budget applies to ownership changes only. A same-FDT
            # reorder (branch 1 below) costs nothing and cannot oscillate
            # ownership, so it is always allowed; moves and swaps are what
            # need rationing.
            _budget_ok = _repair_budget_left(bad_fat)

            source_pon = WING_TO_PON.get(wing_label, 1)
            source_a, source_b = _current_wings_without(source, bad_fat, pon=source_pon)

            # 1) Same-FDT reordering / opposite-wing placement, if it fixes the chain.
            #    PON-scoped: never considers the other PON's wings (spec §A.6).
            same_fdt = _best_valid_wing_insertion(
                source, bad_fat, dist_calc=dist_calc, topo=topo, remove_fat=bad_fat,
                pon=source_pon, profile=profile,
            )
            if same_fdt is not None:
                _, new_a, new_b = same_fdt
                _apply_pon_scoped(source, source_pon, new_a, new_b)
                logger.log(
                    f"CHAIN-REPAIR reorder: {bad_fat.name} stayed in {source.name}; "
                    f"previous hop {prev_name}→{bad_fat.name} was {bad_dist:.0f}m > {limit:.0f}m."
                )
                repairs += 1
                applied = True
                break

            # 2) Direct move to another FDT with a valid insertion point.
            #    Target PON is resolved the same way as the source's (the
            #    candidate's own already-assigned PON) — a direct move never
            #    reassigns a FAT to a different PON, only a different FDT.
            #    [Corrective fix] this branch previously removed bad_fat from
            #    source unconditionally — with no capacity guard at all. As
            #    the last ownership-mutating stage before final validation,
            #    that could silently push an already-valid (or already-just-
            #    repaired) source FDT below minimum with nothing left to
            #    catch it. Only attempt a direct move when source can afford
            #    to lose one FAT and stay at or above MIN; otherwise skip
            #    straight to the capacity-neutral relay swap (3) below.
            best_direct = None
            if len(source.fats) > profile.min_fat_per_fdt:
                for target in fdts:
                    if target is source or len(target.fats) >= profile.max_fat_per_fdt:
                        continue
                    insertion = _best_valid_wing_insertion(
                        target, bad_fat, dist_calc=dist_calc, topo=topo,
                        pon=source_pon, profile=profile,
                    )
                    if insertion is None:
                        continue
                    target_cost, target_a, target_b = insertion
                    target_dist = _distance_to_fdt_anchor(bad_fat, target, dist_calc=dist_calc, topo=topo, roads=roads)
                    source_dist = _distance_to_fdt_anchor(bad_fat, source, dist_calc=dist_calc, topo=topo, roads=roads)
                    score = target_cost + max(0.0, target_dist - source_dist)
                    if best_direct is None or score < best_direct[0]:
                        best_direct = (score, target, target_a, target_b)
            else:
                logger.log(
                    f"[FDT-MOVE-BLOCKED] FAT={bad_fat.name} FROM={source.name} "
                    f"TO=<direct-move> SOURCE_COUNT={len(source.fats)} "
                    f"REASON=SOURCE_AT_OR_BELOW_MINIMUM_CAPACITY"
                )

            if best_direct is not None and _budget_ok:
                _, target, target_a, target_b = best_direct
                src_before, dst_before = len(source.fats), len(target.fats)
                source.fats.remove(bad_fat)
                _apply_pon_scoped(source, source_pon, source_a, source_b)
                _apply_pon_scoped(target, source_pon, target_a, target_b)
                bad_fat.allocation_type = "chain-repaired"
                _record_repair_move(bad_fat)
                logger.log(
                    f"[FDT-MOVE] FAT={bad_fat.name} FROM={source.name} TO={target.name} "
                    f"SOURCE_BEFORE={src_before} TARGET_BEFORE={dst_before} "
                    f"SOURCE_AFTER={len(source.fats)} TARGET_AFTER={len(target.fats)} "
                    f"REASON=CHAIN_REPAIR_DIRECT_MOVE"
                )
                logger.log(
                    f"CHAIN-REPAIR move: {bad_fat.name} {source.name} → {target.name}; "
                    f"broken hop {prev_name}→{bad_fat.name} was {bad_dist:.0f}m > {limit:.0f}m."
                )
                repairs += 1
                applied = True
                break

            # 3) Relay swap with a full neighbour. The return FAT's own PON is
            #    resolved independently, so a swap can legally exchange an A/B
            #    FAT for a C/D FAT across two FDTs — each side still only
            #    reorders within its own PON's two wings.
            best_swap = None
            for target in (fdts if _budget_ok else []):
                if target is source:
                    continue
                for return_fat in list(target.fats):
                    if not _repair_budget_left(return_fat):
                        continue
                    return_pon = WING_TO_PON.get(getattr(return_fat, 'wing', ''), 1)
                    target_insert = _best_valid_wing_insertion(
                        target, bad_fat, dist_calc=dist_calc, topo=topo, remove_fat=return_fat,
                        pon=source_pon, profile=profile,
                    )
                    if target_insert is None:
                        continue
                    source_insert = _best_valid_wing_insertion(
                        source, return_fat, dist_calc=dist_calc, topo=topo, remove_fat=bad_fat,
                        pon=return_pon, profile=profile,
                    )
                    if source_insert is None:
                        continue
                    target_cost, target_a, target_b = target_insert
                    source_cost, swap_source_a, swap_source_b = source_insert
                    score = target_cost + source_cost
                    if best_swap is None or score < best_swap[0]:
                        best_swap = (score, target, return_fat, return_pon,
                                     target_a, target_b, swap_source_a, swap_source_b)

            if best_swap is not None:
                _, target, return_fat, return_pon, target_a, target_b, swap_source_a, swap_source_b = best_swap
                src_before, dst_before = len(source.fats), len(target.fats)
                if bad_fat in source.fats:
                    source.fats.remove(bad_fat)
                if return_fat in target.fats:
                    target.fats.remove(return_fat)
                _apply_pon_scoped(source, return_pon, swap_source_a, swap_source_b)
                _apply_pon_scoped(target, source_pon, target_a, target_b)
                bad_fat.allocation_type = "chain-relay-swap-out"
                return_fat.allocation_type = "chain-relay-swap-in"
                _record_repair_move(bad_fat, return_fat)
                logger.log(
                    f"[FDT-MOVE] FAT={bad_fat.name} FROM={source.name} TO={target.name} "
                    f"SOURCE_BEFORE={src_before} TARGET_BEFORE={dst_before} "
                    f"SOURCE_AFTER={len(source.fats)} TARGET_AFTER={len(target.fats)} "
                    f"REASON=CHAIN_REPAIR_RELAY_SWAP (paired with {return_fat.name} "
                    f"{target.name}→{source.name}, capacity-neutral)"
                )
                logger.log(
                    f"CHAIN-REPAIR swap: {bad_fat.name} {source.name} → {target.name}; "
                    f"{return_fat.name} {target.name} → {source.name}."
                )
                repairs += 1
                applied = True
                break

        if not applied:
            # ---- Cascade / multi-hop relay recalibration ----------------------
            # Instead of stopping at the first unresolvable violation, try a
            # chain of moves: bad_fat -> FDT_A, FDT_A's farthest FAT -> FDT_B,
            # ... until a receiver with legal capacity is reached. If nothing
            # works for a given FAT we log it as an unresolved outlier and keep
            # going so the caller can still export the design.
            unresolved: List[Tuple[FDT, str, FAT, float, float, str]] = []
            for _, source, wing_label, _, bad_fat, bad_dist, limit, prev_name in violations:
                if bad_fat not in source.fats:
                    continue
                if _cascade_relay_repair(
                    bad_fat, source, fdts, logger,
                    roads=roads, dist_calc=dist_calc, topo=topo,
                    max_depth=4, profile=profile,
                ):
                    repairs += 1
                    applied = True
                else:
                    unresolved.append((source, wing_label, bad_fat, bad_dist, limit, prev_name))

            if not applied:
                # Nothing at all moved this pass — mark remaining as tolerated
                # outliers so the run can proceed instead of aborting.
                for source, wing_label, bad_fat, bad_dist, limit, prev_name in unresolved:
                    bad_fat.allocation_type = "chain-unresolved-outlier"
                    logger.log(
                        f"WARNING CHAIN-REPAIR unresolved: {source.name} Wing {wing_label}: "
                        f"{prev_name} → {bad_fat.name} = {bad_dist:.0f}m > {limit:.0f}m. "
                        f"No direct move, swap, or cascade relay could reposition it; "
                        f"leaving in place and continuing export."
                    )
                logger.log(
                    f"Wing-chain continuity repair finished with {len(unresolved)} "
                    f"unresolved outlier(s) after {repairs} successful repair(s)."
                )
                return

    logger.log(
        f"WARNING: Wing-chain continuity repair did not converge after {max_passes} "
        f"passes; continuing with best-effort layout ({repairs} repair(s) applied)."
    )


def _cascade_relay_repair(
    bad_fat: FAT,
    source: FDT,
    fdts: List[FDT],
    logger: PerformanceLogger,
    roads: Optional[Dict[int, 'RoadSegment']] = None,
    dist_calc: Optional['DistanceCalculator'] = None,
    topo: Optional['RoadTopologyEngine'] = None,
    max_depth: int = 4,
    profile: Optional['CapacityProfile'] = None,
) -> bool:
    """Multi-hop relay: push a chain of donations toward a receiver with slack.

    Chain shape (depth k):
        bad_fat -> FDT_1 (displaces f_1) -> FDT_2 (displaces f_2) -> ... -> FDT_k
    where FDT_k has spare capacity OR accepts f_{k-1} via legal insertion, and
    every intermediate hop is a legal wing insertion. FDT ordering is by
    proximity to `source` so the cascade physically walks toward the receiver.

    Dual-PON: the DFS is PON-scoped per FAT — each carried FAT resolves its
    own PON from its current wing (WING_TO_PON) and the insertion search is
    scoped to that PON's two wings only (spec §A.6), never crossing the
    PON1/PON2 boundary. When a step is applied, the *other* PON's wings are
    always re-read from the FDT and carried through unchanged in the same
    ``_apply_explicit_wing_order`` call — this was a real bug (not just an
    unrepaired outlier): applying only the touched PON's two wings without
    the other PON's caused ``fdt.fats`` to be silently rebuilt *without* the
    untouched C/D (or A/B) members, deleting them from the FDT entirely.
    """
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    if bad_fat not in source.fats:
        return False

    def _pon_of(fat: FAT) -> int:
        return WING_TO_PON.get(getattr(fat, 'wing', None), 1)

    def _apply_pon_scoped_full(fdt: FDT, pon: int, wing_lo_fats: List[FAT], wing_hi_fats: List[FAT]) -> None:
        """Commit a repaired PON's two wings while re-reading and carrying
        through the *other* PON's wings unchanged — never drops them."""
        wlo, whi = PON_WINGS[pon]
        wings: Dict[str, List[FAT]] = {wlo: wing_lo_fats, whi: wing_hi_fats}
        other = {1: 2, 2: 1}.get(pon)
        if other in PON_WINGS:
            olo, ohi = PON_WINGS[other]
            wings[olo] = _ordered_wing_fats(fdt, olo)
            wings[ohi] = _ordered_wing_fats(fdt, ohi)
        _apply_explicit_wing_order(
            fdt, [], [], dist_calc=dist_calc, topo=topo, roads=roads,
            wings=wings, profile=profile,
        )

    def anchor_dist(fdt_a: FDT, fdt_b: FDT) -> float:
        # PRESERVED BUG (see module docstring): `_fdt_to_fdt_distance` does
        # not exist anywhere in the source file, so this always raises
        # NameError and falls through to the straight-line distance below —
        # network-distance neighbour ranking here is dead code in practice.
        try:
            return _fdt_to_fdt_distance(fdt_a, fdt_b, dist_calc=dist_calc, topo=topo, roads=roads)  # type: ignore[name-defined]  # noqa: F821
        except Exception:
            try:
                return dist_calc.distance(fdt_a.geometry, fdt_b.geometry) if dist_calc else 0.0
            except Exception:
                return 0.0

    # [Corrective fix] every intermediate hop in this cascade is naturally
    # capacity-neutral (each middle FDT gains one carried FAT and gives away
    # one displaced FAT), and the final receiver only accepts with genuine
    # spare capacity (checked below via len(cand.fats) < max) — but `source`
    # itself loses bad_fat with nothing coming back. That was never guarded.
    # As the last-resort ownership-mutating stage before final validation,
    # letting it drain an already-at-or-below-minimum source would silently
    # create (or worsen) exactly the kind of violation
    # validate_capacity_and_absorption_model exists to catch.
    #
    # [Floor-backfill fix] Refusing outright here throws away every case
    # where some OTHER FDT genuinely has spare-above-minimum capacity and a
    # FAT that legally reaches into `source`'s wings (same hop-limit
    # validity check as everywhere else — _best_valid_wing_insertion, the
    # exact function used to validate every other insertion in this file).
    # Backfill `source` with that FAT FIRST: a plain, capacity-safe trade
    # (donor stays >= min, source goes from min to min+1) that costs nobody
    # anything. With `source` now above the floor, the donation below can
    # proceed exactly as if the guard had never fired — `source` ends the
    # whole operation back at exactly `min`, never below it. This is what
    # turns a one-way "donate and shrink" cascade into a genuine
    # redistribution loop: nobody's FDT count ever leaves [min, max], and no
    # additional FDT is ever created. Only when NO such donor exists anywhere
    # does this fall back to the original refusal — leaving bad_fat in place
    # (still logged as an unresolved chain violation by the caller) is
    # strictly better than making capacity worse to fix a distance violation.
    if len(source.fats) <= profile.min_fat_per_fdt:
        backfill_best: Optional[Tuple[float, FDT, FAT, int, List[FAT], List[FAT]]] = None
        for donor in sorted([f for f in fdts if f is not source], key=lambda f: anchor_dist(source, f)):
            if len(donor.fats) <= profile.min_fat_per_fdt:
                continue  # donor would itself breach the floor — never eligible
            for cand_fat in list(donor.fats):
                if cand_fat is bad_fat:
                    continue
                cand_pon = _pon_of(cand_fat)
                insertion = _best_valid_wing_insertion(
                    source, cand_fat, dist_calc=dist_calc, topo=topo,
                    pon=cand_pon, profile=profile,
                )
                if insertion is None:
                    continue
                cost, wa, wb = insertion
                if backfill_best is None or cost < backfill_best[0]:
                    backfill_best = (cost, donor, cand_fat, cand_pon, wa, wb)
            if backfill_best is not None:
                break  # nearest donor already yielded a legal candidate — good enough

        if backfill_best is None:
            logger.log(
                f"[FDT-MOVE-BLOCKED] FAT={bad_fat.name} FROM={source.name} "
                f"TO=<cascade-relay> SOURCE_COUNT={len(source.fats)} "
                f"REASON=SOURCE_AT_OR_BELOW_MINIMUM_CAPACITY"
            )
            return False

        _, backfill_donor, backfill_fat, backfill_pon, backfill_wa, backfill_wb = backfill_best
        donor_a, donor_b = _current_wings_without(backfill_donor, backfill_fat, pon=backfill_pon)
        donor_before = len(backfill_donor.fats)
        source_before = len(source.fats)
        backfill_donor.fats.remove(backfill_fat)
        _apply_pon_scoped_full(backfill_donor, backfill_pon, donor_a, donor_b)
        _apply_pon_scoped_full(source, backfill_pon, backfill_wa, backfill_wb)
        backfill_fat.allocation_type = "cascade-floor-backfill"
        logger.log(
            f"[FDT-MOVE] FAT={backfill_fat.name} FROM={backfill_donor.name} "
            f"TO={source.name} SOURCE_BEFORE={donor_before} TARGET_BEFORE={source_before} "
            f"SOURCE_AFTER={len(backfill_donor.fats)} TARGET_AFTER={len(source.fats)} "
            f"REASON=CASCADE_FLOOR_BACKFILL (frees {source.name} to donate "
            f"{bad_fat.name} without breaching the floor)"
        )

    neighbours = sorted(
        [f for f in fdts if f is not source],
        key=lambda f: anchor_dist(source, f),
    )

    # Try increasing chain depths — shortest cascade first.
    for depth in range(1, max_depth + 1):
        # DFS over neighbour chains of exactly `depth` FDTs. Each plan step
        # carries its own resolved `pon` alongside (cand, carry_fat, a, b) so
        # apply-time never has to re-derive it from a FAT whose .wing may
        # already have been overwritten by an earlier step in the same plan.
        def dfs(carry_fat: FAT, giver: FDT, chain: List[Tuple[FDT, FAT, Tuple, Tuple, int]], remaining: int) -> Optional[List[Tuple[FDT, FAT, Tuple, Tuple, int]]]:
            carry_pon = _pon_of(carry_fat)
            for cand in neighbours:
                if cand is giver or any(cand is step[0] for step in chain):
                    continue
                # Case A: cand has spare capacity — absorb carry_fat, done.
                if len(cand.fats) < profile.max_fat_per_fdt:
                    insert = _best_valid_wing_insertion(
                        cand, carry_fat, dist_calc=dist_calc, topo=topo, pon=carry_pon,
                    )
                    if insert is not None:
                        _, a, b = insert
                        return chain + [(cand, carry_fat, a, b, carry_pon)]
                if remaining <= 1:
                    continue
                # Case B: cand is full — try displacing one of its FATs onward.
                # Prefer displacing its farthest FAT (most likely a fringe one).
                # Only consider displacing FATs from carry_fat's own PON — a
                # displaced FAT keeps searching within its own PON's wings at
                # the next DFS level, same as every other step.
                cand_fats_sorted = sorted(
                    [f for f in cand.fats if _pon_of(f) == carry_pon],
                    key=lambda ff: _distance_to_fdt_anchor(ff, cand, dist_calc=dist_calc, topo=topo, roads=roads),
                    reverse=True,
                )
                for displaced in cand_fats_sorted[:6]:  # cap fan-out
                    insert = _best_valid_wing_insertion(
                        cand, carry_fat, dist_calc=dist_calc, topo=topo,
                        remove_fat=displaced, pon=carry_pon,
                    )
                    if insert is None:
                        continue
                    _, a, b = insert
                    tail = dfs(displaced, cand, chain + [(cand, carry_fat, a, b, carry_pon)], remaining - 1)
                    if tail is not None:
                        return tail
            return None

        plan = dfs(bad_fat, source, [], depth)
        if plan is None:
            continue

        # Apply the cascade atomically.
        source_pon = _pon_of(bad_fat)
        source_a, source_b = _current_wings_without(source, bad_fat, pon=source_pon)
        src_before = len(source.fats)
        source.fats.remove(bad_fat)
        _apply_pon_scoped_full(source, source_pon, source_a, source_b)
        logger.log(
            f"[FDT-MOVE] FAT={bad_fat.name} FROM={source.name} "
            f"TO=<cascade depth {len(plan)}> SOURCE_BEFORE={src_before} "
            f"SOURCE_AFTER={len(source.fats)} REASON=CHAIN_REPAIR_CASCADE_RELAY"
        )

        carry = bad_fat
        step_names = [f"{source.name}:{bad_fat.name}"]
        for i, (fdt_step, incoming_fat, wa, wb, step_pon) in enumerate(plan):
            # If this step displaces, the displaced FAT becomes next carry
            # (already encoded because incoming_fat == prior carry). Remove it
            # from fdt_step BEFORE applying the new order that includes it.
            if i + 1 < len(plan):
                next_incoming = plan[i + 1][1]
                if next_incoming in fdt_step.fats:
                    fdt_step.fats.remove(next_incoming)
            _apply_pon_scoped_full(fdt_step, step_pon, wa, wb)
            incoming_fat.allocation_type = "chain-cascade-relay"
            step_names.append(f"→ {fdt_step.name}:{incoming_fat.name}")
            carry = incoming_fat

        logger.log("CHAIN-REPAIR cascade (depth %d): %s" % (len(plan), " ".join(step_names)))
        return True

    return False
