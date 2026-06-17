"""NASR AIXM navaid parser — CLI orchestration."""

from __future__ import annotations

import argparse
import gzip
import sys
from contextlib import ExitStack
from pathlib import Path

from nasr_aixm2geojson.aixm import parse_aixm_file
from tilemaker_shared.geojson import (
    COORDINATE_SYSTEM_ESRI_102009,
    COORDINATE_SYSTEM_WGS84,
    GeoJSONFeatureCollectionWriter,
    build_coordinate_transform,
    feature_collection_crs_name,
    normalized_record_to_geojson_feature,
)
from nasr_aixm2geojson.navaid import NavaidRecord


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse NASR AIXM navaid records.")
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to the NASR AIXM navaid XML file (NAV_AIXM.xml).",
    )
    parser.add_argument(
        "--geojson-out",
        type=Path,
        required=True,
        help="Path to output GeoJSON FeatureCollection (gzip-compressed).",
    )
    parser.add_argument(
        "--coordinate-system",
        choices=[COORDINATE_SYSTEM_WGS84, COORDINATE_SYSTEM_ESRI_102009],
        default=COORDINATE_SYSTEM_WGS84,
        help="Coordinate system for output geometry coordinates (default: wgs84).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    coordinate_transform = build_coordinate_transform(args.coordinate_system)
    crs_name = feature_collection_crs_name(args.coordinate_system)

    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        return 1

    args.geojson_out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ExitStack() as stack:
            geojson_file = stack.enter_context(
                gzip.open(args.geojson_out, mode="wt", encoding="utf-8")
            )
            geojson_writer = GeoJSONFeatureCollectionWriter(geojson_file, crs_name=crs_name)
            stack.callback(geojson_writer.close)

            def write_outputs(record: NavaidRecord) -> None:
                normalized = record.to_normalized_dict()
                geojson_writer.write_feature(
                    normalized_record_to_geojson_feature(
                        normalized,
                        coordinate_transform=coordinate_transform,
                    )
                )

            summary, effective_date = parse_aixm_file(
                input_path=args.input,
                error_stream=sys.stderr,
                record_handler=write_outputs,
            )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    effective_str = f" Effective date: {effective_date}." if effective_date else ""
    print(
        f"Wrote {summary.navaid_count} navaids to {args.geojson_out} (gzip). "
        f"Resolved {summary.rcc_count} frequency records. "
        f"Encountered {summary.error_count} parse errors.{effective_str}"
    )
    return 0
