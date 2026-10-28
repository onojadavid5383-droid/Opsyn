"""rtree-backed adapter for the subset of QgsSpatialIndex / QgsFeature the
ported pipeline calls: ``QgsFeature(id)`` + ``.setGeometry()``,
``index.addFeature(feature)`` / ``index.insertFeature(feature)``,
``index.nearestNeighbor(point_or_geom, n, maxDistance=0)`` and
``index.intersects(rectangle)``, both returning lists of feature ids.

Performance history — this WAS a brute-force O(n) linear scan (both
methods), exactly as the module docstring used to warn: "swap in `rtree`
during Phase 6 load testing if profiling shows this is a bottleneck at
100k-homepass scale." Phase 6 load testing did exactly that: a 360-homepass
/ 60-road synthetic grid — a trivially small dataset by the script's own
"100,000+ homepass" design target — took 21+ seconds in
``assign_homepasses_to_roads()`` alone. Profiling (cProfile) showed the
entire cost was ``intersects()``: 108,000 calls (360 homepasses × 5
candidate roads × 60 roads scanned per call) each rebuilding a fresh
Shapely ``box()`` polygon from scratch and running a full precise
``.intersects()`` geometry op against it, when the caller
(``_line_intersects_other_roads`` in homepass_assignment.py) only ever
wanted a cheap BOUNDING-BOX candidate prefilter before its own exact
``crosses()`` check — which is exactly what real QGIS's own
``QgsSpatialIndex.intersects(rectangle)`` documents itself as (a
bounding-box query, not an exact-geometry one). ``nearestNeighbor()``
wasn't the bottleneck at this tier (only 360 calls, ~0.7s), but brute-force
distance-sorting against every indexed feature is O(homepasses × features)
and would dominate instead at real 100k-homepass scale.

Now backed by the `rtree` package (libspatialindex R-tree bindings, already
suggested as the fallback in the code this replaces):
  - ``intersects()`` is now an exact bounding-box query against the tree —
    O(log n + k), and more faithful to real QGIS's own documented
    bbox-only contract than the previous exact-geometry check was.
  - ``nearestNeighbor()`` uses the tree's own bbox-distance ``nearest()``
    query to fetch a generously oversized candidate pool (bbox distance is
    a lower bound on true geometry distance, so a wide-enough pool
    reliably contains the true k-nearest for the road/pole/FDT-density
    datasets this pipeline works on), then ranks that pool by the SAME
    exact Shapely distance the original brute-force version used — so the
    "Fidelity fix" below (never collapse a line to its centroid) is fully
    preserved, just no longer computed against every feature in the index.

Every ``addFeature``/``insertFeature`` call site across the ported engine
was audited (grep across engine/*.py) and always uses a strictly
incrementing, never-reused feature id — so treating insertion as
append-only (no id-collision/update-in-place handling) is safe; `rtree`
itself allows duplicate ids but has no upsert semantics, which would
silently corrupt a query if some caller ever *did* re-add an id to move it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union

import rtree.index

from .geometry import QgsGeometry, QgsPointXY, QgsRectangle


class _BoundFieldNames:
    """Minimal ``QgsFields``-shaped view over a feature's own bound field
    names, returned by ``QgsFeature.fields()``. The real ``QgsFields`` type
    lives in ``vector_layer.py``, which imports ``QgsFeature`` from this
    module — importing it back here would be circular — so this is a
    small, self-contained duplicate of just the ``.names()``/``.indexOf()``
    surface a bound feature's own field list needs (e.g.
    ``'name' in feat.fields().names()`` in closures.py's pickup lookup)."""

    __slots__ = ("_names",)

    def __init__(self, names: Sequence[str]):
        self._names = list(names)

    def names(self) -> List[str]:
        return list(self._names)

    def indexOf(self, name: str) -> int:
        try:
            return self._names.index(name)
        except ValueError:
            return -1

    def __len__(self) -> int:
        return len(self._names)

    def __iter__(self):
        return iter(self._names)


