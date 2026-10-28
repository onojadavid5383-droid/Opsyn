"""Verbatim port of the Optical Power Budget & Trace Engine from
``FTTx Designer — dual PON integrated.py``: ``OpticalStep``, ``OpticalPath``,
``FatOpticalNode``, ``FdtOpticalNode``, ``OpticalDesignResult``,
``db_from_power_ratio``, ``propagate_power_dbm``, ``fiber_loss_db``,
``splitter_output_loss_db``, ``optical_status_for_margin``,
``build_optical_paths``, ``summarize_fdt_optical``, ``summarize_fat_optical``,
``evaluate_optical_design``, ``build_optical_loss_summary``,
``populate_validation_layer``.

No logic changes from the source script — only the QGIS types and
cross-module imports. Confirmed (contrary to an earlier, stale reading of
the integration plan) to genuinely exist in the current source and to be
real, non-optional port work — PCC-architecture-only; Legacy paths are
deliberately reported as ``UNSUPPORTED_TOPOLOGY``, not modeled.

``build_optical_paths`` reuses ``_walk_cascade_chain`` (cascade.py, already
ported) and the real per-hop cable geometry already produced by
``route_fdt_to_fats``/``route_fat_to_homepasses`` — it never recomputes
distance or topology, only the loss/power arithmetic layered on top of it.

The pure calculation primitives (``db_from_power_ratio`` through
``optical_status_for_margin``) have zero QGIS dependency in the source
too, and are covered there by ``test_optical_engine.py`` (plain ``python``,
no QGIS).

Deliberately excluded from this module: ``persist_optical_loss_summary``
and ``persist_project_identity`` (``QgsProject.writeEntry(...)`` — a
project-custom-property mechanism with no web equivalent; in the eventual
backend this becomes a DB row instead, a Phase 3 concern) and
``create_validation_output_layer`` (QGIS provider-string layer
construction plus ``QgsProject`` registry cleanup — the same class of
thing already deferred for ``create_output_layers`` et al.).
``populate_validation_layer`` IS ported here despite living in the same
source section as the deferred function above it — it only writes into an
already-constructed layer via the same bound
``QgsFeature(layer.fields())``/``dataProvider().addFeatures()`` pattern
``boq.py``/``output_layers.py`` already use, reading
``PerformanceLogger.get_findings()`` (already ported, Phase 1).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .cascade import _walk_cascade_chain
from .config import (
    DEFAULT_OPTICAL_BUDGET_CLASS,
    OPTICAL_BUDGET_DB,
    OPTICAL_WAVELENGTHS,
    WING_TO_PON,
    CapacityProfile,
    CascadeArchitecture,
    FTTXConfig,
)
from .domain import FAT, FDT, CableSegment, Homepass
from .errors import ValidationError
from .geometry_compat import QgsFeature, QgsVectorLayer
from .perf_logger import PerformanceLogger
from .spatial_utils import DistanceCalculator


@dataclass
class OpticalStep:
    """One hop's power transition along an optical path (spec §17-18)."""
    step_no: int
    from_node: str
    to_node: str
    component_type: str        # "FDT_SPLITTER" | "FAT_SPLITTER" | "FIBER"
    output_role: str = ""      # "cascade" | "local" | ""
    input_power_dbm: float = 0.0
    loss_db: float = 0.0
    output_power_dbm: float = 0.0
    fiber_length_m: float = 0.0


@dataclass
class OpticalPath:
    """Complete per-customer, per-wavelength optical trace/result (spec §17)."""
    customer_id: str
    homepass_fid: int
    pon_id: str
    fdt_id: str
    fat_id: str
    branch_id: str              # wing label, e.g. "A"
    fat_stage: int
    wavelength: str

    steps: List[OpticalStep] = field(default_factory=list)

    # Loss breakdown — kept separate, never pre-summed (spec §32).
    splitter_loss_db: float = 0.0
    fiber_loss_db: float = 0.0
    splice_loss_db: float = 0.0
    connector_loss_db: float = 0.0
    misc_loss_db: float = 0.0

    splice_count: int = 0
    connector_count: int = 0
    fiber_length_m: float = 0.0
    distance_source: str = "ROUTED"   # "ROUTED" | "DIRECT" | "FALLBACK"

    fdt_output_dbm: float = 0.0
    fat_input_dbm: float = 0.0
    fat_local_output_dbm: float = 0.0

    olt_launch_power_dbm: float = 0.0
    expected_power_dbm: float = 0.0

    optical_budget_db: float = 0.0
    optical_budget_class: str = ""

    physical_loss_db: float = 0.0
    engineering_margin_db: float = 0.0
    total_design_loss_db: float = 0.0
    available_margin_db: float = 0.0

    # PASS | MARGINAL | FAIL | INVALID_TOPOLOGY | UNSUPPORTED_TOPOLOGY
    status: str = "PASS"
    warnings: List[str] = field(default_factory=list)


