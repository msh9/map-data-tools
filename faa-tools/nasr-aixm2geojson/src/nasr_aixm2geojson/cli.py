"""Command entrypoint for nasr-aixm2geojson."""

from __future__ import annotations

import argparse
from typing import Sequence

from nasr_aixm2geojson import parse_navaids


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NASR AIXM to GeoJSON CLI.")
    subparsers = parser.add_subparsers(dest="command")

    parse_navaids_parser = subparsers.add_parser(
        "parse-navaids", help="Parse NASR AIXM navaid records into gzip-compressed GeoJSON."
    )
    parse_navaids_parser.set_defaults(func=parse_navaids.main)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args, remaining = parser.parse_known_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(remaining)
