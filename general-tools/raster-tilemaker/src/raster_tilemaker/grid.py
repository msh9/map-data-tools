from __future__ import annotations

import math
from typing import Iterable

from raster_tilemaker.config import DEFAULT_RESOLUTIONS


def validate_resolutions(resolutions: Iterable[float]) -> list[float]:
    resolved = [float(value) for value in resolutions]
    if not resolved:
        raise ValueError("At least one resolution is required.")
    allowed = {float(value) for value in DEFAULT_RESOLUTIONS}
    for value in resolved:
        if value <= 0:
            raise ValueError("Resolutions must be positive values.")
        if value not in allowed:
            raise ValueError(f"Resolution {value} is not supported by the ADR-005 ladder.")
    for left, right in zip(resolved, resolved[1:]):
        if left <= right:
            raise ValueError("Resolutions must be listed from coarse to fine.")
    return resolved


def compute_zoom_levels(
    base_resolution: float,
    extent_width: float,
    extent_height: float,
    tile_size: int,
) -> tuple[int, int, list[float]]:
    if base_resolution <= 0:
        raise ValueError("Base resolution must be positive.")
    if tile_size <= 0:
        raise ValueError("Tile size must be positive.")
    extent_px = max(extent_width, extent_height) / base_resolution
    if extent_px <= tile_size:
        max_zoom = 0
    else:
        max_zoom = math.ceil(math.log2(extent_px / tile_size))
    max_zoom = max(max_zoom, 0)
    resolutions = [base_resolution * 2 ** (max_zoom - z) for z in range(max_zoom + 1)]
    return 0, max_zoom, resolutions


def tile_counts(
    extent_width: float,
    extent_height: float,
    resolution: float,
    tile_size: int,
) -> tuple[int, int]:
    span = tile_size * resolution
    tiles_x = math.ceil(extent_width / span)
    tiles_y = math.ceil(extent_height / span)
    return tiles_x, tiles_y


def tile_index_range(
    bounds: tuple[float, float, float, float],
    origin: tuple[float, float],
    resolution: float,
    tile_size: int,
) -> tuple[int, int, int, int]:
    min_x, min_y, max_x, max_y = bounds
    origin_x, origin_y = origin
    span = tile_size * resolution
    x_min = math.floor((min_x - origin_x) / span)
    x_max = math.ceil((max_x - origin_x) / span) - 1
    y_min = math.floor((origin_y - max_y) / span)
    y_max = math.ceil((origin_y - min_y) / span) - 1
    if x_max < x_min or y_max < y_min:
        raise ValueError("Bounds do not intersect tile grid.")
    return max(x_min, 0), max(y_min, 0), max(x_max, 0), max(y_max, 0)


def tile_bounds_for_index(
    origin: tuple[float, float],
    resolution: float,
    tile_size: int,
    x: int,
    y: int,
) -> tuple[float, float, float, float]:
    origin_x, origin_y = origin
    span = tile_size * resolution
    min_x = origin_x + x * span
    max_x = min_x + span
    max_y = origin_y - y * span
    min_y = max_y - span
    return (min_x, min_y, max_x, max_y)


def compute_origin(bounds: tuple[float, float, float, float]) -> tuple[float, float]:
    min_x, _, _, max_y = bounds
    return min_x, max_y
