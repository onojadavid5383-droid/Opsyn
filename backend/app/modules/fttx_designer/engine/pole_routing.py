"""Aerial box-to-box routing over the snapped support-structure network."""

from __future__ import annotations

import heapq
from typing import Dict, List, Optional, Sequence, Tuple

from .domain import RoadSegment, SupportStructure
from .geometry_compat import QgsGeometry, QgsPointXY
from .spatial_utils import DistanceCalculator


# Poles are commonly offset slightly from a road centreline. This tolerance
# limits which corridors they can join without requiring a separate pole-road
# assignment layer.
_MAX_ROAD_MATCH_M = 15.0
# At a junction, a pole may be associated with both roads when their
# centre-lines are nearly equally close.
_JUNCTION_ROAD_MATCH_DELTA_M = 3.0
# A device's snapped point can be fanned out around its pole for display.
_MAX_DEVICE_TO_POLE_M = 5.0
# pole_max_spacing_m triggers densification; it is not a hard span rejection.
# Allow a small tolerance so an otherwise direct hop just above the trigger
# does not take a large graph loop.
_DIRECT_SPAN_TOLERANCE_FACTOR = 1.25


def build_pole_graph(
    structures: Sequence[SupportStructure],
    roads: Dict[int, RoadSegment],
    dist_calc: DistanceCalculator,
    topology=None,
    max_junction_span_m: float = 60.0,
    edge_paths: Optional[Dict[Tuple[int, int], List[QgsPointXY]]] = None,
) -> Tuple[List[SupportStructure], Dict[int, Dict[int, float]]]:
    """Connect consecutive poles along each road into a weighted graph.

    A pole near an intersection may be assigned to multiple road corridors,
    joining those corridors through the shared physical support. Repaired road
    junctions from ``RoadTopologyEngine`` are also honored: the nearest
    supported poles on incident roads are joined when the physical span is
    within the configured pole spacing. Edges always represent pole-to-pole
    spans use road distance and preserve road geometry for the final route.
    """
    poles = [
        structure for structure in structures
        if structure.structure_type.lower() == "pole"
    ]
    adjacency: Dict[int, Dict[int, float]] = {index: {} for index in range(len(poles))}
    paths = edge_paths if edge_paths is not None else {}
    if len(poles) < 2 or not roads:
        return poles, adjacency

    road_members: Dict[int, List[Tuple[float, int]]] = {}
    for pole_index, pole in enumerate(poles):
        pole_geometry = QgsGeometry.fromPointXY(pole.geometry)
        candidates: List[Tuple[float, int, float]] = []
        for road_id, road in roads.items():
            geometry = getattr(road, "geometry", None)
            if geometry is None or geometry.isEmpty():
                continue
            distance = float(dist_calc.distance(geometry, pole_geometry))
            if distance <= _MAX_ROAD_MATCH_M:
                chainage = float(geometry.lineLocatePoint(pole_geometry))
                candidates.append((distance, road_id, chainage))
        if not candidates:
            continue
        candidates.sort()
        best_distance = candidates[0][0]
        best_road_geometry = roads[candidates[0][1]].geometry
        for distance, road_id, chainage in candidates:
            if distance > min(_MAX_ROAD_MATCH_M, best_distance + _JUNCTION_ROAD_MATCH_DELTA_M):
                break
            if road_id != candidates[0][1]:
                candidate_geometry = roads[road_id].geometry
                if not candidate_geometry.intersects(best_road_geometry):
                    continue
            road_members.setdefault(road_id, []).append((chainage, pole_index))

    def add_edge(left: int, right: int, points: Sequence[QgsPointXY]) -> None:
        compact: List[QgsPointXY] = []
        for point in points:
            if (not compact or abs(point.x() - compact[-1].x()) > 1e-8
                    or abs(point.y() - compact[-1].y()) > 1e-8):
                compact.append(point)
        if len(compact) < 2:
            return
        weight = sum(dist_calc.distance_points(a, b) for a, b in zip(compact, compact[1:]))
        if weight >= adjacency[left].get(right, float("inf")):
            return
        adjacency[left][right] = weight
        adjacency[right][left] = weight
        paths[(left, right)] = compact
        paths[(right, left)] = list(reversed(compact))

    def road_span(road_id: int, left: int, right: int) -> List[QgsPointXY]:
        geometry = roads[road_id].geometry
        parts = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
        best = None
        for part in parts:
            if len(part) < 2:
                continue
            line = QgsGeometry.fromPolylineXY(part)
            a = float(line.lineLocatePoint(QgsGeometry.fromPointXY(poles[left].geometry)))
            b = float(line.lineLocatePoint(QgsGeometry.fromPointXY(poles[right].geometry)))
            if best is None or a + b < best[0]:
                best = (a + b, part, a, b)
        if best is None:
            return [poles[left].geometry, poles[right].geometry]
        _, part, a, b = best
        line = QgsGeometry.fromPolylineXY(part)
        points: List[QgsPointXY] = [
            poles[left].geometry, line.interpolate(a).asPoint()
        ]
        lo, hi = sorted((a, b))
        travelled = 0.0
        for p, q in zip(part, part[1:]):
            travelled += dist_calc.distance_points(p, q)
            if lo + 1e-6 < travelled < hi - 1e-6:
                points.append(q)
        points.extend([line.interpolate(b).asPoint(), poles[right].geometry])
        if a > b:
            points.reverse()
        return points

    for road_id, members in road_members.items():
        members.sort(key=lambda item: item[0])
        ordered_indices: List[int] = []
        for _, pole_index in members:
            if not ordered_indices or ordered_indices[-1] != pole_index:
                ordered_indices.append(pole_index)
        for left, right in zip(ordered_indices, ordered_indices[1:]):
            if left == right:
                continue
            add_edge(left, right, road_span(road_id, left, right))

    # RoadTopologyEngine heals near-miss endpoints and un-noded T-junctions
    # in its graph, while the source road geometries remain unchanged. Exact
    # geometry intersection therefore leaves the support graph fragmented.
    # Join the nearest pole on each incident road at those healed junctions.
    if topology is not None and max_junction_span_m > 0:
        def connect_at(point: QgsPointXY, incident_roads: Sequence[int]) -> None:
            candidates: List[int] = []
            for road_id in incident_roads:
                members = road_members.get(road_id, ())
                if not members:
                    continue
                road = roads.get(road_id)
                geometry = getattr(road, "geometry", None) if road else None
                if geometry is None or geometry.isEmpty():
                    continue
                chainage = float(geometry.lineLocatePoint(
                    QgsGeometry.fromPointXY(point)
                ))
                _, pole_index = min(members, key=lambda item: abs(item[0] - chainage))
                pole_distance = dist_calc.distance_points(poles[pole_index].geometry, point)
                # A topology junction is a turn point, not permission to span
                # an entire block diagonally. Only supports physically at the
                # junction can transfer between its incident road corridors.
                if pole_distance <= 12.0:
                    candidates.append(pole_index)
            # A repaired junction needs support from at least two distinct
            # poles. The direct span cap prevents a topology repair from
            # creating an implausibly long aerial hop.
            for offset, left in enumerate(candidates):
                for right in candidates[offset + 1:]:
                    if left == right:
                        continue
                    span = dist_calc.distance_points(
                        poles[left].geometry, poles[right].geometry
                    )
                    if span > 24.0:
                        continue
                    adjacency[left][right] = min(
                        adjacency[left].get(right, float("inf")), span
                    )
                    adjacency[right][left] = min(
                        adjacency[right].get(left, float("inf")), span
                    )
                    paths[(left, right)] = [poles[left].geometry, point, poles[right].geometry]
                    paths[(right, left)] = list(reversed(paths[(left, right)]))

        for node_id, node_data in getattr(topology, "_nodes", {}).items():
            incident = sorted(
                road_id for road_id in node_data.get("edges", set())
                if road_id in roads
            )
            if len(incident) > 1:
                connect_at(node_data["point"], incident)

        # Virtual connectors join two distinct topology nodes (road_id=-1).
        # Apply the same support-span check across their small repaired gap.
        for node_id, edges in getattr(topology, "adj", {}).items():
            for neighbor_id, road_id, _weight in edges:
                if road_id != -1 or node_id >= neighbor_id:
                    continue
                left_roads = getattr(topology, "_nodes", {}).get(
                    node_id, {}
                ).get("edges", set())
                right_roads = getattr(topology, "_nodes", {}).get(
                    neighbor_id, {}
                ).get("edges", set())
                left_point = getattr(topology, "node_points", {}).get(node_id)
                right_point = getattr(topology, "node_points", {}).get(neighbor_id)
                if left_point is None or right_point is None:
                    continue
                connect_at(left_point, sorted(left_roads))
                connect_at(right_point, sorted(right_roads))
                # Pair the nearest supported pole at either connector end.
                def nearest_for(road_ids, point):
                    nearby = []
                    for rid in road_ids:
                        members = road_members.get(rid, ())
                        if not members:
                            continue
                        road = roads[rid]
                        chainage = float(road.geometry.lineLocatePoint(
                            QgsGeometry.fromPointXY(point)
                        ))
                        _, pole_index = min(members, key=lambda item: abs(item[0] - chainage))
                        nearby.append(pole_index)
                    nearby = [
                        index for index in nearby
                        if dist_calc.distance_points(poles[index].geometry, point)
                        <= 12.0
                    ]
                    return min(
                        nearby,
                        key=lambda index: dist_calc.distance_points(
                            poles[index].geometry, point
                        ),
                    ) if nearby else None
                left_pole = nearest_for(left_roads, left_point)
                right_pole = nearest_for(right_roads, right_point)
                if left_pole is not None and right_pole is not None and left_pole != right_pole:
                    span = dist_calc.distance_points(
                        poles[left_pole].geometry, poles[right_pole].geometry
                    )
                    if span <= 24.0:
                        adjacency[left_pole][right_pole] = min(
                            adjacency[left_pole].get(right_pole, float("inf")), span
                        )
                        adjacency[right_pole][left_pole] = min(
                            adjacency[right_pole].get(left_pole, float("inf")), span
                        )
                        paths[(left_pole, right_pole)] = [
                            poles[left_pole].geometry, left_point, right_point,
                            poles[right_pole].geometry,
                        ]
                        paths[(right_pole, left_pole)] = list(reversed(paths[(left_pole, right_pole)]))

    return poles, adjacency


