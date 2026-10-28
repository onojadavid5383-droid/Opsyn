"""Verbatim port of the wing-assignment stage from
``FTTx Designer — dual PON integrated.py``: ``assign_wings_per_fdt``,
``create_fdt_wing_cascades``.

No logic changes from the source script — only the QGIS types and
cross-module imports.

``_street_position`` (also used here) is defined once, in
``street_utils.py`` — the source itself defines it only once too, despite
also being consumed by ``structures.py``'s ``assign_pole_tags`` and
``boq.py``'s ``populate_boq_layer``; see that module's docstring.

Note: ``SPLITTER_PATTERN`` is one of the 8 tunables the pipeline overrides
per-run (see runtime_config.py's docstring) — read through
``runtime_config.SPLITTER_PATTERN``.
"""

from __future__ import annotations

import math
from collections import Counter as _Counter
from typing import Dict, Optional, Tuple

from . import runtime_config as rc
from .cascade import _legacy_alpha_code, _project_tag
from .config import MAX_FAT_PER_WING, CapacityProfile, CascadeArchitecture, PONArchitecture, CAPACITY_PROFILES
from .domain import FDT, RoadSegment
from .errors import ValidationError
from .fdt_anchor import _compute_fdt_anchor_from_fats
from .fdt_boundary import _enforce_fdt_boundaries, _resolve_legacy_fat_boundaries
from .fdt_generation import _apply_fat_traceability
from .geometry_compat import QgsGeometry, QgsPointXY
from .perf_logger import PerformanceLogger
from .repair.outlier_repair import _relax_fdt_ownership
from .spatial_utils import DistanceCalculator
from .street_utils import _street_position
from .topology import RoadTopologyEngine
from .wing_chain import _optimal_wing_order, _wing_chain_violations
from .wing_geometry import _angular_split_wings


