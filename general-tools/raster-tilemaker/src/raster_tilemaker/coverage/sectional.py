from __future__ import annotations

from pathlib import Path

from raster_tilemaker.coverage import common
from raster_tilemaker.coverage.common import CoverageFeature, CoverageIndex, load_coverage_index

SectionalCoverageFeature = CoverageFeature
SectionalCoverageIndex = CoverageIndex


def normalize_chart_name(name: str) -> str:
    return common.normalize_chart_name(name)


def load_sectional_coverage_index(path: Path) -> SectionalCoverageIndex:
    return load_coverage_index(path)
