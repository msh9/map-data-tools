"""Download a single DEM tile from a URL to a local file."""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


def download_dem(url: str, dest_path: Path) -> Path:
    """Download a DEM file from *url* to *dest_path*.

    Returns the destination path on success.
    """
    logger.info("Downloading %s -> %s", url, dest_path)
    urllib.request.urlretrieve(url, dest_path)  # noqa: S310
    return dest_path