@dataclass
class FatOpticalNode:
    """Per-FAT, per-wavelength splitter-output record — exists independently
    of whether the FAT has any customers (feeds the FAT_Optical_Output table,
    spec §25)."""
    fat_id: str
    fdt_id: str
    branch_id: str
    fat_stage: int
    wavelength: str
    splitter_type: str
    connected_to: str                          # next FAT name, "" if terminal
    input_power_dbm: float
    local_output_power_dbm: Optional[float] = None
    cascade_output_power_dbm: Optional[float] = None
    local_loss_db: Optional[float] = None
    cascade_loss_db: Optional[float] = None
    fiber_length_m: float = 0.0
    fiber_loss_db: float = 0.0
    status: str = "PASS"


@dataclass
class FdtOpticalNode:
    """Per-FDT, per-wing, per-wavelength splitter-output record (feeds the
    FDT_Optical_Output table, spec §26)."""
    fdt_id: str
    branch_id: str
    wavelength: str
    connected_to: str
    input_power_dbm: float
    output_power_dbm: float
    loss_db: float


@dataclass
class OpticalDesignResult:
    """Everything the optical engine produced for one run."""
    paths: List[OpticalPath] = field(default_factory=list)
    fat_nodes: List[FatOpticalNode] = field(default_factory=list)
    fdt_nodes: List[FdtOpticalNode] = field(default_factory=list)


# ── Pure calculation primitives (no qgis.* dependency — see
# test_optical_engine.py, which exercises these standalone) ─────────────────

def db_from_power_ratio(power_fraction: float) -> float:
    """Convert a linear power-split fraction (0,1] to a loss in dB.
    loss_db = -10 * log10(power_fraction) — spec §33."""
    if power_fraction <= 0 or power_fraction > 1:
        raise ValueError(f"power_fraction must be in (0,1], got {power_fraction}")
    return -10.0 * math.log10(power_fraction)


def propagate_power_dbm(input_dbm: float, loss_db: float) -> float:
    """Pout(dBm) = Pin(dBm) - Loss(dB). Never multiply dBm by a ratio (spec §33)."""
    return input_dbm - loss_db


def fiber_loss_db(length_m: float, wavelength: str, atten_table: Dict[str, float]) -> float:
    """Fibre attenuation loss, in dB, for a routed length at one wavelength."""
    if length_m < 0:
        raise ValueError(f"length_m must be >= 0, got {length_m}")
    atten = atten_table.get(wavelength)
    if atten is None:
        raise ValueError(f"Unknown wavelength {wavelength!r}; expected one of {list(atten_table)}")
    return (length_m / 1000.0) * atten


def splitter_output_loss_db(splitter_type: str, role: str, library: Dict[str, Dict[str, Any]]) -> float:
    """Insertion loss (dB) for one output role ('cascade' or 'local') of a
    splitter type, from the splitter library (spec §6-§8)."""
    entry = library.get(splitter_type)
    if entry is None:
        raise ValueError(f"Unknown splitter_type {splitter_type!r}; expected one of {list(library)}")
    loss = entry["roles"].get(role)
    if loss is None:
        raise ValueError(f"Splitter {splitter_type!r} has no {role!r} output role")
    return loss


def optical_status_for_margin(margin_db: float, pass_db: float, marginal_db: float) -> str:
    """PASS / MARGINAL / FAIL from available design margin (spec §20)."""
    if margin_db >= pass_db:
        return "PASS"
    if margin_db >= marginal_db:
        return "MARGINAL"
    return "FAIL"


# ── Topology-aware trace (consumes existing generated topology only) ───────

