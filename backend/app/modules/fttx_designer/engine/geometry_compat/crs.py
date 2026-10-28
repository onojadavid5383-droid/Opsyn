"""pyproj-backed adapter for the subset of QgsCoordinateReferenceSystem /
QgsCoordinateTransform the source script uses — CRS handling there is
already isolated to layer load/validation and the single
`processing.run("native:reprojectlayer", ...)` call site (the integration
plan's §4.2/§4.3), both of which are rewritten directly against
`geopandas.GeoDataFrame.to_crs()` rather than routed through this shim. This
module exists for the handful of call sites that construct/compare/transform
CRS objects independently of a layer (e.g. UTM-zone selection for
metre-accurate distance math).
"""

from __future__ import annotations

from typing import Optional

import pyproj

from .geometry import QgsPointXY


class QgsCoordinateReferenceSystem:
    """Drop-in replacement for the subset of
    qgis.core.QgsCoordinateReferenceSystem used (construction from an
    authid/WKT string, `.authid()`, `.isValid()`, equality)."""

    def __init__(self, definition: str = "EPSG:4326"):
        self._input = definition
        self._crs: Optional[pyproj.CRS] = None
        if definition:
            try:
                self._crs = pyproj.CRS.from_user_input(definition)
            except pyproj.exceptions.CRSError:
                self._crs = None

    def authid(self) -> str:
        if self._crs is None:
            return ""
        epsg = self._crs.to_epsg()
        return f"EPSG:{epsg}" if epsg is not None else self._input

    def isValid(self) -> bool:
        return self._crs is not None

    def isGeographic(self) -> bool:
        return self._crs is not None and self._crs.is_geographic

    def toWkt(self) -> str:
        return self._crs.to_wkt() if self._crs is not None else ""

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, QgsCoordinateReferenceSystem)
            and self._crs is not None
            and other._crs is not None
            and self._crs == other._crs
        )

    def __repr__(self) -> str:
        return f"QgsCoordinateReferenceSystem({self.authid()!r})"


class QgsCoordinateTransform:
    """Drop-in replacement for the subset of
    qgis.core.QgsCoordinateTransform used (point-by-point transform between
    two CRSes)."""

    def __init__(
        self,
        source: QgsCoordinateReferenceSystem,
        dest: QgsCoordinateReferenceSystem,
        context: object = None,
    ):
        self._transformer = pyproj.Transformer.from_crs(
            source._crs, dest._crs, always_xy=True
        )

    def transform(self, point: QgsPointXY) -> QgsPointXY:
        x, y = self._transformer.transform(point.x(), point.y())
        return QgsPointXY(x, y)
