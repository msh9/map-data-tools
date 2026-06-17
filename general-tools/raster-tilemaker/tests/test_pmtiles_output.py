from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import features

from raster_tilemaker import build_tiles
from raster_tilemaker.config import TILE_CONFIG_NAME
from raster_tilemaker.output.pmtiles import write_pmtiles_archive, write_pmtiles_archive_parallel
from raster_tilemaker.render.mosaic import RenderedTile, iter_tile_specs

from osgeo import gdal
from osgeo import osr


def _read_uint64(raw: bytes, offset: int) -> int:
    return int.from_bytes(raw[offset : offset + 8], byteorder="little", signed=False)


def _read_header(path: Path) -> dict[str, int]:
    raw = path.read_bytes()[:127]
    assert raw[:7] == b"PMTiles"
    return {
        "version": raw[7],
        "metadata_offset": _read_uint64(raw, 24),
        "metadata_length": _read_uint64(raw, 32),
        "addressed_tiles_count": _read_uint64(raw, 72),
        "tile_entries_count": _read_uint64(raw, 80),
        "tile_contents_count": _read_uint64(raw, 88),
        "tile_type": raw[99],
    }


def _read_metadata(path: Path, header: dict[str, int]) -> dict:
    raw = path.read_bytes()
    metadata_start = header["metadata_offset"]
    metadata_end = metadata_start + header["metadata_length"]
    return json.loads(gzip.decompress(raw[metadata_start:metadata_end]).decode("utf-8"))


def _create_rgba_tif(path: Path) -> None:
    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(
        str(path),
        64,
        64,
        4,
        gdal.GDT_Byte,
        options=["TILED=YES", "BLOCKXSIZE=64", "BLOCKYSIZE=64"],
    )
    if dataset is None:
        raise RuntimeError("Failed to create test GeoTIFF.")

    dataset.SetGeoTransform((-2000000.0, 1000.0, 0.0, 1100000.0, 0.0, -1000.0))
    spatial_ref = osr.SpatialReference()
    spatial_ref.SetFromUserInput("ESRI:102009")
    spatial_ref.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dataset.SetProjection(spatial_ref.ExportToWkt())

    red = np.full((64, 64), 120, dtype=np.uint8)
    green = np.full((64, 64), 90, dtype=np.uint8)
    blue = np.full((64, 64), 60, dtype=np.uint8)
    alpha = np.full((64, 64), 255, dtype=np.uint8)

    dataset.GetRasterBand(1).WriteArray(red)
    dataset.GetRasterBand(2).WriteArray(green)
    dataset.GetRasterBand(3).WriteArray(blue)
    dataset.GetRasterBand(4).WriteArray(alpha)
    dataset = None


def _create_vrt(vrt_path: Path, tif_path: Path) -> None:
    vrt = gdal.BuildVRT(str(vrt_path), [str(tif_path)])
    if vrt is None:
        raise RuntimeError("Failed to create test VRT.")
    vrt = None


@pytest.fixture(scope="module", autouse=True)
def _enable_gdal_exceptions() -> None:
    gdal.UseExceptions()


def test_build_tiles_pmtiles_writes_archive(tmp_path: Path) -> None:
    if not features.check("webp"):
        pytest.skip("WebP support missing in Pillow build.")

    tif_path = tmp_path / "source.tif"
    vrt_path = tmp_path / "mosaic.vrt"
    output_dir = tmp_path / "out"

    _create_rgba_tif(tif_path)
    _create_vrt(vrt_path, tif_path)

    exit_code = build_tiles.main(
        [
            "--input-vrt",
            str(vrt_path),
            "--output-dir",
            str(output_dir),
            "--resolution",
            "2560",
            "--output-kind",
            "pmtiles",
        ]
    )
    assert exit_code == 0

    archive_path = output_dir / "tiles.pmtiles"
    assert archive_path.exists()
    assert (output_dir / "tiles-config.json").exists()
    assert not (output_dir / TILE_CONFIG_NAME).exists()
    assert not (output_dir / "tiles").exists()

    header = _read_header(archive_path)
    assert header["version"] == 3
    assert header["tile_type"] == 4
    assert header["addressed_tiles_count"] > 0
    assert header["tile_entries_count"] == header["addressed_tiles_count"]
    assert header["tile_contents_count"] == header["addressed_tiles_count"]

    metadata = _read_metadata(archive_path, header)
    assert "localZoomToPmtilesZoom" in metadata
    assert "pmtilesZoomOffset" in metadata


