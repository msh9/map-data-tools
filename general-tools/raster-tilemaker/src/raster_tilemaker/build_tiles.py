from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Sequence

from raster_tilemaker import tiler
from raster_tilemaker.config import DEFAULT_RESOLUTIONS
from raster_tilemaker.grid import validate_resolutions
from raster_tilemaker.logging_config import configure_logging
from raster_tilemaker.pipeline import build_mosaic_output

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build tiles + tile config from a GDAL VRT input.")
    parser.add_argument(
        "--input-vrt",
        type=Path,
        required=True,
        help="Path to the input GDAL VRT file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for tiles + tile config.",
    )
    parser.add_argument(
        "--tile-size",
        type=int,
        default=tiler.DEFAULT_TILE_SIZE,
        choices=(tiler.DEFAULT_TILE_SIZE,),
        help="Tile size in pixels (locked to 512 for M1).",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=tiler.DEFAULT_QUALITY,
        help="Image quality (0-100).",
    )
    parser.add_argument(
        "--format",
        choices=("webp", "avif", "png"),
        default=tiler.DEFAULT_FORMAT,
        help="Tile format output.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to JSON config file (resolutions list).",
    )
    parser.add_argument(
        "--resolution",
        action="append",
        dest="resolutions",
        type=float,
        help="Tile resolution in CRS units per pixel (repeatable).",
    )
    parser.add_argument(
        "--output-kind",
        choices=("zxy", "pmtiles"),
        default="zxy",
        help="Output mode: directory tiles (zxy) or a PMTiles archive.",
    )
    parser.add_argument(
        "--pmtiles-file",
        type=Path,
        default=Path("tiles.pmtiles"),
        help="PMTiles output filename (relative to --output-dir by default).",
    )
    parser.add_argument(
        "--render-workers",
        type=int,
        default=0,
        dest="render_workers",
        help=(
            "Worker processes for parallel tile render+encode when writing PMTiles "
            "(0 = auto-detect from CPU count; 1 = serial)."
        ),
    )
    parser.add_argument(
        "--log-format",
        choices=("text", "json"),
        default="text",
        help="Log output format: human-readable text or structured JSON lines.",
    )
    parser.add_argument(
        "--log-level",
        choices=("debug", "info", "warning", "error"),
        default="info",
        help="Minimum log level to emit.",
    )
    return parser


def load_resolutions_from_config(path: Path) -> list[float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    resolutions = payload.get("resolutions")
    if resolutions is None:
        raise ValueError("Config file is missing required 'resolutions' list.")
    if not isinstance(resolutions, list):
        raise ValueError("Config file 'resolutions' must be a list of numbers.")
    return validate_resolutions(resolutions)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_format, args.log_level)
    try:
        if args.config and args.resolutions:
            raise ValueError("Use either --config or --resolution, not both.")
        if args.config:
            if not args.config.exists():
                raise FileNotFoundError(f"Config file not found: {args.config}")
            resolutions = load_resolutions_from_config(args.config)
            resolution_source = f"config file: {args.config}"
        elif args.resolutions:
            resolutions = validate_resolutions(args.resolutions)
            resolution_source = "command-line --resolution flags"
        else:
            resolutions = validate_resolutions(DEFAULT_RESOLUTIONS)
            resolution_source = "built-in defaults"
        logger.info(
            "Starting build-tiles",
            extra={
                "vrt_path": str(args.input_vrt),
                "output_dir": str(args.output_dir),
                "output_kind": args.output_kind,
                "tile_format": args.format,
                "quality": args.quality,
                "n_resolutions": len(resolutions),
                "resolution_source": resolution_source,
            },
        )
        build_mosaic_output(
            args.input_vrt,
            args.output_dir,
            resolutions,
            tile_size=args.tile_size,
            quality=args.quality,
            tile_format=args.format,
            output_kind=args.output_kind,
            pmtiles_file=args.pmtiles_file,
            render_workers=args.render_workers if args.render_workers > 0 else None,
        )
    except Exception as exc:  # pragma: no cover - CLI surface
        logger.error("Error: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
