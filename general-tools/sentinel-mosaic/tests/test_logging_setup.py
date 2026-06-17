"""Tests for logging configuration."""

from __future__ import annotations

import json
import logging

from sentinel_mosaic.logging_setup import JsonFormatter


class TestJsonFormatter:
    def test_emits_valid_json_with_required_fields(self) -> None:
        record = logging.LogRecord(
            name="sentinel_mosaic.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        payload = json.loads(JsonFormatter().format(record))
        assert payload["msg"] == "hello world"
        assert payload["level"] == "INFO"
        assert payload["logger"] == "sentinel_mosaic.test"
        assert "ts" in payload

    def test_includes_extra_fields(self) -> None:
        record = logging.LogRecord(
            name="sentinel_mosaic.test",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg="skipped",
            args=(),
            exc_info=None,
        )
        record.region = "wasatch"  # type: ignore[attr-defined]
        record.tile_id = "T0"  # type: ignore[attr-defined]
        payload = json.loads(JsonFormatter().format(record))
        assert payload["region"] == "wasatch"
        assert payload["tile_id"] == "T0"