def build_optical_paths(
    fdts: List['FDT'],
    fats: List['FAT'],
    b2b_cables: List['CableSegment'],
    b2c_cables: List['CableSegment'],
    homepasses: List['Homepass'],
    config: 'FTTXConfig',
    cascade_architecture: 'CascadeArchitecture',
    logger: 'PerformanceLogger',
    profile: Optional['CapacityProfile'] = None,
    dist_calc: Optional['DistanceCalculator'] = None,
) -> OpticalDesignResult:
    """Trace optical power from the OLT/FDT input to every customer's ONU.

    Reuses the existing cascade chain (_walk_cascade_chain) and the real
    per-hop cable geometry already produced by route_fdt_to_fats /
    route_fat_to_homepasses — this function never recomputes distance or
    topology, only the loss/power arithmetic layered on top of it.
    """
    logger.start_module("Optical Power Trace")
    result = OpticalDesignResult()

    if config.olt_launch_power_dbm is None:
        raise ValidationError("optical: FTTXConfig.olt_launch_power_dbm is not set")

    library = config.optical_splitter_library
    atten = config.optical_fiber_atten_db_per_km
    budget_db = OPTICAL_BUDGET_DB.get(
        config.optical_budget_class, OPTICAL_BUDGET_DB[DEFAULT_OPTICAL_BUDGET_CLASS]
    )
    launch_dbm = config.olt_launch_power_dbm
    pass_db = config.optical_margin_pass_db
    marginal_db = config.optical_margin_marginal_db

    fat_by_name: Dict[str, FAT] = {f.name: f for f in fats}
    hp_by_fid: Dict[int, Homepass] = {h.fid: h for h in homepasses}
    b2b_by_pair: Dict[Tuple[str, str], CableSegment] = {
        (c.start_device, c.end_device): c for c in b2b_cables
    }
    b2c_by_fat: Dict[str, List[CableSegment]] = defaultdict(list)
    for c in b2c_cables:
        b2c_by_fat[c.start_device].append(c)

    def _fat_customer_fids(fat: 'FAT') -> List[int]:
        if fat.customer_allocations:
            return list(fat.customer_allocations.keys())
        return list(fat.customers)

    def _invalid_paths_for_fat(fat: 'FAT', wavelength: str, reason: str) -> List[OpticalPath]:
        out = []
        for fid in _fat_customer_fids(fat):
            out.append(OpticalPath(
                customer_id=f"Customer_{fid}", homepass_fid=fid,
                pon_id="", fdt_id=fat.parent_fdt, fat_id=fat.name,
                branch_id=fat.wing, fat_stage=fat.cascade_order, wavelength=wavelength,
                olt_launch_power_dbm=launch_dbm, optical_budget_db=budget_db,
                optical_budget_class=config.optical_budget_class,
                status="INVALID_TOPOLOGY", warnings=[reason],
            ))
        return out

    # ── Legacy architecture: not modeled in v1 — flag, do not guess ─────────
    if cascade_architecture == CascadeArchitecture.LEGACY:
        for fat in fats:
            for wavelength in OPTICAL_WAVELENGTHS:
                for fid in _fat_customer_fids(fat):
                    result.paths.append(OpticalPath(
                        customer_id=f"Customer_{fid}", homepass_fid=fid,
                        pon_id="", fdt_id=fat.parent_fdt, fat_id=fat.name,
                        branch_id=fat.wing, fat_stage=0, wavelength=wavelength,
                        olt_launch_power_dbm=launch_dbm, optical_budget_db=budget_db,
                        optical_budget_class=config.optical_budget_class,
                        status="UNSUPPORTED_TOPOLOGY",
                        warnings=["Legacy cascade architecture optical modeling is "
                                  "out of scope for v1 (PCC only)."],
                    ))
        logger.log(f"[OPTICAL] Legacy architecture: {len(result.paths)} customer "
                    f"path(s) marked UNSUPPORTED_TOPOLOGY.")
        logger.end_module("Optical Power Trace")
        return result

    # ── PCC architecture ─────────────────────────────────────────────────────
    covered_fids: Set[int] = set()

    for fdt in fdts:
        fdt_point = fdt.snapped_geometry or fdt.geometry
        wings_present = sorted(set(f.wing for f in fdt.fats))
        for wing in wings_present:
            wing_fats_all = [f for f in fdt.fats if f.wing == wing]
            chain = _walk_cascade_chain(fdt, wing, fat_by_name)
            if not chain:
                logger.log(f"WARNING [OPTICAL]: {fdt.name} wing {wing} — no cascade "
                            f"head found; every customer on this wing marked INVALID_TOPOLOGY.")
                for fat in wing_fats_all:
                    for wavelength in OPTICAL_WAVELENGTHS:
                        result.paths.extend(_invalid_paths_for_fat(
                            fat, wavelength,
                            f"No cascade chain resolved for {fdt.name} wing {wing}."))
                        covered_fids.update(_fat_customer_fids(fat))
                continue

            n_stages = len(chain)
            if profile is not None and n_stages > profile.max_fat_per_wing:
                logger.log(f"WARNING [OPTICAL]: {fdt.name} wing {wing} has {n_stages} "
                            f"FAT(s), exceeding profile.max_fat_per_wing="
                            f"{profile.max_fat_per_wing}.")

            pon_id = f"PON{WING_TO_PON.get(wing, 1)}"

            for wavelength in OPTICAL_WAVELENGTHS:
                step_no = 0
                current_power = launch_dbm
                prev_name = fdt.name
                prev_point = fdt_point
                cum_splitter_loss = 0.0
                cum_fiber_loss = 0.0
                cum_fiber_len = 0.0
                cum_splice_ct = 0
                cum_connector_ct = 0
                cum_distance_source = "ROUTED"
                steps: List[OpticalStep] = []
                chain_ok = True

                # FDT 1x2 splitter: FDT PON input -> wing head input.
                try:
                    fdt_split_loss = splitter_output_loss_db("1x2", "cascade", library)
                except ValueError as e:
                    logger.log(f"WARNING [OPTICAL]: {fdt.name} wing {wing} — {e}")
                    for fat in chain:
                        result.paths.extend(_invalid_paths_for_fat(fat, wavelength, str(e)))
                        covered_fids.update(_fat_customer_fids(fat))
                    continue
                step_no += 1
                wing_head_input_dbm = propagate_power_dbm(current_power, fdt_split_loss)
                steps.append(OpticalStep(step_no, fdt.name, chain[0].name, "FDT_SPLITTER",
                                          "cascade", current_power, fdt_split_loss,
                                          wing_head_input_dbm))
                cum_splitter_loss += fdt_split_loss
                cum_connector_ct += 1
                current_power = wing_head_input_dbm
                fdt_output_dbm = wing_head_input_dbm

                result.fdt_nodes.append(FdtOpticalNode(
                    fdt_id=fdt.name, branch_id=wing, wavelength=wavelength,
                    connected_to=chain[0].name, input_power_dbm=launch_dbm,
                    output_power_dbm=wing_head_input_dbm, loss_db=fdt_split_loss,
                ))

                fat_cache: Dict[str, Dict[str, Any]] = {}

                for i, fat in enumerate(chain):
                    is_terminal = (i == n_stages - 1)
                    splitter_type = fat.splitter_type
                    if not splitter_type:
                        splitter_type = "1x8" if is_terminal else "1x9"
                        logger.log(f"WARNING [OPTICAL]: {fat.name} has no splitter_type "
                                    f"set; defaulted to {splitter_type!r}.")

                    # Fibre leg: prev_name -> fat.name.
                    cable = b2b_by_pair.get((prev_name, fat.name))
                    if cable is not None:
                        hop_len_m = cable.length
                        hop_source = "ROUTED"
                    elif dist_calc is not None:
                        fat_point = fat.snapped_geometry or fat.geometry
                        hop_len_m = dist_calc.distance_points(prev_point, fat_point)
                        hop_source = "FALLBACK"
                        logger.log(f"WARNING [OPTICAL]: no routed B2B cable for hop "
                                    f"{prev_name}->{fat.name}; used straight-line fallback.")
                    else:
                        logger.log(f"WARNING [OPTICAL]: no routed B2B cable for hop "
                                    f"{prev_name}->{fat.name} and no distance fallback "
                                    f"available; {fat.name} and its downstream chain "
                                    f"marked INVALID_TOPOLOGY.")
                        for remaining in chain[i:]:
                            result.paths.extend(_invalid_paths_for_fat(
                                remaining, wavelength,
                                f"Missing B2B cable for hop {prev_name}->{fat.name}."))
                            covered_fids.update(_fat_customer_fids(remaining))
                        chain_ok = False
                        break

                    try:
                        hop_fiber_loss = fiber_loss_db(hop_len_m, wavelength, atten)
                    except ValueError as e:
                        logger.log(f"WARNING [OPTICAL]: {prev_name}->{fat.name} — {e}")
                        for remaining in chain[i:]:
                            result.paths.extend(_invalid_paths_for_fat(remaining, wavelength, str(e)))
                            covered_fids.update(_fat_customer_fids(remaining))
                        chain_ok = False
                        break

                    step_no += 1
                    hop_out_dbm = propagate_power_dbm(current_power, hop_fiber_loss)
                    steps.append(OpticalStep(step_no, prev_name, fat.name, "FIBER", "",
                                              current_power, hop_fiber_loss, hop_out_dbm,
                                              fiber_length_m=hop_len_m))
                    cum_fiber_loss += hop_fiber_loss
                    cum_fiber_len += hop_len_m
                    cum_splice_ct += 1
                    cum_connector_ct += 1
                    if hop_source == "FALLBACK":
                        cum_distance_source = "FALLBACK"
                    current_power = hop_out_dbm
                    fat_input_dbm = current_power

                    # This FAT's own splitter outputs.
                    try:
                        local_loss = splitter_output_loss_db(splitter_type, "local", library)
                    except ValueError as e:
                        logger.log(f"WARNING [OPTICAL]: {fat.name} — {e}")
                        result.paths.extend(_invalid_paths_for_fat(fat, wavelength, str(e)))
                        covered_fids.update(_fat_customer_fids(fat))
                        local_loss = None

                    cascade_loss = None
                    cascade_out_dbm = None
                    if not is_terminal:
                        try:
                            cascade_loss = splitter_output_loss_db(splitter_type, "cascade", library)
                            cascade_out_dbm = propagate_power_dbm(fat_input_dbm, cascade_loss)
                        except ValueError as e:
                            logger.log(f"WARNING [OPTICAL]: {fat.name} cascade output — {e}")
                            for remaining in chain[i + 1:]:
                                result.paths.extend(_invalid_paths_for_fat(remaining, wavelength, str(e)))
                                covered_fids.update(_fat_customer_fids(remaining))
                            chain_ok = False

                    local_out_dbm = (propagate_power_dbm(fat_input_dbm, local_loss)
                                      if local_loss is not None else None)

                    result.fat_nodes.append(FatOpticalNode(
                        fat_id=fat.name, fdt_id=fdt.name, branch_id=wing,
                        fat_stage=fat.cascade_order, wavelength=wavelength,
                        splitter_type=splitter_type,
                        connected_to=(chain[i + 1].name if not is_terminal else ""),
                        input_power_dbm=fat_input_dbm,
                        local_output_power_dbm=local_out_dbm,
                        cascade_output_power_dbm=cascade_out_dbm,
                        local_loss_db=local_loss, cascade_loss_db=cascade_loss,
                        fiber_length_m=hop_len_m, fiber_loss_db=hop_fiber_loss,
                        status=("PASS" if local_loss is not None else "INVALID_TOPOLOGY"),
                    ))

                    if local_loss is not None:
                        fat_cache[fat.name] = {
                            "steps": list(steps),
                            "splitter_loss_db": cum_splitter_loss + local_loss,
                            "fiber_loss_db": cum_fiber_loss,
                            "fiber_length_m": cum_fiber_len,
                            "splice_ct": cum_splice_ct,
                            "connector_ct": cum_connector_ct,
                            "distance_source": cum_distance_source,
                            "fdt_output_dbm": fdt_output_dbm,
                            "fat_input_dbm": fat_input_dbm,
                            "fat_local_output_dbm": local_out_dbm,
                            "stage": fat.cascade_order,
                        }

                    if not chain_ok:
                        break

                    # Advance the running cascade totals to this FAT's cascade output.
                    cum_splitter_loss += cascade_loss if cascade_loss is not None else 0.0
                    current_power = cascade_out_dbm if cascade_out_dbm is not None else current_power
                    prev_name = fat.name
                    prev_point = fat.snapped_geometry or fat.geometry

                # ── Branch off to every customer cached along this wing ─────
                for fat_name, cache in fat_cache.items():
                    fat = fat_by_name[fat_name]
                    for fid in _fat_customer_fids(fat):
                        covered_fids.add(fid)
                        hp = hp_by_fid.get(fid)
                        if hp is None:
                            result.paths.append(OpticalPath(
                                customer_id=f"Customer_{fid}", homepass_fid=fid,
                                pon_id=pon_id, fdt_id=fdt.name, fat_id=fat.name,
                                branch_id=wing, fat_stage=cache["stage"], wavelength=wavelength,
                                olt_launch_power_dbm=launch_dbm, optical_budget_db=budget_db,
                                optical_budget_class=config.optical_budget_class,
                                status="INVALID_TOPOLOGY",
                                warnings=[f"Homepass fid {fid} not found in homepasses list."],
                            ))
                            continue

                        drop_cable = next(
                            (c for c in b2c_by_fat.get(fat.name, [])
                             if c.end_device.startswith(f"Customer_{fid}")),
                            None,
                        )
                        if drop_cable is not None:
                            drop_len = drop_cable.length
                            drop_source = "DIRECT"
                        elif dist_calc is not None:
                            start_pt = fat.offset_geometry or fat.snapped_geometry or fat.geometry
                            drop_len = dist_calc.distance_points(start_pt, hp.geometry)
                            drop_source = "FALLBACK"
                        else:
                            result.paths.append(OpticalPath(
                                customer_id=f"Customer_{fid}", homepass_fid=fid,
                                pon_id=pon_id, fdt_id=fdt.name, fat_id=fat.name,
                                branch_id=wing, fat_stage=cache["stage"], wavelength=wavelength,
                                olt_launch_power_dbm=launch_dbm, optical_budget_db=budget_db,
                                optical_budget_class=config.optical_budget_class,
                                status="INVALID_TOPOLOGY",
                                warnings=[f"No drop cable found for {fat.name} -> "
                                          f"Customer_{fid} and no distance fallback available."],
                            ))
                            continue

                        try:
                            drop_fiber_loss = fiber_loss_db(drop_len, wavelength, atten)
                        except ValueError as e:
                            result.paths.append(OpticalPath(
                                customer_id=f"Customer_{fid}", homepass_fid=fid,
                                pon_id=pon_id, fdt_id=fdt.name, fat_id=fat.name,
                                branch_id=wing, fat_stage=cache["stage"], wavelength=wavelength,
                                olt_launch_power_dbm=launch_dbm, optical_budget_db=budget_db,
                                optical_budget_class=config.optical_budget_class,
                                status="INVALID_TOPOLOGY", warnings=[str(e)],
                            ))
                            continue

                        drop_out_dbm = propagate_power_dbm(cache["fat_local_output_dbm"], drop_fiber_loss)

                        total_splitter_loss = cache["splitter_loss_db"]
                        total_fiber_loss = cache["fiber_loss_db"] + drop_fiber_loss
                        total_splice_ct = cache["splice_ct"] + 1
                        total_connector_ct = cache["connector_ct"] + 1
                        splice_loss = total_splice_ct * config.optical_splice_loss_db
                        connector_loss = total_connector_ct * config.optical_connector_loss_db

                        physical_loss = (total_splitter_loss + total_fiber_loss
                                          + splice_loss + connector_loss)
                        total_design_loss = physical_loss + config.optical_engineering_margin_db
                        expected_power = propagate_power_dbm(launch_dbm, physical_loss)
                        available_margin = budget_db - total_design_loss
                        status = optical_status_for_margin(available_margin, pass_db, marginal_db)

                        # "FALLBACK" if any leg (upstream cascade or drop) had to be
                        # estimated; otherwise "DIRECT" — the drop leg is always a
                        # straight-line by design, so it dominates the label whenever
                        # every real cable was found (spec §4's tier-1/tier-4 distinction).
                        if cache["distance_source"] == "FALLBACK" or drop_source == "FALLBACK":
                            final_source = "FALLBACK"
                        else:
                            final_source = "DIRECT"

                        drop_step_no = len(cache["steps"]) + 1
                        result.paths.append(OpticalPath(
                            customer_id=f"Customer_{fid}", homepass_fid=fid,
                            pon_id=pon_id, fdt_id=fdt.name, fat_id=fat.name,
                            branch_id=wing, fat_stage=cache["stage"], wavelength=wavelength,
                            steps=cache["steps"] + [OpticalStep(
                                drop_step_no, fat.name, f"Customer_{fid}", "FIBER", "local",
                                cache["fat_local_output_dbm"], drop_fiber_loss, drop_out_dbm,
                                fiber_length_m=drop_len,
                            )],
                            splitter_loss_db=total_splitter_loss, fiber_loss_db=total_fiber_loss,
                            splice_loss_db=splice_loss, connector_loss_db=connector_loss,
                            splice_count=total_splice_ct, connector_count=total_connector_ct,
                            fiber_length_m=cache["fiber_length_m"] + drop_len,
                            distance_source=final_source,
                            fdt_output_dbm=cache["fdt_output_dbm"],
                            fat_input_dbm=cache["fat_input_dbm"],
                            fat_local_output_dbm=cache["fat_local_output_dbm"],
                            olt_launch_power_dbm=launch_dbm, expected_power_dbm=expected_power,
                            optical_budget_db=budget_db, optical_budget_class=config.optical_budget_class,
                            physical_loss_db=physical_loss,
                            engineering_margin_db=config.optical_engineering_margin_db,
                            total_design_loss_db=total_design_loss,
                            available_margin_db=available_margin,
                            status=status,
                        ))

    # Any homepass with a fat_id that the walk above never reached (orphaned
    # reference) — record rather than silently drop (spec §31).
    for hp in homepasses:
        if hp.fid in covered_fids or not hp.fat_id:
            continue
        for wavelength in OPTICAL_WAVELENGTHS:
            result.paths.append(OpticalPath(
                customer_id=f"Customer_{hp.fid}", homepass_fid=hp.fid,
                pon_id="", fdt_id="", fat_id=hp.fat_id, branch_id="",
                fat_stage=0, wavelength=wavelength,
                olt_launch_power_dbm=launch_dbm, optical_budget_db=budget_db,
                optical_budget_class=config.optical_budget_class,
                status="INVALID_TOPOLOGY",
                warnings=[f"Homepass fid {hp.fid} references fat_id {hp.fat_id!r} "
                          f"which was never reached by the cascade walk."],
            ))

    logger.log(f"[OPTICAL] {len(result.paths)} customer path(s), "
                f"{len(result.fat_nodes)} FAT node(s), {len(result.fdt_nodes)} FDT "
                f"node(s) computed across {len(OPTICAL_WAVELENGTHS)} wavelength(s).")
    logger.end_module("Optical Power Trace")
    return result


