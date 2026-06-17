from __future__ import annotations

from pathlib import Path
from raster_tilemaker.config import DEFAULT_FORMAT, DEFAULT_QUALITY, DEFAULT_TILE_SIZE

__all__ = [
    "DEFAULT_FORMAT",
    "DEFAULT_QUALITY",
    "DEFAULT_TILE_SIZE",
    "default_output_dir",
]


def default_output_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "tile_output"
