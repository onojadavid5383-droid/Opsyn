"""Verbatim port of ``populate_output_layers`` from
``FTTx Designer — dual PON integrated.py``: writes the FDT/FAT/Box_to_Box/
Box_to_Customer/Closure/Tagged_Poles/Pickup_Point/Feeder/Closure_to_FDT
device-attribute rows into their respective output layers, then calls
``populate_boq_layer`` (boq.py) to fill the BOQ summary table.

No logic changes from the source script — only the QGIS types and
cross-module imports. This uses only the same append-only
``QgsFeature(layer.fields())`` + ``.setAttributes()`` +
``layer.dataProvider().addFeatures([...])`` write API already extended for
``boq.py`` — no further ``geometry_compat`` changes were needed beyond
adding ``QgsVectorLayer.extent()``/``updateExtents()`` (a live bounding-box
computation over the layer's own features; there's no separate cache here
to invalidate, so ``updateExtents()`` is a no-op — see that module's
docstring), which this function calls on every output layer after writing.

Deliberately excluded from this module: ``create_output_layers``. It
constructs the empty layers this function populates via real QGIS
provider-string syntax (``QgsVectorLayer("Point?crs=...", "FDT",
"memory")``), ``QVariant`` field-type enums, and
``project.mapLayersByName()``/``removeMapLayer()`` project-registry
cleanup — genuine QGIS Project/provider machinery with no
``geometry_compat`` equivalent, and not clearly the right thing to
replicate 1:1 for a web backend anyway (which will define its own output
schema — DB rows or GeoJSON, not QGIS memory layers with a project
registry). Deferred to Phase 5, alongside ``validate_selected_layers``.
Callers of ``populate_output_layers`` in the meantime build the target
layers via ``QgsVectorLayer.from_records([], field_names=[...])``, matching
how ``boq.py``'s functions are already tested.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from .boq import populate_boq_layer
from .config import CAPACITY_PROFILES, CapacityProfile, CascadeArchitecture, PONArchitecture
from .domain import FAT, FDT, CableSegment, DomeClosure, Homepass, SupportStructure
from .geometry_compat import QgsFeature, QgsGeometry, QgsVectorLayer, QgsWkbTypes
from .homepass_assignment import _parse_homepass_value
from .perf_logger import PerformanceLogger
from .street_utils import _build_road_to_street_map


def populate_output_layers(layers: Dict[str, QgsVectorLayer],
                          road_layer: QgsVectorLayer,
                          homepass_layer: QgsVectorLayer,
                          pole_layer: QgsVectorLayer,
                          homepasses: List[Homepass],
                          fdts: List[FDT],
                          fats: List[FAT],
                          b2b_cables: List[CableSegment],
                          b2c_cables: List[CableSegment],
                          closures: List[DomeClosure],
                          closure_cables: List[CableSegment],
                          pickup_cables: List[CableSegment],
                          pickup_layer: Optional[QgsVectorLayer],
                          logger: PerformanceLogger,
                          coverage_pct: int = 100,
                          cascade_architecture: 'CascadeArchitecture' = None,
                          profile: Optional['CapacityProfile'] = None,
                          structures: Optional[List['SupportStructure']] = None):
    """Populate output layers with features, including dome closures and cables"""
    logger.start_module("Output Layer Population")
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]

    def _order_fats_for_attribute_table(fats_list: List[FAT]) -> List[FAT]:
        """Return fats ordered by parent FDT, wing, then fat sequence.

        This helper only affects how FAT records are iterated when creating
        attribute table features. It does not modify any FAT objects or
        underlying design relationships.
        """
        def parse_parent_fdt(fat: FAT):
            # Try explicit serial first
            try:
                if getattr(fat, 'fdt_serial', None) is not None:
                    return int(fat.fdt_serial)
            except Exception:
                pass
            # Try to extract trailing number from parent_fdt (e.g., 'FDT-06')
            try:
                pf = getattr(fat, 'parent_fdt', '') or ''
                # extract digits
                m = re.search(r"(\d+)\s*$", str(pf))
                if m:
                    return int(m.group(1))
            except Exception:
                pass
            # Fallback to large number so unknowns sort last
            return 10**9

        def parse_wing(fat: FAT):
            # Prefer `wing` then `wing_id` — normalize to uppercase single letter
            w = getattr(fat, 'wing', None) or getattr(fat, 'wing_id', None) or ''
            try:
                w = str(w).strip().upper()
                if len(w) > 1:
                    # sometimes 'A1' or similar — take first letter
                    w = w[0]
                if w and w.isalpha():
                    return ord(w) - ord('A')
            except Exception:
                pass
            return 10**6

        def parse_sequence(fat: FAT):
            # fat_sequence may be numeric or string like '01'
            try:
                seq = getattr(fat, 'fat_sequence', None)
                if seq is None:
                    # try to extract trailing number from fat name
                    name = getattr(fat, 'fat_full_code', None) or getattr(fat, 'name', '')
                    m = re.search(r"(\d+)$", str(name))
                    if m:
                        return int(m.group(1))
                    return 10**6
                return int(str(seq))
            except Exception:
                # final fallback: put non-parsable sequences at end
                return 10**6

        return sorted(fats_list, key=lambda f: (parse_parent_fdt(f), parse_wing(f), parse_sequence(f)))

    # road_id -> street name, used to stamp every device with the name of
    # the street it physically sits on (Name field stays the device code;
    # road_name is the human-readable street label — see ded_report_generator.py,
    # which has no other way to discover which arbitrary input layer was
    # "the road layer" for this run).
    road_to_street, _all_street_names = _build_road_to_street_map(road_layer)

    def _fdt_road_name(fdt: 'FDT') -> str:
        rid = fdt.primary_road_id
        if rid is None and fdt.fats:
            rid = fdt.fats[0].road_id
        return road_to_street.get(rid, "UNASSIGNED")

    def _closure_road_name(closure: 'DomeClosure') -> str:
        if not closure.fdts:
            return "UNASSIGNED"
        names = Counter(_fdt_road_name(f) for f in closure.fdts)
        return names.most_common(1)[0][0]

    # FDT Layer
    # Phase 11: one closure-to-FDT cable feeds each FDT (fdt_id == fdt.name)
    # — look its core_info up once so every FDT row can show what feeds it.
    core_by_fdt_name: Dict[str, Dict] = {
        c.fdt_id: c.core_info for c in closure_cables if c.fdt_id
    }
    fdt_features = []
    for fdt in fdts:
        feat = QgsFeature(layers['fdt'].fields())
        geom = fdt.snapped_geometry or fdt.geometry
        feat.setGeometry(QgsGeometry.fromPointXY(geom))
        ci = core_by_fdt_name.get(fdt.name, {})
        feat.setAttributes([
            fdt.name,
            fdt.fdt_code or fdt.name,
            fdt.fdt_serial,
            "",  # Tag (can be filled later)
            # V5: use live len(fdt.fats) / sum(customers) — frozen fdt.total_fat
            # is stale after _resolve_legacy_fat_boundaries moves FATs around.
            sum(_parse_homepass_value(f.total_customers) for f in fdt.fats),
            len(fdt.fats),
            fdt.wing_a_count,
            fdt.wing_b_count,
            fdt.wing_c_count,
            fdt.wing_d_count,
            profile.pon_count,
            ci.get("closure_name", ""),
            ci.get("buffer_color_active", ""),
            ci.get("core_color_active", ""),
            ci.get("core_number_active", 0) or 0,
            ci.get("buffer_color_redundant", ""),
            ci.get("core_color_redundant", ""),
            ci.get("core_number_redundant", 0) or 0,
            ci.get("pon2_buffer_color_active", ""),
            ci.get("pon2_core_color_active", ""),
            ci.get("pon2_core_number_active", 0) or 0,
            ci.get("pon2_buffer_color_redundant", ""),
            ci.get("pon2_core_color_redundant", ""),
            ci.get("pon2_core_number_redundant", 0) or 0,
            _fdt_road_name(fdt),
            fdt.structure_name,
        ])
        fdt_features.append(feat)
    layers['fdt'].dataProvider().addFeatures(fdt_features)

    # FAT Layer
    fat_features = []
    for fat in _order_fats_for_attribute_table(fats):
        feat = QgsFeature(layers['fat'].fields())
        geom = fat.offset_geometry or fat.snapped_geometry or fat.geometry
        feat.setGeometry(QgsGeometry.fromPointXY(geom))
        feat.setAttributes([
            fat.name,
            fat.parent_fdt,
            fat.physical_fdt,
            fat.logical_fdt,
            fat.allocation_type,
            fat.network_dist_to_fdt,
            fat.fdt_serial,
            fat.wing_id or fat.wing,
            fat.fat_sequence,
            fat.fat_full_code or fat.name,
            fat.from_device,
            fat.to_device,
            fat.road_id,
            fat.total_customers,
            fat.cascade_order,
            fat.wing,
            fat.splitter_type,
            fat.fdt_port,  # V5: 1-indexed direct FDT port (legacy); 0 in PCC
            road_to_street.get(fat.road_id, "UNASSIGNED"),
            fat.structure_name,
        ])
        fat_features.append(feat)

    layers['fat'].dataProvider().addFeatures(fat_features)

    # Box-to-Box Cable Layer
    b2b_features = []
    for cable in b2b_cables:
        feat = QgsFeature(layers['b2b'].fields())
        feat.setGeometry(cable.geometry)
        ci = cable.core_info or {}
        feat.setAttributes([
            cable.name,
            cable.start_device,
            cable.end_device,
            cable.length,
            cable.fdt_id,
            # V5 architecture fields
            ci.get("architecture", "PCC"),
            str(ci.get("fdt_port", "")),
            ci.get("tap_sequence", ""),
            ci.get("cable_type", "b2b"),
            ci.get("wing", ""),
            ci.get("wing_name", cable.fdt_id),
            bool(ci.get("length_exception", False)),
            ci.get("length_limit_m", 0.0),
            ci.get("length_excess_m", 0.0),
            ci.get("exception_cost_estimate", 0.0),
        ])
        b2b_features.append(feat)

    layers['b2b'].dataProvider().addFeatures(b2b_features)

    # Box-to-Customer Cable Layer
    b2c_features = []
    for cable in b2c_cables:
        feat = QgsFeature(layers['b2c'].fields())
        feat.setGeometry(cable.geometry)
        # Extract customer ID from name (handles DROP_FAT_C123 and DROP_FAT_C123_1)
        customer_id = 0
        if '_C' in cable.name:
            try:
                suffix = cable.name.split('_C')[-1]
                customer_id = int(suffix.split('_')[0])
            except (ValueError, IndexError):
                pass

        feat.setAttributes([
            cable.name,
            cable.start_device,
            customer_id,
            cable.length
        ])
        b2c_features.append(feat)

    layers['b2c'].dataProvider().addFeatures(b2c_features)

    # Dome Closure Layer features
    if closures and 'closure' in layers:
        closure_features = []
        for closure in closures:
            feat = QgsFeature(layers['closure'].fields())
            geom = closure.snapped_geometry or closure.geometry
            feat.setGeometry(QgsGeometry.fromPointXY(geom))
            feat.setAttributes([
                closure.name,
                _closure_road_name(closure),
                closure.total_fdt,
                closure.feed_capacity,
                closure.pickup_name or "",
            ])
            closure_features.append(feat)
        layers['closure'].dataProvider().addFeatures(closure_features)

    # Pole Layer features — copy of the canonically-tagged pole structures.
    # Names/types/serials are already final by this point (see
    # assign_pole_tags(), called earlier in run_fttx_design() once closures/
    # pickups exist) — this block only writes them out, it does not compute
    # or re-derive any tag itself. Includes software-proposed poles too
    # (structures the design itself adds), not just input-layer poles.
    if 'pole_output' in layers and structures:
        poles = [s for s in structures if s.structure_type == "pole"]
        pole_features = []
        for pole in poles:
            feat = QgsFeature(layers['pole_output'].fields())
            feat.setGeometry(QgsGeometry.fromPointXY(pole.geometry))
            feat.setAttributes([pole.name, pole.name, pole.raw_name])
            pole_features.append(feat)
        if pole_features:
            layers['pole_output'].dataProvider().addFeatures(pole_features)
            logger.log(f"Tagged_Poles: wrote {len(pole_features)} canonically-tagged pole(s)")

    # Pickup Point Features
    if 'pickup_point' in layers:
        # Phase 11: per-pickup core totals, summed from this pickup's own
        # feeder cables (cable.start_device == the pickup name used below).
        pickup_core_totals: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"total_core": 0, "active_core": 0, "redundant_core": 0}
        )
        for cable in pickup_cables:
            agg = pickup_core_totals[cable.start_device]
            agg["total_core"]     += cable.core_info.get("total_core", 0)
            agg["active_core"]    += cable.core_info.get("active_core", 0)
            agg["redundant_core"] += cable.core_info.get("redundant_core", 0)

        def _core_totals(pickup_name: str) -> List[int]:
            t = pickup_core_totals.get(
                pickup_name, {"total_core": 0, "active_core": 0, "redundant_core": 0}
            )
            return [t["total_core"], t["active_core"], t["redundant_core"]]

        pp_feats = []
        seen = set()
        # first, include any user-supplied pickup features
        if pickup_layer and pickup_layer.featureCount() > 0:
            for feat in pickup_layer.getFeatures():
                geom = feat.geometry()
                if not geom or geom.isEmpty():
                    continue
                if QgsWkbTypes.geometryType(geom.wkbType()) != QgsWkbTypes.PointGeometry:
                    continue
                pt = geom.asPoint()
                key = (pt.x(), pt.y())
                seen.add(key)
                new_feat = QgsFeature(layers['pickup_point'].fields())
                new_feat.setGeometry(QgsGeometry.fromPointXY(pt))
                name = ""
                if 'name' in feat.fields().names():
                    try:
                        name = str(feat['name'])
                    except Exception:
                        name = ""
                new_feat.setAttributes([name, "existing"] + _core_totals(name))
                pp_feats.append(new_feat)
        # next add pickups assigned to closures (generated or nearest)
        if closures:
            for closure in closures:
                if closure.pickup_geometry:
                    key = (closure.pickup_geometry.x(), closure.pickup_geometry.y())
                    if key in seen:
                        continue
                    seen.add(key)
                    new_feat = QgsFeature(layers['pickup_point'].fields())
                    new_feat.setGeometry(QgsGeometry.fromPointXY(closure.pickup_geometry))
                    source = "existing" if pickup_layer and pickup_layer.featureCount() > 0 else "generated"
                    pickup_name = closure.pickup_name or "PICKUP"
                    new_feat.setAttributes([pickup_name, source] + _core_totals(pickup_name))
                    pp_feats.append(new_feat)
        layers['pickup_point'].dataProvider().addFeatures(pp_feats)

    # Feeder Cable Layer features
    if 'feeder' in layers:
        feeder_feats = []
        for cable in pickup_cables:
            feat = QgsFeature(layers['feeder'].fields())
            feat.setGeometry(cable.geometry)
            cable_type = cable.core_info.get('cable_type', '')
            feat.setAttributes([
                cable.name,
                cable.start_device,
                cable.end_device,
                cable_type,
                cable.length,
                cable.core_info.get("total_pole", 0),
                cable.core_info.get("tension_clamp", 0),
                cable.core_info.get("hook_belt", 0),
                cable.core_info.get("total_core", 0),
                cable.core_info.get("active_core", 0),
                cable.core_info.get("redundant_core", 0),
                cable.core_info.get("buffer_colors", ""),
                cable.core_info.get("fdt_core_map", ""),
            ])
            feeder_feats.append(feat)
        layers['feeder'].dataProvider().addFeatures(feeder_feats)

    # Closure-to-FDT Cable Layer features
    if closure_cables and 'closure_cable' in layers:
        cc_features = []
        for cable in closure_cables:
            feat = QgsFeature(layers['closure_cable'].fields())
            feat.setGeometry(cable.geometry)
            feat.setAttributes([
                cable.name,
                cable.core_info.get("closure_name", ""),
                cable.start_device,
                cable.end_device,
                cable.length,
                cable.fdt_id,
                cable.core_info.get("buffer_color_active", ""),
                cable.core_info.get("core_color_active", ""),
                cable.core_info.get("core_number_active", 0),
                cable.core_info.get("buffer_color_redundant", ""),
                cable.core_info.get("core_color_redundant", ""),
                cable.core_info.get("core_number_redundant", 0),
                cable.core_info.get("cable_capacity", ""),
                cable.core_info.get("cascade_group", ""),
                cable.core_info.get("total_pole", 0),
                cable.core_info.get("tension_clamp", 0),
                cable.core_info.get("hook_belt", 0),
                cable.core_info.get("pon2_buffer_color_active", ""),
                cable.core_info.get("pon2_core_color_active", ""),
                cable.core_info.get("pon2_core_number_active", 0) or 0,
                cable.core_info.get("pon2_buffer_color_redundant", ""),
                cable.core_info.get("pon2_core_color_redundant", ""),
                cable.core_info.get("pon2_core_number_redundant", 0) or 0,
            ])
            cc_features.append(feat)
        layers['closure_cable'].dataProvider().addFeatures(cc_features)

    # BOQ table
    populate_boq_layer(
        layers['boq'],
        road_layer,
        homepass_layer,
        pole_layer,
        homepasses,
        fdts,
        fats,
        b2b_cables,
        closures,
        closure_cables,
        pickup_cables,
        coverage_pct=coverage_pct,
        cascade_architecture=cascade_architecture,
        logger=logger,
    )

    # Update extents
    for layer in layers.values():
        layer.updateExtents()

    logger.end_module("Output Layer Population")
    logger.log(f"Created: {len(fdt_features)} FDTs, {len(fat_features)} FATs, "
              f"{len(b2b_features)} box-to-box cables, {len(b2c_features)} drop cables")
