"""Verbatim port of the dome-closure stage from
``FTTx Designer — dual PON integrated.py``: ``classify_length``,
``generate_core_list``, ``compute_closure_service_zones`` (no-op, retained
for API compatibility), ``enforce_closure_zone_membership`` (no-op, ditto),
``_cluster_fdts``, ``_cluster_closures``, ``_generate_pickup_points``
(all three deferred from the topology sub-phase — needed only here),
``_equalise_closure_fdts``, ``generate_closures``,
``correct_cable_zone_violations``, ``route_pickup_to_closure``.

No logic changes from the source script — only the QGIS types and
cross-module imports.

``route_closure_to_fdts`` is the one exception: its "shared-graph Dijkstra
per closure" strategy relied directly on
``QgsVectorLayerDirector.makeGraph()`` (the same API ``CableRouter`` used
before being rewritten in the cable_routing.py sub-phase). Rather than
re-deriving that logic a second time, it now calls the same
``cable_routing._build_tied_graph()`` this port already built and verified
for exactly this purpose — one closure point plus every FDT point tied in
as exact graph vertices, one Dijkstra pass from the closure vertex serving
every FDT. The path-reconstruction and cable-building logic that follows is
unchanged.

Note: ``MAX_BOX_TO_BOX_DISTANCE`` and ``DROP_LENGTH_TOLERANCE`` are 2 of the
8 tunables the pipeline overrides per-run (see runtime_config.py's
docstring) — every direct reference reads ``runtime_config.X``.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from . import runtime_config as rc
from .cable_routing import CableRouter, _build_tied_graph
from .cascade import _project_tag
from .config import (
    CAPACITY_PROFILES,
    CLOSURE_LARGE_CAPACITY,
    CLOSURE_SMALL_CAPACITY,
    CLOSURES_PER_PICKUP,
    MAX_FDT_PER_8CORE,
    CapacityProfile,
    PONArchitecture,
    _closure_size_for,
    _core_color,
)
from .domain import CableSegment, DomeClosure, FDT, RoadSegment
from .errors import ValidationError
from .geometry_compat import (
    QgsFeatureRequest,
    QgsGeometry,
    QgsGraphAnalyzer,
    QgsPointXY,
    QgsSpatialIndex,
    QgsVectorLayer,
    QgsWkbTypes,
)
from .perf_logger import PerformanceLogger
from .spatial_utils import DistanceCalculator, SpatialIndexManager
from .topology import _dedupe_points, _road_vertices

try:
    from sklearn.cluster import KMeans
except Exception:
    # Minimal, deterministic KMeans fallback when scikit-learn is not installed.
    import numpy as np

    class KMeans:
        def __init__(self, n_clusters=8, random_state=None, n_init=10, max_iter=300):
            self.n_clusters = n_clusters
            self.random_state = random_state
            self.n_init = n_init
            self.max_iter = max_iter
            self.cluster_centers_ = None

        def fit_predict(self, X):
            X = np.asarray(X, dtype=float)
            n_samples = X.shape[0]
            k = int(self.n_clusters)

            rng = np.random.RandomState(self.random_state)
            best_inertia = None
            best_labels = None
            best_centers = None

            n_init = max(1, int(self.n_init))
            for _ in range(n_init):
                if n_samples >= k:
                    indices = rng.choice(n_samples, k, replace=False)
                else:
                    indices = rng.choice(n_samples, k, replace=True)
                centers = X[indices].astype(float).copy()

                for _ in range(int(self.max_iter)):
                    dists = np.linalg.norm(X[:, None, :] - centers[None, :, :], axis=2)
                    labels = np.argmin(dists, axis=1)

                    new_centers = np.array([
                        X[labels == ci].mean(axis=0) if np.any(labels == ci) else centers[ci]
                        for ci in range(k)
                    ])

                    if np.allclose(new_centers, centers):
                        break
                    centers = new_centers

                inertia = np.sum((X - centers[labels]) ** 2)
                if best_inertia is None or inertia < best_inertia:
                    best_inertia = inertia
                    best_labels = labels
                    best_centers = centers

            self.cluster_centers_ = best_centers
            return best_labels


def classify_length(length: float) -> int:
    """Standardize cable length to procurement bucket."""
    if length <= 9:
        return 10
    if 10 <= length <= 45:
        return 50
    if 46 <= length <= 96:
        return 100
    if 97 <= length <= 145:
        return 150
    return 150


def generate_core_list(capacity: int) -> List[Tuple[str, int, str]]:
    """Return ordered list of (buffer_color, core_number, core_color) triples
    for a cable.

    The function respects the buffer/core examples given in the requirements.
    For a 48-core feed there are four buffers (Blue, Orange, Green, Brown)
    with 12 cores each. For a 24-core feed we use the first two buffers
    Blue/Orange with 12 cores each. ``core_color`` is the core's true fibre
    colour (TIA/EIA-598-C 12-colour code, via _core_color()) — distinct from
    ``core_number``, its 1-based position within the buffer.
    """
    if capacity not in (CLOSURE_SMALL_CAPACITY, CLOSURE_LARGE_CAPACITY):
        raise ValidationError(f"Unsupported closure capacity {capacity}")
    if capacity == CLOSURE_SMALL_CAPACITY:
        buffers = ["Blue", "Orange"]
    else:
        buffers = ["Blue", "Orange", "Green", "Brown"]
    cores_per_buffer = capacity // len(buffers)
    cores = []
    for buf in buffers:
        for num in range(1, cores_per_buffer + 1):
            cores.append((buf, num, _core_color(num)))
    return cores


# -------------------------------------------------------------------------
# Closure zone helpers
# -------------------------------------------------------------------------

def compute_closure_service_zones(closures: List[DomeClosure]) -> None:
    """No-op: zone_geometry is now computed inside generate_closures from the
    K-Means cluster's convex hull, so no post-hoc Voronoi is needed.
    Retained for API compatibility."""
    pass


def enforce_closure_zone_membership(closures: List[DomeClosure],
                                    fdts: List[FDT],
                                    dist_calc: DistanceCalculator,
                                    logger: PerformanceLogger) -> None:
    """No-op: FDT cluster membership is definitive from _cluster_fdts().
    The K-Means clusters are the zones — no Voronoi reassignment is performed.
    Retained for API compatibility."""
    pass


def _cluster_fdts(fdts: List[FDT],
                  max_per_cluster: int,
                  dist_calc: DistanceCalculator) -> List[List[FDT]]:
    """Divide FDTs into equal, geographically compact regions for closure assignment.

    Design principle (matches reference images)
    ───────────────────────────────────────────
    Each closure controls one contiguous geographic region of streets.
    FDTs close to each other (on the same or nearby roads) stay together.
    All regions should contain approximately the same number of FDTs.

    Algorithm
    ---------
    Step 1 — Determine k (number of closures):
        k = ceil(N / target) where target = round(max_per_cluster * 0.75).
        This produces fuller clusters — matching the images where each of
        the 3 closures serves ~15-20 FDTs rather than 5 half-empty ones.

    Step 2 — K-Means on FDT coordinates:
        Standard K-Means finds k spatially compact centroids.
        Each FDT is assigned to its nearest centroid.

    Step 3 — Balanced reallocation:
        Move border FDTs between clusters until sizes are within ±1 of N/k.
        "Border FDT" = the FDT in the larger cluster that is closest to the
        smaller cluster's centroid AND within a geographic distance limit
        (prevents cross-city moves that destroy zone compactness).
        The distance limit is the diameter of a cluster of max_per_cluster
        FDTs at typical 250m road spacing = max_per_cluster * 250 / 2 m.

    Step 4 — Hard-cap overflow split:
        Any cluster still over max_per_cluster is chunked into extra clusters.

    Returns list of FDT lists (one per cluster/closure).
    """
    import numpy as np

    n = len(fdts)
    if n == 0:
        return []
    if n <= max_per_cluster:
        return [fdts[:]]

    # ── Step 1: number of clusters ────────────────────────────────────────────
    target_per = max(1, round(max_per_cluster * 0.75))   # ~18 for cap=24
    k = max(2, math.ceil(n / target_per))
    k = min(k, n)

    # ── Step 2: K-Means ───────────────────────────────────────────────────────
    coords = np.array([[f.geometry.x(), f.geometry.y()] for f in fdts],
                      dtype=float)
    km = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=500)
    labels = km.fit_predict(coords)

    clusters: List[List[FDT]] = [[] for _ in range(k)]
    for fdt, label in zip(fdts, labels):
        clusters[label].append(fdt)
    clusters = [c for c in clusters if c]
    k = len(clusters)
    if k == 0:
        return [fdts[:]]

    # ── Step 3: balanced reallocation ─────────────────────────────────────────
    # Distance limit: half the expected diameter of a full cluster.
    # This remains Euclidean because it is only a pre-clustering heuristic
    # for balancing cluster sizes before final ownership assignment.
    geo_limit = (max_per_cluster * rc.MAX_BOX_TO_BOX_DISTANCE) / 2.0

    def _ctr(cl: List[FDT]) -> QgsPointXY:
        cx = sum(f.geometry.x() for f in cl) / len(cl)
        cy = sum(f.geometry.y() for f in cl) / len(cl)
        return QgsPointXY(cx, cy)

    for _ in range(n * 4):
        sizes   = [len(c) for c in clusters]
        max_sz  = max(sizes)
        min_sz  = min(sizes)
        if max_sz - min_sz <= 1 and max_sz <= max_per_cluster:
            break

        big_idx   = sizes.index(max_sz)
        small_idx = sizes.index(min_sz)
        if big_idx == small_idx:
            break

        big_cl   = clusters[big_idx]
        small_cl = clusters[small_idx]
        small_c  = _ctr(small_cl)

        # Find closest border FDT in the big cluster within distance limit
        best, best_d = None, float('inf')
        for fdt in big_cl:
            d = dist_calc.distance_points(fdt.geometry, small_c)
            if d < best_d and d <= geo_limit:
                best_d, best = d, fdt

        if best is None:
            break  # no valid candidate — accept imbalance

        big_cl.remove(best)
        small_cl.append(best)

    # ── Step 4: enforce hard cap ──────────────────────────────────────────────
    final: List[List[FDT]] = []
    for cl in clusters:
        if not cl:
            continue
        cl.sort(key=lambda f: (round(f.geometry.x(), 6), round(f.geometry.y(), 6)))
        for i in range(0, len(cl), max_per_cluster):
            chunk = cl[i:i + max_per_cluster]
            if chunk:
                final.append(chunk)

    return final


def _cluster_closures(closures: List[DomeClosure],
                      max_per_cluster: int,
                      dist_calc: DistanceCalculator) -> List[List[DomeClosure]]:
    """Greedy geographic clustering of dome closures.

    Same algorithm used for FDTs but operating on closures.
    """
    clusters: List[List[DomeClosure]] = []
    remaining = closures.copy()
    remaining.sort(key=lambda c: (round(c.geometry.x(), 6), round(c.geometry.y(), 6)))

    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        remaining.sort(key=lambda c: dist_calc.distance_points(seed.geometry, c.geometry))
        while remaining and len(cluster) < max_per_cluster:
            cluster.append(remaining.pop(0))
        clusters.append(cluster)
    return clusters


def _generate_pickup_points(closures: List[DomeClosure],
                            roads: Dict[int, RoadSegment],
                            road_index: QgsSpatialIndex,
                            dist_calc: DistanceCalculator,
                            logger: PerformanceLogger) -> List[QgsPointXY]:
    """Automatically generate one pickup point per closure group.

    Each pickup is placed at the road point nearest to the centroid of its
    closure group.  Uses nearestPoint() (same method as all other road-snapping
    in the script) so the result is always a valid road-geometry point that
    Dijkstra can reach without falling back to a straight line.
    """
    if not closures:
        return []

    num_clusters = max(1, math.ceil(len(closures) / CLOSURES_PER_PICKUP))
    clusters     = _cluster_closures(
        closures, math.ceil(len(closures) / num_clusters), dist_calc
    )

    generated: List[QgsPointXY] = []
    for ci, cluster in enumerate(clusters, start=1):
        if not cluster:
            continue

        # Centroid of this closure group
        cx       = sum(c.geometry.x() for c in cluster) / len(cluster)
        cy       = sum(c.geometry.y() for c in cluster) / len(cluster)
        centroid = QgsPointXY(cx, cy)

        # Snap to nearest road using nearestPoint() — consistent with rest of script
        pickup_pt = centroid
        if road_index:
            nearest = road_index.nearestNeighbor(centroid, 1)
            if nearest:
                road = roads.get(nearest[0])
                if road and road.geometry and not road.geometry.isEmpty():
                    snapped = road.geometry.nearestPoint(
                        QgsGeometry.fromPointXY(centroid)
                    )
                    if snapped and not snapped.isEmpty():
                        pickup_pt = snapped.asPoint()

        pickup_name = f"PICKUP_{ci}"
        generated.append(pickup_pt)
        for c in cluster:
            c.pickup_geometry = pickup_pt
            c.pickup_name     = pickup_name

    logger.log(f"Generated {len(generated)} automatic pickup point(s)")
    return generated


def _equalise_closure_fdts(closures: List[DomeClosure],
                           dist_calc: DistanceCalculator,
                           logger: PerformanceLogger,
                           tolerance: int = 3,
                           profile: Optional['CapacityProfile'] = None) -> None:
    """Rebalance FDT counts across closures after Voronoi zone enforcement.

    Moves border FDTs from overloaded closures to underloaded ones so that
    all closures end up within `tolerance` FDTs of each other.

    Geographic guard: an FDT is only eligible to move if its distance to the
    receiving closure is <= MAX_BOX_TO_BOX_DISTANCE * 4.  This prevents
    cross-city moves that destroy zone compactness.

    The tolerance is set to 3 by default — tighter balancing is counter-
    productive when geographic constraints prevent valid moves.
    """
    if len(closures) < 2:
        return

    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    hard_cap  = CLOSURE_LARGE_CAPACITY // profile.cores_per_fdt
    geo_limit = rc.MAX_BOX_TO_BOX_DISTANCE * 4   # 1000 m geographic guard
    n_total   = sum(c.total_fdt for c in closures)
    max_iters = n_total + 1

    def _ctr(c: DomeClosure) -> QgsPointXY:
        return c.snapped_geometry or c.geometry

    for iteration in range(max_iters):
        counts  = [c.total_fdt for c in closures]
        max_cnt = max(counts)
        min_cnt = min(counts)

        if max_cnt - min_cnt <= tolerance:
            break

        big   = closures[counts.index(max_cnt)]
        small = closures[counts.index(min_cnt)]

        if small.total_fdt >= hard_cap:
            break

        small_ctr = _ctr(small)

        # Only consider FDTs within geographic reach of the receiving closure
        best_fdt  = None
        best_dist = float('inf')
        for fdt in big.fdts:
            fdt_pt = fdt.snapped_geometry or fdt.geometry
            d = dist_calc.distance_points(fdt_pt, small_ctr)
            if d < best_dist and d <= geo_limit:
                best_dist = d
                best_fdt  = fdt

        if best_fdt is None:
            # No geographically valid FDT to move — accept this imbalance
            logger.log(
                f"Equalise: cannot reduce imbalance "
                f"({big.name}={big.total_fdt} vs {small.name}={small.total_fdt}) "
                f"— no FDT within {geo_limit:.0f}m geographic limit"
            )
            break

        big.fdts.remove(best_fdt)
        big.total_fdt   -= 1
        small.fdts.append(best_fdt)
        small.total_fdt += 1

        logger.log(
            f"Equalise iter {iteration+1}: {best_fdt.name} "
            f"{big.name}({big.total_fdt+1}→{big.total_fdt}) → "
            f"{small.name}({small.total_fdt-1}→{small.total_fdt}), "
            f"dist={best_dist:.0f}m"
        )

    # Refresh feed capacities
    for c in closures:
        c.feed_capacity = _closure_size_for(c.total_fdt, profile.cores_per_fdt)


def generate_closures(fdts: List[FDT],
                      pickup_layer: Optional[QgsVectorLayer],
                      index_mgr: SpatialIndexManager,
                      dist_calc: DistanceCalculator,
                      roads: Dict[int, RoadSegment],
                      road_index: QgsSpatialIndex,
                      building_layer: Optional[QgsVectorLayer],
                      logger: PerformanceLogger,
                      pole_layer: Optional[QgsVectorLayer] = None,
                      profile: Optional['CapacityProfile'] = None) -> List[DomeClosure]:
    """Cluster FDTs into equal geographic regions and create one closure per region.

    Pipeline
    ────────
    1. _cluster_fdts()  — balanced K-Means → k equal geographic clusters.
       The cluster IS the definitive zone.  No post-hoc Voronoi reassignment.

    2. For each cluster, place the closure at the road-junction pole nearest
       to the cluster centroid.  A junction pole is preferred because it is
       where cable arms naturally branch outward (as shown in the reference).

    3. Build a convex-hull zone geometry from the cluster's FDT points so that
       correct_cable_zone_violations can detect genuine misassignments caused
       by snapping.  This zone is NOT used to reassign FDTs — it is only a
       diagnostic boundary.

    4. Assign pickup points and auto-generate them if no pickup layer exists.
    """
    closures: List[DomeClosure] = []
    if not fdts:
        return []

    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    # Blocker 10 fix: this pre-clustering cap previously hardcoded
    # ``// 2`` (Single-PON's cores_per_fdt), independent of the *actual*
    # per-FDT capacity check that runs later during core assignment. Under
    # Single-PON the two numbers agree by coincidence (48//2 == 48//8*4 ==
    # 24); under Dual-PON they would not (48//2=24 vs the real 48//4=12),
    # letting _cluster_fdts group up to twice as many FDTs into one closure
    # as its core list can actually hold — a silent late-stage core-
    # assignment failure for the overflow FDTs. Thread cores_per_fdt through.
    max_per_closure = CLOSURE_LARGE_CAPACITY // profile.cores_per_fdt
    clusters = _cluster_fdts(fdts, max_per_closure, dist_calc)

    # Log initial balance
    if clusters:
        sizes = [len(c) for c in clusters]
        logger.log(
            f"Closure clustering: {len(clusters)} region(s), "
            f"FDTs per region — min={min(sizes)} max={max(sizes)} "
            f"avg={sum(sizes)/len(sizes):.1f}"
        )

    # ── Prepare spatial indices ───────────────────────────────────────────────
    building_index = None
    building_geoms: Dict[int, QgsGeometry] = {}
    if building_layer:
        building_index = index_mgr.build_index(building_layer, cache_geoms=True)
        building_geoms = index_mgr.geometries.get(building_layer.id(), {})

    pole_index = None
    pole_geoms: Dict[int, QgsGeometry] = {}
    if pole_layer and pole_layer.featureCount() > 0:
        pole_index = index_mgr.build_index(pole_layer, cache_geoms=True)
        pole_geoms = index_mgr.geometries.get(pole_layer.id(), {})

    pick_idx   = None
    pick_geoms = {}
    if pickup_layer and pickup_layer.featureCount() > 0:
        pick_idx   = index_mgr.build_index(pickup_layer, cache_geoms=True)
        pick_geoms = index_mgr.geometries.get(pickup_layer.id(), {})
        logger.log("Pickup layer available; closures will reference nearest pickup")

    # ── Build one closure per cluster ─────────────────────────────────────────
    for ci, cluster in enumerate(clusters, start=1):

        # Cluster centroid
        cx = sum(f.geometry.x() for f in cluster) / len(cluster)
        cy = sum(f.geometry.y() for f in cluster) / len(cluster)
        centroid = QgsPointXY(cx, cy)
        closure_pt = centroid
        snapped_pt = None
        road_geom  = None
        best_score = None

        # ── Place closure at road-junction pole nearest to centroid ───────────
        # Prefer poles at road endpoints (junctions) for natural cable branching.
        if road_index and pole_index:
            candidate_ids = pole_index.nearestNeighbor(centroid, 25)
            best_pole   = None
            best_score  = -1
            best_dist   = float('inf')

            for pid in candidate_ids:
                pgeom = pole_geoms.get(pid)
                if not pgeom:
                    continue
                pole_pt   = pgeom.asPoint()
                pole_dist = dist_calc.distance_points(centroid, pole_pt)

                # Junction score: count road endpoints within 5 m of this pole
                nearby_rids    = road_index.nearestNeighbor(pole_pt, 8)
                junction_score = 0
                for rid in nearby_rids:
                    road = roads.get(rid)
                    if not road or not road.geometry or road.geometry.isEmpty():
                        continue
                    verts = _road_vertices(road.geometry)
                    if not verts:
                        continue
                    for ep in (verts[0], verts[-1]):
                        if dist_calc.distance_points(pole_pt, ep) <= 5.0:
                            junction_score += 1
                            break

                if (junction_score > best_score or
                        (junction_score == best_score and pole_dist < best_dist)):
                    best_score = junction_score
                    best_dist  = pole_dist
                    best_pole  = pole_pt

            if best_pole:
                snapped_pt = best_pole
                closure_pt = best_pole

        # Fallback: snap to nearest road then nearest pole
        if snapped_pt is None:
            if road_index:
                nr = road_index.nearestNeighbor(closure_pt, 1)
                if nr:
                    road = roads.get(nr[0])
                    if road and road.geometry and not road.geometry.isEmpty():
                        road_geom  = road.geometry
                        closure_pt = road_geom.nearestPoint(
                            QgsGeometry.fromPointXY(closure_pt)).asPoint()
            if pole_index:
                cids = pole_index.nearestNeighbor(closure_pt, 5)
                bp, bd = None, float('inf')
                for pid in cids:
                    pg = pole_geoms.get(pid)
                    if not pg:
                        continue
                    pp = pg.asPoint()
                    d  = dist_calc.distance_points(closure_pt, pp)
                    if d < bd:
                        bd, bp = d, pp
                if bp:
                    snapped_pt = bp
                    closure_pt = bp

        # Building avoidance
        if building_index:
            for bid in building_index.intersects(
                    QgsGeometry.fromPointXY(closure_pt).boundingBox()):
                bgeom = building_geoms.get(bid)
                if bgeom and bgeom.contains(QgsGeometry.fromPointXY(closure_pt)):
                    if road_geom:
                        closure_pt = road_geom.nearestPoint(
                            QgsGeometry.fromPointXY(closure_pt)).asPoint()
                    snapped_pt = None
                    break

        # ── Zone geometry: convex hull of cluster FDT points ─────────────────
        # Used only as a diagnostic boundary — NOT for FDT reassignment.
        fdt_pts = [QgsGeometry.fromPointXY(f.snapped_geometry or f.geometry)
                   for f in cluster]
        if len(fdt_pts) >= 3:
            merged   = QgsGeometry.unaryUnion(fdt_pts)
            zone_raw = merged.convexHull()
            # Buffer by MAX_BOX_TO_BOX_DISTANCE so FDTs on zone edge are included
            zone_geom = zone_raw.buffer(rc.MAX_BOX_TO_BOX_DISTANCE, 8)
        elif fdt_pts:
            zone_geom = fdt_pts[0].buffer(rc.MAX_BOX_TO_BOX_DISTANCE * 2, 8)
        else:
            zone_geom = QgsGeometry.fromPointXY(closure_pt).buffer(
                rc.MAX_BOX_TO_BOX_DISTANCE * 2, 8)

        # ── Capacity ──────────────────────────────────────────────────────────
        cap = _closure_size_for(len(cluster), profile.cores_per_fdt)

        # ── Pickup point ──────────────────────────────────────────────────────
        pickup_pt   = None
        pickup_name = None
        if pick_idx:
            nr = pick_idx.nearestNeighbor(closure_pt, 1)
            if nr:
                pid = nr[0]
                pg  = pick_geoms.get(pid)
                feat = None
                # BUG (pre-existing, not introduced by this pass): wkbType()
                # returns a QgsWkbTypes.Type (Point, PointZ, MultiPoint, ...)
                # — a different enum from QgsWkbTypes.PointGeometry, which is
                # a QgsWkbTypes.GeometryType (the Point/Line/Polygon
                # *category*). Comparing them directly is never true for
                # real point data; the correct check converts the specific
                # WKB type to its category first via QgsWkbTypes.geometryType().
                # This branch was silently always False before, so every
                # lookup fell through to the `else` below, which used to
                # call .asPoint() unconditionally (no type check at all) —
                # that's *why* it worked by accident. Adding a real type
                # check to the else branch with the same broken comparison
                # (my earlier fix) made it fail every time instead, which is
                # the self-contradictory "geometry type Point, not Point"
                # warning. Fixed here in both places.
                if pg and QgsWkbTypes.geometryType(pg.wkbType()) == QgsWkbTypes.PointGeometry:
                    pickup_pt = pg.asPoint()
                else:
                    req  = QgsFeatureRequest(pid)
                    feat = next(pickup_layer.getFeatures(req), None)
                    fgeom = feat.geometry() if feat else None
                    if fgeom and QgsWkbTypes.geometryType(fgeom.wkbType()) == QgsWkbTypes.PointGeometry:
                        pickup_pt = fgeom.asPoint()
                    elif fgeom and not fgeom.isEmpty():
                        # Defensive: the "optional pickup layer" fed to this
                        # run is not a point layer (e.g. a roads/line layer
                        # got wired in by mistake) — don't crash the whole
                        # pipeline over one closure's pickup lookup, treat as
                        # "no pickup for this closure" and keep going. A
                        # wrong optional-layer selection is a project/config
                        # issue to fix on the QGIS side, not something this
                        # function should take down the whole run for.
                        logger.log(
                            f"WARNING [PICKUP_LAYER_NOT_POINTS]: nearest pickup "
                            f"feature (fid {pid}) has geometry type "
                            f"{QgsWkbTypes.displayString(fgeom.wkbType())}, not "
                            f"Point — skipping pickup for closure #{ci}. Check "
                            f"that the correct point layer is wired in as the "
                            f"optional pickup layer."
                        )
                pickup_name = f"PICKUP_{pid}"
                if feat and 'name' in feat.fields().names():
                    try:
                        pickup_name = str(feat['name'])
                    except Exception:
                        pass

        closure = DomeClosure(
            name=_project_tag("CLOSURE", f"{ci:04d}"),
            geometry=closure_pt,
            fdts=list(cluster),
            total_fdt=len(cluster),
            feed_capacity=cap,
            pickup_geometry=pickup_pt,
            pickup_name=pickup_name,
            snapped_geometry=snapped_pt,
            zone_geometry=zone_geom,
        )
        closures.append(closure)
        logger.log(
            f"  {closure.name}: {len(cluster)} FDTs, "
            f"cap={cap} cores, junction_score={best_score if pole_index else 'n/a'}"
        )

    # ── Auto-generate pickup points if no pickup layer ────────────────────────
    if not pick_idx:
        _generate_pickup_points(closures, roads, road_index, dist_calc, logger)

    # ── Final balance report ──────────────────────────────────────────────────
    counts = [c.total_fdt for c in closures]
    logger.log(
        f"Final: {len(closures)} closure(s) — "
        f"min={min(counts)} max={max(counts)} avg={sum(counts)/len(counts):.1f}"
    )

    return closures


def correct_cable_zone_violations(closures: List[DomeClosure],
                                   cables: List[CableSegment],
                                   cable_router: CableRouter,
                                   logger: PerformanceLogger,
                                   profile: Optional['CapacityProfile'] = None) -> List[CableSegment]:
    """Re-check FDT zone membership after routing and fix any misassignments.

    Since enforce_closure_zone_membership already ran during generate_closures,
    this pass is a lightweight safety net.  It checks each routed cable's FDT
    point against its closure's zone and, if the point falls outside, moves the
    FDT to the correct closure and re-routes the affected closures.
    """
    if not closures:
        return cables

    hard_cap    = CLOSURE_LARGE_CAPACITY // 2
    reassigned  = set()   # FDT names that were moved

    for closure in closures:
        for fdt in list(closure.fdts):
            test_pt  = fdt.snapped_geometry or fdt.geometry
            pt_geom  = QgsGeometry.fromPointXY(test_pt)
            in_zone  = (closure.zone_geometry and
                        closure.zone_geometry.contains(pt_geom))
            if in_zone:
                continue

            # FDT is outside this closure's zone — find the correct one
            correct = None
            for other in closures:
                if other is closure:
                    continue
                if (other.zone_geometry and
                        other.zone_geometry.contains(pt_geom) and
                        other.total_fdt < hard_cap):
                    correct = other
                    break

            # Fallback: nearest closure with capacity
            if correct is None:
                candidates = [(c, cable_router.dist_calc.distance_points(
                                  test_pt, c.snapped_geometry or c.geometry))
                              for c in closures
                              if c is not closure and c.total_fdt < hard_cap]
                if candidates:
                    correct = min(candidates, key=lambda x: x[1])[0]

            if correct is None:
                logger.log(f"No reassignment target for {fdt.name}; keeping in {closure.name}")
                continue

            logger.log(f"Reassigning {fdt.name}: {closure.name} → {correct.name}")
            closure.fdts.remove(fdt)
            closure.total_fdt -= 1
            correct.fdts.append(fdt)
            correct.total_fdt += 1
            reassigned.add(closure.name)
            reassigned.add(correct.name)

    if not reassigned:
        return cables

    # Update capacities
    for c in closures:
        c.feed_capacity = _closure_size_for(c.total_fdt, (profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]).cores_per_fdt)

    # Re-route only the affected closures; keep unaffected cables intact
    unaffected = [c for c in cables
                  if c.core_info.get("closure_name", "") not in reassigned]
    affected   = [c for c in closures if c.name in reassigned]
    re_routed  = route_closure_to_fdts(affected, cable_router, logger)

    logger.log(f"Zone correction: {len(reassigned)} closures re-routed "
               f"({len(re_routed)} cables)")
    return unaffected + re_routed


def route_closure_to_fdts(closures: List[DomeClosure],
                          cable_router: CableRouter,
                          logger: PerformanceLogger,
                          profile: Optional['CapacityProfile'] = None) -> List[CableSegment]:
    """Route Closure→FDT distribution cables — one road-following cable per FDT.

    Strategy: shared-graph Dijkstra per closure
    ────────────────────────────────────────────
    For each closure, build ONE temporary graph that ties the closure point
    AND every FDT point in as exact graph vertices (via
    ``cable_routing._build_tied_graph`` — see module docstring). Then run
    Dijkstra ONCE from the closure vertex so a single O(V log V) pass gives
    the shortest-path tree to ALL FDT vertices simultaneously. Each FDT path
    is reconstructed by tracing back through that tree.

    Why this eliminates the flying-cable artefact
    ─────────────────────────────────────────────
    A naive approach anchors each endpoint to the nearest road JUNCTION node.
    For mid-road devices the path would include a straight stub from the snap
    point to the junction — cutting directly through buildings. Tying the
    exact device coordinates in as graph vertices on the road centre-line
    means every segment in the output geometry follows actual road geometry
    with no off-road stubs.

    Fallback: if the shared graph build fails for a closure, each FDT is
    routed individually via find_shortest_path_points().

    Rules preserved:
      1. Zone integrity  – closure.fdts is already clean from generate_closures().
      2. FDTs sorted by distance for deterministic core assignment.
      3. Core pairs assigned sequentially in groups of MAX_FDT_PER_8CORE.
    """
    logger.start_module("Closure to FDT Routing")
    profile = profile or CAPACITY_PROFILES[PONArchitecture.SINGLE_PON]
    cables: List[CableSegment] = []

    for closure in closures:
        if not closure.fdts:
            continue

        closure_pt = closure.snapped_geometry or closure.geometry

        # ── Sort FDTs by distance for deterministic core assignment ───────────
        sorted_fdts = sorted(
            closure.fdts,
            key=lambda f: (
                round(cable_router.dist_calc.distance_points(
                    closure_pt, f.snapped_geometry or f.geometry), 3),
                f.name
            )
        )

        # ── Validate capacity ─────────────────────────────────────────────────
        cores = generate_core_list(closure.feed_capacity)
        # §13 fix: closure capacity is now a direct formula
        # (feed_capacity // cores_per_fdt), replacing the single-PON-only
        # ``(feed_capacity // 8) * MAX_FDT_PER_8CORE`` — those two agreed by
        # coincidence only under Single-PON (cores_per_fdt=2).
        max_fdt_for_capacity = closure.feed_capacity // profile.cores_per_fdt
        if len(sorted_fdts) > max_fdt_for_capacity:
            logger.error(
                f"{closure.name} has {len(sorted_fdts)} FDTs but "
                f"{closure.feed_capacity} cores can only serve "
                f"{max_fdt_for_capacity}; skipping")
            continue

        fdt_pts = [fdt.snapped_geometry or fdt.geometry for fdt in sorted_fdts]

        # ── Build one shared graph with closure + all FDT points tied in ──────
        # Ties every point in as an exact vertex on the road network. Running
        # Dijkstra once from closure_v gives shortest paths to all FDTs.
        graph       = None
        tree        = None
        closure_v   = -1
        fdt_verts: List[int] = []

        try:
            # [B2B detour fix] Distribution cables share the routing graph
            # defect, so they share the fix.
            _rl = cable_router._ensure_routing_layer(logger)
            input_pts = [closure_pt] + fdt_pts
            graph, vertex_ids = _build_tied_graph(_rl, input_pts)

            if vertex_ids and len(vertex_ids) == len(input_pts):
                closure_v = vertex_ids[0]
                fdt_verts = vertex_ids[1:]

            if closure_v >= 0:
                tree, _ = QgsGraphAnalyzer.dijkstra(graph, closure_v, 0)
        except Exception as exc:
            logger.error(f"Shared graph build failed for {closure.name}: {exc}")
            graph = None

        v_count = graph.vertexCount() if graph else 0
        e_count = graph.edgeCount()   if graph else 0

        # ── Route one cable per FDT ───────────────────────────────────────────
        for idx, fdt in enumerate(sorted_fdts):
            fdt_pt = fdt_pts[idx]

            # §13 core-pair stride: generalized from the Single-PON-only
            # ``pos_in_group * 2`` to a cores_per_fdt-wide block per FDT.
            # For Single-PON (cores_per_fdt=2) this is byte-identical to the
            # original: n_per_group == 8//2 == 4 == MAX_FDT_PER_8CORE,
            # base_core == group_idx*8 + pos_in_group*2.
            n_per_group  = 8 // profile.cores_per_fdt
            group_idx    = idx // n_per_group
            pos_in_group = idx % n_per_group
            base_core    = group_idx * 8 + pos_in_group * profile.cores_per_fdt

            if base_core + (profile.cores_per_fdt - 1) >= len(cores):
                logger.error(
                    f"Not enough cores in {closure.name} for FDT {fdt.name} "
                    f"(idx {idx}); skipping")
                continue

            active    = cores[base_core]
            redundant = cores[base_core + 1]
            # Dual-PON: PON2's active/redundant pair, immediately after PON1's.
            pon2_active   = cores[base_core + 2] if profile.cores_per_fdt >= 4 else None
            pon2_redundant = cores[base_core + 3] if profile.cores_per_fdt >= 4 else None

            geom: Optional[QgsGeometry] = None
            length: float = 0.0

            # ── Try shared-graph path first ───────────────────────────────────
            fdt_v = fdt_verts[idx] if fdt_verts and idx < len(fdt_verts) else -1

            if (tree is not None and graph is not None
                    and closure_v >= 0 and fdt_v >= 0
                    and fdt_v < len(tree) and tree[fdt_v] != -1):
                pts: List[QgsPointXY] = []
                current = fdt_v
                steps   = 0
                max_s   = v_count + e_count + 10
                ok      = True

                while current != closure_v:
                    if current < 0 or current >= v_count:
                        ok = False; break
                    pts.append(graph.vertex(current).point())
                    eid = tree[current]
                    if eid < 0 or eid >= e_count:
                        ok = False; break
                    current = graph.edge(eid).fromVertex()
                    steps += 1
                    if steps > max_s:
                        ok = False; break

                if ok:
                    pts.append(graph.vertex(closure_v).point())
                    pts.reverse()
                    # [Physical contact fix] pts here are graph vertices —
                    # tied to the nearest point ON the road, so for a
                    # pole-mounted device offset from the road centre-line
                    # these are NOT the true device coordinates. Stub back
                    # out to them, same fix as
                    # CableRouter.find_shortest_path_points().
                    if cable_router.dist_calc.distance_points(pts[0], closure_pt) > rc.DROP_LENGTH_TOLERANCE:
                        pts.insert(0, closure_pt)
                    if cable_router.dist_calc.distance_points(pts[-1], fdt_pt) > rc.DROP_LENGTH_TOLERANCE:
                        pts.append(fdt_pt)
                    pts = _dedupe_points(pts)
                    if len(pts) >= 2:
                        geom   = QgsGeometry.fromPolylineXY(pts)
                        length = geom.length()

            # ── Fallback: individual tied-graph build for this FDT pair ───────
            if geom is None or geom.isEmpty():
                geom, length = cable_router.find_shortest_path_points(
                    closure_pt, fdt_pt
                )

            if geom is None or geom.isEmpty():
                logger.error(
                    f"No road path found for {closure.name} → {fdt.name}; "
                    f"cable skipped")
                continue

            cables.append(CableSegment(
                name=f"{closure.name}-{fdt.name}",
                start_device=closure.name,
                end_device=fdt.name,
                geometry=geom,
                length=length,
                fdt_id=fdt.name,
                core_info={
                    "closure_name":           closure.name,
                    # active/redundant are (buffer_color, core_number,
                    # core_color) triples from generate_core_list(). Keep
                    # both the true colour AND the raw position — a splice
                    # record needs the number, a colour-coded drawing needs
                    # the colour, and neither should be derived from the
                    # other downstream.
                    "buffer_color_active":    active[0],
                    "core_number_active":     active[1],
                    "core_color_active":      active[2],
                    "buffer_color_redundant": redundant[0],
                    "core_number_redundant":  redundant[1],
                    "core_color_redundant":   redundant[2],
                    # Dual-PON: PON2's own active/redundant core pair, in the
                    # same physical cable (one cable per FDT still — see §13
                    # worked example). None/absent under Single-PON.
                    "pon2_buffer_color_active":    pon2_active[0] if pon2_active else None,
                    "pon2_core_number_active":     pon2_active[1] if pon2_active else None,
                    "pon2_core_color_active":      pon2_active[2] if pon2_active else None,
                    "pon2_buffer_color_redundant": pon2_redundant[0] if pon2_redundant else None,
                    "pon2_core_number_redundant":  pon2_redundant[1] if pon2_redundant else None,
                    "pon2_core_color_redundant":   pon2_redundant[2] if pon2_redundant else None,
                    "cores_per_fdt":          profile.cores_per_fdt,
                    "cable_capacity":         closure.feed_capacity,
                    "cascade_group":          group_idx,
                    "zone_violation":         False,
                }
            ))

    logger.end_module("Closure to FDT Routing")
    logger.log(f"Routed {len(cables)} closure-to-FDT cables")
    return cables


def route_pickup_to_closure(closures: List[DomeClosure],
                            pickup_layer: Optional[QgsVectorLayer],
                            index_mgr: SpatialIndexManager,
                            cable_router: CableRouter,
                            logger: PerformanceLogger,
                            closure_cables: Optional[List[CableSegment]] = None) -> List[CableSegment]:
    """Route feeder cables from pickup points to closures via shortest road path.

    Both the pickup point and the closure point are already ON the road network
    (they were snapped to roads during generation).  For points already on roads
    the correct approach is to find the nearest graph VERTEX directly — no
    road_id projection is needed or helpful, and in fact passing a road_id can
    cause _road_snap to project onto a DIFFERENT parallel road, sending Dijkstra
    to the wrong start/end vertex and producing a long detour.

    So for feeder routing we use find_shortest_path_points() which inserts both
    endpoints as exact graph vertices so Dijkstra is guaranteed to find the
    globally shortest path.

    ``closure_cables`` (the already-routed closure-to-FDT cables, if passed)
    is read — never re-derived — to build this feeder's own core manifest:
    total/active/redundant core counts, buffer colours in use, and a
    per-FDT core-colour trace (fdt_core_map). Reading the real routed
    cables here, rather than recomputing the FDT-to-core assignment a
    second time, guarantees the feeder's manifest can never disagree with
    what route_closure_to_fdts() actually built.
    """
    cables: List[CableSegment] = []
    pick_idx   = None
    pick_geoms = {}
    if pickup_layer and pickup_layer.featureCount() > 0:
        pick_idx   = index_mgr.get_index(pickup_layer)
        pick_geoms = index_mgr.geometries.get(pickup_layer.id(), {})

    for closure in closures:
        # ── END point: the closure's actual placed position (pole on road) ─────
        end_pt = closure.snapped_geometry or closure.geometry

        # ── START point: pickup geometry ──────────────────────────────────────
        start_pt = None

        if closure.pickup_geometry:
            start_pt = closure.pickup_geometry
        elif pick_idx:
            nearest = pick_idx.nearestNeighbor(end_pt, 1)
            if nearest:
                pid = nearest[0]
                pg  = pick_geoms.get(pid)
                if pg and QgsWkbTypes.geometryType(pg.wkbType()) == QgsWkbTypes.PointGeometry:
                    start_pt = pg.asPoint()
                else:
                    req  = QgsFeatureRequest(pid)
                    feat = next(pickup_layer.getFeatures(req), None)
                    if feat and feat.geometry():
                        start_pt = feat.geometry().asPoint()

        if start_pt is None:
            v_idx = cable_router.find_nearest_vertex(end_pt)
            if v_idx >= 0 and cable_router.graph:
                start_pt = cable_router.graph.vertex(v_idx).point()
            else:
                start_pt = end_pt

        # ── True shortest road path via point-insertion graph ────────────────
        # find_shortest_path_points() inserts both endpoints as exact graph
        # vertices so Dijkstra is guaranteed to find the globally shortest path.
        geom, length = cable_router.find_shortest_path_points(start_pt, end_pt)

        pickup_name = closure.pickup_name or "PICKUP"
        cable_type  = f"{closure.feed_capacity}C"

        # ── Core manifest: read from the already-routed closure-to-FDT
        # cables for this closure, never recomputed independently — see
        # docstring. Sorted by cascade_group/fdt_id for a stable, readable
        # fdt_core_map ordering.
        member_cables = sorted(
            (c for c in (closure_cables or [])
             if c.core_info.get("closure_name") == closure.name),
            key=lambda c: (c.core_info.get("cascade_group", 0), c.fdt_id)
        )
        cores_per_fdt   = member_cables[0].core_info.get("cores_per_fdt", 2) if member_cables else 2
        active_per_fdt  = cores_per_fdt // 2
        active_core     = len(member_cables) * active_per_fdt
        redundant_core  = active_core
        total_core      = active_core + redundant_core

        buffer_colors = sorted({
            c.core_info.get(k) for c in member_cables
            for k in ("buffer_color_active", "buffer_color_redundant",
                      "pon2_buffer_color_active", "pon2_buffer_color_redundant")
            if c.core_info.get(k)
        })

        map_entries = []
        for c in member_cables:
            ci = c.core_info
            entry = (
                f"{c.fdt_id}: "
                f"{ci.get('buffer_color_active')}-{ci.get('core_number_active')}"
                f"({ci.get('core_color_active')}) active / "
                f"{ci.get('buffer_color_redundant')}-{ci.get('core_number_redundant')}"
                f"({ci.get('core_color_redundant')}) redundant"
            )
            if ci.get("pon2_buffer_color_active"):
                entry += (
                    f" | PON2: {ci.get('pon2_buffer_color_active')}-"
                    f"{ci.get('pon2_core_number_active')}"
                    f"({ci.get('pon2_core_color_active')}) active / "
                    f"{ci.get('pon2_buffer_color_redundant')}-"
                    f"{ci.get('pon2_core_number_redundant')}"
                    f"({ci.get('pon2_core_color_redundant')}) redundant"
                )
            map_entries.append(entry)

        cables.append(CableSegment(
            name=f"{pickup_name}-{closure.name}-{cable_type}",
            start_device=pickup_name,
            end_device=closure.name,
            geometry=geom,
            length=length,
            fdt_id="",
            core_info={
                "feed_capacity":   closure.feed_capacity,
                "cable_type":      cable_type,
                "closure_name":    closure.name,
                "total_core":      total_core,
                "active_core":     active_core,
                "redundant_core":  redundant_core,
                "buffer_colors":   ",".join(buffer_colors),
                "fdt_core_map":    "; ".join(map_entries),
            }
        ))

    logger.log(f"Routed {len(cables)} pickup-to-closure feeder cables")
    return cables
