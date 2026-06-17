from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Sequence

from _process_sectionals.constants import (
    CHART_TYPE_FLY,
    CHART_TYPE_SECTIONAL,
    CHART_TYPE_TAC,
    CLIPPED_CHART_COG_OPTIONS_JXL_LOSSLESS,
    CLIPPED_CHART_COG_OPTIONS_ZSTD,
    CLIPPED_OUTPUT_MODE_JXL_LOSSLESS,
    CLIPPED_OUTPUT_MODE_ZSTD,
    DEFAULT_CLIPPED_OUTPUT_MODE,
    DEFAULT_THREADS,
    FULL_CHART_COG_OPTIONS,
    TARGET_CRS,
)
from _process_sectionals.coverage import (
    build_coverage_index,
    coverage_dir_for_entry,
    coverage_lookup_for_entry,
)
from _process_sectionals.discovery import discover_chart_sources, select_sources
from _process_sectionals.models import ChartEntry, ChartJob, ChartSource, RunResult
from _process_sectionals.naming import slugify

_GDAL = None


def load_gdal():
    from osgeo import gdal as gdal_module

    gdal_module.UseExceptions()
    return gdal_module


def get_gdal():
    if _GDAL is None:
        raise RuntimeError("GDAL runtime is not initialized.")
    return _GDAL


def log_stage(message: str, *, verbose: bool) -> None:
    if verbose:
        print(message)


def warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


def clipped_output_suffix(clipped_output_mode: str) -> str:
    if clipped_output_mode == CLIPPED_OUTPUT_MODE_ZSTD:
        return "clip.zstd.cog.tif"
    if clipped_output_mode == CLIPPED_OUTPUT_MODE_JXL_LOSSLESS:
        return "clip.jxl.cog.tif"
    raise ValueError(f"Unsupported clipped output mode: {clipped_output_mode}")


def clipped_cog_options(clipped_output_mode: str) -> list[str]:
    if clipped_output_mode == CLIPPED_OUTPUT_MODE_ZSTD:
        return list(CLIPPED_CHART_COG_OPTIONS_ZSTD)
    if clipped_output_mode == CLIPPED_OUTPUT_MODE_JXL_LOSSLESS:
        return list(CLIPPED_CHART_COG_OPTIONS_JXL_LOSSLESS)
    raise ValueError(f"Unsupported clipped output mode: {clipped_output_mode}")


def creation_options_args(creation_options: Sequence[str]) -> str:
    parts: list[str] = []
    for option in creation_options:
        parts.append("--co")
        parts.append(shlex.quote(option))
    return " ".join(parts)


def output_prefix(source: ChartSource, entry: ChartEntry) -> str:
    chart_slug = slugify(source.chart_name)
    if len(source.entries) == 1:
        prefix = chart_slug
    else:
        source_slug = slugify(entry.tif_path.stem)
        prefix = f"{chart_slug}--{source_slug}"

    if entry.chart_type in (CHART_TYPE_TAC, CHART_TYPE_FLY):
        prefix = f"{prefix}.{entry.chart_type}"
    return prefix


def build_pipeline(job: ChartJob, *, clipped_output_mode: str, threads: int) -> str:
    pipeline_stage_a = (
        "read "
        "! color-map --add-alpha --color-selection exact "
        f"! reproject --dst-crs={TARGET_CRS} --resampling=cubic --num-threads={threads} "
    )
    full_options = [*FULL_CHART_COG_OPTIONS, f"NUM_THREADS={threads}"]
    clipped_options = [*clipped_cog_options(clipped_output_mode), f"NUM_THREADS={threads}"]
    full_write_pipeline = (
        "write --output-format=COG "
        f"{creation_options_args(full_options)} "
        f"--overwrite {shlex.quote(str(job.full_output_path))}"
    )
    clipped_write_pipeline = (
        "write --output-format=COG "
        f"{creation_options_args(clipped_options)} "
        f"--overwrite {shlex.quote(str(job.clipped_output_path))}"
    )
    return (
        f"{pipeline_stage_a}"
        f"! tee [ {full_write_pipeline} ] "
        f"! clip --like {shlex.quote(str(job.coverage_path))} "
        f"! {clipped_write_pipeline}"
    )


def process_job(
    job: ChartJob,
    *,
    clipped_output_mode: str = DEFAULT_CLIPPED_OUTPUT_MODE,
    threads: int = DEFAULT_THREADS,
    verbose: bool = False,
) -> None:
    gdal = get_gdal()
    pipeline = build_pipeline(job, clipped_output_mode=clipped_output_mode, threads=threads)
    log_stage(
        f"  Stage A start: color-map + reproject ({job.entry.tif_path.name})",
        verbose=verbose,
    )
    log_stage(
        f"  Stage B start: tee write full WEBP COG ({job.full_output_path.name})",
        verbose=verbose,
    )
    log_stage(
        f"  Stage C start: clip + write COG ({job.clipped_output_path.name})",
        verbose=verbose,
    )
    if verbose:
        print(f"  Pipeline: {pipeline}")
    job.chart_output_dir.mkdir(parents=True, exist_ok=True)
    job.full_output_path.unlink(missing_ok=True)
    job.clipped_output_path.unlink(missing_ok=True)
    with gdal.Run(
        "raster",
        "pipeline",
        input=[str(job.entry.tif_path)],
        pipeline=pipeline,
    ):
        pass
    log_stage(f"  Stage A complete: {job.entry.tif_path.name}", verbose=verbose)
    log_stage(f"  Stage B complete: {job.full_output_path.name}", verbose=verbose)
    log_stage(f"  Stage C complete: {job.clipped_output_path.name}", verbose=verbose)


