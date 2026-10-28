# ============================================================
# OPSYN FTTX DESIGNER GEOJSON I/O — app/modules/fttx_designer/geojson_io.py
#
# The web-upload boundary the engine package (engine/) always deferred as
# "Phase 5" — now concrete now that uploads are GeoJSON (see the
# 0085_fttx_designer_runs migration's docstring for why GeoJSON was chosen
# and how it simplifies CRS handling).
#
# Two directions:
#   build_input_layers()  — GeoJSON (always WGS84, per RFC 7946) -> the
#                            Dict[str, QgsVectorLayer] pipeline.run_fttx_design()
#                            expects, reprojected to one shared UTM zone.
#   layer_to_geojson()     — an engine-produced QgsVectorLayer (UTM) -> a
#                            WGS84 GeoJSON FeatureCollection, for the
#                            frontend's Leaflet-style map.
#
# This module is NOT part of engine/ (the ported-from-source package) —
# it is new web-integration glue, same status as pipeline.py's own
# "genuinely adapted" tail (see that module's docstring).
#
# CRS strategy: the source script's validate_selected_layers() (still
# deferred — see engine/validation.py's docstring) has to cope with roads
# and poles arriving in arbitrary, possibly-inconsistent CRSs, because a
# desktop QGIS project can mix layers from anywhere. A GeoJSON upload
# can't have that problem — RFC 7946 mandates WGS84 — so there is exactly
# one CRS decision left: which UTM zone to project into for the run's
# metre-accurate distance math. `_utm_epsg_for_extent()` below is a
# verbatim port of the source function of the same name (previously
# unported since its only caller, validate_selected_layers, was deferred);
# it is applied here to the road layer's own extent, exactly as the source
# does in validate_selected_layers's "every layer is geographic" branch.
# ============================================================

from __future__ import annotations

import math
import numbers
from decimal import Decimal
from collections.abc import Mapping
from typing import Any, Callable, Dict, List, Optional, Tuple

import pyproj
from shapely import wkt as _shapely_wkt
from shapely.geometry import mapping as _shapely_mapping
from shapely.geometry import shape as _shapely_shape

from app.modules.fttx_designer.engine.geometry_compat import (
    QgsCoordinateReferenceSystem,
    QgsGeometry,
    QgsRectangle,
    QgsVectorLayer,
)


class GeoJsonLayerError(ValueError):
    """Raised for a malformed or empty uploaded GeoJSON layer."""


