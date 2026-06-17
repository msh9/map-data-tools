from __future__ import annotations

from pathlib import Path

from faa_vfr_fetch import fetch_vfr
from faa_vfr_fetch.cli import main


def test_cli_prints_help_without_command(capsys):
    exit_code = main([])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "FAA VFR chart fetch utility" in captured.out


def test_cli_fetch_passes_arguments_to_fetcher(tmp_path: Path, capsys, monkeypatch):
    calls: dict[str, object] = {}

    def fake_fetch_vfr_packages(**kwargs):
        calls.update(kwargs)
        spec = fetch_vfr.PackageSpec(
            chart_type="sectional",
            cycle="01-22-2026",
            zip_name="Denver.zip",
            url="https://example.invalid/Denver.zip",
            folder_name="Denver",
        )
        result = fetch_vfr.PackageResult(
            spec=spec,
            zip_path=tmp_path / "Denver" / "Denver.zip",
            status="downloaded",
            downloaded=True,
            extracted_files=2,
            size_bytes=123,
            content_length=123,
            etag=None,
            last_modified=None,
        )
        return fetch_vfr.FetchSummary(
            cycle="01-22-2026",
            chart_types=("sectional",),
            package_results=(result,),
            manifest_path=tmp_path / "manifest.json",
        )

    monkeypatch.setattr(fetch_vfr, "fetch_vfr_packages", fake_fetch_vfr_packages)

    exit_code = main(
        [
            "fetch",
            "--cycle",
            "01-22-2026",
            "--chart-type",
            "sectional",
            "--output-dir",
            str(tmp_path),
            "--force",
            "--no-extract",
            "--timeout-seconds",
            "30",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert calls["cycle"] == "01-22-2026"
    assert calls["chart_types"] == ["sectional"]
    assert calls["output_dir"] == tmp_path
    assert calls["skip_existing"] is False
    assert calls["extract"] is False
    assert calls["timeout_seconds"] == 30
    assert "Cycle: 01-22-2026" in captured.out
    assert "Fetched 1 package(s): 1 downloaded, 0 skipped." in captured.out
