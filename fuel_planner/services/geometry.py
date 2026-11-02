"""Geometric helpers for locating approximate stations along a route.

The source CSV has city/state but no station latitude/longitude. The import
command attaches a Census Gazetteer place point. The resulting markers are
therefore approximate. A supplemental exact-coordinate CSV can override them.
"""

from __future__ import annotations

from math import cos, hypot, radians, sin, sqrt
from typing import Any, Iterable

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two latitude/longitude points."""
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lambda = radians(lon2 - lon1)
    a = sin(delta_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(delta_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * sqrt(min(1.0, a))


def project_point_onto_route(
    latitude: float,
    longitude: float,
    route_coordinates: list[list[float]],
) -> tuple[float, float]:
    """Return (miles_from_route_start, nearest_distance_from_route).

    Coordinates from ORS are [longitude, latitude]. We project each short
    segment into a local equirectangular plane, find the closest point on the
    segment, and interpolate the cumulative route mileage. The local-plane
    calculation is sufficiently accurate for our intentionally approximate
    place-point station locations and short route-corridor threshold.
    """
    if len(route_coordinates) < 2:
        raise ValueError("A route needs at least two coordinate points.")

    cumulative_miles = 0.0
    best_distance = float("inf")
    best_route_position = 0.0

    for first, second in zip(route_coordinates, route_coordinates[1:]):
        lon1, lat1 = float(first[0]), float(first[1])
        lon2, lat2 = float(second[0]), float(second[1])
        segment_miles = haversine_miles(lat1, lon1, lat2, lon2)

        # A zero-length segment has no direction. It cannot improve a useful
        # projection, but still has a valid cumulative distance of zero.
        if segment_miles == 0:
            continue

        reference_latitude = radians((lat1 + lat2) / 2)
        miles_per_longitude_degree = 69.172 * cos(reference_latitude)
        miles_per_latitude_degree = 69.0

        segment_x = (lon2 - lon1) * miles_per_longitude_degree
        segment_y = (lat2 - lat1) * miles_per_latitude_degree
        point_x = (longitude - lon1) * miles_per_longitude_degree
        point_y = (latitude - lat1) * miles_per_latitude_degree

        squared_length = segment_x * segment_x + segment_y * segment_y
        fraction = (point_x * segment_x + point_y * segment_y) / squared_length
        fraction = min(1.0, max(0.0, fraction))

        nearest_x = fraction * segment_x
        nearest_y = fraction * segment_y
        distance = hypot(point_x - nearest_x, point_y - nearest_y)

        if distance < best_distance:
            best_distance = distance
            best_route_position = cumulative_miles + fraction * segment_miles

        cumulative_miles += segment_miles

    return best_route_position, best_distance


class _RouteIndex:
    """Pre-computed route segments plus a coarse grid for fast station lookups.

    Building this once per request turns the per-station cost from "scan every
    route point with trigonometry" into "check a handful of nearby segments".
    """

    GRID_DEGREES = 1.0

    def __init__(
        self,
        full_route: list[list[float]],
        max_deviation_miles: float,
        simplify_tolerance_miles: float,
    ) -> None:
        # Mileage always comes from the full-resolution route so positions stay
        # accurate; only the nearest-point search uses the simplified line.
        full_cumulative = [0.0]
        for first, second in zip(full_route, full_route[1:]):
            full_cumulative.append(
                full_cumulative[-1]
                + haversine_miles(
                    float(first[1]), float(first[0]), float(second[1]), float(second[0])
                )
            )
        kept = _simplify_indices(full_route, simplify_tolerance_miles)
        route = [full_route[i] for i in kept]

        self.segments: list[tuple[float, float, float, float, float, float, float, float]] = []
        cumulative = 0.0
        for k, (first, second) in enumerate(zip(route, route[1:])):
            lon1, lat1 = float(first[0]), float(first[1])
            lon2, lat2 = float(second[0]), float(second[1])
            segment_miles = full_cumulative[kept[k + 1]] - full_cumulative[kept[k]]
            if segment_miles == 0:
                continue
            cumulative = full_cumulative[kept[k]]
            kx = 69.172 * cos(radians((lat1 + lat2) / 2))
            seg_x = (lon2 - lon1) * kx
            seg_y = (lat2 - lat1) * 69.0
            self.segments.append(
                (lon1, lat1, kx, seg_x, seg_y, seg_x * seg_x + seg_y * seg_y,
                 segment_miles, cumulative)
            )
        self.total_miles = full_cumulative[-1]

        # Coarse grid: only stations in a cell near the route get the exact test.
        max_lat = max(abs(float(point[1])) for point in route)
        cell_miles = 69.172 * max(cos(radians(max_lat)), 0.2) * self.GRID_DEGREES
        margin = max(1, int(max_deviation_miles / cell_miles) + 1)
        self.cells: set[tuple[int, int]] = set()
        for first, second in zip(route, route[1:]):
            lon1, lat1 = float(first[0]), float(first[1])
            lon2, lat2 = float(second[0]), float(second[1])
            steps = int(max(abs(lat2 - lat1), abs(lon2 - lon1)) / (self.GRID_DEGREES / 2)) + 1
            for i in range(steps + 1):
                t = i / steps
                row = int((lat1 + (lat2 - lat1) * t) // self.GRID_DEGREES)
                col = int((lon1 + (lon2 - lon1) * t) // self.GRID_DEGREES)
                for dr in range(-margin, margin + 1):
                    for dc in range(-margin, margin + 1):
                        self.cells.add((row + dr, col + dc))

    def may_be_near(self, latitude: float, longitude: float) -> bool:
        key = (int(latitude // self.GRID_DEGREES), int(longitude // self.GRID_DEGREES))
        return key in self.cells

    def project(self, latitude: float, longitude: float) -> tuple[float, float]:
        """Return (miles_from_route_start, nearest_distance_from_route)."""
        best_distance = float("inf")
        best_position = 0.0
        for lon1, lat1, kx, seg_x, seg_y, sq_len, seg_miles, start in self.segments:
            point_x = (longitude - lon1) * kx
            point_y = (latitude - lat1) * 69.0
            fraction = (point_x * seg_x + point_y * seg_y) / sq_len
            fraction = min(1.0, max(0.0, fraction))
            distance = hypot(point_x - fraction * seg_x, point_y - fraction * seg_y)
            if distance < best_distance:
                best_distance = distance
                best_position = start + fraction * seg_miles
        return best_position, best_distance


def stations_near_route(
    stations: Iterable[Any],
    route_coordinates: list[list[float]],
    *,
    max_deviation_miles: float = 25.0,
    simplify_tolerance_miles: float = 0.1,
) -> list[dict[str, Any]]:
    """Project station records onto a route and keep nearby candidates.

    Speed: the route is simplified (default 0.1 mile tolerance, far finer than
    the city-level station pins) and indexed once; a coarse grid rejects most
    stations without any geometry. Stations sharing a coordinate are projected
    once.
    """
    index = _RouteIndex(route_coordinates, max_deviation_miles, simplify_tolerance_miles)

    projected_by_coordinate: dict[tuple[float, float], tuple[float, float]] = {}
    candidates: list[dict[str, Any]] = []

    for station in stations:
        if station.latitude is None or station.longitude is None:
            continue

        lat = float(station.latitude)
        lon = float(station.longitude)
        if not index.may_be_near(lat, lon):
            continue

        coordinate_key = (round(lat, 5), round(lon, 5))
        projected = projected_by_coordinate.get(coordinate_key)
        if projected is None:
            projected = index.project(lat, lon)
            projected_by_coordinate[coordinate_key] = projected

        route_position, off_route_distance = projected
        if off_route_distance > max_deviation_miles:
            continue

        candidates.append(
            {
                "station_id": station.station_id,
                "name": station.name,
                "address": station.address,
                "city": station.city,
                "state": station.state,
                "price_per_gallon": float(station.price_per_gallon),
                "latitude": lat,
                "longitude": lon,
                "location_precision": station.location_precision,
                "route_position_miles": route_position,
                "distance_from_route_miles": off_route_distance,
            }
        )

    return candidates


def _simplify_indices(
    route_coordinates: list[list[float]],
    tolerance_miles: float,
) -> list[int]:
    """Douglas-Peucker simplification so the JSON response stays small and fast.

    Station projection still uses the full-resolution route; only the line sent
    to the browser is simplified. Iterative to avoid recursion limits.
    """
    n = len(route_coordinates)
    if n <= 2:
        return list(range(n))
    mean_lat = sum(float(point[1]) for point in route_coordinates) / n
    kx = 69.172 * cos(radians(mean_lat))
    xs = [float(point[0]) * kx for point in route_coordinates]
    ys = [float(point[1]) * 69.0 for point in route_coordinates]

    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        first, last = stack.pop()
        dx, dy = xs[last] - xs[first], ys[last] - ys[first]
        length_sq = dx * dx + dy * dy
        best, best_index = -1.0, -1
        for i in range(first + 1, last):
            px, py = xs[i] - xs[first], ys[i] - ys[first]
            if length_sq == 0:
                distance = hypot(px, py)
            else:
                t = max(0.0, min(1.0, (px * dx + py * dy) / length_sq))
                distance = hypot(px - t * dx, py - t * dy)
            if distance > best:
                best, best_index = distance, i
        if best > tolerance_miles:
            keep[best_index] = True
            stack.append((first, best_index))
            stack.append((best_index, last))
    return [i for i in range(n) if keep[i]]


def simplify_route(
    route_coordinates: list[list[float]],
    tolerance_miles: float = 0.25,
) -> list[list[float]]:
    """Douglas-Peucker simplified copy of the route (coordinates rounded to 5 dp)."""
    return [
        [round(float(route_coordinates[i][0]), 5), round(float(route_coordinates[i][1]), 5)]
        for i in _simplify_indices(route_coordinates, tolerance_miles)
    ]
