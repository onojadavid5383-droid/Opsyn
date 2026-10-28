"""Orchestrator port of ``run_fttx_design()`` from
``FTTx Designer — dual PON integrated.py`` — the pipeline entry point every
other engine module feeds into.

The **compute** portion (road processing through optical trace) is a
verbatim port: same call order, same functions, same convergence-loop and
diagnostic logic as the source. Only the **desktop-GUI-shaped tail** is
genuinely adapted, each documented at its call site below:

- ``QApplication.processEvents()`` — a Qt event-pump call with no meaning
  in a headless backend worker. Dropped entirely; ``progress_callback`` is
  still invoked exactly as before, and ``cancel_check`` still raises
  ``DesignCancelledError`` cooperatively at every stage boundary.
- ``QgsProject.instance()`` / the ``layers is None`` auto-discovery branch
  (``validate_and_load_layers``) — "find layers by name convention in the
  currently-open QGIS project" has no web-backend equivalent. ``layers``
  is now a required argument; the caller (Phase 3's upload/task boundary)
  is responsible for having already built it, e.g. via
  ``QgsVectorLayer.from_records(...)``.
- ``validate_selected_layers`` (CRS reprojection via ``processing.run``) —
  still deferred (see ``validation.py``'s docstring); this function now
  documents CRS-consistency of ``layers`` as a precondition instead of
  enforcing it inline. Phase 5's upload boundary is where that
  reprojection belongs.
- ``create_output_layers`` / ``create_validation_output_layer`` — the
  source builds these via real QGIS provider-string syntax
  (``QgsVectorLayer("Point?crs=...", "FDT", "memory")``) plus
  ``QgsProject`` registry bookkeeping (removing stale layers from a
  previous run in the same desktop session, then registering the new
  ones). A headless run has no accumulated project state to clean up and
  no map canvas to register into, so this port's ``_build_output_layers()``
  keeps only the actual schema (the same field lists, verbatim) and builds
  each layer via ``QgsVectorLayer.from_records([], field_names=[...])`` —
  no project involved at all, not deferred elsewhere.
- ``persist_optical_loss_summary`` / ``persist_project_identity``
  (``QgsProject.writeEntry(...)``, a project-file custom-property
  mechanism) — there is no project file in a backend run. The same data
  (``build_optical_loss_summary()``'s dict, and
  ``{project_name, project_abbreviation}``) is attached directly to
  ``PipelineResult`` instead; the caller decides where it actually
  persists (a DB column, a JSON blob on the design-run record — a Phase 3
  concern, not this module's).

``_get_strategy`` currently only resolves ``DeploymentType.AERIAL`` to a
real strategy (``AerialStrategy``) — Underground/Drainage/Hybrid raise
``NotImplementedError`` with a clear message, since only those three
strategies' pure-algorithm pieces have been ported so far (see
``strategies/underground.py``, ``strategies/drainage.py``,
``strategies/hybrid.py`` docstrings for exactly what's missing and why:
each needs a real design decision for how a web upload flow supplies "an
existing structure/channel/boundary layer," which the desktop tool
resolves via a live ``QgsProject`` lookup with no web equivalent yet).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from . import distance_oracle as _distance_oracle_mod
from . import runtime_config as rc
from .boq import (
    _write_accessories_to_boq,
    compute_aerial_accessories,
    compute_cable_pole_hardware,
    populate_boq_fdt_detail_layer,
)
from .cable_routing import CableRouter, NetworkDistanceOracle, audit_road_layer_noding, route_fat_to_homepasses
from .cascade import _override_legacy_connections, create_fat_cascade, create_legacy_cascade
from .closures import (
    correct_cable_zone_violations,
    generate_closures,
    route_closure_to_fdts,
    route_pickup_to_closure,
)
from .config import (
    MAX_MOVES_PER_FAT,
    SCRIPT_VERSION,
    CapacityProfile,
    CascadeArchitecture,
    DeploymentType,
    FTTXConfig,
    get_capacity_profile,
)
from .distance_oracle import clear_distance_oracle, install_distance_oracle
from .domain import CableSegment, DomeClosure, FAT, FDT, Homepass, RoadSegment, SupportStructure
from .errors import DesignCancelledError, LayerNotFoundError
from .fat_generation import _rebalance_fats_for_capacity, generate_fats
from .fdt_generation import generate_fdts
from .geometry_compat import QgsCoordinateReferenceSystem, QgsPointXY, QgsVectorLayer
from .homepass_assignment import _apply_coverage_trim, _parse_homepass_value, assign_homepasses_to_roads
from .optical import (
    OpticalDesignResult,
    build_optical_loss_summary,
    build_optical_paths,
    evaluate_optical_design,
    populate_validation_layer,
)
from .output_layers import populate_output_layers
from .perf_logger import PerformanceLogger
from .repair.capacity_repair import _rebalance_fdts_for_capacity, attempt_fdt_capacity_absorption
from .repair.outlier_repair import _repair_fdt_outliers_by_relay
from .repair.wing_repair import _repair_wing_chain_continuity, _repair_wing_membership_by_swap
from .spatial_utils import DistanceCalculator, SpatialIndexManager
from .strategies.aerial import AerialStrategy
from .strategies.base import DeploymentStrategy
from .strategies.duct_occupancy import DuctOccupancyLedger
from .street_utils import _build_road_to_street_map, _build_street_bboxes
from .structures import _restamp_snapped_structure_names, assign_pole_tags, propose_aerial_poles, snap_to_structures
from .topology import RoadTopologyEngine, process_roads
from .validation import (
    audit_b2b_detours,
    diagnose_b2b_headroom,
    log_final_capacity_audit,
    validate_all_wing_chain_graphs,
    validate_box_to_box_cable_constraints,
    validate_capacity_and_absorption_model,
    validate_drop_cable_constraints,
    validate_fat_fdt_ownership,
    validate_fdt_wing_structure,
    validate_pon_partition,
    validate_wing_sequences,
)
from .wing_assignment import assign_wings_per_fdt, create_fdt_wing_cascades
from .wing_chain import _REPAIR_MOVE_LEDGER, _ordered_wing_fats, _wing_chain_violations, reset_repair_move_ledger


def _get_strategy(config: FTTXConfig) -> DeploymentStrategy:
    """Factory: return the correct strategy for the configured deployment type."""
    if config.deployment_type == DeploymentType.AERIAL:
        return AerialStrategy(config.cascade_architecture)
    if config.deployment_type in (DeploymentType.UNDERGROUND, DeploymentType.DRAINAGE, DeploymentType.HYBRID):
        raise NotImplementedError(
            f"DeploymentStrategy for '{config.deployment_type.value}' is not yet ported to the "
            f"web engine — only its pure-algorithm helpers exist so far (see "
            f"strategies/{config.deployment_type.value}.py's module docstring). "
            f"Available now: aerial."
        )
    raise NotImplementedError(
        f"DeploymentStrategy for '{config.deployment_type.value}' is not registered. "
        f"Available: aerial, underground, drainage, hybrid."
    )


_OUTPUT_LAYER_SCHEMAS: Dict[str, List[str]] = {
    "fdt": [
        "Name", "fdt_code", "fdt_serial", "Tag", "total_customers", "total_FAT",
        "wing_A_count", "wing_B_count", "wing_C_count", "wing_D_count", "pon_count",
        "closure_name", "buffer_act", "core_act", "core_num_act", "buffer_red", "core_red",
        "core_num_red", "buffer_act_p2", "core_act_p2", "core_num_act_p2", "buffer_red_p2",
        "core_red_p2", "core_num_red_p2", "road_name", "structure_name",
    ],
    "fat": [
        "Name", "parent_fdt", "physical_fdt", "logical_fdt", "allocation_type",
        "network_dist_to_fdt", "fdt_serial", "wing_id", "fat_sequence", "fat_full_code",
        "from_device", "to_device", "road_id", "total_customers", "cascade_order", "wing",
        "splitter_type", "legacy_port", "road_name", "structure_name",
    ],
    "b2b": [
        "name", "start_device", "end_device", "cable_length", "fdt_id", "cable_arch",
        "fdt_port", "tap_sequence", "cable_type", "wing", "wing_name",
    ],
    "b2c": ["name", "fat_name", "customer_id", "cable_length"],
    "boq": [
        "level_type", "street_name", "total_homepass", "total_fdt", "total_fat", "total_poles",
        "total_structures", "total_closures", "total_box_to_box_cable", "cable_10m", "cable_50m",
        "cable_100m", "cable_150m", "total_standard_length", "feeder_cable_count",
        "feeder_cable_length_m", "closure_fdt_cable_count", "closure_fdt_cable_length_m",
        "acc_suspension_clamp", "acc_dead_end_clamp", "acc_pole_bracket", "acc_ss_band",
        "acc_ss_buckle", "acc_j_hook", "acc_slack_bracket", "acc_joint_closure",
        "acc_pole_id_tag", "acc_cable_marker", "acc_drop_cable_clamp", "acc_drop_wire_hook",
        "acc_splice_sleeve", "acc_heat_shrink", "acc_total_pole", "acc_tension_clamp",
        "acc_hook_belt", "acc_core_total", "acc_core_active", "acc_core_redundant",
    ],
    "closure": ["Name", "road_name", "total_FDT", "feed_capacity", "pickup_name"],
    "pole_output": ["Name", "Tag", "Original_Name"],
    "pickup_point": [
        "name", "source", "total_core_needed", "active_core_needed", "redundant_core_needed",
    ],
    "feeder": [
        "name", "start_device", "end_device", "cable_type", "length", "total_pole",
        "tension_clamp", "hook_belt", "total_core", "active_core", "redundant_core",
        "buffer_colors", "fdt_core_map",
    ],
    "closure_cable": [
        "name", "closure_name", "start_device", "end_device", "cable_length", "fdt_id",
        "buffer_act", "core_act", "core_num_act", "buffer_red", "core_red", "core_num_red",
        "cable_capacity", "cascade_group", "total_pole", "tension_clamp", "hook_belt",
        "buffer_act_p2", "core_act_p2", "core_num_act_p2", "buffer_red_p2", "core_red_p2",
        "core_num_red_p2",
    ],
    "boq_fdt": [
        "fdt_name", "cascade_arch", "fat_count", "road_count", "total_cable_m", "max_reach_m",
        "inter_box_dist_csv", "fat_sequence_csv", "pon_count", "splitter_count", "cores_per_fdt",
        "wing_a_count", "wing_b_count", "wing_c_count", "wing_d_count",
    ],
}

_OUTPUT_LAYER_DISPLAY_NAMES: Dict[str, str] = {
    "fdt": "FDT", "fat": "FAT", "b2b": "Box_to_Box", "b2c": "Box_to_Customer",
    "boq": "BOQ", "closure": "Closure", "pole_output": "Tagged_Poles",
    "pickup_point": "Pickup_Point", "feeder": "Feeder_Cable",
    "closure_cable": "Closure_to_FDT", "boq_fdt": "BOQ_FDT_Detail",
}


def _build_output_layers(crs: 'QgsCoordinateReferenceSystem') -> Dict[str, QgsVectorLayer]:
    """Headless equivalent of ``create_output_layers()``: same schemas
    (field name lists, verbatim), built via ``QgsVectorLayer.from_records
    ([], field_names=[...])`` instead of QGIS provider-string construction,
    with no ``QgsProject`` registration — see this module's docstring."""
    return {
        key: QgsVectorLayer.from_records(
            [], field_names=fields, crs=crs, layer_id=_OUTPUT_LAYER_DISPLAY_NAMES[key],
        )
        for key, fields in _OUTPUT_LAYER_SCHEMAS.items()
    }