def assign_wings_per_fdt(fdts: list,
                         logger: PerformanceLogger,
                         roads: Optional[Dict[int, 'RoadSegment']] = None,
                         dist_calc: Optional['DistanceCalculator'] = None,
                         cascade_architecture: 'CascadeArchitecture' = None,
                         topo: Optional['RoadTopologyEngine'] = None,
                         profile: Optional['CapacityProfile'] = None,
                         road_to_street: Optional[Dict[int, str]] = None,
                         street_bboxes: Optional[Dict[str, Tuple[float, float, float, float]]] = None):
    """Assign FAT wings per FDT with topology-aware, road-class-sensitive layout.

    Standard (non-dead-end) wing layout
    ------------------------------------
    FATs are split at the midpoint of the sorted-by-cascade-order list:

      Wing A – lower half, reversed  → A-01 closest to FDT boundary, A-04 far end.
      Wing B – upper half, ascending → B-01 closest to FDT boundary, B-04 far end.

    The FDT is placed at the boundary between Wing A and Wing B.

    Borrowed FATs (cross-road)
    --------------------------
    Always inserted at index 0 of their wing (the junction/nearest position).

    Dead-end road treatment  ← NEW
    --------------------------------
    When the primary road of an FDT is a topological dead-end the standard
    bilateral split is physically wrong: splitting the FAT chain in two
    directions implies cable running back through the junction, which is
    impossible on a dead-end.

    Instead the FDT is anchored to the dead-end's junction point (where the
    dead-end meets the parent road), and ALL FATs cascade outward in a single
    direction using Wing B only:

        FDT (at junction) → B-01 → B-02 → B-03 → B-04 (far end of dead-end)

    Wing A is left empty.  The cascade splitter pattern is applied to Wing B
    positions as normal (1×9, 1×9, 1×9, 1×8).

    Cascade chain:
        FDT → A-01 (1×9) → A-02 (1×9) → A-03 (1×9) → A-04 (1×8)
        FDT → B-01 (1×9) → B-02 (1×9) → B-03 (1×9) → B-04 (1×8)
    """
    logger.start_module("Wing Distribution")
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    if profile.pon_count == 2 and cascade_architecture == CascadeArchitecture.LEGACY:
        raise ValidationError(
            "Legacy + Dual-PON is not a supported combination — Legacy mode has "
            "no wing/PON concept (uniform 1x8 star wiring). Select Single-PON "
            "when using Legacy cascading."
        )

    # Order FDTs sequentially along their street before assigning serials
    # below, so FDT-01, FDT-02, ... walk each street in physical order
    # instead of whatever order capacity rebalancing left them in. Grouped
    # by street name first (stable), then by position along that street's
    # own bounding-box diagonal — see _street_position.
    if road_to_street and street_bboxes:
        def _fdt_order_key(f: 'FDT'):
            rid = f.primary_road_id
            if rid is None and f.fats:
                rid = f.fats[0].road_id
            street = road_to_street.get(rid, "￿")
            anchor = f.snapped_geometry or f.geometry
            return (street, _street_position(anchor, street_bboxes.get(street)))
        fdts.sort(key=_fdt_order_key)

    # V5: Legacy mode — apply alpha naming with no wings; exit early
    if cascade_architecture is not None and cascade_architecture == CascadeArchitecture.LEGACY:
        for fdt_index, fdt in enumerate(fdts, start=1):
            alpha    = _legacy_alpha_code(fdt_index - 1)
            fdt_code = _project_tag("FDT", alpha)
            fdt.fdt_serial = alpha
            fdt.fdt_code   = fdt_code
            fdt.name       = fdt_code
            # Sort FATs by straight-line distance from the FDT outward.
            # cascade_order is road-local (position along one road segment) and
            # produces wrong cross-road ordering when an FDT serves multiple roads.
            # Distance-from-FDT gives a universal "01 = nearest to FDT" ordering.
            fdt_anchor = fdt.snapped_geometry or fdt.geometry
            if dist_calc is not None and fdt_anchor:
                all_fats = sorted(
                    fdt.fats,
                    key=lambda f: dist_calc.distance_points(
                        fdt_anchor,
                        f.snapped_geometry or f.geometry,
                    )
                )
            else:
                # Fallback when dist_calc unavailable
                all_fats = sorted(
                    fdt.fats,
                    key=lambda f: (
                        f.cascade_order if f.cascade_order is not None else 999,
                        f.name or "",
                    )
                )
            for seq, fat in enumerate(all_fats, start=1):
                fat.name         = _project_tag("FAT", alpha, f"{seq:02d}")
                fat.fat_full_code = fat.name
                fat.wing         = ""   # no wing in legacy mode
                fat.fat_sequence  = f"{seq:02d}"
                fat.parent_fdt   = fdt_code
                fat.fdt_serial   = alpha
                fat.from_device  = fdt_code   # direct-FDT; overridden by _override_legacy_connections
                fat.to_device    = ""
            fdt.fats = all_fats
            logger.log(f"Legacy naming: {fdt_code} — {len(all_fats)} FATs")

        # Fix boundary ambiguity: FATs closer to a neighbouring FDT are
        # reassigned and re-numbered so sequence always starts nearest FDT.
        if dist_calc is not None:
            _resolve_legacy_fat_boundaries(fdts, dist_calc, logger)

        for fdt in fdts:
            _apply_fat_traceability(fdt, dist_calc=dist_calc, topo=topo, roads=roads)
        logger.end_module("Wing Distribution")
        return

    # ── Fix H: FDT↔FDT boundary enforcement (pre-wing) ───────────────────
    # Reassign FATs whose current FDT is not the geographically nearest one.
    # Runs BEFORE the naming loop below so wing-assignment names/wings are
    # applied to the corrected FDT membership.
    if dist_calc is not None:
        _enforce_fdt_boundaries(fdts, dist_calc, logger, topo=topo, roads=roads, profile=profile)

    for fdt_index, fdt in enumerate(fdts, start=1):
        # V5: 2-digit serial to match image convention (FDT-01, FAT-01A-01)
        fdt_serial = f"{fdt_index:02d}"
        fdt_code   = _project_tag("FDT", fdt_serial)
        fdt.fdt_serial = fdt_serial
        fdt.fdt_code   = fdt_code
        fdt.name       = fdt_code

        all_fats   = list(fdt.fats)
        total_fats = len(all_fats)

        if total_fats > profile.max_fat_per_fdt:
            raise ValidationError(
                f"{fdt.name} has {total_fats} FATs; exceeds {profile.max_fat_per_fdt}"
            )
        if total_fats < profile.min_fat_per_fdt:
            logger.log(
                f"WARNING: {fdt.name} has only {total_fats} FATs "
                f"(minimum {profile.min_fat_per_fdt}); isolated road."
            )

        # ----------------------------------------------------------------
        # Step 1: resolve primary road.
        # Use fdt.primary_road_id set by the walk-forward grouper (exact),
        # falling back to majority vote only when the field is absent.
        # ----------------------------------------------------------------
        primary_road_id = (
            fdt.primary_road_id
            if fdt.primary_road_id is not None
            else _Counter(f.road_id for f in all_fats).most_common(1)[0][0]
        )

        primary_fats = sorted(
            [f for f in all_fats if f.road_id == primary_road_id],
            key=lambda f: f.cascade_order   # ascending road position
        )
        borrowed_fats = sorted(
            [f for f in all_fats if f.road_id != primary_road_id],
            key=lambda f: f.cascade_order
        )

        # ----------------------------------------------------------------
        # Step 2: dead-end single-direction layout.
        #
        # When the primary road is a topological dead-end the bilateral
        # wing split is physically impossible — there is no "behind the FDT"
        # direction.  Instead:
        #   • FDT is anchored to the junction point (where the dead-end
        #     meets the parent road network).
        #   • ALL primary FATs are placed in Wing B, ordered by distance
        #     from the junction outward (B-01 = closest to junction).
        #   • Wing A is left empty.
        #   • Borrowed FATs are prepended to Wing B as normal.
        # ----------------------------------------------------------------
        primary_road_obj  = roads.get(primary_road_id) if roads else None
        is_dead_end_fdt   = (primary_road_obj is not None and
                             primary_road_obj.is_dead_end and
                             primary_road_obj.dead_end_junction_pt is not None)

        if is_dead_end_fdt:
            junction_pt = primary_road_obj.dead_end_junction_pt

            # Sort primary FATs nearest-to-junction first
            if dist_calc is not None:
                primary_fats.sort(
                    key=lambda f: dist_calc.distance_points(f.geometry, junction_pt)
                )
            else:
                primary_fats.sort(
                    key=lambda f: (f.geometry.x() - junction_pt.x()) ** 2 +
                                  (f.geometry.y() - junction_pt.y()) ** 2
                )

            if len(primary_fats) > 4:
                # ── Enhanced Inner Dead-End Logic (generalized to Dual-PON) ────
                #
                # primary_fats is sorted nearest-to-junction first (index 0 =
                # closest to junction, index -1 = deepest / farthest away).
                #
                # A dead-end has only ONE physical direction, so there is no
                # angular split to reuse (spec §9 doesn't apply here — see
                # spec §B.7/§A.11 notes). Instead the sequential dead-end
                # chain is peeled into 1-3 "deep" groups of exactly 4, closest
                # peeled last so Wing A is ALWAYS the group nearest the FDT
                # boundary — this exactly reproduces today's tested Single-PON
                # behaviour (Wing A = the deepest 4) whenever only one deep
                # group is needed (len(primary_fats) in 5..8), and extends the
                # SAME rule outward for Dual-PON's extra capacity:
                #   len(primary_fats) in  5..8  -> deep groups: A                (unchanged)
                #   len(primary_fats) in  9..12 -> deep groups: A (near), C (far)
                #   len(primary_fats) in 13..16 -> deep groups: A (near), C, D (deepest)
                # Wing B remains the universal catch-all: whatever primary FATs
                # are left nearest the junction, plus ALL borrowed FATs at its
                # far end (unchanged from today).
                #
                # Physical note: Wing C/D's cascade (like every wing's) is
                # independently rooted at the FDT (route_fdt_to_fats's per-wing
                # FDT->wing[0] first hop, unchanged) and its cable necessarily
                # runs alongside Wing A's territory to reach deeper FATs —
                # normal for multi-cable dead-end spurs sharing one duct/pole
                # line. If that first hop is long enough to trip the existing
                # cable-length / hop-distance checks, it is flagged exactly as
                # any other over-distance hop already is (WARNING
                # [CABLE_LENGTH_EXCEEDED], wing-chain-violation repair) — no
                # new failure mode, just something to watch for on real data
                # with widely-spaced dead-end FATs needing 9+ total capacity.
                chain = list(reversed(primary_fats))   # deep-first: chain[0] = deepest

                n_primary = len(chain)
                if n_primary <= 8:
                    n_deep_chunks = 1
                elif n_primary <= 12:
                    n_deep_chunks = 2
                else:
                    n_deep_chunks = 3
                # Deepest-peeled-first order; "A" is always peeled LAST so it
                # always ends up as the shallowest (boundary-adjacent) group.
                labels_deepest_first = {1: ["A"], 2: ["C", "A"], 3: ["D", "C", "A"]}[n_deep_chunks]
                if n_deep_chunks > 1 and profile.pon_count == 1:
                    # Unreachable in practice — the earlier total_fats cap
                    # (<= profile.max_fat_per_fdt == 8 for Single-PON) already
                    # prevents len(primary_fats) from exceeding 8. Defensive
                    # guard only, matching the hard-cap raises used elsewhere.
                    raise ValidationError(
                        f"{fdt.name}: dead-end FDT needs wing {labels_deepest_first[0]} "
                        f"under Single-PON — this should be unreachable "
                        f"(len(primary_fats)={n_primary} exceeds the Single-PON cap)."
                    )

                deep_groups: Dict[str, list] = {}
                remaining = chain
                for label in labels_deepest_first:
                    grp = remaining[:4]
                    remaining = remaining[4:]
                    # shallow-of-group first (nearest this group's own inward
                    # boundary — matches wing_a[0]-nearest-FDT convention).
                    deep_groups[label] = list(reversed(grp))
                wing_a = deep_groups.get("A", [])
                wing_c = deep_groups.get("C", [])
                wing_d = deep_groups.get("D", [])

                # Wing B (dead-end portion): `remaining` is already deep-first,
                # i.e. remaining[0] = deepest-of-what's-left = closest to
                # Wing A's boundary = correctly ordered as B-01 already.
                wing_b_dead_end = list(remaining)

                # Separate borrowed-from-parent FATs (tagged in generate_fdts)
                # from regular borrowed FATs (from other touching roads).
                parent_borrowed  = [f for f in borrowed_fats
                                    if getattr(f, '_borrowed_from_parent', False)]
                regular_borrowed = [f for f in borrowed_fats
                                    if not getattr(f, '_borrowed_from_parent', False)]

                # Sort parent-borrowed FATs: nearest-junction-LAST so they
                # sit at the far end of Wing B (physically farthest from FDT).
                if dist_calc is not None:
                    parent_borrowed.sort(
                        key=lambda f: dist_calc.distance_points(f.geometry, junction_pt),
                        reverse=True
                    )
                else:
                    parent_borrowed.sort(
                        key=lambda f: (f.geometry.x() - junction_pt.x()) ** 2 +
                                      (f.geometry.y() - junction_pt.y()) ** 2,
                        reverse=True
                    )

                # Regular borrowed FATs anchor on the junction-closest FAT
                # already in Wing B so the cascade chain stays physically
                # continuous (dead-end tail -> crossing FAT -> next FAT).
                _wb_anchor = (wing_b_dead_end[-1].geometry if wing_b_dead_end
                              else junction_pt)
                if dist_calc is not None:
                    regular_borrowed.sort(
                        key=lambda f: dist_calc.distance_points(f.geometry, _wb_anchor)
                    )
                else:
                    regular_borrowed.sort(
                        key=lambda f: (f.geometry.x() - _wb_anchor.x()) ** 2 +
                                      (f.geometry.y() - _wb_anchor.y()) ** 2
                    )

                # Assemble Wing B: [dead-end near-FDT FATs] + [regular
                # borrowed] + [parent borrowed] — cascade flows outward from
                # FDT, crosses junction last.
                wing_b = wing_b_dead_end + regular_borrowed + parent_borrowed

                # Hard-cap enforcement: spill Wing B overflow into whichever
                # deep wings still have room, nearest-first (A, then C, then
                # D) — generalizes the original 2-wing safety net. Should not
                # trigger given the borrow guard in generate_fdts.
                _spill_order = [w for w in ("A", "C", "D") if w in profile.wings]
                for _label in _spill_order:
                    _grp = {"A": wing_a, "C": wing_c, "D": wing_d}[_label]
                    while len(wing_b) > profile.max_fat_per_wing and len(_grp) < profile.max_fat_per_wing:
                        _grp.append(wing_b.pop())
                while len(wing_a) > profile.max_fat_per_wing and len(wing_b) < profile.max_fat_per_wing:
                    wing_b.append(wing_a.pop())

                for _label, _grp in (("A", wing_a), ("B", wing_b), ("C", wing_c), ("D", wing_d)):
                    if len(_grp) > profile.max_fat_per_wing:
                        raise ValidationError(
                            f"{fdt.name}: dead-end wing {_label} overflow "
                            f"({len(_grp)} > {profile.max_fat_per_wing}) — no "
                            f"remaining wing has room to absorb it."
                        )

                # FDT Placement: road-interpolated midpoint between the two
                # FATs that straddle the Wing A / Wing B boundary — this stays
                # correct regardless of how many deep wings exist, since Wing
                # A is always the shallowest (boundary-adjacent) deep group.
                boundary_fat_a = wing_a[0] if wing_a else (wing_c[0] if wing_c else (wing_d[0] if wing_d else None))
                boundary_fat_b = (remaining[0] if remaining
                                  else (wing_b[0] if wing_b else None))

                _placed = False
                if (boundary_fat_a is not None and boundary_fat_b is not None
                        and primary_road_obj is not None and not primary_road_obj.geometry.isEmpty()):
                    _rg   = primary_road_obj.geometry
                    _rlen = _rg.length()
                    if _rlen > 0:
                        _ta = _rg.lineLocatePoint(QgsGeometry.fromPointXY(boundary_fat_a.geometry))
                        _tb = _rg.lineLocatePoint(QgsGeometry.fromPointXY(boundary_fat_b.geometry))
                        _mg = _rg.interpolate((_ta + _tb) / 2)
                        if _mg and not _mg.isEmpty():
                            fdt.geometry = _mg.asPoint()
                            _placed = True

                if not _placed:
                    if boundary_fat_a is not None and boundary_fat_b is not None:
                        fdt.geometry = QgsPointXY(
                            (boundary_fat_a.geometry.x() + boundary_fat_b.geometry.x()) / 2,
                            (boundary_fat_a.geometry.y() + boundary_fat_b.geometry.y()) / 2
                        )
                    else:
                        # No usable boundary pair (all-borrowed edge case) — fall
                        # back to the junction, same as Standard Dead-End Logic.
                        fdt.geometry = junction_pt

                logger.log(
                    f"{fdt_code}: enhanced inner dead-end layout — FDT inside dead-end, "
                    f"A:{len(wing_a)} C:{len(wing_c)} D:{len(wing_d)} (deep dead-end FATs), "
                    f"B:{len(wing_b)} "
                    f"({len(wing_b_dead_end)} dead-end near-FDT + "
                    f"{len(regular_borrowed)} regular borrowed + "
                    f"{len(parent_borrowed)} parent-road borrowed at far end)"
                )
            else:
                # ── Standard Dead-End Logic (Existing) ──
                wing_a = []
                wing_b = list(primary_fats)          # all FATs cascade outward into dead-end
                # Explicit reset (not just "leave unset"): wing_c/wing_d are
                # plain local variables in this per-FDT loop, and Step 5 below
                # picks them up via locals().get(...). Without an explicit
                # reset here, a PRIOR iteration's dual-PON dead-end FDT could
                # leave stale non-empty wing_c/wing_d in scope, which this
                # branch (T<=4, never needs C/D) would then silently inherit
                # and wrongly attribute to the wrong FDT.
                wing_c = []
                wing_d = []

                # Prepend borrowed FATs at the front (they sit at the junction too)
                for fat in reversed(borrowed_fats):
                    wing_b.insert(0, fat)

                # Hard-cap Wing B; overflow spills into A, then — Dual-PON
                # only — C, then D. Generalizes the original 2-wing loop
                # (which had NO upper bound on Wing A at all) to respect the
                # 4-per-wing cap on every wing it can reach, not just B.
                # FIXED [Phase-1b]: was wing_b.pop() (removes the LAST = deepest FAT)
                # followed by wing_a.insert(0, …), which placed the deepest FAT at
                # A-01 — physically backwards.  The overflow FAT that spills from
                # Wing B is the junction-closest one (index 0 of the already-ordered
                # wing_b list) so it becomes -01 in whichever wing receives it,
                # matching the naming convention that seq-01 is always the FAT
                # closest to FDT.
                _spill_targets = [wing_a] + ([wing_c, wing_d] if profile.pon_count == 2 else [])
                for _spill in _spill_targets:
                    while len(wing_b) > MAX_FAT_PER_WING and len(_spill) < MAX_FAT_PER_WING:
                        _spill.append(wing_b.pop(0))
                    if len(wing_b) <= MAX_FAT_PER_WING:
                        break

                if len(wing_b) > MAX_FAT_PER_WING:
                    # Total dead-end + borrowed FATs exceed what every
                    # available wing (cap 4 each) can hold between them —
                    # would need a 5th wing, which doesn't exist. This
                    # points to an upstream grouping problem (too much
                    # borrowed onto one dead-end FDT), not something this
                    # function can silently paper over.
                    raise ValidationError(
                        f"{fdt.name}: dead-end + borrowed FATs ({len(primary_fats) + len(borrowed_fats)} "
                        f"total) exceed the {len(_spill_targets) + 1} wings available "
                        f"(cap {MAX_FAT_PER_WING} each = {(len(_spill_targets) + 1) * MAX_FAT_PER_WING} max). "
                        f"Reduce dead-end FDT grouping or its donor/borrow floor."
                    )

                # Anchor FDT at the junction point
                fdt.geometry = junction_pt
                logger.log(
                    f"{fdt_code}: standard dead-end layout — FDT anchored at junction, "
                    f"B:{len(wing_b)} FATs outward, A:{len(wing_a)} "
                    f"C:{len(wing_c)} D:{len(wing_d)} overflow"
                )

        else:
            # ----------------------------------------------------------------
            # Step 2 (standard): split ALL of this FDT's FATs by physical
            # direction along the primary road — NOT by road_id equality.
            #
            # BUG THIS REPLACES: the previous version bucketed FATs into
            # "primary" (road_id == fdt.primary_road_id) vs "borrowed"
            # (every other road_id), then spliced "borrowed" FATs into a
            # wing via a left/right sign test and ALWAYS inserted them at
            # the wing's near-FDT end (index 0) — an assumption that only
            # holds when "borrowed" genuinely means "a perpendicular side
            # street meeting at a junction."  In practice almost every real
            # road is chopped into many road_id segments even where there
            # is no real junction (OSM splits at side-streets, driveways,
            # minor nodes), so most of an FDT's own FATs along its own
            # street typically sit on several *different* road_id values.
            # Those FATs were being treated as "borrowed" and spliced in
            # near the FDT regardless of their true position along the
            # road — producing wings whose members zig-zag across BOTH
            # physical sides of the FDT (visible on the map as A/B labels
            # interleaved instead of cascading cleanly outward).
            #
            # Fix: project every FAT (regardless of road_id) onto a single
            # shared axis — the primary road's tangent direction — relative
            # to the FAT cluster's centroid.  This is comparable across
            # road_id/segment boundaries and correctly separates "before
            # the FDT" from "after the FDT" no matter how many OSM pieces
            # the physical street is chopped into.
            # ----------------------------------------------------------------
            # v16 fix (Defect 1 + FDT-anchor consolidation): establish the
            # ONE authoritative FDT anchor — centroid of ALL FATs assigned
            # to this FDT, snapped to the primary road — BEFORE computing
            # anything direction-dependent. Angular sector split then runs
            # against that exact anchor. This replaces the single-axis
            # tangent projection (which is still just a 1-D line: at a
            # T/Y-junction a side-branch FAT can project to a coordinate
            # near a FAT that is actually on the far end of the primary
            # road, mixing branches into one wing) and it also replaces the
            # separate boundary-FAT/road-midpoint placement step that used
            # to run *after* the split — that was a second, competing
            # placement mechanism computing the FDT's position from only
            # the two wing-boundary FATs instead of the full FAT group. See
            # _angular_split_wings() and _compute_fdt_anchor_from_fats().
            fdt.geometry = _compute_fdt_anchor_from_fats(all_fats, primary_road_obj) or fdt.geometry
            _fdt_anchor_for_split = fdt.geometry

            def _dist_from_split_anchor(fat: 'FAT') -> float:
                p = fat.snapped_geometry or fat.geometry
                dx = p.x() - _fdt_anchor_for_split.x()
                dy = p.y() - _fdt_anchor_for_split.y()
                return math.sqrt(dx * dx + dy * dy)

            if profile.pon_count == 1:
                wing_a, wing_b = _angular_split_wings(
                    _fdt_anchor_for_split, all_fats, dist_calc,
                    max_per_wing=profile.max_fat_per_wing,
                )
                wing_c, wing_d = [], []
            else:
                # Nested reuse of the same unmodified 2-way function (spec §9,
                # §A.5): outer cut (cap 8) -> PON1/PON2, inner cut (cap 4) ->
                # A/B and C/D within each half. Spatial/topological, not
                # fill-priority — PON1 is not forced to 8 before PON2 is used.
                pon1_fats, pon2_fats = _angular_split_wings(
                    _fdt_anchor_for_split, all_fats, dist_calc,
                    max_per_wing=profile.max_fat_per_wing * 2,
                )
                wing_a, wing_b = _angular_split_wings(
                    _fdt_anchor_for_split, pon1_fats, dist_calc,
                    max_per_wing=profile.max_fat_per_wing,
                )
                wing_c, wing_d = _angular_split_wings(
                    _fdt_anchor_for_split, pon2_fats, dist_calc,
                    max_per_wing=profile.max_fat_per_wing,
                )

            # Sequence ordering is a *separate* operation from sector
            # assignment (spec section 16): within each already-correct
            # sector, closest-to-FDT goes first so it becomes -01.
            for _w in (wing_a, wing_b, wing_c, wing_d):
                _w.sort(key=_dist_from_split_anchor)

            # ----------------------------------------------------------------
            # Step 4: enforce max_fat_per_wing per wing, PON-scoped (a
            # rebalance never moves a FAT across the PON1/PON2 boundary —
            # only within A<->B or within C<->D — matching §9's PON-major
            # design). A direction-aware split can still overflow one side
            # when the cluster isn't evenly distributed; the fallback below
            # moves only the wing-boundary-adjacent FAT.
            # ----------------------------------------------------------------
            while len(wing_a) > profile.max_fat_per_wing and len(wing_b) < profile.max_fat_per_wing:
                wing_b.insert(0, wing_a.pop(0))
            while len(wing_b) > profile.max_fat_per_wing and len(wing_a) < profile.max_fat_per_wing:
                wing_a.insert(0, wing_b.pop(-1))
            while len(wing_c) > profile.max_fat_per_wing and len(wing_d) < profile.max_fat_per_wing:
                wing_d.insert(0, wing_c.pop(0))
            while len(wing_d) > profile.max_fat_per_wing and len(wing_c) < profile.max_fat_per_wing:
                wing_c.insert(0, wing_d.pop(-1))

            if (len(wing_a) > profile.max_fat_per_wing or len(wing_b) > profile.max_fat_per_wing
                    or len(wing_c) > profile.max_fat_per_wing or len(wing_d) > profile.max_fat_per_wing):
                raise ValidationError(
                    f"{fdt_code}: wing overflow after rebalance "
                    f"A={len(wing_a)}, B={len(wing_b)}, C={len(wing_c)}, D={len(wing_d)}"
                )

            # v16 fix: the FDT's position was already set above from
            # _compute_fdt_anchor_from_fats() (centroid of the full FAT
            # group, snapped to the primary road) before the angular split
            # ran. Re-deriving it here from only the two wing-boundary FATs
            # would be a second, competing placement rule — removed.

        # ----------------------------------------------------------------
        # Step 5: assign names, sequence numbers, wing labels.
        # wing_a[0]/wing_b[0]/wing_c[0]/wing_d[0] are ALWAYS closest to the
        # FDT within their own wing. Dead-end FDTs never populate C/D (guarded
        # above); wing_c/wing_d default to [] for that branch.
        # ----------------------------------------------------------------
        _wings_by_label = {
            "A": wing_a, "B": wing_b,
            "C": locals().get("wing_c", []) or [],
            "D": locals().get("wing_d", []) or [],
        }
        for wing_label in profile.wings:
            wing_fats = _wings_by_label.get(wing_label, [])
            for seq, fat in enumerate(wing_fats, start=1):
                fat.wing          = wing_label
                fat.wing_id       = wing_label
                fat.parent_fdt    = fdt_code
                fat.fdt_serial    = fdt_serial
                fat.fat_sequence  = f"{seq:02d}"
                fat.fat_full_code = _project_tag("FAT", f"{fdt_serial}{wing_label}", f"{seq:02d}")
                fat.name          = fat.fat_full_code

        fdt.wing_a_count = len(_wings_by_label.get("A", []))
        fdt.wing_b_count = len(_wings_by_label.get("B", []))
        fdt.wing_c_count = len(_wings_by_label.get("C", []))
        fdt.wing_d_count = len(_wings_by_label.get("D", []))
        # PON-major concatenation order — never interleaved (spec §7/§A.2).
        fdt.fats = [fat for label in profile.wings for fat in _wings_by_label.get(label, [])]
        _apply_fat_traceability(fdt, dist_calc=dist_calc, topo=topo, roads=roads)

        # ----------------------------------------------------------------
        # Step 6 (removed, v16): this used to be a separate "centralize
        # the FDT" pass — project the FAT group onto the primary road,
        # find the min/max span, and move the FDT to that span's midpoint
        # — followed by yet another from-scratch wing re-split around the
        # new position. It existed only because Steps 2-4 used to place
        # the FDT at a wing-boundary FAT (an off-centre position by
        # construction), so a second corrective pass was needed.
        #
        # Step 2 now sets fdt.geometry directly from
        # _compute_fdt_anchor_from_fats() — the centroid of every FAT in
        # the group, snapped to the primary road — before the angular
        # split even runs. That already *is* the centred position this
        # step used to correct for, so a second placement/re-split pass
        # here would just be a competing mechanism that could disagree
        # with Step 2's result. Dead-end FDTs are unaffected either way:
        # they were always anchored at the junction point instead (a
        # deliberate exception — see the dead-end branch above — because
        # there is no "behind the FDT" direction to centre a span over).
        # ----------------------------------------------------------------

        logger.log(
            f"{fdt.name} -> {total_fats} FAT -> A:{len(wing_a)}, B:{len(wing_b)} "
            f"| A-01={wing_a[0].name if wing_a else 'none'} "
            f"B-01={wing_b[0].name if wing_b else 'none'}"
        )

    _relax_fdt_ownership(fdts, logger, roads=roads, dist_calc=dist_calc, topo=topo, profile=profile)

    logger.end_module("Wing Distribution")


