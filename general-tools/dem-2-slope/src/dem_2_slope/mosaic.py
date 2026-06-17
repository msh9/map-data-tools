"""Build a VRT mosaic over processed slope COGs."""

from __future__ import annotations

import logging
from pathlib import Path

from osgeo import gdal

logger = logging.getLogger(__name__)

VRT_FILENAME = "slope-mosaic.vrt"


def build_vrt(
    cog_paths: list[Path],
    output_dir: Path,
    vrt_name: str = VRT_FILENAME,
) -> Path:
    """Build a VRT over all processed slope COGs.

    Returns the path to the output VRT file.
    """
    vrt_path = output_dir / vrt_name
    input_files = [str(p) for p in cog_paths]

    logger.info("Building VRT over %d COGs -> %s", len(input_files), vrt_path)
    vrt_ds = gdal.BuildVRT(str(vrt_path), input_files)
    if vrt_ds is None:
        raise RuntimeError("gdal.BuildVRT failed")
    vrt_ds.FlushCache()
    vrt_ds = None  # close to ensure the VRT XML is written

    logger.info("Wrote VRT: %s", vrt_path)
    return vrt_path
