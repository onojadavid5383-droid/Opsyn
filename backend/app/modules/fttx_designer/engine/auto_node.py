"""Automatic road network noding repair.

Provides robust noding functions that can be called from the pipeline to
automatically fix T_UNNODED defects before routing, eliminating B2B detours.
"""

from __future__ import annotations

import time
from typing import List, Optional

from .geometry_compat import (
    QgsGeometry,
    QgsVectorLayer,
    QgsPointXY,
)
from .spatial_utils import DistanceCalculator
from .perf_logger import PerformanceLogger
from .config import MASTER_GRAPH_TOPOLOGY_TOLERANCE, NODE_ROADS_FOR_ROUTING


def repair_road_layer_noding(
    road_layer: QgsVectorLayer,
    dist_calc: DistanceCalculator,
    logger: PerformanceLogger,
) -> QgsVectorLayer:
    """Repair road noding defects automatically before routing.

    This should be called before CableRouter construction to ensure
    the routing graph has proper connections at all intersections.

    Returns a noded version of the road layer.
    """
    if not NODE_ROADS_FOR_ROUTING:
        logger.log("NODE_ROADS_FOR_ROUTING=False, skipping auto-noding")
        return road_layer

    logger.start_module("Auto-Noding Road Repair")
    logger.log(f"Input road layer: {road_layer.featureCount()} features")

    t0 = time.time()

    try:
        # Collect all geometries
        geoms: List[QgsGeometry] = []
        for f in road_layer.getFeatures():
            g = f.geometry()
            if g and not g.isEmpty():
                geoms.append(g.clone())

        if not geoms:
            logger.log("WARNING [AUTO-NODE]: no road geometries to node")
            return road_layer

        n_input = len(geoms)

        # Log some diagnostics
        total_vertices_pre = sum(len(g.asPolyline()) for g in geoms if not g.isMultipart())
        logger.log(f"Pre-noding: {n_input} lines with ~{total_vertices_pre} vertices")

        # Apply aggressive noding with snapping tolerance
        # This is more robust than standard unaryUnion
        all_points: List[QgsPointXY] = []
        for g in geoms:
            if not g.isMultipart():
                all_points.extend(g.asPolyline())

        # Create tolerance-based clustering to ensure nearby points snap together
        point_clusters = _cluster_points_by_tolerance(
            all_points, MASTER_GRAPH_TOPOLOGY_TOLERANCE
        )

        # Snap all geometries to clustered points
        snapped_geoms: List[QgsGeometry] = []
        for g in geoms:
            snapped = _snap_geometry_to_clusters(
                g, point_clusters, MASTER_GRAPH_TOPOLOGY_TOLERANCE
            )
            if snapped:
                snapped_geoms.append(snapped)

        if not snapped_geoms:
            logger.log("WARNING [AUTO-NODE]: no geometries after snapping")
            return road_layer

        # Now apply unaryUnion on snapped geometries
        merged = QgsGeometry.unaryUnion(snapped_geoms)
        if merged is None or merged.isEmpty():
            logger.log("WARNING [AUTO-NODE]: unaryUnion returned empty")
            return road_layer

        # Extract noded linework
        if merged.isMultipart():
            parts = merged.asMultiPolyline()
        else:
            parts = [merged.asPolyline()]

        all_lines = []
        for part in parts:
            if part and len(part) >= 2:
                all_lines.append(part)

        n_output = len(all_lines)

        if not all_lines:
            logger.log("WARNING [AUTO-NODE]: no linework after noding")
            return road_layer

        # Create output layer
        noded_layer = QgsVectorLayer.from_records(
            [{"geometry": QgsGeometry.fromPolylineXY(part)} for part in all_lines],
            crs=road_layer.crs(),
            layer_id="roads_auto_noded_repaired",
        )

        # Calculate post-noding statistics
        total_vertices_post = 0
        for f in noded_layer.getFeatures():
            g = f.geometry()
            if g:
                if g.isMultipart():
                    for part in g.asMultiPolyline():
                        total_vertices_post += len(part)
                else:
                    total_vertices_post += len(g.asPolyline())

        elapsed = time.time() - t0
        logger.log(
            f"Auto-noding complete: {n_input} features -> {n_output} segments, "
            f"vertices: {total_vertices_pre} -> {total_vertices_post} "
            f"({((total_vertices_post/total_vertices_pre)-1)*100:.1f}% increase) "
            f"in {elapsed:.2f}s"
        )

        # Verify improvement
        if total_vertices_post <= total_vertices_pre * 1.1:  # Less than 10% increase
            logger.log(
                "WARNING [AUTO-NODE]: Vertex count didn't increase much - "
                "noding may not have worked properly"
            )

        return noded_layer

    except Exception as e:
        logger.log(f"ERROR [AUTO-NODE]: Failed with error: {e}")
        return road_layer
    finally:
        logger.end_module("Auto-Noding Road Repair")


