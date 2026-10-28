"""Verbatim port of the BOQ (bill of quantities) row-population stage from
``FTTx Designer — dual PON integrated.py``: ``_compute_fdt_cable_stats``,
``populate_boq_fdt_detail_layer``, ``_add_boq_row``, ``populate_boq_layer``,
``compute_cable_pole_hardware``, ``compute_aerial_accessories``,
``_write_accessories_to_boq``.

The last three (added in the strategies/ sub-phase, once it became clear
they are called directly from the pipeline orchestrator — not dispatched
per-strategy like ``build_boq``) derive aerial-hardware and accessory BOQ
quantities strictly from already-generated design objects; no QGIS/project
dependency beyond ``QgsSpatialIndex``/``QgsFeature``/``QgsGeometry``,
already available here.

No logic changes from the source script — only the QGIS types and
cross-module imports. These are OUTPUT-layer writers (as opposed to the
read-only INPUT layers every other ported module consumes): they call
``layer.startEditing()`` / ``feat.setAttributes([...])`` /
``layer.dataProvider().addFeatures([...])`` / ``layer.commitChanges()``,
which needed a small, deliberately minimal write-side addition to
``geometry_compat``'s ``QgsVectorLayer``/``QgsFeature`` (append-only, no
real edit-buffer/rollback semantics) — see that module's docstring. Callers
construct the target layer via ``QgsVectorLayer.from_records([],
field_names=[...])`` (an empty layer with a known schema) before passing it
in, matching how the source script builds a fresh memory layer.

Note: ``HOMEPASS_FIELD_NAME`` is one of the 8 tunables the pipeline
overrides per-run (see runtime_config.py's docstring) — read through
``runtime_config.HOMEPASS_FIELD_NAME``.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional

from typing import Set

from . import runtime_config as rc
from .closures import classify_length
from .config import (
    CAPACITY_PROFILES,
    POLE_PATH_TOLERANCE_M,
    POLE_TENSION_INTERVAL_M,
    TOPOLOGY_SNAP_TOLERANCE,
    CapacityProfile,
    CascadeArchitecture,
    PONArchitecture,
)
from .domain import FAT, FDT, CableSegment, DomeClosure, Homepass, RoadSegment, SupportStructure
from .errors import CRSError, ValidationError
from .geometry_compat import (
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsSpatialIndex,
    QgsVectorLayer,
)
from .homepass_assignment import _parse_homepass_value, safe_homepass_sum
from .perf_logger import PerformanceLogger
from .spatial_utils import DistanceCalculator
from .street_utils import _build_road_to_street_map


def _compute_fdt_cable_stats(
    fdt: 'FDT',
    cables: List['CableSegment'],
    cascade_architecture: 'CascadeArchitecture',
    dist_calc: 'DistanceCalculator',
    profile: Optional['CapacityProfile'] = None,
) -> Dict:
    """Return per-FDT cable statistics for the BOQ FDT Detail layer.

    PCC mode: cables are discrete B2B hop segments (one per adjacent pair).
    Each cable's .length is the routed hop length — no tap-offset arithmetic needed.
    Inter-box distances are simply [c.length for c in fdt_cables] ordered by hop_seq.

    Legacy mode: cables are road-grouped runs (FDT → last FAT per road).
    Inter-box distances are straight-line FDT→FAT steps, preserved for compatibility.
    """
    fdt_cables = [c for c in cables if c.fdt_id == fdt.name]
    fdt_pt = fdt.snapped_geometry or fdt.geometry
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]

    if cascade_architecture == CascadeArchitecture.LEGACY:
        # Legacy: one cable per road branch; inter-distances are FDT→FAT straight-line
        total_m   = sum(c.length for c in fdt_cables)
        max_reach = max((c.length for c in fdt_cables), default=0.0)
        fat_order = sorted(
            fdt.fats,
            key=lambda f: dist_calc.distance_points(
                fdt_pt, f.snapped_geometry or f.geometry
            )
        )
        inter_dists = []
        prev_pt = fdt_pt
        for fat in fat_order:
            fat_pt = fat.snapped_geometry or fat.geometry
            inter_dists.append(round(dist_calc.distance_points(prev_pt, fat_pt), 2))
            prev_pt = fat_pt
    else:
        # PCC mode: discrete B2B hop cables — one record per hop, ordered by hop_seq.
        # Sort by wing then hop_seq so Wing A hops come before Wing B hops.
        hop_cables = sorted(
            fdt_cables,
            key=lambda c: (
                c.core_info.get("wing", ""),
                c.core_info.get("hop_seq", 0),
            ),
        )
        inter_dists = [round(c.length, 2) for c in hop_cables]
        total_m     = sum(c.length for c in hop_cables)
        max_reach   = max(inter_dists) if inter_dists else 0.0

    return {
        "fdt_name":           fdt.name,
        "cascade_arch":       cascade_architecture.value.upper(),
        "fat_count":          len(fdt.fats),
        "road_count":         len(set(f.road_id for f in fdt.fats)),
        "total_cable_m":      round(total_m, 2),
        "max_reach_m":        round(max_reach, 2),
        "inter_box_dist_csv": ", ".join(str(d) for d in inter_dists),
        "fat_sequence_csv":   ", ".join(
            f.name for f in sorted(fdt.fats, key=lambda f: f.fat_sequence or "")
        ),
        # §17 additive columns — constant per run (profile-derived), never a
        # flat multiplier on the single-PON total; BOQ sums the actually-
        # generated topology, this just labels which architecture it was
        # generated under. wing_c_count/wing_d_count mirror wing_a_count/
        # wing_b_count exactly and are 0 for every FDT under Single-PON.
        "pon_count":          profile.pon_count,
        "splitter_count":     profile.pon_count,
        "cores_per_fdt":      profile.cores_per_fdt,
        "wing_a_count":       fdt.wing_a_count,
        "wing_b_count":       fdt.wing_b_count,
        "wing_c_count":       fdt.wing_c_count,
        "wing_d_count":       fdt.wing_d_count,
    }


def populate_boq_fdt_detail_layer(
    boq_fdt_layer: 'QgsVectorLayer',
    fdts: List['FDT'],
    cables: List['CableSegment'],
    cascade_architecture: 'CascadeArchitecture',
    dist_calc: 'DistanceCalculator',
    profile: Optional['CapacityProfile'] = None,
) -> None:
    """Write one row per FDT to the BOQ FDT Detail layer."""
    boq_fdt_layer.startEditing()
    for fdt in fdts:
        stats = _compute_fdt_cable_stats(fdt, cables, cascade_architecture, dist_calc, profile=profile)
        feat = QgsFeature(boq_fdt_layer.fields())
        feat.setAttributes([
            stats["fdt_name"],
            stats["cascade_arch"],
            stats["fat_count"],
            stats["road_count"],
            stats["total_cable_m"],
            stats["max_reach_m"],
            stats["inter_box_dist_csv"],
            stats["fat_sequence_csv"],
            stats["pon_count"],
            stats["splitter_count"],
            stats["cores_per_fdt"],
            stats["wing_a_count"],
            stats["wing_b_count"],
            stats["wing_c_count"],
            stats["wing_d_count"],
        ])
        boq_fdt_layer.dataProvider().addFeatures([feat])
    boq_fdt_layer.commitChanges()


def _add_boq_row(layer: QgsVectorLayer,
                 level_type: str,
                 street_name: str,
                 total_homepass: int,
                 total_fdt: int,
                 total_fat: int,
                 total_poles: int,
                 total_closures: int,
                 total_box_to_box_cable: int,
                 cable_10m: int,
                 cable_50m: int,
                 cable_100m: int,
                 cable_150m: int,
                 total_standard_length: float,
                 feeder_cable_count: int,
                 feeder_cable_length_m: float,
                 closure_fdt_cable_count: int,
                 closure_fdt_cable_length_m: float,
                 total_structures: Optional[int] = None,
                 # Phase 4: aerial accessory quantities (all default 0)
                 acc_suspension_clamp: int = 0,
                 acc_dead_end_clamp: int = 0,
                 acc_pole_bracket: int = 0,
                 acc_ss_band: int = 0,
                 acc_ss_buckle: int = 0,
                 acc_j_hook: int = 0,
                 acc_slack_bracket: int = 0,
                 acc_joint_closure: int = 0,
                 acc_pole_id_tag: int = 0,
                 acc_cable_marker: int = 0,
                 acc_drop_cable_clamp: int = 0,
                 acc_drop_wire_hook: int = 0,
                 acc_splice_sleeve: int = 0,
                 acc_heat_shrink: int = 0,
                 # Phase 10: closure/feeder pole hardware (all default 0)
                 acc_total_pole: int = 0,
                 acc_tension_clamp: int = 0,
                 acc_hook_belt: int = 0,
                 # Phase 11: project-wide fibre core totals (all default 0)
                 acc_core_total: int = 0,
                 acc_core_active: int = 0,
                 acc_core_redundant: int = 0):
    """Write one BOQ row.  ``total_structures`` defaults to ``total_poles``
    for aerial runs so the field is always populated.
    Accessory fields default to 0 and are populated by
    ``compute_aerial_accessories`` during the project-level summary row."""
    if total_structures is None:
        total_structures = total_poles
    feat = QgsFeature(layer.fields())
    feat.setAttributes([
        level_type,
        street_name,
        total_homepass,
        total_fdt,
        total_fat,
        total_poles,
        total_structures,
        total_closures,
        total_box_to_box_cable,
        cable_10m,
        cable_50m,
        cable_100m,
        cable_150m,
        total_standard_length,
        feeder_cable_count,
        feeder_cable_length_m,
        closure_fdt_cable_count,
        closure_fdt_cable_length_m,
        acc_suspension_clamp,
        acc_dead_end_clamp,
        acc_pole_bracket,
        acc_ss_band,
        acc_ss_buckle,
        acc_j_hook,
        acc_slack_bracket,
        acc_joint_closure,
        acc_pole_id_tag,
        acc_cable_marker,
        acc_drop_cable_clamp,
        acc_drop_wire_hook,
        acc_splice_sleeve,
        acc_heat_shrink,
        acc_total_pole,
        acc_tension_clamp,
        acc_hook_belt,
        acc_core_total,
        acc_core_active,
        acc_core_redundant,
    ])
    layer.dataProvider().addFeatures([feat])


def populate_boq_layer(boq_layer: QgsVectorLayer,
                       road_layer: QgsVectorLayer,
                       homepass_layer: QgsVectorLayer,
                       pole_layer: QgsVectorLayer,
                       homepasses: List[Homepass],
                       fdts: List[FDT],
                       fats: List[FAT],
                       b2b_cables: List[CableSegment],
                       closures: List[DomeClosure],
                       closure_cables: List[CableSegment],
                       pickup_cables: List[CableSegment],
                       coverage_pct: int = 100,
                       cascade_architecture: 'CascadeArchitecture' = None,
                       logger: Optional[PerformanceLogger] = None):
    """Populate BOQ with project-level and street-level procurement summaries.

    New columns added:
      total_poles                – distinct poles snapped to on this street
      total_closures             – dome closures whose centroid maps to this street
      feeder_cable_count         – pickup-to-closure cable segments on this street
      feeder_cable_length_m      – total feeder cable length (actual geometry, metres)
      closure_fdt_cable_count    – closure-to-FDT cable segments on this street
      closure_fdt_cable_length_m – total closure-to-FDT cable length (metres)
    """
    if road_layer.crs().isGeographic():
        raise CRSError(
            f"Road layer CRS {road_layer.crs().authid()} is geographic. Projected CRS in meters is required for BOQ."
        )
    homepass_fields = [f.name() for f in homepass_layer.fields()]
    if rc.HOMEPASS_FIELD_NAME not in homepass_fields:
        raise ValidationError(
            f"Configured homepass field '{rc.HOMEPASS_FIELD_NAME}' is missing from layer {homepass_layer.name()}."
        )

    road_to_street, all_streets = _build_road_to_street_map(road_layer)
    if not all_streets:
        all_streets = ["UNASSIGNED"]

    fat_by_name = {fat.name: fat for fat in fats}
    fdt_to_street: Dict[str, str] = {}
    for fdt in fdts:
        street = "UNASSIGNED"
        if fdt.fats:
            road_id = fdt.fats[0].road_id
            street = road_to_street.get(road_id, street)
        fdt_to_street[fdt.name] = street
        if street not in all_streets:
            all_streets.append(street)

    # ── Build spatial index for poles so we can assign them to streets ─────────
    pole_road_index = QgsSpatialIndex()
    pole_id_to_road: Dict[int, int] = {}  # pole fid -> nearest road fid
    if pole_layer and pole_layer.featureCount() > 0:
        road_si = QgsSpatialIndex()
        road_geom_cache: Dict[int, QgsGeometry] = {}
        for rf in road_layer.getFeatures():
            rg = rf.geometry()
            if rg and not rg.isEmpty():
                road_si.addFeature(rf)
                road_geom_cache[rf.id()] = rg
        for pf in pole_layer.getFeatures():
            pg = pf.geometry()
            if not pg or pg.isEmpty():
                continue
            pp = pg.asPoint()
            nearest_roads = road_si.nearestNeighbor(pp, 1)
            pole_id_to_road[pf.id()] = nearest_roads[0] if nearest_roads else -1

    # ── Collect poles actually used (snapped-to) by FATs or FDTs ───────────────
    # A pole is "used on a street" if the FAT/FDT that snapped to it belongs to
    # that street.  We track unique pole coordinates per street.
    street_pole_coords: Dict[str, set] = {}

    def _register_pole(geom, street: str):
        if not geom:
            return
        key = (round(geom.x(), 6), round(geom.y(), 6))
        street_pole_coords.setdefault(street, set()).add(key)

    for fat in fats:
        street = road_to_street.get(fat.road_id, "UNASSIGNED")
        _register_pole(fat.snapped_geometry, street)

    for fdt in fdts:
        street = fdt_to_street.get(fdt.name, "UNASSIGNED")
        _register_pole(fdt.snapped_geometry, street)

    # ── Map closures to streets via their constituent FDT streets ──────────────
    closure_to_street: Dict[str, str] = {}
    for closure in closures:
        if closure.fdts:
            # use the most common street among member FDTs
            street_counts = Counter(fdt_to_street.get(f.name, "UNASSIGNED") for f in closure.fdts)
            closure_to_street[closure.name] = street_counts.most_common(1)[0][0]
        else:
            closure_to_street[closure.name] = "UNASSIGNED"

    # ── Map closure_cables (Closure→FDT) to streets via FDT ──────────────────
    fdt_name_to_street: Dict[str, str] = fdt_to_street  # alias for clarity

    # ── Map pickup_cables (Pickup→Closure) to streets via closure ─────────────
    closure_name_to_street: Dict[str, str] = closure_to_street

    # ── Initialize street buckets ──────────────────────────────────────────────
    _zero: Dict[str, object] = {
        "homepass": 0,
        "fdt": 0,
        "fat": 0,
        "cables": 0,
        "c10": 0, "c50": 0, "c100": 0, "c150": 0,
        "std_len": 0.0,
        "closures": 0,
        "feeder_cnt": 0,
        "feeder_len": 0.0,
        "cfdt_cnt": 0,
        "cfdt_len": 0.0,
    }

    street_rows: Dict[str, Dict] = {}
    for street in sorted(set(all_streets)):
        street_rows[street] = {k: (0.0 if isinstance(v, float) else type(v)()) for k, v in _zero.items()}

    def _ensure_street(s: str):
        if s not in street_rows:
            street_rows[s] = {k: (0.0 if isinstance(v, float) else type(v)()) for k, v in _zero.items()}

    # Homepass
    for hp in homepasses:
        street = road_to_street.get(hp.road_id, "UNASSIGNED")
        _ensure_street(street)
        street_rows[street]["homepass"] += _parse_homepass_value(hp.customer_count)

    # FAT count
    for fat in fats:
        street = road_to_street.get(fat.road_id, "UNASSIGNED")
        _ensure_street(street)
        street_rows[street]["fat"] += 1

    # FDT count
    for fdt in fdts:
        street = fdt_to_street.get(fdt.name, "UNASSIGNED")
        _ensure_street(street)
        street_rows[street]["fdt"] += 1

    # Box-to-Box cables (FDT→FAT distribution)
    # V5: In Legacy mode each cable object is a road-run serving multiple FATs
    # (recorded in cable.tap_points).  For BOQ purposes we count the physical
    # cable once but bucket it by street via the end_device (last FAT on road).
    # The "cables" counter tracks cable segments, not FAT connections.
    for cable in b2b_cables:
        street = "UNASSIGNED"
        end_fat = fat_by_name.get(cable.end_device)
        if end_fat:
            street = road_to_street.get(end_fat.road_id, street)
        else:
            start_fat = fat_by_name.get(cable.start_device)
            if start_fat:
                street = road_to_street.get(start_fat.road_id, street)
            else:
                street = fdt_to_street.get(cable.fdt_id, street)
        _ensure_street(street)
        standardized = classify_length(float(cable.length))
        street_rows[street]["cables"] += 1
        street_rows[street]["std_len"] += standardized
        if standardized == 10:
            street_rows[street]["c10"] += 1
        elif standardized == 50:
            street_rows[street]["c50"] += 1
        elif standardized == 100:
            street_rows[street]["c100"] += 1
        else:
            street_rows[street]["c150"] += 1

    # Closures count per street
    for closure in closures:
        street = closure_to_street.get(closure.name, "UNASSIGNED")
        _ensure_street(street)
        street_rows[street]["closures"] += 1

    # Feeder cables (Pickup → Closure) per street
    for cable in pickup_cables:
        street = closure_name_to_street.get(cable.end_device, "UNASSIGNED")
        _ensure_street(street)
        street_rows[street]["feeder_cnt"] += 1
        street_rows[street]["feeder_len"] += float(cable.length)

    # Closure-to-FDT cables per street (keyed by FDT name = cable.fdt_id / end_device)
    for cable in closure_cables:
        fdt_name = cable.end_device  # end_device is the FDT name
        street = fdt_name_to_street.get(fdt_name, "UNASSIGNED")
        _ensure_street(street)
        street_rows[street]["cfdt_cnt"] += 1
        street_rows[street]["cfdt_len"] += float(cable.length)

    # ── Pole counts per street from collected coordinates ─────────────────────
    # ── Project-level totals ───────────────────────────────────────────────────
    total_c10   = sum(v["c10"]   for v in street_rows.values())
    total_c50   = sum(v["c50"]   for v in street_rows.values())
    total_c100  = sum(v["c100"]  for v in street_rows.values())
    total_c150  = sum(v["c150"]  for v in street_rows.values())
    total_std_len       = sum(v["std_len"]     for v in street_rows.values())
    total_street_cables = sum(v["cables"]      for v in street_rows.values())
    total_homepass      = sum(int(v["homepass"]) for v in street_rows.values())

    # All distinct poles snapped anywhere across the project
    all_pole_coords: set = set()
    for coords in street_pole_coords.values():
        all_pole_coords.update(coords)
    total_poles_project = len(all_pole_coords)

    configured_total_homepass = safe_homepass_sum(list(homepass_layer.getFeatures()), rc.HOMEPASS_FIELD_NAME)

    # V5: When coverage trim is active the assigned total is intentionally less
    # than the raw layer sum.  Use a ±2% tolerance (minimum 10 HP) in that case.
    _is_legacy = (cascade_architecture is not None and
                  cascade_architecture == CascadeArchitecture.LEGACY)
    if coverage_pct < 100:
        _expected = round(configured_total_homepass * coverage_pct / 100)
        _tolerance = max(10, round(_expected * 0.02))
        if abs(total_homepass - _expected) > _tolerance:
            raise ValidationError(
                f"Homepass aggregation mismatch (coverage={coverage_pct}%): "
                f"assigned={total_homepass}, expected≈{_expected} "
                f"(±{_tolerance}), raw_layer={configured_total_homepass}"
            )
    else:
        if total_homepass != configured_total_homepass:
            raise ValidationError(
                f"Homepass aggregation mismatch: assigned={total_homepass}, "
                f"configured_field_sum={configured_total_homepass}"
            )

    # Ensure we have a logger available for reporting
    if logger is None:
        class _NullLogger:
            def log(self, *_):
                return
            def start_module(self, *_):
                return
            def end_module(self, *_):
                return
            def error(self, *_):
                return
        logger = _NullLogger()

    # V5: Cable-count validation.
    # PCC mode: one cable per wing per FDT (2 per FDT max) — NOT one per FAT.
    #   total_street_cables still counts per-FAT so it will never equal len(b2b_cables).
    # Legacy mode: one cable per road-branch per FDT — also not per-FAT.
    # In both cases the strict per-FAT equality is wrong. Instead verify that
    # b2b_cables is non-empty when FATs exist, and log the counts for auditing.
    _expected_min_cables = len(fdts) if fdts else 0
    if len(b2b_cables) == 0 and _expected_min_cables > 0:
        logger.log(
            f"WARNING [CABLE_MISSING]: no box-to-box cables generated "
            f"for {_expected_min_cables} FDTs"
        )
    logger.log(
        f"BOQ cable audit: {len(b2b_cables)} b2b cables for {_expected_min_cables} FDTs "
        f"({'PCC wing-runs' if not _is_legacy else 'Legacy road-runs'}), "
        f"street_cable_segments_counted={total_street_cables}"
    )
    if total_homepass < len(fats):
        raise Warning("Homepass total appears incorrect. Check value aggregation.")

    # ── PROJECT summary row ────────────────────────────────────────────────────
    _add_boq_row(
        boq_layer,
        "PROJECT",
        "ALL",
        int(total_homepass),
        len(fdts),
        len(fats),
        total_poles_project,
        len(closures),
        len(b2b_cables),
        int(total_c10),
        int(total_c50),
        int(total_c100),
        int(total_c150),
        float(total_std_len),
        len(pickup_cables),
        float(sum(c.length for c in pickup_cables)),
        len(closure_cables),
        float(sum(c.length for c in closure_cables)),
    )

    # ── Per-STREET rows ────────────────────────────────────────────────────────
    for street in sorted(street_rows.keys()):
        row = street_rows[street]
        poles_on_street = len(street_pole_coords.get(street, set()))
        _add_boq_row(
            boq_layer,
            "STREET",
            street,
            int(row["homepass"]),
            int(row["fdt"]),
            int(row["fat"]),
            poles_on_street,
            int(row["closures"]),
            int(row["cables"]),
            int(row["c10"]),
            int(row["c50"]),
            int(row["c100"]),
            int(row["c150"]),
            float(row["std_len"]),
            int(row["feeder_cnt"]),
            float(row["feeder_len"]),
            int(row["cfdt_cnt"]),
            float(row["cfdt_len"]),
        )


def compute_cable_pole_hardware(
    cables: List[CableSegment],
    structures: List[SupportStructure],
    dist_calc: 'DistanceCalculator',
    logger: PerformanceLogger,
) -> None:
    """Walk each cable's routed geometry and record, per cable, how many
    real poles it physically touches and how many of those actually get
    tensioning hardware.

    Written for closure-to-FDT and pickup-to-closure cables — the two cable
    types that have no FAT-cascade sequence to piggyback on (unlike b2b
    cables, whose intermediate-pole count is inferred from cascade_order in
    compute_aerial_accessories()). This instead reads the cable's own final
    geometry directly, so it only works correctly once that geometry
    actually reaches its devices — see the ``_with_device_stubs`` fix in
    ``CableRouter.find_shortest_path_points()`` and the matching fix in
    ``route_closure_to_fdts``'s shared-graph branch.

    Mutates each ``cable.core_info`` in place with three integer keys:
      total_pole     — every real pole within POLE_PATH_TOLERANCE_M of the
                        cable's line, in path order. Informational: this is
                        every pole the cable physically runs past, not the
                        hardware count.
      tension_clamp  — the subset of those poles that actually get a
                        tensioning clamp: both physical ends of the cable
                        (always, regardless of spacing — the cable must be
                        anchored where it terminates) plus any intermediate
                        pole that is POLE_TENSION_INTERVAL_M or farther
                        (measured along the cable) from the previous
                        tensioning point. Poles closer together than that
                        are passed with no hardware — a cable is not
                        tensioned at every pole it happens to run by.
      hook_belt      — one hook-and-belt kit per tension_clamp point (they
                        are installed together), so always equal to
                        tension_clamp.

    Structures that are not poles (handholes, manholes, chambers) are
    ignored — this is aerial-hardware accounting only.
    """
    poles = [s for s in structures if s.structure_type == "pole"]
    if not cables or not poles:
        for cable in cables:
            cable.core_info["total_pole"] = 0
            cable.core_info["tension_clamp"] = 0
            cable.core_info["hook_belt"] = 0
        return

    # One spatial index for every cable in this batch — avoids an O(cables
    # x poles) distance check when a project has thousands of poles.
    pole_index = QgsSpatialIndex()
    pole_pts: Dict[int, QgsPointXY] = {}
    for s in poles:
        feat = QgsFeature(s.id)
        feat.setGeometry(QgsGeometry.fromPointXY(s.geometry))
        pole_index.addFeature(feat)
        pole_pts[s.id] = s.geometry

    total_tension = 0
    for cable in cables:
        geom = cable.geometry
        if not geom or geom.isEmpty():
            cable.core_info["total_pole"] = 0
            cable.core_info["tension_clamp"] = 0
            cable.core_info["hook_belt"] = 0
            continue

        bbox = geom.boundingBox()
        bbox.grow(POLE_PATH_TOLERANCE_M)
        candidate_ids = pole_index.intersects(bbox)

        hits: List[tuple] = []   # (chainage, pole_id)
        for pid in candidate_ids:
            p_pt = pole_pts.get(pid)
            if p_pt is None:
                continue
            p_geom = QgsGeometry.fromPointXY(p_pt)
            if geom.distance(p_geom) <= POLE_PATH_TOLERANCE_M:
                hits.append((geom.lineLocatePoint(p_geom), pid))
        hits.sort(key=lambda t: t[0])

        total_pole_count = len(hits)

        kept: List[tuple] = []
        if hits:
            kept.append(hits[0])   # near-end pole — always tensioned
            for chain, pid in hits[1:-1]:
                if chain - kept[-1][0] >= POLE_TENSION_INTERVAL_M:
                    kept.append((chain, pid))
            if len(hits) > 1 and hits[-1][1] != kept[-1][1]:
                kept.append(hits[-1])   # far-end pole — always tensioned

        cable.core_info["total_pole"] = total_pole_count
        cable.core_info["tension_clamp"] = len(kept)
        cable.core_info["hook_belt"] = len(kept)   # 1:1 companion hardware
        total_tension += len(kept)

    logger.log(
        f"compute_cable_pole_hardware: {len(cables)} cable(s) — "
        f"{total_tension} tensioning point(s) / hook-and-belt kit(s) "
        f"(poles closer than {POLE_TENSION_INTERVAL_M:.0f}m apart share one)."
    )


def compute_aerial_accessories(
    b2b_cables: List[CableSegment],
    b2c_cables: List[CableSegment],
    fdts: List[FDT],
    fats: List[FAT],
    structures: List[SupportStructure],
    roads: Dict[int, RoadSegment],
    marker_interval_m: float = 50.0,
    closure_cables: Optional[List[CableSegment]] = None,
    pickup_cables: Optional[List[CableSegment]] = None,
) -> Dict[str, int]:
    """Derive quantities for all 14 aerial fibre accessory types.

    Every quantity is derived strictly from the generated design objects.
    No quantity is ever hard-coded or estimated.

    Accessory              Derivation
    --------------------   --------------------------------------------------
    Suspension clamp       Intermediate poles on each b2b cable path:
                           poles snapped to FATs that are neither the first
                           nor last in their wing (cascade_order > 1)
    Dead-end clamp         len(b2b_cables) × 2  (each segment has 2 terminations)
    Pole bracket           Distinct poles hosting ≥1 FAT or FDT
                           (identified by snapped_geometry coordinate)
    SS band                pole_bracket × 2
    SS buckle              pole_bracket × 4
    J-hook                 Total tap_points across all b2b cables
    Slack storage bracket  len(fdts) + count of FATs with cascade_order == max
                           in their wing (end-of-wing FATs need slack storage)
    Joint closure          Splice points: tap_points where core_pair changes
                           (proxy: len(tap_points) across all b2b cables)
    Pole ID tag            Same as pole_bracket (one tag per hosted pole)
    Cable marker tag       floor(total_b2b_length / marker_interval_m)
    Drop cable clamp       len(b2c_cables)
    Drop wire hook         len(b2c_cables) × 2
    Splice protection      Tap points across all b2b cables (one per splice)
    Heat shrink sleeve     Same as splice_protection (one sleeve per splice)

    Parameters
    ----------
    b2b_cables      : box-to-box distribution cable segments
    b2c_cables      : box-to-customer drop cable segments
    fdts            : generated FDT list
    fats            : generated FAT list (with snapped_geometry populated)
    structures      : SupportStructure list (poles or handholes etc.)
    roads           : road segment dict
    marker_interval_m: spacing between cable marker tags (default 50 m)

    Returns
    -------
    Dict mapping accessory name → integer quantity
    """
    # ------------------------------------------------------------------
    # Pole identification — collect unique pole locations from FAT/FDT
    # snapped geometry.  Two structures within TOPOLOGY_SNAP_TOLERANCE
    # of each other are treated as the same pole.
    # ------------------------------------------------------------------
    SNAP = TOPOLOGY_SNAP_TOLERANCE * 2

    def _pt_key(pt: Optional[QgsPointXY]) -> Optional[str]:
        if pt is None:
            return None
        return f"{pt.x():.2f},{pt.y():.2f}"

    # All pole coords from structures (aerial only cares about poles)
    structure_pts: Set[str] = set()
    for s in structures:
        k = _pt_key(s.geometry)
        if k:
            structure_pts.add(k)

    # Poles that host at least one FAT
    fat_pole_pts: Set[str] = set()
    for fat in fats:
        k = _pt_key(fat.snapped_geometry or fat.geometry)
        if k:
            fat_pole_pts.add(k)

    # Poles that host at least one FDT
    fdt_pole_pts: Set[str] = set()
    for fdt in fdts:
        k = _pt_key(fdt.snapped_geometry if hasattr(fdt, 'snapped_geometry') else fdt.geometry)
        if k:
            fdt_pole_pts.add(k)

    hosted_pole_pts = fat_pole_pts | fdt_pole_pts
    pole_bracket_count = len(hosted_pole_pts)

    # ------------------------------------------------------------------
    # Suspension clamps — intermediate poles on each b2b cable path
    # A FAT is "intermediate" if its cascade_order > 1 and it is not
    # the last in its wing sequence (i.e. cascade_order < wing_max).
    # Wing max per FDT + wing label:
    # ------------------------------------------------------------------
    wing_maxes: Dict[str, int] = {}
    for fat in fats:
        key = f"{fat.parent_fdt}_{fat.wing}"
        current = wing_maxes.get(key, 0)
        if fat.cascade_order > current:
            wing_maxes[key] = fat.cascade_order

    suspension_clamp_count = 0
    for fat in fats:
        key = f"{fat.parent_fdt}_{fat.wing}"
        wmax = wing_maxes.get(key, 1)
        if fat.cascade_order > 1 and fat.cascade_order < wmax:
            suspension_clamp_count += 1

    # ------------------------------------------------------------------
    # Tap points across all b2b cables
    # ------------------------------------------------------------------
    total_tap_points = sum(len(seg.tap_points) for seg in b2b_cables)

    # ------------------------------------------------------------------
    # Total b2b cable length
    # ------------------------------------------------------------------
    total_b2b_length = sum(seg.length for seg in b2b_cables)

    # ------------------------------------------------------------------
    # End-of-wing FATs (need slack storage bracket)
    # ------------------------------------------------------------------
    end_of_wing_fats = sum(
        1 for fat in fats
        if fat.cascade_order == wing_maxes.get(f"{fat.parent_fdt}_{fat.wing}", 1)
    )
    slack_bracket_count = len(fdts) + end_of_wing_fats

    # ------------------------------------------------------------------
    # Closure/feeder pole hardware — summed from the per-cable figures
    # compute_cable_pole_hardware() already wrote into cable.core_info
    # (see Phase 10). Not recomputed here; this just rolls the per-cable
    # values up into the project-level accessory summary.
    # ------------------------------------------------------------------
    closure_feeder_cables = list(closure_cables or []) + list(pickup_cables or [])
    total_pole_count      = sum(c.core_info.get("total_pole", 0) for c in closure_feeder_cables)
    tension_clamp_count   = sum(c.core_info.get("tension_clamp", 0) for c in closure_feeder_cables)
    hook_belt_count       = sum(c.core_info.get("hook_belt", 0) for c in closure_feeder_cables)

    # ------------------------------------------------------------------
    # Project-wide fibre core totals — summed from the feeder cables'
    # own manifests (one feeder cable per closure, each already carrying
    # that closure's exact total/active/redundant core usage; see
    # route_pickup_to_closure). Summing across every feeder in the
    # project gives the project-wide "total core needed" figure.
    # ------------------------------------------------------------------
    project_total_core     = sum(c.core_info.get("total_core", 0) for c in (pickup_cables or []))
    project_active_core    = sum(c.core_info.get("active_core", 0) for c in (pickup_cables or []))
    project_redundant_core = sum(c.core_info.get("redundant_core", 0) for c in (pickup_cables or []))

    # ------------------------------------------------------------------
    # Assemble result dict
    # ------------------------------------------------------------------
    return {
        "Suspension Clamp":        suspension_clamp_count,
        "Dead-End Clamp":          len(b2b_cables) * 2,
        "Pole Bracket":            pole_bracket_count,
        "Stainless Steel Band":    pole_bracket_count * 2,
        "Stainless Steel Buckle":  pole_bracket_count * 4,
        "J-Hook":                  total_tap_points,
        "Slack Storage Bracket":   slack_bracket_count,
        "Joint Closure":           total_tap_points,
        "Pole Identification Tag": pole_bracket_count,
        "Cable Marker":            max(1, int(total_b2b_length / marker_interval_m)),
        "Drop Cable Clamp":        len(b2c_cables),
        "Drop Wire Hook":          len(b2c_cables) * 2,
        "Splice Protection Sleeve":total_tap_points,
        "Heat Shrink Sleeve":      total_tap_points,
        "Total Pole (Closure/Feeder)":      total_pole_count,
        "Tensioning Clamp (Closure/Feeder)":tension_clamp_count,
        "Hook and Belt (Closure/Feeder)":   hook_belt_count,
        "Total Core (Project)":      project_total_core,
        "Active Core (Project)":     project_active_core,
        "Redundant Core (Project)":  project_redundant_core,
    }


def _write_accessories_to_boq(
    boq_layer: QgsVectorLayer,
    accessories: Dict[str, int],
    logger: PerformanceLogger,
) -> None:
    """Write aerial accessories as a dedicated PROJECT-level BOQ row.

    Rather than adding 14 extra rows (one per accessory), the quantities
    are packed into the 14 ``acc_*`` fields of a single summary row
    with ``level_type = 'AERIAL_ACCESSORIES'``.  This keeps the BOQ
    layer schema stable and the row count predictable.
    """
    # Map accessory names to field kwargs for _add_boq_row
    _field_map = {
        "Suspension Clamp":         "acc_suspension_clamp",
        "Dead-End Clamp":           "acc_dead_end_clamp",
        "Pole Bracket":             "acc_pole_bracket",
        "Stainless Steel Band":     "acc_ss_band",
        "Stainless Steel Buckle":   "acc_ss_buckle",
        "J-Hook":                   "acc_j_hook",
        "Slack Storage Bracket":    "acc_slack_bracket",
        "Joint Closure":            "acc_joint_closure",
        "Pole Identification Tag":  "acc_pole_id_tag",
        "Cable Marker":             "acc_cable_marker",
        "Drop Cable Clamp":         "acc_drop_cable_clamp",
        "Drop Wire Hook":           "acc_drop_wire_hook",
        "Splice Protection Sleeve": "acc_splice_sleeve",
        "Heat Shrink Sleeve":       "acc_heat_shrink",
        "Total Pole (Closure/Feeder)":       "acc_total_pole",
        "Tensioning Clamp (Closure/Feeder)": "acc_tension_clamp",
        "Hook and Belt (Closure/Feeder)":    "acc_hook_belt",
        "Total Core (Project)":      "acc_core_total",
        "Active Core (Project)":     "acc_core_active",
        "Redundant Core (Project)":  "acc_core_redundant",
    }

    kwargs = {v: accessories.get(k, 0) for k, v in _field_map.items()}

    _add_boq_row(
        boq_layer,
        level_type               = "AERIAL_ACCESSORIES",
        street_name              = "Project Summary — Aerial Accessories",
        total_homepass           = 0,
        total_fdt                = 0,
        total_fat                = 0,
        total_poles              = 0,
        total_closures           = 0,
        total_box_to_box_cable   = 0,
        cable_10m                = 0,
        cable_50m                = 0,
        cable_100m               = 0,
        cable_150m               = 0,
        total_standard_length    = 0.0,
        feeder_cable_count       = 0,
        feeder_cable_length_m    = 0.0,
        closure_fdt_cable_count  = 0,
        closure_fdt_cable_length_m = 0.0,
        **kwargs,
    )

    logger.log(
        "Aerial accessories BOQ row written:\n" +
        "\n".join(f"  {k}: {v}" for k, v in accessories.items())
    )
