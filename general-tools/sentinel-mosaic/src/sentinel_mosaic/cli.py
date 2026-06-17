"""CLI entry point for sentinel-mosaic."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import logging
import os
import sys
import time
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from osgeo import gdal


from sentinel_mosaic.composite import (
    build_per_region_vrt,
    build_top_level_vrt,
    finalize_output_tile,
    finalize_single_cog,
)
from sentinel_mosaic.logging_setup import configure_logging
from sentinel_mosaic.process import _resolve_gdal_path, process_bands, process_tile
from sentinel_mosaic.search import (
    STAC_URL,
    MosaicTile,
    load_mosaic_tiles,
    load_region_geometries,
    search_mosaic_tiles,
)

logger = logging.getLogger(__name__)

PIXEL_SIZE_M = 10.0


def _configure_gdal(workers: int = 1) -> None:
    """Install GDAL config options for resilient cloud reads."""
    gdal.UseExceptions()
    gdal.SetConfigOption(
        "GDAL_CACHEMAX",
        os.getenv("SENTINEL_MOSAIC_GDAL_CACHEMAX", "512"),
    )
    gdal.SetConfigOption(
        "GDAL_NUM_THREADS",
        os.getenv("SENTINEL_MOSAIC_GDAL_NUM_THREADS", str(max(1, workers))),
    )
    # Bound HTTP latency and let GDAL retry transient failures from /vsis3 and
    # /vsicurl rather than aborting on the first network blip.
    gdal.SetConfigOption("GDAL_HTTP_TIMEOUT", "60")
    gdal.SetConfigOption("GDAL_HTTP_CONNECTTIMEOUT", "15")
    gdal.SetConfigOption("GDAL_HTTP_MAX_RETRY", "5")
    gdal.SetConfigOption("CPL_VSIL_CURL_RETRY_DELAY", "2")
    logger.info("GDAL config: %s", gdal.GetConfigOptions())

def _positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError(f"{value!r} is not a positive integer")
    return n


def _add_mosaic_subparser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser(
        "mosaic",
        help=(
            "Build true-color Sentinel-2 quarterly mosaic COGs from CDSE for "
            "the raster-tilemaker pipeline."
        ),
    )
    p.add_argument("--clip-regions", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument(
        "--scratch-dir",
        type=Path,
        default=None,
        help=(
            "Working directory for temporary tile files (heavy write traffic — "
            "point at local SSD, not a network mount). If omitted, a per-run "
            "temp dir is created and removed at exit; pass an explicit path to "
            "enable resume across runs."
        ),
    )
    p.add_argument(
        "--quarter",
        action="append",
        required=True,
        help="Quarter to process as YYYY-Qn (repeatable, e.g. 2024-Q3).",
    )
    p.add_argument("--stac-url", type=str, default=STAC_URL)
    p.add_argument(
        "--vrt-name",
        type=str,
        default="sentinel-mosaic.vrt",
        help="Base VRT filename. Each quarter is prefixed (e.g. 2024-Q3-sentinel-mosaic.vrt).",
    )
    p.add_argument(
        "--workers",
        type=_positive_int,
        default=1,
        help=(
            "Number of tiles to fetch+tone-map concurrently. Default 1 = serial. "
            "Set to 2 on a 2-vCPU host to overlap CDSE band fetches with tile writes."
        ),
    )
    p.add_argument("--verbose", action="store_true", default=False)
    p.add_argument(
        "--log-format",
        choices=("plain", "json"),
        default="plain",
        help="Log output format. Use 'json' for cloud log ingestion.",
    )
    scene_group = p.add_mutually_exclusive_group()
    scene_group.add_argument(
        "--save-scenes",
        type=Path,
        default=None,
        metavar="PATH",
        help=("Write STAC scene search results to a JSON file and exit without fetching imagery."),
    )
    scene_group.add_argument(
        "--load-scenes",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Load scene search results from a JSON file saved by --save-scenes, "
            "skipping the STAC API query."
        ),
    )


def _add_process_bands_subparser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser(
        "process-bands",
        help="Process a single set of Sentinel-2 band files into a true-color COG.",
    )
    p.add_argument(
        "--red",
        type=str,
        required=True,
        metavar="PATH",
        help="Red (B04) band — local path, s3://, or https:// URL.",
    )
    p.add_argument(
        "--green",
        type=str,
        required=True,
        metavar="PATH",
        help="Green (B03) band — local path, s3://, or https:// URL.",
    )
    p.add_argument(
        "--blue",
        type=str,
        required=True,
        metavar="PATH",
        help="Blue (B02) band — local path, s3://, or https:// URL.",
    )
    p.add_argument(
        "--output",
        type=str,
        required=True,
        metavar="PATH",
        help="Output COG path.",
    )
    p.add_argument(
        "--pixel-size",
        type=float,
        default=PIXEL_SIZE_M,
        metavar="METERS",
        help=f"Output pixel size in metres (default: {PIXEL_SIZE_M}).",
    )
    p.add_argument("--verbose", action="store_true", default=False)
    p.add_argument(
        "--log-format",
        choices=("plain", "json"),
        default="plain",
        help="Log output format. Use 'json' for cloud log ingestion.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sentinel-mosaic",
        description="Build Sentinel-2 true-color COG mosaics.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True
    _add_mosaic_subparser(sub)
    _add_process_bands_subparser(sub)
    return parser


def _process_region_quarter(
    region_name: str,
    region_geometry: dict,
    quarter: str,
    args: argparse.Namespace,
    *,
    preloaded_tiles: list[MosaicTile] | None = None,
) -> Path | None:
    if preloaded_tiles is not None:
        tiles = [t for t in preloaded_tiles if t.quarter == quarter]
    else:
        tiles = search_mosaic_tiles(
            region_geometry=region_geometry,
            quarter=quarter,
            stac_url=args.stac_url,
        )
    if not tiles:
        logger.warning("No tiles for region '%s' quarter %s", region_name, quarter)
        return None

    tile_output_dir = args.output_dir / f"{region_name}_{quarter}"
    tile_output_dir.mkdir(parents=True, exist_ok=True)

    per_region_vrt = args.output_dir / f"{region_name}_{quarter}.vrt"
    if per_region_vrt.exists():
        logger.info(
            "Skipping %s %s — per-region VRT already exists at %s",
            region_name,
            quarter,
            per_region_vrt,
        )
        return per_region_vrt

    # Resume: skip tiles whose output COG already exists.
    pending_tiles = [
        (i, tile)
        for i, tile in enumerate(tiles)
        if not (tile_output_dir / f"{tile.tile_id}.cog.tif").exists()
    ]
    already_done = len(tiles) - len(pending_tiles)
    if already_done:
        logger.info(
            "Resume: %d/%d tile(s) already finalized for %s %s",
            already_done,
            len(tiles),
            region_name,
            quarter,
        )

    skipped: list[str] = []
    workers = max(1, getattr(args, "workers", 1))

    # Bounded sliding window: at most ``workers`` process_tile futures in flight
    # at a time. Draining in submission order keeps the VRT source ordering
    # deterministic regardless of worker count.
    with ThreadPoolExecutor(max_workers=workers) as executor:
        in_flight: deque[tuple[int, MosaicTile, str, Future[str]]] = deque()
        next_to_submit = 0

        def submit_until_full() -> None:
            nonlocal next_to_submit
            while len(in_flight) < workers and next_to_submit < len(pending_tiles):
                i, tile = pending_tiles[next_to_submit]
                next_to_submit += 1
                tag = uuid.uuid4().hex[:8]
                vsimem_path = f"/vsimem/tile_{tag}.tif"
                logger.info(
                    "Region %s %s: tile %d/%d (%s)",
                    region_name,
                    quarter,
                    i + 1,
                    len(tiles),
                    tile.tile_id,
                )
                fut = executor.submit(process_tile, tile, vsimem_path)
                in_flight.append((i, tile, vsimem_path, fut))

        submit_until_full()
        while in_flight:
            _i, tile, vsimem_path, fut = in_flight.popleft()
            try:
                fut.result()
                finalize_output_tile(
                    vsimem_path,
                    tile.tile_id,
                    args.clip_regions,
                    region_name,
                    tile_output_dir,
                    PIXEL_SIZE_M,
                )
            except Exception:
                # Single-tile failure must not abort the region — neighboring
                # tiles cover the gap; the missing output file acts as the
                # resume signal on the next run.
                logger.warning(
                    "Skipping tile %s for region %s %s",
                    tile.tile_id,
                    region_name,
                    quarter,
                    exc_info=True,
                )
                skipped.append(tile.tile_id)
            finally:
                with contextlib.suppress(RuntimeError):
                    gdal.Unlink(vsimem_path)
            submit_until_full()

    if skipped:
        logger.warning(
            "Region %s %s: %d tile(s) skipped: %s",
            region_name,
            quarter,
            len(skipped),
            ", ".join(skipped),
        )

    # Collect all finalized tile paths in STAC order (pre-existing + newly written).
    output_tile_paths = [
        tile_output_dir / f"{tile.tile_id}.cog.tif"
        for tile in tiles
        if (tile_output_dir / f"{tile.tile_id}.cog.tif").exists()
    ]

    if not output_tile_paths:
        logger.warning("No tiles produced for region '%s' quarter %s", region_name, quarter)
        return None

    return build_per_region_vrt(output_tile_paths, args.output_dir, region_name, quarter)


def _write_quarter_summary(
    output_dir: Path,
    quarter: str,
    results: list[dict[str, object]],
    elapsed_seconds: float,
) -> None:
    summary = {
        "quarter": quarter,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "regions_attempted": len(results),
        "regions_succeeded": sum(1 for r in results if r["status"] == "succeeded"),
        "regions_failed": sum(1 for r in results if r["status"] == "failed"),
        "regions_skipped_no_tiles": sum(1 for r in results if r["status"] == "skipped_no_tiles"),
        "regions": results,
    }
    summary_path = output_dir / f"{quarter}-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    logger.info("Wrote summary: %s", summary_path)


def _run_mosaic(args: argparse.Namespace) -> int:
    try:
        _configure_gdal(args.workers)

        args.output_dir.mkdir(parents=True, exist_ok=True)

        regions = load_region_geometries(args.clip_regions)
        if not regions:
            logger.warning("No regions found in clip-regions file.")
            return 0

        if args.save_scenes is not None:
            all_tiles = []
            for quarter in args.quarter:
                for region_name, region_geometry in regions:
                    logger.info("Searching STAC: %s / %s", quarter, region_name)
                    tiles = search_mosaic_tiles(
                        region_geometry=region_geometry,
                        quarter=quarter,
                        stac_url=args.stac_url,
                    )
                    all_tiles.extend(tiles)
            with open(args.save_scenes, "w") as f:
                json.dump([dataclasses.asdict(t) for t in all_tiles], f, indent=2)
            logger.info("Saved %d scenes to %s", len(all_tiles), args.save_scenes)
            return 0

        preloaded_tiles: list[MosaicTile] | None = None
        if args.load_scenes is not None:
            preloaded_tiles = load_mosaic_tiles(args.load_scenes)
            logger.info("Loaded %d scenes from %s", len(preloaded_tiles), args.load_scenes)

        any_region_failed = False

        for quarter in args.quarter:
            start_ts = time.monotonic()
            quarter_vrts: list[Path] = []
            results: list[dict[str, object]] = []
            for region_name, region_geometry in regions:
                logger.info("--- %s : %s ---", quarter, region_name)
                try:
                    vrt = _process_region_quarter(
                        region_name,
                        region_geometry,
                        quarter,
                        args,
                        preloaded_tiles=preloaded_tiles,
                    )
                except Exception as exc:
                    logger.exception("Region %s %s failed", region_name, quarter)
                    any_region_failed = True
                    results.append(
                        {
                            "region_name": region_name,
                            "quarter": quarter,
                            "status": "failed",
                            "output_path": None,
                            "error": str(exc),
                        }
                    )
                    continue

                if vrt is None:
                    results.append(
                        {
                            "region_name": region_name,
                            "quarter": quarter,
                            "status": "skipped_no_tiles",
                            "output_path": None,
                            "error": None,
                        }
                    )
                else:
                    quarter_vrts.append(vrt)
                    results.append(
                        {
                            "region_name": region_name,
                            "quarter": quarter,
                            "status": "succeeded",
                            "output_path": str(vrt),
                            "error": None,
                        }
                    )

            if quarter_vrts:
                build_top_level_vrt(
                    quarter_vrts,
                    args.output_dir,
                    vrt_name=f"{quarter}-{args.vrt_name}",
                )
            else:
                logger.warning("No VRTs produced for quarter %s.", quarter)

            _write_quarter_summary(args.output_dir, quarter, results, time.monotonic() - start_ts)

        return 1 if any_region_failed else 0

    except Exception:
        logger.exception("Pipeline failed")
        return 1


def _run_process_bands(args: argparse.Namespace) -> int:
    try:
        _configure_gdal()
        path_r = _resolve_gdal_path(args.red)
        path_g = _resolve_gdal_path(args.green)
        path_b = _resolve_gdal_path(args.blue)
        config: dict[str, str] = {}
        if path_r.startswith("/vsis3/"):
            config["AWS_VIRTUAL_HOSTING"] = "FALSE"

        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)

        tag = uuid.uuid4().hex[:8]
        vsimem_path = f"/vsimem/process_bands_{tag}.tif"
        try:
            process_bands(path_r, path_g, path_b, vsimem_path, config)
            finalize_single_cog(vsimem_path, output, args.pixel_size)
        finally:
            with contextlib.suppress(RuntimeError):
                gdal.Unlink(vsimem_path)

        return 0
    except Exception:
        logger.exception("process-bands failed")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(args.verbose, args.log_format)

    if args.command == "mosaic":
        return _run_mosaic(args)
    return _run_process_bands(args)


def cli() -> None:
    sys.exit(main())


if __name__ == "__main__":
    cli()
