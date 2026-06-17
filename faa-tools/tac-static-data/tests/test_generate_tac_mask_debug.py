from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional dependency
    np = None

try:
    from rasterio.transform import from_origin
except ImportError:  # pragma: no cover - optional dependency
    from_origin = None


def load_module():
    module_path = (
        Path(__file__).resolve().parents[1] / "generate_tac_mask_debug.py"
    )
    spec = importlib.util.spec_from_file_location(
        "generate_tac_mask_debug", module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load generate_tac_mask_debug module.")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipIf(np is None, "numpy is required for mask tests")
class MaskDebugTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_background_mask_matches_palette_index(self):
        data = np.array(
            [
                [0, 0, 1],
                [0, 2, 1],
                [0, 0, 0],
            ],
            dtype=np.uint8,
        )
        mask = self.module.background_mask(data, 0, tolerance=0)
        self.assertTrue(mask[0, 0])
        self.assertFalse(mask[1, 1])

    def test_flood_fill_marks_edge_background(self):
        data = np.array(
            [
                [True, True, True],
                [True, False, True],
                [True, True, True],
            ]
        )
        outside = self.module.flood_fill_from_edges(data)
        self.assertTrue(outside[0, 0])
        self.assertFalse(outside[1, 1])

    def test_build_debug_mask_finds_center_object(self):
        data = np.zeros((6, 6), dtype=np.uint8)
        data[2:4, 2:4] = 5
        mask, _ = self.module.build_debug_mask(
            data,
            edge_width=1,
            tolerance=0,
            close_iterations=0,
            palette=None,
            ink_threshold=0,
            neatline_coverage=1.0,
            core_erode_iterations=0,
            extension_gap=1,
            extension_min_area=1,
            extension_max_area_ratio=0.5,
            extension_max_fill_ratio=1.0,
            extension_max_thickness=3,
            extension_max_overhang_north=10,
            extension_max_overhang_south=10,
            extension_max_overhang_west=10,
            extension_max_overhang_east=10,
            island_east_band_width=64,
            island_east_min_area=8,
            island_east_min_span=2,
        )
        self.assertTrue(mask[2, 2])
        self.assertFalse(mask[0, 0])

    def test_dominant_core_mask_drops_corner_artifact(self):
        chart_mask = np.zeros((25, 25), dtype=bool)
        chart_mask[8:20, 8:20] = True
        chart_mask[1:6, 4:9] = True
        core = self.module.dominant_core_mask(chart_mask, erode_iterations=1)
        corners = self.module.corner_points(core)
        self.assertEqual(corners["nw"], (8, 8))

    def test_select_extension_components_keeps_thin_and_rejects_dense(self):
        core = np.zeros((30, 30), dtype=bool)
        core[10:20, 10:20] = True
        chart = core.copy()
        # Thin attached extension (line-like) should be kept.
        chart[9, 13:18] = True
        # Dense attached block should be rejected by fill ratio.
        chart[4:9, 20:25] = True
        chart[9:11, 21] = True  # bridge to core

        extensions, report = self.module.select_extension_components(
            chart,
            core,
            gap_pixels=1,
            min_area=2,
            max_area_ratio=0.5,
            max_fill_ratio=0.6,
            max_thickness=2,
            max_overhang_north=10,
            max_overhang_south=10,
            max_overhang_west=10,
            max_overhang_east=10,
        )
        self.assertTrue(extensions[9, 14])
        self.assertFalse(extensions[6, 22])
        self.assertEqual(len(report), 2)
        self.assertIn("above_fill_ratio", {item["reason"] for item in report})

    def test_select_extension_components_rejects_large_overhang(self):
        core = np.zeros((30, 30), dtype=bool)
        core[10:20, 10:20] = True
        chart = core.copy()
        chart[12:15, 20:29] = True

        extensions, report = self.module.select_extension_components(
            chart,
            core,
            gap_pixels=2,
            min_area=2,
            max_area_ratio=0.5,
            max_fill_ratio=1.0,
            max_thickness=10,
            max_overhang_north=4,
            max_overhang_south=4,
            max_overhang_west=4,
            max_overhang_east=4,
        )
        self.assertFalse(extensions.any())
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["reason"], "above_overhang_east")

    def test_corner_points_returns_extremes(self):
        mask = np.zeros((5, 5), dtype=bool)
        mask[1:4, 1:4] = True
        corners = self.module.corner_points(mask)
        self.assertEqual(corners["nw"], (1, 1))
        self.assertEqual(corners["ne"], (1, 3))
        self.assertEqual(corners["se"], (3, 3))
        self.assertEqual(corners["sw"], (3, 1))

    @unittest.skipIf(from_origin is None, "rasterio is required")
    def test_mask_to_source_geometry_returns_multipolygon(self):
        mask = np.zeros((10, 10), dtype=bool)
        mask[1:3, 1:3] = True
        mask[6:8, 6:8] = True
        geometry = self.module.mask_to_source_geometry(mask, from_origin(0, 10, 1, 1))
        self.assertEqual(geometry["type"], "MultiPolygon")
        self.assertEqual(len(geometry["coordinates"]), 2)

    def test_build_geojson_feature_structure(self):
        geometry = {
            "type": "Polygon",
            "coordinates": [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 0.0)]],
        }
        feature = self.module.build_geojson_feature(
            "Test Chart",
            geometry,
            source_path=Path("example.tif"),
            mask_shape=(10, 12),
            heuristics={"tolerance": 0},
            corners={"nw": (0, 0), "ne": (0, 1), "se": (1, 1), "sw": (1, 0)},
        )
        self.assertEqual(feature["type"], "Feature")
        self.assertEqual(feature["geometry"]["type"], "Polygon")
        self.assertEqual(feature["properties"]["mask_shape"]["height"], 10)

    def test_parse_args_defaults(self):
        with patch.object(sys, "argv", ["prog", "--input", "example.tif"]):
            args = self.module.parse_args()
        self.assertEqual(args.close_iterations, 0)
        self.assertEqual(args.tolerance, 0)

    def test_close_mask_can_merge_corner_artifact(self):
        mask = np.zeros((25, 25), dtype=bool)
        mask[8:20, 8:20] = True
        mask[1:6, 4:9] = True

        base_component = self.module.largest_connected_component(mask)
        base_corners = self.module.corner_points(base_component)
        self.assertEqual(base_corners["nw"], (8, 8))

        closed_component = self.module.largest_connected_component(
            self.module.close_mask(mask, 1)
        )
        closed_corners = self.module.corner_points(closed_component)
        self.assertEqual(closed_corners["nw"], (0, 4))

    def test_slc_fixture_extensions_keep_edge_annotation_without_legend(self):
        snapshot_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "slc_downsample_stage_snapshot.npz"
        )
        oracle_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "slc_hand_oracle_mask_512.npz"
        )
        snapshot = np.load(snapshot_path)
        raw = snapshot["raw"].astype(bool)
        core = snapshot["core"].astype(bool)
        oracle = np.load(oracle_path)["mask"].astype(bool)

        extensions, _ = self.module.select_extension_components(
            raw,
            core,
            gap_pixels=6,
            min_area=6,
            max_area_ratio=0.12,
            max_fill_ratio=0.72,
            max_thickness=3,
            max_overhang_north=7,
            max_overhang_south=7,
            max_overhang_west=24,
            max_overhang_east=24,
        )
        recomputed_final = self.module.prune_small_components(
            core | extensions,
            min_area=6,
        )
        recomputed_final = self.module.filter_output_components(
            recomputed_final,
            east_band_width=64,
            east_min_area=8,
            east_min_span=2,
        )

        # Regression guard: top-left legend artifact remains excluded.
        self.assertFalse(recomputed_final[3, 81])
        self.assertEqual(int(extensions[:40, :120].sum()), 0)
        # Regression guard: keep at least one right-edge off-neatline extension.
        self.assertTrue(extensions[77, 446])
        self.assertGreater(int(extensions.sum()), 0)

        # Oracle metrics against hand-edited SLC mask.
        intersection = int(np.logical_and(recomputed_final, oracle).sum())
        union = int(np.logical_or(recomputed_final, oracle).sum())
        iou = float(intersection / union)
        self.assertGreaterEqual(iou, 0.991)

        false_positive = np.logical_and(recomputed_final, ~oracle)
        components = self.module.connected_components(false_positive)
        large_fp_components = [c for c in components if int(c["area"]) >= 16]
        self.assertLessEqual(len(large_fp_components), 2)

        output_components = self.module.connected_components(recomputed_final)
        self.assertLessEqual(len(output_components), 2)

        false_negative = np.logical_and(oracle, ~recomputed_final)
        width = oracle.shape[1]
        east_fn = int(false_negative[:, width - 80 :].sum())
        self.assertLessEqual(east_fn, 6)


if __name__ == "__main__":
    unittest.main()
