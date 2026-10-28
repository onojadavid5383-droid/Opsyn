"""Verbatim port of the FDT-ownership outlier-repair pass from
``FTTx Designer — dual PON integrated.py``: ``_build_fdt_anchor_index``,
``_nearest_fdt_candidates``, ``_cached_fat_fdt_distance``,
``_invalidate_fdt_cache``, ``_relax_fdt_ownership``,
``_repair_fdt_outliers_by_relay``.

No logic changes from the source script — only the QGIS types and
cross-module imports. Called directly from ``wing_assignment.
assign_wings_per_fdt`` as its own last step (not merely orchestrated
afterward by the pipeline), which is why this module exists ahead of the
rest of the ``repair/`` subpackage — see CLAUDE.md's own warning that the
repair passes are tightly coupled to earlier pipeline invariants.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .. import runtime_config as rc
from ..config import CAPACITY_PROFILES, PONArchitecture, CapacityProfile
from ..domain import FAT, FDT, RoadSegment
from ..fdt_anchor import _distance_to_fdt_anchor, _recompute_fdt_anchor, _renumber_fdt_wings
from ..geometry_compat import QgsFeature, QgsGeometry, QgsPointXY, QgsSpatialIndex
from ..homepass_assignment import _parse_homepass_value
from ..perf_logger import PerformanceLogger
from ..spatial_utils import DistanceCalculator
from ..topology import RoadTopologyEngine
from ..wing_chain import _record_repair_move, _repair_budget_left

NEIGHBOR_FDT_K = 15  # k-nearest FDTs considered as borrow/swap candidates


def _build_fdt_anchor_index(fdts: List[FDT]) -> Tuple[QgsSpatialIndex, Dict[int, FDT]]:
    """Return (spatial index of anchors, fid→FDT map).  Straight-line pruning only."""
    idx = QgsSpatialIndex()
    fid_map: Dict[int, FDT] = {}
    for i, fdt in enumerate(fdts):
        pt = fdt.snapped_geometry or fdt.geometry
        if pt is None:
            continue
        feat = QgsFeature(i)
        feat.setGeometry(QgsGeometry.fromPointXY(pt))
        idx.addFeature(feat)
        fid_map[i] = fdt
    return idx, fid_map


def _nearest_fdt_candidates(
    fat: FAT,
    anchor_idx: QgsSpatialIndex,
    fid_map: Dict[int, FDT],
    k: int = NEIGHBOR_FDT_K,
) -> List[FDT]:
    pt = fat.snapped_geometry or fat.geometry
    if pt is None:
        return []
    ids = anchor_idx.nearestNeighbor(pt, k)
    return [fid_map[i] for i in ids if i in fid_map]


def _cached_fat_fdt_distance(
    fat: FAT,
    fdt: FDT,
    cache: Dict[Tuple[int, str], float],
    dist_calc: Optional['DistanceCalculator'] = None,
    topo: Optional['RoadTopologyEngine'] = None,
    roads: Optional[Dict[int, 'RoadSegment']] = None,
) -> float:
    key = (id(fat), fdt.name)
    d = cache.get(key)
    if d is not None:
        return d
    d = _distance_to_fdt_anchor(fat, fdt, dist_calc=dist_calc, topo=topo, roads=roads)
    cache[key] = d
    return d


def _invalidate_fdt_cache(cache: Dict[Tuple[int, str], float], fdt: FDT) -> None:
    name = fdt.name
    for key in [k for k in cache if k[1] == name]:
        cache.pop(key, None)


def _relax_fdt_ownership(
    fdts: List[FDT],
    logger: PerformanceLogger,
    roads: Optional[Dict[int, 'RoadSegment']] = None,
    dist_calc: Optional['DistanceCalculator'] = None,
    topo: Optional['RoadTopologyEngine'] = None,
    profile: Optional['CapacityProfile'] = None,
) -> None:
    """One-pass Lloyd relaxation: move FATs only when another FDT is truly closer.

    v12 speed: outer FDT already IS the current owner (no per-FAT membership
    scan), candidate FDTs are pruned to the K nearest anchors via a spatial
    index, and road-graph distances are memoized for the whole pass.  The
    borrowing rule (transfer only on real gain + capacity + wing-slot checks)
    is unchanged.
    """
    if not fdts:
        return

    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    transfers = 0
    affected = set()
    MIN_RELAX_GAIN_M = 20.0

    anchor_idx, fid_map = _build_fdt_anchor_index(fdts)
    dist_cache: Dict[Tuple[int, str], float] = {}

    for current_owner in list(fdts):
        owner_anchor = current_owner.snapped_geometry or current_owner.geometry
        if owner_anchor is None:
            continue

        for fat in list(current_owner.fats):
            fat_pt = fat.snapped_geometry or fat.geometry
            if not fat_pt:
                continue

            current_dist = _cached_fat_fdt_distance(
                fat, current_owner, dist_cache,
                dist_calc=dist_calc, topo=topo, roads=roads,
            )

            best = None
            best_dist = current_dist
            for other in _nearest_fdt_candidates(fat, anchor_idx, fid_map):
                if other is current_owner:
                    continue
                d = _cached_fat_fdt_distance(
                    fat, other, dist_cache,
                    dist_calc=dist_calc, topo=topo, roads=roads,
                )
                if d < best_dist:
                    best_dist = d
                    best = other

            if best is None:
                continue
            if current_dist - best_dist < MIN_RELAX_GAIN_M:
                continue
            if len(current_owner.fats) <= profile.min_fat_per_fdt:
                continue
            if len(best.fats) >= profile.max_fat_per_fdt:
                continue
            if best_dist > rc.MAX_BOX_TO_BOX_DISTANCE:
                continue

            # Cheap, approximate gate only (does *some* wing have room?) —
            # loops profile.wings instead of a hardcoded A/B pair so Dual-PON
            # transfers aren't silently blocked by a check that only ever
            # looked at wings A and B. The authoritative answer is always
            # re-derived from scratch by _renumber_fdt_wings() below, so this
            # gate never needs to be exact about *which* wing/PON.
            wing_counts = {
                label: sum(1 for f in best.fats if getattr(f, 'wing', '') == label)
                for label in profile.wings
            }
            if all(count >= profile.max_fat_per_wing for count in wing_counts.values()):
                continue
            target_wing = min(wing_counts, key=lambda label: wing_counts[label])

            current_owner.fats = [member for member in current_owner.fats if member is not fat]
            best.fats.append(fat)
            fat.wing = target_wing
            fat.parent_fdt = best.name
            fat.fdt_serial = best.fdt_serial
            affected.add(current_owner.name)
            affected.add(best.name)
            transfers += 1

    if transfers:
        for fdt in fdts:
            # v16 fix: anchor must be current BEFORE the angular split runs.
            _recompute_fdt_anchor(fdt, roads=roads)
            _renumber_fdt_wings(fdt, dist_calc=dist_calc, profile=profile)
        logger.log(f"Post-generation Lloyd relaxation: {transfers} FAT(s) reassigned")
    else:
        logger.log("Post-generation Lloyd relaxation: no transfers needed")


def _repair_fdt_outliers_by_relay(
    fdts: List[FDT],
    logger: PerformanceLogger,
    roads: Optional[Dict[int, 'RoadSegment']] = None,
    dist_calc: Optional['DistanceCalculator'] = None,
    topo: Optional['RoadTopologyEngine'] = None,
    max_passes: int = 8,
    profile: Optional['CapacityProfile'] = None,
) -> None:
    """Repair far/out-of-boundary FAT ownership with direct moves or 1-hop swaps.

    The first relay patch only affected the inner dead-end borrow loop.  The
    remaining visible errors (for example B-03/B-02 outliers) are usually created
    later by normal corridor grouping or post-capacity absorption.  Those groups
    can be at MIN capacity, so the normal boundary pass refuses to move the bad
    FAT because it would under-fill the donor.  This pass fixes that case by
    using an atomic 1-for-1 relay swap:

        source FDT gives its far/outlier FAT to the closer neighbour;
        that neighbour gives back its closest boundary FAT to the source.

    Counts stay unchanged, no FDT crosses MAX/MIN, and both exchanged FATs must
    improve the total network-distance cost while staying within the cable reach
    used for box-to-box continuity.
    """
    if not fdts or dist_calc is None:
        return

    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    MIN_DIRECT_GAIN_M = 20.0
    MIN_SWAP_GAIN_M = 10.0
    moved = 0
    swapped = 0

    # v12 speed: memoize road-graph distances across the whole repair (safe:
    # anchors only shift when we mutate an FDT, and we invalidate that FDT's
    # cache entries below).  Prune target search to K nearest FDT anchors via
    # a spatial index rebuilt only when anchors move.
    dist_cache: Dict[Tuple[int, str], float] = {}
    anchor_idx, fid_map = _build_fdt_anchor_index(fdts)

    def _anchor(fdt: FDT) -> Optional[QgsPointXY]:
        return fdt.snapped_geometry or fdt.geometry

    def _dist(fdt: FDT, fat: FAT) -> float:
        return _cached_fat_fdt_distance(
            fat, fdt, dist_cache,
            dist_calc=dist_calc, topo=topo, roads=roads,
        )

    def _refresh_fdt(fdt: FDT) -> None:
        fdt.total_fat = len(fdt.fats)
        fdt.total_customers = sum(_parse_homepass_value(f.total_customers) for f in fdt.fats)
        # v16 fix: this pass moves FATs between FDTs (direct moves and
        # 1-for-1 relay swaps) but previously only refreshed the anchor
        # point — it never recalculated wing membership/sequence after an
        # ownership change, leaving stale A/B labels and sequence numbers
        # on both sides of every swap. Recompute the anchor, then re-derive
        # wings against it, exactly as every other ownership-changing path
        # in this module now does.
        _recompute_fdt_anchor(fdt, roads=roads)
        _renumber_fdt_wings(fdt, dist_calc=dist_calc, profile=profile)
        _invalidate_fdt_cache(dist_cache, fdt)

    for _pass in range(max_passes):
        best_action = None
        best_gain = 0.0

        for source in fdts:
            if not _anchor(source):
                continue
            for fat_x in list(source.fats):
                # [Fix 7] Per-FAT move budget. FAT-21A-02 appeared in 28 repair
                # actions on the reference run and the ownership signature
                # never stabilised; a FAT that has already been relocated
                # MAX_MOVES_PER_FAT times is being fought over, not improved.
                if not _repair_budget_left(fat_x):
                    continue
                d_x_source = _dist(source, fat_x)
                target = None
                d_x_target = d_x_source
                # Only look at the K nearest FDT anchors — a far FDT can never
                # be a valid receiver under MAX_BOX_TO_BOX_DISTANCE anyway.
                for other in _nearest_fdt_candidates(fat_x, anchor_idx, fid_map):
                    if other is source or not _anchor(other):
                        continue
                    d = _dist(other, fat_x)
                    if d < d_x_target:
                        target = other
                        d_x_target = d

                if target is None:
                    continue

                direct_gain = d_x_source - d_x_target
                if direct_gain < MIN_DIRECT_GAIN_M:
                    continue

                # Direct move when it does not break capacity.  This catches
                # simple 8→7 / 7→8 corrections without needing a swap.
                if (len(source.fats) > profile.min_fat_per_fdt
                        and len(target.fats) < profile.max_fat_per_fdt
                        and d_x_target <= rc.MAX_BOX_TO_BOX_DISTANCE
                        and direct_gain > best_gain):
                    best_action = ('move', source, target, fat_x, None)
                    best_gain = direct_gain

                # Relay swap when the donor is already at MIN or receiver is full.
                if d_x_target > rc.MAX_BOX_TO_BOX_DISTANCE:
                    continue
                for fat_y in list(target.fats):
                    if fat_y is fat_x:
                        continue
                    if not _repair_budget_left(fat_y):
                        continue
                    d_y_source = _dist(source, fat_y)
                    if d_y_source > rc.MAX_BOX_TO_BOX_DISTANCE:
                        continue
                    # Prefer boundary FATs: the return FAT should be genuinely
                    # closer to the source than the outlier currently is.
                    if d_y_source >= d_x_source:
                        continue

                    d_y_target = _dist(target, fat_y)
                    swap_gain = (d_x_source + d_y_target) - (d_x_target + d_y_source)
                    if swap_gain < MIN_SWAP_GAIN_M:
                        continue

                    if swap_gain > best_gain:
                        best_action = ('swap', source, target, fat_x, fat_y)
                        best_gain = swap_gain

        if best_action is None:
            break

        kind, source, target, fat_x, fat_y = best_action
        if kind == 'move':
            source.fats.remove(fat_x)
            target.fats.append(fat_x)
            fat_x.allocation_type = "relay-corrected"
            _record_repair_move(fat_x)
            moved += 1
            logger.log(
                f"RELAY-REPAIR move: {getattr(fat_x, 'name', '<unnamed>')} "
                f"{source.name} → {target.name} (gain {best_gain:.1f}m)"
            )
            _refresh_fdt(source)
            _refresh_fdt(target)
            anchor_idx, fid_map = _build_fdt_anchor_index(fdts)
            continue

        source.fats.remove(fat_x)
        target.fats.remove(fat_y)
        target.fats.append(fat_x)
        source.fats.append(fat_y)
        fat_x.allocation_type = "relay-swap-outlier"
        fat_y.allocation_type = "relay-swap-boundary"
        _record_repair_move(fat_x, fat_y)
        swapped += 1
        logger.log(
            f"RELAY-REPAIR swap: {getattr(fat_x, 'name', '<unnamed>')} "
            f"{source.name} → {target.name}; "
            f"{getattr(fat_y, 'name', '<unnamed>')} {target.name} → {source.name} "
            f"(gain {best_gain:.1f}m)"
        )
        _refresh_fdt(source)
        _refresh_fdt(target)
        anchor_idx, fid_map = _build_fdt_anchor_index(fdts)

    if moved or swapped:
        logger.log(
            f"Relay outlier repair complete — {moved} direct move(s), "
            f"{swapped} relay swap(s)."
        )
    else:
        logger.log("Relay outlier repair: no qualifying outliers found")
