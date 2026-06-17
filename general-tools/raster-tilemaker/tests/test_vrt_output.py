from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, features

from raster_tilemaker import build_tiles
from raster_tilemaker.config import TILE_CONFIG_NAME

from osgeo import gdal
from osgeo import osr


def _create_tif(
    path: Path,
    *,
    band_count: int,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    crs: str,
    apply_nodata_mask: bool = False,
) -> None:
    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(
        str(path),
        64,
        64,
        band_count,
        gdal.GDT_Byte,
        options=["TILED=YES", "BLOCKXSIZE=64", "BLOCKYSIZE=64"],
    )
    if dataset is None:
        raise RuntimeError("Failed to create test GeoTIFF.")

    pixel_width = (max_x - min_x) / 64
    pixel_height = (max_y - min_y) / 64
    dataset.SetGeoTransform((min_x, pixel_width, 0.0, max_y, 0.0, -pixel_height))

    spatial_ref = osr.SpatialReference()
    spatial_ref.SetFromUserInput(crs)
    spatial_ref.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dataset.SetProjection(spatial_ref.ExportToWkt())

    if band_count in {1, 2}:
        gray = np.zeros((64, 64), dtype=np.uint8)
        gray[8:56, 8:56] = 200
        band = dataset.GetRasterBand(1)
        band.WriteArray(gray)
        if apply_nodata_mask:
            band.SetNoDataValue(0)
        if band_count == 2:
            alpha = np.full((64, 64), 255, dtype=np.uint8)
            alpha[:8, :] = 0
            alpha_band = dataset.GetRasterBand(2)
            alpha_band.WriteArray(alpha)
        dataset = None
        return

    if band_count not in {3, 4}:
        raise ValueError("Tests only support creating 1/2/3/4-band fixtures.")

    red = np.zeros((64, 64), dtype=np.uint8)
    green = np.zeros((64, 64), dtype=np.uint8)
    blue = np.zeros((64, 64), dtype=np.uint8)
    red[8:56, 8:56] = 255
    green[8:56, 8:56] = 128
    blue[8:56, 8:56] = 64
    if band_count == 4:
        alpha = np.full((64, 64), 255, dtype=np.uint8)
    else:
        alpha = None

    dataset.GetRasterBand(1).WriteArray(red)
    dataset.GetRasterBand(2).WriteArray(green)
    dataset.GetRasterBand(3).WriteArray(blue)
    if apply_nodata_mask:
        dataset.GetRasterBand(1).SetNoDataValue(0)
        dataset.GetRasterBand(2).SetNoDataValue(0)
        dataset.GetRasterBand(3).SetNoDataValue(0)
    if alpha is not None:
        dataset.GetRasterBand(4).WriteArray(alpha)
    dataset = None


def _create_vrt(vrt_path: Path, input_paths: list[Path]) -> None:
    vrt = gdal.BuildVRT(str(vrt_path), [str(path) for path in input_paths])
    if vrt is None:
        raise RuntimeError("Failed to create test VRT.")
    vrt = None


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module", autouse=True)
def _enable_gdal_exceptions() -> None:
    gdal.UseExceptions()


def test_build_tiles_zxy_from_vrt(tmp_path: Path) -> None:
    if not features.check("webp"):
        pytest.skip("WebP support missing in Pillow build.")

    tif_path = tmp_path / "source.tif"
    vrt_path = tmp_path / "mosaic.vrt"
    output_dir = tmp_path / "out"

    _create_tif(
        tif_path,
        band_count=4,
        min_x=-2000000.0,
        min_y=1000000.0,
        max_x=-1900000.0,
        max_y=1100000.0,
        crs="ESRI:102009",
    )
    _create_vrt(vrt_path, [tif_path])

    exit_code = build_tiles.main(
        [
            "--input-vrt",
            str(vrt_path),
            "--output-dir",
            str(output_dir),
            "--resolution",
            "2560",
        ]
    )
    assert exit_code == 0

    config = _load_json(output_dir / TILE_CONFIG_NAME)
    assert config["schemaVersion"] == "1.0"
    assert config["sources"] == []
    assert config["tile"]["resolutions"] == [2560.0]
    assert config["tile"]["tileSizePx"] == 512

    source_ds = gdal.Open(str(vrt_path), gdal.GA_ReadOnly)
    assert source_ds is not None
    assert config["crs"]["value"] == source_ds.GetProjectionRef()

    tile_path = output_dir / "tiles" / "0" / "0" / "0.webp"
    assert tile_path.exists()

    with Image.open(tile_path) as image:
        assert image.size == (512, 512)
        assert image.mode == "RGBA"


