"""STAC API discovery for CDSE Sentinel-2 quarterly global mosaics."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

import requests
from pystac_client import Client

try:
    # pystac-client >=0.7 exposes APIError; absent in older builds.
    from pystac_client.exceptions import APIError as _APIError
except ImportError:  # pragma: no cover
    _APIError = type("APIError", (Exception,), {})

T = TypeVar("T")

# Errors worth retrying: connection-level failures and STAC API transients.
_RETRY_EXCEPTIONS: tuple[type[BaseException], ...] = (
    requests.ConnectionError,
    requests.Timeout,
    _APIError,
)

logger = logging.getLogger(__name__)

STAC_URL = "https://stac.dataspace.copernicus.eu/v1"
COLLECTION = "sentinel-2-global-mosaics"

RED_ASSET = "B04"
GREEN_ASSET = "B03"
BLUE_ASSET = "B02"


@dataclass(frozen=True)
class MosaicTile:
    """A single Sentinel-2 quarterly mosaic tile."""

    tile_id: str
    quarter: str  # e.g. "2024-Q3"
    geometry: dict
    href_red: str
    href_green: str
    href_blue: str


def load_region_geometries(clip_regions_path: Path) -> list[tuple[str, dict]]:
    """Load (region_name, geometry) pairs from a GeoJSON FeatureCollection."""
    with open(clip_regions_path) as f:
        fc = json.load(f)

    regions = []
    for feature in fc.get("features", []):
        name = feature.get("properties", {}).get("region-name", "unknown")
        geometry = feature.get("geometry")
        if geometry:
            regions.append((name, geometry))
    return regions


def quarter_to_datetime_range(quarter: str) -> tuple[str, str]:
    """Parse 'YYYY-Qn' into an ISO datetime interval string for STAC.

    Returns (start, end) as RFC3339 strings.
    """
    try:
        year_str, q_str = quarter.split("-Q")
        year = int(year_str)
        q = int(q_str)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid quarter format '{quarter}', expected YYYY-Qn") from exc

    if q not in (1, 2, 3, 4):
        raise ValueError(f"Quarter must be 1-4, got {q}")

    start_dt = datetime(year, (q - 1) * 3 + 1, 1, tzinfo=timezone.utc)
    end_dt = (
        datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        if q == 4
        else datetime(year, q * 3 + 1, 1, tzinfo=timezone.utc)
    )
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start_dt.strftime(fmt), end_dt.strftime(fmt)


def _with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    backoff_base: int = 8,
    description: str = "STAC request",
) -> T:
    """Call ``fn`` with bounded retry + exponential backoff on transient errors."""
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except _RETRY_EXCEPTIONS as exc:
            last_exc = exc
            if attempt < max_attempts:
                delay = backoff_base ** (attempt)
                logger.warning(
                    "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                    description,
                    attempt,
                    max_attempts,
                    exc,
                    delay,
                )
                time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def _extract_href(item, asset_key: str) -> str:
    asset = item.assets.get(asset_key)
    if asset is None:
        raise ValueError(f"Item {item.id} missing asset '{asset_key}'")
    return asset.href


def load_mosaic_tiles(path: Path) -> list[MosaicTile]:
    """Load MosaicTile objects from a JSON file previously saved by --save-scenes."""
    with open(path) as f:
        data = json.load(f)
    required = {f.name for f in fields(MosaicTile)}
    tiles: list[MosaicTile] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict) or not required.issubset(item):
            missing = required - set(item) if isinstance(item, dict) else required
            raise ValueError(
                f"Scene entry {i} in {path} missing required fields: {sorted(missing)}"
            )
        tiles.append(MosaicTile(**{k: item[k] for k in required}))
    return tiles


def search_mosaic_tiles(
    region_geometry: dict,
    quarter: str,
    *,
    stac_url: str = STAC_URL,
) -> list[MosaicTile]:
    """Search the CDSE STAC API for mosaic tiles intersecting a region.

    Args:
        region_geometry: GeoJSON geometry of the region of interest.
        quarter: Quarter string 'YYYY-Qn' (e.g. '2024-Q3').
        stac_url: STAC API root.

    Returns:
        A list of MosaicTile entries (one per matching STAC item).
    """
    start, end = quarter_to_datetime_range(quarter)
    client = _with_retry(lambda: Client.open(stac_url), description="STAC client open")

    search = client.search(
        collections=[COLLECTION],
        intersects=region_geometry,
        datetime=f"{start}/{end}",
        max_items=None,
    )

    # Materialize the iterator under retry — pystac-client paginates lazily and
    # transient errors mid-pagination would otherwise abort the run.
    items = _with_retry(lambda: list(search.items()), description="STAC items pagination")

    tiles: list[MosaicTile] = []
    for item in items:
        try:
            tiles.append(
                MosaicTile(
                    tile_id=item.id,
                    quarter=quarter,
                    geometry=item.geometry,
                    href_red=_extract_href(item, RED_ASSET),
                    href_green=_extract_href(item, GREEN_ASSET),
                    href_blue=_extract_href(item, BLUE_ASSET),
                )
            )
        except ValueError as exc:
            logger.warning("Skipping mosaic item %s: %s", item.id, exc)

    logger.info("Found %d mosaic tiles for quarter %s", len(tiles), quarter)
    return tiles
