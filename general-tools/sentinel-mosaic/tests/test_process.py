"""Tests for tile processing (read → stretch → write)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from osgeo import gdal, osr

from unittest.mock import patch

from sentinel_mosaic.process import (
    DEFAULT_TONE_MAP,
    ToneMapParams,
    _resolve_gdal_path,
    process_bands,
    process_tile,
    true_color,
)
from sentinel_mosaic.search import MosaicTile

gdal.UseExceptions()


def _make_band(path: str, fill: int) -> None:
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(path, 16, 16, 1, gdal.GDT_Int16)
    ds.SetGeoTransform((-112.0, 0.001, 0, 41.0, 0, -0.001))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(np.full((16, 16), fill, dtype=np.int16))
    ds.GetRasterBand(1).SetNoDataValue(0)
    ds.FlushCache()
    ds = None


class TestResolveGdalPath:
    def test_https_to_vsicurl(self) -> None:
        assert (
            _resolve_gdal_path("https://example.com/x.tif") == "/vsicurl/https://example.com/x.tif"
        )

    def test_s3_to_vsis3(self) -> None:
        assert _resolve_gdal_path("s3://bucket/key.tif") == "/vsis3/bucket/key.tif"

    def test_local_passthrough(self) -> None:
        assert _resolve_gdal_path("/tmp/x.tif") == "/tmp/x.tif"


class TestTrueColor:
    def test_returns_three_uint8_arrays(self) -> None:
        shape = (8, 8)
        red = np.full(shape, 1300, dtype=np.int16)
        green = np.full(shape, 1000, dtype=np.int16)
        blue = np.full(shape, 800, dtype=np.int16)
        result = true_color(red, green, blue)
        assert len(result) == 3
        for band in result:
            assert band.dtype == np.ubyte
            assert band.shape == shape

    def test_nonzero_input_produces_nonzero_output(self) -> None:
        # Typical Sentinel-2 L3 DN values for vegetated land
        shape = (4, 4)
        red = np.full(shape, 1300, dtype=np.int16)
        green = np.full(shape, 1500, dtype=np.int16)
        blue = np.full(shape, 900, dtype=np.int16)
        result = true_color(red, green, blue)
        for band in result:
            assert np.all(band > 0), "Expected non-zero output for typical reflectance input"
            assert np.all(band < 255), "Expected unsaturated output for typical reflectance input"

    def test_golden_values(self) -> None:
        """Regression lock for the default tone-map pipeline.

        If tone-map constants ever change on purpose, recompute these
        values and update the assertion — the point is that an
        *accidental* drift in constants or algorithm order fails loudly.
        """
        red = np.array([[800, 1300, 2500], [500, 1800, 3200]], dtype=np.float32)
        green = np.array([[900, 1500, 2400], [600, 1700, 3000]], dtype=np.float32)
        blue = np.array([[700, 900, 2200], [400, 1400, 2800]], dtype=np.float32)
        r, g, b = true_color(red, green, blue)
        assert r.tolist() == [[121, 152, 191], [92, 173, 204]]
        assert g.tolist() == [[129, 163, 189], [104, 169, 201]]
        assert b.tolist() == [[111, 125, 183], [78, 155, 196]]

    def test_custom_tone_map_params_change_output(self) -> None:
        shape = (4, 4)
        red = np.full(shape, 1300, dtype=np.float32)
        green = np.full(shape, 1500, dtype=np.float32)
        blue = np.full(shape, 900, dtype=np.float32)
        default = true_color(red, green, blue)
        tweaked = true_color(red, green, blue, ToneMapParams(gamma=DEFAULT_TONE_MAP.gamma + 0.5))
        assert not np.array_equal(default[0], tweaked[0])

    def test_zero_input_stays_zero(self) -> None:
        # All-zero DN = nodata; should propagate through as zero
        shape = (4, 4)
        red = np.zeros(shape, dtype=np.int16)
        green = np.zeros(shape, dtype=np.int16)
        blue = np.zeros(shape, dtype=np.int16)
        result = true_color(red, green, blue)
        for band in result:
            assert np.all(band == 0), "Expected zero output for zero (nodata) input"


class TestProcessTile:
    def test_writes_4band_rgba(self, tmp_path: Path) -> None:
        red_path = str(tmp_path / "B04.tif")
        green_path = str(tmp_path / "B03.tif")
        blue_path = str(tmp_path / "B02.tif")
        _make_band(red_path, 2000)
        _make_band(green_path, 1500)
        _make_band(blue_path, 1000)

        tile = MosaicTile(
            tile_id="test-tile",
            quarter="2024-Q3",
            geometry={},
            href_red=red_path,
            href_green=green_path,
            href_blue=blue_path,
        )

        out_path = str(tmp_path / "out.tif")
        process_tile(tile, out_path)

        ds = gdal.Open(out_path)
        assert ds is not None
        assert ds.RasterCount == 4
        assert ds.GetRasterBand(1).DataType == gdal.GDT_Byte
        assert ds.GetRasterBand(4).GetColorInterpretation() == gdal.GCI_AlphaBand
        # All source pixels are non-zero so alpha should be fully opaque.
        assert np.all(ds.GetRasterBand(4).ReadAsArray() == 255)
        # No band should declare 0 as nodata — 0,0,0 is valid black.
        for i in range(1, 5):
            assert ds.GetRasterBand(i).GetNoDataValue() != 0
        ds = None

    def test_nodata_source_pixels_produce_transparent_alpha(self, tmp_path: Path) -> None:
        red_path = str(tmp_path / "B04.tif")
        green_path = str(tmp_path / "B03.tif")
        blue_path = str(tmp_path / "B02.tif")
        _make_band(red_path, 0)  # all nodata
        _make_band(green_path, 0)
        _make_band(blue_path, 0)

        tile = MosaicTile(
            tile_id="nodata-tile",
            quarter="2024-Q3",
            geometry={},
            href_red=red_path,
            href_green=green_path,
            href_blue=blue_path,
        )

        out_path = str(tmp_path / "out.tif")
        process_tile(tile, out_path)

        ds = gdal.Open(out_path)
        assert np.all(ds.GetRasterBand(4).ReadAsArray() == 0)
        ds = None


class TestProcessBands:
    def test_writes_4band_rgba(self, tmp_path: Path) -> None:
        red_path = str(tmp_path / "B04.tif")
        green_path = str(tmp_path / "B03.tif")
        blue_path = str(tmp_path / "B02.tif")
        _make_band(red_path, 2000)
        _make_band(green_path, 1500)
        _make_band(blue_path, 1000)

        out_path = str(tmp_path / "out.tif")
        process_bands(red_path, green_path, blue_path, out_path)

        ds = gdal.Open(out_path)
        assert ds is not None
        assert ds.RasterCount == 4
        assert ds.GetRasterBand(1).DataType == gdal.GDT_Byte
        assert ds.GetRasterBand(4).GetColorInterpretation() == gdal.GCI_AlphaBand
        assert np.all(ds.GetRasterBand(4).ReadAsArray() == 255)
        ds = None

    def test_nodata_produces_transparent_alpha(self, tmp_path: Path) -> None:
        red_path = str(tmp_path / "B04.tif")
        green_path = str(tmp_path / "B03.tif")
        blue_path = str(tmp_path / "B02.tif")
        _make_band(red_path, 0)
        _make_band(green_path, 0)
        _make_band(blue_path, 0)

        out_path = str(tmp_path / "out.tif")
        process_bands(red_path, green_path, blue_path, out_path)

        ds = gdal.Open(out_path)
        assert np.all(ds.GetRasterBand(4).ReadAsArray() == 0)
        ds = None

    def test_process_tile_delegates_to_process_bands(self, tmp_path: Path) -> None:
        red_path = str(tmp_path / "B04.tif")
        green_path = str(tmp_path / "B03.tif")
        blue_path = str(tmp_path / "B02.tif")
        _make_band(red_path, 2000)
        _make_band(green_path, 1500)
        _make_band(blue_path, 1000)

        tile = MosaicTile(
            tile_id="test-tile",
            quarter="2024-Q3",
            geometry={},
            href_red=red_path,
            href_green=green_path,
            href_blue=blue_path,
        )

        out_path = str(tmp_path / "out.tif")
        import sentinel_mosaic.process as proc_mod

        with patch.object(proc_mod, "process_bands", wraps=proc_mod.process_bands) as mock_pb:
            process_tile(tile, out_path)

        mock_pb.assert_called_once_with(red_path, green_path, blue_path, out_path, {})