def test_build_tiles_pmtiles_custom_archive_name_controls_config_name(
    tmp_path: Path,
) -> None:
    if not features.check("webp"):
        pytest.skip("WebP support missing in Pillow build.")

    tif_path = tmp_path / "source.tif"
    vrt_path = tmp_path / "mosaic.vrt"
    output_dir = tmp_path / "out"

    _create_rgba_tif(tif_path)
    _create_vrt(vrt_path, tif_path)

    exit_code = build_tiles.main(
        [
            "--input-vrt",
            str(vrt_path),
            "--output-dir",
            str(output_dir),
            "--resolution",
            "2560",
            "--output-kind",
            "pmtiles",
            "--pmtiles-file",
            "sectionals.pmtiles",
        ]
    )
    assert exit_code == 0
    assert (output_dir / "sectionals.pmtiles").exists()
    assert (output_dir / "sectionals-config.json").exists()
    assert not (output_dir / TILE_CONFIG_NAME).exists()


def test_write_pmtiles_archive_skips_empty_tiles(tmp_path: Path) -> None:
    if not features.check("webp"):
        pytest.skip("WebP support missing in Pillow build.")

    empty = np.full((8, 8, 4), 255, dtype=np.uint8)
    empty[:, :, 3] = 0
    filled = np.full((8, 8, 4), 0, dtype=np.uint8)
    filled[:, :, 3] = 255

    tiles = [
        RenderedTile(z=0, x=0, y=0, tile_array=empty, has_data=False),
        RenderedTile(z=0, x=0, y=0, tile_array=filled, has_data=True),
    ]

    output_path = tmp_path / "tiles.pmtiles"
    written = write_pmtiles_archive(
        tiles,
        output_path,
        tile_format="webp",
        quality=30,
        resolutions=[2560.0],
        bounds_wgs84=(-111.0, 40.0, -109.0, 42.0),
    )
    assert written == 1

    header = _read_header(output_path)
    assert header["addressed_tiles_count"] == 1


def test_write_pmtiles_archive_errors_when_all_tiles_empty(tmp_path: Path) -> None:
    if not features.check("webp"):
        pytest.skip("WebP support missing in Pillow build.")

    empty = np.full((8, 8, 4), 255, dtype=np.uint8)
    empty[:, :, 3] = 0
    tiles = [RenderedTile(z=0, x=0, y=0, tile_array=empty, has_data=False)]

    with pytest.raises(ValueError, match="No non-empty tiles"):
        write_pmtiles_archive(
            tiles,
            tmp_path / "tiles.pmtiles",
            tile_format="webp",
            quality=30,
            resolutions=[2560.0],
            bounds_wgs84=(-111.0, 40.0, -109.0, 42.0),
        )


def test_write_pmtiles_archive_png_la_tiles(tmp_path: Path) -> None:
    """LA tiles with PNG format should produce a valid PMTiles archive."""
    filled = np.zeros((8, 8, 2), dtype=np.uint8)
    filled[:, :, 0] = 128  # luminance
    filled[:, :, 1] = 255  # alpha

    tiles = [
        RenderedTile(z=0, x=0, y=0, tile_array=filled, has_data=True),
    ]

    output_path = tmp_path / "tiles.pmtiles"
    written = write_pmtiles_archive(
        tiles,
        output_path,
        tile_format="png",
        quality=0,
        resolutions=[2560.0],
        bounds_wgs84=(-111.0, 40.0, -109.0, 42.0),
    )
    assert written == 1

    header = _read_header(output_path)
    assert header["tile_type"] == 2  # PNG


