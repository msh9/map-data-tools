from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from _process_sectionals.constants import (
    CHART_TYPE_FLY,
    CHART_TYPE_SECTIONAL,
    CHART_TYPE_TAC,
    CHART_TYPES,
    MAPPING_KEY_BY_CHART_TYPE,
    TERMINAL_AREA_KEY_ALIASES,
)
from _process_sectionals.naming import normalize_chart_name


def warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


def collect_processed_chart_files(
    chart_dir: Path,
    *,
    file_match_token: str,
    chart_type: str,
) -> list[Path]:
    token = file_match_token.lower()
    files: list[Path] = []
    for path in sorted(chart_dir.glob("*.tif"), key=lambda item: item.name.lower()):
        lower_name = path.name.lower()
        if token not in lower_name:
            continue
        if chart_type in (CHART_TYPE_TAC, CHART_TYPE_FLY) and f".{chart_type}." not in lower_name:
            continue
        files.append(path)
    return files


def build_processed_chart_dir_index(processed_root: Path) -> dict[str, Path]:
    chart_dir_by_normalized_name: dict[str, Path] = {}
    for chart_dir in sorted(processed_root.iterdir(), key=lambda item: item.name.lower()):
        if not chart_dir.is_dir():
            continue
        normalized_name = normalize_chart_name(chart_dir.name)
        existing = chart_dir_by_normalized_name.get(normalized_name)
        if existing is not None:
            raise ValueError(f"Duplicate normalized chart directory key: {normalized_name}")
        chart_dir_by_normalized_name[normalized_name] = chart_dir
    return chart_dir_by_normalized_name


def terminal_area_lookup_keys_for_file(path: Path, *, chart_type: str) -> set[str]:
    marker = f".{chart_type}."
    lower_name = path.name.lower()
    if marker not in lower_name:
        return set()

    prefix = lower_name.split(marker, 1)[0]
    source_component = prefix.split("--", 1)[1] if "--" in prefix else prefix
    normalized_source_component = normalize_chart_name(source_component)

    keys = {normalized_source_component}
    for suffix in ("tac", "fly"):
        if normalized_source_component.endswith(suffix):
            trimmed = normalized_source_component[: -len(suffix)]
            if trimmed:
                keys.add(trimmed)
    return keys


def terminal_area_lookup_variants(key: str) -> set[str]:
    variants = {key}
    for alias in TERMINAL_AREA_KEY_ALIASES.get(key, ()):
        variants.add(alias)
    return variants


def build_terminal_area_file_index(
    processed_root: Path,
    *,
    file_match_token: str,
    chart_type: str,
) -> dict[str, list[Path]]:
    by_key: dict[str, list[Path]] = {}
    seen_by_key: dict[str, set[Path]] = {}

    for chart_dir in sorted(processed_root.iterdir(), key=lambda item: item.name.lower()):
        if not chart_dir.is_dir():
            continue
        chart_files = collect_processed_chart_files(
            chart_dir,
            file_match_token=file_match_token,
            chart_type=chart_type,
        )
        for path in chart_files:
            keys = terminal_area_lookup_keys_for_file(path, chart_type=chart_type)
            for key in keys:
                for variant in terminal_area_lookup_variants(key):
                    if variant not in by_key:
                        by_key[variant] = []
                        seen_by_key[variant] = set()
                    if path in seen_by_key[variant]:
                        continue
                    seen_by_key[variant].add(path)
                    by_key[variant].append(path)

    for values in by_key.values():
        values.sort(key=lambda item: str(item).lower())
    return by_key


def load_region_mapping(mapping_json: Path, *, chart_type: str) -> dict[str, list[str]]:
    if chart_type not in MAPPING_KEY_BY_CHART_TYPE:
        raise ValueError(f"Unsupported chart type for region mapping: {chart_type}")

    payload = json.loads(mapping_json.read_text(encoding="utf-8"))
    mapping_key = MAPPING_KEY_BY_CHART_TYPE[chart_type]
    mapping = payload.get(mapping_key)
    if not isinstance(mapping, dict):
        raise ValueError(f"Mapping JSON missing .{mapping_key} object")

    regions: dict[str, list[str]] = {}
    for region, charts in mapping.items():
        if not isinstance(region, str):
            raise ValueError(f"Region key must be a string under .{mapping_key}")
        if not isinstance(charts, list) or not all(isinstance(item, str) for item in charts):
            raise ValueError(f"Region {region!r} under .{mapping_key} must be a list of chart names")
        regions[region] = charts
    return regions


