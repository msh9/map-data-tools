"""Download and extract FAA VFR sectional and TAC chart packages."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import json
from pathlib import Path
import re
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
import urllib.request
import zipfile

VISUAL_ROOT_URL = "https://aeronav.faa.gov/visual/"
CHART_TYPE_SECTIONAL = "sectional"
CHART_TYPE_TAC = "tac"
CHART_TYPES = (CHART_TYPE_SECTIONAL, CHART_TYPE_TAC)
CYCLE_PATTERN = re.compile(r"^\d{2}-\d{2}-\d{4}$")
HREF_PATTERN = re.compile(r"href\s*=\s*[\"']?([^\"'\s>]+)", re.IGNORECASE)
USER_AGENT = "flyer-maps-faa-vfr-fetch/0.1"

CHART_TYPE_SUBDIR = {
    CHART_TYPE_SECTIONAL: "sectional-files",
    CHART_TYPE_TAC: "tac-files",
}

PUBLISHED_SET_FILE = {
    CHART_TYPE_SECTIONAL: "Sectional.zip",
    CHART_TYPE_TAC: "Terminal.zip",
}


@dataclass(frozen=True)
class PackageSpec:
    chart_type: str
    cycle: str
    zip_name: str
    url: str
    folder_name: str


@dataclass(frozen=True)
class PackageResult:
    spec: PackageSpec
    zip_path: Path
    status: str
    downloaded: bool
    extracted_files: int
    size_bytes: int | None
    content_length: int | None
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class FetchSummary:
    cycle: str
    chart_types: tuple[str, ...]
    package_results: tuple[PackageResult, ...]
    manifest_path: Path

    @property
    def package_count(self) -> int:
        return len(self.package_results)

    @property
    def downloaded_count(self) -> int:
        return sum(1 for result in self.package_results if result.downloaded)

    @property
    def skipped_count(self) -> int:
        return sum(1 for result in self.package_results if result.status == "skipped-existing")


TextFetcher = Callable[[str, int], str]
UrlExistsChecker = Callable[[str, int], bool]
Downloader = Callable[[str, Path, int], dict[str, object]]


def default_output_dir(start: Path | None = None) -> Path:
    start_path = (start or Path(__file__)).resolve()
    for ancestor in (start_path, *start_path.parents):
        candidate = ancestor / "tilemaker" / "raster-tilemaker" / "data" / "raw"
        if candidate.is_dir():
            return candidate
    return Path("tilemaker/raster-tilemaker/data/raw").resolve()


def normalize_chart_types(chart_types: list[str] | None) -> list[str]:
    if not chart_types:
        return list(CHART_TYPES)

    normalized: list[str] = []
    seen: set[str] = set()
    for chart_type in chart_types:
        lowered = chart_type.lower().strip()
        if lowered not in CHART_TYPES:
            expected = ", ".join(CHART_TYPES)
            raise ValueError(f"Unsupported chart type: {chart_type!r}. Expected one of: {expected}.")
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(lowered)
    return normalized


def fetch_text(url: str, timeout_seconds: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8", errors="replace")


def url_exists(url: str, timeout_seconds: int) -> bool:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return 200 <= response.status < 400
    except HTTPError as exc:
        if exc.code in (405, 501):
            fallback = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(fallback, timeout=timeout_seconds) as response:
                    return 200 <= response.status < 400
            except (HTTPError, URLError):
                return False
        return False
    except URLError:
        return False


def extract_hrefs(html: str) -> list[str]:
    return [match.group(1).strip() for match in HREF_PATTERN.finditer(html)]


def parse_cycle_date(cycle: str) -> dt.date:
    return dt.datetime.strptime(cycle, "%m-%d-%Y").date()


def extract_cycle_directories(html: str) -> list[str]:
    cycles: set[str] = set()
    for href in extract_hrefs(html):
        path = urlparse(href).path.strip("/")
        for part in path.split("/"):
            if CYCLE_PATTERN.fullmatch(part):
                cycles.add(part)

    return sorted(cycles, key=parse_cycle_date)


def cycle_is_published(cycle: str, exists_checker: UrlExistsChecker, timeout_seconds: int) -> bool:
    for chart_type in CHART_TYPES:
        package_file = PUBLISHED_SET_FILE[chart_type]
        all_files_url = f"{VISUAL_ROOT_URL}{cycle}/All_Files/{package_file}"
        if not exists_checker(all_files_url, timeout_seconds):
            return False
    return True


def discover_latest_cycle(
    text_fetcher: TextFetcher,
    exists_checker: UrlExistsChecker,
    timeout_seconds: int,
) -> str:
    html = text_fetcher(VISUAL_ROOT_URL, timeout_seconds)
    cycles = extract_cycle_directories(html)
    if not cycles:
        raise ValueError("Unable to discover FAA visual chart cycles.")

    for cycle in sorted(cycles, key=parse_cycle_date, reverse=True):
        if cycle_is_published(cycle, exists_checker, timeout_seconds):
            return cycle

    raise ValueError("Unable to find a published FAA visual chart cycle with sectional and TAC sets.")


def extract_zip_urls(index_url: str, index_html: str) -> list[str]:
    discovered: dict[str, str] = {}
    for href in extract_hrefs(index_html):
        absolute_url = urljoin(index_url, href)
        path = urlparse(absolute_url).path
        if not path.lower().endswith(".zip"):
            continue
        zip_name = Path(path).name
        discovered[zip_name] = absolute_url

    return [discovered[name] for name in sorted(discovered)]


def list_packages_for_cycle(
    cycle: str,
    chart_types: list[str],
    text_fetcher: TextFetcher,
    timeout_seconds: int,
) -> list[PackageSpec]:
    packages: list[PackageSpec] = []

    for chart_type in chart_types:
        subdir = CHART_TYPE_SUBDIR[chart_type]
        index_url = f"{VISUAL_ROOT_URL}{cycle}/{subdir}/"
        html = text_fetcher(index_url, timeout_seconds)
        zip_urls = extract_zip_urls(index_url, html)
        if not zip_urls:
            raise ValueError(f"No zip packages found for {chart_type} at {index_url}")

        for package_url in zip_urls:
            zip_name = Path(urlparse(package_url).path).name
            folder_name = Path(zip_name).stem
            packages.append(
                PackageSpec(
                    chart_type=chart_type,
                    cycle=cycle,
                    zip_name=zip_name,
                    url=package_url,
                    folder_name=folder_name,
                )
            )

    packages.sort(key=lambda package: (package.chart_type, package.folder_name))
    return packages


def download_to_file(url: str, destination: Path, timeout_seconds: int) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(destination.suffix + ".tmp")

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    bytes_written = 0
    headers: dict[str, str] = {}

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            with temporary_path.open("wb") as output_file:
                while chunk := response.read(1024 * 1024):
                    output_file.write(chunk)
                    bytes_written += len(chunk)
        temporary_path.replace(destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    return {"bytes_written": bytes_written, "headers": headers}


def safe_extract_zip(zip_path: Path, destination_dir: Path) -> int:
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_root = destination_dir.resolve()
    extracted_file_count = 0

    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            destination = (destination_dir / member.filename).resolve()
            try:
                destination.relative_to(destination_root)
            except ValueError as exc:
                raise ValueError(f"Unsafe zip entry path: {member.filename}") from exc

            archive.extract(member, destination_dir)
            if not member.is_dir():
                extracted_file_count += 1

    return extracted_file_count


def parse_optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def write_manifest(
    output_dir: Path,
    cycle: str,
    chart_types: list[str],
    package_results: list[PackageResult],
) -> Path:
    manifest_path = output_dir / f"faa-vfr-fetch-manifest-{cycle}.json"
    payload = {
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "cycle": cycle,
        "chart_types": chart_types,
        "source": {"visual_root_url": VISUAL_ROOT_URL},
        "package_count": len(package_results),
        "downloaded_count": sum(1 for result in package_results if result.downloaded),
        "skipped_count": sum(1 for result in package_results if result.status == "skipped-existing"),
        "packages": [
            {
                "chart_type": result.spec.chart_type,
                "zip_name": result.spec.zip_name,
                "folder_name": result.spec.folder_name,
                "url": result.spec.url,
                "zip_path": str(result.zip_path.relative_to(output_dir)),
                "status": result.status,
                "downloaded": result.downloaded,
                "extracted_files": result.extracted_files,
                "size_bytes": result.size_bytes,
                "content_length": result.content_length,
                "etag": result.etag,
                "last_modified": result.last_modified,
            }
            for result in package_results
        ],
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def fetch_vfr_packages(
    *,
    output_dir: Path,
    cycle: str = "auto",
    chart_types: list[str] | None = None,
    skip_existing: bool = True,
    extract: bool = True,
    timeout_seconds: int = 60,
    dry_run: bool = False,
    text_fetcher: TextFetcher = fetch_text,
    exists_checker: UrlExistsChecker = url_exists,
    downloader: Downloader = download_to_file,
) -> FetchSummary:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")

    selected_chart_types = normalize_chart_types(chart_types)
    selected_cycle = cycle
    if cycle == "auto":
        selected_cycle = discover_latest_cycle(text_fetcher, exists_checker, timeout_seconds)
    elif not CYCLE_PATTERN.fullmatch(cycle):
        raise ValueError("cycle must be in MM-DD-YYYY format or set to 'auto'.")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    packages = list_packages_for_cycle(
        selected_cycle,
        selected_chart_types,
        text_fetcher,
        timeout_seconds,
    )

    package_results: list[PackageResult] = []
    for package in packages:
        chart_dir = output_dir / package.folder_name
        zip_path = chart_dir / package.zip_name
        chart_dir.mkdir(parents=True, exist_ok=True)

        status = "dry-run"
        downloaded = False
        extracted_files = 0
        headers: dict[str, object] = {}

        can_skip_existing = (
            skip_existing and zip_path.exists() and zip_path.stat().st_size > 0 and not dry_run
        )
        if can_skip_existing:
            status = "skipped-existing"
        elif dry_run:
            status = "dry-run"
        else:
            transfer = downloader(package.url, zip_path, timeout_seconds)
            headers = transfer.get("headers", {}) if isinstance(transfer, dict) else {}
            status = "downloaded"
            downloaded = True

        if extract and zip_path.exists() and not dry_run:
            extracted_files = safe_extract_zip(zip_path, chart_dir)

        package_results.append(
            PackageResult(
                spec=package,
                zip_path=zip_path,
                status=status,
                downloaded=downloaded,
                extracted_files=extracted_files,
                size_bytes=zip_path.stat().st_size if zip_path.exists() else None,
                content_length=parse_optional_int(headers.get("content-length")),
                etag=(headers.get("etag") if isinstance(headers.get("etag"), str) else None),
                last_modified=(
                    headers.get("last-modified")
                    if isinstance(headers.get("last-modified"), str)
                    else None
                ),
            )
        )

    manifest_path = write_manifest(output_dir, selected_cycle, selected_chart_types, package_results)
    return FetchSummary(
        cycle=selected_cycle,
        chart_types=tuple(selected_chart_types),
        package_results=tuple(package_results),
        manifest_path=manifest_path,
    )