# ── Aggregation & reporting ─────────────────────────────────────────────────

def summarize_fdt_optical(result: OpticalDesignResult) -> Dict[str, Dict[str, Any]]:
    """Per-FDT worst/best/avg optical summary, keyed by fdt_id (spec §22)."""
    by_fdt: Dict[str, List[OpticalPath]] = defaultdict(list)
    for p in result.paths:
        if p.fdt_id:
            by_fdt[p.fdt_id].append(p)

    summaries: Dict[str, Dict[str, Any]] = {}
    for fdt_id, plist in by_fdt.items():
        valid = [p for p in plist if p.status in ("PASS", "MARGINAL", "FAIL")]
        powers = [p.expected_power_dbm for p in valid]
        worst = min(valid, key=lambda p: p.available_margin_db, default=None)
        summaries[fdt_id] = {
            "fdt_id": fdt_id,
            "customer_count": len(set(p.homepass_fid for p in plist)),
            "min_customer_power_dbm": min(powers) if powers else None,
            "max_customer_power_dbm": max(powers) if powers else None,
            "avg_customer_power_dbm": (sum(powers) / len(powers)) if powers else None,
            "worst_customer_id": worst.customer_id if worst else None,
            "worst_customer_power_dbm": worst.expected_power_dbm if worst else None,
            "worst_margin_db": worst.available_margin_db if worst else None,
            "pass_count": sum(1 for p in valid if p.status == "PASS"),
            "marginal_count": sum(1 for p in valid if p.status == "MARGINAL"),
            "fail_count": sum(1 for p in valid if p.status == "FAIL"),
            "invalid_count": sum(1 for p in plist if p.status not in ("PASS", "MARGINAL", "FAIL")),
            "optical_status": (
                "FAIL" if any(p.status == "FAIL" for p in valid) else
                "MARGINAL" if any(p.status == "MARGINAL" for p in valid) else
                "PASS" if valid else "INVALID_TOPOLOGY"
            ),
        }
    return summaries


