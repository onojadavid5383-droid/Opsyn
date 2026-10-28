"""Verbatim port of the FDT capacity-repair passes from
``FTTx Designer — dual PON integrated.py``: ``allocation_cost``,
``attempt_fdt_capacity_absorption``, ``re_absorb_along_street``,
``_rebalance_fdts_for_capacity`` — the global, convergent FDT capacity
rebalancer that runs after wing assignment.

No logic changes from the source script — only the QGIS types and
cross-module imports.

Note: ``MAX_BOX_TO_BOX_DISTANCE`` is one of the 8 tunables the pipeline
overrides per-run (see runtime_config.py's docstring) — every direct
reference reads ``runtime_config.MAX_BOX_TO_BOX_DISTANCE``.
``MAX_FAT_ABSORPTION_ROAD_DISTANCE``, by contrast, is a *derived* constant
(``= MAX_BOX_TO_BOX_DISTANCE`` at config.py's import time) that the source's
own ``_apply_config_to_globals()`` never re-derives when it overrides the
base value — the same pre-existing quirk as ``FDT_MAX_RADIUS`` in
fdt_generation.py. Preserved here as a plain static import, not "fixed."
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from .. import runtime_config as rc
from ..config import (
    CAPACITY_PROFILES,
    MAX_BOX_TO_BOX_DISTANCE as _CONFIG_MAX_BOX_TO_BOX_DISTANCE,
    PON_WINGS,
    WING_TO_PON,
    CapacityProfile,
    PONArchitecture,
    _balanced_partition_sizes,
)
from ..distance_oracle import _network_distance
from ..domain import FAT, FDT, RoadSegment
from ..fdt_anchor import _recompute_fdt_anchor, _renumber_fdt_wings
from ..fdt_generation import _apply_fat_traceability
from ..geometry_compat import QgsGeometry, QgsPointXY
from ..homepass_assignment import _parse_homepass_value
from ..perf_logger import PerformanceLogger
from ..spatial_utils import DistanceCalculator
from ..topology import RoadTopologyEngine
from ..wing_chain import _apply_explicit_wing_order, _best_valid_wing_insertion, _ordered_wing_fats

ABSORPTION_BOUNDARY_RATIO = 0.75
MAX_ABSORB_PER_PASS = 2
# New second-stage road-corridor fallback for FDT/FAT rebalancing.
# Keep the existing direct absorption path intact, but if the donor is too
# far by road-network distance, stop forcing a single long jump and try a
# road-connected intermediate seller-chain instead.
MAX_FAT_ABSORPTION_ROAD_DISTANCE = _CONFIG_MAX_BOX_TO_BOX_DISTANCE
MAX_REABSORB_STEP_ROAD_DISTANCE = 500.0
RE_ABSORB_ALONG_STREET_ENABLED = True

MAX_REBALANCE_ITERATIONS = 50


def allocation_cost(
    network_distance: float,
    boundary_violation: bool,
    sequence_disorder: int,
    fdt_capacity_imbalance: int,
    wing_imbalance: int,
    w_boundary: float = 500.0,
    w_sequence: float = 20.0,
    w_capacity: float = 50.0,
    w_wing: float = 25.0,
) -> float:
    """Lower is better for choosing between competing donor FDTs."""
    return (
        network_distance
        + (w_boundary if boundary_violation else 0.0)
        + w_sequence * sequence_disorder
        + w_capacity * fdt_capacity_imbalance
        + w_wing * wing_imbalance
    )


def attempt_fdt_capacity_absorption(
    fdts: List['FDT'],
    dist_calc: 'DistanceCalculator',
    logger: 'PerformanceLogger',
    topo: Optional['RoadTopologyEngine'] = None,
    profile: Optional['CapacityProfile'] = None,
) -> None:
    """Fill under-capacity FDTs by absorbing whole FATs from the nearest
    adjacent FDT when the receiver is short and the donor has spare capacity.

    This pass runs after generation+boundary-enforcement as a deliberate
    receiver-short / donor-spare capacity operation, rather than the earlier
    opportunistic per-hop borrowing logic.
    """
    if not fdts:
        return

    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    fdt_by_name = {f.name: f for f in fdts}

    for receiver in fdts:
        shortfall = profile.max_fat_per_fdt - len(receiver.fats)
        if shortfall <= 0:
            continue

        r_anchor = receiver.snapped_geometry or receiver.geometry

        candidates = []
        for donor in fdts:
            if donor.name == receiver.name:
                continue
            spare = len(donor.fats) - profile.min_fat_per_fdt
            if spare <= 0:
                continue

            d_anchor = donor.snapped_geometry or donor.geometry
            network_distance = _network_distance(
                r_anchor,
                d_anchor,
                road_a_id=receiver.primary_road_id,
                road_b_id=donor.primary_road_id,
                topo=topo,
                dist_calc=dist_calc,
            )

            n_to_take = min(shortfall, spare, MAX_ABSORB_PER_PASS)
            if n_to_take <= 0:
                continue

            donor_ranked = sorted(
                donor.fats,
                key=lambda fat: _network_distance(
                    fat.snapped_geometry or fat.geometry,
                    r_anchor,
                    road_a_id=fat.road_id,
                    road_b_id=receiver.primary_road_id,
                    topo=topo,
                    dist_calc=dist_calc,
                ),
            )
            moving = donor_ranked[:n_to_take]

            receiver_ordered = sorted(
                receiver.fats,
                key=lambda fat: _network_distance(
                    fat.snapped_geometry or fat.geometry,
                    r_anchor,
                    road_a_id=fat.road_id,
                    road_b_id=receiver.primary_road_id,
                    topo=topo,
                    dist_calc=dist_calc,
                ),
            )

            ordered = list(receiver_ordered)
            sequence_disorder = 0
            for fat in sorted(
                moving,
                key=lambda fat: _network_distance(
                    fat.snapped_geometry or fat.geometry,
                    r_anchor,
                    road_a_id=fat.road_id,
                    road_b_id=receiver.primary_road_id,
                    topo=topo,
                    dist_calc=dist_calc,
                ),
            ):
                fat_dist = _network_distance(
                    fat.snapped_geometry or fat.geometry,
                    r_anchor,
                    road_a_id=fat.road_id,
                    road_b_id=receiver.primary_road_id,
                    topo=topo,
                    dist_calc=dist_calc,
                )
                insert_pos = 0
                while insert_pos < len(ordered) and _network_distance(
                    ordered[insert_pos].snapped_geometry or ordered[insert_pos].geometry,
                    r_anchor,
                    road_a_id=ordered[insert_pos].road_id,
                    road_b_id=receiver.primary_road_id,
                    topo=topo,
                    dist_calc=dist_calc,
                ) < fat_dist:
                    insert_pos += 1
                ordered.insert(insert_pos, fat)
                sequence_disorder += insert_pos

            boundary_violation = (
                receiver.primary_road_id is None
                or donor.primary_road_id is None
                or receiver.primary_road_id != donor.primary_road_id
            )
            capacity_imbalance = (
                abs(len(donor.fats) - 1 - profile.max_fat_per_fdt)
                + abs(len(receiver.fats) + 1 - profile.max_fat_per_fdt)
            )
            # Wing-imbalance heuristic generalized to however many wings the
            # architecture has (2 for Single-PON, 4 for Dual-PON) — spread
            # across profile.wings instead of a hardcoded A/B pair.
            wing_counts = {label: sum(1 for fat in receiver.fats if fat.wing == label)
                           for label in profile.wings}
            for fat in moving:
                if fat.wing in wing_counts:
                    wing_counts[fat.wing] += 1
            wing_imbalance = (max(wing_counts.values()) - min(wing_counts.values())) if wing_counts else 0

            cost = allocation_cost(
                network_distance,
                boundary_violation,
                sequence_disorder,
                capacity_imbalance,
                wing_imbalance,
            )
            candidates.append((cost, network_distance, donor, spare, moving))

        if not candidates:
            logger.log(
                f"WARNING [ABSORPTION_NO_DONOR]: {receiver.name} short "
                f"{shortfall} FAT(s), no donor with spare capacity found."
            )
            # Stage 2: do not force a long direct FAT jump when the road
            # graph says every donor is outside the configured reach. Try the
            # road-corridor fallback instead of replacing the direct path.
            if RE_ABSORB_ALONG_STREET_ENABLED:
                moved = re_absorb_along_street(
                    fdts,
                    receiver,
                    dist_calc,
                    logger,
                    topo,
                    profile,
                )
                if moved:
                    logger.log(
                        f"[RE_ABSORB_ALONG_STREET] accepted one road-corridor FAT movement "
                        f"for receiver={receiver.name}"
                    )
                else:
                    logger.log(
                        f"[RE_ABSORB_ALONG_STREET] no valid road-corridor chain for "
                        f"receiver={receiver.name}; leaving unresolved."
                    )
            continue

        candidates.sort(key=lambda t: t[0])
        _, _, donor, spare, moving = candidates[0]
        n_to_take = min(shortfall, spare, MAX_ABSORB_PER_PASS)
        if n_to_take <= 0:
            continue

        if len(moving) > n_to_take:
            moving = moving[:n_to_take]

        for fat in moving:
            hop_dist = _network_distance(
                fat.snapped_geometry or fat.geometry,
                r_anchor,
                road_a_id=fat.road_id,
                road_b_id=receiver.primary_road_id,
                topo=topo,
                dist_calc=dist_calc,
            )
            if hop_dist > rc.MAX_BOX_TO_BOX_DISTANCE:
                logger.log(
                    f"ABSORPTION_REJECTED: {fat.name} → {receiver.name} "
                    f"would be {hop_dist:.0f}m, exceeds {rc.MAX_BOX_TO_BOX_DISTANCE}m cap."
                )
                continue

            donor.fats.remove(fat)
            receiver.fats.append(fat)
            fat.logical_fdt = receiver.name
            fat.allocation_type = "absorbed"
            fat.network_dist_to_fdt = round(hop_dist, 2)

            logger.log(
                f"ABSORBED {fat.name} (physical={fat.physical_fdt}): "
                f"{donor.name} → {receiver.name}, dist={hop_dist:.0f}m"
            )

        for f in (donor, receiver):
            # v16 fix: anchor must be current BEFORE the angular split runs,
            # not after — recompute the centroid anchor first, then
            # re-derive wings/sequence against that fresh anchor.
            _recompute_fdt_anchor(f, roads=None)
            _renumber_fdt_wings(f, dist_calc=dist_calc, profile=profile)
            f.total_fat = len(f.fats)
            f.total_customers = sum(_parse_homepass_value(x.total_customers) for x in f.fats)


def re_absorb_along_street(
    fdts: List['FDT'],
    receiver: 'FDT',
    dist_calc: 'DistanceCalculator',
    logger: 'PerformanceLogger',
    topo: Optional['RoadTopologyEngine'] = None,
    profile: Optional['CapacityProfile'] = None,
) -> bool:
    """RE_ABSORB_ALONG_STREET — Mode 2 road-corridor rebalancing fallback.

    Mode 1 (the direct-absorption loop in attempt_fdt_capacity_absorption)
    already tried a direct donor and found none within
    MAX_FAT_ABSORPTION_ROAD_DISTANCE. This stage does NOT then reach for
    the nearest distant donor and teleport a FAT straight into `receiver`
    — that "safe chain, unsafe move" pattern was the defect in the
    previous version of this function: it built and validated a
    step-limited road corridor, then ignored it and moved the FAT donor
    -> receiver in a single hop anyway, which could (and did) exceed the
    real cable-length cap the corridor check was supposed to protect.

    Instead: find the actual road corridor between `receiver` and a
    candidate donor (RoadTopologyEngine.weighted_shortest_path — Dijkstra,
    never straight-line), order every other FDT that sits on that corridor
    by its position along the path (never by raw proximity, so a nearby
    FDT that is not actually "on the way" cannot be used as a bridge), and
    walk capacity down the corridor one hop at a time: each intermediate
    FDT receives a FAT from its donor-side neighbour and, in the same
    sweep, hands its own nearest-to-receiver FAT to its receiver-side
    neighbour. Every hop is validated through the exact same
    _best_valid_wing_insertion() check every other insertion in this file
    uses, so a hop can never be accepted here that would fail the real
    box-to-box cable-length gate — MAX_REABSORB_STEP_ROAD_DISTANCE only
    widens how far the SEARCH looks for a corridor, it never substitutes
    for that check.

    No FDT (donor, intermediate, or receiver) is ever pushed outside
    [profile.min_fat_per_fdt, profile.max_fat_per_fdt] by this function,
    and no additional FDT is ever created — every hop is either a genuine
    donation from the true donor end (which starts strictly above the
    floor) or a net-zero relay through an intermediate.
    """
    if not fdts or receiver is None:
        return False
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]

    if len(receiver.fats) >= profile.min_fat_per_fdt:
        return False

    required_fats = profile.min_fat_per_fdt - len(receiver.fats)
    remaining_required_fats = required_fats
    r_anchor = receiver.snapped_geometry or receiver.geometry

    if topo is None:
        logger.log(
            f"[RE_ABSORB_ALONG_STREET] Receiver={receiver.name}: no topology "
            f"engine available — road corridor cannot be determined."
        )
        return False

    # ── 1. Rank candidate donors ──────────────────────────────────────────
    # Only FDTs strictly above the floor, and only ones Mode 1 already
    # declined (direct reach beyond MAX_FAT_ABSORPTION_ROAD_DISTANCE) — this
    # stage exists precisely for that case, never to compete with Mode 1.
    donor_candidates: List[Tuple[float, 'FDT']] = []
    for donor in fdts:
        if donor is receiver or len(donor.fats) <= profile.min_fat_per_fdt:
            continue
        d_anchor = donor.snapped_geometry or donor.geometry
        direct = _network_distance(
            r_anchor, d_anchor,
            road_a_id=receiver.primary_road_id, road_b_id=donor.primary_road_id,
            topo=topo, dist_calc=dist_calc,
        )
        if direct <= MAX_FAT_ABSORPTION_ROAD_DISTANCE:
            continue
        donor_candidates.append((direct, donor))
    donor_candidates.sort(key=lambda t: t[0])

    if not donor_candidates:
        logger.log(
            f"[RE_ABSORB_ALONG_STREET] Receiver={receiver.name}: no donor "
            f"FDT exists beyond the direct-absorption envelope — nothing "
            f"for this stage to do."
        )
        return False

    any_progress = False

    for _direct, donor in donor_candidates:
        if remaining_required_fats <= 0:
            break

        # ── 2/3. Find the road corridor and order every FDT along it ────
        d_anchor = donor.snapped_geometry or donor.geometry
        path_geom, _path_len = topo.weighted_shortest_path(
            r_anchor, d_anchor,
            start_road_id=receiver.primary_road_id,
            end_road_id=donor.primary_road_id,
        )
        if path_geom is None or path_geom.isEmpty():
            logger.log(
                f"[RE_ABSORB_ALONG_STREET] Receiver={receiver.name} "
                f"Donor={donor.name}: no road corridor exists — skipped."
            )
            continue

        def _path_position(fdt: 'FDT') -> Optional[float]:
            anchor = fdt.snapped_geometry or fdt.geometry
            if anchor is None:
                return None
            near = path_geom.nearestPoint(QgsGeometry.fromPointXY(anchor))
            if near is None or near.isEmpty():
                return None
            near_pt = near.asPoint()
            off_path = dist_calc.distance_points(anchor, near_pt) if dist_calc else 0.0
            if off_path > MAX_REABSORB_STEP_ROAD_DISTANCE:
                return None   # not really "on" this corridor
            return path_geom.lineLocatePoint(QgsGeometry.fromPointXY(near_pt))

        intermediates: List[Tuple[float, 'FDT']] = []
        for other in fdts:
            if other is receiver or other is donor:
                continue
            if len(other.fats) < profile.min_fat_per_fdt:
                continue  # §10: never use an already-underfilled FDT as a bridge
            pos = _path_position(other)
            if pos is not None:
                intermediates.append((pos, other))
        intermediates.sort(key=lambda t: t[0])
        road_chain: List['FDT'] = [receiver] + [f for _, f in intermediates] + [donor]

        # ── 4/11. Directional, per-step distance-limited corridor check ──
        chain_ok = True
        for left, right in zip(road_chain, road_chain[1:]):
            step = _network_distance(
                left.snapped_geometry or left.geometry,
                right.snapped_geometry or right.geometry,
                road_a_id=left.primary_road_id, road_b_id=right.primary_road_id,
                topo=topo, dist_calc=dist_calc,
            )
            if step > MAX_REABSORB_STEP_ROAD_DISTANCE:
                chain_ok = False
                break
        if not chain_ok:
            logger.log(
                f"[RE_ABSORB_ALONG_STREET] Receiver={receiver.name} "
                f"Donor={donor.name}: corridor step exceeds "
                f"{MAX_REABSORB_STEP_ROAD_DISTANCE:.0f}m — rejected."
            )
            continue

        logger.log(
            "[RE_ABSORB_ALONG_STREET]\n"
            f"Receiver: {receiver.name}\n"
            f"Donor: {donor.name}\n"
            f"Road Chain: {' -> '.join(f.name for f in road_chain)}\n"
            f"Required FATs: {remaining_required_fats}"
        )

        # ── 5/7/8/9/12. Walk the chain, relaying capacity one FAT at a ───
        # time from the donor end toward the receiver, one sweep per unit
        # of deficit, until remaining_required_fats reaches 0 or a full
        # sweep makes no progress at all.
        step_no = 0
        chain_progress = True
        while remaining_required_fats > 0 and chain_progress:
            chain_progress = False
            for i in range(len(road_chain) - 1, 0, -1):
                if remaining_required_fats <= 0:
                    break
                giver = road_chain[i]
                taker = road_chain[i - 1]
                # §9 donor/intermediate release protection: re-checked live
                # on every visit, so an intermediate that already received
                # its own inbound FAT earlier in THIS sweep is correctly
                # allowed to give here, and one that hasn't is correctly
                # refused.
                if len(giver.fats) <= profile.min_fat_per_fdt:
                    continue
                if len(taker.fats) >= profile.max_fat_per_fdt:
                    continue

                taker_anchor = taker.snapped_geometry or taker.geometry
                candidate_fats = sorted(
                    giver.fats,
                    key=lambda fat: _network_distance(
                        fat.snapped_geometry or fat.geometry, taker_anchor,
                        road_a_id=fat.road_id, road_b_id=taker.primary_road_id,
                        topo=topo, dist_calc=dist_calc,
                    ),
                )
                for fat in candidate_fats:
                    cand_pon = WING_TO_PON.get(getattr(fat, 'wing', None), 1)
                    insertion = _best_valid_wing_insertion(
                        taker, fat, dist_calc=dist_calc, topo=topo,
                        pon=cand_pon, profile=profile,
                    )
                    if insertion is None:
                        continue

                    step_dist = _network_distance(
                        fat.snapped_geometry or fat.geometry, taker_anchor,
                        road_a_id=fat.road_id, road_b_id=taker.primary_road_id,
                        topo=topo, dist_calc=dist_calc,
                    )

                    giver.fats.remove(fat)
                    _recompute_fdt_anchor(giver, roads=None)
                    _renumber_fdt_wings(giver, dist_calc=dist_calc, profile=profile)

                    _, wa, wb = insertion
                    wlo, whi = PON_WINGS[cand_pon]
                    wings: Dict[str, List['FAT']] = {wlo: wa, whi: wb}
                    other_pon = {1: 2, 2: 1}.get(cand_pon)
                    if other_pon in PON_WINGS:
                        olo, ohi = PON_WINGS[other_pon]
                        wings[olo] = _ordered_wing_fats(taker, olo)
                        wings[ohi] = _ordered_wing_fats(taker, ohi)
                    _apply_explicit_wing_order(
                        taker, [], [], dist_calc=dist_calc, topo=topo,
                        wings=wings, profile=profile,
                    )
                    fat.allocation_type = "re_absorb_along_street"

                    step_no += 1
                    logger.log(
                        f"Step {step_no}:\n"
                        f"{giver.name} -> {taker.name}\n"
                        f"Dijkstra: {step_dist:.0f} m\n"
                        f"Status: ACCEPTED"
                    )
                    chain_progress = True
                    any_progress = True
                    if taker is receiver:
                        remaining_required_fats -= 1
                    break   # this link is done for this sweep

        for fdt in road_chain:
            fdt.total_fat = len(fdt.fats)
            fdt.total_customers = sum(
                _parse_homepass_value(x.total_customers) for x in fdt.fats
            )

        if remaining_required_fats <= 0:
            logger.log("Remaining deficit: 0\nSTATUS: RE-ABSORB SUCCESSFUL")
            return True

        logger.log(
            f"Remaining deficit: {remaining_required_fats}\n"
            f"STATUS: RE-ABSORB PARTIAL — trying next candidate donor, if any"
        )

    if any_progress:
        return True

    logger.log(
        f"[RE_ABSORB_ALONG_STREET] Receiver={receiver.name}: no valid road "
        f"corridor yielded any capacity among {len(donor_candidates)} "
        f"candidate donor(s). Leaving unresolved — not forcing a movement."
    )
    return False


def _rebalance_fdts_for_capacity(
    fdts: List['FDT'],
    dist_calc: Optional['DistanceCalculator'],
    logger: 'PerformanceLogger',
    topo: Optional['RoadTopologyEngine'] = None,
    profile: Optional['CapacityProfile'] = None,
    roads: Optional[Dict[int, 'RoadSegment']] = None,
    max_iterations: int = MAX_REBALANCE_ITERATIONS,
) -> List['FDT']:
    """Global, convergent FDT capacity rebalancer (spec §5-§9).

    Unlike ``attempt_fdt_capacity_absorption`` (a single bounded pass capped
    at ``MAX_ABSORB_PER_PASS`` FATs per receiver), this iterates FAT-level
    moves to convergence, and — when the existing FDT count cannot possibly
    satisfy capacity no matter how FATs are shuffled — dissolves/merges whole
    FDTs, so the design lands on the mathematically correct global FDT count
    (spec §8) and every FDT sits in
    ``[profile.min_fat_per_fdt, profile.max_fat_per_fdt]`` (spec §13), not
    just "improved but still short because of a two-FAT-per-pass cap."

    Geographic affinity is preserved throughout (spec §5): every donor/
    receiver pairing is ranked by the existing network-distance engine
    (``_network_distance``), never Euclidean-only, and every FAT move
    immediately recomputes ``logical_fdt``, FDT anchor, wings, and totals
    (spec §17) via the existing ``_recompute_fdt_anchor`` /
    ``_renumber_fdt_wings`` / ``_apply_fat_traceability`` helpers — there is
    no second, competing capacity model (spec §24).

    "Healthy" FDTs (comfortably above min, including ones sitting at MAX)
    may donate to an underfilled FDT, not just other underfilled FDTs
    (spec §7) — donors are ranked purely by network distance to the
    receiver, so a 16-FAT donor and a 15-FAT donor compete on equal footing.
    """
    if not fdts:
        return fdts

    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    min_fdt = profile.min_fat_per_fdt
    max_fdt = profile.max_fat_per_fdt

    total_fats = sum(len(f.fats) for f in fdts)
    if total_fats == 0:
        return fdts

    target_sizes, _ = _balanced_partition_sizes(total_fats, min_fdt, max_fdt)
    target_k = len(target_sizes)

    logger.log(f"[FDT-CAPACITY] Total FATs={total_fats}")
    logger.log(f"[FDT-CAPACITY] Allowed range={min_fdt}-{max_fdt} FAT/FDT")
    logger.log(
        f"[FDT-CAPACITY] Valid FDT count range="
        f"{-(-total_fats // max_fdt)}-{total_fats // min_fdt}"
    )
    logger.log(f"[FDT-CAPACITY] Selected FDT count={target_k}")

    def _anchor(f: 'FDT') -> QgsPointXY:
        return f.snapped_geometry or f.geometry

    def _fdt_dist(a: 'FDT', b: 'FDT') -> float:
        return _network_distance(
            _anchor(a), _anchor(b),
            road_a_id=a.primary_road_id, road_b_id=b.primary_road_id,
            topo=topo, dist_calc=dist_calc,
        )

    def _fat_dist_to(fat: 'FAT', target: 'FDT') -> float:
        return _network_distance(
            fat.snapped_geometry or fat.geometry, _anchor(target),
            road_a_id=fat.road_id, road_b_id=target.primary_road_id,
            topo=topo, dist_calc=dist_calc,
        )

    def _refresh(f: 'FDT') -> None:
        if not f.fats:
            return
        _recompute_fdt_anchor(f, roads=roads)
        _renumber_fdt_wings(f, dist_calc=dist_calc, profile=profile)
        f.total_fat = len(f.fats)
        f.total_customers = sum(_parse_homepass_value(x.total_customers) for x in f.fats)
        _apply_fat_traceability(f, dist_calc=dist_calc, topo=topo, roads=roads)

    def _move_fat(fat: 'FAT', donor: 'FDT', receiver: 'FDT', hop_dist: float) -> None:
        donor_before, receiver_before = len(donor.fats), len(receiver.fats)
        donor.fats.remove(fat)
        receiver.fats.append(fat)
        fat.logical_fdt = receiver.name
        fat.allocation_type = "absorbed"
        fat.network_dist_to_fdt = round(hop_dist, 2)
        logger.log(
            f"[FDT-REBALANCE] donor={donor.name} receiver={receiver.name} "
            f"FAT={fat.name} donor_before={donor_before} "
            f"receiver_before={receiver_before} donor_after={donor_before - 1} "
            f"receiver_after={receiver_before + 1} network_distance={hop_dist:.0f}m"
        )

    # ── Phase 0: split any FDT above MAX (defensive) ────────────────────────
    # generate_fdts() already guarantees no group is emitted above MAX, but
    # this rebalancer is also re-invoked later in the pipeline after other
    # mutation passes (wing assignment, relay repair) — never assume an
    # upstream invariant holds; enforce the max bound here too using the
    # same authoritative partitioner, rather than crashing on it deep inside
    # _renumber_fdt_wings's own cap check.
    _split_counter = 0

    def _next_split_name(base_name: str) -> str:
        nonlocal _split_counter
        _split_counter += 1
        return f"{base_name}-SPLIT{_split_counter}"

    split_overflow: List['FDT'] = []
    for fdt in fdts:
        if len(fdt.fats) <= max_fdt:
            continue
        sizes, _ = _balanced_partition_sizes(len(fdt.fats), min_fdt, max_fdt)
        ordered = sorted(fdt.fats, key=lambda fat: _fat_dist_to(fat, fdt))
        chunks, idx = [], 0
        for size in sizes:
            chunks.append(ordered[idx: idx + size])
            idx += size
        fdt.fats = chunks[0]
        for fat in fdt.fats:
            fat.logical_fdt = fdt.name
        _refresh(fdt)
        for extra_chunk in chunks[1:]:
            new_fdt = FDT(
                name=_next_split_name(fdt.name),
                geometry=fdt.geometry,
                total_customers=0, total_fat=0,
                wing_a_count=0, wing_b_count=0,
                fats=extra_chunk,
                primary_road_id=fdt.primary_road_id,
            )
            for fat in extra_chunk:
                fat.logical_fdt = new_fdt.name
                fat.allocation_type = "absorbed"
            _refresh(new_fdt)
            split_overflow.append(new_fdt)
            logger.log(
                f"[FDT-REBALANCE] {fdt.name} exceeded MAX — overflow split "
                f"into {new_fdt.name} ({len(extra_chunk)} FATs)"
            )
    if split_overflow:
        fdts = fdts + split_overflow

    # ── Phase 1: iterative FAT-level rebalancing (spec §6/§7) ──────────────
    # Runs until every FDT clears MIN, or no further legal move exists, or
    # max_iterations is hit (hard loop-safety cap, spec §6).
    for _iteration in range(max_iterations):
        fdts = [f for f in fdts if f.fats]
        receivers = sorted(
            (f for f in fdts if len(f.fats) < min_fdt and not f.is_global_final_fdt_exception),
            key=lambda f: len(f.fats),
        )
        if not receivers:
            break

        moved_any = False
        for receiver in receivers:
            shortfall = min_fdt - len(receiver.fats)
            if shortfall <= 0:
                continue

            donors = sorted(
                (d for d in fdts if d.name != receiver.name and len(d.fats) > min_fdt),
                key=lambda d: _fdt_dist(receiver, d),
            )
            for donor in donors:
                if shortfall <= 0 or len(receiver.fats) >= max_fdt:
                    break
                spare = len(donor.fats) - min_fdt
                if spare <= 0:
                    continue
                n_to_take = min(shortfall, spare, max_fdt - len(receiver.fats))
                if n_to_take <= 0:
                    continue
                donor_ranked = sorted(donor.fats, key=lambda fat: _fat_dist_to(fat, receiver))
                for fat in donor_ranked[:n_to_take]:
                    hop_dist = _fat_dist_to(fat, receiver)
                    if hop_dist > rc.MAX_BOX_TO_BOX_DISTANCE * 2:
                        # Never silently create a physically absurd cable run,
                        # even though this pass is allowed a wider reach than
                        # same-generation absorption (it is the authoritative
                        # global-convergence fix, spec §6).
                        continue
                    _move_fat(fat, donor, receiver, hop_dist)
                    shortfall -= 1
                    moved_any = True
                _refresh(donor)
            _refresh(receiver)

        if not moved_any:
            break

    # ── Phase 2: pool + re-derive (spec §5 STEP 3, §8) ──────────────────────
    # A greedy "dissolve victim into nearest neighbour, filling it to MAX"
    # cannot generally reach the mathematically optimal global partition —
    # it overfills early neighbours to MAX and can strand a later victim
    # with an unnecessarily large, avoidable shortfall (verified: on the
    # 182-FAT/Dual-PON regression case, greedy-fill converged to eleven
    # 16s + one stranded 6, needing a false "final exception", even though
    # a clean 12x(16,16,15x10) split exists with none). Instead: for each
    # FDT still below MIN after Phase 1, grow a geographically-ordered pool
    # — starting from the victim, absorbing its nearest not-yet-pooled FDT
    # one at a time — until _balanced_partition_sizes finds an EXACT valid
    # split for the pooled FAT count, then materialise that split back into
    # exactly that many FDTs. This is the same pool -> re-derive-sizes
    # pattern generate_fdts's own underfilled-group merge passes already
    # use, just applied globally instead of per-corridor.
    #
    # A victim this pass can't find a valid pool for is recorded in
    # blocked_fdt_victims and skipped, NOT treated as proof the whole
    # global rebalancer is finished — this matters far more on a tight
    # range like Single-PON's 7-8 (gap of 1) than on Dual-PON's 14-16
    # (gap of 2), since a narrow range makes it much easier for a
    # particular pool-growth order to exhaust every reachable neighbour
    # without hitting an exact K, even when a DIFFERENT victim (or the
    # same victim with one more neighbour pulled in later) is perfectly
    # solvable. Cleared whenever the population actually changes.
    def _grow_pool(victim: 'FDT', candidates: List['FDT'], respect_cap: bool):
        """Grow a geographically-ordered pool starting from `victim` until
        _balanced_partition_sizes finds an exact valid split, or
        `candidates` is exhausted. When `respect_cap` is True, a candidate
        farther than MAX_BOX_TO_BOX_DISTANCE*4 is skipped (recorded, not
        merged) rather than aborting the search — spec item 14. Returns
        (pool_fdts, sizes, exact, skipped_log_lines).
        """
        pool_fdts = [victim]
        sizes, exact = _balanced_partition_sizes(len(victim.fats), min_fdt, max_fdt)
        skipped: List[str] = []
        for candidate in candidates:
            if exact:
                break
            if respect_cap:
                hop = _fdt_dist(victim, candidate)
                if hop > rc.MAX_BOX_TO_BOX_DISTANCE * 4:
                    skipped.append(f"{candidate.name}: {hop:.0f}m exceeds allowed reach")
                    continue
            pool_fdts.append(candidate)
            pool_total = sum(len(f.fats) for f in pool_fdts)
            sizes, exact = _balanced_partition_sizes(pool_total, min_fdt, max_fdt)
        return pool_fdts, sizes, exact, skipped

    def _footprint(fats_list: List['FAT']) -> float:
        """Max pairwise straight-line distance among a chunk's members —
        a cheap proxy for how geographically compact the resulting FDT
        will be. Not the same metric as an actual routed wing-chain hop
        (that depends on road topology and sequencing, computed much
        later by the real cable router), but a group whose own members
        are already >250m apart from each other has essentially no
        chance of producing a compliant wing chain no matter how it's
        sequenced — so this is a real, useful early warning.
        """
        if len(fats_list) <= 1 or dist_calc is None:
            return 0.0
        pts = [f.snapped_geometry or f.geometry for f in fats_list]
        worst = 0.0
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                d = dist_calc.distance_points(pts[i], pts[j])
                if d > worst:
                    worst = d
        return worst

    def _footprint_aware_sizes(pool_fats_sorted: List['FAT'], total: int) -> Tuple[List[int], bool]:
        """[Cost-reduction fix] Among every K that's mathematically valid
        for `total` (spec §3/§4), _balanced_partition_sizes always returns
        the lowest one — correct for minimizing device count when
        geography is uniform, but on real, unevenly-dense road networks
        that alone regularly produces FDTs whose members are spread far
        enough apart that no wing sequencing can keep every hop under
        MAX_BOX_TO_BOX_DISTANCE (confirmed against real QGIS output: 58-67%
        of FDTs affected in the reported runs — a systemic conflict
        between "fewest FDTs" and "compact FDTs" on this data, not a rare
        corner case). This evaluates every valid K's resulting chunks
        (sliced from the same distance-ordered pool _materialize_pool
        will use) and prefers whichever K keeps every chunk's own
        footprint smallest — i.e. accepts a few more FDTs only when doing
        so measurably tightens geographic compactness, never as a matter
        of course. Falls back to the plain lowest-K answer whenever only
        one K is valid, or when a larger K doesn't actually help (ties
        broken toward the lower K), so this never trades away the
        material-optimization objective for no real geographic benefit.
        """
        k_min = -(-total // max_fdt)
        k_max = total // min_fdt if min_fdt else 0
        if k_min <= 0 or k_min > k_max:
            return _balanced_partition_sizes(total, min_fdt, max_fdt)
        if k_min == k_max:
            base, remainder = divmod(total, k_min)
            return [base + 1 if i < remainder else base for i in range(k_min)], True

        best_sizes, best_worst = None, None
        for k in range(k_min, k_max + 1):
            base, remainder = divmod(total, k)
            sizes = [base + 1 if i < remainder else base for i in range(k)]
            idx = 0
            worst = 0.0
            for size in sizes:
                chunk = pool_fats_sorted[idx: idx + size]
                idx += size
                fp = _footprint(chunk)
                if fp > worst:
                    worst = fp
            # Meaningful improvement threshold (5m) avoids churn between
            # two K's that are geographically equivalent within noise.
            if best_worst is None or worst < best_worst - 5.0:
                best_sizes, best_worst = sizes, worst
        return best_sizes, True

    def _materialize_pool(pool_fdts: List['FDT'], sizes: List[int], victim: 'FDT') -> None:
        """Split the pool's combined FATs into exactly len(sizes) groups,
        reusing the first len(sizes) pool FDTs as containers (geographically
        ordered by distance to the victim's anchor) and dissolving the rest.
        """
        pool_fats: List['FAT'] = [fat for f in pool_fdts for fat in f.fats]
        pool_fats.sort(key=lambda fat: _fat_dist_to(fat, victim))
        idx = 0
        target_fdts = pool_fdts[:len(sizes)]
        for i, size in enumerate(sizes):
            chunk = pool_fats[idx: idx + size]
            idx += size
            target = target_fdts[i]
            target.fats = chunk
            for fat in chunk:
                fat.logical_fdt = target.name
                fat.allocation_type = "absorbed"
                fat.network_dist_to_fdt = round(_fat_dist_to(fat, target), 2)
            _refresh(target)
        for extra in pool_fdts[len(sizes):]:
            extra.fats = []
            logger.log(f"[FDT-REBALANCE] {extra.name} fully dissolved into pool re-derivation (spec §8)")

    blocked_fdt_victims: Set[str] = set()
    for _iteration in range(max_iterations):
        fdts = [f for f in fdts if f.fats]
        underfilled = [
            f for f in fdts
            if len(f.fats) < min_fdt and f.name not in blocked_fdt_victims
        ]
        if not underfilled:
            break

        victim = min(underfilled, key=lambda f: len(f.fats))
        remaining = sorted(
            (f for f in fdts if f.name != victim.name),
            key=lambda f: _fdt_dist(victim, f),
        )
        pool_fdts, sizes, exact, pool_blocked = _grow_pool(victim, remaining, respect_cap=True)
        if exact and len(pool_fdts) > 1:
            _pool_total = sum(len(f.fats) for f in pool_fdts)
            _pool_fats_sorted = sorted(
                (fat for f in pool_fdts for fat in f.fats),
                key=lambda fat: _fat_dist_to(fat, victim),
            )
            sizes, exact = _footprint_aware_sizes(_pool_fats_sorted, _pool_total)

        if len(pool_fdts) == 1 and not pool_blocked:
            # No other FDT exists in the design at all to pool with.
            blocked_fdt_victims.add(victim.name)
            logger.log(

                f"[FDT-REBALANCE-BLOCKED] {victim.name} = {len(victim.fats)} FATs "
                f"— no other FDT exists to pool with."
            )
            continue

        if not exact and pool_blocked:
            # [FDT patch §12/§13/§14, mirrors the earlier FAT-rebalancer
            # fix]: some candidates were skipped for being geographically
            # too far — this victim's LOCAL neighbourhood doesn't resolve,
            # but forcing a merge across the reach cap would violate spec
            # item 14 ("do not solve capacity by blindly merging distant
            # FDTs"). Record it as blocked and move on to the next weakest
            # still-eligible victim instead — a different victim's own
            # local neighbourhood (or this one's, after the population
            # changes from someone else's successful merge) may resolve
            # where this one didn't. Phase 2b below is the last-resort
            # fallback if this leaves more than one FDT stuck.
            blocked_fdt_victims.add(victim.name)
            logger.log(
                f"[FDT-REBALANCE-BLOCKED] {victim.name} = {len(victim.fats)} FATs "
                f"— no valid pool found among {len(pool_fdts)} reachable "
                f"candidate FDT(s) (pooled total="
                f"{sum(len(f.fats) for f in pool_fdts)}, required range="
                f"[{min_fdt},{max_fdt}] per FDT)"
            )
            for line in pool_blocked[:5]:
                logger.log(f"  {line}")
            continue

        # Either exact==True (normal success), or exact==False with
        # pool_blocked empty — meaning every OTHER FDT remaining in the
        # design was already tried (nothing was skipped for distance) and
        # STILL no valid K exists. That is genuine global infeasibility,
        # not a local/geographic search failure, so this materialises
        # _balanced_partition_sizes's own fallback (max-fill with the
        # unavoidable shortfall isolated into exactly one group) instead
        # of looping forever — matching its documented contract and
        # guaranteeing Phase 3 sees at most one exception candidate here.
        _materialize_pool(pool_fdts, sizes, victim)
        logger.log(
            f"[FDT-REBALANCE] pool-rebalance: {[f.name for f in pool_fdts]} "
            f"({sum(len(f.fats) for f in pool_fdts)} FATs) -> {len(sizes)} FDT(s), "
            f"sizes={sizes}, exact={exact}"
        )

        # Population changed — a previously-blocked victim may be
        # repairable now (mirrors the FAT-rebalancer's convergence fix).
        blocked_fdt_victims.clear()

    fdts = [f for f in fdts if f.fats]

    # ── Phase 2b: last-resort, geography-unlimited consolidation ───────────
    # The capped search above (Phase 2) is the PREFERRED path and always
    # runs first — it's what keeps merges geographically sane. But if it
    # still leaves more than one FDT below MIN, each blocked purely by the
    # reach cap rather than by mathematics, give up on the geography
    # constraint as a genuine last resort before accepting multiple
    # underfilled FDTs: pooling several blocked FDTs together (or with a
    # previously-out-of-reach donor) can satisfy _balanced_partition_sizes
    # even when no single capped pairing could — e.g. {6,3,4}=13 is
    # infeasible alone (ceil(13/8)=2 > floor(13/7)=1) no matter how close
    # together those three are, and needs a 4th FDT pulled in from
    # wherever one is reachable at all. This only runs when Phase 2 left
    # 2+ FDTs stuck; a single remaining low FDT is left for Phase 3 to
    # flag as the legitimate final exception without ever being routed
    # through here.
    still_blocked = [f for f in fdts if len(f.fats) < min_fdt]
    if len(still_blocked) > 1:
        logger.log(
            f"[FDT-REBALANCE] {len(still_blocked)} FDT(s) remain below minimum "
            f"after the geography-respecting search "
            f"({[(f.name, len(f.fats)) for f in still_blocked]}) — attempting "
            f"one last-resort consolidation without the reach cap before "
            f"treating this as genuinely unresolvable."
        )
        for _iteration in range(max_iterations):
            fdts = [f for f in fdts if f.fats]
            still_blocked = [f for f in fdts if len(f.fats) < min_fdt]
            if len(still_blocked) <= 1:
                break
            victim = min(still_blocked, key=lambda f: len(f.fats))
            remaining = sorted(
                (f for f in fdts if f.name != victim.name),
                key=lambda f: _fdt_dist(victim, f),
            )
            pool_fdts, sizes, exact, _ = _grow_pool(victim, remaining, respect_cap=False)
            if len(pool_fdts) == 1:
                break  # truly nothing else exists in the design
            if exact:
                _pool_total2 = sum(len(f.fats) for f in pool_fdts)
                _pool_fats_sorted2 = sorted(
                    (fat for f in pool_fdts for fat in f.fats),
                    key=lambda fat: _fat_dist_to(fat, victim),
                )
                sizes, exact = _footprint_aware_sizes(_pool_fats_sorted2, _pool_total2)
            _materialize_pool(pool_fdts, sizes, victim)
            logger.log(
                f"[FDT-REBALANCE] last-resort (reach cap lifted) pool-rebalance: "
                f"{[f.name for f in pool_fdts]} -> {len(sizes)} FDT(s), "
                f"sizes={sizes}, exact={exact}"
            )
        fdts = [f for f in fdts if f.fats]

    # ── Phase 3: single explicit global final FDT exception (spec §12) ─────
    still_low = [f for f in fdts if len(f.fats) < min_fdt]
    if len(still_low) == 1:
        still_low[0].is_global_final_fdt_exception = True
        logger.log(
            f"[FDT-CAPACITY] Global final FDT exception: {still_low[0].name} "
            f"({len(still_low[0].fats)} FATs, below minimum {min_fdt}) — "
            f"no further legal geographic move exists; flagged as the single "
            f"permitted exception."
        )
    elif len(still_low) > 1:
        for f in still_low:
            logger.log(
                f"WARNING [FDT_BELOW_MINIMUM]: {f.name} has {len(f.fats)} FATs "
                f"(< {min_fdt}); {len(still_low)} FDTs remain below minimum — "
                f"only ONE global final-FDT exception is permitted. This "
                f"design will fail hard-gate validation."
            )

    for f in fdts:
        _refresh(f)

    distribution = sorted((len(f.fats) for f in fdts), reverse=True)
    logger.log(f"[FDT-CAPACITY] Target distribution={target_sizes}")
    logger.log(f"[FDT-CAPACITY] Actual FDT count={len(fdts)}, distribution={distribution}")
    invalid = [
        f for f in fdts
        if not (min_fdt <= len(f.fats) <= max_fdt) and not f.is_global_final_fdt_exception
    ]
    logger.log("[FDT-CAPACITY] PASS" if not invalid else
               f"[FDT-CAPACITY] FAIL — {len(invalid)} FDT(s) still outside [{min_fdt},{max_fdt}]")

    return fdts
