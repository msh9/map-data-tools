from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from raster_tilemaker.config import (
    DEFAULT_FORMAT,
    DEFAULT_QUALITY,
    DEFAULT_TILE_SIZE,
)
from raster_tilemaker.grid import tile_bounds_for_index, tile_index_range

logger = logging.getLogger(__name__)


def load_gdal():
    from osgeo import gdal as gdal_module

    gdal_module.UseExceptions()
    return gdal_module


def ensure_format_support(tile_format: str) -> None:
    from PIL import features

    if tile_format == "png":
        return  # always supported by Pillow
    if tile_format == "avif" and not features.check("avif"):
        raise RuntimeError("AVIF support is missing. Install a Pillow build with AVIF support.")
    if tile_format == "webp" and not features.check("webp"):
        raise RuntimeError("WebP support is missing. Install a Pillow build with WebP support.")


@dataclass(frozen=True)
class VrtMetadata:
    path: Path
    crs_wkt: str
    bounds: tuple[float, float, float, float]
    band_count: int


@dataclass(frozen=True)
class RenderedTile:
    z: int
    x: int
    y: int
    tile_array: object
    has_data: bool


def _validate_supported_band_count(dataset, *, source_path: Path) -> int:
    band_count = dataset.RasterCount
    if band_count not in {1, 2, 3, 4}:
        raise ValueError(
            "Input VRT must have 1 (Gray), 2 (LA), 3 (RGB), or 4 (RGBA) bands; "
            f"found {band_count} band(s) in {source_path}."
        )
    return band_count


def _dataset_bounds(dataset) -> tuple[float, float, float, float]:
    geotransform = dataset.GetGeoTransform(can_return_null=True)
    if geotransform is None:
        raise ValueError("VRT is missing geotransform metadata.")
    x_size = dataset.RasterXSize
    y_size = dataset.RasterYSize

    corners = []
    for pixel_x, pixel_y in ((0, 0), (x_size, 0), (0, y_size), (x_size, y_size)):
        x = geotransform[0] + (pixel_x * geotransform[1]) + (pixel_y * geotransform[2])
        y = geotransform[3] + (pixel_x * geotransform[4]) + (pixel_y * geotransform[5])
        corners.append((x, y))

    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def read_vrt_metadata(path: Path) -> VrtMetadata:
    if not path.exists():
        raise FileNotFoundError(f"Input VRT not found: {path}")
    gdal = load_gdal()
    dataset = gdal.Open(str(path), gdal.GA_ReadOnly)
    if dataset is None:
        raise ValueError(f"Unable to open VRT: {path}")

    band_count = _validate_supported_band_count(dataset, source_path=path)
    crs_wkt = dataset.GetProjectionRef()
    if not crs_wkt:
        raise ValueError(f"Input VRT is missing projection metadata: {path}")
    bounds = _dataset_bounds(dataset)
    dataset = None
    return VrtMetadata(path=path, crs_wkt=crs_wkt, bounds=bounds, band_count=band_count)


def _read_tile_rgba(
    dataset,
    tile_bounds: tuple[float, float, float, float],
    tile_size: int,
):
    import numpy as np

    gdal = load_gdal()
    gdal.PushErrorHandler("CPLQuietErrorHandler")
    try:
        tile_dataset = gdal.Warp(
            "",
            dataset,
            format="MEM",
            outputBounds=tile_bounds,
            width=tile_size,
            height=tile_size,
            dstSRS=dataset.GetProjectionRef(),
            resampleAlg="cubic",
        )
    finally:
        gdal.PopErrorHandler()
    if tile_dataset is None:
        raise ValueError("Failed to read tile data from VRT.")

    raw_data = tile_dataset.ReadAsArray()
    if raw_data is None:
        raise ValueError("Failed to read tile array from VRT.")
    if raw_data.ndim == 2:
        raw_data = raw_data[np.newaxis, :, :]

    band_count = raw_data.shape[0]
    if band_count not in {3, 4}:
        raise ValueError(
            "Internal error: warped tile is not RGB/RGBA; " f"found {band_count} bands."
        )

    rgb = np.transpose(raw_data[:3], (1, 2, 0))
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)

    valid_mask = np.ones((tile_size, tile_size), dtype=bool)
    for band_index in range(1, band_count + 1):
        mask_band = tile_dataset.GetRasterBand(band_index).GetMaskBand()
        mask_data = mask_band.ReadAsArray()
        if mask_data is None:
            continue
        valid_mask = np.logical_and(valid_mask, mask_data > 0)

    if band_count == 4:
        alpha = np.clip(raw_data[3], 0, 255).astype(np.uint8)
    else:
        alpha = np.full((tile_size, tile_size), 255, dtype=np.uint8)

    alpha[~valid_mask] = 0

    tile_array = np.zeros((tile_size, tile_size, 4), dtype=np.uint8)
    tile_array[:, :, :3] = rgb
    tile_array[:, :, 3] = alpha
    has_data = bool((alpha > 0).any())

    tile_dataset = None
    return tile_array, has_data


