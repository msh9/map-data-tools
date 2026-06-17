"""Command entrypoint for FAA VFR fetch utility."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from faa_vfr_fetch import fetch_vfr


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FAA VFR chart fetch utility.")
    subparsers = parser.add_subparsers(dest="command")

    fetch_parser = subparsers.add_parser(
        "fetch",
        help="Download and extract FAA sectional and TAC chart packages.",
    )
    fetch_parser.add_argument(
        "--cycle",
        default="auto",
        help="FAA visual cycle in MM-DD-YYYY format, or 'auto' for latest published.",
    )
    fetch_parser.add_argument(
        "--chart-type",
        dest="chart_types",
        action="append",
        choices=list(fetch_vfr.CHART_TYPES),
        help="Chart type to download. Repeatable; defaults to sectional and tac.",
    )
    fetch_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where chart folders and archives are written.",
    )
    fetch_parser.add_argument(
        "--force",
        action="store_true",
        help="Redownload archives even if local zip files already exist.",
    )
    fetch_parser.add_argument(
        "--no-extract",
        action="store_true",
        help="Download zip packages only; do not extract archive contents.",
    )
    fetch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve cycle and package list without downloading files.",
    )
    fetch_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=60,
        help="HTTP timeout for each request in seconds (default: 60).",
    )
    fetch_parser.set_defaults(func=run_fetch)

    return parser


def run_fetch(args: argparse.Namespace) -> int:
    try:
        summary = fetch_vfr.fetch_vfr_packages(
            output_dir=args.output_dir,
            cycle=args.cycle,
            chart_types=args.chart_types,
            skip_existing=not args.force,
            extract=not args.no_extract,
            timeout_seconds=args.timeout_seconds,
            dry_run=args.dry_run,
        )
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Cycle: {summary.cycle}")
    print(
        f"Fetched {summary.package_count} package(s): "
        f"{summary.downloaded_count} downloaded, {summary.skipped_count} skipped."
    )
    print(f"Manifest: {summary.manifest_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args, remaining = parser.parse_known_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    if remaining:
        parser.error(f"unrecognized arguments: {' '.join(remaining)}")
    return args.func(args)
