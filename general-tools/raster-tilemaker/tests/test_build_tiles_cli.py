from __future__ import annotations

import logging
from pathlib import Path

import pytest

from raster_tilemaker import build_tiles


def test_build_tiles_requires_input_vrt() -> None:
    with pytest.raises(SystemExit) as excinfo:
        build_tiles.main([])
    assert excinfo.value.code == 2


def test_build_tiles_missing_input_vrt_returns_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="raster_tilemaker"):
        exit_code = build_tiles.main(
            [
                "--input-vrt",
                str(tmp_path / "missing.vrt"),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
    assert exit_code == 1
    assert "Input VRT not found" in caplog.text


def test_build_tiles_rejects_config_and_resolution_together(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"resolutions": [2560, 1280]}', encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="raster_tilemaker"):
        exit_code = build_tiles.main(
            [
                "--input-vrt",
                str(tmp_path / "any.vrt"),
                "--output-dir",
                str(tmp_path / "out"),
                "--config",
                str(config_path),
                "--resolution",
                "640",
            ]
        )
    assert exit_code == 1
    assert "Use either --config or --resolution" in caplog.text
