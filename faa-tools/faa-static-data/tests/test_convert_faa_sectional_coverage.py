from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def load_converter_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "faa-tools/faa-static-data/convert_faa_sectional_coverage.py"
    spec = importlib.util.spec_from_file_location("convert_faa_sectional_coverage", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load converter module.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, module_path, repo_root


class ConvertFaaSectionalCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.converter, cls.converter_path, cls.repo_root = load_converter_module()
        cls.input_path = cls.repo_root / "shared-configuration" / "faa-sectional-coverage.txt"
        cls.rows = cls.converter.read_coverage_rows(cls.input_path)
        cls.rows_by_chart = {row.chart: row for row in cls.rows}

    def test_parse_dms_coordinates(self):
        self.assertEqual(self.converter.parse_dms_coordinate("32°00'N"), 32.0)
        self.assertEqual(self.converter.parse_dms_coordinate("109°00'W"), -109.0)
        self.assertAlmostEqual(
            self.converter.parse_dms_coordinate("68°07’N"),
            68 + (7 / 60),
        )

    def test_parses_expected_chart_rows(self):
        self.assertGreater(len(self.rows), 40)
        self.assertIn("Albuquerque", self.rows_by_chart)
        self.assertIn("Western Aleutian Islands (East)", self.rows_by_chart)

    def test_generates_polygon_for_non_antimeridian_chart(self):
        row = self.rows_by_chart["Albuquerque"]
        feature = self.converter.build_feature(row)
        self.assertEqual(feature["geometry"]["type"], "Polygon")

    def test_generates_multipolygon_for_antimeridian_chart(self):
        row = self.rows_by_chart["Western Aleutian Islands (East)"]
        feature = self.converter.build_feature(row)
        self.assertEqual(feature["geometry"]["type"], "MultiPolygon")
        self.assertEqual(len(feature["geometry"]["coordinates"]), 2)

    def test_convert_file_outputs_valid_geojson(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "coverage.geojson"
            row_count = self.converter.convert_file(self.input_path, output_path, indent=2)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["type"], "FeatureCollection")
        self.assertEqual(len(payload["features"]), row_count)
        first_feature = payload["features"][0]
        self.assertEqual(first_feature["type"], "Feature")
        self.assertIn("chart", first_feature["properties"])
        self.assertIn("source_fields", first_feature["properties"])
        self.assertIn("corner_decimal_degrees", first_feature["properties"])

    def test_chart_filename_slugifies_chart_name(self):
        self.assertEqual(self.converter.chart_filename("Denver"), "denver.geojson")
        self.assertEqual(
            self.converter.chart_filename("Dallas - Ft. Worth"),
            "dallas-ft-worth.geojson",
        )
        self.assertEqual(
            self.converter.chart_filename("Western Aleutian Islands (East)"),
            "western-aleutian-islands-east.geojson",
        )

    def test_convert_to_coverage_directory_outputs_feature_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coverage_dir = Path(tmpdir) / "coverage"
            row_count = self.converter.convert_to_coverage_directory(
                self.input_path,
                coverage_dir,
                indent=2,
            )

            files = sorted(coverage_dir.glob("*.geojson"))
            denver_file = coverage_dir / "denver.geojson"
            denver_payload = json.loads(denver_file.read_text(encoding="utf-8"))

        self.assertEqual(len(files), row_count)
        self.assertEqual(denver_payload["type"], "Feature")
        self.assertEqual(denver_payload["properties"]["chart"], "Denver")

    def test_cli_accepts_configurable_input_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "charts.geojson"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(self.converter_path),
                    "--input",
                    str(self.input_path),
                    "--output",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["type"], "FeatureCollection")
        self.assertIn("Wrote", completed.stdout)

    def test_cli_accepts_coverage_directory_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coverage_dir = Path(tmpdir) / "coverage"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(self.converter_path),
                    "--input",
                    str(self.input_path),
                    "--coverage-dir",
                    str(coverage_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            denver_payload = json.loads((coverage_dir / "denver.geojson").read_text())

        self.assertEqual(denver_payload["type"], "Feature")
        self.assertEqual(denver_payload["properties"]["chart"], "Denver")
        self.assertIn("directory", completed.stdout)


if __name__ == "__main__":
    unittest.main()
