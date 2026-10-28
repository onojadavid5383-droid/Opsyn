"""Verbatim port of the FDT boundary-correction passes from
``FTTx Designer — dual PON integrated.py``: ``_resolve_legacy_fat_boundaries``
(Legacy mode) and ``_enforce_fdt_boundaries`` (PCC mode, "Fix H" safety net).

No logic changes from the source script — only the QGIS types and
cross-module imports.
"""

from __future__ import annotations

from typing import Dict, Optional

from .config import CAPACITY_PROFILES, MAX_FAT_PER_FDT, PONArchitecture, CapacityProfile
from .distance_oracle import _network_distance
from .domain import FDT, RoadSegment
from .fdt_anchor import _distance_to_fdt_anchor, _network_distance_is_reliable
from .homepass_assignment import _parse_homepass_value
from .cascade import _project_tag
from .perf_logger import PerformanceLogger
from .spatial_utils import DistanceCalculator
from .topology import RoadTopologyEngine


def _resolve_legacy_fat_boundaries(
    fdts: list,
    dist_calc: 'DistanceCalculator',
    logger: 'PerformanceLogger',
    topo: Optional['RoadTopologyEngine'] = None,
    roads: Optional[Dict[int, 'RoadSegment']] = None,
) -> None:
    """Boundary fix: reassign FATs that are genuinely closer to a neighbouring FDT.

    Problem (image-observed): at road intersections a FAT on road I near the I/K
    junction gets grouped under FDT-K because the spanning-tree walk crossed the
    junction.  We detect these outliers and move them to the closer FDT.

    Rules
    -----
    BOUNDARY_STEAL_RATIO : float
        The candidate FDT must be ≤ this fraction of the current parent's
        distance to qualify.  0.55 = must be 45%+ closer (conservative).
    MAX_STEAL_PER_FDT : int
        Hard cap on FATs stolen FROM one FDT per pass (avoids runaway stealing).
    Capacity guard:
        A steal is rejected when the receiving FDT would exceed MAX_FAT_PER_FDT.
        This is checked against the *live* count (after earlier steals in this
        pass), not the frozen fdt.total_fat snapshot.

    After all moves, affected FDTs are:
      - re-sorted by distance-from-FDT
      - re-numbered (FAT-{alpha}-{seq:02d})
      - total_fat / total_customers recomputed so the attribute table is correct
    """
    BOUNDARY_STEAL_RATIO = 0.55   # more conservative than previous 0.60
    MAX_STEAL_PER_FDT    = 1      # steal at most 1 FAT per FDT per pass

    fdt_by_name  = {fdt.name: fdt for fdt in fdts}
    fdt_anchors  = {
        fdt.name: fdt.snapped_geometry or fdt.geometry
        for fdt in fdts
    }

    # Live count: tracks current len(fdt.fats) as steals happen this pass
    live_count = {fdt.name: len(fdt.fats) for fdt in fdts}

    changes: list = []   # (fat, from_fdt_name, to_fdt_name)

    for fdt in fdts:
        anchor = fdt_anchors[fdt.name]
        if not anchor:
            continue

        # Examine FATs farthest-first — boundary outliers are always the
        # farthest members of the wrong FDT group
        fats_by_dist = sorted(
            fdt.fats,
            key=lambda f: _network_distance(
                anchor,
                f.snapped_geometry or f.geometry,
                road_a_id=fdt.primary_road_id,
                road_b_id=f.road_id,
                topo=topo,
                dist_calc=dist_calc,
            ),
            reverse=True,
        )

        stolen_from_this = 0
        for fat in fats_by_dist:
            if stolen_from_this >= MAX_STEAL_PER_FDT:
                break
            fat_pt       = fat.snapped_geometry or fat.geometry
            dist_current = _network_distance(
                anchor,
                fat_pt,
                road_a_id=fdt.primary_road_id,
                road_b_id=fat.road_id,
                topo=topo,
                dist_calc=dist_calc,
            )

            # Find the nearest other FDT to this FAT
            best_other_name = None
            best_other_dist = float('inf')
            for other in fdts:
                if other.name == fdt.name:
                    continue
                other_anchor = fdt_anchors[other.name]
                if not other_anchor:
                    continue
                d = _network_distance(
                    other_anchor,
                    fat_pt,
                    road_a_id=other.primary_road_id,
                    road_b_id=fat.road_id,
                    topo=topo,
                    dist_calc=dist_calc,
                )
                if d < best_other_dist:
                    best_other_dist = d
                    best_other_name = other.name

            if best_other_name is None:
                continue

            # Ratio check — candidate must be meaningfully closer
            if best_other_dist >= dist_current * BOUNDARY_STEAL_RATIO:
                continue

            # Capacity guard — receiving FDT must have room (live count)
            if live_count[best_other_name] >= MAX_FAT_PER_FDT:
                logger.log(
                    f"  Boundary: skipped moving {fat.name} → {best_other_name} "
                    f"(receiver already at capacity {live_count[best_other_name]})"
                )
                continue

            # Safe to steal
            changes.append((fat, fdt.name, best_other_name))
            stolen_from_this += 1
            live_count[fdt.name]         -= 1
            live_count[best_other_name]  += 1

    if not changes:
        logger.log("Boundary fix: no FATs required reassignment")
        return

    logger.log(f"Boundary fix: {len(changes)} FAT(s) reassigned")
    affected_fdts: set = set()

    for fat, from_name, to_name in changes:
        from_fdt = fdt_by_name[from_name]
        to_fdt   = fdt_by_name[to_name]
        from_fdt.fats = [f for f in from_fdt.fats if f is not fat]
        to_fdt.fats.append(fat)
        fat.parent_fdt  = to_fdt.name
        fat.fdt_serial  = to_fdt.fdt_serial
        fat.from_device = to_fdt.name
        affected_fdts.add(from_name)
        affected_fdts.add(to_name)
        logger.log(
            f"  Moved {fat.name}: {from_name} → {to_name} "
            f"(d_from={_network_distance(fdt_anchors[from_name], fat.snapped_geometry or fat.geometry, road_a_id=fdt_by_name[from_name].primary_road_id, road_b_id=fat.road_id, topo=topo, dist_calc=dist_calc):.0f}m "
            f"d_to={_network_distance(fdt_anchors[to_name], fat.snapped_geometry or fat.geometry, road_a_id=fdt_by_name[to_name].primary_road_id, road_b_id=fat.road_id, topo=topo, dist_calc=dist_calc):.0f}m)"
        )

    # Re-sort, re-number, and recompute totals on every affected FDT
    for fdt_name in affected_fdts:
        fdt    = fdt_by_name[fdt_name]
        alpha  = fdt.fdt_serial
        anchor = fdt_anchors[fdt_name]

        fdt.fats.sort(
            key=lambda f: _network_distance(
                anchor,
                f.snapped_geometry or f.geometry,
                road_a_id=fdt.primary_road_id,
                road_b_id=f.road_id,
                topo=topo,
                dist_calc=dist_calc,
            )
        )
        for seq, fat in enumerate(fdt.fats, start=1):
            fat.name          = _project_tag("FAT", alpha, f"{seq:02d}")
            fat.fat_full_code = fat.name
            fat.fat_sequence  = f"{seq:02d}"

        # Recompute frozen totals so the attribute table stays consistent
        fdt.total_fat       = len(fdt.fats)
        fdt.total_customers = sum(
            _parse_homepass_value(f.total_customers) for f in fdt.fats
        )
        logger.log(
            f"  Re-numbered {fdt_name}: {fdt.total_fat} FATs, "
            f"{fdt.total_customers} customers"
        )


