from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

from faa_vfr_fetch.fetch_vfr import (
    VISUAL_ROOT_URL,
    discover_latest_cycle,
    extract_cycle_directories,
    extract_zip_urls,
    fetch_vfr_packages,
)


def build_zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        for file_path, content in files.items():
            archive.writestr(file_path, content)
    return buffer.getvalue()


def test_extract_cycle_directories_reads_visual_index_entries():
    html = """
    <a href="/visual/10-02-2025/">10-02-2025</a>
    <a href="/visual/01-22-2026/">01-22-2026</a>
    <a href="/visual/03-19-2026/">03-19-2026</a>
    """

    assert extract_cycle_directories(html) == ["10-02-2025", "01-22-2026", "03-19-2026"]


def test_discover_latest_cycle_returns_newest_published_cycle():
    html = """
    <a href="/visual/01-22-2026/">01-22-2026</a>
    <a href="/visual/03-19-2026/">03-19-2026</a>
    """

    def fake_fetch_text(url: str, _timeout_seconds: int) -> str:
        assert url == VISUAL_ROOT_URL
        return html

    def fake_exists(url: str, _timeout_seconds: int) -> bool:
        return "/01-22-2026/" in url

    assert discover_latest_cycle(fake_fetch_text, fake_exists, timeout_seconds=5) == "01-22-2026"


def test_extract_zip_urls_supports_relative_and_absolute_links():
    index_url = f"{VISUAL_ROOT_URL}01-22-2026/sectional-files/"
    html = """
    <a href="Denver.zip">Denver.zip</a>
    <a href="https://aeronav.faa.gov/visual/01-22-2026/sectional-files/Las_Vegas.zip">Las</a>
    <a href="README.txt">readme</a>
    """

    assert extract_zip_urls(index_url, html) == [
        f"{VISUAL_ROOT_URL}01-22-2026/sectional-files/Denver.zip",
        f"{VISUAL_ROOT_URL}01-22-2026/sectional-files/Las_Vegas.zip",
    ]


def test_fetch_vfr_packages_downloads_extracts_and_writes_manifest(tmp_path: Path):
    cycle = "01-22-2026"
    visual_html = """
    <a href="/visual/01-22-2026/">01-22-2026</a>
    <a href="/visual/03-19-2026/">03-19-2026</a>
    """
    sectional_index_html = """
    <a href="Denver.zip">Denver.zip</a>
    <a href="Las_Vegas.zip">Las_Vegas.zip</a>
    """
    tac_index_html = """
    <a href="Denver_TAC.zip">Denver_TAC.zip</a>
    """

    sections_url = f"{VISUAL_ROOT_URL}{cycle}/sectional-files/"
    tac_url = f"{VISUAL_ROOT_URL}{cycle}/tac-files/"

    def fake_fetch_text(url: str, _timeout_seconds: int) -> str:
        if url == VISUAL_ROOT_URL:
            return visual_html
        if url == sections_url:
            return sectional_index_html
        if url == tac_url:
            return tac_index_html
        raise AssertionError(f"Unexpected URL: {url}")

    def fake_exists(url: str, _timeout_seconds: int) -> bool:
        return f"/{cycle}/All_Files/" in url

    archive_data = {
        f"{sections_url}Denver.zip": build_zip_bytes(
            {
                "Denver SEC.tif": "tif",
                "Denver SEC.htm": "html",
            }
        ),
        f"{sections_url}Las_Vegas.zip": build_zip_bytes(
            {
                "Las Vegas SEC.tif": "tif",
            }
        ),
        f"{tac_url}Denver_TAC.zip": build_zip_bytes(
            {
                "Denver TAC.tif": "tif",
                "Denver FLY.tif": "tif",
            }
        ),
    }

    def fake_downloader(url: str, destination: Path, _timeout_seconds: int) -> dict[str, object]:
        payload = archive_data[url]
        destination.write_bytes(payload)
        return {
            "headers": {
                "content-length": str(len(payload)),
                "etag": "W/fake",
                "last-modified": "Mon, 01 Jan 2026 00:00:00 GMT",
            }
        }

    summary = fetch_vfr_packages(
        output_dir=tmp_path,
        cycle="auto",
        chart_types=["sectional", "tac"],
        skip_existing=True,
        extract=True,
        timeout_seconds=5,
        text_fetcher=fake_fetch_text,
        exists_checker=fake_exists,
        downloader=fake_downloader,
    )

    assert summary.cycle == cycle
    assert summary.package_count == 3
    assert summary.downloaded_count == 3
    assert summary.skipped_count == 0

    assert (tmp_path / "Denver" / "Denver SEC.tif").exists()
    assert (tmp_path / "Las_Vegas" / "Las Vegas SEC.tif").exists()
    assert (tmp_path / "Denver_TAC" / "Denver FLY.tif").exists()

    manifest = json.loads(summary.manifest_path.read_text(encoding="utf-8"))
    assert manifest["cycle"] == cycle
    assert manifest["package_count"] == 3
    assert {entry["zip_path"] for entry in manifest["packages"]} == {
        "Denver/Denver.zip",
        "Las_Vegas/Las_Vegas.zip",
        "Denver_TAC/Denver_TAC.zip",
    }