def _cluster_points_by_tolerance(
    points: List[QgsPointXY],
    tolerance: float,
) -> List[List[QgsPointXY]]:
    """Cluster points that are within tolerance of each other."""
    if not points:
        return []

    clusters = []
    used = set()

    for i, p in enumerate(points):
        if i in used:
            continue

        cluster = [p]
        used.add(i)

        for j, q in enumerate(points):
            if j in used or j == i:
                continue

            dx = p.x() - q.x()
            dy = p.y() - q.y()
            distance = (dx * dx + dy * dy) ** 0.5

            if distance <= tolerance:
                cluster.append(q)
                used.add(j)

        clusters.append(cluster)

    return clusters


def _snap_geometry_to_clusters(
    geom: QgsGeometry,
    clusters: List[List[QgsPointXY]],
    tolerance: float,
) -> Optional[QgsGeometry]:
    """Snap geometry vertices to the average of their cluster."""
    if geom.isMultipart():
        parts = geom.asMultiPolyline()
        new_parts = []
        for part in parts:
            new_part = _snap_polyline_to_clusters(part, clusters, tolerance)
            if new_part:
                new_parts.append(new_part)
        if new_parts:
            return QgsGeometry.fromMultiPolylineXY(new_parts)
        else:
            return None
    else:
        part = geom.asPolyline()
        new_part = _snap_polyline_to_clusters(part, clusters, tolerance)
        if new_part:
            return QgsGeometry.fromPolylineXY(new_part)
        else:
            return None


def _snap_polyline_to_clusters(
    polyline: List[QgsPointXY],
    clusters: List[List[QgsPointXY]],
    tolerance: float,
) -> List[QgsPointXY]:
    """Snap each point in a polyline to its cluster's average."""
    if not polyline:
        return []

    # Find the cluster for each point
    cluster_for_point = {}
    for cluster_idx, cluster in enumerate(clusters):
        cluster_avg_x = sum(p.x() for p in cluster) / len(cluster)
        cluster_avg_y = sum(p.y() for p in cluster) / len(cluster)
        for p in cluster:
            key = (round(p.x(), 6), round(p.y(), 6))
            cluster_for_point[key] = (cluster_avg_x, cluster_avg_y)

    # Snap each point
    snapped = []
    for p in polyline:
        key = (round(p.x(), 6), round(p.y(), 6))
        if key in cluster_for_point:
            avg_x, avg_y = cluster_for_point[key]
            snapped.append(QgsPointXY(avg_x, avg_y))
        else:
            snapped.append(p)

    return snapped


def apply_auto_noding_to_pipeline(
    road_layer: QgsVectorLayer,
    dist_calc: DistanceCalculator,
    logger: PerformanceLogger,
) -> QgsVectorLayer:
    """Main entry point for auto-noding in the pipeline.

    This should be called immediately after loading road layers and
    before CableRouter creation.

    Returns the noded road layer to use for routing.
    """
    logger.log("=== APPLYING AUTO-NODING TO FIX B2B DETOURS ===")

    # First, run the noding audit to see how bad it is
    try:
        from .cable_routing import audit_road_layer_noding
        defects = audit_road_layer_noding(road_layer, dist_calc, logger)
        n_defects = len(defects)
        n_t_unioned = sum(1 for d in defects if d.get('kind') == 'T_UNNODED')
        logger.log(
            f"Noding audit: {n_defects} total defects, {n_t_unioned} T_UNNODED "
            f"(critical for B2B detours)"
        )
    except Exception as e:
        logger.log(f"Noding audit failed: {e}")
        n_t_unioned = -1

    # If no T_UNNODED defects, no need for aggressive noding
    if n_t_unioned <= 0:
        logger.log("No T_UNNODED defects detected - using standard noding")
        return road_layer

    logger.log(
        f"{n_t_unioned} T_UNNODED defects found - "
        "applying aggressive auto-noding repair"
    )

    # Apply auto-noding repair
    repaired_layer = repair_road_layer_noding(road_layer, dist_calc, logger)

    # Verify the repair
    try:
        from .cable_routing import audit_road_layer_noding
        post_defects = audit_road_layer_noding(repaired_layer, dist_calc, logger)
        n_post_defects = len(post_defects)
        n_post_t_unioned = sum(1 for d in post_defects if d.get('kind') == 'T_UNNODED')
        logger.log(
            f"Post-noding audit: {n_post_defects} defects, {n_post_t_unioned} T_UNNODED "
            f"(reduction: {n_t_unioned - n_post_t_unioned})"
        )
    except Exception as e:
        logger.log(f"Post-noding audit failed: {e}")

    logger.log("=== AUTO-NODING COMPLETE ===")
    return repaired_layer