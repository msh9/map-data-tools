"""Tests for STAC search and quarter parsing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import requests

from sentinel_mosaic.search import (
    MosaicTile,
    load_mosaic_tiles,
    load_region_geometries,
    quarter_to_datetime_range,
    search_mosaic_tiles,
)


class TestQuarterToDatetimeRange:
    def test_q1(self) -> None:
        start, end = quarter_to_datetime_range("2024-Q1")
        assert start == "2024-01-01T00:00:00Z"
        assert end == "2024-04-01T00:00:00Z"

    def test_q3(self) -> None:
        start, end = quarter_to_datetime_range("2024-Q3")
        assert start == "2024-07-01T00:00:00Z"
        assert end == "2024-10-01T00:00:00Z"

    def test_q4_crosses_year(self) -> None:
        start, end = quarter_to_datetime_range("2024-Q4")
        assert start == "2024-10-01T00:00:00Z"
        assert end == "2025-01-01T00:00:00Z"

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid quarter"):
            quarter_to_datetime_range("2024Q3")

    def test_invalid_quarter_number_raises(self) -> None:
        with pytest.raises(ValueError, match="Quarter must be 1-4"):
            quarter_to_datetime_range("2024-Q5")


class TestLoadRegionGeometries:
    def test_loads_named_features(self, tmp_path: Path) -> None:
        path = tmp_path / "regions.geojson"
        path.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"region-name": "wasatch"},
                            "geometry": {"type": "Point", "coordinates": [-112, 41]},
                        },
                        {
                            "type": "Feature",
                            "properties": {"region-name": "front-range"},
                            "geometry": {"type": "Point", "coordinates": [-105, 40]},
                        },
                    ],
                }
            )
        )
        regions = load_region_geometries(path)
        assert [r[0] for r in regions] == ["wasatch", "front-range"]


class TestLoadMosaicTiles:
    _TILE_DATA = [
        {
            "tile_id": "32TNT",
            "quarter": "2024-Q3",
            "geometry": {"type": "Polygon", "coordinates": []},
            "href_red": "https://example.com/B04.tif",
            "href_green": "https://example.com/B03.tif",
            "href_blue": "https://example.com/B02.tif",
        }
    ]

    def test_round_trips_mosaic_tiles(self, tmp_path: Path) -> None:
        path = tmp_path / "scenes.json"
        path.write_text(json.dumps(self._TILE_DATA))
        tiles = load_mosaic_tiles(path)
        assert len(tiles) == 1
        assert isinstance(tiles[0], MosaicTile)
        assert tiles[0].tile_id == "32TNT"
        assert tiles[0].quarter == "2024-Q3"
        assert tiles[0].href_red == "https://example.com/B04.tif"

    def test_returns_empty_list_for_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "scenes.json"
        path.write_text("[]")
        assert load_mosaic_tiles(path) == []

    def test_raises_on_missing_fields(self, tmp_path: Path) -> None:
        path = tmp_path / "scenes.json"
        path.write_text(json.dumps([{"tile_id": "32TNT"}]))  # missing href_* and quarter
        with pytest.raises(ValueError, match="missing required fields"):
            load_mosaic_tiles(path)

    def test_extra_fields_are_ignored(self, tmp_path: Path) -> None:
        data = [{**self._TILE_DATA[0], "extra_field": "ignored"}]
        path = tmp_path / "scenes.json"
        path.write_text(json.dumps(data))
        tiles = load_mosaic_tiles(path)
        assert tiles[0].tile_id == "32TNT"


class TestSearchMosaicTiles:
    def _make_item(self, item_id: str) -> MagicMock:
        item = MagicMock()
        item.id = item_id
        item.geometry = {"type": "Point", "coordinates": [0, 0]}

        def asset(href):
            a = MagicMock()
            a.href = href
            return a

        item.assets = {
            "B04": asset(f"https://cdse/{item_id}/B04.tif"),
            "B03": asset(f"https://cdse/{item_id}/B03.tif"),
            "B02": asset(f"https://cdse/{item_id}/B02.tif"),
        }
        return item

    def test_returns_mosaic_tiles(self) -> None:
        client = MagicMock()
        search = MagicMock()
        search.items.return_value = [self._make_item("T12TVL"), self._make_item("T12TVK")]
        client.search.return_value = search

        with patch("sentinel_mosaic.search.Client.open", return_value=client):
            tiles = search_mosaic_tiles(
                region_geometry={"type": "Polygon", "coordinates": [[[0, 0]]]},
                quarter="2024-Q3",
            )

        assert len(tiles) == 2
        assert all(isinstance(t, MosaicTile) for t in tiles)
        assert tiles[0].quarter == "2024-Q3"
        assert tiles[0].href_red.endswith("B04.tif")
        assert tiles[0].href_green.endswith("B03.tif")
        assert tiles[0].href_blue.endswith("B02.tif")

    def test_retries_on_transient_network_failure(self) -> None:
        client = MagicMock()
        search = MagicMock()
        attempts = {"n": 0}

        def items_with_flake():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise requests.ConnectionError("simulated transient")
            return iter([self._make_item("T1"), self._make_item("T2")])

        search.items.side_effect = items_with_flake
        client.search.return_value = search

        with (
            patch("sentinel_mosaic.search.Client.open", return_value=client),
            patch("sentinel_mosaic.search.time.sleep") as mock_sleep,
        ):
            tiles = search_mosaic_tiles(
                region_geometry={"type": "Polygon", "coordinates": [[[0, 0]]]},
                quarter="2024-Q3",
            )

        assert len(tiles) == 2
        assert attempts["n"] == 3
        # Backoff was applied between retries (don't assert exact delays — keep
        # tests resilient to tuning).
        assert mock_sleep.call_count >= 2

    def test_gives_up_after_max_attempts(self) -> None:
        client = MagicMock()
        search = MagicMock()
        search.items.side_effect = requests.ConnectionError("permanently down")
        client.search.return_value = search

        with (
            patch("sentinel_mosaic.search.Client.open", return_value=client),
            patch("sentinel_mosaic.search.time.sleep"),
            pytest.raises(requests.ConnectionError),
        ):
            search_mosaic_tiles(
                region_geometry={"type": "Polygon", "coordinates": [[[0, 0]]]},
                quarter="2024-Q3",
            )

    def test_skips_items_missing_assets(self) -> None:
        good = self._make_item("good")
        bad = MagicMock()
        bad.id = "bad"
        bad.geometry = {}
        bad.assets = {}  # missing all bands

        client = MagicMock()
        search = MagicMock()
        search.items.return_value = [good, bad]
        client.search.return_value = search

        with patch("sentinel_mosaic.search.Client.open", return_value=client):
            tiles = search_mosaic_tiles(
                region_geometry={"type": "Polygon", "coordinates": [[[0, 0]]]},
                quarter="2024-Q3",
            )
        assert [t.tile_id for t in tiles] == ["good"]