def build_jobs(
    selected_sources: Sequence[ChartSource],
    *,
    sectional_coverage_index: dict[str, Path],
    tac_fly_coverage_index: dict[str, Path],
    sectional_coverage_dir: Path,
    tac_fly_coverage_dir: Path,
    output_root: Path,
    clipped_output_mode: str,
    continue_on_error: bool,
) -> tuple[list[ChartJob], list[str]]:
    jobs: list[ChartJob] = []
    failures: list[str] = []

    for source in selected_sources:
        chart_output_dir = output_root / source.chart_name
        for entry in source.entries:
            coverage_path = coverage_lookup_for_entry(
                entry,
                sectional_coverage_index=sectional_coverage_index,
                tac_fly_coverage_index=tac_fly_coverage_index,
            )
            if coverage_path is None:
                coverage_dir = coverage_dir_for_entry(
                    entry,
                    sectional_coverage_dir=sectional_coverage_dir,
                    tac_fly_coverage_dir=tac_fly_coverage_dir,
                )
                message = (
                    f"Missing {entry.chart_type} coverage GeoJSON for {source.chart_name} "
                    f"({entry.tif_path.name}). Expected under {coverage_dir}."
                )
                if continue_on_error:
                    failures.append(message)
                    continue
                raise FileNotFoundError(message)

            prefix = output_prefix(source, entry)
            full_output_path = chart_output_dir / f"{prefix}.webp.cog.tif"
            clipped_output_path = chart_output_dir / (
                f"{prefix}.{clipped_output_suffix(clipped_output_mode)}"
            )
            jobs.append(
                ChartJob(
                    source=source,
                    entry=entry,
                    coverage_path=coverage_path,
                    chart_output_dir=chart_output_dir,
                    full_output_path=full_output_path,
                    clipped_output_path=clipped_output_path,
                )
            )

    return jobs, failures


def run(
    *,
    raw_charts_dir: Path,
    sectional_coverage_dir: Path,
    tac_fly_coverage_dir: Path,
    output_root: Path,
    requested_charts: Sequence[str] | None,
    all_charts: bool,
    chart_types: Sequence[str],
    clipped_output_mode: str = DEFAULT_CLIPPED_OUTPUT_MODE,
    threads: int = DEFAULT_THREADS,
    verbose: bool = False,
    continue_on_error: bool = False,
) -> RunResult:
    if threads < 1:
        raise ValueError(f"Thread count must be >= 1, got: {threads}")

    global _GDAL
    _GDAL = load_gdal()
    print(f"GDAL runtime: {_GDAL.VersionInfo('--version')}")
    print(f"GDAL module path: {Path(_GDAL.__file__).resolve()}")

    selected_chart_types = set(chart_types)
    discovered_sources = discover_chart_sources(
        raw_charts_dir,
        chart_types=selected_chart_types,
    )
    selected_sources = select_sources(
        discovered_sources,
        requested_charts=requested_charts,
        all_charts=all_charts,
    )

    has_sectional = any(
        entry.chart_type == CHART_TYPE_SECTIONAL
        for source in selected_sources
        for entry in source.entries
    )
    has_tac_or_fly = any(
        entry.chart_type in (CHART_TYPE_TAC, CHART_TYPE_FLY)
        for source in selected_sources
        for entry in source.entries
    )

    sectional_coverage_index: dict[str, Path] = {}
    if has_sectional:
        sectional_coverage_index = build_coverage_index(sectional_coverage_dir)

    tac_fly_coverage_index: dict[str, Path] = {}
    if has_tac_or_fly:
        tac_fly_coverage_index = build_coverage_index(tac_fly_coverage_dir)

    jobs, failures = build_jobs(
        selected_sources,
        sectional_coverage_index=sectional_coverage_index,
        tac_fly_coverage_index=tac_fly_coverage_index,
        sectional_coverage_dir=sectional_coverage_dir,
        tac_fly_coverage_dir=tac_fly_coverage_dir,
        output_root=output_root,
        clipped_output_mode=clipped_output_mode,
        continue_on_error=continue_on_error,
    )

    processed_jobs: list[ChartJob] = []
    for job in jobs:
        print(f"Processing {job.source.chart_name} [{job.entry.chart_type}]: {job.entry.tif_path}")
        try:
            process_job(
                job,
                clipped_output_mode=clipped_output_mode,
                threads=threads,
                verbose=verbose,
            )
        except Exception as exc:
            message = (
                f"Failed processing {job.source.chart_name} ({job.entry.tif_path.name}): {exc}"
            )
            failures.append(message)
            print(f"  Error: {exc}")
            if continue_on_error:
                continue
            raise
        print(f"  wrote {job.full_output_path}")
        print(f"  wrote {job.clipped_output_path}")
        processed_jobs.append(job)

    print(f"Processed {len(processed_jobs)} source file(s); {len(failures)} failure(s).")
    if failures:
        print("Failures:")
        for failure in failures:
            print(f"  - {failure}")
    return RunResult(
        processed_jobs=tuple(processed_jobs),
        failed_messages=tuple(failures),
    )
