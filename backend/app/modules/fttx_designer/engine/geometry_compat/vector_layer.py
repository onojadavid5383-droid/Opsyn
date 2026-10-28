"""Minimal drop-in replacement for the subset of QgsVectorLayer / QgsFields /
QgsFeatureRequest the ported pipeline calls when reading INPUT layers
(roads, homepasses, poles, buildings, pickups): ``layer.getFeatures()``,
``layer.id()``, ``layer.crs()``, ``layer.fields().indexOf(name)``,
``feature.attribute(index_or_name)``.

Deliberate, flagged deviation from the integration plan
(§4.2's API-surface table, "QgsVectorLayer... recommend NOT shimming this
one... more naturally a `for row in gdf.itertuples()`"): that rewrite would
touch every function signature from topology.py through validation.py —
exactly the ~14,000 lines of tightly-coupled repair/rebalance logic
CLAUDE.md itself warns is the highest-regression-risk part of this port
(the source repo's own CLAUDE.md: "repair/ is deliberately its own
subpackage... tells future maintainers these three files change together or
not at all"). A thin QgsVectorLayer-shaped adapter keeps that risk
contained: pipeline modules keep their original
``for feat in layer.getFeatures(): ...`` bodies verbatim, and only the
actual I/O boundary (Phase 5's upload/input_validation.py, which will build
a QgsVectorLayer from an uploaded file's parsed rows) needs to know a real
QGIS data provider is no longer involved.

Deliberately NOT built as a generic GeoDataFrame-backed layer here — this
module has no geopandas dependency. Phase 5's upload code is expected to
call ``QgsVectorLayer.from_records()`` after it has already parsed an
uploaded file into plain Python values; that keeps this compatibility layer
dependency-light and keeps "how do we parse a Shapefile/GeoJSON/GeoPackage
upload" a Phase 5 concern, not a Phase 2 one.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

from .crs import QgsCoordinateReferenceSystem
from .geometry import QgsGeometry, QgsRectangle
from .spatial_index import QgsFeature


class QgsField:
    """Drop-in replacement for the subset of qgis.core.QgsField used
    (``.name()``, read when a pipeline function iterates ``layer.fields()``
    to search for a field by name, e.g. RoadTopologyEngine's OSM highway
    field detection)."""

    __slots__ = ("_name",)

    def __init__(self, name: str):
        self._name = name

    def name(self) -> str:
        return self._name


class QgsFields:
    """Drop-in replacement for the subset of qgis.core.QgsFields used
    (``.indexOf(name)`` for the ``field_idx >= 0`` pattern seen throughout
    the source script, plus iteration yielding ``QgsField`` objects)."""

    def __init__(self, names: Sequence[str] = ()):
        self._names: List[str] = list(names)

    def indexOf(self, name: str) -> int:
        try:
            return self._names.index(name)
        except ValueError:
            return -1

    def names(self) -> List[str]:
        return list(self._names)

    def __len__(self) -> int:
        return len(self._names)

    def __iter__(self) -> Iterator[QgsField]:
        return iter(QgsField(n) for n in self._names)


class QgsFeatureRequest:
    """Drop-in replacement for the subset of qgis.core.QgsFeatureRequest
    used: ``.setFilterFid(fid)`` (consumed by SpatialIndexManager
    .nearest_neighbor()) and the ``QgsFeatureRequest(fid)`` constructor
    shorthand for the same thing (used directly in closures.py)."""

    def __init__(self, fid: Optional[int] = None):
        self._filter_fid: Optional[int] = fid

    def setFilterFid(self, fid: int) -> "QgsFeatureRequest":
        self._filter_fid = fid
        return self

    def filterFid(self) -> Optional[int]:
        return self._filter_fid


class _QgsVectorDataProvider:
    """Minimal stand-in for the object ``QgsVectorLayer.dataProvider()``
    returns — only the one method the pipeline's OUTPUT-layer population
    functions call: ``.addFeatures([...])``. Auto-assigns sequential
    feature ids to any appended feature that doesn't already have one
    (mirroring a fresh QGIS memory-provider layer), matching the pattern
    used throughout ``populate_boq_layer``/``populate_boq_fdt_detail_layer``
    of building a bare ``QgsFeature(layer.fields())`` (id left at -1) and
    handing it straight to ``addFeatures``."""

    def __init__(self, layer: "QgsVectorLayer"):
        self._layer = layer

    def addFeatures(self, features: Sequence[QgsFeature]) -> tuple:
        for feat in features:
            if feat.id() < 0:
                feat.setId(len(self._layer._features))
            feat._bind_fields(self._layer._fields.names())
            self._layer._features.append(feat)
            self._layer._by_id[feat.id()] = feat
        return True, list(features)


class QgsVectorLayer:
    """Drop-in replacement for the subset of qgis.core.QgsVectorLayer used
    to read an input layer (roads/homepasses/poles/buildings/pickups):
    ``getFeatures()``, ``id()``, ``crs()``, ``fields()``, ``featureCount()``.

    Also supports the minimal OUTPUT-side editing surface the BOQ/output-
    layer population functions use: ``startEditing()``, ``dataProvider().
    addFeatures([...])``, ``commitChanges()``. There is no real edit-buffer/
    rollback concept here (``startEditing``/``commitChanges`` are no-ops
    that just preserve the source script's call shape) — appended features
    land in ``self._features`` immediately. Construct an initially-empty
    output layer via ``from_records([], field_names=[...])``, matching how
    the source script builds a fresh memory layer with a known schema
    before populating it.

    Not a general-purpose QGIS provider emulation — no real
    provider/datasource concepts, no signals. Construct an input layer via
    ``from_records()`` once at the pipeline's input boundary.
    """

    def __init__(
        self,
        features: Sequence[QgsFeature],
        field_names: Sequence[str] = (),
        crs: Optional[QgsCoordinateReferenceSystem] = None,
        layer_id: str = "",
    ):
        self._fields = QgsFields(field_names)
        for feat in features:
            feat._bind_fields(self._fields.names())
        self._features: List[QgsFeature] = list(features)
        self._by_id: Dict[int, QgsFeature] = {f.id(): f for f in self._features}
        self._crs = crs or QgsCoordinateReferenceSystem("EPSG:4326")
        self._id = layer_id or f"layer_{id(self)}"

    @staticmethod
    def from_records(
        records: Iterable[Dict[str, Any]],
        geometry_field: str = "geometry",
        field_names: Optional[Sequence[str]] = None,
        crs: Optional[QgsCoordinateReferenceSystem] = None,
        layer_id: str = "",
    ) -> "QgsVectorLayer":
        """Build a layer from plain dict rows, each holding a ``QgsGeometry``
        under ``geometry_field`` plus arbitrary attribute keys. Feature ids
        are assigned sequentially (0-based), matching a freshly-loaded QGIS
        layer with no persisted feature ids of its own."""
        records = list(records)
        if field_names is None:
            names: List[str] = []
            seen = set()
            for rec in records:
                for key in rec:
                    if key != geometry_field and key not in seen:
                        seen.add(key)
                        names.append(key)
            field_names = names

        features: List[QgsFeature] = []
        for fid, rec in enumerate(records):
            feat = QgsFeature(fid)
            geom = rec.get(geometry_field)
            if geom is not None:
                feat.setGeometry(geom)
            for name in field_names:
                feat.setAttribute(name, rec.get(name))
            features.append(feat)

        return QgsVectorLayer(features, field_names=field_names, crs=crs, layer_id=layer_id)

    def getFeatures(self, request: Optional[QgsFeatureRequest] = None) -> Iterator[QgsFeature]:
        if request is not None and request.filterFid() is not None:
            feat = self._by_id.get(request.filterFid())
            return iter([feat] if feat is not None else [])
        return iter(self._features)

    def id(self) -> str:
        return self._id

    def name(self) -> str:
        """Real QGIS distinguishes an internal `.id()` from a user-facing
        `.name()`; this compat layer only ever tracks one identifier per
        layer (`layer_id`), so `.name()` returns the same value — sufficient
        for the handful of call sites that use it only to label an error
        message, never for lookup."""
        return self._id

    def crs(self) -> QgsCoordinateReferenceSystem:
        return self._crs

    def fields(self) -> QgsFields:
        return self._fields

    def featureCount(self) -> int:
        return len(self._features)

    def startEditing(self) -> bool:
        return True

    def commitChanges(self) -> bool:
        return True

    def extent(self) -> "QgsRectangle":
        """Bounding box over every feature's geometry. Computed live from
        ``self._features`` rather than cached — this shim has no separate
        extent cache to keep in sync, so ``updateExtents()`` (below) is a
        no-op; a real QGIS layer caches its extent and needs that call
        after bulk feature writes, which is why callers still call it."""
        xmin = ymin = float("inf")
        xmax = ymax = float("-inf")
        for feat in self._features:
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            bb = geom.boundingBox()
            xmin = min(xmin, bb.xMinimum())
            ymin = min(ymin, bb.yMinimum())
            xmax = max(xmax, bb.xMaximum())
            ymax = max(ymax, bb.yMaximum())
        if xmin > xmax:
            return QgsRectangle(0.0, 0.0, 0.0, 0.0)
        return QgsRectangle(xmin, ymin, xmax, ymax)

    def updateExtents(self) -> None:
        return None

    def addFeature(self, feature: QgsFeature) -> bool:
        """Real QGIS's single-feature edit-session counterpart to
        ``dataProvider().addFeatures([...])`` — used by
        ``_build_underground_boq``/``_build_drainage_boq``, which add BOQ
        rows one at a time inside a ``startEditing()``/``commitChanges()``
        block rather than batching a features list."""
        ok, _ = self.dataProvider().addFeatures([feature])
        return ok

    def dataProvider(self) -> "_QgsVectorDataProvider":
        return _QgsVectorDataProvider(self)