def _build_validation_output_layer(crs: 'QgsCoordinateReferenceSystem') -> Dict[str, QgsVectorLayer]:
    """Headless equivalent of ``create_validation_output_layer()``."""
    return {
        "validation_results": QgsVectorLayer.from_records(
            [], field_names=["severity", "category", "message"],
            crs=crs, layer_id="Validation_Results",
        )
    }


@dataclass
class PipelineResult:
    """Everything ``run_fttx_design()`` used to scatter across local
    variables and QGIS output layers, bundled for the caller. Attaching
    ``optical_loss_summary``/``project_identity`` here (instead of writing
    them into a QGIS project's custom properties, as the source does) is
    this port's replacement for ``persist_optical_loss_summary``/
    ``persist_project_identity`` — see the module docstring."""
    config: FTTXConfig
    roads: Dict[int, RoadSegment]
    topo: Optional[RoadTopologyEngine]
    homepasses: List[Homepass]
    fats: List[FAT]
    fdts: List[FDT]
    structures: List[SupportStructure]
    closures: List[DomeClosure]
    b2b_cables: List[CableSegment]
    b2c_cables: List[CableSegment]
    closure_cables: List[CableSegment]
    pickup_cables: List[CableSegment]
    optical_result: Optional[OpticalDesignResult]
    optical_loss_summary: Optional[Dict[str, Any]]
    project_identity: Dict[str, str]
    output_layers: Dict[str, QgsVectorLayer]
    logger: PerformanceLogger


