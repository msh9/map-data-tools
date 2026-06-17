from __future__ import annotations

from pathlib import Path

from _process_sectionals.constants import CHART_TYPE_FLY, CHART_TYPE_SECTIONAL, CHART_TYPE_TAC
from _process_sectionals.models import ChartEntry
from _process_sectionals.naming import normalize_chart_name


def build_coverage_index(coverage_dir: Path) -> dict[str, Path]:
    if not coverage_dir.is_dir():
        raise FileNotFoundError(f"Coverage directory not found: {coverage_dir}")

    by_chart_name: dict[str, Path] = {}
    for coverage_path in sorted(coverage_dir.glob("*.geojson"), key=lambda path: path.name.lower()):
        normalized_name = normalize_chart_name(coverage_path.stem)
        existing = by_chart_name.get(normalized_name)
        if existing is not None:
            raise ValueError(
                "Duplicate normalized coverage key "
                f"{normalized_name!r} from {existing} and {coverage_path}."
            )
        by_chart_name[normalized_name] = coverage_path
    return by_chart_name


def coverage_lookup_for_entry(
    entry: ChartEntry,
    *,
    sectional_coverage_index: dict[str, Path],
    tac_fly_coverage_index: dict[str, Path],
) -> Path | None:
    if entry.chart_type == CHART_TYPE_SECTIONAL:
        return sectional_coverage_index.get(entry.coverage_key)
    if entry.chart_type in (CHART_TYPE_TAC, CHART_TYPE_FLY):
        return tac_fly_coverage_index.get(entry.coverage_key)
    raise ValueError(f"Unsupported chart type: {entry.chart_type}")


def coverage_dir_for_entry(
    entry: ChartEntry,
    *,
    sectional_coverage_dir: Path,
    tac_fly_coverage_dir: Path,
) -> Path:
    if entry.chart_type == CHART_TYPE_SECTIONAL:
        return sectional_coverage_dir
    if entry.chart_type in (CHART_TYPE_TAC, CHART_TYPE_FLY):
        return tac_fly_coverage_dir
    raise ValueError(f"Unsupported chart type: {entry.chart_type}")