def create_fdt_wing_cascades(fdts: list,
                             logger: PerformanceLogger,
                             cascade_architecture: 'CascadeArchitecture' = None,
                             dist_calc: Optional['DistanceCalculator'] = None,
                             topo: Optional['RoadTopologyEngine'] = None,
                             profile: Optional['CapacityProfile'] = None):
    """Wire cascade from_device/to_device and assign splitter types.

    Each wing is already ordered closest-to-FDT first by assign_wings_per_fdt.
    The cascade chain is:
        FDT → wing[0] (1×9) → wing[1] (1×9) → wing[2] (1×9) → wing[3] (1×8)

    SPLITTER_PATTERN = ["1x9", "1x9", "1x9", "1x8"]
    Position 0 is closest to FDT, position 3 (1×8) is the far end.
    In Legacy mode: assign uniform 1x8 splitter type; skip chain wiring
    (direct FDT connections are handled by _override_legacy_connections).

    Dual-PON: loops profile.wings (A/B/C/D) instead of a literal (A,B) tuple.
    Each wing's chain is independent, rooted at the FDT — PON1's A/B chain
    and PON2's C/D chain never touch (per-wing signature, confirmed
    PON-independent by construction; spec §11).
    """
    logger.start_module("FDT Wing Cascading")
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]

    # V5: Legacy mode — uniform splitter, no chain wiring
    if cascade_architecture is not None and cascade_architecture == CascadeArchitecture.LEGACY:
        for fdt in fdts:
            for fat in fdt.fats:
                fat.splitter_type = "1x8"
        logger.end_module("FDT Wing Cascading")
        return

    # Reset stale cascade wiring before rebuilding chains — Lloyd relaxation may have
    # transferred FATs across FDTs, leaving stale from_device/to_device markers that
    # would produce spurious 'head' FATs and a star topology at the FDT anchor.
    for fdt in fdts:
        for fat in fdt.fats:
            fat.from_device = ""
            fat.to_device = ""

    for fdt in fdts:
        total_fats = len(fdt.fats)
        if total_fats > profile.max_fat_per_fdt:
            raise ValidationError(
                f"{fdt.name} has {total_fats} FATs, exceeds {profile.max_fat_per_fdt}"
            )

        wings_by_label = {label: [f for f in fdt.fats if f.wing == label] for label in profile.wings}

        for label, members in wings_by_label.items():
            if len(members) > profile.max_fat_per_wing:
                raise ValidationError(
                    f"{fdt.name} wing {label} FAT count exceeded: "
                    f"{len(members)}, max={profile.max_fat_per_wing}"
                )

        # ------------------------------------------------------------------
        # ENHANCEMENT (reference-parity, v10): re-sort each wing by distance
        # from the FINAL FDT anchor, re-apply naming/sequence, and ENFORCE
        # the invariant that the sequence number tracks physical proximity.
        #
        # Rule enforced:
        #   For every wing W served by an FDT F:
        #     dist(F, FAT_W-01) <= dist(F, FAT_W-02) <= ... <= dist(F, FAT_W-NN)
        #   i.e.  -01 is the FAT nearest to F on wing W,
        #         -NN (highest seq, e.g. -04) is the farthest and closes the
        #         cascade chain with the 1x8 splitter.
        #
        # Why re-sort here (not in assign_wings_per_fdt):
        #   Step 5 sorted wings closest-first, but afterwards
        #     • Step 6 centralization moved the FDT anchor,
        #     • _relax_fdt_ownership may have shuffled FATs across FDTs.
        #   Either can invert the -01 / -NN relationship, so we restore it
        #   BEFORE wiring the from_device/to_device chain and BEFORE assigning
        #   splitter ratios (which depend on cascade position).
        # ------------------------------------------------------------------
        fdt_anchor = fdt.snapped_geometry or fdt.geometry

        def _dist_from_fdt(fat, _anchor=fdt_anchor):
            # v13-fix: Reverted to straight-line.  The previous v12 change
            # that used _network_distance here caused two problems:
            #   1. PERFORMANCE: _network_distance runs full Dijkstra for every
            #      FAT in every wing, adding O(total_fats) graph searches.
            #   2. QUALITY: weighted_shortest_path returns inflated detour
            #      distances for FATs on different road segments (opposite
            #      carriageway, adjacent branch), causing wrong neighbor
            #      selection and crisscrossing wing chains.
            # Straight-line is accurate enough for cascade_order and advisory
            # monotonicity checks because wings are small clusters where
            # Euclidean distance preserves relative ordering.  The actual
            # cable-route validation is done later by _wing_chain_violations
            # (which now also uses the fast path in _network_distance).
            if not _anchor:
                return 0.0
            fat_pt = fat.snapped_geometry or fat.geometry
            dx = fat_pt.x() - _anchor.x()
            dy = fat_pt.y() - _anchor.y()
            return math.sqrt(dx * dx + dy * dy)

        # [Fix 2] Cascade order is now chosen by minimising the longest hop,
        # not by radial distance from the anchor.
        #
        # History, because the comment that used to sit here was wrong and cost
        # real debugging time. v16 deleted _order_by_nearest_hop (a greedy
        # nearest-neighbour walk) for producing zig-zag cascades, and replaced
        # it with `sorted(wing, key=_dist_from_fdt)` — a pure Euclidean radial
        # sort. But the comments below were never updated, so the code claimed
        # to be "picking the nearest available FAT at each step" while actually
        # doing nothing of the kind, and the warning text repeated that claim
        # into the log.
        #
        # Radial order is the wrong invariant. It makes consecutive chain
        # members RADIAL neighbours, which constrains nothing about the road
        # distance between them, and it systematically pushes the outermost FAT
        # (the one most likely to be on a different branch) to the end of the
        # chain. On the reference run 26 of 48 wings had their longest hop last,
        # against a chance expectation of about 12.
        #
        # _optimal_wing_order solves the actual objective exactly at this size.
        # The FDT anchor still decides nothing about order, but _dist_from_fdt
        # is kept below for cascade_order, which is only an ordinal.
        if fdt_anchor:
            for label in profile.wings:
                wings_by_label[label] = _optimal_wing_order(
                    fdt, wings_by_label[label], dist_calc=dist_calc, topo=topo
                )

            fdt_serial = fdt.fdt_serial or ""
            for wing_label in profile.wings:
                for seq, fat in enumerate(wings_by_label[wing_label], start=1):
                    fat.wing          = wing_label
                    fat.wing_id       = wing_label
                    fat.parent_fdt    = fdt.name
                    fat.fdt_serial    = fdt_serial
                    fat.fat_sequence  = f"{seq:02d}"
                    fat.fat_full_code = _project_tag("FAT", f"{fdt_serial}{wing_label}", f"{seq:02d}")
                    fat.name          = fat.fat_full_code

            # Persist the new ordering on the FDT so downstream consumers
            # (route_fdt_to_fats, exports, cable routing) see wings in
            # PON-major cascade order (A,B,C,D — never interleaved).
            fdt.fats         = [f for label in profile.wings for f in wings_by_label[label]]
            fdt.wing_a_count = len(wings_by_label.get("A", []))
            fdt.wing_b_count = len(wings_by_label.get("B", []))
            fdt.wing_c_count = len(wings_by_label.get("C", []))
            fdt.wing_d_count = len(wings_by_label.get("D", []))

        # Wire the from_device / to_device chain and assign splitter types.
        # Wings are now guaranteed closest-to-FDT first by the re-sort above.
        # cascade_order is rewritten here using straight-line distance from
        # the FDT anchor so ordering is comparable across all roads served
        # by this FDT (road-local lineLocatePoint values run 0-1000 per road
        # and cannot be compared between roads).
        fdt_outputs = 0
        for wing_label in profile.wings:
            wing_fats = wings_by_label[wing_label]
            if not wing_fats:
                continue
            for i, fat in enumerate(wing_fats):
                # SPLITTER_PATTERN index 0 = 1x9 (closest to FDT, feeds the rest)
                # SPLITTER_PATTERN index -1 = 1x8 (farthest, closes the chain)
                fat.splitter_type = rc.SPLITTER_PATTERN[i]
                fat.from_device   = fdt.name if i == 0 else wing_fats[i - 1].name
                fat.to_device     = wing_fats[i + 1].name if i < len(wing_fats) - 1 else ""
                if fdt_anchor:
                    fat.cascade_order = int(_dist_from_fdt(fat) * 100)

            # --------------------------------------------------------------
            # ADVISORY: -01 is normally nearest to the FDT and later seqs
            # farther, but _optimal_wing_order minimises the longest hop, not
            # distance from the anchor. On a bent or forked road the hop-optimal
            # chain can dip in radial distance without any hop being too long.
            # That is the correct outcome, so this stays a warning.
            #
            # ENFORCEMENT: [Fix 2] the order below IS hop-optimal — it is the
            # best of every permutation of this wing, scored on the same graph
            # the cable router uses. So a hop that still exceeds its limit here
            # cannot be fixed by any re-ordering, and the problem is wing
            # membership or FDT ownership, not sequence. That is now a
            # justified claim rather than the inherited one: the previous text
            # asserted a "nearest-hop walk" that had been deleted three versions
            # earlier, while the code did a radial sort.
            #
            # All violating hops are reported, not just the first. Reporting
            # only hop_violations[0] hid the rest of the wing: on the reference
            # run FDT-11 Wing A logged one 949 m first-hop violation and stayed
            # silent about the two real ones behind it.
            # --------------------------------------------------------------
            if fdt_anchor and len(wing_fats) > 1:
                dists = [_dist_from_fdt(f) for f in wing_fats]
                for i in range(1, len(dists)):
                    if dists[i] + 1e-6 < dists[i - 1]:
                        logger.log(
                            f"{fdt.name} wing {wing_label} "
                            f"{wing_fats[i - 1].name} @ {dists[i - 1]:.2f}m "
                            f"precedes {wing_fats[i].name} @ {dists[i]:.2f}m "
                            f"from FDT anchor (hop-optimal order, not a "
                            f"corridor error)"
                        )

                hop_violations = _wing_chain_violations(
                    fdt, wing_fats, dist_calc=dist_calc, topo=topo
                )
                for _idx, bad_fat, hop_dist, limit, prev_name in hop_violations:
                    logger.log(
                        f"WARNING [WING_HOP_UNFIXABLE_BY_ORDER]: {fdt.name} "
                        f"wing {wing_label} {prev_name} -> {bad_fat.name} is "
                        f"{hop_dist:.2f}m by road (limit {limit:.2f}m). This is "
                        f"the hop-optimal ordering of this wing, so no re-sort "
                        f"can shorten it — {bad_fat.name} is isolated from the "
                        f"rest of {fdt.name} wing {wing_label} by road "
                        f"distance; review wing membership / FDT ownership"
                    )

            fdt_outputs += 1

        if fdt_outputs > len(profile.wings):
            raise ValidationError(
                f"{fdt.name} has {fdt_outputs} outputs; maximum is {len(profile.wings)}"
            )

        logger.log(
            f"{fdt.name} -> total FAT {total_fats}, outputs {fdt_outputs}, "
            + ", ".join(f"Wing{label} {len(wings_by_label[label])}" for label in profile.wings)
            + " | " + " ".join(
                f"{label}-01={wings_by_label[label][0].name if wings_by_label[label] else 'none'}"
                for label in profile.wings
            )
        )

    logger.end_module("FDT Wing Cascading")