def run_fttx_design(config: Optional[FTTXConfig] = None,
                    layers: Optional[Dict[str, QgsVectorLayer]] = None,
                    progress_callback: Optional[Callable[[int, str], None]] = None,
                    cancel_check: Optional[Callable[[], bool]] = None) -> PipelineResult:
    """Main execution function.

    ``layers`` is required (unlike the source's GUI-only auto-discovery
    default) and must already be CRS-consistent, projected, and field-
    validated — that validation happens at the upload/ingestion boundary
    (Phase 3/5), before this function is ever called; see the module
    docstring for why ``validate_selected_layers`` isn't invoked here.

    ``cancel_check``: an optional zero-arg callable returning True once the
    caller wants this run to stop. Checked at every ``_update_progress()``
    call — i.e. at every existing stage boundary already threaded through
    the pipeline — so cancellation is cooperative and always exits through
    the same try/finally that closes the occupancy ledger and run log on
    any other exception path.
    """
    if config is None:
        config = FTTXConfig()
    if layers is None:
        raise LayerNotFoundError(
            "run_fttx_design() requires `layers` — this port has no QgsProject "
            "to auto-discover them from (see module docstring)."
        )
    if progress_callback is None:
        def progress_callback(value: int, message: str = ""):
            return None

    def _update_progress(value: int, message: str = ""):
        try:
            progress_callback(value, message)
        except Exception:
            pass
        if cancel_check is not None and cancel_check():
            raise DesignCancelledError("Design run cancelled by user.")

    old_globals = {
        "MAX_BOX_TO_BOX_DISTANCE": rc.MAX_BOX_TO_BOX_DISTANCE,
        "MAX_BOX_TO_CUSTOMER_DISTANCE": rc.MAX_BOX_TO_CUSTOMER_DISTANCE,
        "DROP_LENGTH_TOLERANCE": rc.DROP_LENGTH_TOLERANCE,
        "SNAP_OFFSET_DISTANCE": rc.SNAP_OFFSET_DISTANCE,
        "FAT_OFFSET_RADIUS": rc.FAT_OFFSET_RADIUS,
        "SPLITTER_PATTERN": rc.SPLITTER_PATTERN,
        "HOMEPASS_FIELD_NAME": rc.HOMEPASS_FIELD_NAME,
        "PROJECT_ABBREVIATION": rc.PROJECT_ABBREVIATION,
    }
    rc.MAX_BOX_TO_BOX_DISTANCE = config.max_box_to_box_distance
    rc.MAX_BOX_TO_CUSTOMER_DISTANCE = config.max_box_to_customer_distance
    rc.DROP_LENGTH_TOLERANCE = config.drop_length_tolerance
    rc.SNAP_OFFSET_DISTANCE = config.snap_offset_distance
    rc.FAT_OFFSET_RADIUS = config.fat_offset_radius
    rc.SPLITTER_PATTERN = config.splitter_pattern
    rc.HOMEPASS_FIELD_NAME = config.homepass_field_name
    rc.PROJECT_ABBREVIATION = (config.project_abbreviation or "").strip().upper()

    # [Fix 1] No cross-run state. A Single->Dual->Single sequence inside one
    # process must never measure against a previous run's road graph, and
    # the repair budget must start fresh (spec §18 / Blocker 19).
    clear_distance_oracle()
    reset_repair_move_ledger()

    logger: Optional[PerformanceLogger] = None
    _ledger: Optional[DuctOccupancyLedger] = None
    try:
        logger = PerformanceLogger()
        logger.log(f"Script version: {SCRIPT_VERSION}")
        logger.log("=" * 60)
        logger.log("Starting FTTX Network Design Automation")
        logger.log("=" * 60)

        strategy = _get_strategy(config)
        logger.log(f"Deployment strategy: {config.deployment_type.value.upper()}")

        # Phase 8: Open occupancy ledger (UG/Drainage/Hybrid only)
        _needs_ledger = config.deployment_type in (
            DeploymentType.UNDERGROUND,
            DeploymentType.DRAINAGE,
            DeploymentType.HYBRID,
        )
        if _needs_ledger and config.occupancy_enabled and config.occupancy_gpkg_path:
            _ledger = DuctOccupancyLedger(config.occupancy_gpkg_path, logger)
            _ledger.open()
        elif _needs_ledger and config.occupancy_enabled:
            logger.log(
                "OccupancyLedger: config.occupancy_gpkg_path not set — "
                "occupancy tracking disabled for this run. "
                "Set it in the Deployment tab to enable persistent occupancy."
            )

        _update_progress(5, "Layer Validation")

        # Initialize utilities
        crs = layers['road'].crs()
        index_mgr = SpatialIndexManager()
        dist_calc = DistanceCalculator(crs)

        # Process roads
        _update_progress(10, "Road Processing")
        roads, topo = process_roads(layers['road'], index_mgr, logger, dist_calc=dist_calc)

        # [B2B detour fix] Pre-flight noding audit. Purely diagnostic, but it
        # names the exact junctions that would otherwise force block-perimeter
        # B2B cables, with WKT coordinates ready for the QGIS locator bar.
        try:
            audit_road_layer_noding(layers['road'], dist_calc, logger)
        except Exception as _exc:
            logger.log(f'NODING-AUDIT skipped: {_exc}')

        # Assign homepasses to roads
        _update_progress(25, "Homepass Assignment")
        homepasses = assign_homepasses_to_roads(
            layers['homepass'], layers['road'], roads, index_mgr, dist_calc, logger
        )

        # V5 Step 2: Coverage trim
        full_homepass_count = len(homepasses)
        full_customer_sum = sum(_parse_homepass_value(hp.customer_count) for hp in homepasses)
        if config.coverage_pct < 100:
            _update_progress(28, f"Coverage Trim ({config.coverage_pct}%)")
            homepasses = _apply_coverage_trim(
                homepasses, roads, config.coverage_pct, logger
            )

        # Generate FATs
        _update_progress(40, "FAT Generation")
        fats = generate_fats(
            roads,
            layers['road'],
            index_mgr,
            layers.get('building'),
            dist_calc,
            logger,
            topo=topo,
        )

        # Global FAT capacity balancing — dedicated stage, runs AFTER FAT
        # generation/tail-borrow and BEFORE FAT cascading.
        _update_progress(45, "FAT Capacity Balancing")
        fats = _rebalance_fats_for_capacity(
            fats, roads, layers['road'], index_mgr, layers.get('building'),
            dist_calc, logger, topo=topo,
        )

        # ── Stand up the routing graph BEFORE anything measures ─────────────
        _update_progress(48, "Routing Graph")
        _road_index = index_mgr.get_index(layers['road'])
        cable_router = CableRouter(layers['road'], dist_calc, roads=roads,
                                   road_index=_road_index, topology_engine=topo)
        cable_router.build_graph()

        def _collect_master_points(_fats, _fdts=None) -> List[QgsPointXY]:
            """Every anchor a cable might terminate on, deduped."""
            _pts: List[QgsPointXY] = []
            _seen = set()

            def _add(_p):
                if _p is None:
                    return
                _key = (round(_p.x(), 6), round(_p.y(), 6))
                if _key not in _seen:
                    _seen.add(_key)
                    _pts.append(_p)

            for _fat in (_fats or []):
                _add(getattr(_fat, 'offset_geometry', None))
                _add(getattr(_fat, 'snapped_geometry', None))
                _add(getattr(_fat, 'geometry', None))
            for _fdt in (_fdts or []):
                _add(getattr(_fdt, 'snapped_geometry', None))
                _add(getattr(_fdt, 'geometry', None))
            return _pts

        _oracle_pts = _collect_master_points(fats)
        _distance_oracle = None
        if _oracle_pts:
            _n_tied = cable_router.build_master_graph(_oracle_pts)
            if _n_tied:
                _distance_oracle = NetworkDistanceOracle(
                    cable_router, dist_calc=dist_calc, logger=logger)
                install_distance_oracle(_distance_oracle)
                logger.log(
                    f"[DISTANCE-ORACLE] Routing graph is now authoritative for "
                    f"every distance decision — {_n_tied}/{len(_oracle_pts)} "
                    f"anchor point(s) tied in as exact graph vertices."
                )
            else:
                logger.log(
                    "WARNING [DISTANCE-ORACLE]: master graph build tied in 0 "
                    "points; falling back to the legacy topology estimate. "
                    "Expect box-to-box hop measurements to disagree with the "
                    "routed cable lengths."
                )
        else:
            logger.log(
                "WARNING [DISTANCE-ORACLE]: no FAT anchor points available; "
                "distance oracle not installed."
            )

        # FAT cascading — FORKED by architecture
        _update_progress(50, "FAT Cascading")
        _arch = config.cascade_architecture
        logger.log(f"Cascade architecture: {_arch.value.upper()}")
        if _arch == CascadeArchitecture.LEGACY:
            fats = create_legacy_cascade(fats, roads, dist_calc, logger)
        else:
            fats = create_fat_cascade(fats, roads, dist_calc, logger)

        # Generate FDTs
        _update_progress(65, "FDT Generation")
        profile = get_capacity_profile(config.pon_architecture)
        logger.log(f"PON architecture: {config.pon_architecture.value} "
                   f"({profile.pon_count} PON, wings={profile.wings}, "
                   f"max {profile.max_fat_per_fdt} FAT/FDT)")
        fdts = generate_fdts(
            fats, logger,
            roads=roads, dist_calc=dist_calc, topo=topo, profile=profile,
        )
        _repair_fdt_outliers_by_relay(fdts, logger, roads=roads, dist_calc=dist_calc, topo=topo, profile=profile)

        def _fdt_diagnostic(checkpoint: str) -> None:
            logger.log(f"[FDT-DIAGNOSTIC] {checkpoint}")
            bad = [
                f for f in fdts
                if not (profile.min_fat_per_fdt <= len(f.fats) <= profile.max_fat_per_fdt)
            ]
            for f in bad:
                logger.log(f"  {f.name} = {len(f.fats)} FATs, {f.total_customers} customers")
            logger.log(
                f"  ({len(fdts)} FDT(s) total, {len(bad)} outside "
                f"[{profile.min_fat_per_fdt},{profile.max_fat_per_fdt}])"
            )

        def _fdt_ownership_signature() -> tuple:
            return tuple(sorted(
                (fdt.name, tuple(sorted(f.name for f in fdt.fats)))
                for fdt in fdts
            ))

        _fdt_diagnostic("AFTER_GENERATION")

        # [Corrective fix, spec §6-§8] Bounded final convergence loop.
        _road_to_street, _ = _build_road_to_street_map(layers['road'])
        _street_bboxes = _build_street_bboxes(layers['road'], _road_to_street)

        MAX_FINAL_FDT_CONVERGENCE_PASSES = 5
        previous_signature: Optional[tuple] = None
        reset_repair_move_ledger()
        for _pass_no in range(MAX_FINAL_FDT_CONVERGENCE_PASSES):
            _update_progress(70, f"FDT Capacity Convergence (pass {_pass_no + 1})")
            fdts = _rebalance_fdts_for_capacity(
                fdts, dist_calc, logger, topo=topo, profile=profile, roads=roads,
            )
            _fdt_diagnostic(f"AFTER_GLOBAL_REBALANCE_{_pass_no + 1}")

            _update_progress(75, "Wing Assignment")
            assign_wings_per_fdt(fdts, logger, roads=roads, dist_calc=dist_calc,
                                 cascade_architecture=_arch, topo=topo, profile=profile,
                                 road_to_street=_road_to_street, street_bboxes=_street_bboxes)
            _fdt_diagnostic("AFTER_WING_ASSIGNMENT")

            attempt_fdt_capacity_absorption(fdts, dist_calc, logger, topo=topo, profile=profile)
            _repair_fdt_outliers_by_relay(fdts, logger, roads=roads, dist_calc=dist_calc, topo=topo, profile=profile)

            if _arch != CascadeArchitecture.LEGACY:
                create_fdt_wing_cascades(fdts, logger,
                                         cascade_architecture=_arch,
                                         dist_calc=dist_calc, topo=topo,
                                         profile=profile)

                _repair_wing_membership_by_swap(
                    fdts, logger, roads=roads, dist_calc=dist_calc,
                    topo=topo, profile=profile)

                _repair_wing_chain_continuity(fdts, logger, roads=roads, dist_calc=dist_calc, topo=topo, profile=profile)
            _fdt_diagnostic("AFTER_CHAIN_REPAIR")

            if _arch != CascadeArchitecture.LEGACY:
                _obj_excess = 0.0
                _obj_worst = 0.0
                _obj_bad = 0
                for _f in fdts:
                    for _wl in profile.wings:
                        for _v in _wing_chain_violations(
                            _f, _ordered_wing_fats(_f, _wl),
                            dist_calc=dist_calc, topo=topo,
                        ):
                            _ex = _v[2] - _v[3]
                            _obj_excess += _ex
                            _obj_worst = max(_obj_worst, _ex)
                            _obj_bad += 1
                logger.log(
                    f"[B2B-OBJECTIVE] pass {_pass_no + 1}: "
                    f"{_obj_bad} hop(s) over limit, total excess "
                    f"{_obj_excess:.1f}m, worst {_obj_worst:.1f}m, "
                    f"{sum(1 for _c in _REPAIR_MOVE_LEDGER.values() if _c >= MAX_MOVES_PER_FAT)} "
                    f"FAT(s) at move budget"
                )

            current_signature = _fdt_ownership_signature()
            bad_now = [
                f for f in fdts
                if not (profile.min_fat_per_fdt <= len(f.fats) <= profile.max_fat_per_fdt)
            ]
            stable = (current_signature == previous_signature)
            capacity_ok = not bad_now
            logger.log(
                f"[FDT-DIAGNOSTIC] convergence pass {_pass_no + 1}: "
                f"stable={stable} capacity_ok={capacity_ok} violations={len(bad_now)}"
            )
            if stable:
                if capacity_ok:
                    logger.log(f"[FDT-DIAGNOSTIC] Convergence reached after {_pass_no + 1} pass(es).")
                else:
                    logger.log(
                        f"[FDT-DIAGNOSTIC] No further ownership changes possible; "
                        f"capacity still unresolved after {_pass_no + 1} pass(es) — "
                        f"final validation will report the remaining violation(s)."
                    )
                break
            previous_signature = current_signature
        else:
            logger.log(
                f"[FDT-DIAGNOSTIC] Reached MAX_FINAL_FDT_CONVERGENCE_PASSES "
                f"({MAX_FINAL_FDT_CONVERGENCE_PASSES}) without the ownership "
                f"signature stabilising."
            )

        _fdt_diagnostic("FINAL")
        validate_capacity_and_absorption_model(fdts, logger, profile=profile)
        validate_fdt_wing_structure(fdts, profile)
        validate_pon_partition(fdts, profile, logger=logger)
        create_fdt_wing_cascades(fdts, logger,
                                 cascade_architecture=_arch,
                                 dist_calc=dist_calc, topo=topo, profile=profile)

        # [Fix 3] Final settle.
        if _arch != CascadeArchitecture.LEGACY:
            _settle_swaps = _repair_wing_membership_by_swap(
                fdts, logger, roads=roads, dist_calc=dist_calc,
                topo=topo, profile=profile)
            _settle_before = _fdt_ownership_signature()
            _repair_wing_chain_continuity(
                fdts, logger, roads=roads, dist_calc=dist_calc,
                topo=topo, profile=profile)
            if _settle_swaps or _fdt_ownership_signature() != _settle_before:
                create_fdt_wing_cascades(fdts, logger,
                                         cascade_architecture=_arch,
                                         dist_calc=dist_calc, topo=topo,
                                         profile=profile)

        if _arch == CascadeArchitecture.LEGACY:
            _override_legacy_connections(fdts, logger)
        else:
            validate_wing_sequences(fdts, dist_calc, logger, profile=profile)
            validate_fat_fdt_ownership(fdts, logger)

        # [spec §14] Final global capacity audit.
        log_final_capacity_audit(fdts, logger, profile)

        # Load structures via strategy
        _update_progress(85, "Structure Snapping")
        structures = strategy.load_structures(layers, roads, dist_calc, config, logger)

        # Phase 9: Aerial pole proposing.
        if config.deployment_type == DeploymentType.AERIAL:
            proposed_poles = propose_aerial_poles(
                roads, structures, fats, homepasses, config, dist_calc, logger
            )
            if proposed_poles:
                structures = structures + proposed_poles

        # Phase 3: Underground augments structure list with FDT/closure locations.
        if hasattr(strategy, 'augment_structures'):
            strategy.augment_structures(fdts, [], dist_calc, logger)
            structures = strategy._structures

        fdts, fats = snap_to_structures(
            fdts, fats, homepasses, structures, roads, dist_calc, logger
        )

        # Cable routing via strategy
        _update_progress(95, "Cable Routing")

        _master_pts = _collect_master_points(
            [_fat for _fdt in fdts for _fat in _fdt.fats], fdts
        )

        if _master_pts:
            _n_tied = cable_router.build_master_graph(_master_pts)
            if _distance_oracle is not None:
                _distance_oracle.refresh()
            logger.log(
                f"Perf: master routing graph rebuilt for final device "
                f"positions with {_n_tied}/{len(_master_pts)} point(s) tied in "
                f"(replaces per-hop graph rebuilds)."
            )

        if hasattr(strategy, '_cable_router'):
            strategy._cable_router = cable_router
        if hasattr(strategy, '_roads'):
            strategy._roads = roads
        if hasattr(strategy, '_ledger'):
            strategy._ledger = _ledger

        b2b_cables = strategy.route_cable(fdts, cable_router, logger, profile=profile)

        if _arch != CascadeArchitecture.LEGACY:
            diagnose_b2b_headroom(fdts, b2b_cables, logger, profile=profile,
                                  dist_calc=dist_calc, topo=topo)

        audit_b2b_detours(b2b_cables, dist_calc, logger)

        validate_box_to_box_cable_constraints(b2b_cables, logger)

        if _arch != CascadeArchitecture.LEGACY:
            validate_all_wing_chain_graphs(fdts, profile)

        closures: List[DomeClosure] = []
        closure_cables: List[CableSegment] = []
        pickup_cables: List[CableSegment] = []

        if config.enable_closure_generation:
            closures = generate_closures(
                fdts,
                layers.get('pickup'),
                index_mgr,
                dist_calc,
                roads,
                _road_index,
                layers.get('building'),
                logger,
                pole_layer=layers['pole'],
                profile=profile,
            )

            if closures:
                closure_cables = route_closure_to_fdts(closures, cable_router, logger, profile=profile)
                closure_cables = correct_cable_zone_violations(closures, closure_cables, cable_router, logger, profile=profile)
                pickup_cables = route_pickup_to_closure(closures, layers.get('pickup'), index_mgr, cable_router, logger, closure_cables=closure_cables)

            if hasattr(strategy, 'augment_structures') and closures:
                strategy.augment_structures([], closures, dist_calc, logger)
                structures = strategy._structures

            _update_progress(100, "Closure Generation")

        # Phase 10: pole hardware + canonical pole tagging.
        if config.deployment_type in (DeploymentType.AERIAL, DeploymentType.HYBRID):
            compute_cable_pole_hardware(closure_cables, structures, dist_calc, logger)
            compute_cable_pole_hardware(pickup_cables, structures, dist_calc, logger)
            assign_pole_tags(structures, layers['road'], closures, logger)
            _restamp_snapped_structure_names(fdts, fats, structures)

        # Route FAT to homepass cables
        b2c_cables = route_fat_to_homepasses(fats, homepasses, dist_calc, logger)
        validate_drop_cable_constraints(b2c_cables, logger)

        # Optical power budget trace (additive).
        optical_result: Optional[OpticalDesignResult] = None
        if config.optical_enabled:
            _update_progress(97, "Optical Power Trace")
            optical_result = build_optical_paths(
                fdts, fats, b2b_cables, b2c_cables, homepasses, config, _arch,
                logger, profile=profile, dist_calc=dist_calc,
            )

        # Create output layers (headless — see module docstring).
        output_layers = _build_output_layers(crs)

        extra_layers = strategy.create_extra_output_layers(crs, None, config)
        output_layers.update(extra_layers)
        if extra_layers:
            logger.log(f"Strategy added {len(extra_layers)} extra output layers: {list(extra_layers.keys())}")

        optical_loss_summary: Optional[Dict[str, Any]] = None
        if optical_result is not None:
            optical_loss_summary = build_optical_loss_summary(optical_result, config)
        project_identity = {
            "project_name": config.project_name,
            "project_abbreviation": config.project_abbreviation,
        }

        output_layers.update(_build_validation_output_layer(crs))

        # Populate output layers
        populate_output_layers(
            output_layers,
            layers['road'],
            layers['homepass'],
            layers['pole'],
            homepasses,
            fdts,
            fats,
            b2b_cables,
            b2c_cables,
            closures,
            closure_cables,
            pickup_cables,
            layers.get('pickup'),
            logger,
            coverage_pct=config.coverage_pct,
            cascade_architecture=_arch,
            profile=profile,
            structures=structures,
        )

        # V5: Populate BOQ FDT Detail layer
        if 'boq_fdt' in output_layers:
            populate_boq_fdt_detail_layer(
                output_layers['boq_fdt'],
                fdts,
                b2b_cables,
                _arch,
                dist_calc,
                profile=profile,
            )

        # Phase 4: Aerial accessories BOQ
        if config.deployment_type in (DeploymentType.AERIAL, DeploymentType.HYBRID) \
                and 'boq' in output_layers:
            _update_progress(100, "Aerial Accessories BOQ")
            accessories = compute_aerial_accessories(
                b2b_cables,
                b2c_cables,
                fdts,
                fats,
                structures,
                roads,
                marker_interval_m=config.marker_interval_m,
                closure_cables=closure_cables,
                pickup_cables=pickup_cables,
            )
            _write_accessories_to_boq(output_layers['boq'], accessories, logger)

        # Populated last so it captures every finding logged during this run.
        if 'validation_results' in output_layers:
            populate_validation_layer(output_layers['validation_results'], logger)

        _update_progress(100, "Completed")

        logger.log("=" * 60)
        logger.log("FTTX Network Design Completed Successfully")
        logger.log(f"Total execution time: {time.time() - logger.start_time:.2f} seconds")
        logger.log("=" * 60)

        logger.log(
            f"Summary: roads={len(roads)} homepasses={len(homepasses)} "
            f"(coverage={config.coverage_pct}%, full={full_homepass_count} records / "
            f"{full_customer_sum} customers) architecture={_arch.value.upper()} "
            f"fats={len(fats)} fdts={len(fdts)} closures={len(closures)} "
            f"b2b_cables={len(b2b_cables)} closure_cables={len(closure_cables)} "
            f"pickup_cables={len(pickup_cables)} b2c_cables={len(b2c_cables)} "
            f"boq_rows={output_layers['boq'].featureCount()} "
            f"boq_fdt_rows={output_layers.get('boq_fdt').featureCount() if output_layers.get('boq_fdt') else 0}"
        )
        if optical_result is not None:
            _opt_overview = evaluate_optical_design(optical_result)
            logger.log(
                f"Optical customer paths: {len(optical_result.paths)} "
                f"({_opt_overview['passed_customers']} PASS / "
                f"{_opt_overview['marginal_customers']} MARGINAL / "
                f"{_opt_overview['failed_customers']} FAIL / "
                f"{_opt_overview['invalid_customers']} INVALID customer(s))"
            )

        return PipelineResult(
            config=config,
            roads=roads,
            topo=topo,
            homepasses=homepasses,
            fats=fats,
            fdts=fdts,
            structures=structures,
            closures=closures,
            b2b_cables=b2b_cables,
            b2c_cables=b2c_cables,
            closure_cables=closure_cables,
            pickup_cables=pickup_cables,
            optical_result=optical_result,
            optical_loss_summary=optical_loss_summary,
            project_identity=project_identity,
            output_layers=output_layers,
            logger=logger,
        )

    except DesignCancelledError as e:
        if logger is not None:
            logger.log(f"[CANCELLED] {str(e)}")
        raise
    except Exception as e:
        if logger is not None:
            logger.error(f"Fatal error: {str(e)}")
            # The Celery task persists this after the logger is flushed in the
            # finally block. Failed runs have no PipelineResult to carry it.
            try:
                setattr(e, "_fttx_log_path", logger.log_path)
            except Exception:
                pass
        raise
    finally:
        # Phase 8: always close ledger — even on exception.
        if _ledger is not None:
            _ledger.close()
        try:
            if logger is not None:
                logger.close()
        except Exception:
            pass
        # [Fix 1] Drop the oracle on the way out, including on the exception
        # path, so a failed run cannot leave a stale graph installed for the
        # next one.
        clear_distance_oracle()
        for key, val in old_globals.items():
            setattr(rc, key, val)
