#!/usr/bin/env python3
"""Convert FAA sectional coverage bounds from DMS text to GeoJSON."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

HEADER_PATTERN = re.compile(r'"([^"]+)"')
DMS_PATTERN = re.compile(
    r"^(?P<degrees>\d+)[^\d]+(?P<minutes>\d+)[^A-Za-z]*(?P<hemisphere>[NSEW])$",
    re.IGNORECASE,
)

CORNER_ORDER = ("SW", "NW", "SE", "NE")
EPSILON = 1e-9


@dataclass(frozen=True)
class CoverageRow:
    """One chart row from the FAA coverage table."""

    chart: str
    source_fields: dict[str, str]
    corners: dict[str, tuple[float, float]]


def parse_dms_coordinate(value: str) -> float:
    """Convert a DMS coordinate like 32°00'N to decimal degrees."""
    normalized = (
        value.strip()
        .replace("’", "'")
        .replace("′", "'")
        .replace("`", "'")
        .upper()
    )

    match = DMS_PATTERN.match(normalized)
    if match is None:
        raise ValueError(f"Unsupported DMS coordinate format: {value!r}")

    degrees = int(match.group("degrees"))
    minutes = int(match.group("minutes"))
    hemisphere = match.group("hemisphere")

    decimal_value = degrees + (minutes / 60.0)
    if hemisphere in {"S", "W"}:
        decimal_value *= -1.0

    return decimal_value


def parse_header(header_line: str) -> list[str]:
    headers = HEADER_PATTERN.findall(header_line)
    if len(headers) != 9 or headers[0] != "Chart":
        raise ValueError("Unexpected FAA sectional coverage header format.")
    return headers


def parse_coverage_line(line: str, headers: list[str]) -> CoverageRow:
    tokens = line.split()
    if len(tokens) < 9:
        raise ValueError(f"Coverage row has too few fields: {line!r}")

    chart = " ".join(tokens[:-8]).strip()
    if not chart:
        raise ValueError(f"Coverage row is missing chart name: {line!r}")

    source_values = tokens[-8:]
    source_fields = {header: value for header, value in zip(headers[1:], source_values)}
    northings = source_values[:4]
    westings = source_values[4:]

    corners: dict[str, tuple[float, float]] = {}
    for index, corner in enumerate(CORNER_ORDER):
        latitude = parse_dms_coordinate(northings[index])
        longitude = parse_dms_coordinate(westings[index])
        corners[corner] = (longitude, latitude)

    return CoverageRow(chart=chart, source_fields=source_fields, corners=corners)


def read_coverage_rows(input_path: Path) -> list[CoverageRow]:
    lines = [line.strip() for line in input_path.read_text(encoding="utf-8").splitlines()]
    non_empty_lines = [line for line in lines if line]
    if len(non_empty_lines) < 2:
        raise ValueError("Coverage file must include a header and at least one row.")

    headers = parse_header(non_empty_lines[0])
    rows: list[CoverageRow] = []

    for index, line in enumerate(non_empty_lines[1:], start=2):
        try:
            rows.append(parse_coverage_line(line, headers))
        except ValueError as exc:
            raise ValueError(f"Invalid coverage row at line {index}: {exc}") from exc

    return rows