def route_between_supports(
    poles: Sequence[SupportStructure],
    adjacency: Dict[int, Dict[int, float]],
    dist_calc: DistanceCalculator,
    start: QgsPointXY,
    end: QgsPointXY,
    start_anchor: Optional[QgsPointXY],
    end_anchor: Optional[QgsPointXY],
    start_name: Optional[str] = None,
    end_name: Optional[str] = None,
    max_direct_span_m: float = 60.0,
    edge_paths: Optional[Dict[Tuple[int, int], List[QgsPointXY]]] = None,
    diagnostic: Optional[Dict[str, object]] = None,
) -> Optional[QgsGeometry]:
    """Return cable geometry through the shortest connected pole chain.

    Start and end are the cable attachment points; anchors identify the
    snapped supports. Pole-to-pole mode does not fall back to road routing.
    """
    if diagnostic is not None:
        diagnostic.clear()
    if not poles:
        if diagnostic is not None:
            diagnostic["reason"] = "support graph has no poles"
        return None
    if start_anchor is None or end_anchor is None:
        if diagnostic is not None:
            missing = "start" if start_anchor is None else "end"
            if start_anchor is None and end_anchor is None:
                missing = "start and end"
            diagnostic["reason"] = f"{missing} support anchor is missing"
        return None

    def resolve(anchor: QgsPointXY, name: Optional[str], side: str) -> Optional[int]:
        named = [
            index for index, pole in enumerate(poles)
            if name and getattr(pole, "name", None) == name
        ]
        candidates = named or list(range(len(poles)))
        if not candidates:
            if diagnostic is not None:
                diagnostic["reason"] = f"{side} anchor has no candidate support pole"
            return None
        index = min(
            candidates,
            key=lambda i: dist_calc.distance_points(poles[i].geometry, anchor),
        )
        distance = dist_calc.distance_points(poles[index].geometry, anchor)
        if distance > _MAX_DEVICE_TO_POLE_M:
            if diagnostic is not None:
                diagnostic["reason"] = (
                    f"{side} anchor is {distance:.2f} m from support pole "
                    f"{name or index} (maximum {_MAX_DEVICE_TO_POLE_M:.2f} m)"
                )
            return None
        return index

    source = resolve(start_anchor, start_name, "start")
    target = resolve(end_anchor, end_name, "end")
    if source is None or target is None:
        return None

    def component_labels() -> Dict[int, int]:
        labels: Dict[int, int] = {}
        component = 0
        for seed in range(len(poles)):
            if seed in labels:
                continue
            stack = [seed]
            labels[seed] = component
            while stack:
                current = stack.pop()
                for neighbor in adjacency.get(current, {}):
                    if neighbor not in labels:
                        labels[neighbor] = component
                        stack.append(neighbor)
            component += 1
        return labels

    labels = component_labels()
    if diagnostic is not None:
        diagnostic.update({
            "start_pole": source,
            "end_pole": target,
            "start_component": labels[source],
            "end_component": labels[target],
        })

    if source == target:
        chain = [source]
    else:
        previous: Dict[int, Optional[int]] = {source: None}
        distances = {source: 0.0}
        queue: List[Tuple[float, int]] = [(0.0, source)]
        while queue:
            cost, current = heapq.heappop(queue)
            if cost != distances.get(current):
                continue
            if current == target:
                break
            for neighbor, span in adjacency.get(current, {}).items():
                candidate = cost + span
                if candidate < distances.get(neighbor, float("inf")):
                    distances[neighbor] = candidate
                    previous[neighbor] = current
                    heapq.heappush(queue, (candidate, neighbor))
        if target not in previous:
            if diagnostic is not None:
                diagnostic["reason"] = (
                    "support poles are disconnected "
                    f"(components {labels[source]} and {labels[target]})"
                )
            return None

        chain = []
        current: Optional[int] = target
        while current is not None:
            chain.append(current)
            current = previous[current]
        chain.reverse()
    points = [start]
    for left, right in zip(chain, chain[1:]):
        span_points = (edge_paths or {}).get((left, right))
        if not span_points:
            if diagnostic is not None:
                diagnostic["reason"] = f"support span {left}->{right} has no route geometry"
            return None
        points.extend(span_points)
    if len(chain) == 1:
        points.append(poles[chain[0]].geometry)
    points.append(end)

    deduped: List[QgsPointXY] = []
    for point in points:
        if (not deduped
                or abs(point.x() - deduped[-1].x()) > 1e-8
                or abs(point.y() - deduped[-1].y()) > 1e-8):
            deduped.append(point)
    if len(deduped) < 2:
        return QgsGeometry()
    return QgsGeometry.fromPolylineXY(deduped)
