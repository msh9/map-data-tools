"""Command entrypoint for raster-tilemaker."""

from __future__ import annotations

import argparse
from typing import Sequence

from raster_tilemaker import build_tiles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Raster tilemaker CLI.")
    subparsers = parser.add_subparsers(dest="command")

    build_parser = subparsers.add_parser("build-tiles", help="Build tiles + tile config.")
    build_parser.set_defaults(func=build_tiles.main)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args, remaining = parser.parse_known_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(remaining)
