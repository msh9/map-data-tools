"""Tests for per-tile COG output and VRT construction."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from osgeo import gdal, osr

from sentinel_mosaic.composite import (
    TARGET_CRS,
    build_per_region_vrt,
    build_top_level_vrt,
    finalize_output_tile,
    finalize_single_cog,
)

gdal.UseExceptions()


def _create_rgba_geotiff(
    path: str,
    *,
    origin_x: float,
    origin_y: float,
    rows: int = 16,
    cols: int = 16,
    pixel_size: float = 0.01,
    red_val: int = 100,
    green_val: int = 150,
    blue_val: int = 200,
    alpha_val: int = 255,
) -> str:
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(path, cols, rows, 4, gdal.GDT_Byte)
    ds.SetGeoTransform((origin_x, pixel_size, 0, origin_y, 0, -pixel_size))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(np.full((rows, cols), red_val, dtype=np.uint8))
    ds.GetRasterBand(2).WriteArray(np.full((rows, cols), green_val, dtype=np.uint8))
    ds.GetRasterBand(3).WriteArray(np.full((rows, cols), blue_val, dtype=np.uint8))
    ds.GetRasterBand(4).WriteArray(np.full((rows, cols), alpha_val, dtype=np.uint8))
    ds.GetRasterBand(4).SetColorInterpretation(gdal.GCI_AlphaBand)
    ds.FlushCache()
    ds = None
    return path


def _create_clip_geojson(path: Path, region_name: str, bounds: tuple) -> Path:
    min_x, min_y, max_x, max_y = bounds
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"region-name": region_name},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [min_x, min_y],
                                    [max_x, min_y],
                                    [max_x, max_y],
                                    [min_x, max_y],
                                    [min_x, min_y],
                                ]
                            ],
                        },
                    }
                ],
            }
        )
    )
    return path


class TestFinalizeOutputTile:
    def test_produces_cog_at_expected_path(self, tmp_path: Path) -> None:
        clip = _create_clip_geojson(tmp_path / "clip.geojson", "r", (-112.0, 40.0, -111.0, 41.0))
        tile_dir = tmp_path / "r_2024-Q3"
        tile_dir.mkdir()
        tile_path = _create_rgba_geotiff(
            str(tmp_path / "tile.tif"),
            origin_x=-111.8,
            origin_y=40.8,
            rows=8,
            cols=8,
            pixel_size=0.05,
        )

        result = finalize_output_tile(tile_path, "T00", clip, "r", tile_dir, pixel_size=1000.0)

        assert result == tile_dir / "T00.cog.tif"
        assert result.exists()

    def test_output_is_in_target_crs(self, tmp_path: Path) -> None:
        clip = _create_clip_geojson(tmp_path / "clip.geojson", "r", (-112.0, 40.0, -111.0, 41.0))
        tile_dir = tmp_path / "r_2024-Q3"
        tile_dir.mkdir()
        tile_path = _create_rgba_geotiff(
            str(tmp_path / "tile.tif"),
            origin_x=-111.8,
            origin_y=40.8,
            rows=8,
            cols=8,
            pixel_size=0.05,
        )

        result = finalize_output_tile(tile_path, "T00", clip, "r", tile_dir, pixel_size=1000.0)

        ds = gdal.Open(str(result))
        try:
            out_srs = osr.SpatialReference()
            out_srs.ImportFromWkt(ds.GetProjection())
            target_srs = osr.SpatialReference()
            target_srs.SetFromUserInput(TARGET_CRS)
            assert out_srs.IsSame(target_srs), f"Expected {TARGET_CRS}, got {ds.GetProjection()}"
        finally:
            ds = None

    def test_output_has_four_bands(self, tmp_path: Path) -> None:
        clip = _create_clip_geojson(tmp_path / "clip.geojson", "r", (-112.0, 40.0, -111.0, 41.0))
        tile_dir = tmp_path / "r_2024-Q3"
        tile_dir.mkdir()
        tile_path = _create_rgba_geotiff(
            str(tmp_path / "tile.tif"),
            origin_x=-111.8,
            origin_y=40.8,
            rows=8,
            cols=8,
            pixel_size=0.05,
        )

        result = finalize_output_tile(tile_path, "T00", clip, "r", tile_dir, pixel_size=1000.0)

        ds = gdal.Open(str(result))
        try:
            assert ds.RasterCount == 4
        finally:
            ds = None

    def test_cutline_crops_extent_to_region(self, tmp_path: Path) -> None:
        # A clip region covering half the source tile's extent should produce
        # an output smaller than finalizing with the full extent clip region.
        full_clip = _create_clip_geojson(
            tmp_path / "full_clip.geojson", "r", (-112.0, 40.0, -111.0, 41.0)
        )
        half_clip = _create_clip_geojson(
            tmp_path / "half_clip.geojson", "r", (-111.5, 40.5, -111.0, 41.0)
        )
        tile_dir = tmp_path / "r_2024-Q3"
        tile_dir.mkdir()

        # Source tile covers the entire 1°×1° clip region.
        tile_path = _create_rgba_geotiff(
            str(tmp_path / "tile.tif"),
            origin_x=-112.0,
            origin_y=41.0,
            rows=100,
            cols=100,
            pixel_size=0.01,
        )

        full_result = finalize_output_tile(
            tile_path, "FULL", full_clip, "r", tile_dir, pixel_size=1000.0
        )
        half_result = finalize_output_tile(
            tile_path, "HALF", half_clip, "r", tile_dir, pixel_size=1000.0
        )

        full_ds = gdal.Open(str(full_result))
        half_ds = gdal.Open(str(half_result))
        try:
            full_pixels = full_ds.RasterXSize * full_ds.RasterYSize
            half_pixels = half_ds.RasterXSize * half_ds.RasterYSize
            assert half_pixels < full_pixels, (
                f"half-region output ({half_pixels}px) should be smaller "
                f"than full-region output ({full_pixels}px)"
            )
        finally:
            full_ds = None
            half_ds = None


class TestBuildPerRegionVrt:
    def _make_tile(self, path: Path) -> Path:
        _create_rgba_geotiff(
            str(path), origin_x=-111.8, origin_y=40.8, rows=4, cols=4, pixel_size=0.05
        )
        return path

    def test_vrt_at_expected_path(self, tmp_path: Path) -> None:
        out = tmp_path / "output"
        out.mkdir()
        tile_dir = out / "r_2024-Q3"
        tile_dir.mkdir()
        t0 = self._make_tile(tile_dir / "T0.cog.tif")

        vrt = build_per_region_vrt([t0], out, "r", "2024-Q3")

        assert vrt == out / "r_2024-Q3.vrt"
        assert vrt.exists()

    def test_source_filenames_are_relative_to_vrt(self, tmp_path: Path) -> None:
        out = tmp_path / "output"
        out.mkdir()
        tile_dir = out / "r_2024-Q3"
        tile_dir.mkdir()
        t0 = self._make_tile(tile_dir / "T0.cog.tif")

        vrt = build_per_region_vrt([t0], out, "r", "2024-Q3")

        root = ET.parse(vrt).getroot()
        sources = root.findall(".//SourceFilename")
        assert sources
        for src in sources:
            assert src.text is not None
            assert src.get("relativeToVRT") == "1", f"expected relativeToVRT=1, got {src.attrib}"
            assert not Path(src.text).is_absolute(), f"expected relative path, got {src.text!r}"
            assert (out / src.text).exists(), f"relative path {src.text!r} does not resolve"

    def test_sources_in_reverse_order_for_last_wins(self, tmp_path: Path) -> None:
        # GDAL VRT compositing is first-source-wins; reversing the tile list
        # makes the last STAC-returned tile appear first in the VRT.
        out = tmp_path / "output"
        out.mkdir()
        tile_dir = out / "r_2024-Q3"
        tile_dir.mkdir()
        t0 = self._make_tile(tile_dir / "T0.cog.tif")
        t1 = self._make_tile(tile_dir / "T1.cog.tif")
        t2 = self._make_tile(tile_dir / "T2.cog.tif")

        vrt = build_per_region_vrt([t0, t1, t2], out, "r", "2024-Q3")

        root = ET.parse(vrt).getroot()
        sources = root.findall(".//SourceFilename")
        filenames = [Path(src.text).name for src in sources if src.text is not None]
        # Deduplicate preserving order (BuildVRT lists each file once per band).
        seen: list[str] = []
        for fn in filenames:
            if fn not in seen:
                seen.append(fn)
        assert seen.index("T2.cog.tif") < seen.index("T0.cog.tif"), (
            f"T2 (last STAC tile) must appear before T0 in VRT for last-wins; order: {seen}"
        )


class TestBuildTopLevelVrt:
    def _make_region_vrt(self, path: Path, tile_path: Path) -> Path:
        _create_rgba_geotiff(
            str(tile_path), origin_x=-111.8, origin_y=40.8, rows=4, cols=4, pixel_size=0.05
        )
        vrt_ds = gdal.BuildVRT(str(path), [str(tile_path)])
        vrt_ds.FlushCache()
        vrt_ds = None
        return path

    def test_vrt_at_expected_path(self, tmp_path: Path) -> None:
        out = tmp_path / "output"
        out.mkdir()
        vrt_a = self._make_region_vrt(out / "a_2024-Q3.vrt", out / "a.tif")

        top = build_top_level_vrt([vrt_a], out, "2024-Q3-sentinel-mosaic.vrt")

        assert top == out / "2024-Q3-sentinel-mosaic.vrt"
        assert top.exists()

    def test_references_per_region_vrts_with_relative_paths(self, tmp_path: Path) -> None:
        out = tmp_path / "output"
        out.mkdir()
        vrt_a = self._make_region_vrt(out / "a_2024-Q3.vrt", out / "a.tif")
        vrt_b = self._make_region_vrt(out / "b_2024-Q3.vrt", out / "b.tif")

        top = build_top_level_vrt([vrt_a, vrt_b], out, "2024-Q3-sentinel-mosaic.vrt")

        root = ET.parse(top).getroot()
        sources = root.findall(".//SourceFilename")
        assert sources
        for src in sources:
            assert src.text is not None
            assert src.get("relativeToVRT") == "1", f"expected relativeToVRT=1, got {src.attrib}"
            assert not Path(src.text).is_absolute(), f"expected relative path, got {src.text!r}"


class TestFinalizeSingleCog:
    def _make_tile(self, path: str) -> str:
        return _create_rgba_geotiff(
            path, origin_x=-111.8, origin_y=40.8, rows=8, cols=8, pixel_size=0.05
        )

    def test_produces_cog_at_expected_path(self, tmp_path: Path) -> None:
        tile_path = self._make_tile(str(tmp_path / "tile.tif"))
        output = tmp_path / "out.cog.tif"

        result = finalize_single_cog(tile_path, output, pixel_size=1000.0)

        assert result == output
        assert output.exists()

    def test_output_is_in_target_crs(self, tmp_path: Path) -> None:
        tile_path = self._make_tile(str(tmp_path / "tile.tif"))
        output = tmp_path / "out.cog.tif"

        finalize_single_cog(tile_path, output, pixel_size=1000.0)

        ds = gdal.Open(str(output))
        try:
            out_srs = osr.SpatialReference()
            out_srs.ImportFromWkt(ds.GetProjection())
            target_srs = osr.SpatialReference()
            target_srs.SetFromUserInput(TARGET_CRS)
            assert out_srs.IsSame(target_srs), f"Expected {TARGET_CRS}, got {ds.GetProjection()}"
        finally:
            ds = None

    def test_output_has_four_bands(self, tmp_path: Path) -> None:
        tile_path = self._make_tile(str(tmp_path / "tile.tif"))
        output = tmp_path / "out.cog.tif"

        finalize_single_cog(tile_path, output, pixel_size=1000.0)

        ds = gdal.Open(str(output))
        try:
            assert ds.RasterCount == 4
        finally:
            ds = None
