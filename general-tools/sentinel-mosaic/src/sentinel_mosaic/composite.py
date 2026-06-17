"""Per-tile COG output and VRT construction for Sentinel-2 mosaics."""

from __future__ import annotations

import logging
from pathlib import Path

from osgeo import gdal

logger = logging.getLogger(__name__)

# Lambert Azimuthal Equal-Area (North America) — equal-area projection preserves
TARGET_CRS = "ESRI:102009"

TILE_COG_CREATION_OPTIONS = [
    "COMPRESS=WEBP",
    "QUALITY=100",
    "BLOCKSIZE=512",
    "ADD_ALPHA=NO",
]

def finalize_output_tile(
    processed_path: str,
    tile_id: str,
    clip_regions_path: Path,
    region_name: str,
    tile_output_dir: Path,
    pixel_size: float,
) -> Path:
    """Warp, clip to region polygon, and reproject a processed tile to a COG in TARGET_CRS."""
    output_path = tile_output_dir / f"{tile_id}.cog.tif"

    escaped_name = region_name.replace("'", "''")
    warp_options = gdal.WarpOptions(
        cutlineDSName=str(clip_regions_path),
        cutlineWhere=f"\"region-name\" = '{escaped_name}'",
        cropToCutline=True,
        dstSRS=TARGET_CRS,
        xRes=pixel_size,
        yRes=pixel_size,
        resampleAlg="cubic",
        format="COG",
        creationOptions=TILE_COG_CREATION_OPTIONS,
        multithread=True,
    )

    gdal.Warp(output_path, processed_path, options=warp_options)
    logger.info("Wrote tile COG: %s", output_path)
    return output_path


def finalize_single_cog(
    processed_path: str,
    output_path: Path,
    pixel_size: float = 10.0,
    target_crs: str = TARGET_CRS,
) -> Path:
    """Warp a processed RGBA tile to a COG in target_crs without cutline clipping."""
    warp_options = gdal.WarpOptions(
        dstSRS=target_crs,
        xRes=pixel_size,
        yRes=pixel_size,
        resampleAlg="cubic",
        format="COG",
        creationOptions=TILE_COG_CREATION_OPTIONS,
        multithread=True,
    )

    gdal.Warp(output_path, processed_path, options=warp_options)
    logger.info("Wrote single COG: %s", output_path)
    return output_path


def build_per_region_vrt(
    tile_paths: list[Path],
    output_dir: Path,
    region_name: str,
    quarter: str,
) -> Path:
    """Build a VRT mosaicking a region's tile COGs with last-STAC-tile-wins semantics.

    GDAL VRT compositing is first-source-wins; reversing the tile list makes the
    last STAC-returned tile appear first in the VRT, achieving last-wins on overlap.
    """
    vrt_path = output_dir / f"{region_name}_{quarter}.vrt"
    input_files = [str(p) for p in reversed(tile_paths)]

    logger.info("Building per-region VRT over %d tiles -> %s", len(input_files), vrt_path)
    vrt_ds = gdal.BuildVRT(str(vrt_path), input_files)
    if vrt_ds is None:
        raise RuntimeError("gdal.BuildVRT failed")
    vrt_ds.FlushCache()
    vrt_ds = None

    _rewrite_vrt_paths_relative(vrt_path)
    logger.info("Wrote per-region VRT: %s", vrt_path)
    return vrt_path


def build_top_level_vrt(
    per_region_vrt_paths: list[Path],
    output_dir: Path,
    vrt_name: str,
) -> Path:
    """Build a VRT-of-VRTs referencing all per-region VRTs for a quarter."""
    vrt_path = output_dir / vrt_name
    input_files = [str(p) for p in per_region_vrt_paths]

    logger.info("Building top-level VRT over %d region VRTs -> %s", len(input_files), vrt_path)
    vrt_ds = gdal.BuildVRT(str(vrt_path), input_files)
    if vrt_ds is None:
        raise RuntimeError("gdal.BuildVRT failed")
    vrt_ds.FlushCache()
    vrt_ds = None

    _rewrite_vrt_paths_relative(vrt_path)
    logger.info("Wrote top-level VRT: %s", vrt_path)
    return vrt_path


def _rewrite_vrt_paths_relative(vrt_path: Path) -> None:
    """Rewrite <SourceFilename> entries in a VRT to be relative to the VRT."""
    import xml.etree.ElementTree as ET

    tree = ET.parse(vrt_path)
    root = tree.getroot()
    vrt_dir = vrt_path.parent
    for src in root.iter("SourceFilename"):
        if src.text is None:
            continue
        candidate = Path(src.text)
        if not candidate.is_absolute():
            continue
        try:
            rel = candidate.relative_to(vrt_dir)
        except ValueError:
            # Source lives outside the VRT directory; absolute path is the
            # only correct reference, leave it alone.
            continue
        src.text = str(rel)
        src.set("relativeToVRT", "1")
    tree.write(vrt_path, encoding="utf-8", xml_declaration=False)
