from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from osgeo import gdal, osr


def load_module():
    repo_root = Path(__file__).resolve().parents[4]
    module_path = (
        repo_root
        / "third-party-static-data/utility/faa-raster-chart-preprocess/process_sectionals.py"
    )
    spec = importlib.util.spec_from_file_location("process_sectionals", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load chart processing module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def create_paletted_tif(
    path: Path,
    *,
    geotransform: tuple[float, float, float, float, float, float] = (
        -106.8,
        0.01,
        0.0,
        40.2,
        0.0,
        -0.01,
    ),
) -> None:
    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(
        str(path),
        128,
        128,
        1,
        gdal.GDT_Byte,
        options=["PHOTOMETRIC=PALETTE"],
    )
    dataset.SetGeoTransform(geotransform)
    source_crs = osr.SpatialReference()
    source_crs.ImportFromEPSG(4326)
    dataset.SetProjection(source_crs.ExportToWkt())
    color_table = gdal.ColorTable()
    color_table.SetColorEntry(0, (0, 0, 0, 0))
    color_table.SetColorEntry(1, (255, 0, 0, 255))
    color_table.SetColorEntry(2, (0, 255, 0, 255))
    band = dataset.GetRasterBand(1)
    band.SetRasterColorTable(color_table)
    band.SetRasterColorInterpretation(gdal.GCI_PaletteIndex)
    pixels = np.zeros((128, 128), dtype=np.uint8)
    pixels[20:100, 20:100] = 1
    pixels[50:85, 50:85] = 2
    band.WriteArray(pixels)
    dataset = None


def write_coverage_geojson(path: Path, *, chart_name: str = "Denver") -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"chart": chart_name},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-106.5, 40.0],
                            [-105.8, 40.0],
                            [-105.8, 39.2],
                            [-106.5, 39.2],
                            [-106.5, 40.0],
                        ]
                    ],
                },
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class ProcessChartsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        gdal.UseExceptions()

    def test_normalize_chart_name(self):
        self.assertEqual(self.module.normalize_chart_name("Dallas-Ft_Worth"), "dallasftworth")
        self.assertEqual(self.module.normalize_chart_name("St. Louis"), "stlouis")

    def test_discover_chart_sources_classifies_and_skips_exceptions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_dir = Path(tmpdir) / "raw_charts"
            sectional_dir = raw_dir / "Denver"
            sectional_dir.mkdir(parents=True)
            (sectional_dir / "Denver SEC.tif").write_bytes(b"placeholder")
            (sectional_dir / "Honolulu Inset SEC.tif").write_bytes(b"placeholder")

            tac_dir = raw_dir / "Denver_TAC"
            tac_dir.mkdir(parents=True)
            (tac_dir / "Denver TAC.tif").write_bytes(b"placeholder")
            (tac_dir / "Denver FLY.tif").write_bytes(b"placeholder")
            (tac_dir / "Anchorage Graphic.tif").write_bytes(b"placeholder")
            (tac_dir / "Caribbean Planning Chart.tif").write_bytes(b"placeholder")
            (tac_dir / "New York TAC VFR Planning Charts.tif").write_bytes(b"placeholder")

            discovered = self.module.discover_chart_sources(
                raw_dir,
                chart_types={
                    self.module.CHART_TYPE_SECTIONAL,
                    self.module.CHART_TYPE_TAC,
                    self.module.CHART_TYPE_FLY,
                },
            )

        by_name = {source.chart_name: source for source in discovered}
        self.assertIn("Denver", by_name)
        self.assertIn("Denver_TAC", by_name)
        denver_types = {entry.chart_type for entry in by_name["Denver"].entries}
        self.assertEqual(denver_types, {self.module.CHART_TYPE_SECTIONAL})
        denver_files = {entry.tif_path.name for entry in by_name["Denver"].entries}
        self.assertNotIn("Honolulu Inset SEC.tif", denver_files)
        denver_tac_types = {entry.chart_type for entry in by_name["Denver_TAC"].entries}
        self.assertEqual(
            denver_tac_types,
            {self.module.CHART_TYPE_TAC, self.module.CHART_TYPE_FLY},
        )
        denver_tac_files = {entry.tif_path.name for entry in by_name["Denver_TAC"].entries}
        self.assertNotIn("Anchorage Graphic.tif", denver_tac_files)
        self.assertNotIn("Caribbean Planning Chart.tif", denver_tac_files)
        self.assertNotIn("New York TAC VFR Planning Charts.tif", denver_tac_files)

    def test_select_sources_requires_chart_or_all(self):
        source = self.module.ChartSource(
            chart_name="Denver",
            normalized_chart_name="denver",
            entries=(
                self.module.ChartEntry(
                    tif_path=Path("/tmp/Denver SEC.tif"),
                    chart_type=self.module.CHART_TYPE_SECTIONAL,
                    coverage_key="denver",
                ),
            ),
        )
        with self.assertRaisesRegex(ValueError, "--chart"):
            self.module.select_sources(
                [source],
                requested_charts=None,
                all_charts=False,
            )

    def test_clipped_cog_options_support_zstd_and_jxl(self):
        zstd_options = self.module.clipped_cog_options(self.module.CLIPPED_OUTPUT_MODE_ZSTD)
        self.assertIn("COMPRESS=ZSTD", zstd_options)
        self.assertIn("PREDICTOR=2", zstd_options)
        self.assertIn("LEVEL=20", zstd_options)

        jxl_options = self.module.clipped_cog_options(self.module.CLIPPED_OUTPUT_MODE_JXL_LOSSLESS)
        self.assertIn("COMPRESS=JXL", jxl_options)
        self.assertIn("JXL_LOSSLESS=YES", jxl_options)
        self.assertIn("JXL_EFFORT=7", jxl_options)

    def test_build_pipeline_includes_configured_thread_controls(self):
        source = self.module.ChartSource(
            chart_name="Denver",
            normalized_chart_name="denver",
            entries=(
                self.module.ChartEntry(
                    tif_path=Path("/tmp/Denver SEC.tif"),
                    chart_type=self.module.CHART_TYPE_SECTIONAL,
                    coverage_key="denver",
                ),
            ),
        )
        job = self.module.ChartJob(
            source=source,
            entry=source.entries[0],
            coverage_path=Path("/tmp/denver.geojson"),
            chart_output_dir=Path("/tmp/out/Denver"),
            full_output_path=Path("/tmp/out/Denver/denver.webp.cog.tif"),
            clipped_output_path=Path("/tmp/out/Denver/denver.clip.zstd.cog.tif"),
        )
        pipeline = self.module.build_pipeline(
            job,
            clipped_output_mode=self.module.CLIPPED_OUTPUT_MODE_ZSTD,
            threads=3,
        )
        self.assertIn("--num-threads=3", pipeline)
        self.assertIn("NUM_THREADS=3", pipeline)

    def test_default_coverage_dirs(self):
        self.assertEqual(
            self.module.DEFAULT_SECTIONAL_COVERAGE_DIR.name,
            "sectional-chart-masks",
        )
        self.assertEqual(
            self.module.DEFAULT_TAC_FLY_COVERAGE_DIR.name,
            "terminal-area-fly-chart-masks",
        )
        self.assertGreaterEqual(self.module.DEFAULT_THREADS, 1)

    def test_end_to_end_single_sectional_chart_outputs_both_cogs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_dir = root / "raw_charts"
            sectional_coverage_dir = root / "sectional-chart-masks"
            tac_fly_coverage_dir = root / "terminal-area-fly-chart-masks"
            output_root = root / "processed"
            chart_dir = raw_dir / "Denver"
            chart_dir.mkdir(parents=True)
            sectional_coverage_dir.mkdir(parents=True)
            tac_fly_coverage_dir.mkdir(parents=True)

            input_tif = chart_dir / "Denver SEC.tif"
            create_paletted_tif(input_tif)
            write_coverage_geojson(sectional_coverage_dir / "denver.geojson")

            exit_code = self.module.main(
                [
                    "--chart",
                    "denver",
                    "--chart-type",
                    "sectional",
                    "--raw-charts-dir",
                    str(raw_dir),
                    "--sectional-coverage-dir",
                    str(sectional_coverage_dir),
                    "--tac-fly-coverage-dir",
                    str(tac_fly_coverage_dir),
                    "--output-root",
                    str(output_root),
                ]
            )
            self.assertEqual(exit_code, 0)

            full_output = output_root / "Denver" / "denver.webp.cog.tif"
            clipped_output = output_root / "Denver" / "denver.clip.zstd.cog.tif"
            self.assertTrue(full_output.exists())
            self.assertTrue(clipped_output.exists())

            full_info = gdal.Info(str(full_output), format="json")
            clipped_info = gdal.Info(str(clipped_output), format="json")
            full_image_structure = full_info.get("metadata", {}).get("IMAGE_STRUCTURE", {})
            clipped_image_structure = clipped_info.get("metadata", {}).get("IMAGE_STRUCTURE", {})

            self.assertEqual(full_image_structure.get("LAYOUT"), "COG")
            self.assertEqual(full_image_structure.get("COMPRESSION"), "WEBP")
            self.assertEqual(clipped_image_structure.get("LAYOUT"), "COG")
            self.assertEqual(clipped_image_structure.get("COMPRESSION"), "ZSTD")
            self.assertEqual(clipped_image_structure.get("PREDICTOR"), "2")
            self.assertEqual(clipped_info["bands"][0]["block"], [512, 512])

    def test_end_to_end_tac_and_fly_outputs_include_type_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_dir = root / "raw_charts"
            sectional_coverage_dir = root / "sectional-chart-masks"
            tac_fly_coverage_dir = root / "terminal-area-fly-chart-masks"
            output_root = root / "processed"
            chart_dir = raw_dir / "Denver_TAC"
            chart_dir.mkdir(parents=True)
            sectional_coverage_dir.mkdir(parents=True)
            tac_fly_coverage_dir.mkdir(parents=True)

            create_paletted_tif(chart_dir / "Denver TAC.tif")
            create_paletted_tif(chart_dir / "Denver FLY.tif")
            write_coverage_geojson(
                tac_fly_coverage_dir / "Denver_TAC.geojson",
                chart_name="Denver",
            )

            exit_code = self.module.main(
                [
                    "--chart",
                    "Denver_TAC",
                    "--chart-type",
                    "tac",
                    "--chart-type",
                    "fly",
                    "--raw-charts-dir",
                    str(raw_dir),
                    "--sectional-coverage-dir",
                    str(sectional_coverage_dir),
                    "--tac-fly-coverage-dir",
                    str(tac_fly_coverage_dir),
                    "--output-root",
                    str(output_root),
                ]
            )
            self.assertEqual(exit_code, 0)

            output_files = {path.name for path in (output_root / "Denver_TAC").glob("*.tif")}
            self.assertTrue(any(".tac.webp.cog.tif" in name for name in output_files))
            self.assertTrue(any(".tac.clip.zstd.cog.tif" in name for name in output_files))
            self.assertTrue(any(".fly.webp.cog.tif" in name for name in output_files))
            self.assertTrue(any(".fly.clip.zstd.cog.tif" in name for name in output_files))

    def test_all_charts_continue_on_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_dir = root / "raw_charts"
            sectional_coverage_dir = root / "sectional-chart-masks"
            tac_fly_coverage_dir = root / "terminal-area-fly-chart-masks"
            output_root = root / "processed"
            good_chart_dir = raw_dir / "Denver"
            bad_chart_dir = raw_dir / "Salt_Lake_City"
            good_chart_dir.mkdir(parents=True)
            bad_chart_dir.mkdir(parents=True)
            sectional_coverage_dir.mkdir(parents=True)
            tac_fly_coverage_dir.mkdir(parents=True)

            create_paletted_tif(good_chart_dir / "Denver SEC.tif")
            create_paletted_tif(bad_chart_dir / "Salt Lake City SEC.tif")
            write_coverage_geojson(sectional_coverage_dir / "denver.geojson")

            exit_code = self.module.main(
                [
                    "--all-charts",
                    "--chart-type",
                    "sectional",
                    "--raw-charts-dir",
                    str(raw_dir),
                    "--sectional-coverage-dir",
                    str(sectional_coverage_dir),
                    "--tac-fly-coverage-dir",
                    str(tac_fly_coverage_dir),
                    "--output-root",
                    str(output_root),
                ]
            )
            self.assertEqual(exit_code, 1)
            self.assertTrue((output_root / "Denver" / "denver.webp.cog.tif").exists())

    def test_build_region_mosaics_sectional_dry_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            mapping_json = root / "mapping.json"
            processed_root = root / "processed"
            output_dir = root / "output"

            (processed_root / "Denver").mkdir(parents=True)
            (processed_root / "Seattle").mkdir(parents=True)
            (processed_root / "Denver" / "denver.clip.jxl.cog.tif").write_bytes(b"x")
            (processed_root / "Seattle" / "seattle.clip.jxl.cog.tif").write_bytes(b"x")

            mapping_json.write_text(
                json.dumps(
                    {
                        "sectional": {"west": ["denver", "seattle", "missing_chart"]},
                        "terminal_area": {},
                    }
                ),
                encoding="utf-8",
            )

            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                exit_code = self.module.main(
                    [
                        "build-region-mosaics",
                        "--mapping-json",
                        str(mapping_json),
                        "--processed-root",
                        str(processed_root),
                        "--output-dir",
                        str(output_dir),
                        "--dry-run",
                    ]
                )

            self.assertEqual(exit_code, 0)
            output = stdout_buffer.getvalue()
            self.assertIn("DRY-RUN:", output)
            self.assertIn("sectional-west-mosaic.clip.jxl.vrt", output)
            self.assertIn("denver.clip.jxl.cog.tif", output)
            self.assertIn("seattle.clip.jxl.cog.tif", output)
            self.assertIn("missing_chart", stderr_buffer.getvalue())

    def test_build_region_mosaics_tac_dry_run_resolves_split_packages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            mapping_json = root / "mapping.json"
            processed_root = root / "processed"
            output_dir = root / "output"

            (processed_root / "Denver_TAC").mkdir(parents=True)
            (processed_root / "Seattle_TAC").mkdir(parents=True)
            (processed_root / "Tampa-Orlando_TAC").mkdir(parents=True)
            (processed_root / "Dallas-Ft_Worth_TAC").mkdir(parents=True)
            (
                processed_root / "Denver_TAC" / "denver-tac--denver-tac.tac.clip.jxl.cog.tif"
            ).write_bytes(b"x")
            (
                processed_root
                / "Denver_TAC"
                / "denver-tac--colorado-springs-tac.tac.clip.jxl.cog.tif"
            ).write_bytes(b"x")
            (
                processed_root / "Seattle_TAC" / "seattle-tac--seattle-tac.tac.clip.jxl.cog.tif"
            ).write_bytes(b"x")
            (
                processed_root / "Seattle_TAC" / "seattle-tac--portland-tac.tac.clip.jxl.cog.tif"
            ).write_bytes(b"x")
            (
                processed_root
                / "Tampa-Orlando_TAC"
                / "tampa-orlando-tac--tampa-tac.tac.clip.jxl.cog.tif"
            ).write_bytes(b"x")
            (
                processed_root
                / "Tampa-Orlando_TAC"
                / "tampa-orlando-tac--orlando-tac.tac.clip.jxl.cog.tif"
            ).write_bytes(b"x")
            (
                processed_root
                / "Dallas-Ft_Worth_TAC"
                / "dallas-ft-worth-tac.tac.clip.jxl.cog.tif"
            ).write_bytes(b"x")

            mapping_json.write_text(
                json.dumps(
                    {
                        "sectional": {},
                        "terminal_area": {
                            "conus": [
                                "denver",
                                "colorado_springs",
                                "seattle",
                                "portland",
                                "dallas-fort_worth",
                                "tampa",
                                "orlando",
                                "missing",
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                exit_code = self.module.main(
                    [
                        "build-region-mosaics",
                        "--mapping-json",
                        str(mapping_json),
                        "--processed-root",
                        str(processed_root),
                        "--output-dir",
                        str(output_dir),
                        "--chart-type",
                        "tac",
                        "--dry-run",
                    ]
                )

            self.assertEqual(exit_code, 0)
            output = stdout_buffer.getvalue()
            self.assertIn("tac-conus-mosaic.clip.jxl.vrt", output)
            self.assertIn("denver-tac--denver-tac.tac.clip.jxl.cog.tif", output)
            self.assertIn("denver-tac--colorado-springs-tac.tac.clip.jxl.cog.tif", output)
            self.assertIn("seattle-tac--portland-tac.tac.clip.jxl.cog.tif", output)
            self.assertIn("dallas-ft-worth-tac.tac.clip.jxl.cog.tif", output)
            self.assertIn("tampa-orlando-tac--orlando-tac.tac.clip.jxl.cog.tif", output)
            self.assertIn("missing", stderr_buffer.getvalue())

    def test_build_region_mosaics_fly_dry_run_filters_tac_inputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            mapping_json = root / "mapping.json"
            processed_root = root / "processed"
            output_dir = root / "output"

            (processed_root / "Seattle_TAC").mkdir(parents=True)
            (
                processed_root / "Seattle_TAC" / "seattle-tac--seattle-fly.fly.clip.jxl.cog.tif"
            ).write_bytes(b"x")
            (
                processed_root / "Seattle_TAC" / "seattle-tac--seattle-tac.tac.clip.jxl.cog.tif"
            ).write_bytes(b"x")
            (
                processed_root / "Seattle_TAC" / "seattle-tac--portland-fly.fly.clip.jxl.cog.tif"
            ).write_bytes(b"x")
            (
                processed_root / "Seattle_TAC" / "seattle-tac--portland-tac.tac.clip.jxl.cog.tif"
            ).write_bytes(b"x")

            mapping_json.write_text(
                json.dumps(
                    {
                        "sectional": {},
                        "terminal_area": {"conus": ["seattle", "portland"]},
                    }
                ),
                encoding="utf-8",
            )

            stdout_buffer = io.StringIO()
            with contextlib.redirect_stdout(stdout_buffer):
                exit_code = self.module.main(
                    [
                        "build-region-mosaics",
                        "--mapping-json",
                        str(mapping_json),
                        "--processed-root",
                        str(processed_root),
                        "--output-dir",
                        str(output_dir),
                        "--chart-type",
                        "fly",
                        "--dry-run",
                    ]
                )

            self.assertEqual(exit_code, 0)
            output = stdout_buffer.getvalue()
            self.assertIn("fly-conus-mosaic.clip.jxl.vrt", output)
            self.assertIn("seattle-tac--seattle-fly.fly.clip.jxl.cog.tif", output)
            self.assertIn("seattle-tac--portland-fly.fly.clip.jxl.cog.tif", output)
            self.assertNotIn("seattle-tac--seattle-tac.tac.clip.jxl.cog.tif", output)
            self.assertNotIn("seattle-tac--portland-tac.tac.clip.jxl.cog.tif", output)

    def test_verbose_logs_emit_stage_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_dir = root / "raw_charts"
            sectional_coverage_dir = root / "sectional-chart-masks"
            tac_fly_coverage_dir = root / "terminal-area-fly-chart-masks"
            output_root = root / "processed"
            chart_dir = raw_dir / "Denver"
            chart_dir.mkdir(parents=True)
            sectional_coverage_dir.mkdir(parents=True)
            tac_fly_coverage_dir.mkdir(parents=True)

            input_tif = chart_dir / "Denver SEC.tif"
            create_paletted_tif(input_tif)
            write_coverage_geojson(sectional_coverage_dir / "denver.geojson")

            stdout_buffer = io.StringIO()
            with contextlib.redirect_stdout(stdout_buffer):
                exit_code = self.module.main(
                    [
                        "--chart",
                        "Denver",
                        "--raw-charts-dir",
                        str(raw_dir),
                        "--sectional-coverage-dir",
                        str(sectional_coverage_dir),
                        "--tac-fly-coverage-dir",
                        str(tac_fly_coverage_dir),
                        "--output-root",
                        str(output_root),
                        "--threads",
                        "3",
                        "--verbose",
                    ]
                )
            self.assertEqual(exit_code, 0)
            logs = stdout_buffer.getvalue()
            self.assertIn("Stage A start", logs)
            self.assertIn("Stage A complete", logs)
            self.assertIn("Stage B start", logs)
            self.assertIn("Stage B complete", logs)
            self.assertIn("Stage C start", logs)
            self.assertIn("Stage C complete", logs)
            self.assertIn("Pipeline:", logs)
            self.assertIn("--num-threads=3", logs)
            self.assertIn("NUM_THREADS=3", logs)


if __name__ == "__main__":
    unittest.main()