def test_fetch_vfr_packages_skips_existing_archives(tmp_path: Path):
    cycle = "01-22-2026"
    visual_html = '<a href="/visual/01-22-2026/">01-22-2026</a>'
    sectional_index_html = '<a href="Denver.zip">Denver.zip</a>'
    tac_index_html = '<a href="Denver_TAC.zip">Denver_TAC.zip</a>'

    sections_url = f"{VISUAL_ROOT_URL}{cycle}/sectional-files/"
    tac_url = f"{VISUAL_ROOT_URL}{cycle}/tac-files/"

    def fake_fetch_text(url: str, _timeout_seconds: int) -> str:
        if url == VISUAL_ROOT_URL:
            return visual_html
        if url == sections_url:
            return sectional_index_html
        if url == tac_url:
            return tac_index_html
        raise AssertionError(f"Unexpected URL: {url}")

    def fake_exists(url: str, _timeout_seconds: int) -> bool:
        return f"/{cycle}/All_Files/" in url

    archive_data = {
        f"{sections_url}Denver.zip": build_zip_bytes({"Denver SEC.tif": "tif"}),
        f"{tac_url}Denver_TAC.zip": build_zip_bytes({"Denver FLY.tif": "tif"}),
    }

    def fake_downloader(url: str, destination: Path, _timeout_seconds: int) -> dict[str, object]:
        destination.write_bytes(archive_data[url])
        return {"headers": {"content-length": str(len(archive_data[url]))}}

    first_summary = fetch_vfr_packages(
        output_dir=tmp_path,
        cycle="auto",
        chart_types=["sectional", "tac"],
        skip_existing=True,
        extract=True,
        timeout_seconds=5,
        text_fetcher=fake_fetch_text,
        exists_checker=fake_exists,
        downloader=fake_downloader,
    )
    assert first_summary.downloaded_count == 2

    def fail_downloader(_url: str, _destination: Path, _timeout_seconds: int) -> dict[str, object]:
        raise AssertionError("Downloader should not be called when archives already exist.")

    second_summary = fetch_vfr_packages(
        output_dir=tmp_path,
        cycle="auto",
        chart_types=["sectional", "tac"],
        skip_existing=True,
        extract=True,
        timeout_seconds=5,
        text_fetcher=fake_fetch_text,
        exists_checker=fake_exists,
        downloader=fail_downloader,
    )

    assert second_summary.downloaded_count == 0
    assert second_summary.skipped_count == 2
    assert (tmp_path / "Denver" / "Denver SEC.tif").exists()
    assert (tmp_path / "Denver_TAC" / "Denver FLY.tif").exists()
