"""FAA Digital Obstacle File (DOF) parser — CLI orchestration."""

from __future__ import annotations

import argparse
import gzip
import sys
from contextlib import ExitStack
from pathlib import Path

from dof2geojson.dof import (
    DOFObstacleRecord,
    ParseSummary,
    decode_horizontal_accuracy,
    decode_lighting,
    decode_mark_indicator,
    decode_verification_status,
    decode_vertical_accuracy,
    list_dof_state_files,
    normalize_state_filter,
    parse_dof_directory,
    parse_dof_file,
    parse_dof_line,
)
from tilemaker_shared.geojson import (
    COORDINATE_SYSTEM_ESRI_102009,
    COORDINATE_SYSTEM_WGS84,
    GeoJSONFeatureCollectionWriter,
    build_coordinate_transform,
    build_esri_102009_coordinate_transform,
    feature_collection_crs_name,
    normalized_record_to_geojson_feature,
)

__all__ = [
    "DOFObstacleRecord",
    "ParseSummary",
    "decode_horizontal_accuracy",
    "decode_lighting",
    "decode_mark_indicator",
    "decode_verification_status",
    "decode_vertical_accuracy",
    "list_dof_state_files",
    "normalize_state_filter",
    "parse_dof_directory",
    "parse_dof_file",
    "parse_dof_line",
    "COORDINATE_SYSTEM_ESRI_102009",
    "COORDINATE_SYSTEM_WGS84",
    "GeoJSONFeatureCollectionWriter",
    "build_coordinate_transform",
    "build_esri_102009_coordinate_transform",
    "feature_collection_crs_name",
    "normalized_record_to_geojson_feature",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse FAA DOF records.")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--input",
        type=Path,
        help="Path to a single FAA DOF-format input file.",
    )
    input_group.add_argument(
        "--input-dir",
        type=Path,
        help="Path to directory of FAA archive state files (for example 49-UT.Dat).",
    )
    parser.add_argument(
        "--geojson-out",
        type=Path,
        required=True,
        help="Path to output GeoJSON FeatureCollection (gzip-compressed).",
    )
    parser.add_argument(
        "--state",
        action="append",
        default=[],
        help="Optional state filter (repeatable, ex: --state UT --state CO).",
    )
    parser.add_argument(
        "--coordinate-system",
        choices=[COORDINATE_SYSTEM_WGS84, COORDINATE_SYSTEM_ESRI_102009],
        default=COORDINATE_SYSTEM_WGS84,
        help=("Coordinate system for output geometry coordinates (default: wgs84)."),
    )
    parser.add_argument(
        "--include-amsl-z",
        action="store_true",
        help="Include AMSL meters as the third coordinate element.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state_filter = normalize_state_filter(args.state)
    coordinate_transform = build_coordinate_transform(args.coordinate_system)
    crs_name = feature_collection_crs_name(args.coordinate_system)

    args.geojson_out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ExitStack() as stack:
            geojson_file = stack.enter_context(
                gzip.open(args.geojson_out, mode="wt", encoding="utf-8")
            )
            geojson_writer = GeoJSONFeatureCollectionWriter(geojson_file, crs_name=crs_name)
            stack.callback(geojson_writer.close)

            def write_outputs(record: DOFObstacleRecord) -> None:
                normalized = record.to_normalized_dict()
                geojson_writer.write_feature(
                    normalized_record_to_geojson_feature(
                        normalized,
                        coordinate_transform=coordinate_transform,
                        include_amsl_z=args.include_amsl_z,
                    )
                )

            if args.input_dir is not None:
                summary = parse_dof_directory(
                    input_dir=args.input_dir,
                    state_filter=state_filter,
                    error_stream=sys.stderr,
                    record_handler=write_outputs,
                )
            else:
                summary = parse_dof_file(
                    input_path=args.input,
                    state_filter=state_filter,
                    error_stream=sys.stderr,
                    record_handler=write_outputs,
                )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Processed {summary.file_count} files. Wrote {summary.parsed_count} records to "
        f"{args.geojson_out} (gzip). "
        f"Skipped {summary.skipped_by_state_count} by state filter. "
        f"Encountered {summary.error_count} parse errors."
    )
    return 0
