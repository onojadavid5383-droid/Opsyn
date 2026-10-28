# ============================================================
# OPSYN FTTX DESIGNER — DED REPORT GENERATOR
# app/modules/fttx_designer/ded_report.py
#
# Web port of the standalone script's ded_report_generator.py. A read-only
# reporting layer over one completed FttxDesignRun's PERSISTED output
# (FttxDesignRunOutput.output_layers/boq_rows/boq_fdt_rows/
# optical_loss_summary/project_identity — see models.py). It never
# re-derives, re-validates, re-routes, or otherwise recomputes any design
# decision; every fact in the generated report traces back to a field
# already written by the engine pipeline (pipeline.run_fttx_design()).
#
# Scope, identical to the source: Pickup -> Feeder -> Closure -> FDT -> FAT.
# Drop cables and FAT-to-customer/homepass connectivity are deliberately out
# of scope for the main report (no drop-cable rows, no per-FAT customer
# counts, no homepass listing, no drop cables on the maps).
#
# generate_ded_report() produces TWO files, not one — same split as source:
#   1. The .docx itself — narrative, tables, maps. No warnings/errors, no
#      FDT boundary-crossing detail.
#   2. A plain-text "<name>_Warnings.txt" alongside it — every WARNING/
#      ERROR the design engine logged (Validation_Results output layer)
#      PLUS every FAT that crossed an FDT boundary to form its current FDT
#      group (allocation_type != "native"). See write_warnings_file().
#
# What changed from the source, and why
# --------------------------------------
# B1 (layer reader): the source read live QgsVectorLayer objects out of a
# QgsProject. There is no QGIS project on a backend worker — the engine's
# geojson_io.layer_to_geojson() already serialized every output layer to a
# WGS84 GeoJSON FeatureCollection at the end of the Celery task
# (app/tasks/fttx_design_run.py), stored verbatim in
# FttxDesignRunOutput.output_layers. read_design_layers() below reads THAT
# instead: same field names (QGIS field names -> GeoJSON Feature.properties
# keys, unchanged one-to-one — see pipeline.py's _OUTPUT_LAYER_SCHEMAS),
# same shape (Dict[str, List[Dict]]), just a different source. B2
# (relationship builder) and B3 (narrative generators) are PURE PYTHON in
# the source already — verbatim here, zero changes, since they only ever
# operated on plain dicts.
#
# B4 (maps): the source built one throwaway QgsLayout per map (basemap +
# categorized renderer + scoped legend + scale bar), which has no
# server-side equivalent — QGIS's layout engine only exists inside a QGIS
# process. Rebuilt on geopandas + contextily + matplotlib: GeoDataFrames
# built directly from the stored GeoJSON, reprojected to Web Mercator
# (EPSG:3857) to align with contextily's OSM tile fetch, categorized
# per-group coloring reproduced by looping unique field values and plotting
# each as its own colored subset (mirrors QgsCategorizedSymbolRenderer's
# effect without needing that class), and a manually-built legend (mirrors
# the source's scoped-legend fix — only this map's own hub/leaf/cable
# values are listed, never anything else). Same three stages, same
# hub/leaf/cable field wiring, same "frame every map to the whole project's
# extent" behavior (MAP_STAGES / _project_wide_extent's replacement below)
# — see build_report_maps().
#
# contextily.add_basemap() fetches real OSM tiles over the network at
# generation time — this is a real, accepted cost of matching the source's
# basemap behavior (see the design decision recorded when this module was
# built). A tile-fetch failure degrades to "map without a basemap" rather
# than losing the whole map or the whole report — a deliberately FINER
# fault-tolerance grain than the source's per-map all-or-nothing, since a
# flaky tile server is the single most likely failure point here and the
# categorized markers/lines/legend are still fully correct without it.
#
# B5 (docx writer) and the warnings file are pure python-docx / pure Python
# in the source already — verbatim here (signatures adjusted to take
# `output_layers` instead of a QgsProject where maps are generated).
# ============================================================

from __future__ import annotations

import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    from docx import Document
    from docx.shared import Inches, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    _HAVE_DOCX = True
except ImportError:
    _HAVE_DOCX = False

try:
    import matplotlib
    matplotlib.use("Agg")  # headless — no display server on a backend worker
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    import geopandas as gpd
    import contextily
    _HAVE_MAPPING = True
except ImportError:
    _HAVE_MAPPING = False


# =============================================================================
# B1 — LAYER READER
# =============================================================================

# Every output-layer key the engine pipeline can produce (pipeline.py's
# _OUTPUT_LAYER_SCHEMAS keys, plus 'validation_results' which is merged in
# separately — see pipeline.run_fttx_design()). A missing key just means an
# older/degraded run; the corresponding report section says so rather than
# silently omitting or inventing data.
_EXPECTED_LAYER_KEYS: List[str] = [
    "fdt", "fat", "b2b", "b2c", "boq", "closure", "pole_output",
    "pickup_point", "feeder", "closure_cable", "boq_fdt", "validation_results",
]


