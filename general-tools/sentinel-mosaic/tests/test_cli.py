"""Tests for CLI argument parsing and orchestration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from osgeo import gdal, osr

from sentinel_mosaic.cli import _process_region_quarter, build_parser, main
from sentinel_mosaic.search import MosaicTile


class TestBuildParser:
    def _base_args(self) -> list[str]:
        return [
            "mosaic",
            "--clip-regions",
            "regions.geojson",
            "--output-dir",
            "/tmp/out",
            "--quarter",
            "2024-Q3",
        ]

    def test_required_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args())
        assert args.clip_regions == Path("regions.geojson")
        assert args.output_dir == Path("/tmp/out")
        assert args.quarter == ["2024-Q3"]

    def test_quarter_repeatable(self) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args() + ["--quarter", "2024-Q4"])
        assert args.quarter == ["2024-Q3", "2024-Q4"]

    def test_default_vrt_name(self) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args())
        assert args.vrt_name == "sentinel-mosaic.vrt"

    def test_default_stac_url(self) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args())
        assert "dataspace.copernicus.eu" in args.stac_url

    def test_log_format_default_plain(self) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args())
        assert args.log_format == "plain"

    def test_log_format_json_parsed(self) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args() + ["--log-format", "json"])
        assert args.log_format == "json"

    def test_scratch_dir_arg_parsed(self) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args() + ["--scratch-dir", "/tmp/scratch"])
        assert args.scratch_dir == Path("/tmp/scratch")

    def test_scratch_dir_default_is_none(self) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args())
        assert args.scratch_dir is None


class TestSaveScenes:
    _TILE = MosaicTile(
        tile_id="32TNT",
        quarter="2024-Q3",
        geometry={"type": "Polygon", "coordinates": []},
        href_red="https://example.com/B04.tif",
        href_green="https://example.com/B03.tif",
        href_blue="https://example.com/B02.tif",
    )

    def _base_args(self, save_scenes_path: str) -> list[str]:
        return [
            "mosaic",
            "--clip-regions",
            "regions.geojson",
            "--output-dir",
            "/tmp/out",
            "--quarter",
            "2024-Q3",
            "--save-scenes",
            save_scenes_path,
        ]

    def test_save_scenes_arg_parsed(self, tmp_path: Path) -> None:
        parser = build_parser()
        out = str(tmp_path / "scenes.json")
        args = parser.parse_args(self._base_args(out))
        assert args.save_scenes == Path(out)

    def test_save_scenes_writes_json(self, tmp_path: Path) -> None:
        out = tmp_path / "scenes.json"
        regions_path = tmp_path / "regions.geojson"
        regions_path.write_text(
            '{"type":"FeatureCollection","features":[{"type":"Feature",'
            '"properties":{"region-name":"test"},"geometry":{"type":"Polygon","coordinates":[]}}]}'
        )
        (tmp_path / "out").mkdir()

        with patch("sentinel_mosaic.cli.search_mosaic_tiles", return_value=[self._TILE]):
            rc = main(
                [
                    "mosaic",
                    "--clip-regions",
                    str(regions_path),
                    "--output-dir",
                    str(tmp_path / "out"),
                    "--quarter",
                    "2024-Q3",
                    "--save-scenes",
                    str(out),
                ]
            )

        assert rc == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert len(data) == 1
        assert data[0]["tile_id"] == "32TNT"
        assert data[0]["href_red"] == "https://example.com/B04.tif"

    def test_save_scenes_skips_processing(self, tmp_path: Path) -> None:
        out = tmp_path / "scenes.json"
        regions_path = tmp_path / "regions.geojson"
        regions_path.write_text(
            '{"type":"FeatureCollection","features":[{"type":"Feature",'
            '"properties":{"region-name":"test"},"geometry":{"type":"Polygon","coordinates":[]}}]}'
        )
        (tmp_path / "out").mkdir()

        with (
            patch("sentinel_mosaic.cli.search_mosaic_tiles", return_value=[self._TILE]),
            patch("sentinel_mosaic.cli._process_region_quarter") as mock_proc,
        ):
            main(
                [
                    "mosaic",
                    "--clip-regions",
                    str(regions_path),
                    "--output-dir",
                    str(tmp_path / "out"),
                    "--quarter",
                    "2024-Q3",
                    "--save-scenes",
                    str(out),
                ]
            )

        mock_proc.assert_not_called()


class TestLoadScenesMode:
    _TILE = MosaicTile(
        tile_id="32TNT",
        quarter="2024-Q3",
        geometry={"type": "Polygon", "coordinates": []},
        href_red="https://example.com/B04.tif",
        href_green="https://example.com/B03.tif",
        href_blue="https://example.com/B02.tif",
    )

    def _write_scenes(self, path: Path) -> None:
        import dataclasses

        path.write_text(json.dumps([dataclasses.asdict(self._TILE)]))

    def _write_regions(self, path: Path) -> None:
        path.write_text(
            '{"type":"FeatureCollection","features":[{"type":"Feature",'
            '"properties":{"region-name":"test"},"geometry":{"type":"Polygon","coordinates":[]}}]}'
        )

    def test_load_scenes_arg_parsed(self, tmp_path: Path) -> None:
        scenes = tmp_path / "scenes.json"
        self._write_scenes(scenes)
        parser = build_parser()
        args = parser.parse_args(
            [
                "mosaic",
                "--clip-regions",
                "regions.geojson",
                "--output-dir",
                "/tmp/out",
                "--quarter",
                "2024-Q3",
                "--load-scenes",
                str(scenes),
            ]
        )
        assert args.load_scenes == scenes

    def test_load_scenes_skips_stac_search(self, tmp_path: Path) -> None:
        scenes = tmp_path / "scenes.json"
        self._write_scenes(scenes)
        regions = tmp_path / "regions.geojson"
        self._write_regions(regions)
        (tmp_path / "out").mkdir()

        with (
            patch("sentinel_mosaic.cli.search_mosaic_tiles") as mock_search,
            patch("sentinel_mosaic.cli._process_region_quarter", return_value=None),
        ):
            main(
                [
                    "mosaic",
                    "--clip-regions",
                    str(regions),
                    "--output-dir",
                    str(tmp_path / "out"),
                    "--quarter",
                    "2024-Q3",
                    "--load-scenes",
                    str(scenes),
                ]
            )

        mock_search.assert_not_called()

    def test_load_and_save_scenes_are_mutually_exclusive(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "mosaic",
                    "--clip-regions",
                    "r.geojson",
                    "--output-dir",
                    "/tmp/out",
                    "--quarter",
                    "2024-Q3",
                    "--load-scenes",
                    str(tmp_path / "in.json"),
                    "--save-scenes",
                    str(tmp_path / "out.json"),
                ]
            )
        assert exc.value.code == 2


@pytest.fixture(autouse=True)
def _coarse_pixels(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default PIXEL_SIZE_M=10.0 over the 1°×1° fixture polygon would produce
    # large output tiles. Bumping to 1000m keeps finalize_output_tile warps fast
    # without affecting the orchestration behaviors under test.
    monkeypatch.setattr("sentinel_mosaic.cli.PIXEL_SIZE_M", 1000.0)


def _write_clip(path: Path, region_name: str = "r") -> None:
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
                                    [-112.0, 40.0],
                                    [-111.0, 40.0],
                                    [-111.0, 41.0],
                                    [-112.0, 41.0],
                                    [-112.0, 40.0],
                                ]
                            ],
                        },
                    }
                ],
            }
        )
    )


def _write_processed_tile(path: str) -> None:
    """Write a tiny RGBA GeoTIFF with the geometry process_tile would produce."""
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(path, 8, 8, 4, gdal.GDT_Byte)
    ds.SetGeoTransform((-111.8, 0.05, 0, 40.8, 0, -0.05))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    for band in range(1, 4):
        ds.GetRasterBand(band).WriteArray(np.full((8, 8), 100 + band * 30, dtype=np.uint8))
    ds.GetRasterBand(4).WriteArray(np.full((8, 8), 255, dtype=np.uint8))
    ds.GetRasterBand(4).SetColorInterpretation(gdal.GCI_AlphaBand)
    ds.FlushCache()
    ds = None


def _make_args(clip: Path, output_dir: Path, *, workers: int = 1) -> argparse.Namespace:
    return argparse.Namespace(
        clip_regions=clip,
        output_dir=output_dir,
        scratch_dir=None,
        stac_url="https://example/stac",
        vrt_name="sentinel-mosaic.vrt",
        verbose=False,
        save_scenes=None,
        load_scenes=None,
        quarter=["2024-Q3"],
        workers=workers,
    )


class TestPerTileFailureIsolation:
    def _tiles(self) -> list[MosaicTile]:
        return [
            MosaicTile(
                tile_id=f"T{i}",
                quarter="2024-Q3",
                geometry={"type": "Polygon", "coordinates": []},
                href_red=f"https://example/{i}/B04.tif",
                href_green=f"https://example/{i}/B03.tif",
                href_blue=f"https://example/{i}/B02.tif",
            )
            for i in range(3)
        ]

    def test_single_tile_failure_does_not_kill_region(self, tmp_path: Path) -> None:
        clip = tmp_path / "clip.geojson"
        _write_clip(clip)
        out = tmp_path / "out"
        out.mkdir()

        tiles = self._tiles()
        call_count = {"n": 0}

        def fake_process_tile(tile: MosaicTile, output_path: str) -> str:
            call_count["n"] += 1
            if tile.tile_id == "T1":
                raise RuntimeError("simulated CDSE 503")
            _write_processed_tile(output_path)
            return output_path

        args = _make_args(clip, out)
        with patch("sentinel_mosaic.cli.process_tile", side_effect=fake_process_tile):
            vrt = _process_region_quarter(
                "r",
                {"type": "Polygon", "coordinates": []},
                "2024-Q3",
                args,
                preloaded_tiles=tiles,
            )

        # All three tiles attempted; per-region VRT produced from the two that succeeded.
        assert call_count["n"] == 3
        assert vrt is not None
        assert vrt.exists()


class TestResume:
    def _tiles(self) -> list[MosaicTile]:
        return [
            MosaicTile(
                tile_id=f"T{i}",
                quarter="2024-Q3",
                geometry={"type": "Polygon", "coordinates": []},
                href_red=f"https://example/{i}/B04.tif",
                href_green=f"https://example/{i}/B03.tif",
                href_blue=f"https://example/{i}/B02.tif",
            )
            for i in range(3)
        ]

    def test_skips_when_per_region_vrt_already_exists(self, tmp_path: Path) -> None:
        clip = tmp_path / "clip.geojson"
        _write_clip(clip)
        out = tmp_path / "out"
        out.mkdir()

        existing_vrt = out / "r_2024-Q3.vrt"
        existing_vrt.write_bytes(b"pretend vrt")

        args = _make_args(clip, out)
        with patch("sentinel_mosaic.cli.process_tile") as mock_proc:
            vrt = _process_region_quarter(
                "r",
                {"type": "Polygon", "coordinates": []},
                "2024-Q3",
                args,
                preloaded_tiles=self._tiles(),
            )
        mock_proc.assert_not_called()
        assert vrt == existing_vrt

    def test_resumes_skipping_already_finalized_tiles(self, tmp_path: Path) -> None:
        clip = tmp_path / "clip.geojson"
        _write_clip(clip)
        out = tmp_path / "out"
        out.mkdir()

        # Pre-create tile output dir and GDAL-readable files for T0 and T1 so
        # _process_region_quarter detects them as already finalized via file existence.
        tile_dir = out / "r_2024-Q3"
        tile_dir.mkdir()
        _write_processed_tile(str(tile_dir / "T0.cog.tif"))
        _write_processed_tile(str(tile_dir / "T1.cog.tif"))

        seen: list[str] = []

        def fake_process_tile(tile: MosaicTile, output_path: str) -> str:
            seen.append(tile.tile_id)
            _write_processed_tile(output_path)
            return output_path

        args = _make_args(clip, out)
        with patch("sentinel_mosaic.cli.process_tile", side_effect=fake_process_tile):
            vrt = _process_region_quarter(
                "r",
                {"type": "Polygon", "coordinates": []},
                "2024-Q3",
                args,
                preloaded_tiles=self._tiles(),
            )

        assert seen == ["T2"], "only un-finalized tile should reach process_tile"
        assert vrt is not None and vrt.exists()


class TestSummaryAndExitCode:
    def _write_regions(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"region-name": "regionA"},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [
                                        [-112.0, 40.0],
                                        [-111.0, 40.0],
                                        [-111.0, 41.0],
                                        [-112.0, 41.0],
                                        [-112.0, 40.0],
                                    ]
                                ],
                            },
                        },
                        {
                            "type": "Feature",
                            "properties": {"region-name": "regionB"},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [
                                        [-110.0, 40.0],
                                        [-109.0, 40.0],
                                        [-109.0, 41.0],
                                        [-110.0, 41.0],
                                        [-110.0, 40.0],
                                    ]
                                ],
                            },
                        },
                    ],
                }
            )
        )

    def _scenes(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                [
                    {
                        "tile_id": "T0",
                        "quarter": "2024-Q3",
                        "geometry": {"type": "Polygon", "coordinates": []},
                        "href_red": "https://example/0/B04.tif",
                        "href_green": "https://example/0/B03.tif",
                        "href_blue": "https://example/0/B02.tif",
                    }
                ]
            )
        )

    def test_summary_written_and_exit_zero_on_success(self, tmp_path: Path) -> None:
        regions = tmp_path / "regions.geojson"
        self._write_regions(regions)
        scenes = tmp_path / "scenes.json"
        self._scenes(scenes)
        out = tmp_path / "out"
        out.mkdir()

        def fake_proc(region_name, region_geometry, quarter, args, *, preloaded_tiles):
            vrt = args.output_dir / f"{region_name}_{quarter}.vrt"
            vrt.write_bytes(b"fake vrt")
            return vrt

        with patch("sentinel_mosaic.cli._process_region_quarter", side_effect=fake_proc):
            with patch("sentinel_mosaic.cli.build_top_level_vrt"):
                rc = main(
                    [
                        "mosaic",
                        "--clip-regions",
                        str(regions),
                        "--output-dir",
                        str(out),
                        "--quarter",
                        "2024-Q3",
                        "--load-scenes",
                        str(scenes),
                    ]
                )
        assert rc == 0
        summary = out / "2024-Q3-summary.json"
        assert summary.exists()
        data = json.loads(summary.read_text())
        assert data["quarter"] == "2024-Q3"
        assert data["regions_attempted"] == 2
        assert data["regions_succeeded"] == 2
        assert data["regions_failed"] == 0

    def test_exit_one_when_a_region_fails(self, tmp_path: Path) -> None:
        regions = tmp_path / "regions.geojson"
        self._write_regions(regions)
        scenes = tmp_path / "scenes.json"
        self._scenes(scenes)
        out = tmp_path / "out"
        out.mkdir()

        def fake_proc(region_name, region_geometry, quarter, args, *, preloaded_tiles):
            if region_name == "regionA":
                raise RuntimeError("regionA blew up")
            vrt = args.output_dir / f"{region_name}_{quarter}.vrt"
            vrt.write_bytes(b"fake vrt")
            return vrt

        with patch("sentinel_mosaic.cli._process_region_quarter", side_effect=fake_proc):
            with patch("sentinel_mosaic.cli.build_top_level_vrt"):
                rc = main(
                    [
                        "mosaic",
                        "--clip-regions",
                        str(regions),
                        "--output-dir",
                        str(out),
                        "--quarter",
                        "2024-Q3",
                        "--load-scenes",
                        str(scenes),
                    ]
                )
        assert rc == 1
        summary = json.loads((out / "2024-Q3-summary.json").read_text())
        assert summary["regions_succeeded"] == 1
        assert summary["regions_failed"] == 1
        failed = [r for r in summary["regions"] if r["status"] == "failed"]
        assert len(failed) == 1
        assert failed[0]["region_name"] == "regionA"


class TestWorkersFlag:
    def _base_args(self) -> list[str]:
        return [
            "mosaic",
            "--clip-regions",
            "regions.geojson",
            "--output-dir",
            "/tmp/out",
            "--quarter",
            "2024-Q3",
        ]

    def test_workers_default_is_one(self) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args())
        assert args.workers == 1

    def test_workers_parsed(self) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args() + ["--workers", "4"])
        assert args.workers == 4

    def test_workers_zero_rejected(self, tmp_path: Path) -> None:
        regions = tmp_path / "r.geojson"
        regions.write_text(
            '{"type":"FeatureCollection","features":[{"type":"Feature",'
            '"properties":{"region-name":"test"},"geometry":{"type":"Polygon","coordinates":[]}}]}'
        )
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "mosaic",
                    "--clip-regions",
                    str(regions),
                    "--output-dir",
                    str(tmp_path / "out"),
                    "--quarter",
                    "2024-Q3",
                    "--workers",
                    "0",
                ]
            )
        assert exc.value.code == 2


class TestParallelTileLoop:
    def _tiles(self, n: int = 5) -> list[MosaicTile]:
        return [
            MosaicTile(
                tile_id=f"T{i}",
                quarter="2024-Q3",
                geometry={"type": "Polygon", "coordinates": []},
                href_red=f"https://example/{i}/B04.tif",
                href_green=f"https://example/{i}/B03.tif",
                href_blue=f"https://example/{i}/B02.tif",
            )
            for i in range(n)
        ]

    @staticmethod
    def _write_tile_with_origin(path: str, origin_x: float, origin_y: float, val: int) -> None:
        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(path, 4, 4, 4, gdal.GDT_Byte)
        ds.SetGeoTransform((origin_x, 0.05, 0, origin_y, 0, -0.05))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        ds.SetProjection(srs.ExportToWkt())
        for band in range(1, 4):
            ds.GetRasterBand(band).WriteArray(np.full((4, 4), val, dtype=np.uint8))
        ds.GetRasterBand(4).WriteArray(np.full((4, 4), 255, dtype=np.uint8))
        ds.GetRasterBand(4).SetColorInterpretation(gdal.GCI_AlphaBand)
        ds.FlushCache()
        ds = None

    def _run(self, tmp_path: Path, *, workers: int) -> bytes:
        clip = tmp_path / f"clip_w{workers}.geojson"
        _write_clip(clip)
        out = tmp_path / f"out_w{workers}"
        out.mkdir()

        # Each tile occupies a distinct sub-region so they don't produce
        # overlapping output — VRT ordering determinism is the only variable.
        origins = [
            (-111.9, 40.9),
            (-111.7, 40.9),
            (-111.5, 40.9),
            (-111.9, 40.7),
            (-111.7, 40.7),
        ]

        def fake_process_tile(tile: MosaicTile, output_path: str) -> str:
            idx = int(tile.tile_id[1:])
            ox, oy = origins[idx]
            self._write_tile_with_origin(output_path, ox, oy, val=50 + idx * 30)
            return output_path

        args = _make_args(clip, out, workers=workers)
        with patch("sentinel_mosaic.cli.process_tile", side_effect=fake_process_tile):
            vrt = _process_region_quarter(
                "r",
                {"type": "Polygon", "coordinates": []},
                "2024-Q3",
                args,
                preloaded_tiles=self._tiles(),
            )
        assert vrt is not None and vrt.exists()

        # Read pixel data from the per-region VRT (which references the tile COGs).
        ds = gdal.Open(str(vrt))
        try:
            payload = b"".join(ds.GetRasterBand(b).ReadAsArray().tobytes() for b in range(1, 5))
        finally:
            ds = None
        return payload

    def test_workers_4_matches_workers_1_pixels(self, tmp_path: Path) -> None:
        # Each tile goes to its own deterministic output file regardless of
        # worker count. The per-region VRT lists tiles in the same STAC order
        # for both runs, so pixel reads from the VRT must be identical.
        serial = self._run(tmp_path, workers=1)
        parallel = self._run(tmp_path, workers=4)
        assert serial == parallel

    def test_single_tile_failure_with_parallel_workers(self, tmp_path: Path) -> None:
        clip = tmp_path / "clip.geojson"
        _write_clip(clip)
        out = tmp_path / "out"
        out.mkdir()

        attempted: list[str] = []

        def fake_process_tile(tile: MosaicTile, output_path: str) -> str:
            attempted.append(tile.tile_id)
            if tile.tile_id == "T2":
                raise RuntimeError("simulated CDSE 503")
            _write_processed_tile(output_path)
            return output_path

        args = _make_args(clip, out, workers=4)
        with patch("sentinel_mosaic.cli.process_tile", side_effect=fake_process_tile):
            vrt = _process_region_quarter(
                "r",
                {"type": "Polygon", "coordinates": []},
                "2024-Q3",
                args,
                preloaded_tiles=self._tiles(),
            )
        # All 5 tiles attempted — one failure must not cancel the others.
        assert sorted(attempted) == ["T0", "T1", "T2", "T3", "T4"]
        assert vrt is not None and vrt.exists()

    def test_failed_finalize_does_not_produce_output_file(self, tmp_path: Path) -> None:
        # A tile whose finalize_output_tile fails must leave no output file on
        # disk — file absence is the resume signal for the next run.
        clip = tmp_path / "clip.geojson"
        _write_clip(clip)
        out = tmp_path / "out"
        out.mkdir()

        def fake_process_tile(tile: MosaicTile, output_path: str) -> str:
            idx = int(tile.tile_id[1:])
            self._write_tile_with_origin(output_path, -111.8, 40.8, val=10 + idx)
            return output_path

        tile_dir = out / "r_2024-Q3"

        def fake_finalize(
            processed_path: str,
            tile_id: str,
            clip_regions_path,
            region_name,
            tile_output_dir,
            pixel_size,
        ):
            if tile_id == "T1":
                raise RuntimeError("finalize failed for T1")
            output = tile_output_dir / f"{tile_id}.cog.tif"
            _write_processed_tile(str(output))
            return output

        args = _make_args(clip, out, workers=4)
        with (
            patch("sentinel_mosaic.cli.process_tile", side_effect=fake_process_tile),
            patch("sentinel_mosaic.cli.finalize_output_tile", side_effect=fake_finalize),
        ):
            _process_region_quarter(
                "r",
                {"type": "Polygon", "coordinates": []},
                "2024-Q3",
                args,
                preloaded_tiles=self._tiles(n=3),
            )

        assert (tile_dir / "T0.cog.tif").exists()
        assert not (tile_dir / "T1.cog.tif").exists(), "failed finalize must leave no output file"
        assert (tile_dir / "T2.cog.tif").exists()

    def test_in_flight_bounded_by_workers(self, tmp_path: Path) -> None:
        import threading
        import time as time_mod

        clip = tmp_path / "clip.geojson"
        _write_clip(clip)
        out = tmp_path / "out"
        out.mkdir()

        in_flight = 0
        max_in_flight = 0
        lock = threading.Lock()

        def fake_process_tile(tile: MosaicTile, output_path: str) -> str:
            nonlocal in_flight, max_in_flight
            with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            try:
                time_mod.sleep(0.05)
                _write_processed_tile(output_path)
                return output_path
            finally:
                with lock:
                    in_flight -= 1

        args = _make_args(clip, out, workers=2)
        with patch("sentinel_mosaic.cli.process_tile", side_effect=fake_process_tile):
            _process_region_quarter(
                "r",
                {"type": "Polygon", "coordinates": []},
                "2024-Q3",
                args,
                preloaded_tiles=self._tiles(n=8),
            )

        assert max_in_flight <= 2, f"executor exceeded worker bound: {max_in_flight}"
        assert max_in_flight >= 2


class TestRequiredArgs:
    def test_missing_clip_regions_exits(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["mosaic", "--output-dir", "/tmp/out", "--quarter", "2024-Q3"])
        assert exc.value.code == 2

    def test_missing_output_dir_exits(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["mosaic", "--clip-regions", "r.geojson", "--quarter", "2024-Q3"])
        assert exc.value.code == 2

    def test_missing_quarter_exits(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["mosaic", "--clip-regions", "r.geojson", "--output-dir", "/tmp/out"])
        assert exc.value.code == 2

    def test_missing_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 2


class TestBuildProcessBandsParser:
    def _base_args(self, tmp_path: Path) -> list[str]:
        return [
            "process-bands",
            "--red",
            str(tmp_path / "B04.tif"),
            "--green",
            str(tmp_path / "B03.tif"),
            "--blue",
            str(tmp_path / "B02.tif"),
            "--output",
            str(tmp_path / "out.cog.tif"),
        ]

    def test_required_args_parsed(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args(tmp_path))
        assert args.red == str(tmp_path / "B04.tif")
        assert args.green == str(tmp_path / "B03.tif")
        assert args.blue == str(tmp_path / "B02.tif")
        assert args.output == str(tmp_path / "out.cog.tif")

    def test_pixel_size_default(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args(tmp_path))
        from sentinel_mosaic.cli import PIXEL_SIZE_M

        assert args.pixel_size == PIXEL_SIZE_M

    def test_pixel_size_custom(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args(tmp_path) + ["--pixel-size", "500.0"])
        assert args.pixel_size == 500.0

    def test_verbose_default_false(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args(tmp_path))
        assert args.verbose is False

    def test_log_format_default_plain(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(self._base_args(tmp_path))
        assert args.log_format == "plain"

    def test_missing_red_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "process-bands",
                    "--green",
                    str(tmp_path / "B03.tif"),
                    "--blue",
                    str(tmp_path / "B02.tif"),
                    "--output",
                    str(tmp_path / "out.cog.tif"),
                ]
            )
        assert exc.value.code == 2

    def test_missing_output_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "process-bands",
                    "--red",
                    str(tmp_path / "B04.tif"),
                    "--green",
                    str(tmp_path / "B03.tif"),
                    "--blue",
                    str(tmp_path / "B02.tif"),
                ]
            )
        assert exc.value.code == 2


def _make_band_file(path: Path, fill: int) -> str:
    """Write a tiny single-band Int16 GeoTIFF for process-bands tests."""
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(str(path), 8, 8, 1, gdal.GDT_Int16)
    ds.SetGeoTransform((-112.0, 0.05, 0, 41.0, 0, -0.05))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(np.full((8, 8), fill, dtype=np.int16))
    ds.FlushCache()
    ds = None
    return str(path)


class TestProcessBandsCommand:
    def test_produces_cog_at_output_path(self, tmp_path: Path) -> None:
        red = _make_band_file(tmp_path / "B04.tif", 2000)
        green = _make_band_file(tmp_path / "B03.tif", 1500)
        blue = _make_band_file(tmp_path / "B02.tif", 1000)
        out = tmp_path / "out.cog.tif"

        rc = main(
            [
                "process-bands",
                "--red",
                red,
                "--green",
                green,
                "--blue",
                blue,
                "--output",
                str(out),
                "--pixel-size",
                "1000.0",
            ]
        )

        assert rc == 0
        assert out.exists()

    def test_output_has_four_bands(self, tmp_path: Path) -> None:
        red = _make_band_file(tmp_path / "B04.tif", 2000)
        green = _make_band_file(tmp_path / "B03.tif", 1500)
        blue = _make_band_file(tmp_path / "B02.tif", 1000)
        out = tmp_path / "out.cog.tif"

        main(
            [
                "process-bands",
                "--red",
                red,
                "--green",
                green,
                "--blue",
                blue,
                "--output",
                str(out),
                "--pixel-size",
                "1000.0",
            ]
        )

        ds = gdal.Open(str(out))
        try:
            assert ds.RasterCount == 4
        finally:
            ds = None

    def test_delegates_to_process_bands_and_finalize(self, tmp_path: Path) -> None:
        red = _make_band_file(tmp_path / "B04.tif", 2000)
        green = _make_band_file(tmp_path / "B03.tif", 1500)
        blue = _make_band_file(tmp_path / "B02.tif", 1000)
        out = tmp_path / "out.cog.tif"

        calls: dict[str, int] = {"process_bands": 0, "finalize_single_cog": 0}

        def fake_pb(path_r, path_g, path_b, output_path, gdal_config=None):
            calls["process_bands"] += 1
            _write_processed_tile(output_path)
            return output_path

        def fake_fc(processed_path, output_path, pixel_size=10.0, target_crs=None):
            calls["finalize_single_cog"] += 1
            _write_processed_tile(str(output_path))
            return output_path

        with (
            patch("sentinel_mosaic.cli.process_bands", side_effect=fake_pb),
            patch("sentinel_mosaic.cli.finalize_single_cog", side_effect=fake_fc),
        ):
            rc = main(
                [
                    "process-bands",
                    "--red",
                    red,
                    "--green",
                    green,
                    "--blue",
                    blue,
                    "--output",
                    str(out),
                ]
            )

        assert rc == 0
        assert calls["process_bands"] == 1
        assert calls["finalize_single_cog"] == 1

    def test_returns_one_on_missing_input(self, tmp_path: Path) -> None:
        out = tmp_path / "out.cog.tif"
        rc = main(
            [
                "process-bands",
                "--red",
                str(tmp_path / "nonexistent_B04.tif"),
                "--green",
                str(tmp_path / "nonexistent_B03.tif"),
                "--blue",
                str(tmp_path / "nonexistent_B02.tif"),
                "--output",
                str(out),
            ]
        )
        assert rc == 1