def unwrap_longitudes(vertices: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    iterator = iter(vertices)
    first = next(iterator)
    unwrapped = [first]
    previous_longitude = first[0]

    for longitude, latitude in iterator:
        candidates = (longitude - 360.0, longitude, longitude + 360.0)
        chosen_longitude = min(candidates, key=lambda item: abs(item - previous_longitude))
        unwrapped.append((chosen_longitude, latitude))
        previous_longitude = chosen_longitude

    return unwrapped


def needs_antimeridian_split(vertices: Iterable[tuple[float, float]]) -> int | None:
    longitudes = [vertex[0] for vertex in vertices]
    if max(longitudes) > 180.0 + EPSILON:
        return 180
    if min(longitudes) < -180.0 - EPSILON:
        return -180
    return None


def clip_polygon_vertical(
    vertices: list[tuple[float, float]],
    split_longitude: float,
    keep_leq: bool,
) -> list[tuple[float, float]]:
    """Clip polygon vertices against a vertical line using Sutherland-Hodgman."""

    def inside(point: tuple[float, float]) -> bool:
        if keep_leq:
            return point[0] <= split_longitude + EPSILON
        return point[0] >= split_longitude - EPSILON

    def intersect(
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> tuple[float, float]:
        start_longitude, start_latitude = start
        end_longitude, end_latitude = end

        longitude_delta = end_longitude - start_longitude
        if abs(longitude_delta) < EPSILON:
            return (split_longitude, start_latitude)

        fraction = (split_longitude - start_longitude) / longitude_delta
        fraction = max(0.0, min(1.0, fraction))
        latitude = start_latitude + (end_latitude - start_latitude) * fraction
        return (split_longitude, latitude)

    if not vertices:
        return []

    output: list[tuple[float, float]] = []
    previous = vertices[-1]

    for current in vertices:
        previous_inside = inside(previous)
        current_inside = inside(current)

        if current_inside:
            if not previous_inside:
                output.append(intersect(previous, current))
            output.append(current)
        elif previous_inside:
            output.append(intersect(previous, current))

        previous = current

    return output


def shift_longitudes(
    vertices: list[tuple[float, float]],
    shift: float,
) -> list[tuple[float, float]]:
    return [(longitude + shift, latitude) for longitude, latitude in vertices]


def dedupe_adjacent_vertices(
    vertices: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if not vertices:
        return []

    deduped = [vertices[0]]
    for vertex in vertices[1:]:
        if (
            abs(vertex[0] - deduped[-1][0]) > EPSILON
            or abs(vertex[1] - deduped[-1][1]) > EPSILON
        ):
            deduped.append(vertex)

    return deduped


def signed_area(vertices: list[tuple[float, float]]) -> float:
    area = 0.0
    total = len(vertices)
    for index, current in enumerate(vertices):
        nxt = vertices[(index + 1) % total]
        area += current[0] * nxt[1]
        area -= nxt[0] * current[1]
    return area / 2.0


def finalize_ring(vertices: list[tuple[float, float]]) -> list[list[float]]:
    normalized = dedupe_adjacent_vertices(vertices)
    if len(normalized) < 3:
        raise ValueError("Polygon ring requires at least three distinct vertices.")

    if signed_area(normalized) < 0.0:
        normalized.reverse()

    ring = [
        [round(longitude, 10), round(latitude, 10)]
        for longitude, latitude in normalized
    ]
    ring.append(ring[0])
    return ring


def build_geometry(corners: dict[str, tuple[float, float]]) -> dict[str, object]:
    vertices = [corners["SW"], corners["NW"], corners["NE"], corners["SE"]]
    unwrapped = unwrap_longitudes(vertices)
    split_longitude = needs_antimeridian_split(unwrapped)

    if split_longitude is None:
        return {"type": "Polygon", "coordinates": [finalize_ring(unwrapped)]}

    leq_side = clip_polygon_vertical(unwrapped, split_longitude, keep_leq=True)
    geq_side = clip_polygon_vertical(unwrapped, split_longitude, keep_leq=False)

    if split_longitude == 180:
        left_vertices = shift_longitudes(leq_side, 0.0)
        right_vertices = shift_longitudes(geq_side, -360.0)
    else:
        left_vertices = shift_longitudes(leq_side, 360.0)
        right_vertices = shift_longitudes(geq_side, 0.0)

    polygons: list[list[list[float]]] = []
    for polygon_vertices in (left_vertices, right_vertices):
        cleaned = dedupe_adjacent_vertices(polygon_vertices)
        if len(cleaned) >= 3:
            polygons.append(finalize_ring(cleaned))

    if not polygons:
        raise ValueError("Failed to construct polygon geometry after antimeridian split.")
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": [polygons[0]]}

    return {
        "type": "MultiPolygon",
        "coordinates": [[[coordinate for coordinate in polygon]] for polygon in polygons],
    }


def build_feature(row: CoverageRow) -> dict[str, object]:
    decimal_corners = {
        corner: {"longitude": lon, "latitude": lat}
        for corner, (lon, lat) in row.corners.items()
    }

    return {
        "type": "Feature",
        "properties": {
            "chart": row.chart,
            "source_fields": row.source_fields,
            "corner_decimal_degrees": decimal_corners,
        },
        "geometry": build_geometry(row.corners),
    }


def build_feature_collection(rows: list[CoverageRow]) -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "features": [build_feature(row) for row in rows],
    }


def chart_filename(chart: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", chart.strip().lower()).strip("-")
    if not slug:
        raise ValueError(f"Unable to create filename for chart name: {chart!r}")
    return f"{slug}.geojson"


def write_coverage_directory(
    features: list[dict[str, object]],
    coverage_dir: Path,
    indent: int,
) -> int:
    coverage_dir.mkdir(parents=True, exist_ok=True)
    seen_output_paths: set[Path] = set()

    for feature in features:
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("Feature is missing expected properties object.")

        chart_name = properties.get("chart")
        if not isinstance(chart_name, str):
            raise ValueError("Feature is missing expected chart property.")

        output_path = coverage_dir / chart_filename(chart_name)
        if output_path in seen_output_paths:
            raise ValueError(f"Duplicate output path for chart: {chart_name!r}")
        seen_output_paths.add(output_path)

        output_path.write_text(
            f"{json.dumps(feature, indent=indent, ensure_ascii=False)}\n",
            encoding="utf-8",
        )

    return len(features)


def convert_file(input_path: Path, output_path: Path, indent: int) -> int:
    rows = read_coverage_rows(input_path)
    feature_collection = build_feature_collection(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        f"{json.dumps(feature_collection, indent=indent, ensure_ascii=False)}\n",
        encoding="utf-8",
    )
    return len(rows)


def convert_to_coverage_directory(
    input_path: Path,
    coverage_dir: Path,
    indent: int,
) -> int:
    rows = read_coverage_rows(input_path)
    feature_collection = build_feature_collection(rows)
    return write_coverage_directory(feature_collection["features"], coverage_dir, indent)


def build_arg_parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[2]
    default_input = repo_root / "third-party-static-data" / "faa-sectional-coverage.txt"
    default_output = (
        repo_root / "third-party-static-data" / "faa-sectional-coverage.geojson"
    )

    parser = argparse.ArgumentParser(
        description=(
            "Convert FAA sectional coverage bounds from DMS text to a GeoJSON "
            "FeatureCollection."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=default_input,
        help=f"Input FAA text file (default: {default_input})",
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help=f"Output GeoJSON file (default: {default_output})",
    )
    output_group.add_argument(
        "--coverage-dir",
        type=Path,
        help=(
            "Output directory for one feature GeoJSON file per chart. "
            "Files are named from each chart property."
        ),
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indent width (default: 2)",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.coverage_dir is not None:
        row_count = convert_to_coverage_directory(
            args.input,
            args.coverage_dir,
            args.indent,
        )
        print(f"Wrote {row_count} chart features to directory {args.coverage_dir}")
        return 0

    row_count = convert_file(args.input, args.output, args.indent)
    print(f"Wrote {row_count} chart features to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
