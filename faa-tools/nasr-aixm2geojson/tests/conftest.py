"""Fixtures for NASR AIXM navaid tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make tests directory importable for xml_builders module
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture
def tmp_aixm_file(tmp_path: Path):
    """Factory fixture that writes AIXM XML to a temp file and returns the path."""

    def _create(xml_content: str, filename: str = "NAV_AIXM.xml") -> Path:
        p = tmp_path / filename
        p.write_text(xml_content, encoding="utf-8")
        return p

    return _create
