#!/usr/bin/env python3
"""Generate a heuristic TAC chart mask and coverage GeoJSON from a GeoTIFF."""

from __future__ import annotations

import argparse
from collections import Counter, deque
from pathlib import Path

import json
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a heuristic TAC chart mask and coverage GeoJSON by "
            "flood-filling likely background from edges, deriving a conservative "
            "core component, and selectively adding nearby extension components."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input TAC GeoTIFF path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output final mask PNG path (defaults to <input>.mask.png).",
    )
    parser.add_argument(
        "--full-mask-output",
        type=Path,
        help="Optional alias path for writing the full final mask PNG.",
    )
    parser.add_argument(
        "--geojson-output",
        type=Path,
        help="Output GeoJSON feature file (defaults to <input>.coverage.geojson).",
    )
    parser.add_argument(
        "--corners-json",
        type=Path,
        help="Optional path to write extreme mask corners as JSON.",
    )
    parser.add_argument(
        "--debug-prefix",
        type=Path,
        help=(
            "Optional prefix for stage debug artifacts. Writes "
            "<prefix>-background.png, <prefix>-raw.png, <prefix>-core.png, "
            "<prefix>-extensions.png, <prefix>-final.png, and "
            "<prefix>-components.json."
        ),
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=512,
        help="Max dimension for downsampled processing mask (default: 512).",
    )
    parser.add_argument(
        "--edge-width",
        type=int,
        default=2,
        help="Edge width in pixels for background color sampling (default: 2).",
    )
    parser.add_argument(
        "--tolerance",
        type=int,
        default=0,
        help="RGB tolerance for background matching (default: 0).",
    )
    parser.add_argument(
        "--ink-threshold",
        type=int,
        default=40,
        help="RGB sum threshold for detecting dark neatline ink (default: 40).",
    )
    parser.add_argument(
        "--neatline-coverage",
        type=float,
        default=0.6,
        help="Row/column dark-ink coverage ratio for neatline hints (default: 0.6).",
    )
    parser.add_argument(
        "--core-erode-iterations",
        type=int,
        default=1,
        help=(
            "Erode iterations before selecting dominant core component; the same "
            "count is then dilated back (default: 1)."
        ),
    )
    parser.add_argument(
        "--extension-gap",
        type=int,
        default=6,
        help="Max dilation gap (pixels) for extension-to-core attachment (default: 6).",
    )
    parser.add_argument(
        "--extension-min-area",
        type=int,
        default=6,
        help="Minimum extension component area in pixels (default: 6).",
    )
    parser.add_argument(
        "--extension-max-area-ratio",
        type=float,
        default=0.12,
        help="Max extension area / core area ratio (default: 0.12).",
    )
    parser.add_argument(
        "--extension-max-fill-ratio",
        type=float,
        default=0.72,
        help=(
            "Max component fill ratio (area / bbox area) for keeping extensions "
            "(default: 0.72)."
        ),
    )
    parser.add_argument(
        "--extension-max-thickness",
        type=int,
        default=3,
        help=(
            "Allow dense extension components only when their shorter bbox "
            "dimension is <= this thickness (default: 3)."
        ),
    )
    parser.add_argument(
        "--extension-max-overhang",
        type=int,
        default=24,
        help=(
            "Maximum pixels an extension may protrude beyond core bounds on any "
            "side (default: 24)."
        ),
    )
    parser.add_argument(
        "--extension-max-overhang-north",
        type=int,
        help=(
            "Optional north-side overhang override; defaults to 7 when omitted."
        ),
    )
    parser.add_argument(
        "--extension-max-overhang-south",
        type=int,
        help=(
            "Optional south-side overhang override; defaults to 7 when omitted."
        ),
    )
    parser.add_argument(
        "--extension-max-overhang-west",
        type=int,
        help=(
            "Optional west-side overhang override; defaults to "
            "--extension-max-overhang."
        ),
    )
    parser.add_argument(
        "--extension-max-overhang-east",
        type=int,
        help=(
            "Optional east-side overhang override; defaults to "
            "--extension-max-overhang."
        ),
    )
    parser.add_argument(
        "--island-east-band-width",
        type=int,
        default=64,
        help=(
            "Pixels from the right edge used to preserve east-side non-main "
            "islands after mask assembly (default: 64)."
        ),
    )
    parser.add_argument(
        "--island-east-min-area",
        type=int,
        default=8,
        help=(
            "Minimum area for east-band non-main islands to survive output "
            "component filtering (default: 8)."
        ),
    )
    parser.add_argument(
        "--island-east-min-span",
        type=int,
        default=2,
        help=(
            "Minimum bbox span (height or width) for east-band non-main islands "
            "to survive output component filtering (default: 2)."
        ),
    )
    parser.add_argument(
        "--close-iterations",
        type=int,
        default=0,
        help="Binary close iterations for final mask cleanup (default: 0).",
    )
    return parser.parse_args()


