from __future__ import annotations

from typing import Iterable


def aggregate_bounds(
    bounds_list: Iterable[tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    iterator = iter(bounds_list)
    first = next(iterator)
    min_x, min_y, max_x, max_y = first
    for bounds in iterator:
        min_x = min(min_x, bounds[0])
        min_y = min(min_y, bounds[1])
        max_x = max(max_x, bounds[2])
        max_y = max(max_y, bounds[3])
    return (min_x, min_y, max_x, max_y)


def bounds_intersect(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return not (
        left[2] <= right[0] or left[0] >= right[2] or left[3] <= right[1] or left[1] >= right[3]
    )


def densify_bounds(
    bounds: tuple[float, float, float, float], *, steps: int = 21
) -> list[tuple[float, float]]:
    if steps < 2:
        raise ValueError("steps must be at least 2.")
    min_x, min_y, max_x, max_y = bounds
    points: list[tuple[float, float]] = []
    for i in range(steps):
        t = i / (steps - 1)
        points.append((min_x + (max_x - min_x) * t, min_y))
    for i in range(1, steps):
        t = i / (steps - 1)
        points.append((max_x, min_y + (max_y - min_y) * t))
    for i in range(1, steps):
        t = i / (steps - 1)
        points.append((max_x - (max_x - min_x) * t, max_y))
    for i in range(1, steps - 1):
        t = i / (steps - 1)
        points.append((min_x, max_y - (max_y - min_y) * t))
    if points and points[0] != points[-1]:
        points.append(points[0])
    return points


def polygon_bounds(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def geometry_bounds(geometry: dict[str, object]) -> tuple[float, float, float, float]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    points: list[tuple[float, float]] = []

    if geometry_type == "Polygon":
        if not isinstance(coordinates, list):
            raise ValueError("Polygon coordinates must be a list.")
        for ring in coordinates:
            points.extend((point[0], point[1]) for point in ring)
    elif geometry_type == "MultiPolygon":
        if not isinstance(coordinates, list):
            raise ValueError("MultiPolygon coordinates must be a list.")
        for polygon in coordinates:
            for ring in polygon:
                points.extend((point[0], point[1]) for point in ring)
    else:
        raise ValueError(f"Unsupported geometry type: {geometry_type!r}")

    if not points:
        raise ValueError("Geometry has no coordinate points.")
    return polygon_bounds(points)
