"""Per-tile slope computation, thresholding, RGBA expansion, clipping, and COG output."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import numpy as np
from osgeo import gdal

logger = logging.getLogger(__name__)

TARGET_CRS = "ESRI:102009"

COG_CREATION_OPTIONS = [
    "COMPRESS=ZSTD",
    "LEVEL=18",
    "BLOCKSIZE=512",
]


def resolve_input(source: str | Path) -> str:
    """Resolve a URL or local path to a GDAL-readable path.

    HTTP(S) URLs are prefixed with ``/vsicurl/`` so GDAL streams directly
    from the remote COG.  Local paths are returned as-is.
    """
    source_str = str(source)
    if source_str.startswith("http://") or source_str.startswith("https://"):
        return f"/vsicurl/{source_str}"
    return source_str


def compute_slope(input_path: str | Path, output_path: str | Path) -> gdal.Dataset:
    """Run GDAL DEMProcessing to compute slope in degrees.

    Returns the opened output dataset.
    """
    slope_ds = gdal.DEMProcessing(
        str(output_path),
        str(input_path),
        "slope",
        slopeFormat="degree",
    )
    if slope_ds is None:
        raise RuntimeError(f"DEMProcessing failed for {input_path}")
    return slope_ds


def smooth_slope(slope_array: np.ndarray, kernel_size: int) -> np.ndarray:
    """Apply a uniform (box) moving average to the slope array.

    Uses a cumulative-sum based summed-area table for O(N) performance
    regardless of kernel size.  Edge pixels are padded by replication to
    avoid artificial reduction at boundaries.

    Returns a float32 array of the same shape.
    """
    if kernel_size <= 1:
        return slope_array

    rows, cols = slope_array.shape
    pad = kernel_size // 2
    padded = np.pad(slope_array, pad, mode="edge").astype(np.float64)

    # Build summed-area table with a leading zero row and column so that
    # the box-sum formula works without boundary checks.
    cum = np.cumsum(np.cumsum(padded, axis=0), axis=1)
    sat = np.zeros((cum.shape[0] + 1, cum.shape[1] + 1), dtype=np.float64)
    sat[1:, 1:] = cum

    k = kernel_size
    box_sum = (
        sat[k : k + rows, k : k + cols]
        - sat[0:rows, k : k + cols]
        - sat[k : k + rows, 0:cols]
        + sat[0:rows, 0:cols]
    )
    return (box_sum / (k * k)).astype(np.float32)


def threshold_to_uint8(slope_array: np.ndarray, threshold: float) -> np.ndarray:
    """Apply slope threshold and convert to uint8.

    Pixels with slope < threshold become 0.  Remaining values are clamped to
    the 1-255 range (using ceiling) and cast to uint8.
    """
    result = slope_array.copy()
    result[result < threshold] = 0.0
    mask = result > 0
    # Clamp to 1-255: ceiling ensures any positive value is at least 1
    result[mask] = np.clip(np.ceil(result[mask]), 1, 255)
    return result.astype(np.uint8)


def build_rgba(slope_uint8: np.ndarray) -> np.ndarray:
    """Expand a single-band uint8 slope array to a 4-band RGBA array.

    R = G = B = slope_value, A = 255 where slope > 0 else 0.
    Returns shape (4, rows, cols).
    """
    alpha = np.where(slope_uint8 > 0, np.uint8(255), np.uint8(0))
    return np.stack([slope_uint8, slope_uint8, slope_uint8, alpha], axis=0)


def build_la(slope_uint8: np.ndarray) -> np.ndarray:
    """Expand a single-band uint8 slope array to a 2-band LA array.

    L = slope_value, A = 255 where slope > 0 else 0.
    Returns shape (2, rows, cols).
    """
    alpha = np.where(slope_uint8 > 0, np.uint8(255), np.uint8(0))
    return np.stack([slope_uint8, alpha], axis=0)


def _write_la_dataset(la: np.ndarray, geo_transform, projection, path: str) -> None:
    """Write a 2-band LA array to a GeoTIFF at *path* (disk or /vsimem/)."""
    _, y_size, x_size = la.shape
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(path, x_size, y_size, 2, gdal.GDT_Byte)
    ds.SetGeoTransform(geo_transform)
    ds.SetProjection(projection)
    ds.GetRasterBand(1).WriteArray(la[0])
    band2 = ds.GetRasterBand(2)
    band2.WriteArray(la[1])
    band2.SetColorInterpretation(gdal.GCI_AlphaBand)
    ds.FlushCache()
    ds = None  # close


def process_tile(
    input_path: str | Path,
    output_path: str | Path,
    threshold: float,
    clip_regions_path: str | Path,
    *,
    stream: bool = False,
    smooth_kernel: int | None = None,
) -> Path:
    """Full per-tile processing pipeline.

    1. Compute slope
    2. Optionally smooth with an NxN moving average
    3. Threshold + convert to uint8
    4. Build 2-band LA (luminance + alpha)
    5. Clip to mountainous regions + reproject to ESRI:102009
    6. Write as ZSTD COG

    When *stream* is True the input is read via ``/vsicurl/`` (for HTTP URLs)
    and all intermediate data is kept in GDAL's ``/vsimem/`` RAM filesystem,
    avoiding any temporary disk I/O.  When False (default), intermediates are
    written to disk alongside the output and cleaned up afterward.

    Returns the output COG path.
    """
    output_path = Path(output_path)
    clip_regions_path = Path(clip_regions_path)

    if stream:
        gdal_input = resolve_input(input_path)
        tag = uuid.uuid4().hex[:8]
        slope_path = f"/vsimem/{tag}_slope.tif"
        intermediate_path = f"/vsimem/{tag}_la.tif"
    else:
        gdal_input = str(input_path)
        input_stem = Path(str(input_path)).stem
        slope_path = str(output_path.parent / f"{input_stem}_slope.tif")
        intermediate_path = str(output_path.parent / f"{input_stem}_la.tif")

    try:
        # Step 1: Compute slope
        logger.info("Computing slope for %s", input_path)
        slope_ds = compute_slope(gdal_input, slope_path)
        slope_band = slope_ds.GetRasterBand(1)
        slope_array = slope_band.ReadAsArray()
        geo_transform = slope_ds.GetGeoTransform()
        projection = slope_ds.GetProjection()
        slope_ds = None  # close

        # Step 2: Smooth (optional)
        if smooth_kernel is not None and smooth_kernel > 1:
            logger.info("Smoothing with %dx%d kernel", smooth_kernel, smooth_kernel)
            slope_array = smooth_slope(slope_array, smooth_kernel)

        # Step 3: Threshold
        logger.info("Applying threshold %.1f degrees", threshold)
        slope_uint8 = threshold_to_uint8(slope_array, threshold)

        # Step 4: Build LA
        la = build_la(slope_uint8)

        # Step 5: Write intermediate LA GeoTIFF
        _write_la_dataset(la, geo_transform, projection, intermediate_path)

        # Step 6: Clip + reproject + write COG
        logger.info("Clipping and reprojecting to %s", TARGET_CRS)
        warp_options = gdal.WarpOptions(
            cutlineDSName=str(clip_regions_path),
            dstSRS=TARGET_CRS,
            dstNodata=0,
            resampleAlg="near",
            format="COG",
            creationOptions=COG_CREATION_OPTIONS,
        )
        warped_ds = gdal.Warp(str(output_path), intermediate_path, options=warp_options)
        if warped_ds is None:
            raise RuntimeError(f"gdal.Warp failed for {intermediate_path}")
        warped_ds = None  # close

        logger.info("Wrote COG: %s", output_path)
        return output_path

    finally:
        # Clean up intermediate files
        if stream:
            for vsimem_path in (slope_path, intermediate_path):
                gdal.Unlink(vsimem_path)
        else:
            for disk_path in (Path(slope_path), Path(intermediate_path)):
                if disk_path.exists():
                    disk_path.unlink()