def build_region_mosaics(
    *,
    mapping_json: Path,
    processed_root: Path,
    output_dir: Path,
    file_match_token: str,
    chart_type: str,
    dry_run: bool,
) -> None:
    if chart_type not in CHART_TYPES:
        raise ValueError(f"Unsupported chart type: {chart_type}")
    if chart_type not in MAPPING_KEY_BY_CHART_TYPE:
        raise ValueError(f"Unsupported chart type for mosaic mapping: {chart_type}")
    if not mapping_json.is_file():
        raise FileNotFoundError(f"Mapping JSON not found: {mapping_json}")
    if not processed_root.is_dir():
        raise FileNotFoundError(f"Processed chart root not found: {processed_root}")

    output_dir.mkdir(parents=True, exist_ok=True)
    if not dry_run and shutil.which("gdal") is None:
        raise FileNotFoundError("gdal command not found")

    region_mapping = load_region_mapping(mapping_json, chart_type=chart_type)
    chart_dir_by_normalized_name = build_processed_chart_dir_index(processed_root)
    terminal_area_file_index: dict[str, list[Path]] = {}
    if chart_type in (CHART_TYPE_TAC, CHART_TYPE_FLY):
        terminal_area_file_index = build_terminal_area_file_index(
            processed_root,
            file_match_token=file_match_token,
            chart_type=chart_type,
        )

    for region, mapped_charts in region_mapping.items():
        region_inputs: list[Path] = []
        region_seen: set[Path] = set()

        for chart_name in mapped_charts:
            normalized_chart_name = normalize_chart_name(chart_name)
            if chart_type == CHART_TYPE_SECTIONAL:
                chart_dir = chart_dir_by_normalized_name.get(normalized_chart_name)
                if chart_dir is None:
                    warn(
                        f"Sectional chart '{chart_name}' not found under processed charts. "
                        "Skipping."
                    )
                    continue
                chart_files = collect_processed_chart_files(
                    chart_dir,
                    file_match_token=file_match_token,
                    chart_type=chart_type,
                )
            else:
                chart_files: list[Path] = []
                seen_files: set[Path] = set()
                for key_variant in terminal_area_lookup_variants(normalized_chart_name):
                    for path in terminal_area_file_index.get(key_variant, []):
                        if path in seen_files:
                            continue
                        seen_files.add(path)
                        chart_files.append(path)
                if not chart_files:
                    warn(
                        f"{chart_type.upper()} chart '{chart_name}' not found under processed "
                        "charts. Skipping."
                    )
                    continue

            if not chart_files:
                warn(
                    f"No files matching token '{file_match_token}' found for "
                    f"{chart_type} chart '{chart_name}'."
                )
                continue

            for input_path in chart_files:
                if input_path in region_seen:
                    continue
                region_seen.add(input_path)
                region_inputs.append(input_path)

        if not region_inputs:
            warn(f"Region '{region}' has no resolved inputs. Skipping mosaic creation.")
            continue

        output_vrt = output_dir / f"{chart_type}-{region}-mosaic.clip.jxl.vrt"
        mosaic_cmd = [
            "gdal",
            "raster",
            "mosaic",
            "--resolution",
            "average",
            "--absolute-path",
            "--hide-nodata",
            "--add-alpha",
            "--output-format",
            "VRT",
            "--overwrite",
            *[str(path) for path in region_inputs],
            str(output_vrt),
        ]

        if dry_run:
            print("DRY-RUN: " + " ".join(shlex.quote(token) for token in mosaic_cmd))
            continue

        print(f"Creating mosaic: {output_vrt}")
        subprocess.run(mosaic_cmd, check=True)
        print(f"Wrote: {output_vrt}")
