from __future__ import annotations

from pathlib import Path
from typing import Sequence

from _process_sectionals.constants import (
    CHART_TYPE_FLY,
    CHART_TYPE_SECTIONAL,
    CHART_TYPE_TAC,
    CHART_TYPES,
    SECTIONAL_SKIP_FILENAMES,
    TAC_SKIP_FILENAMES,
)
from _process_sectionals.models import ChartEntry, ChartSource
from _process_sectionals.naming import normalize_chart_name, parse_tac_chart_basename


def classify_tac_chart_file(tif_path: Path) -> ChartEntry | None:
    lower_name = tif_path.name.lower()
    if lower_name in TAC_SKIP_FILENAMES:
        return None

    lower_stem = tif_path.stem.lower()
    if lower_stem.endswith(" fly"):
        chart_type = CHART_TYPE_FLY
    elif " tac" in lower_stem:
        chart_type = CHART_TYPE_TAC
    else:
        raise ValueError(f"Unrecognized TAC/FLY TIFF naming convention: {tif_path.name}")

    base_name = parse_tac_chart_basename(tif_path.stem)
    coverage_key = normalize_chart_name(f"{base_name}_TAC")
    return ChartEntry(
        tif_path=tif_path,
        chart_type=chart_type,
        coverage_key=coverage_key,
    )


def discover_chart_sources(
    raw_charts_dir: Path,
    *,
    chart_types: set[str],
) -> list[ChartSource]:
    if not raw_charts_dir.is_dir():
        raise FileNotFoundError(f"Raw charts directory not found: {raw_charts_dir}")

    unsupported = sorted(chart_type for chart_type in chart_types if chart_type not in CHART_TYPES)
    if unsupported:
        raise ValueError(f"Unsupported chart type(s): {', '.join(unsupported)}")

    discovered: list[ChartSource] = []
    seen_names: dict[str, Path] = {}

    for chart_dir in sorted(raw_charts_dir.iterdir(), key=lambda path: path.name.lower()):
        if not chart_dir.is_dir():
            continue

        entries: list[ChartEntry] = []
        if chart_dir.name.endswith("_TAC"):
            if CHART_TYPE_TAC not in chart_types and CHART_TYPE_FLY not in chart_types:
                continue
            for path in sorted(chart_dir.iterdir(), key=lambda item: item.name.lower()):
                if not path.is_file() or path.suffix.lower() != ".tif":
                    continue
                entry = classify_tac_chart_file(path)
                if entry is None:
                    print(f"Skipping special-case TAC file: {path}")
                    continue
                if entry.chart_type in chart_types:
                    entries.append(entry)
        else:
            if CHART_TYPE_SECTIONAL not in chart_types:
                continue
            coverage_key = normalize_chart_name(chart_dir.name)
            for path in sorted(chart_dir.iterdir(), key=lambda item: item.name.lower()):
                if not path.is_file():
                    continue
                if path.name.lower() in SECTIONAL_SKIP_FILENAMES:
                    print(f"Skipping special-case sectional file: {path}")
                    continue
                if path.suffix.lower() == ".tif" and path.name.lower().endswith(" sec.tif"):
                    entries.append(
                        ChartEntry(
                            tif_path=path,
                            chart_type=CHART_TYPE_SECTIONAL,
                            coverage_key=coverage_key,
                        )
                    )

        if not entries:
            continue

        chart_name = chart_dir.name
        normalized_name = normalize_chart_name(chart_name)
        existing = seen_names.get(normalized_name)
        if existing is not None:
            raise ValueError(
                "Duplicate normalized chart key "
                f"{normalized_name!r} from {existing} and {chart_dir}."
            )
        seen_names[normalized_name] = chart_dir

        discovered.append(
            ChartSource(
                chart_name=chart_name,
                normalized_chart_name=normalized_name,
                entries=tuple(entries),
            )
        )

    return discovered


def select_sources(
    sources: Sequence[ChartSource],
    *,
    requested_charts: Sequence[str] | None,
    all_charts: bool,
) -> list[ChartSource]:
    if requested_charts and all_charts:
        raise ValueError("Use either --chart or --all-charts, not both.")
    if not all_charts and not requested_charts:
        raise ValueError("At least one --chart must be provided unless --all-charts is set.")

    if all_charts:
        return list(sources)

    by_normalized_name = {source.normalized_chart_name: source for source in sources}
    selected: list[ChartSource] = []
    selected_keys: set[str] = set()

    assert requested_charts is not None
    for chart_name in requested_charts:
        normalized = normalize_chart_name(chart_name)
        source = by_normalized_name.get(normalized)
        if source is None:
            known = ", ".join(sorted(source.chart_name for source in sources))
            raise ValueError(f"Requested chart {chart_name!r} was not found. Known charts: {known}")
        if normalized in selected_keys:
            continue
        selected_keys.add(normalized)
        selected.append(source)

    return selected