def summarize_fat_optical(result: OpticalDesignResult) -> Dict[str, Dict[str, Any]]:
    """Per-FAT worst/best/avg optical summary, keyed by fat_id (spec §23)."""
    by_fat: Dict[str, List[OpticalPath]] = defaultdict(list)
    for p in result.paths:
        if p.fat_id:
            by_fat[p.fat_id].append(p)

    summaries: Dict[str, Dict[str, Any]] = {}
    for fat_id, plist in by_fat.items():
        valid = [p for p in plist if p.status in ("PASS", "MARGINAL", "FAIL")]
        powers = [p.expected_power_dbm for p in valid]
        worst = min(valid, key=lambda p: p.available_margin_db, default=None)
        sample = plist[0]
        summaries[fat_id] = {
            "fat_id": fat_id,
            "fdt_id": sample.fdt_id,
            "branch_id": sample.branch_id,
            "fat_stage": sample.fat_stage,
            "input_power_dbm": sample.fat_input_dbm,
            "local_output_power_dbm": sample.fat_local_output_dbm,
            "customer_count": len(set(p.homepass_fid for p in plist)),
            "min_customer_power_dbm": min(powers) if powers else None,
            "max_customer_power_dbm": max(powers) if powers else None,
            "worst_customer_id": worst.customer_id if worst else None,
            "worst_customer_power_dbm": worst.expected_power_dbm if worst else None,
            "worst_margin_db": worst.available_margin_db if worst else None,
            "optical_status": (
                "FAIL" if any(p.status == "FAIL" for p in valid) else
                "MARGINAL" if any(p.status == "MARGINAL" for p in valid) else
                "PASS" if valid else "INVALID_TOPOLOGY"
            ),
        }
    return summaries


