from __future__ import annotations

import re
from pathlib import Path


def parse_html_metadata(html_text: str) -> dict[str, str]:
    def match_value(pattern: str) -> str | None:
        match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        return " ".join(match.group(1).split())

    metadata: dict[str, str] = {}
    meta_map = {
        "Originator": r'<meta name="dc\.creator" content="([^"]+)"',
        "Publication_Date": r'<meta name="dc\.date" content="([^"]+)"',
    }
    for key, pattern in meta_map.items():
        value = match_value(pattern)
        if value:
            metadata[key] = value

    body_map = {
        "Originator": r"Originator:</em>\s*<dd>\s*(.*?)\s*</dd>",
        "Publication_Date": r"Publication_Date:</em>\s*([^<]+)</dt>",
        "Series_Name": r"Series_Name:</em>\s*([^<]+)</dt>",
    }
    for key, pattern in body_map.items():
        value = match_value(pattern)
        if value:
            metadata[key] = value

    return metadata


def parse_html_coverage_bounds(html_text: str) -> tuple[float, float, float, float] | None:
    def match_value(pattern: str) -> str | None:
        match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        return " ".join(match.group(1).split())

    meta_map = {
        "min_lon": r'<meta name="dc\.coverage\.x\.min"[^>]*content="([^"]+)"',
        "max_lon": r'<meta name="dc\.coverage\.x\.max"[^>]*content="([^"]+)"',
        "min_lat": r'<meta name="dc\.coverage\.y\.min"[^>]*content="([^"]+)"',
        "max_lat": r'<meta name="dc\.coverage\.y\.max"[^>]*content="([^"]+)"',
    }
    values = {key: match_value(pattern) for key, pattern in meta_map.items()}

    if any(value is None for value in values.values()):
        body_map = {
            "min_lon": r"West_Bounding_Coordinate:</em>\s*([^<]+)</dt>",
            "max_lon": r"East_Bounding_Coordinate:</em>\s*([^<]+)</dt>",
            "min_lat": r"South_Bounding_Coordinate:</em>\s*([^<]+)</dt>",
            "max_lat": r"North_Bounding_Coordinate:</em>\s*([^<]+)</dt>",
        }
        values = {key: match_value(pattern) for key, pattern in body_map.items()}

    if any(value is None for value in values.values()):
        return None

    min_lon = float(values["min_lon"])
    max_lon = float(values["max_lon"])
    min_lat = float(values["min_lat"])
    max_lat = float(values["max_lat"])
    if min_lon > max_lon:
        min_lon, max_lon = max_lon, min_lon
    if min_lat > max_lat:
        min_lat, max_lat = max_lat, min_lat
    return (min_lon, min_lat, max_lon, max_lat)


def read_sidecar_html(tif_path: Path) -> str | None:
    html_path = tif_path.with_suffix(".htm")
    if html_path.exists():
        return html_path.read_text(encoding="utf-8", errors="ignore")
    return None