def most_common_edge_color(edge_pixels: np.ndarray) -> tuple[int, ...]:
    flattened = edge_pixels.reshape(-1, edge_pixels.shape[-1])
    counts = Counter(tuple(pixel.tolist()) for pixel in flattened)
    return counts.most_common(1)[0][0]


def most_common_edge_index(edge_pixels: np.ndarray) -> int:
    flattened = edge_pixels.reshape(-1)
    return int(np.bincount(flattened).argmax())


def palette_to_rgb(
    data: np.ndarray,
    palette: dict[int, tuple[int, int, int, int]],
) -> np.ndarray:
    max_index = int(data.max())
    table = np.zeros((max_index + 1, 3), dtype=np.uint8)
    for idx, rgba in palette.items():
        if idx <= max_index:
            table[idx] = rgba[:3]
    return table[data]


def background_mask(
    data: np.ndarray,
    background: tuple[int, ...] | int,
    *,
    tolerance: int,
    palette: dict[int, tuple[int, int, int, int]] | None = None,
) -> np.ndarray:
    if data.ndim == 2:
        if palette is None or tolerance <= 0:
            return data == int(background)
        background_rgb = palette.get(int(background))
        if background_rgb is None:
            return data == int(background)
        rgb = palette_to_rgb(data, palette).astype(int)
        diff = np.abs(rgb - np.array(background_rgb[:3], dtype=int))
        distance = diff.sum(axis=2)
        return distance <= tolerance

    diff = np.abs(data.astype(int) - np.array(background, dtype=int))
    distance = diff.sum(axis=2)
    return distance <= tolerance


