from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from _process_sectionals.constants import (
    CHART_TYPES,
    CLIPPED_OUTPUT_MODE_JXL_LOSSLESS,
    CLIPPED_OUTPUT_MODE_ZSTD,
    DEFAULT_CLIPPED_OUTPUT_MODE,
    DEFAULT_MOSAIC_FILE_MATCH_TOKEN,
    DEFAULT_THREADS,
    CHART_TYPE_SECTIONAL,
)
from _process_sectionals.mosaic import build_region_mosaics
from _process_sectionals.pipeline import run


def parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("Thread count must be >= 1.")
    return parsed


def add_preprocess_arguments(parser: argparse.ArgumentParser) -> None:
    chart_group = parser.add_mutually_exclusive_group(required=True)
    chart_group.add_argument(
        "--chart",
        action="append",
        dest="charts",
        help="Chart folder name to process (repeatable), for example Denver or Denver_TAC.",
    )
    chart_group.add_argument(
        "--all-charts",
        action="store_true",
        help="Process all discovered charts under --raw-charts-dir for selected --chart-type values.",
    )
    parser.add_argument(
        "--chart-type",
        action="append",
        choices=CHART_TYPES,
        dest="chart_types",
        help=(
            "Chart type to process (repeatable). "
            "When omitted, all chart types are processed: sectional, tac, fly."
        ),
    )
    parser.add_argument(
        "--raw-charts-dir",
        type=Path,
        required=True,
        help="Directory containing raw chart folders.",
    )
    parser.add_argument(
        "--sectional-coverage-dir",
        type=Path,
        required=True,
        help="Directory containing per-chart sectional coverage GeoJSON files.",
    )
    parser.add_argument(
        "--tac-fly-coverage-dir",
        type=Path,
        required=True,
        help="Directory containing per-chart TAC/FLY coverage GeoJSON files.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="Root output directory for processed chart COGs.",
    )
    parser.add_argument(
        "--clipped-output-mode",
        choices=(CLIPPED_OUTPUT_MODE_ZSTD, CLIPPED_OUTPUT_MODE_JXL_LOSSLESS),
        default=DEFAULT_CLIPPED_OUTPUT_MODE,
        help=(
            "Compression mode for clipped output COG. "
            "'zstd' uses ZSTD/PREDICTOR=2/LEVEL=20, "
            "'jxl-lossless' uses JXL_LOSSLESS=YES/JXL_EFFORT=7."
        ),
    )
    parser.add_argument(
        "--threads",
        type=parse_positive_int,
        default=DEFAULT_THREADS,
        help=(
            "Number of threads used for GDAL reproject and COG write stages "
            f"(default: {DEFAULT_THREADS})."
        ),
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue processing remaining source files after an error.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Emit stage-by-stage status logs during chart processing.",
    )


def add_build_region_mosaics_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mapping-json",
        type=Path,
        required=True,
        help="Mapping JSON path.",
    )
    parser.add_argument(
        "--processed-root",
        type=Path,
        required=True,
        help="Processed chart root directory.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for generated VRT files.",
    )
    parser.add_argument(
        "--file-match-token",
        default=DEFAULT_MOSAIC_FILE_MATCH_TOKEN,
        help=(
            "Token used to match input files in chart directories "
            f"(default: {DEFAULT_MOSAIC_FILE_MATCH_TOKEN!r})."
        ),
    )
    parser.add_argument(
        "--chart-type",
        choices=CHART_TYPES,
        default=CHART_TYPE_SECTIONAL,
        help=(
            "Chart type to mosaic. "
            "sectional uses mapping.sectional; tac/fly use mapping.terminal_area."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print gdal commands without executing them.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FAA raster chart preprocessing utilities.")
    subparsers = parser.add_subparsers(dest="command")

    preprocess_parser = subparsers.add_parser(
        "preprocess",
        help="Prepare chart COG outputs from FAA raw GeoTIFF files.",
    )
    add_preprocess_arguments(preprocess_parser)

    mosaics_parser = subparsers.add_parser(
        "build-region-mosaics",
        help="Build regional VRT mosaics from processed chart COG outputs.",
    )
    add_build_region_mosaics_arguments(mosaics_parser)
    return parser


def normalize_command_argv(argv: Sequence[str] | None) -> list[str]:
    normalized = list(sys.argv[1:] if argv is None else argv)
    if not normalized:
        return normalized
    if normalized[0] in ("preprocess", "build-region-mosaics", "-h", "--help"):
        return normalized
    return ["preprocess", *normalized]


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    normalized_argv = normalize_command_argv(argv)
    args = parser.parse_args(normalized_argv)

    if args.command is None:
        parser.print_help()
        return 2

    if args.command == "build-region-mosaics":
        try:
            build_region_mosaics(
                mapping_json=args.mapping_json,
                processed_root=args.processed_root,
                output_dir=args.output_dir,
                file_match_token=args.file_match_token,
                chart_type=args.chart_type,
                dry_run=args.dry_run,
            )
        except Exception as exc:  # pragma: no cover - CLI surface
            print(f"Error: {exc}")
            return 1
        return 0

    chart_types = args.chart_types if args.chart_types else CHART_TYPES
    continue_on_error = args.continue_on_error or args.all_charts
    try:
        result = run(
            raw_charts_dir=args.raw_charts_dir,
            sectional_coverage_dir=args.sectional_coverage_dir,
            tac_fly_coverage_dir=args.tac_fly_coverage_dir,
            output_root=args.output_root,
            requested_charts=args.charts,
            all_charts=args.all_charts,
            chart_types=chart_types,
            clipped_output_mode=args.clipped_output_mode,
            threads=args.threads,
            verbose=args.verbose,
            continue_on_error=continue_on_error,
        )
    except Exception as exc:  # pragma: no cover - CLI surface
        print(f"Error: {exc}")
        return 1

    if result.failed_messages:
        return 1
    return 0