def json_safe(value: Any) -> Any:
    """Normalize values before writing JSONB, where NaN/Infinity are invalid."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, Decimal):
        number = float(value)
        return number if value.is_finite() and math.isfinite(number) else None
    if isinstance(value, numbers.Real):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    # Normalize NumPy arrays/scalars and similar library containers.
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            normalized = tolist()
        except (TypeError, ValueError):
            return value
        if normalized is not value:
            return json_safe(normalized)
    item = getattr(value, "item", None)
    if callable(item):
        try:
            scalar = item()
        except (TypeError, ValueError):
            return value
        if scalar is not value:
            return json_safe(scalar)
    return value


def _utm_epsg_for_extent(extent_4326: QgsRectangle) -> str:
    """Verbatim port of the source script's ``_utm_epsg_for_extent`` — return
    the correct UTM EPSG code for a geographic (EPSG:4326) extent's
    centroid — never a hardcoded zone. UTM zones are 6 degrees wide
    starting at -180; zone = floor((lon+180)/6)+1. Northern hemisphere uses
    the 326xx series, southern uses 327xx."""
    lon = (extent_4326.xMinimum() + extent_4326.xMaximum()) / 2.0
    lat = (extent_4326.yMinimum() + extent_4326.yMaximum()) / 2.0
    zone = int((lon + 180.0) // 6.0) + 1
    zone = max(1, min(60, zone))
    base = 32600 if lat >= 0 else 32700
    return f"EPSG:{base + zone}"


def _feature_collection_extent(
    feature_collection: Dict[str, Any],
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> QgsRectangle:
    """Bounding box (WGS84) over every feature with a geometry."""
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    features = feature_collection.get("features", [])
    report_every = max(1, len(features) // 10)
    for index, feat in enumerate(features):
        if progress_callback and index % report_every == 0:
            progress_callback(2, "Inspecting road layer extent")
        geom = feat.get("geometry")
        if not geom:
            continue
        b = _shapely_shape(geom).bounds  # (minx, miny, maxx, maxy)
        xmin, ymin = min(xmin, b[0]), min(ymin, b[1])
        xmax, ymax = max(xmax, b[2]), max(ymax, b[3])
    if xmin > xmax:
        raise GeoJsonLayerError("GeoJSON FeatureCollection has no features with geometry")
    return QgsRectangle(xmin, ymin, xmax, ymax)


def _reproject_coords(coords: Any, transformer: "pyproj.Transformer") -> Any:
    """Recursively reproject a GeoJSON `coordinates` array (works for
    Point/LineString/Polygon/Multi* — the nesting depth is the only
    difference between them, and a plain [x, y] pair is always the
    innermost element)."""
    if isinstance(coords[0], (int, float)):
        x, y = transformer.transform(coords[0], coords[1])
        return [x, y]
    return [_reproject_coords(c, transformer) for c in coords]


def _reproject_geometry_dict(geom: Dict[str, Any], transformer: "pyproj.Transformer") -> Dict[str, Any]:
    if geom.get("type") == "GeometryCollection":
        return {
            **geom,
            "geometries": [_reproject_geometry_dict(g, transformer) for g in geom.get("geometries", [])],
        }
    return {**geom, "coordinates": _reproject_coords(geom["coordinates"], transformer)}


def _feature_field_names(features: List[Dict[str, Any]]) -> List[str]:
    """Ordered, de-duplicated property keys across every feature — becomes
    the layer's field schema, matching how QgsVectorLayer.from_records()
    infers field_names when none are given, except computed once up front
    so every feature (even one missing a property another one has) binds
    to the same schema."""
    names: List[str] = []
    seen = set()
    for feat in features:
        for key in (feat.get("properties") or {}):
            if key not in seen:
                seen.add(key)
                names.append(key)
    return names


def _geojson_to_layer(
    feature_collection: Dict[str, Any],
    transformer: "pyproj.Transformer",
    crs: QgsCoordinateReferenceSystem,
    layer_id: str,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    progress_start: int = 2,
    progress_end: int = 4,
) -> QgsVectorLayer:
    features = feature_collection.get("features", [])
    field_names = _feature_field_names(features)

    records: List[Dict[str, Any]] = []
    report_every = max(1, len(features) // 20)
    layer_label = layer_id.replace("_", " ").title()
    for index, feat in enumerate(features):
        if progress_callback and index % report_every == 0:
            fraction = index / max(1, len(features))
            pct = progress_start + int((progress_end - progress_start) * fraction)
            progress_callback(pct, f"Preparing {layer_label} layer")
        geom_dict = feat.get("geometry")
        if geom_dict is None:
            continue
        reprojected = _reproject_geometry_dict(geom_dict, transformer)
        record: Dict[str, Any] = {"geometry": QgsGeometry(_shapely_shape(reprojected))}
        record.update(feat.get("properties") or {})
        records.append(record)

    return QgsVectorLayer.from_records(records, field_names=field_names, crs=crs, layer_id=layer_id)


def build_input_layers(
    geojson_by_key: Dict[str, Dict[str, Any]],
    *,
    road_key: str = "road",
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> Tuple[Dict[str, QgsVectorLayer], QgsCoordinateReferenceSystem]:
    """Build the ``layers`` dict ``pipeline.run_fttx_design()`` expects from
    a set of uploaded GeoJSON FeatureCollections (one per layer key: road,
    homepass, pole, and optionally building, pickup).

    Every layer is reprojected from WGS84 into the same UTM zone, chosen
    from the road layer's own extent (matching the source's own fallback
    UTM-selection rule — see this module's docstring). Raises
    ``GeoJsonLayerError`` if ``road_key`` is missing or empty.
    """
    if road_key not in geojson_by_key:
        raise GeoJsonLayerError(f"Missing required '{road_key}' layer")

    road_extent = _feature_collection_extent(geojson_by_key[road_key], progress_callback)
    target_epsg = _utm_epsg_for_extent(road_extent)
    target_crs = QgsCoordinateReferenceSystem(target_epsg)

    transformer = pyproj.Transformer.from_crs(
        pyproj.CRS.from_epsg(4326), pyproj.CRS.from_user_input(target_epsg), always_xy=True,
    )

    layers: Dict[str, QgsVectorLayer] = {}
    layer_count = max(1, len(geojson_by_key))
    for index, (key, feature_collection) in enumerate(geojson_by_key.items()):
        start = 2 + int(2 * index / layer_count)
        end = 2 + int(2 * (index + 1) / layer_count)
        layers[key] = _geojson_to_layer(
            feature_collection, transformer, target_crs, layer_id=key,
            progress_callback=progress_callback, progress_start=start, progress_end=end,
        )
    return layers, target_crs


def layer_to_rows(layer: QgsVectorLayer) -> List[Dict[str, Any]]:
    """Serialize a non-spatial ``QgsVectorLayer`` (e.g. the BOQ / BOQ FDT
    Detail tables, which the source itself builds with no geometry —
    ``QgsVectorLayer("None", ...)`` — see ``boq.py``) to a plain list of
    attribute dicts, one per row. Unlike ``layer_to_geojson()``, this never
    touches ``feat.geometry()`` — a tabular result has none to serialize."""
    field_names = layer.fields().names()
    return json_safe([
        {name: feat.attribute(name) for name in field_names}
        for feat in layer.getFeatures()
    ])


def layer_to_geojson(layer: QgsVectorLayer) -> Dict[str, Any]:
    """Serialize an engine-produced ``QgsVectorLayer`` (in whatever UTM zone
    the run used) back to a WGS84 GeoJSON FeatureCollection, for the
    frontend's map. A layer already in WGS84 (shouldn't normally happen for
    engine output, but harmless if it does) is passed through unreprojected.
    """
    source_authid = layer.crs().authid()
    transformer: Optional["pyproj.Transformer"] = None
    if source_authid and source_authid.upper() != "EPSG:4326":
        transformer = pyproj.Transformer.from_crs(
            pyproj.CRS.from_user_input(source_authid), pyproj.CRS.from_epsg(4326), always_xy=True,
        )

    field_names = layer.fields().names()
    features: List[Dict[str, Any]] = []
    for feat in layer.getFeatures():
        geom = feat.geometry()
        geo_dict: Optional[Dict[str, Any]] = None
        if geom is not None and not geom.isEmpty():
            geo_dict = _shapely_mapping(_shapely_wkt.loads(geom.asWkt()))
            if transformer is not None:
                geo_dict = _reproject_geometry_dict(geo_dict, transformer)
        properties = {name: feat.attribute(name) for name in field_names}
        features.append({"type": "Feature", "geometry": geo_dict, "properties": properties})

    return json_safe({"type": "FeatureCollection", "features": features})