def test_iter_tile_specs_matches_rendered_tile_coordinates(tmp_path: Path) -> None:
    """iter_tile_specs yields exactly the same (z,x,y) coordinates as iter_rendered_mosaic_tiles."""
    tif_path = tmp_path / "source.tif"
    vrt_path = tmp_path / "mosaic.vrt"
    _create_rgba_tif(tif_path)
    _create_vrt(vrt_path, tif_path)

    from raster_tilemaker.render.mosaic import iter_rendered_mosaic_tiles, read_vrt_metadata

    source = read_vrt_metadata(vrt_path)
    min_x, _, _, max_y = source.bounds
    origin = (min_x, max_y)
    resolutions = [2560.0]
    tile_size = 512

    rendered_coords = {
        (t.z, t.x, t.y)
        for t in iter_rendered_mosaic_tiles(
            vrt_path,
            tile_size=tile_size,
            aggregate_bounds=source.bounds,
            origin=origin,
            resolutions=resolutions,
        )
    }
    spec_coords = {(z, x, y) for z, x, y, _ in iter_tile_specs(source.bounds, origin, resolutions, tile_size)}
    assert spec_coords == rendered_coords


def test_write_pmtiles_archive_parallel_matches_serial(tmp_path: Path) -> None:
    """Parallel render+encode produces the same tile count and metadata as the serial path."""
    if not features.check("webp"):
        pytest.skip("WebP support missing in Pillow build.")

    tif_path = tmp_path / "source.tif"
    vrt_path = tmp_path / "mosaic.vrt"
    _create_rgba_tif(tif_path)
    _create_vrt(vrt_path, tif_path)

    from raster_tilemaker.render.mosaic import (
        iter_rendered_mosaic_tiles,
        read_vrt_metadata,
    )

    source = read_vrt_metadata(vrt_path)
    min_x, _, _, max_y = source.bounds
    origin = (min_x, max_y)
    resolutions = [2560.0]
    bounds_wgs84 = (-111.0, 40.0, -109.0, 42.0)

    serial_path = tmp_path / "serial.pmtiles"
    parallel_path = tmp_path / "parallel.pmtiles"

    rendered_tiles = iter_rendered_mosaic_tiles(
        vrt_path,
        tile_size=512,
        aggregate_bounds=source.bounds,
        origin=origin,
        resolutions=resolutions,
    )
    write_pmtiles_archive(
        rendered_tiles,
        serial_path,
        tile_format="webp",
        quality=30,
        resolutions=resolutions,
        bounds_wgs84=bounds_wgs84,
    )

    write_pmtiles_archive_parallel(
        vrt_path,
        parallel_path,
        tile_format="webp",
        quality=30,
        resolutions=resolutions,
        bounds_wgs84=bounds_wgs84,
        aggregate_bounds=source.bounds,
        origin=origin,
        band_count=source.band_count,
        tile_size=512,
        render_workers=2,
    )

    sh = _read_header(serial_path)
    ph = _read_header(parallel_path)
    assert ph["addressed_tiles_count"] == sh["addressed_tiles_count"]
    assert ph["tile_entries_count"] == sh["tile_entries_count"]
    assert ph["tile_contents_count"] == sh["tile_contents_count"]
    assert ph["tile_type"] == sh["tile_type"]

    sm = _read_metadata(serial_path, sh)
    pm = _read_metadata(parallel_path, ph)
    assert pm["localZoomToPmtilesZoom"] == sm["localZoomToPmtilesZoom"]
    assert pm["pmtilesZoomOffset"] == sm["pmtilesZoomOffset"]


def test_build_tiles_pmtiles_render_workers_flag(tmp_path: Path) -> None:
    """--render-workers is accepted and produces a valid PMTiles archive."""
    if not features.check("webp"):
        pytest.skip("WebP support missing in Pillow build.")

    tif_path = tmp_path / "source.tif"
    vrt_path = tmp_path / "mosaic.vrt"
    output_dir = tmp_path / "out"
    _create_rgba_tif(tif_path)
    _create_vrt(vrt_path, tif_path)

    exit_code = build_tiles.main(
        [
            "--input-vrt", str(vrt_path),
            "--output-dir", str(output_dir),
            "--resolution", "2560",
            "--output-kind", "pmtiles",
            "--render-workers", "2",
        ]
    )
    assert exit_code == 0

    archive_path = output_dir / "tiles.pmtiles"
    assert archive_path.exists()
    header = _read_header(archive_path)
    assert header["addressed_tiles_count"] > 0
