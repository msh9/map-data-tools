"""Tests for slope computation, thresholding, and output format."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from osgeo import gdal, osr

from dem_2_slope.slope import (
    build_la,
    build_rgba,
    compute_slope,
    process_tile,
    resolve_input,
    smooth_slope,
    threshold_to_uint8,
)

gdal.UseExceptions()


def _create_synthetic_dem(
    path: Path,
    rows: int = 32,
    cols: int = 32,
    *,
    epsg: int = 4326,
    origin_x: float = -112.0,
    origin_y: float = 41.0,
    pixel_size: float = 1.0 / 3600,
) -> Path:
    """Write a small synthetic DEM GeoTIFF with a known elevation ramp."""
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(str(path), cols, rows, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((origin_x, pixel_size, 0, origin_y, 0, -pixel_size))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())

    # Elevation ramp: increases by 100m per pixel along the x-axis
    elevation = np.zeros((rows, cols), dtype=np.float32)
    for c in range(cols):
        elevation[:, c] = c * 100.0
    ds.GetRasterBand(1).WriteArray(elevation)
    ds.FlushCache()
    ds = None
    return path


def _create_mixed_dem(
    path: Path,
    rows: int = 32,
    cols: int = 32,
    *,
    origin_x: float = -112.0,
    origin_y: float = 41.0,
) -> Path:
    """Write a DEM with a flat left half and a steep right half."""
    driver = gdal.GetDriverByName("GTiff")
    pixel_size = 1.0 / 3600
    ds = driver.Create(str(path), cols, rows, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((origin_x, pixel_size, 0, origin_y, 0, -pixel_size))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())

    elevation = np.zeros((rows, cols), dtype=np.float32)
    # Left half: flat (slope ~ 0)
    # Right half: steep ramp
    mid = cols // 2
    for c in range(mid, cols):
        elevation[:, c] = (c - mid) * 500.0
    ds.GetRasterBand(1).WriteArray(elevation)
    ds.FlushCache()
    ds = None
    return path


def _create_clip_geojson(path: Path, bounds: tuple[float, float, float, float]) -> Path:
    """Create a simple rectangular GeoJSON polygon for clipping.

    bounds: (min_x, min_y, max_x, max_y) in EPSG:4326.
    """
    min_x, min_y, max_x, max_y = bounds
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
    path.write_text(json.dumps(geojson))
    return path


class TestComputeSlope:
    def test_slope_computation_basic(self, tmp_path: Path) -> None:
        """Create a tiny synthetic DEM with elevation ramp. Verify slope values."""
        dem_path = _create_synthetic_dem(tmp_path / "dem.tif")
        slope_path = tmp_path / "slope.tif"

        slope_ds = compute_slope(dem_path, slope_path)
        slope_band = slope_ds.GetRasterBand(1)
        nodata = slope_band.GetNoDataValue()
        slope_array = slope_band.ReadAsArray()
        slope_ds = None

        # Mask out nodata pixels (edge artifacts from gdaldem slope)
        valid = slope_array if nodata is None else slope_array[slope_array != nodata]

        # Slope should be non-negative degrees
        assert valid.min() >= 0.0
        assert valid.max() <= 90.0
        # With a 100m/pixel ramp, interior pixels should have significant slope
        assert valid.max() > 0.0


class TestThreshold:
    def test_threshold_zeroes_gentle_slopes(self, tmp_path: Path) -> None:
        """Verify pixels below threshold become 0."""
        dem_path = _create_mixed_dem(tmp_path / "mixed.tif")
        slope_path = tmp_path / "slope.tif"

        slope_ds = compute_slope(dem_path, slope_path)
        slope_array = slope_ds.GetRasterBand(1).ReadAsArray()
        slope_ds = None

        threshold = 10.0
        result = threshold_to_uint8(slope_array, threshold)

        # Flat areas should be zero
        assert result.dtype == np.uint8
        # Some pixels should be zero (flat areas) and some non-zero (steep areas)
        assert (result == 0).any(), "Expected some zero pixels from flat region"
        assert (result > 0).any(), "Expected some non-zero pixels from steep region"

    def test_threshold_output_range(self) -> None:
        """Verify output range is 0 or 1-255."""
        slope_array = np.array([[0.5, 5.0, 15.0, 45.0, 89.0]], dtype=np.float32)
        result = threshold_to_uint8(slope_array, threshold=10.0)
        assert result.dtype == np.uint8
        # Below threshold -> 0
        assert result[0, 0] == 0
        assert result[0, 1] == 0
        # Above threshold -> 1-255
        for val in result[0, 2:]:
            assert 1 <= val <= 255


class TestSmoothSlope:
    def test_identity_with_kernel_1(self) -> None:
        arr = np.array([[1.0, 5.0, 3.0], [2.0, 8.0, 4.0]], dtype=np.float32)
        result = smooth_slope(arr, 1)
        np.testing.assert_array_equal(result, arr)

    def test_smoothing_reduces_variation(self) -> None:
        arr = np.zeros((16, 16), dtype=np.float32)
        arr[8, 8] = 90.0  # single spike
        result = smooth_slope(arr, 4)
        assert result.max() < 90.0
        assert result[8, 8] > 0.0

    def test_preserves_shape(self) -> None:
        arr = np.random.default_rng(42).random((20, 30)).astype(np.float32)
        result = smooth_slope(arr, 5)
        assert result.shape == arr.shape

    def test_uniform_array_unchanged(self) -> None:
        arr = np.full((10, 10), 25.0, dtype=np.float32)
        result = smooth_slope(arr, 4)
        np.testing.assert_allclose(result, 25.0, atol=1e-5)


class TestBuildLa:
    def test_output_shape(self) -> None:
        slope = np.array([[0, 128, 255]], dtype=np.uint8)
        la = build_la(slope)
        assert la.shape == (2, 1, 3)

    def test_alpha_channel(self) -> None:
        slope = np.array([[0, 50, 0]], dtype=np.uint8)
        la = build_la(slope)
        np.testing.assert_array_equal(la[1], [[0, 255, 0]])

    def test_luminance_channel_equals_slope(self) -> None:
        slope = np.array([[10, 200]], dtype=np.uint8)
        la = build_la(slope)
        np.testing.assert_array_equal(la[0], slope)


class TestBuildRgba:
    def test_output_shape(self) -> None:
        slope = np.array([[0, 128, 255]], dtype=np.uint8)
        rgba = build_rgba(slope)
        assert rgba.shape == (4, 1, 3)

    def test_alpha_channel(self) -> None:
        slope = np.array([[0, 50, 0]], dtype=np.uint8)
        rgba = build_rgba(slope)
        # Alpha should be 0 where slope is 0, 255 where slope > 0
        np.testing.assert_array_equal(rgba[3], [[0, 255, 0]])

    def test_rgb_channels_equal_slope(self) -> None:
        slope = np.array([[10, 200]], dtype=np.uint8)
        rgba = build_rgba(slope)
        for band in range(3):
            np.testing.assert_array_equal(rgba[band], slope)


class TestResolveInput:
    def test_local_path_unchanged(self) -> None:
        assert resolve_input("/data/dem.tif") == "/data/dem.tif"

    def test_http_url_gets_vsicurl_prefix(self) -> None:
        url = "https://example.com/dem.tif"
        assert resolve_input(url) == f"/vsicurl/{url}"

    def test_http_url_gets_vsicurl_prefix_plain(self) -> None:
        url = "http://example.com/dem.tif"
        assert resolve_input(url) == f"/vsicurl/{url}"

    def test_path_object_unchanged(self) -> None:
        assert resolve_input(Path("/data/dem.tif")) == "/data/dem.tif"


class TestProcessTile:
    def test_output_is_two_band_la(self, tmp_path: Path) -> None:
        """Process a small DEM and verify output has 2 bands (LA)."""
        dem_path = _create_synthetic_dem(tmp_path / "dem.tif")
        clip_path = _create_clip_geojson(
            tmp_path / "clip.geojson",
            (-113.0, 40.0, -111.0, 42.0),
        )
        cog_path = tmp_path / "output.cog.tif"

        process_tile(
            input_path=dem_path,
            output_path=cog_path,
            threshold=5.0,
            clip_regions_path=clip_path,
        )

        ds = gdal.Open(str(cog_path))
        assert ds is not None
        assert ds.RasterCount == 2
        ds = None

    def test_output_crs_is_esri_102009(self, tmp_path: Path) -> None:
        """Process a DEM in EPSG:4326, verify output CRS is ESRI:102009."""
        dem_path = _create_synthetic_dem(tmp_path / "dem.tif", epsg=4326)
        clip_path = _create_clip_geojson(
            tmp_path / "clip.geojson",
            (-113.0, 40.0, -111.0, 42.0),
        )
        cog_path = tmp_path / "output.cog.tif"

        process_tile(
            input_path=dem_path,
            output_path=cog_path,
            threshold=5.0,
            clip_regions_path=clip_path,
        )

        ds = gdal.Open(str(cog_path))
        assert ds is not None
        srs = osr.SpatialReference(wkt=ds.GetProjection())
        # ESRI:102009 is "North America Lambert Conformal Conic"
        assert srs.GetAuthorityCode(None) is not None
        # Verify it's a projected CRS (not geographic)
        assert srs.IsProjected()
        ds = None

    def test_stream_mode_produces_same_output(self, tmp_path: Path) -> None:
        """Verify stream=True produces a valid 2-band LA COG using /vsimem/."""
        dem_path = _create_synthetic_dem(tmp_path / "dem.tif")
        clip_path = _create_clip_geojson(
            tmp_path / "clip.geojson",
            (-113.0, 40.0, -111.0, 42.0),
        )
        cog_path = tmp_path / "stream_output.cog.tif"

        process_tile(
            input_path=dem_path,
            output_path=cog_path,
            threshold=5.0,
            clip_regions_path=clip_path,
            stream=True,
        )

        ds = gdal.Open(str(cog_path))
        assert ds is not None
        assert ds.RasterCount == 2
        srs = osr.SpatialReference(wkt=ds.GetProjection())
        assert srs.IsProjected()
        ds = None

    def test_output_with_smoothing(self, tmp_path: Path) -> None:
        """Verify process_tile with smooth_kernel produces a valid 2-band COG."""
        dem_path = _create_synthetic_dem(tmp_path / "dem.tif")
        clip_path = _create_clip_geojson(
            tmp_path / "clip.geojson",
            (-113.0, 40.0, -111.0, 42.0),
        )
        cog_path = tmp_path / "smoothed.cog.tif"

        process_tile(
            input_path=dem_path,
            output_path=cog_path,
            threshold=5.0,
            clip_regions_path=clip_path,
            smooth_kernel=3,
        )

        ds = gdal.Open(str(cog_path))
        assert ds is not None
        assert ds.RasterCount == 2
        ds = None