def read_design_layers(output_layers: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    """Every known output layer's rows, as plain attribute dicts.

    `output_layers` is FttxDesignRunOutput.output_layers exactly as stored:
    {layer_key: GeoJSON FeatureCollection}. Each Feature's `properties` dict
    IS the attribute row — the same field names the QGIS layer carried,
    unchanged (see geojson_io.layer_to_geojson()). Geometry is dropped here;
    B2/B3 never need it, only build_report_maps() reads geometry, straight
    from `output_layers` itself, not through this function.

    A missing layer key yields an empty list, never a KeyError — callers
    combine this with `layer_is_present()` when the distinction between
    "empty" and "absent" matters (see check_report_data_integrity()).
    """
    data: Dict[str, List[Dict[str, Any]]] = {}
    source = output_layers or {}
    for key in _EXPECTED_LAYER_KEYS:
        fc = source.get(key)
        features = (fc or {}).get("features", []) if fc else []
        data[key] = [f.get("properties") or {} for f in features]
    return data


def layer_is_present(output_layers: Optional[Dict[str, Dict[str, Any]]], key: str) -> bool:
    return key in (output_layers or {})


def read_optical_loss_summary(optical_summary: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """FttxDesignRunOutput.optical_loss_summary — already a native dict via
    JSONB, unlike the source's project-custom-property string that needed
    json.loads(). Returns None as-is when optical tracing was disabled or
    unavailable for this run — same "not available" contract as the source."""
    return optical_summary or None


def read_project_identity(project_identity: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """FttxDesignRunOutput.project_identity — same passthrough as
    read_optical_loss_summary(); see PipelineResult.project_identity's
    docstring in pipeline.py for why this replaces the source's
    project-custom-property read."""
    return project_identity or None


# =============================================================================
# B2 — RELATIONSHIP BUILDER (pure Python — verbatim from the source)
# =============================================================================

def fats_by_fdt(fat_rows: List[Dict]) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = defaultdict(list)
    for row in fat_rows:
        out[row.get('parent_fdt') or ''].append(row)
    return dict(out)


def fats_by_street(fat_rows: List[Dict]) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = defaultdict(list)
    for row in fat_rows:
        out[row.get('road_name') or 'UNASSIGNED'].append(row)
    return dict(out)


def street_counts(fat_rows: List[Dict]) -> List[Tuple[str, int]]:
    """[(street, count), ...] sorted by descending count, then street name,
    from the explicit road_name field already on every FAT row (no
    proximity inference)."""
    counts: Dict[str, int] = defaultdict(int)
    for row in fat_rows:
        counts[row.get('road_name') or 'UNASSIGNED'] += 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def fdts_by_closure(fdt_rows: List[Dict]) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = defaultdict(list)
    for row in fdt_rows:
        closure = row.get('closure_name') or ''
        if closure:
            out[closure].append(row)
    return dict(out)


def customers_by_fat(b2c_rows: List[Dict]) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = defaultdict(list)
    for row in b2c_rows:
        out[row.get('fat_name') or ''].append(row)
    return dict(out)


def structures_by_fat_group(fat_rows: List[Dict]) -> Tuple[Dict[str, List[str]], List[str]]:
    """(structure_name -> [FAT names mounted there], [FAT names with no
    recorded structure]) — never merges FATs onto a structure by coordinate
    proximity, only by the explicit structure_name field."""
    by_structure: Dict[str, List[str]] = defaultdict(list)
    unmounted: List[str] = []
    for row in fat_rows:
        structure = row.get('structure_name') or ''
        name = row.get('Name') or ''
        if structure:
            by_structure[structure].append(name)
        else:
            unmounted.append(name)
    return dict(by_structure), unmounted


def build_fdt_boundary_crossings(fat_rows: List[Dict], fdt_rows: List[Dict]) -> List[Dict[str, Any]]:
    """Every FAT whose `allocation_type` is not "native" — i.e. it was
    borrowed or absorbed into an FDT group other than its own road's — with
    the specific boundary it crossed to get there. Grounded entirely in
    fields the engine already persists (`allocation_type`, `road_name`,
    `parent_fdt`, `network_dist_to_fdt`) — never re-derived. Deliberately
    does NOT use physical_fdt/logical_fdt — both are overwritten to the
    FAT's current FDT every time the pipeline's own
    _apply_fat_traceability() reruns, so by the time a design finishes they
    no longer distinguish "original" from "current"."""
    fdt_street_by_name = {r.get('Name'): (r.get('road_name') or 'UNASSIGNED') for r in fdt_rows}
    crossings: List[Dict[str, Any]] = []
    for row in fat_rows:
        allocation_type = row.get('allocation_type') or 'native'
        if allocation_type == 'native':
            continue
        fat_street = row.get('road_name') or 'UNASSIGNED'
        fdt_name = row.get('parent_fdt') or ''
        fdt_street = fdt_street_by_name.get(fdt_name, 'UNKNOWN')
        crossings.append({
            "fat": row.get('Name', ''),
            "allocation_type": allocation_type,
            "fat_street": fat_street,
            "fdt": fdt_name,
            "fdt_street": fdt_street,
            "crosses_street_boundary": fat_street != fdt_street,
            "network_dist_to_fdt_m": row.get('network_dist_to_fdt'),
        })
    return crossings


def build_project_overview(data: Dict[str, List[Dict]]) -> Dict[str, Any]:
    """Aggregate project-level counts. Prefers the engine's own BOQ
    PROJECT-level summary row where available (read existing
    validation/BOQ results, don't recompute them); falls back to counting
    rows directly when BOQ is unavailable."""
    boq_project = next(
        (r for r in data.get('boq', []) if r.get('level_type') == 'PROJECT'), {}
    )
    fat_rows = data.get('fat', [])
    fdt_rows = data.get('fdt', [])
    streets = {row.get('road_name') or 'UNASSIGNED' for row in fat_rows}
    closures_serving = {row.get('closure_name') for row in fdt_rows if row.get('closure_name')}
    pon_counts = {row.get('pon_count') for row in fdt_rows if row.get('pon_count')}
    max_pon = max(pon_counts) if pon_counts else 1
    architecture = f"{max_pon}-PON cascading architecture ({'Dual' if max_pon >= 2 else 'Single'}-PON)"

    return {
        "total_streets": len(streets),
        "total_zones": len(closures_serving),
        "total_homepass": boq_project.get('total_homepass') or len({r.get('customer_id') for r in data.get('b2c', [])}),
        "total_poles": boq_project.get('total_poles'),
        "total_fat": boq_project.get('total_fat') or len(fat_rows),
        "total_fdt": boq_project.get('total_fdt') or len(fdt_rows),
        "total_closures": boq_project.get('total_closures') or len(data.get('closure', [])),
        "total_cable_length_m": boq_project.get('total_standard_length'),
        "feeder_cable_length_m": boq_project.get('feeder_cable_length_m'),
        "feeder_cable_count": boq_project.get('feeder_cable_count'),
        "closure_fdt_cable_length_m": boq_project.get('closure_fdt_cable_length_m'),
        "closure_fdt_cable_count": boq_project.get('closure_fdt_cable_count'),
        "architecture": architecture,
        "pon_count": max_pon,
    }


# =============================================================================
# DATA INTEGRITY CHECK — derived purely from explicit fields (verbatim)
# =============================================================================

def check_report_data_integrity(data: Dict[str, List[Dict]]) -> List[Dict[str, str]]:
    """Findings about the DESIGN DATA itself (missing/duplicate/dangling
    references) — distinct from the engine's own Validation_Results (which
    reports what the design ENGINE flagged during generation). Never
    fabricates a relationship; only reports what's missing or inconsistent."""
    findings: List[Dict[str, str]] = []
    fat_rows = data.get('fat', [])
    fdt_rows = data.get('fdt', [])
    fdt_names = {r.get('Name') for r in fdt_rows}
    fat_names = {r.get('Name') for r in fat_rows}

    seen: set = set()
    for row in fat_rows:
        name = row.get('Name')
        if name in seen:
            findings.append({"severity": "ERROR", "category": "DUPLICATE_ID",
                              "message": f"Duplicate FAT id: {name}"})
        seen.add(name)
        parent = row.get('parent_fdt')
        if not parent:
            findings.append({"severity": "WARNING", "category": "ORPHAN_FAT",
                              "message": f"{name} has no parent FDT recorded."})
        elif parent not in fdt_names:
            findings.append({"severity": "ERROR", "category": "INVALID_REFERENCE",
                              "message": f"{name} references FDT '{parent}', which does not exist."})
        if not row.get('road_name') or row.get('road_name') == 'UNASSIGNED':
            findings.append({"severity": "WARNING", "category": "FAT_NO_STREET",
                              "message": f"{name} has no assigned street."})
        if not row.get('structure_name'):
            findings.append({"severity": "WARNING", "category": "FAT_NO_STRUCTURE",
                              "message": f"{name} has no recorded mounting structure "
                                         f"(older design run, or genuinely unsnapped)."})

    seen = set()
    for row in fdt_rows:
        name = row.get('Name')
        if name in seen:
            findings.append({"severity": "ERROR", "category": "DUPLICATE_ID",
                              "message": f"Duplicate FDT id: {name}"})
        seen.add(name)
        if not row.get('closure_name'):
            findings.append({"severity": "WARNING", "category": "FDT_NO_CLOSURE",
                              "message": f"{name} has no parent closure recorded."})

    fat_names_with_customers = {r.get('fat_name') for r in data.get('b2c', [])}
    for name in sorted(fat_names - fat_names_with_customers):
        findings.append({"severity": "WARNING", "category": "FAT_NO_CUSTOMERS",
                          "message": f"{name} has no homepass/customer connections recorded."})

    return findings


# =============================================================================
# B3 — NARRATIVE GENERATORS (pure Python — verbatim from the source)
# =============================================================================

_NUMBER_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve",
}


def _spell(n: int) -> str:
    return _NUMBER_WORDS.get(n, str(n))


def _plural(n: int, word: str) -> str:
    return word if n == 1 else word + "s"


def _join_english(parts: List[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]}, while {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def narrate_fdt_streets(fdt_name: str, fat_rows_for_fdt: List[Dict]) -> str:
    """"FDT-001 feeds a total of eight FATs. Five FATs are on Street A,
    while three are on Street B." Entirely derived from
    FAT.parent_fdt/road_name — no invented relationship, no hardcoded
    street name or count."""
    total = len(fat_rows_for_fdt)
    if total == 0:
        return f"{fdt_name} currently feeds no FATs."
    counts = street_counts(fat_rows_for_fdt)
    if len(counts) == 1:
        street, _ = counts[0]
        return (f"{fdt_name} feeds a total of {_spell(total)} ({total}) "
                f"{_plural(total, 'FAT')}, all deployed along {street}.")
    parts = [f"{_spell(c)} ({c}) {_plural(c, 'FAT')} on {s}" for s, c in counts]
    return (f"{fdt_name} feeds a total of {_spell(total)} ({total}) FATs "
            f"distributed across {_spell(len(counts))} streets: "
            f"{_join_english(parts)}.")


def narrate_pole_mounting(fat_rows: List[Dict]) -> str:
    """"FAT-001 is mounted on Pole-001... Pole-010 accommodates FAT-004 and
    FAT-005." Groups by the explicit structure_name field — never assumes
    one FAT per structure."""
    by_structure, unmounted = structures_by_fat_group(fat_rows)
    parts = []
    for structure, fat_names in by_structure.items():
        if len(fat_names) == 1:
            parts.append(f"{fat_names[0]} is mounted on {structure}")
        else:
            parts.append(f"{structure} accommodates {', '.join(fat_names)}")
    sentence = "; ".join(parts) + "." if parts else ""
    note = (f" {len(unmounted)} FAT(s) — {', '.join(unmounted)} — have no "
            f"recorded structure assignment for this run." if unmounted else "")
    return (sentence + note).strip() or "No FAT/structure data available for this run."


def narrate_closure(closure_row: Dict, fdt_rows_for_closure: List[Dict]) -> str:
    if not fdt_rows_for_closure:
        return (f"{closure_row.get('Name', 'Closure')} is recorded in the design "
                f"but no FDTs are currently linked to it.")
    fdt_names = [r.get('Name', '') for r in fdt_rows_for_closure]
    streets = sorted({r.get('road_name') or 'UNASSIGNED' for r in fdt_rows_for_closure})
    return (f"{closure_row.get('Name', 'Closure')} provides distribution connectivity "
            f"to {_join_english(fdt_names) if len(fdt_names) <= 2 else ', '.join(fdt_names[:-1]) + f', and {fdt_names[-1]}'}. "
            f"The connected FDT{_plural(len(fdt_names), '')} "
            f"{'is' if len(fdt_names) == 1 else 'are'} distributed across "
            f"{_join_english(streets) if len(streets) <= 2 else ', '.join(streets[:-1]) + f', and {streets[-1]}'}.")


def narrate_street(street: str, fat_rows_for_street: List[Dict], boq_street_row: Optional[Dict]) -> str:
    if not fat_rows_for_street:
        return f"{street} has no FATs recorded in this design."
    fdt_names = sorted({r.get('parent_fdt') or 'UNASSIGNED' for r in fat_rows_for_street})
    fat_names = [r.get('Name', '') for r in fat_rows_for_street]
    n = len(fat_names)
    served_by = (f"served by {fdt_names[0]}" if len(fdt_names) == 1
                 else f"served by {len(fdt_names)} FDTs ({', '.join(fdt_names)})")
    homepass_txt = ""
    if boq_street_row is not None:
        homepass_txt = f" and collectively serve {boq_street_row.get('total_homepass', 0)} homepasses"
    return (f"{street} contains {_spell(n)} ({n}) {_plural(n, 'FAT')} {served_by}. "
            f"The FATs are {', '.join(fat_names)}{homepass_txt}.")


# ── Optical power budget / loss summary — pure formatting, verbatim ────────

_OPTICAL_COMPONENT_LOSS_TYPE = {
    "FDT_SPLITTER": "Splitter",
    "FAT_SPLITTER": "Splitter",
    "FIBER": "Fiber / Distance",
}


def narrate_optical_overview(summary: Dict[str, Any]) -> str:
    overview = summary.get("overview") or {}
    total = overview.get("total_customers") or 0
    if not total:
        return "No optical customer paths were computed for this run."

    budget_class = summary.get("optical_budget_class", "")
    budget_db = summary.get("optical_budget_db")
    launch = summary.get("olt_launch_power_dbm")
    if budget_db is not None and launch is not None:
        intro = (f"Optical power budget analysis was performed against a "
                 f"{budget_class} ({budget_db:.1f} dB) budget class, with an "
                 f"OLT launch power of {launch:.2f} dBm.")
    else:
        intro = f"Optical power budget analysis was performed against a {budget_class} budget class."

    passed = overview.get("passed_customers") or 0
    marginal = overview.get("marginal_customers") or 0
    failed = overview.get("failed_customers") or 0
    invalid = overview.get("invalid_customers") or 0
    counts = (f"Of {total} customer path{'s' if total != 1 else ''} analyzed, "
              f"{passed} passed, {marginal} were marginal, {failed} failed the "
              f"budget, and {invalid} could not be evaluated (unsupported "
              f"topology or missing route data).")

    worst_power = overview.get("worst_power_dbm")
    worst_margin = overview.get("worst_margin_db")
    worst_txt = ""
    if worst_power is not None and worst_margin is not None:
        worst_txt = (f" The worst-case customer showed an expected received "
                     f"power of {worst_power:.2f} dBm, leaving "
                     f"{worst_margin:.2f} dB of design margin.")

    return f"{intro} {counts}{worst_txt}"


def build_loss_type_rows(summary: Dict[str, Any]) -> List[List[Any]]:
    totals = summary.get("loss_totals") or {}
    n = totals.get("path_count") or 0

    def _avg(total: float) -> float:
        return (total / n) if n else 0.0

    splitter_total = totals.get("splitter_loss_db_total", 0.0) or 0.0
    fiber_total = totals.get("fiber_loss_db_total", 0.0) or 0.0
    splice_total = totals.get("splice_loss_db_total", 0.0) or 0.0
    connector_total = totals.get("connector_loss_db_total", 0.0) or 0.0

    return [
        ["Splitter Loss", f"{splitter_total:.2f} dB total",
         f"{_avg(splitter_total):.2f} dB / customer path"],
        ["Fiber / Distance Loss", f"{fiber_total:.2f} dB total",
         f"{_avg(fiber_total):.2f} dB / customer path"],
        ["Splice Loss",
         f"{splice_total:.2f} dB total ({totals.get('splice_count_total', 0)} splice(s))",
         f"{_avg(splice_total):.2f} dB / customer path"],
        ["Connector Loss",
         f"{connector_total:.2f} dB total ({totals.get('connector_count_total', 0)} connector(s))",
         f"{_avg(connector_total):.2f} dB / customer path"],
        ["Engineering Margin",
         f"{summary.get('engineering_margin_db', 0.0):.2f} dB (fixed allowance, per customer path)", ""],
    ]


def build_fdt_worst_path_rows(worst_path: Dict[str, Any]) -> List[List[Any]]:
    rows: List[List[Any]] = []
    for step in worst_path.get("steps", []):
        loss_type = _OPTICAL_COMPONENT_LOSS_TYPE.get(
            step.get("component_type"), step.get("component_type", "")
        )
        point = f"{step.get('from_node')} → {step.get('to_node')}"
        length = step.get("fiber_length_m") or 0.0
        length_txt = f"{length:.1f} m" if length else ""
        rows.append([
            point, loss_type, f"{step.get('loss_db', 0.0):.3f} dB", length_txt,
            f"{step.get('output_power_dbm', 0.0):.2f} dBm",
        ])

    rows.append([
        "(aggregate — per fibre segment)", "Splice Loss",
        f"{worst_path.get('splice_loss_db', 0.0):.3f} dB "
        f"({worst_path.get('splice_count', 0)} splice(s))", "", "",
    ])
    rows.append([
        "(aggregate — per fibre segment)", "Connector Loss",
        f"{worst_path.get('connector_loss_db', 0.0):.3f} dB "
        f"({worst_path.get('connector_count', 0)} connector(s))", "", "",
    ])
    rows.append([
        "(fixed design allowance)", "Engineering Margin",
        f"{worst_path.get('engineering_margin_db', 0.0):.2f} dB", "", "",
    ])
    rows.append([
        f"Customer_{worst_path.get('customer_id')} (final)", "Expected Power", "", "",
        f"{worst_path.get('expected_power_dbm', 0.0):.2f} dBm ({worst_path.get('status', '')})",
    ])
    return rows


# =============================================================================
# B4 — MAPS (geopandas + contextily + matplotlib; every map is
# independently fault-tolerant, same guarantee as the source)
# =============================================================================

# Single source of truth for the report's map set — same 3 stages, same
# hub/leaf/cable wiring as the source's MAP_STAGES. The hub owns each
# group's identity; the leaf and cable reference that identity in their own
# field — coloring every layer from the SAME per-group color map is what
# makes a leaf/cable's color match its hub's.
#
# Each point spec is (layer_key, field, marker, size); layer_key indexes
# into `output_layers` (not a QGIS layer name — see read_design_layers()).
# marker is a matplotlib marker code ("D" diamond, "o" circle) — hub and
# leaf are deliberately different shapes so the two ends of a link are
# visually distinct even where colors repeat.
MAP_STAGES: List[Dict[str, Any]] = [
    {
        "key": "pickup_to_closure", "title": "Pickup Point to Closure",
        "hub": ("pickup_point", "name", "D", 90),
        "leaf": ("closure", "pickup_name", "o", 55),
        "cable": ("feeder", "start_device"),
    },
    {
        "key": "closure_to_fdt", "title": "Closure to FDT",
        "hub": ("closure", "Name", "D", 90),
        "leaf": ("fdt", "closure_name", "o", 55),
        "cable": ("closure_cable", "closure_name"),
    },
    {
        "key": "fdt_to_fat", "title": "FDT to FAT",
        "hub": ("fdt", "Name", "D", 90),
        "leaf": ("fat", "parent_fdt", "o", 55),
        "cable": ("b2b", "fdt_id"),
    },
]
MAP_TITLES: Dict[str, str] = {stage["key"]: stage["title"] for stage in MAP_STAGES}

# Point-geometry layer keys that count as "the project" for framing every
# map to the same full-project extent (mirrors the source's
# _project_wide_extent(), which unioned every vector layer in the QGIS
# project). Cable/line layers are included too, same as the source.
_ALL_SPATIAL_LAYER_KEYS: List[str] = [
    "fdt", "fat", "b2b", "b2c", "closure", "pole_output",
    "pickup_point", "feeder", "closure_cable",
]

# 20 hand-picked, pairwise-distinct colors before falling back to
# golden-ratio HSV spacing for any project with more groups than that.
_CATEGORY_PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#9acd32", "#fabebe", "#008080",
    "#e6beff", "#9a6324", "#800000", "#aaffc3", "#808000",
    "#ffb37e", "#000075", "#a9a9a9", "#d2b48c", "#556b2f",
]


def _category_color(index: int) -> str:
    if index < len(_CATEGORY_PALETTE):
        return _CATEGORY_PALETTE[index]
    import colorsys
    hue = (index * 0.6180339887) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.85)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def _unique_property_values(features: List[Dict[str, Any]], field: str) -> List[str]:
    values = set()
    for feat in features:
        v = (feat.get("properties") or {}).get(field)
        if v not in (None, ''):
            values.add(str(v))
    return sorted(values)


def _build_group_color_map(feature_field_pairs: List[Tuple[Optional[List[Dict]], str]]) -> Dict[str, str]:
    """One color per unique group value, stable across every layer in one
    map. The FIRST pair (the hub) sets the canonical order — later pairs
    only contribute colors for stray values the hub didn't have."""
    ordered_values: List[str] = []
    seen = set()
    for features, field in feature_field_pairs:
        if not features:
            continue
        for v in _unique_property_values(features, field):
            if v not in seen:
                seen.add(v)
                ordered_values.append(v)
    return {v: _category_color(i) for i, v in enumerate(ordered_values)}


def _features_to_gdf(features: List[Dict[str, Any]]):
    """GeoJSON Feature list -> GeoDataFrame in WGS84, reprojected to Web
    Mercator (EPSG:3857) so it aligns with contextily's OSM tiles. Features
    with null/missing geometry (e.g. a stray BOQ-style row that slipped in)
    are dropped rather than raising."""
    usable = [f for f in features if f.get("geometry")]
    if not usable:
        return None
    gdf = gpd.GeoDataFrame.from_features(usable, crs="EPSG:4326")
    return gdf.to_crs(epsg=3857)


def _combined_bounds(gdfs: List[Any]) -> Optional[Tuple[float, float, float, float]]:
    """Union bounding box (minx, miny, maxx, maxy) across every non-empty
    GeoDataFrame — mirrors the source's _combined_extent(). Skips empty
    frames individually rather than seeding from the first one, so an
    empty layer never silently drops the rest of the project's extent."""
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    have = False
    for gdf in gdfs:
        if gdf is None or gdf.empty:
            continue
        b = gdf.total_bounds  # (minx, miny, maxx, maxy)
        xmin, ymin = min(xmin, b[0]), min(ymin, b[1])
        xmax, ymax = max(xmax, b[2]), max(ymax, b[3])
        have = True
    return (xmin, ymin, xmax, ymax) if have else None


def _plot_categorized(ax, gdf, field: str, color_map: Dict[str, str],
                      marker: Optional[str], size: Optional[float],
                      is_line: bool, legend_handles: Dict[str, Any]) -> None:
    """Plot one layer's features, one color per unique `field` value —
    reproduces QgsCategorizedSymbolRenderer's per-category coloring without
    that class. Adds one legend handle per NEW value seen across the whole
    map (legend_handles is shared/mutated across hub+leaf+cable calls so a
    value's legend entry is created once, from whichever layer draws it
    first, per the source's scoped-legend intent)."""
    if gdf is None or gdf.empty or field not in gdf.columns:
        return
    for value, sub in gdf.groupby(gdf[field].astype(str)):
        color = color_map.get(value)
        if color is None:
            continue
        if is_line:
            sub.plot(ax=ax, color=color, linewidth=1.4, zorder=2)
            if value not in legend_handles:
                legend_handles[value] = Line2D([0], [0], color=color, linewidth=1.4, label=value)
        else:
            sub.plot(ax=ax, color=color, marker=marker or 'o', markersize=size or 40,
                     edgecolor='#333333', linewidth=0.4, zorder=3)
            if value not in legend_handles:
                legend_handles[value] = Line2D(
                    [0], [0], marker=marker or 'o', color='w', markerfacecolor=color,
                    markeredgecolor='#333333', markersize=8, label=value,
                )


def _add_basemap_safely(ax) -> bool:
    """contextily.add_basemap() fetches real tiles over the network — the
    one genuinely unreliable step in this whole function. Failure here
    degrades to "map without a street basemap", never to "no map at all" —
    see the module docstring's fault-tolerance note.

    Uses Esri's public World_Street_Map, NOT contextily's default
    OpenStreetMap.Mapnik tile source. That default was tried first during
    this module's development and confirmed broken for this exact use
    case: OSM's tile.openstreetmap.org enforces a strict, explicitly
    anti-bulk/anti-automated usage policy
    (https://operations.osmfoundation.org/policies/tiles/), and every tile
    request from here came back as an HTTP 200 with a *rendered* "403
    Access Blocked — App is not following the tile usage policy" placeholder
    image tiled across the whole map — which contextily/matplotlib happily
    plots as if it were real basemap tiles, since no exception is raised.
    That is a silent-failure mode strictly worse than no basemap at all: it
    looks like a real street map at a glance. Esri's World_Street_Map has no
    such restriction for this kind of server-side report-generation use and
    requires no API key."""
    try:
        contextily.add_basemap(ax, source=contextily.providers.Esri.WorldStreetMap, zoom='auto')
        return True
    except Exception:
        return False


def _export_stage_map(output_layers: Dict[str, Dict[str, Any]], stage: Dict[str, Any],
                      extent_bounds: Optional[Tuple[float, float, float, float]],
                      out_path: str) -> bool:
    """One stage's map: hub + leaf + cable, categorized coloring, legend,
    basemap, framed to `extent_bounds` (the whole project's extent, not
    just this stage's own layers). Returns False (never raises) on any
    failure that would otherwise produce a broken/empty map."""
    hub_key, hub_field, hub_marker, hub_size = stage["hub"]
    leaf_key, leaf_field, leaf_marker, leaf_size = stage["leaf"]
    cable_key, cable_field = stage["cable"]

    hub_fc = output_layers.get(hub_key) or {}
    leaf_fc = output_layers.get(leaf_key) or {}
    cable_fc = output_layers.get(cable_key) or {}
    hub_features = hub_fc.get("features", [])
    leaf_features = leaf_fc.get("features", [])
    cable_features = cable_fc.get("features", [])

    if not hub_features or not leaf_features:
        return False

    color_map = _build_group_color_map([
        (hub_features, hub_field), (leaf_features, leaf_field),
        (cable_features, cable_field) if cable_features else (None, ""),
    ])
    if not color_map:
        return False

    try:
        hub_gdf = _features_to_gdf(hub_features)
        leaf_gdf = _features_to_gdf(leaf_features)
        cable_gdf = _features_to_gdf(cable_features) if cable_features else None
        if hub_gdf is None or leaf_gdf is None:
            return False

        fig, ax = plt.subplots(figsize=(11.69, 8.27), dpi=150)  # A4 landscape @ 150dpi

        legend_handles: Dict[str, Any] = {}
        if cable_gdf is not None:
            _plot_categorized(ax, cable_gdf, cable_field, color_map, None, None, True, legend_handles)
        # Leaf drawn before hub so the hub stays visually on top (mirrors
        # the source's draw-order comment: hub markers stay visible over
        # leaf points and cable lines).
        _plot_categorized(ax, leaf_gdf, leaf_field, color_map, leaf_marker, leaf_size, False, legend_handles)
        _plot_categorized(ax, hub_gdf, hub_field, color_map, hub_marker, hub_size, False, legend_handles)

        if extent_bounds is not None:
            xmin, ymin, xmax, ymax = extent_bounds
            pad_x = (xmax - xmin) * 0.1 or 1000.0
            pad_y = (ymax - ymin) * 0.1 or 1000.0
            ax.set_xlim(xmin - pad_x, xmax + pad_x)
            ax.set_ylim(ymin - pad_y, ymax + pad_y)

        _add_basemap_safely(ax)

        ax.set_title(stage["title"], fontsize=14, fontweight='bold')
        ax.set_axis_off()

        if legend_handles:
            ax.legend(
                handles=list(legend_handles.values()), title="Legend",
                loc='center left', bbox_to_anchor=(1.01, 0.5),
                fontsize=6, title_fontsize=7, frameon=True,
            )

        fig.tight_layout()
        fig.savefig(out_path, bbox_inches='tight')
        plt.close(fig)
        return os.path.exists(out_path)
    except Exception:
        try:
            plt.close('all')
        except Exception:
            pass
        return False


def build_report_maps(output_layers: Optional[Dict[str, Dict[str, Any]]], tmp_dir: str) -> Dict[str, str]:
    """One map per stage of the Pickup -> Closure -> FDT -> FAT chain (see
    MAP_STAGES), each with an OSM basemap, categorized coloring that
    matches a leaf/cable's color to its hub's, and a legend scoped to
    exactly that map's own layers. Every map is framed to the SAME
    full-project extent (every spatial output layer this run produced) so
    nothing is ever cut off and every map is consistently centered.
    Returns {map_key: png_path} for whichever succeeded — never raises."""
    maps: Dict[str, str] = {}
    if not _HAVE_MAPPING or not output_layers:
        return maps

    extent_gdfs = []
    for key in _ALL_SPATIAL_LAYER_KEYS:
        fc = output_layers.get(key)
        if fc:
            gdf = _features_to_gdf(fc.get("features", []))
            if gdf is not None:
                extent_gdfs.append(gdf)
    extent_bounds = _combined_bounds(extent_gdfs)

    for stage in MAP_STAGES:
        path = os.path.join(tmp_dir, f"map_{stage['key']}.png")
        if _export_stage_map(output_layers, stage, extent_bounds, path):
            maps[stage["key"]] = path

    return maps


# =============================================================================
# B5 — WORD DOCUMENT WRITER (pure python-docx — verbatim from the source)
# =============================================================================

def _add_page_number_field(paragraph) -> None:
    """python-docx has no native page-number field; insert the standard
    PAGE field-code run (Word computes the actual number on open)."""
    run = paragraph.add_run()
    fld_begin = OxmlElement('w:fldChar')
    fld_begin.set(qn('w:fldCharType'), 'begin')
    instr = OxmlElement('w:instrText')
    instr.set(qn('xml:space'), 'preserve')
    instr.text = "PAGE"
    fld_sep = OxmlElement('w:fldChar')
    fld_sep.set(qn('w:fldCharType'), 'separate')
    fld_end = OxmlElement('w:fldChar')
    fld_end.set(qn('w:fldCharType'), 'end')
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(fld_end)


def _add_toc_field(document) -> None:
    """Insert a TOC field code. Word shows "Right-click and choose Update
    Field" until the user opens the doc — this script cannot compute
    Word's own pagination."""
    paragraph = document.add_paragraph()
    run = paragraph.add_run()
    fld_begin = OxmlElement('w:fldChar')
    fld_begin.set(qn('w:fldCharType'), 'begin')
    instr = OxmlElement('w:instrText')
    instr.set(qn('xml:space'), 'preserve')
    instr.text = 'TOC \\o "1-3" \\h \\z \\u'
    fld_sep = OxmlElement('w:fldChar')
    fld_sep.set(qn('w:fldCharType'), 'separate')
    placeholder = OxmlElement('w:t')
    placeholder.text = "Right-click and choose \"Update Field\" to build the table of contents."
    fld_end = OxmlElement('w:fldChar')
    fld_end.set(qn('w:fldCharType'), 'end')
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(placeholder)
    run._r.append(fld_end)


def _add_table(document, headers: List[str], rows: List[List[Any]]):
    table = document.add_table(rows=1, cols=len(headers))
    table.style = 'Light Grid Accent 1'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = str(h)
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
    for row in rows:
        cells = table.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = "" if val is None else str(val)
    return table


def _setup_footer(document) -> None:
    section = document.sections[0]
    footer = section.footer
    paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.add_run("Page ")
    _add_page_number_field(paragraph)


def _add_cover_page(document, project_name: str) -> None:
    for _ in range(4):
        document.add_paragraph()
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("FTTH DETAILED ENGINEERING DESIGN REPORT")
    run.bold = True
    run.font.size = Pt(26)

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run(project_name)
    run.font.size = Pt(16)

    for _ in range(6):
        document.add_paragraph()

    meta = document.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(f"Report Date: {datetime.now().strftime('%Y-%m-%d')}\n")
    meta.add_run("Revision: v1.0\n")
    meta.add_run("Prepared by: FTTx Designer — Automated DED Report Generator")
    document.add_page_break()


# =============================================================================
# B6 — ENTRY POINT
# =============================================================================

def build_report_data(
    output_layers: Optional[Dict[str, Dict[str, Any]]],
    optical_summary: Optional[Dict[str, Any]] = None,
    project_identity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Read + relate everything the report needs. Pure orchestration of
    B1/B2 — safe to call directly from a test with synthetic
    `output_layers`/`optical_summary`/`project_identity` dicts, no DB or
    QGIS involved at all."""
    data = read_design_layers(output_layers)
    overview = build_project_overview(data)
    integrity_findings = check_report_data_integrity(data)
    return {
        "raw": data,
        "overview": overview,
        "fats_by_fdt": fats_by_fdt(data.get('fat', [])),
        "fdts_by_closure": fdts_by_closure(data.get('fdt', [])),
        "customers_by_fat": customers_by_fat(data.get('b2c', [])),
        "fats_by_street": fats_by_street(data.get('fat', [])),
        "integrity_findings": integrity_findings,
        "boundary_crossings": build_fdt_boundary_crossings(data.get('fat', []), data.get('fdt', [])),
        "optical_summary": read_optical_loss_summary(optical_summary),
        "project_identity": read_project_identity(project_identity),
    }


def _write_report_document(
    report: Dict[str, Any],
    output_layers: Optional[Dict[str, Dict[str, Any]]],
    project_name: str,
    include_maps: bool,
) -> "Document":
    """Build the full .docx Document from an already-assembled `report`
    dict (see build_report_data()). Split out from generate_ded_report() so
    this — the actual document-writing logic, including the hand-rolled
    TOC/page-number field codes — can be exercised directly in a test with
    synthetic report data (pass output_layers=None, include_maps=False)."""
    data = report["raw"]
    overview = report["overview"]

    document = Document()
    _add_cover_page(document, project_name)

    document.add_heading("Table of Contents", level=1)
    _add_toc_field(document)
    document.add_page_break()

    # 1-2. Project Overview
    document.add_heading("Project Overview", level=1)
    document.add_paragraph(
        f"The proposed FTTH deployment covers a total of {overview['total_streets']} "
        f"street(s) across {overview['total_zones']} closure service zone(s), and "
        f"provides fiber connectivity to {overview['total_homepass']} homepass(es). "
        f"The designed network consists of {overview['total_closures']} closure(s), "
        f"{overview['total_fdt']} FDT(s), and {overview['total_fat']} FAT(s). "
        f"The network is implemented using a {overview['architecture']}."
    )
    _add_table(document, ["Infrastructure", "Quantity"], [
        ["Streets", overview['total_streets']],
        ["Homepasses", overview['total_homepass']],
        ["Poles / Structures", overview['total_poles']],
        ["FATs", overview['total_fat']],
        ["FDTs", overview['total_fdt']],
        ["Closures", overview['total_closures']],
        ["Feeder Cable", f"{overview['feeder_cable_length_m'] or 0:.1f} m ({overview['feeder_cable_count'] or 0} run(s))"],
        ["Closure-to-FDT Cable", f"{overview['closure_fdt_cable_length_m'] or 0:.1f} m ({overview['closure_fdt_cable_count'] or 0} run(s))"],
        ["Total Distribution/Drop Cable", f"{overview['total_cable_length_m'] or 0:.1f} m"],
    ])
    document.add_page_break()

    # 3. Network Architecture
    document.add_heading("Network Architecture", level=1)
    document.add_paragraph(
        f"The network utilizes a {overview['architecture']}, with FDTs distributing "
        f"their connected FATs across the configured wing arrangement per the "
        f"cascading splitter topology generated by the design engine."
    )

    if include_maps:
        with tempfile.TemporaryDirectory() as tmp_dir:
            maps = build_report_maps(output_layers, tmp_dir)
            if maps:
                document.add_heading("Project Maps", level=1)
                for key, path in maps.items():
                    document.add_heading(MAP_TITLES.get(key, key), level=2)
                    try:
                        document.add_picture(path, width=Inches(6.5))
                    except Exception:
                        document.add_paragraph(f"[Map '{key}' could not be embedded.]")
            else:
                document.add_paragraph(
                    "No maps could be generated for this run (required layers "
                    "not present, or map rendering dependencies/network access "
                    "unavailable)."
                )
    document.add_page_break()

    # Closure Deployment
    document.add_heading("Closure Deployment", level=1)
    if not data.get('closure'):
        document.add_paragraph("No closure data available for this run.")
    else:
        for closure_row in data['closure']:
            name = closure_row.get('Name', 'Closure')
            document.add_heading(name, level=2)
            fdt_rows = report["fdts_by_closure"].get(name, [])
            document.add_paragraph(narrate_closure(closure_row, fdt_rows))
    document.add_page_break()

    # FDT Deployment
    document.add_heading("FDT Deployment", level=1)
    if not data.get('fdt'):
        document.add_paragraph("No FDT data available for this run.")
    else:
        for fdt_row in data['fdt']:
            name = fdt_row.get('Name', 'FDT')
            document.add_heading(name, level=2)
            fat_rows = report["fats_by_fdt"].get(name, [])
            document.add_paragraph(narrate_fdt_streets(name, fat_rows))
            _add_table(document, ["Field", "Value"], [
                ["Parent Closure", fdt_row.get('closure_name') or "N/A"],
                ["PON Count", fdt_row.get('pon_count')],
                ["Wing A / B / C / D", f"{fdt_row.get('wing_A_count', 0)} / {fdt_row.get('wing_B_count', 0)} / "
                                        f"{fdt_row.get('wing_C_count', 0)} / {fdt_row.get('wing_D_count', 0)}"],
                ["Total FATs", len(fat_rows)],
                ["Total Customers", fdt_row.get('total_customers')],
                ["Mounting Structure", fdt_row.get('structure_name') or "not recorded"],
            ])
    document.add_page_break()

    # FAT Deployment + Pole/Structure narrative
    document.add_heading("FAT Deployment", level=1)
    if not data.get('fat'):
        document.add_paragraph("No FAT data available for this run.")
    else:
        rows = []
        for fat_row in data['fat']:
            rows.append([
                fat_row.get('Name', ''), fat_row.get('parent_fdt'), fat_row.get('road_name'),
                fat_row.get('wing'), fat_row.get('splitter_type'),
                fat_row.get('structure_name') or "not recorded",
            ])
        _add_table(document, ["FAT", "FDT", "Street", "Wing", "Splitter",
                               "Structure"], rows)
    document.add_page_break()

    document.add_heading("Pole / Structure Installation Schedule", level=1)
    for street, fat_rows in report["fats_by_street"].items():
        document.add_heading(street, level=2)
        document.add_paragraph(narrate_pole_mounting(fat_rows))
    document.add_page_break()

    # Street-by-Street Deployment
    document.add_heading("Street-by-Street Deployment", level=1)
    boq_by_street = {r.get('street_name'): r for r in data.get('boq', []) if r.get('level_type') == 'STREET'}
    for street, fat_rows in report["fats_by_street"].items():
        document.add_heading(street, level=2)
        document.add_paragraph(narrate_street(street, fat_rows, boq_by_street.get(street)))
    document.add_page_break()

    # FDT-to-FAT Connectivity Schedule
    document.add_heading("FDT-to-FAT Connectivity Schedule", level=1)
    connectivity_rows = []
    for fat_row in sorted(data.get('fat', []),
                           key=lambda r: (r.get('parent_fdt') or '', r.get('wing') or '', r.get('fat_sequence') or '')):
        connectivity_rows.append([
            fat_row.get('parent_fdt'), fat_row.get('Name'), fat_row.get('road_name'),
            fat_row.get('structure_name') or "not recorded", fat_row.get('wing'),
        ])
    _add_table(document, ["FDT", "FAT", "Street", "Structure", "Wing"], connectivity_rows)
    document.add_page_break()

    # Fiber / Core Allocation — Closure-to-FDT only (honest scope statement)
    document.add_heading("Fiber / Core Allocation", level=1)
    document.add_paragraph(
        "Core allocation is tracked in the design at the Closure-to-FDT trunk level. "
        "FDT-to-FAT and FAT-to-Customer legs are not tracked at individual-core "
        "granularity in the current design output, so no per-core figures are stated "
        "for those legs below."
    )
    core_rows = []
    for c in data.get('closure_cable', []):
        core_rows.append([
            c.get('closure_name'), c.get('end_device'), c.get('name'),
            f"{c.get('core_act')} #{c.get('core_num_act')}" if c.get('core_act') else "",
            f"{c.get('core_red')} #{c.get('core_num_red')}" if c.get('core_red') else "",
        ])
    _add_table(document, ["Closure", "FDT", "Cable", "Active Core", "Redundant Core"], core_rows)
    document.add_page_break()

    # Optical Power Budget Summary
    document.add_heading("Optical Power Budget Summary", level=1)
    optical_summary = report.get("optical_summary")
    if not optical_summary:
        document.add_paragraph(
            "Optical power budget tracing was not available for this run — "
            "it was disabled, the cascade architecture is Legacy (unsupported "
            "for optical tracing), or this project predates the feature."
        )
    else:
        document.add_paragraph(narrate_optical_overview(optical_summary))
        _add_table(document, ["Loss Type", "Total", "Average"], build_loss_type_rows(optical_summary))

        fdt_worst_paths = optical_summary.get("fdt_worst_paths") or {}
        for fdt_id in sorted(fdt_worst_paths.keys()):
            worst_path = fdt_worst_paths[fdt_id]
            document.add_heading(f"{fdt_id} — Worst-Case Path", level=2)
            document.add_paragraph(
                f"Customer_{worst_path.get('customer_id')} on wavelength "
                f"{worst_path.get('wavelength')}nm shows the lowest design margin "
                f"under {fdt_id}: {worst_path.get('available_margin_db', 0.0):.2f} dB "
                f"available ({worst_path.get('status')}). The table below shows "
                f"exactly where loss accumulates along this path."
            )
            _add_table(
                document, ["Point", "Loss Type", "Loss", "Fiber Length", "Cumulative Power"],
                build_fdt_worst_path_rows(worst_path),
            )
    document.add_page_break()

    # Cable Routing — Pickup-to-FAT only
    document.add_heading("Cable Routing", level=1)
    document.add_paragraph(
        "This section covers cable routing from the pickup point through to "
        "the FAT: feeder, closure-to-FDT, and box-to-box (FDT-to-FAT) cables. "
        "Drop (FAT-to-customer) cables are out of scope for this report."
    )
    all_cable_rows = []
    for c in data.get('feeder', []):
        all_cable_rows.append(["Feeder", c.get('name'), c.get('start_device'), c.get('end_device'), c.get('length')])
    for c in data.get('closure_cable', []):
        all_cable_rows.append(["Closure-to-FDT", c.get('name'), c.get('start_device'), c.get('end_device'), c.get('cable_length')])
    for c in data.get('b2b', []):
        all_cable_rows.append(["Box-to-Box", c.get('name'), c.get('start_device'), c.get('end_device'), c.get('cable_length')])
    _add_table(document, ["Cable Type", "Name", "From", "To", "Length (m)"], all_cable_rows)
    document.add_page_break()

    # Material Take-Off (from the existing BOQ layer — never recomputed)
    document.add_heading("Material Take-Off", level=1)
    if not data.get('boq'):
        document.add_paragraph("No BOQ data available for this run.")
    else:
        boq_project_row = next((r for r in data['boq'] if r.get('level_type') == 'PROJECT'), None)
        if boq_project_row:
            _add_table(document, ["Item", "Quantity"],
                       [[k, v] for k, v in boq_project_row.items() if k not in ('level_type', 'street_name')])
    document.add_page_break()

    # Deployment Summary
    document.add_heading("Deployment Summary", level=1)
    fdt_summaries = [narrate_fdt_streets(r.get('Name', ''), report["fats_by_fdt"].get(r.get('Name', ''), []))
                      for r in data.get('fdt', [])]
    document.add_paragraph(
        f"The project requires the installation of {overview['total_fdt']} FDT(s) and "
        f"{overview['total_fat']} FAT(s) across {overview['total_streets']} street(s). "
        + " ".join(fdt_summaries)
    )
    _setup_footer(document)
    return document


def generate_ded_report(
    output_layers: Optional[Dict[str, Dict[str, Any]]],
    output_path: str,
    optical_summary: Optional[Dict[str, Any]] = None,
    project_identity: Optional[Dict[str, Any]] = None,
    project_name: Optional[str] = None,
    include_maps: bool = True,
) -> Dict[str, str]:
    """The single entry point the router/Celery task calls for a completed
    FttxDesignRun.

    `output_layers`/`optical_summary`/`project_identity` are exactly
    FttxDesignRunOutput.output_layers/.optical_loss_summary/
    .project_identity for that run. Builds the report and writes a .docx to
    `output_path`. Warnings/errors and FDT boundary-crossing findings are
    deliberately NOT included in that document — they go to their own
    plain-text file instead (see write_warnings_file()), saved alongside it
    as "<name>_Warnings.txt".

    When `project_name` is left as None, it's read back from
    `project_identity` (project_name (abbreviation) if an abbreviation was
    set), falling back to "FTTx Deployment". Pass an explicit `project_name`
    to override that lookup entirely.

    Returns {"report_path": ..., "warnings_path": ...}."""
    if project_name is None:
        identity = read_project_identity(project_identity) or {}
        project_name = identity.get("project_name") or "FTTx Deployment"
        abbrev = identity.get("project_abbreviation") or ""
        if abbrev:
            project_name = f"{project_name} ({abbrev})"
    if not _HAVE_DOCX:
        raise RuntimeError(
            "python-docx is not installed for this interpreter:\n\n"
            f"    {sys.executable}\n\n"
            "Install it with `pip install python-docx` into the environment "
            "this backend/Celery worker actually runs in."
        )
    if include_maps and not _HAVE_MAPPING:
        include_maps = False

    report = build_report_data(output_layers, optical_summary, project_identity)
    document = _write_report_document(report, output_layers, project_name, include_maps)
    document.save(output_path)

    warnings_path = _default_warnings_path(output_path)
    write_warnings_file(report, warnings_path)

    return {"report_path": output_path, "warnings_path": warnings_path}


# =============================================================================
# WARNINGS FILE — kept out of the .docx entirely, its own plain-text file
# (pure Python, verbatim from the source)
# =============================================================================

def _default_warnings_path(report_path: str) -> str:
    base, _ext = os.path.splitext(report_path)
    return base + "_Warnings.txt"


def render_warnings_text(report: Dict[str, Any]) -> str:
    """Pure text-rendering of a `report` dict's findings/boundary-crossings —
    no file I/O, so this half is directly unit-testable."""
    validation_rows = report["raw"].get('validation_results', [])
    crossings = report["boundary_crossings"]
    lines: List[str] = []

    lines.append("=" * 78)
    lines.append("FTTx DESIGN — WARNINGS & FDT BOUNDARY CROSSINGS")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 78)
    lines.append("")

    lines.append("SECTION 1 — DESIGN ENGINE WARNINGS / ERRORS")
    lines.append("-" * 78)
    if not validation_rows:
        lines.append("No structured findings are available for this run (older design run,")
        lines.append("predating the Validation_Results output layer).")
    else:
        errors = [r for r in validation_rows if r.get('severity') == 'ERROR']
        warnings = [r for r in validation_rows if r.get('severity') == 'WARNING']
        lines.append(f"{len(errors)} error-level and {len(warnings)} warning-level "
                      f"finding(s) recorded during generation.")
        lines.append("")
        for row in validation_rows:
            lines.append(f"[{row.get('severity')}] [{row.get('category')}] {row.get('message')}")
    lines.append("")

    lines.append("SECTION 2 — DATA INTEGRITY ISSUES")
    lines.append("-" * 78)
    integrity = report["integrity_findings"]
    if not integrity:
        lines.append("No data integrity issues were detected in the final design output.")
    else:
        for row in integrity:
            lines.append(f"[{row['severity']}] [{row['category']}] {row['message']}")
    lines.append("")

    lines.append("SECTION 3 — FDT BOUNDARY CROSSINGS")
    lines.append("-" * 78)
    lines.append(
        "Every FAT whose allocation_type is not \"native\" — i.e. it was borrowed "
        "or absorbed into an FDT group across a street boundary during capacity "
        "rebalancing — with the specific boundary crossed to form that FDT group."
    )
    lines.append("")
    if not crossings:
        lines.append("No FAT crossed an FDT boundary in this design (every FAT is native "
                      "to its own FDT group).")
    else:
        by_fdt: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for c in crossings:
            by_fdt[c["fdt"] or "UNASSIGNED"].append(c)
        for fdt_name in sorted(by_fdt.keys()):
            lines.append(f"{fdt_name}:")
            for c in by_fdt[fdt_name]:
                boundary_note = (
                    f"crosses street boundary ({c['fat_street']} -> {c['fdt_street']})"
                    if c["crosses_street_boundary"]
                    else f"same street ({c['fat_street']})"
                )
                dist = c["network_dist_to_fdt_m"]
                dist_note = f", {dist:.1f} m to FDT" if isinstance(dist, (int, float)) else ""
                lines.append(f"  - {c['fat']}: {c['allocation_type'].upper()} — {boundary_note}{dist_note}")
            lines.append("")

    lines.append("=" * 78)
    lines.append("END OF WARNINGS FILE")
    lines.append("=" * 78)
    return "\n".join(lines)


def write_warnings_file(report: Dict[str, Any], output_path: str) -> str:
    text = render_warnings_text(report)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
    return output_path
