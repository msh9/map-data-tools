"""Verify the tilemaker pipeline preserves uint8 luminance values for LA PNG tiles."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from raster_tilemaker import build_tiles

from osgeo import gdal, osr


def _create_la_tif_full_tile(path: Path, values: list[int]) -> None:
    """Create a 2-band GeoTIFF that fills an entire tile at resolution 2560.

    Tile span at 2560 m/px with 512 px = 1,310,720 m.
    The source is 512x512 so each source pixel = 2560m (1:1 with tile pixels).
    Horizontal stripes encode known luminance values.
    """
    size = 512
    tile_span = 2560.0 * size  # 1,310,720 m

    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(str(path), size, size, 2, gdal.GDT_Byte)
    if dataset is None:
        raise RuntimeError("Failed to create test GeoTIFF.")

    min_x = -2000000.0
    max_y = 1100000.0
    pixel_size = tile_span / size  # 2560.0

    dataset.SetGeoTransform((min_x, pixel_size, 0.0, max_y, 0.0, -pixel_size))
    srs = osr.SpatialReference()
    srs.SetFromUserInput("ESRI:102009")
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dataset.SetProjection(srs.ExportToWkt())

    # Write luminance: horizontal stripes with each value
    lum = np.zeros((size, size), dtype=np.uint8)
    stripe_height = size // len(values)
    for i, val in enumerate(values):
        lum[i * stripe_height : (i + 1) * stripe_height, :] = val

    # Fully opaque alpha
    alpha = np.full((size, size), 255, dtype=np.uint8)

    dataset.GetRasterBand(1).WriteArray(lum)
    dataset.GetRasterBand(2).WriteArray(alpha)
    dataset = None


@pytest.fixture(scope="module", autouse=True)
def _enable_gdal_exceptions() -> None:
    gdal.UseExceptions()


def test_la_png_preserves_luminance_values(tmp_path: Path) -> None:
    """Known uint8 luminance values survive the full tilemaker pipeline as PNG."""
    test_values = [0, 10, 20, 30, 40, 128, 255]
    tif_path = tmp_path / "slope_la.tif"
    vrt_path = tmp_path / "slope_la.vrt"
    output_dir = tmp_path / "out"

    _create_la_tif_full_tile(tif_path, test_values)
    vrt = gdal.BuildVRT(str(vrt_path), [str(tif_path)])
    assert vrt is not None
    vrt = None

    exit_code = build_tiles.main(
        [
            "--input-vrt",
            str(vrt_path),
            "--output-dir",
            str(output_dir),
            "--format",
            "png",
            "--resolution",
            "2560",
        ]
    )
    assert exit_code == 0

    tile_path = output_dir / "tiles" / "0" / "0" / "0.png"
    assert tile_path.exists()

    with Image.open(tile_path) as image:
        assert image.mode == "LA"
        lum_channel = np.array(image.getchannel("L"))

    # Source is 512x512 at 2560 m/px matching the tile exactly (1:1).
    # Cubic resampling at 1:1 should preserve values exactly.
    stripe_height = 512 // len(test_values)
    for i, expected in enumerate(test_values):
        center_row = i * stripe_height + stripe_height // 2
        sampled = int(lum_channel[center_row, 256])
        assert abs(sampled - expected) <= 1, f"Stripe {i}: expected ~{expected}, got {sampled}"
