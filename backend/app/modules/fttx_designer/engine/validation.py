"""Verbatim port of the validation/audit stage from
``FTTx Designer — dual PON integrated.py``: ``validate_design`` (a
documented no-op — validation now happens via the hard-gate functions
below, run inline during the pipeline, not as one deferred pass),
``validate_drop_cable_constraints``, ``diagnose_b2b_headroom``,
``audit_b2b_detours``, ``validate_box_to_box_cable_constraints``,
``validate_wing_sequences``, ``validate_fat_fdt_ownership``,
``validate_capacity_and_absorption_model``, ``log_final_capacity_audit``,
``validate_fdt_wing_structure``, ``validate_pon_partition``,
``validate_wing_chain_graph``, ``validate_all_wing_chain_graphs``.

No logic changes from the source script — only the QGIS types and
cross-module imports.

Deliberately excluded from this module: ``validate_selected_layers``. It
validates and reprojects raw INPUT layers (CRS detection, a target-CRS
choice across every selected layer, then ``processing.run(
"native:reprojectlayer", ...)`` to actually reproject mismatched ones) —
real QGIS processing-algorithm territory with no ``geometry_compat``
equivalent, and a genuine input-boundary concern (matching
``create_output_layers``/``populate_output_layers``'s symmetric deferral to
the output boundary) rather than engine logic operating on already-loaded
domain objects. It belongs with Phase 5's upload/input_validation.py, where
CRS reprojection can be done directly against parsed coordinates via
pyproj — not ported here.

Note: ``MAX_BOX_TO_CUSTOMER_DISTANCE`` and ``DROP_LENGTH_TOLERANCE`` are 2
of the 8 tunables the pipeline overrides per-run (see runtime_config.py's
docstring) — every direct reference reads ``runtime_config.X``.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List, Optional

from . import runtime_config as rc
from . import distance_oracle as _distance_oracle_mod
from .cascade import _project_tag, _walk_cascade_chain
from .config import (
    ALLOW_DOCUMENTED_B2B_EXCEPTIONS,
    B2B_DETOUR_ABS_LIMIT,
    B2B_DETOUR_RATIO_LIMIT,
    B2B_EXCESS_COST_PER_M,
    CAPACITY_PROFILES,
    MAX_FAT_CAPACITY,
    MIN_FAT_CAPACITY,
    PON_WINGS,
    CapacityProfile,
    PONArchitecture,
)
from .distance_oracle import _network_distance
from .domain import FAT, FDT, CableSegment
from .errors import ValidationError
from .fdt_generation import _apply_fat_traceability
from .hop_limits import _b2b_endpoint, b2b_hop_limit
from .perf_logger import PerformanceLogger
from .spatial_utils import DistanceCalculator
from .topology import RoadTopologyEngine
from .wing_chain import _optimal_wing_order, _ordered_wing_fats, _wing_chain_objective


def validate_design(fdts: List[FDT],
                   fats: List[FAT],
                   b2b_cables: List[CableSegment],
                   b2c_cables: List[CableSegment],
                   logger: PerformanceLogger):
    """Deprecated: design validation was removed in BOQ-only workflow."""
    logger.start_module("Validation")
    logger.log("Validation module is disabled. BOQ generation is the active output workflow.")
    logger.end_module("Validation")


def validate_drop_cable_constraints(b2c_cables: List[CableSegment], logger: PerformanceLogger):
    """Hard validation: every FAT->Customer cable must be <= MAX_BOX_TO_CUSTOMER_DISTANCE."""
    logger.start_module("Drop Cable Constraint Validation")
    for cable in b2c_cables:
        if float(cable.length) > (rc.MAX_BOX_TO_CUSTOMER_DISTANCE + rc.DROP_LENGTH_TOLERANCE):
            raise ValidationError(
                f"Customer connection exceeds maximum distance: {cable.name} = "
                f"{float(cable.length):.2f}m > {rc.MAX_BOX_TO_CUSTOMER_DISTANCE + rc.DROP_LENGTH_TOLERANCE:.2f}m"
            )
    logger.log(
        f"Validated {len(b2c_cables)} drop cables: all <= {rc.MAX_BOX_TO_CUSTOMER_DISTANCE + rc.DROP_LENGTH_TOLERANCE:.2f}m"
    )
    logger.end_module("Drop Cable Constraint Validation")


def diagnose_b2b_headroom(fdts: List[FDT],
                          b2b_cables: List[CableSegment],
                          logger: PerformanceLogger,
                          profile: Optional['CapacityProfile'] = None,
                          dist_calc: Optional['DistanceCalculator'] = None,
                          topo: Optional['RoadTopologyEngine'] = None) -> Dict[str, Any]:
    """[Phase 0] Attribute every over-limit hop to a cause, before anyone acts.

    Two questions this answers, both of which were unanswerable from the old
    log:

    1. ORDERING HEADROOM. For each wing, compare the worst hop excess under the
       shipped cascade order against the best achievable over every permutation
       of that same wing. A non-zero gap means the violation is an artefact of
       sequencing and can be fixed for free. A zero gap means no re-ordering
       helps and the problem is wing membership, FDT ownership, or genuine
       geography — which is a completely different remediation.

       This is what makes the "increase FDT density" advice in the old error
       message safe to act on. Previously that advice was given for every
       violation indiscriminately, including ones that were pure sequencing.

    2. ORACLE AGREEMENT. Compare the decision-time distance for each shipped
       hop against the routed cable length. Before Fix 1 these disagreed by up
       to an order of magnitude (949.33m vs 65.8m on FDT-11 -> FAT-11A-01), so
       every repair pass was optimising a function unrelated to the artefact.
       A large residual here means the oracle is not actually authoritative —
       most likely the master graph tied in no points and the legacy fallback
       is live — and NOTHING else in this report should be trusted until that
       is fixed.

    Read-only. Returns a summary dict for callers that want the numbers.
    """
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    logger.start_module("Box-to-Box Headroom Diagnostic")

    summary: Dict[str, Any] = {
        'wings': 0,
        'wings_violating': 0,
        'fixable_by_reorder': 0,
        'unfixable_by_reorder': 0,
        'recoverable_excess_m': 0.0,
        'residual_excess_m': 0.0,
        'oracle_live': _distance_oracle_mod._DISTANCE_ORACLE is not None
                       and _distance_oracle_mod._DISTANCE_ORACLE.is_live(),
        'max_oracle_disagreement_m': 0.0,
        'oracle_disagreements': [],
    }

    # ── 1. ordering headroom, per wing ───────────────────────────────────
    reorder_rows: List[str] = []
    membership_rows: List[str] = []

    for fdt in fdts:
        for wing_label in profile.wings:
            wing_fats = _ordered_wing_fats(fdt, wing_label)
            if len(wing_fats) < 2:
                continue
            summary['wings'] += 1

            shipped_excess, shipped_total = _wing_chain_objective(
                fdt, wing_fats, dist_calc=dist_calc, topo=topo)
            if shipped_excess <= 0.0:
                continue

            summary['wings_violating'] += 1
            best_order = _optimal_wing_order(
                fdt, wing_fats, dist_calc=dist_calc, topo=topo)
            best_excess, best_total = _wing_chain_objective(
                fdt, best_order, dist_calc=dist_calc, topo=topo)

            recoverable = max(0.0, shipped_excess - best_excess)
            if recoverable > rc.DROP_LENGTH_TOLERANCE:
                summary['fixable_by_reorder'] += 1
                summary['recoverable_excess_m'] += recoverable
                reorder_rows.append(
                    f"    {fdt.name} Wing {wing_label}: worst excess "
                    f"{shipped_excess:.1f}m shipped vs {best_excess:.1f}m "
                    f"achievable (recoverable {recoverable:.1f}m); "
                    f"shipped order "
                    + " -> ".join(f.name for f in wing_fats)
                    + " | best order "
                    + " -> ".join(f.name for f in best_order)
                )
            else:
                summary['unfixable_by_reorder'] += 1
                summary['residual_excess_m'] += best_excess
                membership_rows.append(
                    f"    {fdt.name} Wing {wing_label}: worst excess "
                    f"{best_excess:.1f}m and this is already the hop-optimal "
                    f"order — re-sequencing cannot help. Chain total "
                    f"{best_total:.1f}m over {len(wing_fats)} FAT(s)."
                )

    # ── 2. oracle vs routed length, per shipped hop ──────────────────────
    fdt_by_name = {f.name: f for f in fdts}
    fat_by_name: Dict[str, FAT] = {}
    for fdt in fdts:
        for fat in fdt.fats:
            fat_by_name[fat.name] = fat

    for cable in b2b_cables:
        start = fat_by_name.get(cable.start_device) or fdt_by_name.get(cable.start_device)
        end = fat_by_name.get(cable.end_device)
        if start is None or end is None:
            continue
        start_pt, end_pt = _b2b_endpoint(start), _b2b_endpoint(end)
        if start_pt is None or end_pt is None:
            continue
        decision_len = _network_distance(
            start_pt, end_pt,
            road_a_id=getattr(start, 'road_id', None) or getattr(start, 'primary_road_id', None),
            road_b_id=getattr(end, 'road_id', None),
            topo=topo, dist_calc=dist_calc,
        )
        gap = abs(decision_len - float(cable.length))
        if gap > summary['max_oracle_disagreement_m']:
            summary['max_oracle_disagreement_m'] = gap
        # 10% or 25m, whichever is larger, keeps snap/offset noise out.
        if gap > max(25.0, 0.10 * float(cable.length)):
            summary['oracle_disagreements'].append(
                f"    {cable.name}: decision {decision_len:.1f}m vs routed "
                f"{float(cable.length):.1f}m (gap {gap:.1f}m)"
            )

    # ── report ───────────────────────────────────────────────────────────
    logger.log(
        f"[B2B-HEADROOM] {summary['wings_violating']}/{summary['wings']} wing(s) "
        f"have at least one hop over limit."
    )

    if reorder_rows:
        logger.log(
            f"[B2B-HEADROOM] {summary['fixable_by_reorder']} wing(s) are still "
            f"recoverable by re-ordering alone "
            f"({summary['recoverable_excess_m']:.1f}m of excess). If this is "
            f"non-zero the shipped cascade order is NOT the hop-optimal one, "
            f"which means something re-sorted a wing after "
            f"create_fdt_wing_cascades ran — that is a regression of Fix 3, "
            f"not a data problem:"
        )
        for row in reorder_rows:
            logger.log(row)
    else:
        logger.log(
            "[B2B-HEADROOM] 0 wing(s) recoverable by re-ordering — the shipped "
            "cascade order is hop-optimal everywhere, as Fix 2/Fix 3 intend."
        )

    if membership_rows:
        logger.log(
            f"[B2B-HEADROOM] {summary['unfixable_by_reorder']} wing(s) carry "
            f"{summary['residual_excess_m']:.1f}m of excess that NO ordering "
            f"can remove. These are the genuine wing-membership / FDT-density / "
            f"geography cases — the only ones where adding an FDT or "
            f"re-partitioning is the right answer:"
        )
        for row in membership_rows:
            logger.log(row)

    if not summary['oracle_live']:
        logger.log(
            "WARNING [B2B-HEADROOM]: the distance oracle is NOT live, so every "
            "upstream decision was made on the legacy topology estimate. Treat "
            "the numbers above as unreliable and check the earlier "
            "[DISTANCE-ORACLE] line for why the master graph build failed."
        )
    elif summary['oracle_disagreements']:
        logger.log(
            f"WARNING [B2B-HEADROOM]: {len(summary['oracle_disagreements'])} "
            f"hop(s) where the decision-time distance still disagrees with the "
            f"routed length (worst "
            f"{summary['max_oracle_disagreement_m']:.1f}m). Expected causes: "
            f"anchors moved by snap_to_structures after the last repair pass, "
            f"or a point that missed the exact-match lookup and resolved via "
            f"nearest-vertex:"
        )
        for row in summary['oracle_disagreements'][:20]:
            logger.log(row)
    else:
        logger.log(
            f"[B2B-HEADROOM] Decision-time and routed distances agree on every "
            f"hop (worst gap {summary['max_oracle_disagreement_m']:.1f}m). The "
            f"repair passes and the validation gate were measuring the same "
            f"thing."
        )

    if _distance_oracle_mod._DISTANCE_ORACLE is not None:
        oracle = _distance_oracle_mod._DISTANCE_ORACLE
        logger.log(
            f"[DISTANCE-ORACLE] query stats: {oracle.stats['exact']} "
            f"exact, {oracle.stats['nearest']} nearest-vertex, "
            f"{oracle.stats['dijkstra']} graph search(es), "
            f"{oracle.stats['unanswered']} unanswered."
        )

    logger.end_module("Box-to-Box Headroom Diagnostic")
    return summary


def audit_b2b_detours(b2b_cables: List['CableSegment'],
                      dist_calc: 'DistanceCalculator',
                      logger: 'PerformanceLogger',
                      ratio_limit: float = B2B_DETOUR_RATIO_LIMIT,
                      abs_limit: float = B2B_DETOUR_ABS_LIMIT) -> List[Dict]:
    """Flag hops whose routed length is implausible against straight line.

    A genuinely long hop (river crossing, dual carriageway, a stretch with
    no frontage) has a routed/straight ratio near 1.0-1.6. A cut in the
    routing graph produces a large routed length over a tiny straight line.

    This runs BEFORE validate_box_to_box_cable_constraints so that a graph
    defect is named as a graph defect rather than laundered into a costed
    engineering exception by ALLOW_DOCUMENTED_B2B_EXCEPTIONS.

    Advisory only — never raises, never mutates a cable.
    """
    suspects: List[Dict] = []
    for c in b2b_cables or []:
        g = getattr(c, 'geometry', None)
        if g is None or g.isEmpty():
            continue
        try:
            pts = g.asPolyline()
        except Exception:
            continue
        if not pts or len(pts) < 2:
            continue
        straight = dist_calc.distance_points(pts[0], pts[-1])
        if straight <= 0.01:
            continue
        routed = float(getattr(c, 'length', 0.0) or g.length())
        ratio  = routed / straight
        if ratio >= ratio_limit and routed >= abs_limit:
            suspects.append({
                'name':     getattr(c, 'name', '?'),
                'from':     getattr(c, 'start_device', '?'),
                'to':       getattr(c, 'end_device', '?'),
                'routed':   round(routed, 2),
                'straight': round(straight, 2),
                'ratio':    round(ratio, 2),
                'x':        pts[0].x(),
                'y':        pts[0].y(),
            })

    if not suspects:
        logger.log('B2B-DETOUR-AUDIT: no implausible hops')
        return []

    suspects.sort(key=lambda s: -s['ratio'])
    logger.log(
        f'WARNING [B2B_DETOUR]: {len(suspects)} hop(s) route far longer than '
        f'their straight-line separation. This is almost always an unnoded '
        f'junction in the routing graph, not real geography — run '
        f'audit_road_layer_noding() and inspect the coordinates below '
        f'before accepting these as engineering exceptions.'
    )
    for s in suspects[:25]:
        logger.log(
            f"  {s['name']}  {s['from']} -> {s['to']}  "
            f"routed={s['routed']}m straight={s['straight']}m "
            f"ratio={s['ratio']}x  start POINT({s['x']:.2f} {s['y']:.2f})"
        )
    return suspects


def validate_b2b_detours(suspects: List[Dict]) -> None:
    """Fail the design when a routed B2B cable is an implausible detour.

    These graph-cut signatures must be resolved before optical and BOQ output
    is treated as a valid design. They cannot be waived as length exceptions.
    """
    if not suspects:
        return
    details = "\n".join(
        f"  {row['name']}: routed {row['routed']:.2f}m, "
        f"straight {row['straight']:.2f}m ({row['ratio']:.2f}x)"
        for row in suspects
    )
    raise ValidationError(
        f"[B2B_GRAPH_DETOUR] {len(suspects)} box-to-box route(s) have "
        f"implausible detours. Correct the road graph or device anchors "
        f"before accepting this design:\n{details}"
    )


def validate_box_to_box_cable_constraints(
    b2b_cables: List[CableSegment],
    logger: PerformanceLogger,
    allow_documented_exceptions: Optional[bool] = None,
):
    """Hard validation: every FDT->FAT (or FAT->FAT PCC hop) box-to-box cable
    must be <= MAX_BOX_TO_BOX_DISTANCE.

    Mirrors validate_drop_cable_constraints exactly, but for the box-to-box
    side of the network. Before this function existed, route_fdt_to_fats()
    only logged a WARNING [CABLE_LENGTH_EXCEEDED] when a hop exceeded the
    limit and created the oversized cable anyway — there was no pipeline
    gate downstream to catch it, unlike drop cables (validated right after
    routing) or the FDT/FAT capacity rules (multiple hard gates). This is
    that missing gate: a genuine correctness/cost problem (confirmed
    directly against reported oversized cables — 389m/358m/350m hops against
    a 250m limit), not a defensive one.

    Uses the same DROP_LENGTH_TOLERANCE the rest of the pipeline already
    applies to every other length comparison (drop cables, wing-chain hop
    checks) so a hop at, say, 250.3m from snapping/geometry precision noise
    doesn't spuriously fail a design that's actually compliant.
    """
    logger.start_module("Box-to-Box Cable Constraint Validation")

    # [Fix 4] Per-hop-type limits resolved through the same helper the repair
    # passes use, instead of a single hard-coded MAX_BOX_TO_BOX_DISTANCE for
    # every hop. hop_seq is 1 for the FDT->FAT-01 hop, so hop_seq-1 maps
    # straight onto b2b_hop_limit()'s index.
    violations = []
    for cable in b2b_cables:
        cable_length = float(cable.length)
        core_info = getattr(cable, 'core_info', None) or {}
        hop_seq = core_info.get('hop_seq', 1)
        try:
            hop_index = max(0, int(hop_seq) - 1)
        except (TypeError, ValueError):
            hop_index = 0
        hop_limit = b2b_hop_limit(hop_index)
        if cable_length > hop_limit + rc.DROP_LENGTH_TOLERANCE:
            violations.append({
                'name': cable.name,
                'length': cable_length,
                'limit': hop_limit,
                'excess': cable_length - hop_limit,
                'start_device': cable.start_device,
                'end_device': cable.end_device,
                'fdt_id': cable.fdt_id,
                'cable': cable,
            })

    if violations:
        violation_details = "\n".join(
            f"    {v['name']}: {v['length']:.2f}m vs limit {v['limit']:.0f}m "
            f"(excess {v['excess']:.2f}m) "
            f"[{v['start_device']} → {v['end_device']}] FDT={v['fdt_id']}"
            for v in violations
        )
        total_excess_m = sum(v['excess'] for v in violations)
        est_cost = total_excess_m * B2B_EXCESS_COST_PER_M

        summary = (
            f"[CABLE_LENGTH_EXCEEDED] {len(violations)} box-to-box cable(s) "
            f"exceed their hop limit "
            f"(FDT→FAT {b2b_hop_limit(0):.0f}m, "
            f"FAT→FAT {b2b_hop_limit(1):.0f}m):\n"
            f"{violation_details}\n\n"
            f"Total excess material: {total_excess_m:.1f}m "
            f"(~${est_cost:,.0f} at ${B2B_EXCESS_COST_PER_M:.0f}/m)\n\n"
            f"These hops survived hop-optimal wing ordering, intra-FDT wing "
            f"swapping, relay repair and chain-continuity repair, all measured "
            f"on the routing graph — so they are not ordering artefacts. The "
            f"remaining causes are geographic:\n"
            f"  1. Check the FDT(s) named above for a genuine road/coverage gap\n"
            f"  2. Consider an additional FDT in that gap to shorten the hop\n"
            f"  3. Check the log for '[WING_HOP_UNFIXABLE_BY_ORDER]', "
            f"'[B2B-OBJECTIVE]' and 'CHAIN-REPAIR unresolved' lines naming "
            f"these FDTs/FATs\n"
            f"  4. If the gap is real and unavoidable, enable "
            f"allow_documented_b2b_exceptions for this run to complete the "
            f"design with these hops registered as costed engineering exceptions"
        )

        allow_exceptions = (ALLOW_DOCUMENTED_B2B_EXCEPTIONS
                            if allow_documented_exceptions is None
                            else allow_documented_exceptions)
        if not allow_exceptions:
            raise ValidationError(summary)

        # [Fix 8] Exception mode. The design completes, but nothing is hidden:
        # every surviving cable is tagged in core_info so it carries through to
        # the output layer and the BOQ, and the full list is logged at WARNING.
        # This exists because a hard raise on a genuine river crossing makes the
        # tool unusable on real data, not to make the limit optional.
        for v in violations:
            cable = v['cable']
            info = getattr(cable, 'core_info', None)
            if isinstance(info, dict):
                info['length_exception'] = True
                info['length_limit_m'] = round(v['limit'], 2)
                info['length_excess_m'] = round(v['excess'], 2)
                info['exception_cost_estimate'] = round(
                    v['excess'] * B2B_EXCESS_COST_PER_M, 2)
        logger.log(
            "WARNING [B2B_LENGTH_EXCEPTION] "
            + summary
            + f"\n\nDocumented B2B exceptions are enabled for this run: continuing with "
              f"{len(violations)} cable(s) flagged length_exception=True. "
              f"These require engineering sign-off before build."
        )
        logger.end_module("Box-to-Box Cable Constraint Validation")
        return

    logger.log(
        f"Validated {len(b2b_cables)} box-to-box cables: all within limit "
        f"(FDT→FAT {b2b_hop_limit(0):.0f}m, "
        f"FAT→FAT {b2b_hop_limit(1):.0f}m)"
    )
    logger.end_module("Box-to-Box Cable Constraint Validation")


def validate_wing_sequences(fdts: List[FDT],
                             dist_calc: 'DistanceCalculator',
                             logger: 'PerformanceLogger',
                             profile: Optional['CapacityProfile'] = None) -> None:
    """ADVISORY ONLY: report wings whose sequence is not radially monotonic.

    [Fix 2/Fix 3 — behaviour deliberately changed from mutating to reporting]

    This used to enforce "seq-01 is the FAT closest to the FDT, seq-N the
    farthest" by REVERSING any wing that violated it and reassigning names. It
    must not do that any more, for three separate reasons:

    1. The invariant no longer exists. Cascade order is now chosen by
       _optimal_wing_order to minimise the longest hop, and a hop-optimal chain
       routinely starts at the far end of an arm. Radial monotonicity is
       exactly what was traded away to get compliant cable lengths, so
       "repairing" it here would undo Fix 2 on every wing it touched.

    2. Under the OLD radial sort this function was dead code by construction —
       a list sorted by distance from the anchor can never be inverted, which
       is why the reference run reported "0 inversion(s) corrected". Switching
       to hop-optimal ordering makes this path live for the first time, so its
       latent defects become real defects.

    3. It was never safe anyway. Reversing the list reassigned fat_sequence,
       fat_full_code and fat.name but left from_device/to_device pointing at
       the OLD names. route_fdt_to_fats() rebuilds each chain by walking those
       links through a name lookup, so the walk would break at the first
       renamed FAT, log CHAIN_INCOMPLETE, and fall back to sorting the wing by
       straight-line distance from the FDT anchor — silently discarding the
       hop-optimal order and reintroducing the original bug.

    Reversal also does not do what it appears to do: it preserves every
    FAT->FAT hop (a reversed chain has the same consecutive pairs) while
    changing the FDT->FAT[0] hop to a completely different one. It can
    therefore only ever move the first hop, and it can move it either way.

    The genuinely useful signal is kept: a non-monotonic wing is worth seeing
    in the log, because it usually means the wing straddles two arms. The
    binding hop check lives in _wing_chain_violations and the gate.
    """
    logger.start_module("Wing Sequence Validation")
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    non_monotonic = 0

    for fdt in fdts:
        fdt_pt = fdt.snapped_geometry or fdt.geometry
        if not fdt_pt:
            continue

        for wing_label in profile.wings:
            wing_fats = [f for f in fdt.fats if f.wing == wing_label]
            if len(wing_fats) < 2:
                continue

            distances = [
                dist_calc.distance_points(f.snapped_geometry or f.geometry, fdt_pt)
                for f in wing_fats
            ]

            if distances[0] > distances[1]:
                non_monotonic += 1
                logger.log(
                    f"[WING_SEQUENCE_NON_MONOTONIC]: {fdt.name} Wing "
                    f"{wing_label}: seq-01 is {distances[0]:.1f}m from the "
                    f"anchor, seq-02 is {distances[1]:.1f}m. Expected under "
                    f"hop-optimal ordering when a wing spans two arms — "
                    f"reported, not altered. Hop compliance is enforced by "
                    f"the box-to-box gate, not by radial order."
                )

    logger.log(
        f"Wing sequence validation complete — {non_monotonic} wing(s) "
        f"non-monotonic by radius (advisory; no wing was reordered)."
    )
    logger.end_module("Wing Sequence Validation")


def validate_fat_fdt_ownership(fdts: List[FDT],
                                logger: 'PerformanceLogger') -> None:
    """Fix 4: Verify every FAT's embedded FDT serial matches its actual parent FDT.

    FAT name format: FAT-{fdt_serial}{wing}-{seq}  e.g. FAT-0037B-02
    The fdt_serial embedded in the name must match fdt.fdt_serial.
    A mismatch means the FAT was borrowed into a different FDT group but
    its name was never updated — the double-ownership bug.
    """
    logger.start_module("FAT Ownership Validation")
    mismatches = 0

    for fdt in fdts:
        for fat in fdt.fats:
            expected_prefix = _project_tag("FAT", fdt.fdt_serial)
            if not fat.name.startswith(expected_prefix):
                logger.log(
                    f"WARNING [FAT_OWNERSHIP_MISMATCH]: FAT '{fat.name}' is owned by {fdt.name} "
                    f"(serial {fdt.fdt_serial}) but name embeds a different serial. "
                    f"Renaming to match parent FDT."
                )
                logger.log(
                    f"Fix 4: renaming {fat.name} → belongs to {fdt.name}. "
                    f"Correcting embedded serial from name to {fdt.fdt_serial}."
                )
                # Repair: rebuild the name from the actual parent FDT serial
                fat.fat_full_code = _project_tag(
                    "FAT", f"{fdt.fdt_serial}{fat.wing}", fat.fat_sequence
                )
                fat.name = fat.fat_full_code
                mismatches += 1

    logger.log(f"FAT ownership validation complete — {mismatches} mismatch(es) corrected.")
    logger.end_module("FAT Ownership Validation")


def validate_capacity_and_absorption_model(
    fdts: List['FDT'],
    logger: 'PerformanceLogger',
    profile: Optional['CapacityProfile'] = None,
) -> None:
    """Validate post-absorption FDT/FAT capacity invariants, plus the
    [FIX-PON-1..9] Dual-PON self-checks (spec §16/§A.12) when profile.pon_count==2.
    """
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]

    # [FIX-PON-1] max_fat_per_fdt == max_fat_per_wing * len(wings)
    if profile.max_fat_per_fdt != profile.max_fat_per_wing * len(profile.wings):
        raise ValidationError(
            "[FIX-PON-1] profile.max_fat_per_fdt must equal "
            "max_fat_per_wing * len(wings)"
        )
    # [FIX-PON-2] 8 % cores_per_fdt == 0 (core-pair stride must divide evenly)
    if 8 % profile.cores_per_fdt != 0:
        raise ValidationError("[FIX-PON-2] 8 must be divisible by cores_per_fdt")

    # [spec §13] Hard gate: at most one FDT design-wide may be below
    # minimum, and only when explicitly flagged as the global final FDT
    # exception (never inferred from a road/corridor/branch/isolated-group
    # boundary). This makes the min-capacity check a real gate, not the old
    # "print WARNING [FDT_COUNT_OUT_OF_RANGE] and keep exporting" behavior.
    below_min = [
        fdt for fdt in fdts
        if len(fdt.fats) < profile.min_fat_per_fdt
    ]
    flagged_exceptions = [fdt for fdt in below_min if fdt.is_global_final_fdt_exception]
    unflagged_below_min = [fdt for fdt in below_min if not fdt.is_global_final_fdt_exception]
    if len(flagged_exceptions) > 1:
        raise ValidationError(
            "[FDT-MIN-CAPACITY] More than one FDT is flagged as the global "
            "final FDT exception: "
            f"{[f.name for f in flagged_exceptions]} — only one is permitted."
        )
    if unflagged_below_min:
        raise ValidationError(
            "[FDT-MIN-CAPACITY] FDT(s) below minimum "
            f"({profile.min_fat_per_fdt}) without the explicit global final "
            f"FDT exception flag: "
            f"{[(f.name, len(f.fats)) for f in unflagged_below_min]}"
        )

    for fdt in fdts:
        _apply_fat_traceability(fdt, dist_calc=None, topo=None, roads=None)
        if len(fdt.fats) > profile.max_fat_per_fdt:
            raise ValidationError(
                f"{fdt.name}: {len(fdt.fats)} FATs exceeds cap of {profile.max_fat_per_fdt}"
            )

        wing_counts = {label: [f for f in fdt.fats if f.wing == label] for label in profile.wings}

        # [FIX-PON-3] sum of wing lengths == fdt.total_fat
        if sum(len(v) for v in wing_counts.values()) != len(fdt.fats):
            raise ValidationError(
                f"[FIX-PON-3] {fdt.name}: wing membership doesn't sum to total_fat "
                f"(some FAT has a wing label outside {profile.wings})"
            )
        # [FIX-PON-4] each wing <= max_fat_per_wing
        for label, members in wing_counts.items():
            if len(members) > profile.max_fat_per_wing:
                raise ValidationError(
                    f"[FIX-PON-4] {fdt.name}: wing {label} overflow ({len(members)})"
                )
        # [FIX-PON-5] each PON's two wings sum <= max_fat_per_wing*2
        for pon, (wa, wb) in PON_WINGS.items():
            if wa in wing_counts and wb in wing_counts:
                if len(wing_counts[wa]) + len(wing_counts[wb]) > profile.max_fat_per_wing * 2:
                    raise ValidationError(
                        f"[FIX-PON-5] {fdt.name}: PON{pon} ({wa}+{wb}) exceeds "
                        f"{profile.max_fat_per_wing * 2}"
                    )
        # [FIX-PON-6] under Single-PON, no FAT may carry a C/D wing label
        if profile.pon_count == 1:
            stray = [f for f in fdt.fats if f.wing in ("C", "D")]
            if stray:
                raise ValidationError(
                    f"[FIX-PON-6] {fdt.name}: Single-PON run but "
                    f"{len(stray)} FAT(s) carry wing C/D"
                )
        # [FIX-PON-9] every FAT's .wing must be a key it was actually stored under
        for label, members in wing_counts.items():
            for f in members:
                if f.wing != label:
                    raise ValidationError(
                        f"[FIX-PON-9] {fdt.name}: FAT {f.name} wing mismatch"
                    )

        for fat in fdt.fats:
            if fat.logical_fdt != fdt.name:
                raise ValidationError(
                    f"{fat.name}: logical_fdt mismatch ({fat.logical_fdt} != {fdt.name})"
                )

    # [spec §13] FAT customer-count hard gate — mirrors the FDT gate above.
    # Cable-relay FATs (FAT.is_relay, created by insert_intermediate_fats()
    # to bridge a MAX_FAT_TO_FAT_DISTANCE gap) are excluded here: they are
    # structurally not customer aggregation points, always have
    # total_customers=0 by design, and were never meant to satisfy the
    # 7-8 rule. This scopes the rule correctly rather than weakening it —
    # every genuine customer-serving FAT is still checked exactly as
    # before, and a relay FAT that somehow DID carry customers would be a
    # real bug, not something silently passed (still caught below).
    all_fats = [fat for fdt in fdts for fat in fdt.fats]
    relay_with_customers = [f for f in all_fats if f.is_relay and f.total_customers > 0]
    if relay_with_customers:
        raise ValidationError(
            f"[FAT-RELAY-INCONSISTENCY] Relay FAT(s) unexpectedly carry "
            f"customers (should always be 0): "
            f"{[(f.name, f.total_customers) for f in relay_with_customers]}"
        )
    capacity_checked_fats = [f for f in all_fats if not f.is_relay]
    fat_over_max = [f for f in capacity_checked_fats if f.total_customers > MAX_FAT_CAPACITY]
    if fat_over_max:
        raise ValidationError(
            f"[FAT-MAX-CAPACITY] FAT(s) exceed {MAX_FAT_CAPACITY} customers: "
            f"{[(f.name, f.total_customers) for f in fat_over_max]}"
        )
    fat_below_min = [f for f in capacity_checked_fats if f.total_customers < MIN_FAT_CAPACITY]
    flagged_fat_exceptions = [f for f in fat_below_min if f.is_global_final_fat_exception]
    unflagged_fat_below_min = [f for f in fat_below_min if not f.is_global_final_fat_exception]
    if len(flagged_fat_exceptions) > 1:
        raise ValidationError(
            "[FAT-MIN-CAPACITY] More than one FAT is flagged as the global "
            f"final FAT exception: {[f.name for f in flagged_fat_exceptions]} "
            "— only one is permitted."
        )
    if unflagged_fat_below_min:
        raise ValidationError(
            f"[FAT-MIN-CAPACITY] FAT(s) below minimum ({MIN_FAT_CAPACITY}) "
            "without the explicit global final FAT exception flag: "
            f"{[(f.name, f.total_customers) for f in unflagged_fat_below_min]}"
        )

    logger.log("Capacity/absorption validation passed.")


def log_final_capacity_audit(
    fdts: List['FDT'],
    logger: 'PerformanceLogger',
    profile: 'CapacityProfile',
) -> None:
    """[spec §14] Final global capacity audit, run once immediately before
    export/BOQ generation. Logs the full picture in one place so a design
    is never silently exported with a hidden capacity violation — this is
    a log-only companion to the hard-gate raises already performed by
    ``validate_capacity_and_absorption_model``, which runs earlier in the
    pipeline and would already have stopped finalization on any violation.
    """
    all_fats = [fat for fdt in fdts for fat in fdt.fats]
    total_customers = sum(f.total_customers for f in all_fats)
    total_fats = len(all_fats)
    total_fdts = len(fdts)
    min_fdt, max_fdt = profile.min_fat_per_fdt, profile.max_fat_per_fdt

    # Cable-relay FATs (FAT.is_relay) are excluded from the customer-count
    # portions of this audit for the same reason as in
    # validate_capacity_and_absorption_model — they're not customer
    # aggregation points. They still count toward total_fats/FDT-range
    # figures above, since they do occupy a real FDT/wing slot physically.
    capacity_checked_fats = [f for f in all_fats if not f.is_relay]
    fats_below_min = [f for f in capacity_checked_fats if f.total_customers < MIN_FAT_CAPACITY]
    fats_above_max = [f for f in capacity_checked_fats if f.total_customers > MAX_FAT_CAPACITY]
    final_fat_exceptions = [f.name for f in capacity_checked_fats if f.is_global_final_fat_exception]

    fdts_invalid = [
        fdt for fdt in fdts
        if not (min_fdt <= len(fdt.fats) <= max_fdt) and not fdt.is_global_final_fdt_exception
    ]
    final_fdt_exceptions = [fdt.name for fdt in fdts if fdt.is_global_final_fdt_exception]

    required_range = (
        f"{-(-total_fats // max_fdt) if total_fats else 0}-"
        f"{(total_fats // min_fdt) if total_fats else 0}"
    )
    distribution = ",".join(str(len(fdt.fats)) for fdt in
                             sorted(fdts, key=lambda f: len(f.fats), reverse=True))

    passed = (
        not fdts_invalid
        and not fats_above_max
        and len(final_fat_exceptions) <= 1
        and len([f for f in capacity_checked_fats if f.total_customers < MIN_FAT_CAPACITY
                  and not f.is_global_final_fat_exception]) == 0
        and len(final_fdt_exceptions) <= 1
    )

    logger.log("[CAPACITY-AUDIT]")
    logger.log(f"Total customers: {total_customers}")
    logger.log(f"Total FATs: {total_fats}")
    logger.log(f"Total FDTs: {total_fdts}")
    logger.log(f"PON architecture: {'DUAL' if profile.pon_count == 2 else 'SINGLE'}")
    logger.log(f"Required FDT range: {required_range}")
    logger.log(f"Selected FDT count: {total_fdts}")
    logger.log(f"FAT/FDT distribution: {distribution}")
    logger.log(f"Invalid FDTs: {len(fdts_invalid)}")
    logger.log(f"FATs below {MIN_FAT_CAPACITY}: {len(fats_below_min)}")
    logger.log(f"FATs above {MAX_FAT_CAPACITY}: {len(fats_above_max)}")
    logger.log(f"Final FAT exception: {final_fat_exceptions[0] if final_fat_exceptions else 'NONE'}")
    logger.log(f"Final FDT exception: {final_fdt_exceptions[0] if final_fdt_exceptions else 'NONE'}")
    logger.log(f"Capacity validation: {'PASS' if passed else 'FAIL'}")

    if not passed:
        raise ValidationError(
            "[CAPACITY-AUDIT] FAIL — design does not satisfy capacity rules; "
            "finalization stopped before export/BOQ generation."
        )


def validate_fdt_wing_structure(fdts: List['FDT'], profile: 'CapacityProfile') -> None:
    """[FIX-PON-7/8] No FAT name duplicated across FDTs; no duplicate
    (fdt_serial, wing, fat_sequence) tuple. Cheap, pure-Python, no geometry
    recomputation — safe to run after every mutation stage, not just at export."""
    seen_names = set()
    seen_tuples = set()
    for fdt in fdts:
        for fat in fdt.fats:
            if fat.name in seen_names:
                raise ValidationError(f"[FIX-PON-7] duplicate FAT name: {fat.name}")
            seen_names.add(fat.name)
            key = (fdt.fdt_serial, fat.wing, fat.fat_sequence)
            if key in seen_tuples:
                raise ValidationError(f"[FIX-PON-8] duplicate (serial,wing,seq): {key}")
            seen_tuples.add(key)


def validate_pon_partition(fdts: List['FDT'], profile: 'CapacityProfile',
                            logger: Optional['PerformanceLogger'] = None) -> None:
    """Diagnostic-only (non-blocking) log of each FDT's PON1/PON2 angular
    spans, for the visual spot-check the geospatial test matrix calls for
    (spec §B.15) — bearing spans alone can't prove topological correctness,
    only support a human review of where the PON boundary landed."""
    if profile.pon_count != 2 or logger is None:
        return
    for fdt in fdts:
        anchor = fdt.snapped_geometry or fdt.geometry
        if anchor is None:
            continue
        def _bearing(fat):
            p = fat.snapped_geometry or fat.geometry
            return math.degrees(math.atan2(p.y() - anchor.y(), p.x() - anchor.x()))
        pon1 = [f for f in fdt.fats if f.wing in ("A", "B")]
        pon2 = [f for f in fdt.fats if f.wing in ("C", "D")]
        if pon1 and pon2:
            b1 = [_bearing(f) for f in pon1]
            b2 = [_bearing(f) for f in pon2]
            logger.log(
                f"[PON-DIAG] {fdt.name}: PON1 span=[{min(b1):.0f},{max(b1):.0f}] "
                f"PON2 span=[{min(b2):.0f},{max(b2):.0f}] road={fdt.primary_road_id}"
            )


def validate_wing_chain_graph(
    fdt: 'FDT',
    wing_label: str,
    fat_by_name: Dict[str, 'FAT'],
) -> None:
    """Blocker 6: structural validation of one wing's cascade chain, run once
    per wing per FDT after route_fdt_to_fats completes.

    Reuses ``_walk_cascade_chain`` (the same walk BOQ already uses) rather
    than re-implementing graph traversal — this is a thin wrapper around it
    plus the assertions below. Checks: exactly one head, no orphan
    predecessor besides the head, no FAT claimed as successor by more than
    one predecessor, exactly one tail, and the walk covers every wing FAT
    exactly once (no orphan, no duplicate, all reachable — i.e. no cycle).
    """
    wing_fats = [f for f in fdt.fats if f.wing == wing_label]
    if not wing_fats:
        return

    heads = [f for f in wing_fats if f.from_device == fdt.name]
    if len(heads) != 1:
        raise ValidationError(
            f"[WING_GRAPH] {fdt.name} wing {wing_label}: expected exactly one "
            f"head (from_device=={fdt.name}), found {len(heads)}"
        )

    successor_of = Counter(f.from_device for f in wing_fats if f.from_device != fdt.name)
    over_claimed = [name for name, n in successor_of.items() if n > 1]
    if over_claimed:
        raise ValidationError(
            f"[WING_GRAPH] {fdt.name} wing {wing_label}: FAT(s) "
            f"{over_claimed} claimed as predecessor by more than one FAT"
        )

    tails = [f for f in wing_fats if not f.to_device]
    if len(tails) != 1:
        raise ValidationError(
            f"[WING_GRAPH] {fdt.name} wing {wing_label}: expected exactly one "
            f"tail (to_device==''), found {len(tails)}"
        )

    walked = _walk_cascade_chain(fdt, wing_label, fat_by_name)
    if len(walked) != len(wing_fats) or set(id(f) for f in walked) != set(id(f) for f in wing_fats):
        raise ValidationError(
            f"[WING_GRAPH] {fdt.name} wing {wing_label}: chain walk covered "
            f"{len(walked)}/{len(wing_fats)} FATs — orphan, duplicate, or cycle "
            f"in from_device/to_device links"
        )


def validate_all_wing_chain_graphs(
    fdts: List['FDT'],
    profile: 'CapacityProfile',
    fat_by_name: Optional[Dict[str, 'FAT']] = None,
) -> None:
    """Run validate_wing_chain_graph on every wing of every FDT. Call after
    route_fdt_to_fats (and again after any cross-PON rebuild, per Blocker 7
    step 5)."""
    if fat_by_name is None:
        fat_by_name = {fat.name: fat for fdt in fdts for fat in fdt.fats}
    for fdt in fdts:
        for wing_label in profile.wings:
            validate_wing_chain_graph(fdt, wing_label, fat_by_name)
