# ============================================================
# OPSYN DESIGN INPUTS — app/modules/design/inputs.py
#
# A design's own inputs (decision D6): roads, homepasses, poles, buildings,
# pickup points and existing structures, uploaded per design as GeoJSON or
# Excel. Parsing reuses the network upload readers (network/upload.py:
# read_rows, point_from_row, line_from_row) so both upload paths accept the
# same files the same way.
#
#   road                LineString / MultiLineString  (Excel: geometry_wkt)
#   homepass            Point, with a customer count  (normalised to
#                       properties.customers — the field the engine reads)
#   pole, pickup,
#   existing_structure  Point
#   building            Polygon / MultiPolygon / Point
#
# All-or-nothing: any invalid feature rejects the file (every error is
# reported, nothing is written). mode=replace swaps the layer's features,
# mode=append adds to them.
# ============================================================

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import shape

from app.modules.network.upload import FileError, line_from_row, point_from_row, read_rows

MAX_FEATURES = 50_000
MAX_ERRORS_REPORTED = 200

GEOMETRY_TYPES: dict[str, tuple[str, ...]] = {
    "road": ("LineString", "MultiLineString"),
    "homepass": ("Point",),
    "pole": ("Point",),
    "pickup": ("Point",),
    "existing_structure": ("Point",),
    "building": ("Polygon", "MultiPolygon", "Point"),
}

LAYER_LABELS: dict[str, str] = {
    "road": "Roads", "homepass": "Homepasses", "pole": "Poles", "building": "Buildings",
    "pickup": "Pickup points", "existing_structure": "Existing structures",
}

# Where a homepass's customer count may be found, in order of preference
COUNT_FIELDS: tuple[str, ...] = ("customers", "homepass", "homepasses", "count", "units", "hp", "name")


@dataclass
class ParsedInputs:
    features: list[dict[str, Any]] = field(default_factory=list)     # {geometry, properties}
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    file_hash: str = ""


def _finite(coords: Any) -> bool:
    if isinstance(coords, (int, float)):
        return math.isfinite(coords)
    return all(_finite(c) for c in coords)


def _in_range(coords: Any) -> bool:
    if coords and isinstance(coords[0], (int, float)):
        return -180 <= coords[0] <= 180 and -90 <= coords[1] <= 90
    return all(_in_range(c) for c in coords)


def _check_geometry(layer: str, geom: dict[str, Any]) -> str | None:
    gtype = geom.get("type")
    if gtype not in GEOMETRY_TYPES[layer]:
        return f"{LAYER_LABELS[layer]} must be {' or '.join(GEOMETRY_TYPES[layer])} (got {gtype})"
    coords = geom.get("coordinates")
    if coords is None or not _finite(coords) or not _in_range(coords):
        return "coordinates are missing or outside longitude −180..180 / latitude −90..90"
    try:
        shp = shape(geom)
    except Exception:
        return "the geometry could not be read"
    if shp.is_empty:
        return "the geometry is empty"
    if layer == "road" and shp.length == 0:      # before is_valid: say what is actually wrong
        return "a road needs two distinct points"
    if not shp.is_valid:
        return "the geometry is not valid (self-crossing or unclosed ring)"
    return None


def _count(props: dict[str, Any]) -> tuple[int | None, bool]:
    """(customer count, found). Non-numeric values are skipped."""
    for key in COUNT_FIELDS:
        for k, v in props.items():
            if k.lower() != key or v in (None, ""):
                continue
            try:
                n = float(str(v).strip())
            except ValueError:
                continue
            if math.isfinite(n) and n >= 0 and n == int(n):
                return int(n), True
    return None, False


def parse_input_file(layer: str, filename: str, data: bytes) -> ParsedInputs:
    out = ParsedInputs(file_hash=hashlib.sha256(data).hexdigest())
    try:
        _headers, rows = read_rows(filename, data)
    except FileError as exc:
        out.errors.append({"row": 0, "field": "file", "error": str(exc)})
        return out

    no_count = 0
    for n, raw, geom in rows:
        if len(out.features) + len(out.errors) >= MAX_FEATURES:
            out.errors.append({"row": 0, "field": "file",
                               "error": f"More than {MAX_FEATURES:,} features; split the file"})
            break
        raw = raw or {}
        if geom is None:                      # Excel: the geometry comes from columns
            if layer == "road":
                line, err = line_from_row(raw, None)
                geom = {"type": "LineString", "coordinates": line} if line else None
            elif layer == "building" and raw.get("geometry_wkt"):
                geom, err = None, "Excel buildings are points (longitude, latitude); upload polygons as GeoJSON"
            else:
                pt, err, _f = point_from_row(raw, None)
                geom = {"type": "Point", "coordinates": pt} if pt else None
            if geom is None:
                out.errors.append({"row": n, "field": "geometry", "error": err or "no geometry"})
                continue
        props = {k: v for k, v in raw.items() if k not in ("longitude", "latitude", "geometry_wkt")}
        err = _check_geometry(layer, geom)
        if err:
            out.errors.append({"row": n, "field": "geometry", "error": err})
            continue
        if layer == "homepass":
            count, found = _count(props)
            if not found:
                no_count += 1
                count = 1
            props["customers"] = count
        out.features.append({"geometry": geom, "properties": _json_safe(props)})

    if not out.features and not out.errors:
        out.errors.append({"row": 0, "field": "file", "error": "The file has no features"})
    if no_count:
        out.warnings.append(f"{no_count} homepasses had no customer count and were counted as 1")
    out.errors = out.errors[:MAX_ERRORS_REPORTED]
    return out


def _json_safe(props: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(props, default=str))
