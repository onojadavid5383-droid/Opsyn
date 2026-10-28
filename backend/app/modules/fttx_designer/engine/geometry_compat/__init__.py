"""QGIS-free replacements for the small subset of qgis.core/qgis.analysis
that the ported FTTx pipeline (``FTTx Designer — dual PON integrated.py``)
actually calls, backed by Shapely/pyproj/plain-Python graph structures. See
each submodule's docstring for exactly which QGIS symbols it replaces and
why, and the integration plan (§4) for the full API-surface replacement
table this package implements.

Ported pipeline modules import from here instead of ``qgis.core`` /
``qgis.analysis`` — e.g.::

    from app.modules.fttx_designer.engine.geometry_compat import (
        QgsGeometry, QgsPointXY, QgsSpatialIndex, QgsFeature,
    )

instead of::

    from qgis.core import QgsGeometry, QgsPointXY, QgsSpatialIndex, QgsFeature
"""

from .crs import QgsCoordinateReferenceSystem, QgsCoordinateTransform
from .geometry import QgsGeometry, QgsPointXY, QgsRectangle, QgsWkbTypes
from .graph import (
    QgsGraph,
    QgsGraphAnalyzer,
    QgsGraphBuilder,
    QgsGraphEdge,
    QgsGraphVertex,
)
from .spatial_index import QgsFeature, QgsSpatialIndex
from .vector_layer import QgsField, QgsFeatureRequest, QgsFields, QgsVectorLayer


class Qgis:
    """Small compatibility namespace for QGIS enum values used by the engine."""

    class WkbType:
        Point = "Point"
        MultiPoint = "MultiPoint"

__all__ = [
    "QgsCoordinateReferenceSystem",
    "QgsCoordinateTransform",
    "QgsGeometry",
    "QgsPointXY",
    "QgsRectangle",
    "QgsWkbTypes",
    "Qgis",
    "QgsGraph",
    "QgsGraphAnalyzer",
    "QgsGraphBuilder",
    "QgsGraphEdge",
    "QgsGraphVertex",
    "QgsFeature",
    "QgsSpatialIndex",
    "QgsFeatureRequest",
    "QgsField",
    "QgsFields",
    "QgsVectorLayer",
]