def _read_tile_la(
    dataset,
    tile_bounds: tuple[float, float, float, float],
    tile_size: int,
):
    """Read a tile from a 1- or 2-band dataset as HxWx2 (luminance + alpha)."""
    import numpy as np

    gdal = load_gdal()
    gdal.PushErrorHandler("CPLQuietErrorHandler")
    try:
        tile_dataset = gdal.Warp(
            "",
            dataset,
            format="MEM",
            outputBounds=tile_bounds,
            width=tile_size,
            height=tile_size,
            dstSRS=dataset.GetProjectionRef(),
            resampleAlg="cubic",
        )
    finally:
        gdal.PopErrorHandler()
    if tile_dataset is None:
        raise ValueError("Failed to read tile data from VRT.")

    raw_data = tile_dataset.ReadAsArray()
    if raw_data is None:
        raise ValueError("Failed to read tile array from VRT.")
    if raw_data.ndim == 2:
        raw_data = raw_data[np.newaxis, :, :]

    band_count = raw_data.shape[0]
    luminance = np.clip(raw_data[0], 0, 255).astype(np.uint8)

    # Build validity mask from GDAL mask bands
    valid_mask = np.ones((tile_size, tile_size), dtype=bool)
    for band_index in range(1, band_count + 1):
        mask_band = tile_dataset.GetRasterBand(band_index).GetMaskBand()
        mask_data = mask_band.ReadAsArray()
        if mask_data is None:
            continue
        valid_mask = np.logical_and(valid_mask, mask_data > 0)

    if band_count == 2:
        alpha = np.clip(raw_data[1], 0, 255).astype(np.uint8)
    else:
        alpha = np.full((tile_size, tile_size), 255, dtype=np.uint8)

    alpha[~valid_mask] = 0

    tile_array = np.zeros((tile_size, tile_size, 2), dtype=np.uint8)
    tile_array[:, :, 0] = luminance
    tile_array[:, :, 1] = alpha
    has_data = bool((alpha > 0).any())

    tile_dataset = None
    return tile_array, has_data


def iter_rendered_mosaic_tiles(
    input_vrt: Path,
    *,
    tile_size: int = DEFAULT_TILE_SIZE,
    aggregate_bounds: tuple[float, float, float, float],
    origin: tuple[float, float],
    resolutions: list[float],
) -> Iterator[RenderedTile]:
    gdal = load_gdal()
    dataset = gdal.Open(str(input_vrt), gdal.GA_ReadOnly)
    if dataset is None:
        raise ValueError(f"Unable to open VRT: {input_vrt}")
    band_count = _validate_supported_band_count(dataset, source_path=input_vrt)
    read_tile = _read_tile_la if band_count in {1, 2} else _read_tile_rgba

    total_rendered = 0
    total_empty = 0
    try:
        for z, resolution in enumerate(resolutions):
            x_min, y_min, x_max, y_max = tile_index_range(
                aggregate_bounds, origin, resolution, tile_size
            )
            tile_count = (x_max - x_min + 1) * (y_max - y_min + 1)
            logger.info(
                "Rendering zoom level z=%d",
                z,
                extra={
                    "z": z,
                    "resolution_m_px": resolution,
                    "x_range": [x_min, x_max],
                    "y_range": [y_min, y_max],
                    "tile_count": tile_count,
                },
            )
            z_rendered = 0
            z_empty = 0
            for x in range(x_min, x_max + 1):
                for y in range(y_min, y_max + 1):
                    tile_bounds = tile_bounds_for_index(origin, resolution, tile_size, x, y)
                    tile_array, has_data = read_tile(
                        dataset,
                        tile_bounds,
                        tile_size,
                    )
                    yield RenderedTile(
                        z=z,
                        x=x,
                        y=y,
                        tile_array=tile_array,
                        has_data=has_data,
                    )
                    if has_data:
                        z_rendered += 1
                    else:
                        z_empty += 1
            total_rendered += z_rendered
            total_empty += z_empty
            logger.info(
                "Zoom level z=%d complete",
                z,
                extra={"z": z, "tiles_rendered": z_rendered, "tiles_skipped_empty": z_empty},
            )
            if z_rendered == 0:
                logger.warning(
                    "Zoom level z=%d produced no data tiles — source may not overlap this resolution",
                    z,
                    extra={"z": z, "resolution_m_px": resolution},
                )
    finally:
        dataset = None
    logger.info(
        "Tile iteration complete",
        extra={
            "total_tiles_rendered": total_rendered,
            "total_tiles_skipped_empty": total_empty,
            "n_zoom_levels": len(resolutions),
        },
    )


