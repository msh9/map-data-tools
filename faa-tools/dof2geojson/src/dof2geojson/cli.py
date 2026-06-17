"""Command entrypoint for dof2geojson."""

from __future__ import annotations

import argparse
from typing import Sequence

from dof2geojson import parse_dof


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DOF2GeoJSON CLI.")
    subparsers = parser.add_subparsers(dest="command")

    parse_dof_parser = subparsers.add_parser(
        "parse-dof", help="Parse FAA DOF records into gzip-compressed GeoJSON."
    )
    parse_dof_parser.set_defaults(func=parse_dof.main)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args, remaining = parser.parse_known_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(remaining)
