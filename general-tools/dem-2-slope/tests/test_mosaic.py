"""Tests for VRT mosaic assembly."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from osgeo import gdal, osr

from dem_2_slope.mosaic import build_vrt

gdal.UseExceptions()


def _create_rgba_cog(
    path: Path,
    *,
    origin_x: float,
    origin_y: float,
    rows: int = 16,
    cols: int = 16,
    pixel_size: float = 100.0,
) -> Path:
    """Create a small 4-band RGBA GeoTIFF in ESRI:102009."""
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(str(path), cols, rows, 4, gdal.GDT_Byte)
    ds.SetGeoTransform((origin_x, pixel_size, 0, origin_y, 0, -pixel_size))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())

    for band_idx in range(1, 5):
        band = ds.GetRasterBand(band_idx)
        data = np.full((rows, cols), band_idx * 50, dtype=np.uint8)
        band.WriteArray(data)
    ds.FlushCache()
    ds = None
    return path


class TestBuildVrt:
    def test_build_vrt_over_multiple_cogs(self, tmp_path: Path) -> None:
        """Create 2 small COGs with different extents. Verify VRT properties."""
        cog1 = _create_rgba_cog(
            tmp_path / "tile1.tif",
            origin_x=0.0,
            origin_y=3200.0,
        )
        cog2 = _create_rgba_cog(
            tmp_path / "tile2.tif",
            origin_x=1600.0,
            origin_y=3200.0,
        )

        vrt_path = build_vrt([cog1, cog2], tmp_path)

        assert vrt_path.exists()
        assert vrt_path.name == "slope-mosaic.vrt"

        ds = gdal.Open(str(vrt_path))
        assert ds is not None
        assert ds.RasterCount == 4

        # VRT should span the combined extent of both COGs
        gt = ds.GetGeoTransform()
        vrt_min_x = gt[0]
        vrt_max_x = gt[0] + gt[1] * ds.RasterXSize
        assert vrt_min_x <= 0.0
        assert vrt_max_x >= 1600.0 + 16 * 100.0  # cog2 right edge

        ds = None

    def test_build_vrt_custom_name(self, tmp_path: Path) -> None:
        """build_vrt should use the supplied vrt_name instead of the default."""
        cog = _create_rgba_cog(tmp_path / "tile1.tif", origin_x=0.0, origin_y=3200.0)
        vrt_path = build_vrt([cog], tmp_path, vrt_name="my-slope.vrt")
        assert vrt_path.name == "my-slope.vrt"
        assert vrt_path.exists()
