"""Port of the source script's ``SpatialIndexManager`` and
``DistanceCalculator`` — cross-cutting utilities threaded as parameters
(``index_mgr``, ``dist_calc``) through nearly every pipeline module from
``topology.py`` onward (confirmed by grep: ``dist_calc.distance_points`` is
called from over 60 call sites spanning FAT generation through validation).

One deliberate change from the source, called out explicitly: the original
``DistanceCalculator.__init__`` constructs a ``QgsDistanceArea`` and calls
``setSourceCrs()``/``setEllipsoid()`` on it, but that object is never read
anywhere afterward — ``distance()``/``distance_points()``/
``distance_along_road()`` all use the documented "rough conversion" shortcut
(``* 111320``) instead of a real ellipsoidal measurement. That setup was
dead code even in the original QGIS script (verified by grepping every
``distance_area.`` reference — both hits are inside ``__init__`` itself), so
it is dropped here rather than routed through a ``QgsDistanceArea`` shim
that would do nothing. No behavior change.
"""

from __future__ import annotations

import math
from typing import Dict, Optional

from .geometry_compat import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsPointXY,
    QgsSpatialIndex,
    QgsVectorLayer,
)


class SpatialIndexManager:
    """Manages spatial indices for all layers"""

    def __init__(self):
        self.indices: Dict[str, QgsSpatialIndex] = {}
        self.geometries: Dict[str, Dict[int, QgsGeometry]] = {}

    def build_index(self, layer: QgsVectorLayer, cache_geoms: bool = True) -> QgsSpatialIndex:
        """Build spatial index for a layer with optional geometry caching"""
        index = QgsSpatialIndex()
        geoms = {}

        features = layer.getFeatures()
        for feat in features:
            geom = feat.geometry()
            if geom and not geom.isEmpty():
                index.addFeature(feat)
                if cache_geoms:
                    geoms[feat.id()] = geom

        self.indices[layer.id()] = index
        if cache_geoms:
            self.geometries[layer.id()] = geoms

        return index

    def get_index(self, layer: QgsVectorLayer) -> QgsSpatialIndex:
        """Get or create spatial index for layer"""
        if layer.id() not in self.indices:
            return self.build_index(layer)
        return self.indices[layer.id()]

    def get_geometry(self, layer: QgsVectorLayer, fid: int) -> Optional[QgsGeometry]:
        """Get cached geometry for feature"""
        if layer.id() in self.geometries:
            return self.geometries[layer.id()].get(fid)
        return None

    def nearest_neighbor(
        self,
        layer: QgsVectorLayer,
        point: QgsPointXY,
        max_distance: Optional[float] = None,
    ) -> Optional[QgsFeature]:
        """Find nearest feature in layer to point"""
        index = self.get_index(layer)
        nearest_ids = index.nearestNeighbor(point, 1, max_distance)

        if nearest_ids:
            fid = nearest_ids[0]
            request = QgsFeatureRequest().setFilterFid(fid)
            feat = next(layer.getFeatures(request))
            return feat
        return None


class DistanceCalculator:
    """Handles distance calculations with CRS awareness"""

    def __init__(self, crs: QgsCoordinateReferenceSystem):
        self.crs = crs

    def distance(self, geom1: QgsGeometry, geom2: QgsGeometry) -> float:
        """Calculate distance between geometries in meters"""
        if not geom1 or not geom2:
            return float('inf')

        # If CRS is geographic, transform to meters for distance
        if self.crs.isGeographic():
            return geom1.distance(geom2) * 111320  # Rough conversion
        else:
            return geom1.distance(geom2)

    def distance_points(self, point1: QgsPointXY, point2: QgsPointXY) -> float:
        """Calculate distance between points. Fast path for projected CRS."""
        if not self.crs.isGeographic():
            dx = point2.x() - point1.x()
            dy = point2.y() - point1.y()
            return math.sqrt(dx * dx + dy * dy)
        return self.distance(
            QgsGeometry.fromPointXY(point1),
            QgsGeometry.fromPointXY(point2)
        )

    def distance_along_road(self, road_geom: QgsGeometry,
                             point1: QgsPointXY, point2: QgsPointXY) -> float:
        """Calculate distance along road geometry"""
        # Project points to road
        point1_proj = road_geom.nearestPoint(QgsGeometry.fromPointXY(point1))
        point2_proj = road_geom.nearestPoint(QgsGeometry.fromPointXY(point2))

        # Get distances along line. lineLocatePoint() already returns an
        # absolute chainage in the geometry's CRS units (metres here), not a
        # normalized 0-1 fraction — do not multiply by road_geom.length()
        # again (that squared every FAT-to-FAT cascade distance).
        dist1 = road_geom.lineLocatePoint(point1_proj)
        dist2 = road_geom.lineLocatePoint(point2_proj)

        # Return difference
        return abs(dist2 - dist1)