def test_tile_config_keeps_vrt_projection(tmp_path: Path) -> None:
    if not features.check("webp"):
        pytest.skip("WebP support missing in Pillow build.")

    tif_path = tmp_path / "source_4326.tif"
    vrt_path = tmp_path / "mosaic_4326.vrt"
    output_dir = tmp_path / "out_4326"

    _create_tif(
        tif_path,
        band_count=4,
        min_x=-112.0,
        min_y=39.0,
        max_x=-111.0,
        max_y=40.0,
        crs="EPSG:4326",
    )
    _create_vrt(vrt_path, [tif_path])

    exit_code = build_tiles.main(
        [
            "--input-vrt",
            str(vrt_path),
            "--output-dir",
            str(output_dir),
            "--resolution",
            "2560",
        ]
    )
    assert exit_code == 0

    config = _load_json(output_dir / TILE_CONFIG_NAME)
    source_ds = gdal.Open(str(vrt_path), gdal.GA_ReadOnly)
    assert source_ds is not None
    assert config["crs"]["value"] == source_ds.GetProjectionRef()
    assert len(config["extent"]["wgs84"]) == 4


def test_build_tiles_single_band_png_output(tmp_path: Path) -> None:
    """Single-band input with PNG format should produce LA tiles."""
    tif_path = tmp_path / "single_band.tif"
    vrt_path = tmp_path / "single_band.vrt"
    output_dir = tmp_path / "out"

    _create_tif(
        tif_path,
        band_count=1,
        min_x=-2000000.0,
        min_y=1000000.0,
        max_x=-1900000.0,
        max_y=1100000.0,
        crs="ESRI:102009",
        apply_nodata_mask=True,
    )
    _create_vrt(vrt_path, [tif_path])

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
        assert image.size == (512, 512)


def test_build_tiles_la_input_png_output(tmp_path: Path) -> None:
    """2-band (LA) input with PNG format should produce LA tiles."""
    tif_path = tmp_path / "la_band.tif"
    vrt_path = tmp_path / "la_band.vrt"
    output_dir = tmp_path / "out"

    _create_tif(
        tif_path,
        band_count=2,
        min_x=-2000000.0,
        min_y=1000000.0,
        max_x=-1900000.0,
        max_y=1100000.0,
        crs="ESRI:102009",
    )
    _create_vrt(vrt_path, [tif_path])

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


def test_rgb_input_honors_nodata_mask_in_alpha(tmp_path: Path) -> None:
    if not features.check("webp"):
        pytest.skip("WebP support missing in Pillow build.")

    tif_path = tmp_path / "rgb_nodata.tif"
    vrt_path = tmp_path / "rgb_nodata.vrt"
    output_dir = tmp_path / "out_rgb_nodata"

    _create_tif(
        tif_path,
        band_count=3,
        min_x=-2000000.0,
        min_y=1000000.0,
        max_x=-1900000.0,
        max_y=1100000.0,
        crs="ESRI:102009",
        apply_nodata_mask=True,
    )
    _create_vrt(vrt_path, [tif_path])

    exit_code = build_tiles.main(
        [
            "--input-vrt",
            str(vrt_path),
            "--output-dir",
            str(output_dir),
            "--resolution",
            "2560",
        ]
    )
    assert exit_code == 0

    tile_path = output_dir / "tiles" / "0" / "0" / "0.webp"
    assert tile_path.exists()
    with Image.open(tile_path) as image:
        alpha = np.array(image.getchannel("A"))
        assert (alpha == 0).any()
        assert (alpha > 0).any()


def test_rgba_input_applies_nodata_mask_on_top_of_alpha(tmp_path: Path) -> None:
    if not features.check("webp"):
        pytest.skip("WebP support missing in Pillow build.")

    tif_path = tmp_path / "rgba_nodata.tif"
    vrt_path = tmp_path / "rgba_nodata.vrt"
    output_dir = tmp_path / "out_rgba_nodata"

    _create_tif(
        tif_path,
        band_count=4,
        min_x=-2000000.0,
        min_y=1000000.0,
        max_x=-1900000.0,
        max_y=1100000.0,
        crs="ESRI:102009",
        apply_nodata_mask=True,
    )
    _create_vrt(vrt_path, [tif_path])

    exit_code = build_tiles.main(
        [
            "--input-vrt",
            str(vrt_path),
            "--output-dir",
            str(output_dir),
            "--resolution",
            "2560",
        ]
    )
    assert exit_code == 0

    tile_path = output_dir / "tiles" / "0" / "0" / "0.webp"
    assert tile_path.exists()
    with Image.open(tile_path) as image:
        alpha = np.array(image.getchannel("A"))
        assert (alpha == 0).any()
        assert (alpha > 0).any()
