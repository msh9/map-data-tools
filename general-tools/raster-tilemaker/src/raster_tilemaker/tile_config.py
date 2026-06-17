from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

from raster_tilemaker.config import DEFAULT_FORMAT, DEFAULT_TILE_SIZE, TILE_CONFIG_NAME

logger = logging.getLogger(__name__)


def _transform_bounds_to_wgs84(
    bounds: tuple[float, float, float, float],
    src_crs_wkt: str,
    *,
    densify_pts: int = 21,
) -> tuple[float, float, float, float]:
    logger.info(
        "Transforming bounds to WGS84",
        extra={"src_bounds_crs": list(bounds), "densify_pts": densify_pts},
    )
    from osgeo import osr

    min_x, min_y, max_x, max_y = bounds

    src = osr.SpatialReference()
    src.SetFromUserInput(src_crs_wkt)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    dst = osr.SpatialReference()
    dst.SetFromUserInput("EPSG:4326")
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    transform = osr.CoordinateTransformation(src, dst)

    points: list[tuple[float, float]] = []
    for index in range(densify_pts + 1):
        ratio = index / densify_pts
        x = min_x + (max_x - min_x) * ratio
        y = min_y + (max_y - min_y) * ratio
        points.extend(
            [
                (x, min_y),
                (x, max_y),
                (min_x, y),
                (max_x, y),
            ]
        )

    longitudes: list[float] = []
    latitudes: list[float] = []
    for x, y in points:
        lon, lat, _ = transform.TransformPoint(x, y)
        longitudes.append(lon)
        latitudes.append(lat)

    wgs84 = (min(longitudes), min(latitudes), max(longitudes), max(latitudes))
    logger.info("Bounds transformed to WGS84", extra={"wgs84_extent": list(wgs84)})
    return wgs84


def build_tile_config(
    crs_wkt: str,
    aggregate_bounds_crs: tuple[float, float, float, float],
    resolutions: Iterable[float],
    origin: tuple[float, float],
    *,
    tile_size: int = DEFAULT_TILE_SIZE,
    tile_format: str = DEFAULT_FORMAT,
) -> dict:
    resolutions_list = list(resolutions)
    if not resolutions_list:
        raise ValueError("At least one resolution is required.")

    min_x, min_y, max_x, max_y = aggregate_bounds_crs
    aggregate_wgs84 = _transform_bounds_to_wgs84(aggregate_bounds_crs, crs_wkt)
    origin_x, origin_y = origin

    return {
        "schemaVersion": "1.0",
        "crs": {
            "type": "wkt",
            "value": crs_wkt,
        },
        "tile": {
            "tileSizePx": tile_size,
            "format": tile_format,
            "origin": [origin_x, origin_y],
            "resolutions": resolutions_list,
        },
        "extent": {
            "crsUnits": [min_x, min_y, max_x, max_y],
            "wgs84": list(aggregate_wgs84),
        },
        "sources": [],
    }


def write_tile_config(
    output_dir: Path,
    config: dict,
    *,
    file_name: str = TILE_CONFIG_NAME,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / file_name
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path