class QgsFeature:
    """Drop-in replacement for the subset of qgis.core.QgsFeature used both
    as a carrier object for QgsSpatialIndex insertion (``QgsFeature(id)`` +
    ``.setGeometry()`` + ``.id()``) and for reading input-layer attributes
    (``feature.attribute(index_or_name)``, matching QGIS's own dual
    int-index/str-name overload).

    Also supports the OUTPUT-side constructor form used throughout the
    BOQ/output-layer population functions: ``QgsFeature(layer.fields())``
    (binds the feature to that field schema immediately, matching real
    QGIS) followed by ``.setAttributes([...])`` (positional, by that bound
    field order) — the write-side counterpart of ``.setAttribute(name,
    value)``/``.attribute(index_or_name)`` above.
    """

    def __init__(self, id_or_fields: Optional[Any] = None):
        self._id = id_or_fields if isinstance(id_or_fields, int) else -1
        self._geometry: Optional[QgsGeometry] = None
        self._attributes: Dict[str, object] = {}
        # Set by QgsVectorLayer when this feature is read from a layer, or
        # immediately here when constructed as ``QgsFeature(a_QgsFields)``,
        # so that integer-index attribute() calls (`feat.attribute(3)`)
        # resolve against that layer's field order — QGIS features are
        # never handed out except already bound to their layer's fields.
        self._field_names: Optional[Sequence[str]] = None
        if not isinstance(id_or_fields, int) and id_or_fields is not None:
            names_method = getattr(id_or_fields, "names", None)
            if callable(names_method):
                self._field_names = list(names_method())

    def setGeometry(self, geometry: QgsGeometry) -> None:
        self._geometry = geometry

    def geometry(self) -> Optional[QgsGeometry]:
        return self._geometry

    def setId(self, fid: int) -> None:
        self._id = fid

    def id(self) -> int:
        return self._id

    def setAttribute(self, name: str, value: object) -> None:
        self._attributes[name] = value

    def setAttributes(self, values: Sequence[object]) -> None:
        """Positional attribute assignment against this feature's bound
        field order — requires construction via ``QgsFeature(a_QgsFields)``
        (or a prior ``_bind_fields()`` call), matching real QGIS's own
        requirement that a feature be bound to a field schema before
        positional attribute access is meaningful."""
        if not self._field_names:
            raise ValueError(
                "setAttributes() requires a feature bound to a field schema "
                "— construct via QgsFeature(layer.fields())"
            )
        for name, value in zip(self._field_names, values):
            self._attributes[name] = value

    def attributes(self) -> List[object]:
        """Positional attribute list in the feature's bound field order —
        the read-side counterpart of ``setAttributes()``, used by callers
        that index into it directly (e.g. ``_classify_road_zones``'s
        ``feat.attributes()[field_idx]``). Requires a bound feature, same
        as ``setAttributes()``."""
        if not self._field_names:
            return []
        return [self._attributes.get(name) for name in self._field_names]

    def attribute(self, key: Union[int, str]) -> object:
        if isinstance(key, int):
            if not self._field_names or not (0 <= key < len(self._field_names)):
                return None
            key = self._field_names[key]
        return self._attributes.get(key)

    def fields(self) -> "_BoundFieldNames":
        return _BoundFieldNames(self._field_names or [])

    def _bind_fields(self, field_names: Sequence[str]) -> None:
        """Not part of the QGIS API — called by QgsVectorLayer to enable
        integer-index attribute() lookups."""
        self._field_names = field_names

    def __getitem__(self, name: str) -> object:
        """QGIS features support dict-style attribute access
        (``feature['field_name']``), raising KeyError for a missing field —
        matches the source script's ``safe_homepass_sum``, which relies on
        that KeyError being caught."""
        if name not in self._attributes:
            raise KeyError(name)
        return self._attributes[name]


class QgsSpatialIndex:
    """Drop-in replacement for the subset of qgis.core.QgsSpatialIndex used
    throughout the pipeline for nearest-neighbor / bbox-candidate lookups.
    Backed by an in-memory ``rtree.index.Index`` — see the module
    docstring for why (Phase 6 load testing) and how (bbox prefilter +
    exact-distance rank) this replaces the previous brute-force scan."""

    # Minimum bbox candidate pool requested from the tree per
    # nearestNeighbor() call, even when `neighbors` itself is small — a
    # too-small pool risks the bbox-distance prefilter missing the true
    # nearest feature when several candidates' bounding boxes are close
    # together (common at road junctions). 20 is a generous margin for the
    # small `neighbors` values (1-25) actually used across this engine.
    _MIN_CANDIDATE_POOL = 20

    def __init__(self):
        self._features: Dict[int, QgsFeature] = {}
        self._rtree = rtree.index.Index()

    def addFeature(self, feature: QgsFeature) -> bool:
        fid = feature.id()
        self._features[fid] = feature
        geom = feature.geometry()
        if geom is not None and not geom.isEmpty():
            self._rtree.insert(fid, geom._geom.bounds)
        return True

    # QGIS exposes both names for the same operation.
    insertFeature = addFeature

    def nearestNeighbor(
        self,
        point_or_geom: Union[QgsPointXY, QgsGeometry],
        neighbors: int = 1,
        maxDistance: float = 0,
    ) -> List[int]:
        if not self._features:
            return []
        # Fidelity fix (unchanged from the brute-force version): real
        # QgsSpatialIndex.nearestNeighbor ranks candidate features by true
        # distance to their actual geometry, never by collapsing a line to
        # its centroid first (see the long-form explanation this comment
        # used to carry — still true, just no longer the whole algorithm).
        query_geom = (
            QgsGeometry.fromPointXY(point_or_geom)
            if isinstance(point_or_geom, QgsPointXY)
            else point_or_geom
        )
        n = max(int(neighbors), 1)

        # Bounding-box prefilter: the tree ranks by bbox-to-bbox distance,
        # which is always <= true geometry distance, so a generously
        # oversized pool reliably contains the true k-nearest without
        # having to touch every feature in the index.
        pool_size = min(len(self._features), max(n * 4, self._MIN_CANDIDATE_POOL))
        candidate_fids = self._rtree.nearest(query_geom._geom.bounds, num_results=pool_size)

        scored: List[tuple] = []
        for fid in candidate_fids:
            feat = self._features.get(fid)
            if feat is None:
                continue
            geom = feat.geometry()
            if geom is None:
                continue
            dist = geom.distance(query_geom)
            if maxDistance and dist > maxDistance:
                continue
            scored.append((dist, fid))
        scored.sort(key=lambda t: t[0])
        return [fid for _dist, fid in scored[:n]]

    def intersects(self, rectangle: QgsRectangle) -> List[int]:
        if not self._features:
            return []
        bounds = (
            rectangle.xMinimum(), rectangle.yMinimum(),
            rectangle.xMaximum(), rectangle.yMaximum(),
        )
        return list(self._rtree.intersection(bounds))
