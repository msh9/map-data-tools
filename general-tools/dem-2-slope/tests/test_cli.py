"""Tests for the CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from osgeo import gdal, osr

from dem_2_slope.cli import main

gdal.UseExceptions()


def _create_synthetic_dem(path: Path) -> Path:
    """Write a small synthetic DEM in EPSG:4326."""
    rows, cols = 32, 32
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(str(path), cols, rows, 1, gdal.GDT_Float32)
    pixel_size = 1.0 / 3600
    ds.SetGeoTransform((-112.0, pixel_size, 0, 41.0, 0, -pixel_size))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())

    elevation = np.zeros((rows, cols), dtype=np.float32)
    for c in range(cols):
        elevation[:, c] = c * 100.0
    ds.GetRasterBand(1).WriteArray(elevation)
    ds.FlushCache()
    ds = None
    return path


def _create_clip_geojson(path: Path) -> Path:
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-113.0, 40.0],
                            [-111.0, 40.0],
                            [-111.0, 42.0],
                            [-113.0, 42.0],
                            [-113.0, 40.0],
                        ]
                    ],
                },
            }
        ],
    }
    path.write_text(json.dumps(geojson))
    return path


class TestCliRequiredArgs:
    def test_cli_requires_slope_threshold_exits(self) -> None:
        """Verify argparse raises SystemExit for missing required args."""
        import pytest

        with pytest.raises(SystemExit) as exc_info:
            main(
                [
                    "--url-list",
                    "urls.txt",
                    "--clip-regions",
                    "r.geojson",
                    "--output-dir",
                    "/tmp/out",
                ]
            )
        assert exc_info.value.code == 2


class TestCliEndToEnd:
    def test_cli_end_to_end_local_file(self, tmp_path: Path) -> None:
        """Create a synthetic DEM locally, run main(), verify outputs."""
        dem_path = _create_synthetic_dem(tmp_path / "test_dem.tif")
        clip_path = _create_clip_geojson(tmp_path / "clip.geojson")
        output_dir = tmp_path / "output"

        url_list = tmp_path / "urls.txt"
        url_list.write_text(str(dem_path) + "\n")

        result = main(
            [
                "--url-list",
                str(url_list),
                "--slope-threshold",
                "5.0",
                "--clip-regions",
                str(clip_path),
                "--output-dir",
                str(output_dir),
            ]
        )

        assert result == 0

        # Verify output COG exists and has 2 bands (LA)
        cog_files = list(output_dir.glob("*_slope.cog.tif"))
        assert len(cog_files) == 1
        ds = gdal.Open(str(cog_files[0]))
        assert ds.RasterCount == 2
        ds = None

        # Verify VRT exists with the default name
        vrt_files = list(output_dir.glob("*.vrt"))
        assert len(vrt_files) == 1
        assert vrt_files[0].name == "slope-mosaic.vrt"

    def test_cli_custom_vrt_name(self, tmp_path: Path) -> None:
        """--vrt-name should control the output VRT filename."""
        dem_path = _create_synthetic_dem(tmp_path / "test_dem.tif")
        clip_path = _create_clip_geojson(tmp_path / "clip.geojson")
        output_dir = tmp_path / "output"

        url_list = tmp_path / "urls.txt"
        url_list.write_text(str(dem_path) + "\n")

        result = main(
            [
                "--url-list",
                str(url_list),
                "--slope-threshold",
                "5.0",
                "--clip-regions",
                str(clip_path),
                "--output-dir",
                str(output_dir),
                "--vrt-name",
                "custom.vrt",
            ]
        )

        assert result == 0
        assert (output_dir / "custom.vrt").exists()
        assert not (output_dir / "slope-mosaic.vrt").exists()

    def test_cli_smooth_kernel_argument(self, tmp_path: Path) -> None:
        """--smooth-kernel should apply smoothing and produce valid output."""
        dem_path = _create_synthetic_dem(tmp_path / "test_dem.tif")
        clip_path = _create_clip_geojson(tmp_path / "clip.geojson")
        output_dir = tmp_path / "output"

        url_list = tmp_path / "urls.txt"
        url_list.write_text(str(dem_path) + "\n")

        result = main(
            [
                "--url-list",
                str(url_list),
                "--slope-threshold",
                "5.0",
                "--clip-regions",
                str(clip_path),
                "--output-dir",
                str(output_dir),
                "--smooth-kernel",
                "4",
            ]
        )

        assert result == 0
        cog_files = list(output_dir.glob("*_slope.cog.tif"))
        assert len(cog_files) == 1
