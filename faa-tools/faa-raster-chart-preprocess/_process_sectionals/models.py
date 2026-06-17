from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChartEntry:
    tif_path: Path
    chart_type: str
    coverage_key: str


@dataclass(frozen=True)
class ChartSource:
    chart_name: str
    normalized_chart_name: str
    entries: tuple[ChartEntry, ...]


@dataclass(frozen=True)
class ChartJob:
    source: ChartSource
    entry: ChartEntry
    coverage_path: Path
    chart_output_dir: Path
    full_output_path: Path
    clipped_output_path: Path


@dataclass(frozen=True)
class RunResult:
    processed_jobs: tuple[ChartJob, ...]
    failed_messages: tuple[str, ...]