def evaluate_optical_design(result: OpticalDesignResult) -> Dict[str, Any]:
    """Aggregate design-level optical report (spec §36 future-optimizer hook).

    Read-only in v1 — not wired into any rebalancing/repair loop. Aggregates
    across both wavelengths; per-wavelength detail lives in the individual
    paths/tables.
    """
    valid = [p for p in result.paths if p.status in ("PASS", "MARGINAL", "FAIL")]
    invalid_fids = set(p.homepass_fid for p in result.paths
                        if p.status not in ("PASS", "MARGINAL", "FAIL"))
    margins = [p.available_margin_db for p in valid]
    powers = [p.expected_power_dbm for p in valid]
    return {
        "total_customers": len(set(p.homepass_fid for p in result.paths)),
        "passed_customers": len(set(p.homepass_fid for p in valid if p.status == "PASS")),
        "marginal_customers": len(set(p.homepass_fid for p in valid if p.status == "MARGINAL")),
        "failed_customers": len(set(p.homepass_fid for p in valid if p.status == "FAIL")),
        "invalid_customers": len(invalid_fids),
        "worst_margin_db": min(margins) if margins else None,
        "average_margin_db": (sum(margins) / len(margins)) if margins else None,
        "worst_power_dbm": min(powers) if powers else None,
        "total_fiber_length_m": sum(p.fiber_length_m for p in valid),
    }


