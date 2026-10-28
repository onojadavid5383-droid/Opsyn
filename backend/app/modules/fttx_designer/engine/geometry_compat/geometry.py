"""Shapely-backed adapter for the subset of the QGIS geometry API
(``QgsGeometry``, ``QgsPointXY``, ``QgsRectangle``, ``QgsWkbTypes``) that the
ported FTTx pipeline calls directly.

Method names and signatures deliberately mirror the QGIS classes they
replace (``fromPointXY``, ``asPolyline``, ``lineLocatePoint``, ...) so the
pipeline modules under ``engine/`` (ported from
``FTTx Designer — dual PON integrated.py``) need no call-site changes beyond
their import line — see the integration plan's "compatibility shim, not full
rewrite" strategy.

Fidelity note: the method surface here was built from a full grep of every
QgsGeometry/QgsPointXY call in the source script, but exact numeric/edge-case
parity (e.g. ``closestSegmentWithContext``'s left/right sign convention) is
only verified once the modules that use it (``topology.py``) pass their
golden-output regression test against a real QGIS run — do not assume this
file is behaviorally complete on its own.
"""

from __future__ import annotations

import math
from typing import Any, List, Optional, Sequence, Tuple

from shapely.geometry import LineString, MultiLineString, MultiPoint, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
from shapely.ops import unary_union as _shapely_unary_union


class QgsPointXY:
    """Drop-in replacement for qgis.core.QgsPointXY."""

    __slots__ = ("_x", "_y")

    def __init__(self, x: float, y: float = 0.0):
        self._x = float(x)
        self._y = float(y)

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y

    def distance(self, other: "QgsPointXY") -> float:
        return math.hypot(self._x - other._x, self._y - other._y)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, QgsPointXY)
            and self._x == other._x
            and self._y == other._y
        )

    def __hash__(self) -> int:
        return hash((self._x, self._y))

    def __repr__(self) -> str:
        return f"QgsPointXY({self._x!r}, {self._y!r})"


class QgsRectangle:
    """Drop-in replacement for the subset of qgis.core.QgsRectangle used by
    the pipeline (bbox intersection candidates via QgsSpatialIndex)."""

    __slots__ = ("_xmin", "_ymin", "_xmax", "_ymax")

    def __init__(self, xmin: float, ymin: float, xmax: float, ymax: float):
        self._xmin, self._ymin, self._xmax, self._ymax = xmin, ymin, xmax, ymax

    def xMinimum(self) -> float:
        return self._xmin

    def xMaximum(self) -> float:
        return self._xmax

    def yMinimum(self) -> float:
        return self._ymin

    def yMaximum(self) -> float:
        return self._ymax

    def grow(self, delta: float) -> None:
        """Expand the rectangle by `delta` in all four directions, in place
        (matches qgis.core.QgsRectangle.grow)."""
        self._xmin -= delta
        self._ymin -= delta
        self._xmax += delta
        self._ymax += delta

    def __repr__(self) -> str:
        return f"QgsRectangle({self._xmin}, {self._ymin}, {self._xmax}, {self._ymax})"


class QgsWkbTypes:
    """Drop-in replacement for the small subset of qgis.core.QgsWkbTypes
    actually referenced (geometryType() category checks + displayString()).
    Real QgsWkbTypes distinguishes WKB Type (Point/PointZ/MultiPoint/...)
    from GeometryType (Point/Line/Polygon) — geometryType() is the only
    place the source script bridges the two, so that's the only mapping
    reproduced here."""

    PointGeometry = "PointGeometry"
    LineGeometry = "LineGeometry"
    PolygonGeometry = "PolygonGeometry"
    UnknownGeometry = "UnknownGeometry"
    NullGeometry = "NullGeometry"

    _CATEGORY_BY_SHAPELY_TYPE = {
        "Point": PointGeometry,
        "MultiPoint": PointGeometry,
        "LineString": LineGeometry,
        "MultiLineString": LineGeometry,
        "LinearRing": LineGeometry,
        "Polygon": PolygonGeometry,
        "MultiPolygon": PolygonGeometry,
    }

    @staticmethod
    def geometryType(wkb_type: str) -> str:
        return QgsWkbTypes._CATEGORY_BY_SHAPELY_TYPE.get(
            wkb_type, QgsWkbTypes.UnknownGeometry
        )

    @staticmethod
    def displayString(wkb_type: str) -> str:
        return str(wkb_type)