def _enforce_fdt_boundaries(fdts: list,
                            dist_calc: 'DistanceCalculator',
                            logger: 'PerformanceLogger',
                            max_passes: int = 8,
                            topo: Optional['RoadTopologyEngine'] = None,
                            roads: Optional[Dict[int, 'RoadSegment']] = None,
                            profile: Optional['CapacityProfile'] = None) -> None:
    """FDT↔FDT boundary enforcement (Fix H — safety-net).

    After generate_fdts has grouped FATs into FDT candidates, some FATs may still
    sit on a road that is physically closer to a *different* FDT (visible in
    image-5/6 as FAT-19A-03 landing on FDT-23's corridor, FDT-23 leaking north
    across FDT-19's boundary, etc.).  This pass reassigns each such FAT to its
    true nearest FDT by ROAD-GRAPH distance (via _distance_to_fdt_anchor, which
    prefers topo.weighted_shortest_path and falls back to straight-line only
    when no topology path exists), subject to two hard rules:

    BUG FIX: this previously ranked candidates by raw straight-line distance
    (dist_calc.distance_points(anchor, fat_pt)). That's a fine proxy on a single
    straight road (straight-line ~= along-road distance) but breaks down at
    junctions where several FDTs cluster close together on different roads —
    a FAT can be straight-line close to a neighbouring FDT across the
    intersection while being nowhere near it along the actual cable path. That
    caused FATs to get stolen into the wrong FDT group, producing long diagonal
    box-to-box cables crossing the junction (the "star" pattern visible where
    several dead-ends/roads converge). Road-graph distance keeps the
    comparison physically meaningful in exactly those cases.

      • Donor FDT keeps at least MIN_FAT_PER_FDT FATs (never underfill a valid
        group by draining it, and never further drain a group that is
        already broken — corrective fix: the previous guard here
        (`donor_live <= min and donor_live >= min`) only ever evaluates
        true when donor_live == min exactly, so an already-underfilled
        donor (donor_live < min) fell through and was allowed to donate
        anyway, making it worse. "Already broken so re-homing can't make
        it worse" was the original rationale and is simply wrong — 6→5 is
        strictly worse than 6. The only safe rule is: donate only when
        donor_live is strictly greater than MIN.
      • Receiver FDT stays at or below MAX_FAT_PER_FDT.

    Transfers are ranked by (current_distance − target_distance) descending, so
    the most-misplaced FAT moves first.  We iterate until no transfer qualifies
    (converges quickly; capped at ``max_passes``).

    Wing labels/names are NOT touched here — this runs BEFORE the wing-assignment
    loop, which will (re)number every FAT downstream.
    """
    if not fdts or dist_calc is None:
        return

    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    _MIN_GAIN_M = 5.0   # target must be at least this many metres closer
    total_moved = 0

    for _pass in range(max_passes):
        anchors = {
            fdt.name: (fdt.snapped_geometry or fdt.geometry)
            for fdt in fdts
        }
        live_count = {fdt.name: len(fdt.fats) for fdt in fdts}
        fdt_by_name = {fdt.name: fdt for fdt in fdts}

        candidates = []  # (gain, fat, from_name, to_name)
        for fdt in fdts:
            src_anchor = anchors.get(fdt.name)
            if not src_anchor:
                continue
            for fat in fdt.fats:
                fat_pt = fat.snapped_geometry or fat.geometry
                if not fat_pt:
                    continue
                # Road-graph distance (falls back to straight-line only when
                # no topology path exists) — see BUG FIX note in docstring.
                d_cur = _distance_to_fdt_anchor(fat, fdt, dist_calc, topo, roads)
                src_reliable = _network_distance_is_reliable(
                    fat.snapped_geometry or fat.geometry,
                    fdt.snapped_geometry or fdt.geometry,
                    fat.road_id,
                    fdt.primary_road_id,
                    topo,
                )
                if topo is not None and not src_reliable:
                    logger.log(
                        f"WARNING [FDT_BOUNDARY_FALLBACK]: {fat.name}↔{fdt.name} "
                        f"used straight-line fallback during boundary enforcement"
                    )
                best_name = None
                best_dist = d_cur
                for other in fdts:
                    if other.name == fdt.name:
                        continue
                    o_anchor = anchors.get(other.name)
                    if not o_anchor:
                        continue
                    d = _distance_to_fdt_anchor(fat, other, dist_calc, topo, roads)
                    if topo is not None and not _network_distance_is_reliable(
                        fat.snapped_geometry or fat.geometry,
                        other.snapped_geometry or other.geometry,
                        fat.road_id,
                        other.primary_road_id,
                        topo,
                    ):
                        logger.log(
                            f"WARNING [FDT_BOUNDARY_FALLBACK]: {fat.name}↔{other.name} "
                            f"used straight-line fallback during boundary enforcement"
                        )
                    if d < best_dist:
                        best_dist = d
                        best_name = other.name
                if best_name is None:
                    continue
                gain = d_cur - best_dist
                if gain < _MIN_GAIN_M:
                    continue
                candidates.append((gain, fat, fdt.name, best_name))

        if not candidates:
            break

        candidates.sort(key=lambda t: t[0], reverse=True)
        moved_this_pass = 0
        for gain, fat, from_name, to_name in candidates:
            # Donor floor: never drain a group at or below MIN. [Corrective
            # fix] the old condition `donor_live <= min and donor_live >=
            # min` is logically equivalent to `donor_live == min` — it let
            # an already-underfilled donor (donor_live < min) fall through
            # and donate anyway. The only safe rule is strictly-greater.
            donor_live = live_count[from_name]
            if donor_live <= profile.min_fat_per_fdt:
                logger.log(
                    f"[FDT-MOVE-BLOCKED] FAT={getattr(fat, 'name', '<unnamed>')} "
                    f"FROM={from_name} TO={to_name} SOURCE_COUNT={donor_live} "
                    f"REASON=SOURCE_AT_OR_BELOW_MINIMUM_CAPACITY"
                )
                continue
            if live_count[to_name] >= profile.max_fat_per_fdt:
                continue

            src_fdt = fdt_by_name[from_name]
            dst_fdt = fdt_by_name[to_name]
            if fat not in src_fdt.fats:
                continue

            src_before, dst_before = live_count[from_name], live_count[to_name]
            src_fdt.fats = [f for f in src_fdt.fats if f is not fat]
            dst_fdt.fats.append(fat)
            fat.parent_fdt = dst_fdt.name
            fat.from_device = dst_fdt.name
            live_count[from_name] -= 1
            live_count[to_name] += 1
            moved_this_pass += 1
            logger.log(
                f"[FDT-MOVE] FAT={getattr(fat, 'name', '<unnamed>')} "
                f"FROM={from_name} TO={to_name} SOURCE_BEFORE={src_before} "
                f"TARGET_BEFORE={dst_before} SOURCE_AFTER={live_count[from_name]} "
                f"TARGET_AFTER={live_count[to_name]} REASON=BOUNDARY_ENFORCEMENT "
                f"(gain {gain:.1f}m)"
            )

        total_moved += moved_this_pass
        if moved_this_pass == 0:
            break

    if total_moved:
        for fdt in fdts:
            fdt.total_fat = len(fdt.fats)
            try:
                fdt.total_customers = sum(
                    _parse_homepass_value(f.total_customers) for f in fdt.fats
                )
            except Exception:
                fdt.total_customers = sum(
                    getattr(f, 'total_customers', 0) or 0 for f in fdt.fats
                )
        logger.log(
            f"FDT-boundary enforcement: {total_moved} FAT(s) reassigned "
            f"across {len(fdts)} FDTs"
        )
    else:
        logger.log("FDT-boundary enforcement: no reassignment needed")
