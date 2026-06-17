"""CLI entry point for dem-2-slope."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from osgeo import gdal

from dem_2_slope.download import download_dem
from dem_2_slope.mosaic import build_vrt
from dem_2_slope.slope import process_tile

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dem-2-slope",
        description=(
            "Convert USGS 3DEP DEM GeoTIFFs to slope-shaded RGBA COGs "
            "for the raster-tilemaker pipeline."
        ),
    )
    parser.add_argument(
        "--url-list",
        type=Path,
        required=True,
        help="Path to text file with one DEM URL (or local path) per line.",
    )
    parser.add_argument(
        "--slope-threshold",
        type=float,
        required=True,
        help="Slope threshold in degrees; slopes below this value become transparent.",
    )
    parser.add_argument(
        "--clip-regions",
        type=Path,
        required=True,
        help="Path to mountainous regions GeoJSON for clipping.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for processed COGs and final VRT.",
    )
    parser.add_argument(
        "--vrt-name",
        type=str,
        default="slope-mosaic.vrt",
        help="Filename for the output VRT mosaic (default: slope-mosaic.vrt).",
    )
    parser.add_argument(
        "--smooth-kernel",
        type=int,
        default=None,
        help=(
            "Size of the NxN moving average smoothing kernel. "
            "At ~30m/pixel, 8 covers ~240m. Omit for no smoothing."
        ),
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        default=False,
        help=(
            "Stream DEM tiles directly from S3 via GDAL /vsicurl/ and keep "
            "intermediates in RAM (/vsimem/). Avoids downloading raw tiles "
            "to disk. Falls back to the default download-then-process "
            "approach when not set."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns 0 on success, 1 on error."""
    parser = build_parser()
    args = parser.parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

    try:
        gdal.UseExceptions()

        output_dir: Path = args.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        # Read URL list
        url_list_path: Path = args.url_list
        urls = [
            line.strip()
            for line in url_list_path.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        if not urls:
            logger.warning("URL list is empty, nothing to process.")
            return 0

        processed_cogs: list[Path] = []
        use_stream = args.stream

        for url in urls:
            tile_name = Path(url).stem
            cog_path = output_dir / f"{tile_name}_slope.cog.tif"

            if use_stream:
                # Stream via /vsicurl/ + /vsimem/: no disk download
                process_tile(
                    input_path=url,
                    output_path=cog_path,
                    threshold=args.slope_threshold,
                    clip_regions_path=args.clip_regions,
                    stream=True,
                    smooth_kernel=args.smooth_kernel,
                )
            else:
                # Download-then-process (default)
                is_local = not url.startswith("http://") and not url.startswith("https://")
                if is_local:
                    raw_path = Path(url)
                else:
                    raw_path = output_dir / f"{tile_name}.tif"
                    download_dem(url, raw_path)

                try:
                    process_tile(
                        input_path=raw_path,
                        output_path=cog_path,
                        threshold=args.slope_threshold,
                        clip_regions_path=args.clip_regions,
                        smooth_kernel=args.smooth_kernel,
                    )
                finally:
                    if not is_local and raw_path.exists():
                        raw_path.unlink()
                        logger.info("Deleted raw DEM: %s", raw_path)

            processed_cogs.append(cog_path)

        # Build VRT over all processed COGs
        if processed_cogs:
            vrt_path = build_vrt(processed_cogs, output_dir, vrt_name=args.vrt_name)
            logger.info("Pipeline complete. VRT: %s", vrt_path)

        return 0

    except Exception:
        logger.exception("Pipeline failed")
        return 1


def cli() -> None:
    """Console-script entry point that propagates the exit code."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
