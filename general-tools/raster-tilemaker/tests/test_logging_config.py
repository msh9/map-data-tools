from __future__ import annotations

import json
import logging

import pytest

from raster_tilemaker.logging_config import (
    _JsonFormatter,
    _ROOT_LOGGER,
    configure_logging,
)


@pytest.fixture(autouse=True)
def reset_root_logger():
    """Ensure the raster_tilemaker logger is clean before and after each test."""
    logger = logging.getLogger(_ROOT_LOGGER)
    original_handlers = logger.handlers[:]
    original_level = logger.level
    logger.handlers.clear()
    yield
    logger.handlers.clear()
    logger.handlers.extend(original_handlers)
    logger.setLevel(original_level)


def _make_record(
    msg: str = "test message",
    level: int = logging.INFO,
    name: str = "raster_tilemaker.test",
    **extra_fields,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra_fields.items():
        setattr(record, key, value)
    return record


class TestJsonFormatter:
    def test_produces_valid_json(self):
        formatter = _JsonFormatter()
        record = _make_record()
        output = formatter.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_required_fields_present(self):
        formatter = _JsonFormatter()
        record = _make_record(msg="hello world", level=logging.WARNING)
        parsed = json.loads(formatter.format(record))
        assert parsed["level"] == "WARNING"
        assert parsed["logger"] == "raster_tilemaker.test"
        assert parsed["message"] == "hello world"
        assert "timestamp" in parsed

    def test_timestamp_is_iso8601(self):
        formatter = _JsonFormatter()
        record = _make_record()
        parsed = json.loads(formatter.format(record))
        ts = parsed["timestamp"]
        assert "T" in ts and "+" in ts or ts.endswith("Z") or "+00:00" in ts

    def test_extra_fields_merged_into_output(self):
        formatter = _JsonFormatter()
        record = _make_record(z=3, resolution_m_px=160.0, vrt_path="/some/file.vrt")
        parsed = json.loads(formatter.format(record))
        assert parsed["z"] == 3
        assert parsed["resolution_m_px"] == 160.0
        assert parsed["vrt_path"] == "/some/file.vrt"

    def test_standard_attrs_not_duplicated(self):
        formatter = _JsonFormatter()
        record = _make_record()
        parsed = json.loads(formatter.format(record))
        assert "lineno" not in parsed
        assert "pathname" not in parsed
        assert "funcName" not in parsed
        assert "threadName" not in parsed

    def test_one_line_per_record(self):
        formatter = _JsonFormatter()
        record = _make_record(msg="line one")
        output = formatter.format(record)
        assert "\n" not in output


class TestConfigureLogging:
    def test_adds_handler_to_root_logger(self):
        logger = logging.getLogger(_ROOT_LOGGER)
        assert not logger.handlers
        configure_logging("text", "info")
        assert len(logger.handlers) == 1

    def test_sets_info_level(self):
        configure_logging("text", "info")
        assert logging.getLogger(_ROOT_LOGGER).level == logging.INFO

    def test_sets_warning_level(self):
        configure_logging("text", "warning")
        assert logging.getLogger(_ROOT_LOGGER).level == logging.WARNING

    def test_json_format_uses_json_formatter(self):
        configure_logging("json", "info")
        logger = logging.getLogger(_ROOT_LOGGER)
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0].formatter, _JsonFormatter)

    def test_text_format_uses_standard_formatter(self):
        configure_logging("text", "info")
        logger = logging.getLogger(_ROOT_LOGGER)
        assert len(logger.handlers) == 1
        assert not isinstance(logger.handlers[0].formatter, _JsonFormatter)

    def test_idempotent_second_call_is_noop(self):
        configure_logging("text", "info")
        handler_before = logging.getLogger(_ROOT_LOGGER).handlers[0]
        configure_logging("json", "debug")
        handlers_after = logging.getLogger(_ROOT_LOGGER).handlers
        assert len(handlers_after) == 1
        assert handlers_after[0] is handler_before