def render_mosaic_tiles(
    input_vrt: Path,
    output_dir: Path,
    *,
    tile_size: int = DEFAULT_TILE_SIZE,
    quality: int = DEFAULT_QUALITY,
    tile_format: str = DEFAULT_FORMAT,
    aggregate_bounds: tuple[float, float, float, float],
    origin: tuple[float, float],
    resolutions: list[float],
) -> None:
    from PIL import Image

    ensure_format_support(tile_format)
    output_dir.mkdir(parents=True, exist_ok=True)

    tiles_written = 0
    for tile in iter_rendered_mosaic_tiles(
        input_vrt,
        tile_size=tile_size,
        aggregate_bounds=aggregate_bounds,
        origin=origin,
        resolutions=resolutions,
    ):
        channels = tile.tile_array.shape[2]
        mode = "LA" if channels == 2 else "RGBA"
        image = Image.fromarray(tile.tile_array, mode=mode)
        tile_dir = output_dir / "tiles" / str(tile.z) / str(tile.x)
        tile_dir.mkdir(parents=True, exist_ok=True)
        tile_path = tile_dir / f"{tile.y}.{tile_format}"
        image.save(tile_path, format=tile_format.upper(), quality=quality)
        tiles_written += 1
    logger.info(
        "ZXY tile render complete",
        extra={
            "tiles_written": tiles_written,
            "tile_format": tile_format,
            "output_dir": str(output_dir),
        },
    )


# ── Parallel render+encode support ───────────────────────────────────────────

# Module-level state populated by _worker_init in each worker process.
_worker_dataset = None
_worker_read_tile = None


def _worker_init(vrt_path: str, band_count: int) -> None:
    """ProcessPoolExecutor initializer: opens the VRT once per worker process."""
    global _worker_dataset, _worker_read_tile
    gdal = load_gdal()
    _worker_dataset = gdal.Open(vrt_path, gdal.GA_ReadOnly)
    if _worker_dataset is None:
        raise RuntimeError(f"Worker process failed to open VRT: {vrt_path}")
    _worker_read_tile = _read_tile_la if band_count in {1, 2} else _read_tile_rgba


def render_and_encode_tile(
    tile_bounds: tuple[float, float, float, float],
    z: int,
    x: int,
    y: int,
    *,
    tile_size: int,
    tile_format: str,
    quality: int,
) -> tuple[int, int, int, bool, bytes]:
    """Render and encode one tile. Called inside a ProcessPoolExecutor worker."""
    import io as _io

    from PIL import Image

    tile_array, has_data = _worker_read_tile(_worker_dataset, tile_bounds, tile_size)
    if not has_data:
        return z, x, y, False, b""

    channels = tile_array.shape[2]
    mode = "LA" if channels == 2 else ("RGBA" if channels == 4 else "RGB")
    image = Image.fromarray(tile_array, mode=mode)
    buf = _io.BytesIO()
    image.save(buf, format=tile_format.upper(), quality=quality)
    return z, x, y, True, buf.getvalue()


def iter_tile_specs(
    aggregate_bounds: tuple[float, float, float, float],
    origin: tuple[float, float],
    resolutions: list[float],
    tile_size: int,
) -> Iterator[tuple[int, int, int, tuple[float, float, float, float]]]:
    """Yield (z, x, y, tile_bounds) for every tile without performing any GDAL operations."""
    for z, resolution in enumerate(resolutions):
        x_min, y_min, x_max, y_max = tile_index_range(
            aggregate_bounds, origin, resolution, tile_size
        )
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                yield z, x, y, tile_bounds_for_index(origin, resolution, tile_size, x, y)