def flood_fill_from_edges(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    queue: deque[tuple[int, int]] = deque()

    def enqueue(y: int, x: int) -> None:
        if 0 <= y < height and 0 <= x < width and mask[y, x] and not visited[y, x]:
            visited[y, x] = True
            queue.append((y, x))

    for x in range(width):
        enqueue(0, x)
        enqueue(height - 1, x)
    for y in range(1, height - 1):
        enqueue(y, 0)
        enqueue(y, width - 1)

    while queue:
        y, x = queue.popleft()
        enqueue(y - 1, x)
        enqueue(y + 1, x)
        enqueue(y, x - 1)
        enqueue(y, x + 1)

    return visited


def dilate(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    height, width = mask.shape
    result = np.zeros_like(mask, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            result |= padded[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width]
    return result


def erode(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1, mode="constant", constant_values=True)
    height, width = mask.shape
    result = np.ones_like(mask, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            result &= padded[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width]
    return result


def close_mask(mask: np.ndarray, iterations: int) -> np.ndarray:
    closed = mask
    for _ in range(max(0, iterations)):
        closed = erode(dilate(closed))
    return closed


def connected_components(mask: np.ndarray) -> list[dict[str, object]]:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[dict[str, object]] = []

    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue
            queue: deque[tuple[int, int]] = deque([(y, x)])
            visited[y, x] = True
            rows: list[int] = []
            cols: list[int] = []
            min_row = y
            max_row = y
            min_col = x
            max_col = x
            while queue:
                cy, cx = queue.popleft()
                rows.append(cy)
                cols.append(cx)
                min_row = min(min_row, cy)
                max_row = max(max_row, cy)
                min_col = min(min_col, cx)
                max_col = max(max_col, cx)
                for ny, nx in (
                    (cy - 1, cx),
                    (cy + 1, cx),
                    (cy, cx - 1),
                    (cy, cx + 1),
                ):
                    if (
                        0 <= ny < height
                        and 0 <= nx < width
                        and mask[ny, nx]
                        and not visited[ny, nx]
                    ):
                        visited[ny, nx] = True
                        queue.append((ny, nx))
            components.append(
                {
                    "rows": np.array(rows, dtype=np.int32),
                    "cols": np.array(cols, dtype=np.int32),
                    "area": len(rows),
                    "bbox": (min_row, min_col, max_row, max_col),
                }
            )
    return components


def largest_connected_component(mask: np.ndarray) -> np.ndarray:
    components = connected_components(mask)
    if not components:
        raise ValueError("No foreground pixels found in mask.")
    largest = max(components, key=lambda comp: int(comp["area"]))
    result = np.zeros_like(mask, dtype=bool)
    result[largest["rows"], largest["cols"]] = True
    return result


def corner_points(mask: np.ndarray) -> dict[str, tuple[int, int]]:
    ys, xs = np.where(mask)
    if ys.size == 0:
        raise ValueError("Cannot compute corners from an empty mask.")

    sums = ys + xs
    diffs = ys - xs
    nw = (int(ys[np.argmin(sums)]), int(xs[np.argmin(sums)]))
    ne = (int(ys[np.argmin(diffs)]), int(xs[np.argmin(diffs)]))
    se = (int(ys[np.argmax(sums)]), int(xs[np.argmax(sums)]))
    sw = (int(ys[np.argmax(diffs)]), int(xs[np.argmax(diffs)]))
    return {"nw": nw, "ne": ne, "se": se, "sw": sw}


def _rgb_view(
    data: np.ndarray,
    palette: dict[int, tuple[int, int, int, int]] | None,
) -> np.ndarray:
    if data.ndim == 3:
        return data
    if palette is None:
        return np.repeat(data[:, :, None], 3, axis=2)
    return palette_to_rgb(data, palette)


def expand_background_outside_neatline(
    bg_mask: np.ndarray,
    data: np.ndarray,
    *,
    palette: dict[int, tuple[int, int, int, int]] | None,
    ink_threshold: int,
    coverage_ratio: float,
) -> np.ndarray:
    rgb = _rgb_view(data, palette).astype(int)
    ink_mask = rgb.sum(axis=2) <= ink_threshold
    height, width = ink_mask.shape
    row_counts = ink_mask.sum(axis=1)
    col_counts = ink_mask.sum(axis=0)

    row_thresh = int(width * coverage_ratio)
    col_thresh = int(height * coverage_ratio)

    rows = np.where(row_counts >= row_thresh)[0]
    cols = np.where(col_counts >= col_thresh)[0]

    if rows.size >= 2:
        top = int(rows[0])
        bottom = int(rows[-1])
        bg_mask[:top, :] = True
        bg_mask[bottom + 1 :, :] = True

    if cols.size >= 2:
        left = int(cols[0])
        right = int(cols[-1])
        bg_mask[:, :left] = True
        bg_mask[:, right + 1 :] = True

    return bg_mask


def dominant_core_mask(chart_mask: np.ndarray, *, erode_iterations: int) -> np.ndarray:
    if not chart_mask.any():
        raise ValueError("No chart pixels found in raw chart mask.")

    seed = chart_mask.copy()
    for _ in range(max(0, erode_iterations)):
        seed = erode(seed)
        if not seed.any():
            break

    if seed.any():
        seed = largest_connected_component(seed)
        core = seed
        for _ in range(max(0, erode_iterations)):
            core = dilate(core)
        core &= chart_mask
        if core.any():
            return core

    return largest_connected_component(chart_mask)


def _component_fill_ratio(
    area: int,
    bbox: tuple[int, int, int, int],
) -> float:
    min_row, min_col, max_row, max_col = bbox
    bbox_area = (max_row - min_row + 1) * (max_col - min_col + 1)
    if bbox_area <= 0:
        return 0.0
    return float(area) / float(bbox_area)


def _touches_core_with_gap(
    component_mask: np.ndarray,
    core_mask: np.ndarray,
    gap_pixels: int,
) -> bool:
    expanded = component_mask
    for _ in range(max(0, gap_pixels)):
        expanded = dilate(expanded)
    return bool(np.any(expanded & core_mask))


def select_extension_components(
    chart_mask: np.ndarray,
    core_mask: np.ndarray,
    *,
    gap_pixels: int,
    min_area: int,
    max_area_ratio: float,
    max_fill_ratio: float,
    max_thickness: int,
    max_overhang_north: int,
    max_overhang_south: int,
    max_overhang_west: int,
    max_overhang_east: int,
) -> tuple[np.ndarray, list[dict[str, object]]]:
    candidate_mask = chart_mask & ~core_mask
    components = connected_components(candidate_mask)
    extension_mask = np.zeros_like(chart_mask, dtype=bool)
    report: list[dict[str, object]] = []
    core_area = int(core_mask.sum())
    max_area = max(1, int(core_area * max(0.0, max_area_ratio)))
    core_rows, core_cols = np.where(core_mask)
    core_min_row = int(core_rows.min())
    core_max_row = int(core_rows.max())
    core_min_col = int(core_cols.min())
    core_max_col = int(core_cols.max())

    for idx, component in enumerate(components):
        rows = component["rows"]
        cols = component["cols"]
        area = int(component["area"])
        bbox = component["bbox"]
        bbox_height = int(bbox[2] - bbox[0] + 1)
        bbox_width = int(bbox[3] - bbox[1] + 1)
        min_thickness = min(bbox_height, bbox_width)
        top_overhang = max(0, core_min_row - int(bbox[0]))
        left_overhang = max(0, core_min_col - int(bbox[1]))
        bottom_overhang = max(0, int(bbox[2]) - core_max_row)
        right_overhang = max(0, int(bbox[3]) - core_max_col)
        max_component_overhang = max(
            top_overhang, left_overhang, bottom_overhang, right_overhang
        )
        component_mask = np.zeros_like(chart_mask, dtype=bool)
        component_mask[rows, cols] = True
        fill_ratio = _component_fill_ratio(area, bbox)
        touches_core = _touches_core_with_gap(component_mask, core_mask, gap_pixels)

        keep = True
        reason = "kept"
        if area < max(1, min_area):
            keep = False
            reason = "below_min_area"
        elif area > max_area:
            keep = False
            reason = "above_max_area"
        elif fill_ratio > max_fill_ratio and min_thickness > max(1, max_thickness):
            keep = False
            reason = "above_fill_ratio"
        elif top_overhang > max(0, max_overhang_north):
            keep = False
            reason = "above_overhang_north"
        elif bottom_overhang > max(0, max_overhang_south):
            keep = False
            reason = "above_overhang_south"
        elif left_overhang > max(0, max_overhang_west):
            keep = False
            reason = "above_overhang_west"
        elif right_overhang > max(0, max_overhang_east):
            keep = False
            reason = "above_overhang_east"
        elif not touches_core:
            keep = False
            reason = "not_attached_to_core"

        if keep:
            extension_mask |= component_mask

        report.append(
            {
                "id": idx,
                "area": area,
                "bbox": {
                    "min_row": int(bbox[0]),
                    "min_col": int(bbox[1]),
                    "max_row": int(bbox[2]),
                    "max_col": int(bbox[3]),
                },
                "fill_ratio": fill_ratio,
                "min_thickness": int(min_thickness),
                "max_overhang": int(max_component_overhang),
                "overhang": {
                    "north": int(top_overhang),
                    "south": int(bottom_overhang),
                    "west": int(left_overhang),
                    "east": int(right_overhang),
                },
                "touches_core": touches_core,
                "kept": keep,
                "reason": reason,
            }
        )

    return extension_mask, report


def prune_small_components(mask: np.ndarray, *, min_area: int) -> np.ndarray:
    components = connected_components(mask)
    pruned = np.zeros_like(mask, dtype=bool)
    for component in components:
        if int(component["area"]) < max(1, min_area):
            continue
        pruned[component["rows"], component["cols"]] = True
    return pruned


def filter_output_components(
    mask: np.ndarray,
    *,
    east_band_width: int,
    east_min_area: int,
    east_min_span: int,
) -> np.ndarray:
    components = connected_components(mask)
    if not components:
        return mask

    width = mask.shape[1]
    east_threshold = width - max(1, east_band_width)
    main = max(components, key=lambda comp: int(comp["area"]))
    filtered = np.zeros_like(mask, dtype=bool)
    filtered[main["rows"], main["cols"]] = True

    for component in components:
        if component is main:
            continue
        area = int(component["area"])
        min_row, min_col, max_row, max_col = component["bbox"]
        bbox_height = int(max_row - min_row + 1)
        bbox_width = int(max_col - min_col + 1)
        span = max(bbox_height, bbox_width)
        near_east = max_col >= east_threshold
        if (
            near_east
            and area >= max(1, east_min_area)
            and span >= max(1, east_min_span)
        ):
            filtered[component["rows"], component["cols"]] = True

    return filtered


def build_debug_mask(
    data: np.ndarray,
    *,
    edge_width: int,
    tolerance: int,
    close_iterations: int,
    palette: dict[int, tuple[int, int, int, int]] | None,
    ink_threshold: int,
    neatline_coverage: float,
    core_erode_iterations: int,
    extension_gap: int,
    extension_min_area: int,
    extension_max_area_ratio: float,
    extension_max_fill_ratio: float,
    extension_max_thickness: int,
    extension_max_overhang_north: int,
    extension_max_overhang_south: int,
    extension_max_overhang_west: int,
    extension_max_overhang_east: int,
    island_east_band_width: int,
    island_east_min_area: int,
    island_east_min_span: int,
) -> tuple[np.ndarray, dict[str, object]]:
    if data.ndim == 2:
        edge_pixels = np.concatenate(
            [
                data[:edge_width, :].reshape(-1),
                data[-edge_width:, :].reshape(-1),
                data[:, :edge_width].reshape(-1),
                data[:, -edge_width:].reshape(-1),
            ],
            axis=0,
        )
        background = most_common_edge_index(edge_pixels)
    else:
        edge_pixels = np.concatenate(
            [
                data[:edge_width, :, :].reshape(-1, data.shape[2]),
                data[-edge_width:, :, :].reshape(-1, data.shape[2]),
                data[:, :edge_width, :].reshape(-1, data.shape[2]),
                data[:, -edge_width:, :].reshape(-1, data.shape[2]),
            ],
            axis=0,
        )
        background = most_common_edge_color(edge_pixels)

    bg_mask = background_mask(
        data, background, tolerance=tolerance, palette=palette
    )
    bg_mask = expand_background_outside_neatline(
        bg_mask,
        data,
        palette=palette,
        ink_threshold=ink_threshold,
        coverage_ratio=neatline_coverage,
    )

    outside = flood_fill_from_edges(bg_mask)
    raw_chart_mask = ~outside
    core_mask = dominant_core_mask(
        raw_chart_mask,
        erode_iterations=max(0, core_erode_iterations),
    )
    extension_mask, component_report = select_extension_components(
        raw_chart_mask,
        core_mask,
        gap_pixels=max(0, extension_gap),
        min_area=max(1, extension_min_area),
        max_area_ratio=max(0.0, extension_max_area_ratio),
        max_fill_ratio=max(0.0, min(1.0, extension_max_fill_ratio)),
        max_thickness=max(1, extension_max_thickness),
        max_overhang_north=max(0, extension_max_overhang_north),
        max_overhang_south=max(0, extension_max_overhang_south),
        max_overhang_west=max(0, extension_max_overhang_west),
        max_overhang_east=max(0, extension_max_overhang_east),
    )
    final_mask = core_mask | extension_mask
    if close_iterations:
        final_mask = close_mask(final_mask, close_iterations)
    final_mask = prune_small_components(final_mask, min_area=max(1, extension_min_area))
    final_mask = filter_output_components(
        final_mask,
        east_band_width=max(1, island_east_band_width),
        east_min_area=max(1, island_east_min_area),
        east_min_span=max(1, island_east_min_span),
    )
    if not final_mask.any():
        raise ValueError("Final chart mask is empty.")

    stages = {
        "background": bg_mask,
        "outside": outside,
        "raw": raw_chart_mask,
        "core": core_mask,
        "extensions": extension_mask,
        "final": final_mask,
        "component_report": component_report,
    }
    return final_mask, stages


def downsample_data(dataset, max_size: int) -> tuple[np.ndarray, object]:
    from rasterio.enums import Resampling
    from rasterio.transform import Affine

    width = dataset.width
    height = dataset.height
    scale = min(1.0, max_size / max(width, height))
    out_width = max(1, int(width * scale))
    out_height = max(1, int(height * scale))
    transform = dataset.transform * Affine.scale(
        width / out_width, height / out_height
    )

    if dataset.count >= 3:
        data = dataset.read(
            [1, 2, 3],
            out_shape=(3, out_height, out_width),
            resampling=Resampling.nearest,
        )
        return np.transpose(data, (1, 2, 0)), transform

    data = dataset.read(
        1,
        out_shape=(out_height, out_width),
        resampling=Resampling.nearest,
    )
    return data, transform


def write_mask_png(mask: np.ndarray, output_path: Path) -> None:
    from PIL import Image

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(mask.astype(np.uint8) * 255, mode="L")
    image.save(output_path)


def write_debug_stages(debug_prefix: Path, stages: dict[str, object]) -> None:
    stage_keys = ("background", "raw", "core", "extensions", "final")
    for key in stage_keys:
        stage_path = debug_prefix.parent / f"{debug_prefix.name}-{key}.png"
        write_mask_png(stages[key], stage_path)

    components_path = debug_prefix.parent / f"{debug_prefix.name}-components.json"
    components_path.write_text(
        json.dumps(stages["component_report"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def mask_to_source_geometry(mask: np.ndarray, transform) -> dict[str, object]:
    from rasterio.features import shapes

    geometries: list[dict[str, object]] = []
    for geometry, value in shapes(
        mask.astype(np.uint8),
        mask=mask,
        transform=transform,
    ):
        if int(value) == 1:
            geometries.append(geometry)

    if not geometries:
        raise ValueError("No geometries extracted from final mask.")

    polygons = [g for g in geometries if g.get("type") == "Polygon"]
    if len(polygons) == 1:
        return polygons[0]
    return {
        "type": "MultiPolygon",
        "coordinates": [polygon["coordinates"] for polygon in polygons],
    }


def build_geojson_feature(
    chart_name: str,
    geometry_wgs84: dict[str, object],
    *,
    source_path: Path,
    mask_shape: tuple[int, int],
    heuristics: dict[str, object],
    corners: dict[str, tuple[int, int]],
) -> dict[str, object]:
    properties = {
        "chart": chart_name,
        "source": str(source_path),
        "mask_shape": {"height": int(mask_shape[0]), "width": int(mask_shape[1])},
        "heuristics": heuristics,
        "corner_pixels": {
            key: {"row": row, "col": col} for key, (row, col) in corners.items()
        },
    }
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": geometry_wgs84,
    }


def write_geojson(feature: dict[str, object], output_path: Path) -> None:
    payload = {"type": "FeatureCollection", "features": [feature]}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        f"{json.dumps(payload, indent=2, ensure_ascii=False)}\n",
        encoding="utf-8",
    )


def main() -> int:
    import rasterio
    from rasterio.warp import transform_geom

    args = parse_args()
    output_path = args.output or args.input.with_suffix(".mask.png")
    geojson_path = args.geojson_output or args.input.with_suffix(".coverage.geojson")
    max_overhang = max(0, args.extension_max_overhang)
    overhang_north = (
        7
        if args.extension_max_overhang_north is None
        else max(0, args.extension_max_overhang_north)
    )
    overhang_south = (
        7
        if args.extension_max_overhang_south is None
        else max(0, args.extension_max_overhang_south)
    )
    overhang_west = (
        max_overhang
        if args.extension_max_overhang_west is None
        else max(0, args.extension_max_overhang_west)
    )
    overhang_east = (
        max_overhang
        if args.extension_max_overhang_east is None
        else max(0, args.extension_max_overhang_east)
    )

    with rasterio.open(args.input) as dataset:
        if dataset.crs is None:
            raise ValueError("GeoTIFF CRS is missing.")
        data, transform = downsample_data(dataset, args.max_size)
        palette = None
        if dataset.count == 1 and dataset.colorinterp[0].name == "palette":
            palette = dataset.colormap(1)
        source_crs = dataset.crs
        chart_name = args.input.stem

    final_mask, stages = build_debug_mask(
        data,
        edge_width=max(1, args.edge_width),
        tolerance=max(0, args.tolerance),
        close_iterations=max(0, args.close_iterations),
        palette=palette,
        ink_threshold=max(0, args.ink_threshold),
        neatline_coverage=max(0.0, min(1.0, args.neatline_coverage)),
        core_erode_iterations=max(0, args.core_erode_iterations),
        extension_gap=max(0, args.extension_gap),
        extension_min_area=max(1, args.extension_min_area),
        extension_max_area_ratio=max(0.0, args.extension_max_area_ratio),
        extension_max_fill_ratio=max(0.0, min(1.0, args.extension_max_fill_ratio)),
        extension_max_thickness=max(1, args.extension_max_thickness),
        extension_max_overhang_north=overhang_north,
        extension_max_overhang_south=overhang_south,
        extension_max_overhang_west=overhang_west,
        extension_max_overhang_east=overhang_east,
        island_east_band_width=max(1, args.island_east_band_width),
        island_east_min_area=max(1, args.island_east_min_area),
        island_east_min_span=max(1, args.island_east_min_span),
    )

    write_mask_png(final_mask, output_path)
    if args.full_mask_output:
        write_mask_png(final_mask, args.full_mask_output)
        print(f"Wrote full debug mask to {args.full_mask_output}")

    if args.debug_prefix:
        write_debug_stages(args.debug_prefix, stages)
        print(f"Wrote stage debug artifacts with prefix {args.debug_prefix}")

    corners = corner_points(final_mask)
    if args.corners_json:
        payload = {
            key: {"row": row, "col": col}
            for key, (row, col) in corners.items()
        }
        args.corners_json.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    geometry_source = mask_to_source_geometry(final_mask, transform)
    geometry_wgs84 = transform_geom(
        source_crs,
        "EPSG:4326",
        geometry_source,
        precision=7,
    )
    heuristics = {
        "edge_width": int(max(1, args.edge_width)),
        "tolerance": int(max(0, args.tolerance)),
        "ink_threshold": int(max(0, args.ink_threshold)),
        "neatline_coverage": float(max(0.0, min(1.0, args.neatline_coverage))),
        "core_erode_iterations": int(max(0, args.core_erode_iterations)),
        "extension_gap": int(max(0, args.extension_gap)),
        "extension_min_area": int(max(1, args.extension_min_area)),
        "extension_max_area_ratio": float(max(0.0, args.extension_max_area_ratio)),
        "extension_max_fill_ratio": float(
            max(0.0, min(1.0, args.extension_max_fill_ratio))
        ),
        "extension_max_thickness": int(max(1, args.extension_max_thickness)),
        "extension_max_overhang": int(max_overhang),
        "extension_max_overhang_north": int(overhang_north),
        "extension_max_overhang_south": int(overhang_south),
        "extension_max_overhang_west": int(overhang_west),
        "extension_max_overhang_east": int(overhang_east),
        "island_east_band_width": int(max(1, args.island_east_band_width)),
        "island_east_min_area": int(max(1, args.island_east_min_area)),
        "island_east_min_span": int(max(1, args.island_east_min_span)),
        "close_iterations": int(max(0, args.close_iterations)),
        "max_size": int(max(1, args.max_size)),
    }
    feature = build_geojson_feature(
        chart_name,
        geometry_wgs84,
        source_path=args.input,
        mask_shape=final_mask.shape,
        heuristics=heuristics,
        corners=corners,
    )
    write_geojson(feature, geojson_path)

    print(f"Wrote final mask to {output_path}")
    print(f"Wrote coverage GeoJSON to {geojson_path}")
    print(f"Geometry type: {geometry_wgs84.get('type')}")
    print(f"Corners (row, col): {corners}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