def _unwrap(geom: "QgsGeometry | BaseGeometry") -> BaseGeometry:
    return geom._geom if isinstance(geom, QgsGeometry) else geom


class QgsGeometry:
    """Drop-in replacement for the subset of qgis.core.QgsGeometry actually
    called in the source script (asPoint, asPolyline, asMultiPolyline,
    isEmpty, length, distance, intersects, contains, touches, buffer,
    interpolate, lineLocatePoint, nearestPoint, closestSegmentWithContext,
    boundingBox, wkbType, type, centroid, unaryUnion, convexHull, asWkt),
    backed by a wrapped Shapely geometry."""

    __slots__ = ("_geom",)

    def __init__(self, shapely_geom: Optional[BaseGeometry] = None):
        self._geom = shapely_geom

    # ---- constructors (QGIS staticmethods) --------------------------------

    @staticmethod
    def fromPointXY(point: QgsPointXY) -> "QgsGeometry":
        return QgsGeometry(Point(point.x(), point.y()))

    @staticmethod
    def fromPolylineXY(points: Sequence[QgsPointXY]) -> "QgsGeometry":
        coords = [(p.x(), p.y()) for p in points]
        if len(coords) < 2:
            return QgsGeometry()
        return QgsGeometry(LineString(coords))

    @staticmethod
    def fromMultiPolylineXY(lines: Sequence[Sequence[QgsPointXY]]) -> "QgsGeometry":
        valid = [[(p.x(), p.y()) for p in line] for line in lines if len(line) >= 2]
        if not valid:
            return QgsGeometry()
        return QgsGeometry(
            MultiLineString(valid)
        )

    @staticmethod
    def fromMultiPointXY(points: Sequence[QgsPointXY]) -> "QgsGeometry":
        return QgsGeometry(MultiPoint([(p.x(), p.y()) for p in points]))

    @staticmethod
    def unaryUnion(geometries: Sequence["QgsGeometry"]) -> "QgsGeometry":
        return QgsGeometry(_shapely_unary_union([_unwrap(g) for g in geometries]))

    # ---- extraction ---------------------------------------------------

    def asPoint(self) -> QgsPointXY:
        geom = self._geom
        pt = geom if geom.geom_type == "Point" else geom.centroid
        return QgsPointXY(pt.x, pt.y)

    def asPolyline(self) -> List[QgsPointXY]:
        return [QgsPointXY(x, y) for x, y in self._geom.coords]

    def asMultiPolyline(self) -> List[List[QgsPointXY]]:
        geoms = self._geom.geoms if hasattr(self._geom, "geoms") else [self._geom]
        return [[QgsPointXY(x, y) for x, y in g.coords] for g in geoms]

    def asWkt(self, precision: Optional[int] = None) -> str:
        if precision is None:
            return self._geom.wkt
        from shapely import wkt as _shapely_wkt

        return _shapely_wkt.dumps(self._geom, rounding_precision=precision)

    # ---- predicates / measures -----------------------------------------

    def isEmpty(self) -> bool:
        return self._geom is None or self._geom.is_empty

    def isNull(self) -> bool:
        return self._geom is None

    def length(self) -> float:
        return self._geom.length

    def distance(self, other: "QgsGeometry") -> float:
        return self._geom.distance(_unwrap(other))

    def intersects(self, other: "QgsGeometry | QgsRectangle") -> bool:
        if isinstance(other, QgsRectangle):
            from shapely.geometry import box

            other_geom = box(
                other.xMinimum(), other.yMinimum(), other.xMaximum(), other.yMaximum()
            )
        else:
            other_geom = _unwrap(other)
        return self._geom.intersects(other_geom)

    def contains(self, other: "QgsGeometry") -> bool:
        return self._geom.contains(_unwrap(other))

    def touches(self, other: "QgsGeometry") -> bool:
        return self._geom.touches(_unwrap(other))

    def crosses(self, other: "QgsGeometry") -> bool:
        return self._geom.crosses(_unwrap(other))

    def isMultipart(self) -> bool:
        return self._geom.geom_type.startswith("Multi")

    def wkbType(self) -> str:
        return self._geom.geom_type

    def type(self) -> str:
        return QgsWkbTypes.geometryType(self.wkbType())

    def boundingBox(self) -> QgsRectangle:
        xmin, ymin, xmax, ymax = self._geom.bounds
        return QgsRectangle(xmin, ymin, xmax, ymax)

    # ---- derived geometry -----------------------------------------------

    def buffer(self, distance: float, segments: int = 8) -> "QgsGeometry":
        return QgsGeometry(self._geom.buffer(distance, quad_segs=segments))

    def interpolate(self, distance: float) -> "QgsGeometry":
        return QgsGeometry(self._geom.interpolate(distance))

    def lineLocatePoint(self, point_geom: "QgsGeometry") -> float:
        return self._geom.project(_unwrap(point_geom))

    def nearestPoint(self, other: "QgsGeometry") -> "QgsGeometry":
        """Nearest point ON THIS geometry to `other` (matches QGIS semantics:
        geometry.nearestPoint(other) is a point on `self`)."""
        point_on_self, _point_on_other = nearest_points(self._geom, _unwrap(other))
        return QgsGeometry(point_on_self)

    def centroid(self) -> "QgsGeometry":
        return QgsGeometry(self._geom.centroid)

    def convexHull(self) -> "QgsGeometry":
        return QgsGeometry(self._geom.convex_hull)

    def closestVertex(self, point: "QgsPointXY") -> Tuple["QgsPointXY", int, int, int, float]:
        """Matches QGIS's (nearest_vertex_point, vertex_index,
        previous_vertex_index, next_vertex_index, sqrDist) — only the first
        element (the nearest vertex's own point) is used anywhere in the
        source script (``audit_road_layer_noding``), so the index fields are
        best-effort rather than exhaustively verified."""
        coords = list(self._geom.coords)
        if not coords:
            return QgsPointXY(point.x(), point.y()), -1, -1, -1, 0.0
        best_idx, best_sq = 0, float("inf")
        for i, (x, y) in enumerate(coords):
            sq = (x - point.x()) ** 2 + (y - point.y()) ** 2
            if sq < best_sq:
                best_sq, best_idx = sq, i
        vx, vy = coords[best_idx]
        prev_idx = best_idx - 1 if best_idx > 0 else -1
        next_idx = best_idx + 1 if best_idx < len(coords) - 1 else -1
        return QgsPointXY(vx, vy), best_idx, prev_idx, next_idx, best_sq

    def closestSegmentWithContext(
        self, point: QgsPointXY
    ) -> Tuple[float, QgsPointXY, int, int]:
        """Matches QGIS's (sqrDist, minDistPoint, afterVertexIndex, leftOf)
        return shape. `leftOf` sign convention: negative = point is left of
        the segment's direction, positive = right, 0 = on the line — callers
        in the source script only ever compare this against 0, so exact
        magnitude does not matter, only the sign."""
        coords = list(self._geom.coords)
        px, py = point.x(), point.y()
        best: Optional[Tuple[float, QgsPointXY, int, int]] = None
        for i in range(len(coords) - 1):
            x1, y1 = coords[i]
            x2, y2 = coords[i + 1]
            dx, dy = x2 - x1, y2 - y1
            seg_len_sq = dx * dx + dy * dy
            t = 0.0 if seg_len_sq == 0 else ((px - x1) * dx + (py - y1) * dy) / seg_len_sq
            t = max(0.0, min(1.0, t))
            cx, cy = x1 + t * dx, y1 + t * dy
            sq_dist = (px - cx) ** 2 + (py - cy) ** 2
            if best is None or sq_dist < best[0]:
                cross = dx * (py - y1) - dy * (px - x1)
                left_of = -1 if cross > 0 else (1 if cross < 0 else 0)
                best = (sq_dist, QgsPointXY(cx, cy), i + 1, left_of)
        if best is None:
            pt = QgsPointXY(px, py)
            return 0.0, pt, 0, 0
        return best

    def __repr__(self) -> str:
        return f"QgsGeometry({self._geom!r})"
