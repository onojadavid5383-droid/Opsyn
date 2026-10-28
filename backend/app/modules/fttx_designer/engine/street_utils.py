"""Verbatim port of the small street-name/geometry utilities from
``FTTx Designer — dual PON integrated.py``: ``_detect_street_field``,
``_build_road_to_street_map``, ``_build_street_bboxes``, ``_street_position``.

Pulled into their own dependency-free module (source defines them once,
inline in the pole-tagging/BOQ section of the file, but they are consumed
by three otherwise-unrelated modules): ``wing_assignment.py`` (device
ordering along a street during wing assignment), ``structures.py``
(``assign_pole_tags``' street-relative pole ordering), and ``boq.py``
(``populate_boq_layer``'s per-street bucketing). Centralizing them here
avoids picking an arbitrary "owner" module for the other two to import
from, and keeps this leaf module free of any engine-internal dependencies.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Set, Tuple

from .geometry_compat import QgsPointXY, QgsVectorLayer


def _detect_street_field(road_layer: QgsVectorLayer) -> Optional[str]:
    """Pick best available street-name field from road layer."""
    names = [f.name() for f in road_layer.fields()]
    preferred = ["street_name", "street", "road_name", "name", "Street", "STREET", "ROAD_NAME", "Name"]
    lower_lookup = {n.lower(): n for n in names}
    for cand in preferred:
        if cand.lower() in lower_lookup:
            return lower_lookup[cand.lower()]
    # Fallback: first field whose actual value (sampled from any feature
    # that has one) is a string. Real QGIS checks the field's declared
    # `type() == QVariant.String`; this compat layer's QgsField carries no
    # type metadata (see geometry_compat/vector_layer.py's docstring — only
    # `.name()` is modeled, since no other ported call site ever needed
    # field-type introspection), so this inspects a sampled attribute value
    # instead of a declared column type to find the same kind of field.
    for name in names:
        for feat in road_layer.getFeatures():
            val = feat.attribute(name)
            if val is not None:
                if isinstance(val, str):
                    return name
                break
    return None


def _build_road_to_street_map(road_layer: QgsVectorLayer) -> Tuple[Dict[int, str], List[str]]:
    """Build road-id to street-name map and ordered unique street list."""
    street_field = _detect_street_field(road_layer)
    road_to_street: Dict[int, str] = {}
    street_set: Set[str] = set()

    for feat in road_layer.getFeatures():
        street = ""
        if street_field:
            try:
                street = str(feat[street_field] or "").strip()
            except Exception:
                street = ""
        if not street:
            street = f"ROAD_{feat.id()}"
        road_to_street[feat.id()] = street
        street_set.add(street)

    return road_to_street, sorted(street_set)


def _build_street_bboxes(road_layer: QgsVectorLayer,
                          road_to_street: Dict[int, str]) -> Dict[str, Tuple[float, float, float, float]]:
    """Bounding box (xmin, ymin, xmax, ymax) covering every road segment that
    shares a given street name.

    Used as a cheap, deterministic proxy axis for ordering devices
    "sequentially along the street" — a street's own bounding-box diagonal
    stands in for its general direction of travel without needing to
    reconstruct the exact chain of segments that make it up.
    """
    bboxes: Dict[str, List[float]] = {}
    for feat in road_layer.getFeatures():
        street = road_to_street.get(feat.id())
        if not street:
            continue
        geom = feat.geometry()
        if not geom or geom.isEmpty():
            continue
        bb = geom.boundingBox()
        if street not in bboxes:
            bboxes[street] = [bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum()]
        else:
            b = bboxes[street]
            b[0] = min(b[0], bb.xMinimum())
            b[1] = min(b[1], bb.yMinimum())
            b[2] = max(b[2], bb.xMaximum())
            b[3] = max(b[3], bb.yMaximum())
    return {k: (v[0], v[1], v[2], v[3]) for k, v in bboxes.items()}


def _street_position(pt: Optional['QgsPointXY'],
                      bbox: Optional[Tuple[float, float, float, float]]) -> float:
    """Scalar projection of `pt` onto its street's own bounding-box diagonal —
    a simple, deterministic "distance along the street" proxy. Larger values
    sit further along the diagonal; used only to order devices relative to
    each other on the same street, never as a real-world distance."""
    if pt is None or bbox is None:
        return 0.0
    xmin, ymin, xmax, ymax = bbox
    dx, dy = xmax - xmin, ymax - ymin
    norm = math.hypot(dx, dy) or 1.0
    return ((pt.x() - xmin) * dx + (pt.y() - ymin) * dy) / norm
