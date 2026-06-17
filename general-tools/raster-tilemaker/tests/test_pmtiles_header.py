from __future__ import annotations

from pathlib import Path

import numpy as np

from raster_tilemaker.output import pmtiles as pmtiles_module
from raster_tilemaker.render.mosaic import RenderedTile


def _read_header_tile_type(path: Path) -> int:
    return path.read_bytes()[99]


def _single_non_empty_tile() -> list[RenderedTile]:
    tile_array = np.full((8, 8, 4), 255, dtype=np.uint8)
    return [RenderedTile(z=0, x=0, y=0, tile_array=tile_array, has_data=True)]


def test_pmtiles_header_tile_type_matches_output_format(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(pmtiles_module, "ensure_format_support", lambda *_: None)
    monkeypatch.setattr(
        pmtiles_module,
        "_encode_tile",
        lambda *_args, **kwargs: kwargs["tile_format"].encode("ascii"),
    )

    bounds_wgs84 = (-111.0, 40.0, -109.0, 42.0)
    for tile_format, expected_tile_type in (("webp", 4), ("avif", 5)):
        output_path = tmp_path / f"{tile_format}.pmtiles"
        written = pmtiles_module.write_pmtiles_archive(
            _single_non_empty_tile(),
            output_path,
            tile_format=tile_format,
            quality=30,
            resolutions=[2560.0],
            bounds_wgs84=bounds_wgs84,
        )

        assert written == 1
        assert _read_header_tile_type(output_path) == expected_tile_type