# ── Loss-budget summary (persisted as a project property, not a layer, in
# the source — that persistence step is deferred here, see module docstring) ─

def build_optical_loss_summary(result: OpticalDesignResult,
                              config: 'FTTXConfig') -> Dict[str, Any]:
    """Compact, JSON-serializable optical loss-budget summary for the DED
    report: project totals, aggregate loss broken down by type (splitter,
    fiber/distance, splice, connector), and the worst-case customer path per
    FDT with its step-by-step trace (so the report can show exactly *where*
    loss accumulates without dumping every customer)."""
    overview = evaluate_optical_design(result)
    fdt_summaries = summarize_fdt_optical(result)

    valid = [p for p in result.paths if p.status in ("PASS", "MARGINAL", "FAIL")]
    loss_totals = {
        "splitter_loss_db_total": sum(p.splitter_loss_db for p in valid),
        "fiber_loss_db_total": sum(p.fiber_loss_db for p in valid),
        "splice_loss_db_total": sum(p.splice_loss_db for p in valid),
        "splice_count_total": sum(p.splice_count for p in valid),
        "connector_loss_db_total": sum(p.connector_loss_db for p in valid),
        "connector_count_total": sum(p.connector_count for p in valid),
        "path_count": len(valid),
    }

    paths_by_fdt: Dict[str, List[OpticalPath]] = defaultdict(list)
    for p in valid:
        if p.fdt_id:
            paths_by_fdt[p.fdt_id].append(p)

    fdt_worst_paths: Dict[str, Dict[str, Any]] = {}
    for fdt_id, plist in paths_by_fdt.items():
        worst = min(plist, key=lambda p: p.available_margin_db)
        fdt_worst_paths[fdt_id] = {
            "customer_id": worst.customer_id,
            "wavelength": worst.wavelength,
            "fat_id": worst.fat_id,
            "branch_id": worst.branch_id,
            "status": worst.status,
            "expected_power_dbm": worst.expected_power_dbm,
            "available_margin_db": worst.available_margin_db,
            "splitter_loss_db": worst.splitter_loss_db,
            "fiber_loss_db": worst.fiber_loss_db,
            "splice_loss_db": worst.splice_loss_db,
            "splice_count": worst.splice_count,
            "connector_loss_db": worst.connector_loss_db,
            "connector_count": worst.connector_count,
            "engineering_margin_db": worst.engineering_margin_db,
            "fiber_length_m": worst.fiber_length_m,
            "steps": [
                {
                    "step_no": s.step_no,
                    "from_node": s.from_node,
                    "to_node": s.to_node,
                    "component_type": s.component_type,
                    "loss_db": s.loss_db,
                    "output_power_dbm": s.output_power_dbm,
                    "fiber_length_m": s.fiber_length_m,
                }
                for s in worst.steps
            ],
        }

    return {
        "olt_launch_power_dbm": config.olt_launch_power_dbm,
        "optical_budget_class": config.optical_budget_class,
        "optical_budget_db": OPTICAL_BUDGET_DB.get(config.optical_budget_class),
        "engineering_margin_db": config.optical_engineering_margin_db,
        "splice_loss_db_per_splice": config.optical_splice_loss_db,
        "connector_loss_db_per_connector": config.optical_connector_loss_db,
        "overview": overview,
        "loss_totals": loss_totals,
        "fdt_summaries": fdt_summaries,
        "fdt_worst_paths": fdt_worst_paths,
    }


# ── Validation results output layer ─────────────────────────────────────────
# Additive, same pattern as the optical output layers above: reads findings
# PerformanceLogger already classified from its existing log()/error() calls
# (see PerformanceLogger._record_finding) — no validate_*/repair function is
# touched, and nothing about what gets checked or how changes.

def populate_validation_layer(layer: 'QgsVectorLayer', logger: 'PerformanceLogger') -> None:
    """Write every finding PerformanceLogger recorded this run into the
    Validation_Results table."""
    features = []
    for finding in logger.get_findings():
        feat = QgsFeature(layer.fields())
        feat.setAttributes([finding["severity"], finding["category"], finding["message"]])
        features.append(feat)
    if features:
        layer.dataProvider().addFeatures(features)
    logger.log(f"[VALIDATION] {len(features)} finding(s) written to Validation_Results.")
