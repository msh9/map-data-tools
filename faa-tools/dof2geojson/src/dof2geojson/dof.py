"""FAA Digital Obstacle File (DOF) format parsing."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Collection, TextIO

FEET_TO_METERS = 0.3048
RECORD_LINE_PATTERN = re.compile(r"^[A-Z0-9]{2}-[A-Z0-9]{6}")
STATE_FILE_PATTERN = re.compile(r"^\d{2}-[A-Z]{2}\.DAT$", re.IGNORECASE)

LIGHTING_TYPES = {
    "R": "Red",
    "D": "Dual Red and Medium Intensity White Strobe",
    "H": "High Intensity White",
    "M": "Medium Intensity White",
    "S": "Dual Medium Intensity White Strobe and Red",
    "F": "Flood",
    "C": "Dual Red and High Intensity White",
    "W": "Synchronized Red Lighting",
    "L": "Lighted (Type Unknown)",
    "N": "Unlighted",
}

HORIZONTAL_ACCURACY = {
    "1": ("+/- 20 ft", 20),
    "2": ("+/- 50 ft", 50),
    "3": ("+/- 100 ft", 100),
    "4": ("+/- 500 ft", 500),
    "5": ("+/- 1,000 ft", 1000),
    "6": ("+/- 2,000 ft", 2000),
    "7": ("+/- 1/2 NM", None),
    "8": ("+/- 1 NM", None),
    "9": ("Unknown", None),
}

VERTICAL_ACCURACY = {
    "A": ("+/- 3 ft", 3),
    "B": ("+/- 10 ft", 10),
    "C": ("+/- 20 ft", 20),
    "D": ("+/- 50 ft", 50),
    "E": ("+/- 125 ft", 125),
    "F": ("+/- 250 ft", 250),
    "G": ("+/- 500 ft", 500),
    "H": ("+/- 1,000 ft", 1000),
    "I": ("Unknown", None),
}

VERIFICATION_STATUS = {
    "O": "Verified",
    "U": "Unverified",
}

MARK_INDICATOR = {
    "M": "Marked",
    "P": "Orange or Orange and White Paint",
    "F": "Flag Marker",
    "L": "High Visibility Markers",
    "R": "Spherical Markers",
    "W": "High Visibility Spherical Markers",
    "K": "Marked and Lighted",
}


@dataclass(frozen=True)
class DOFObstacleRecord:
    """Parsed FAA DOF obstacle record."""

    line_number: int
    oas_code: str
    obstacle_number: str
    verification_status_code: str
    country_identifier: str
    state_identifier: str | None
    city_name: str | None
    latitude: float
    longitude: float
    obstacle_type: str
    quantity: int | None
    agl_height_ft: int
    amsl_height_ft: int
    lighting_code: str
    horizontal_accuracy_code: str
    vertical_accuracy_code: str
    mark_indicator_code: str
    faa_study_number: str | None
    action: str
    julian_date: str

    def to_normalized_dict(self) -> dict[str, object]:
        """Return normalized obstacle data for downstream GeoJSON output."""
        horizontal_desc, horizontal_ft = decode_horizontal_accuracy(self.horizontal_accuracy_code)
        vertical_desc, vertical_ft = decode_vertical_accuracy(self.vertical_accuracy_code)
        lighting_desc = decode_lighting(self.lighting_code)
        verification_desc = decode_verification_status(self.verification_status_code)
        mark_desc = decode_mark_indicator(self.mark_indicator_code)

        return {
            "obstacle_id": f"{self.oas_code}-{self.obstacle_number}",
            "source": {"line_number": self.line_number},
            "country_identifier": self.country_identifier,
            "state_identifier": self.state_identifier,
            "city_name": self.city_name,
            "location": {
                "latitude": self.latitude,
                "longitude": self.longitude,
            },
            "obstacle_type": self.obstacle_type,
            "quantity": self.quantity,
            "heights": {
                "agl": {
                    "feet": self.agl_height_ft,
                    "meters": feet_to_meters(self.agl_height_ft),
                },
                "amsl": {
                    "feet": self.amsl_height_ft,
                    "meters": feet_to_meters(self.amsl_height_ft),
                },
            },
            "lighting": {
                "code": self.lighting_code,
                "description": lighting_desc,
            },
            "horizontal_accuracy": {
                "code": self.horizontal_accuracy_code,
                "description": horizontal_desc,
                "feet": horizontal_ft,
                "meters": feet_to_meters(horizontal_ft),
            },
            "vertical_accuracy": {
                "code": self.vertical_accuracy_code,
                "description": vertical_desc,
                "feet": vertical_ft,
                "meters": feet_to_meters(vertical_ft),
            },
            "verification_status": {
                "code": self.verification_status_code,
                "description": verification_desc,
            },
            "mark_indicator": {
                "code": self.mark_indicator_code,
                "description": mark_desc,
            },
            "faa_study_number": self.faa_study_number,
            "action": self.action,
            "julian_date": self.julian_date,
        }


@dataclass
class ParseSummary:
    """Parsing summary and optional in-memory records."""

    file_count: int = 0
    scanned_record_lines: int = 0
    parsed_count: int = 0
    skipped_by_state_count: int = 0
    error_count: int = 0
    records: list[DOFObstacleRecord] = field(default_factory=list)


def decode_lighting(code: str) -> str:
    return LIGHTING_TYPES.get(code.upper(), "Unknown")


def decode_horizontal_accuracy(code: str) -> tuple[str, int | None]:
    return HORIZONTAL_ACCURACY.get(code.upper(), ("Unknown", None))


def decode_vertical_accuracy(code: str) -> tuple[str, int | None]:
    return VERTICAL_ACCURACY.get(code.upper(), ("Unknown", None))


def decode_verification_status(code: str) -> str:
    return VERIFICATION_STATUS.get(code.upper(), "Unknown")


def decode_mark_indicator(code: str) -> str:
    return MARK_INDICATOR.get(code.upper(), "Unknown")


def feet_to_meters(value: int | None) -> float | None:
    if value is None:
        return None
    return round(value * FEET_TO_METERS, 3)


def parse_coordinate(
    degrees_text: str, minutes_text: str, seconds_text: str, hemisphere: str, axis: str
) -> float:
    try:
        degrees = int(degrees_text)
        minutes = int(minutes_text)
        seconds = float(seconds_text)
    except ValueError as exc:
        raise ValueError(f"invalid {axis} coordinate numeric component") from exc

    if minutes < 0 or minutes >= 60:
        raise ValueError(f"{axis} minutes must be in [0, 59]")
    if seconds < 0 or seconds >= 60:
        raise ValueError(f"{axis} seconds must be in [0, 60)")

    normalized_hemi = hemisphere.upper()
    if axis == "lat":
        if degrees < 0 or degrees > 90:
            raise ValueError("lat degrees must be in [0, 90]")
        if normalized_hemi not in {"N", "S"}:
            raise ValueError("lat hemisphere must be N or S")
    elif axis == "lon":
        if degrees < 0 or degrees > 180:
            raise ValueError("lon degrees must be in [0, 180]")
        if normalized_hemi not in {"E", "W"}:
            raise ValueError("lon hemisphere must be E or W")
    else:
        raise ValueError(f"unsupported axis: {axis}")

    decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)
    if normalized_hemi in {"S", "W"}:
        decimal = -decimal
    return round(decimal, 8)


def required_int(line: str, start: int, end: int, field_name: str) -> int:
    text = required_text(line, start, end, field_name)
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def optional_int(line: str, start: int, end: int, field_name: str) -> int | None:
    text = optional_text(line, start, end)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer when present") from exc


def required_text(line: str, start: int, end: int, field_name: str) -> str:
    text = slice_text(line, start, end).strip()
    if not text:
        raise ValueError(f"missing {field_name}")
    return text


def optional_text(line: str, start: int, end: int) -> str | None:
    text = slice_text(line, start, end).strip()
    if not text:
        return None
    return text


def slice_text(line: str, start: int, end: int) -> str:
    if end > len(line):
        raise ValueError(f"line shorter than expected field ending at column {end}")
    return line[start - 1 : end]


def is_record_line(line: str) -> bool:
    """Return True when a line appears to contain a DOF obstacle record."""
    return len(line) >= 127 and RECORD_LINE_PATTERN.match(line) is not None


def list_dof_state_files(input_dir: Path) -> list[Path]:
    """Return sorted FAA DOF state files from an archive directory."""
    return sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and STATE_FILE_PATTERN.match(path.name) is not None
    )


def parse_dof_line(line: str, line_number: int) -> DOFObstacleRecord:
    """Parse a fixed-width FAA DOF line."""
    if len(line) < 127:
        raise ValueError(f"record is {len(line)} chars; expected at least 127 chars")
    if line[2] != "-":
        raise ValueError("record separator '-' missing at column 3")

    oas_code = required_text(line, 1, 2, "OAS code")
    obstacle_number = required_text(line, 4, 9, "obstacle number")
    verification_status_code = required_text(line, 11, 11, "verification status").upper()
    country_identifier = required_text(line, 13, 14, "country identifier").upper()
    state_identifier = optional_text(line, 16, 17)
    if country_identifier == "US" and state_identifier is None:
        raise ValueError("missing state identifier for US record")
    if state_identifier is not None:
        state_identifier = state_identifier.upper()
    city_name = optional_text(line, 19, 34)

    latitude = parse_coordinate(
        required_text(line, 36, 37, "latitude degrees"),
        required_text(line, 39, 40, "latitude minutes"),
        required_text(line, 42, 46, "latitude seconds"),
        required_text(line, 47, 47, "latitude hemisphere"),
        axis="lat",
    )
    longitude = parse_coordinate(
        required_text(line, 49, 51, "longitude degrees"),
        required_text(line, 53, 54, "longitude minutes"),
        required_text(line, 56, 60, "longitude seconds"),
        required_text(line, 61, 61, "longitude hemisphere"),
        axis="lon",
    )

    obstacle_type = required_text(line, 63, 80, "obstacle type")
    quantity = optional_int(line, 82, 82, "quantity")
    agl_height_ft = required_int(line, 84, 88, "AGL height")
    amsl_height_ft = required_int(line, 90, 94, "AMSL height")
    lighting_code = (optional_text(line, 96, 96) or "").upper()
    horizontal_accuracy_code = (optional_text(line, 98, 98) or "").upper()
    vertical_accuracy_code = (optional_text(line, 100, 100) or "").upper()
    mark_indicator_code = (optional_text(line, 102, 102) or "").upper()
    faa_study_number = optional_text(line, 104, 117)
    action = required_text(line, 119, 119, "action").upper()
    julian_date = required_text(line, 121, 127, "julian date")
    if not julian_date.isdigit():
        raise ValueError("julian date must be a 7-digit numeric value")

    return DOFObstacleRecord(
        line_number=line_number,
        oas_code=oas_code,
        obstacle_number=obstacle_number,
        verification_status_code=verification_status_code,
        country_identifier=country_identifier,
        state_identifier=state_identifier,
        city_name=city_name,
        latitude=latitude,
        longitude=longitude,
        obstacle_type=obstacle_type,
        quantity=quantity,
        agl_height_ft=agl_height_ft,
        amsl_height_ft=amsl_height_ft,
        lighting_code=lighting_code,
        horizontal_accuracy_code=horizontal_accuracy_code,
        vertical_accuracy_code=vertical_accuracy_code,
        mark_indicator_code=mark_indicator_code,
        faa_study_number=faa_study_number,
        action=action,
        julian_date=julian_date,
    )


def matches_state_filter(record: DOFObstacleRecord, state_filter: Collection[str]) -> bool:
    normalized = {token.upper().strip() for token in state_filter}
    state_identifier = (record.state_identifier or "").upper()
    return (
        state_identifier in normalized
        or record.country_identifier.upper() in normalized
        or record.oas_code.upper() in normalized
    )


def normalize_state_filter(states: Collection[str] | None) -> set[str] | None:
    if not states:
        return None

    normalized = {state.strip().upper() for state in states if state.strip()}
    if not normalized:
        return None

    for state in normalized:
        if len(state) != 2:
            raise ValueError(
                f"Invalid state filter '{state}'. Expected 2-character state identifiers."
            )
    return normalized


def parse_dof_file(
    input_path: Path,
    state_filter: Collection[str] | None = None,
    error_stream: TextIO | None = None,
    record_handler: Callable[[DOFObstacleRecord], None] | None = None,
) -> ParseSummary:
    """Parse DOF records from an input file with best-effort error handling."""
    active_error_stream = error_stream if error_stream is not None else sys.stderr
    normalized_filter = normalize_state_filter(state_filter)
    summary = ParseSummary(file_count=1)

    with input_path.open("r", encoding="utf-8", errors="replace") as input_file:
        for line_number, raw_line in enumerate(input_file, start=1):
            line = raw_line.rstrip("\r\n")
            if not is_record_line(line):
                continue

            summary.scanned_record_lines += 1
            try:
                record = parse_dof_line(line, line_number)
            except ValueError as exc:
                summary.error_count += 1
                print(f"{input_path}:{line_number}: parse error: {exc}", file=active_error_stream)
                continue

            if normalized_filter and not matches_state_filter(record, normalized_filter):
                summary.skipped_by_state_count += 1
                continue

            summary.parsed_count += 1
            if record_handler is not None:
                record_handler(record)
            else:
                summary.records.append(record)

    return summary


def parse_dof_directory(
    input_dir: Path,
    state_filter: Collection[str] | None = None,
    error_stream: TextIO | None = None,
    record_handler: Callable[[DOFObstacleRecord], None] | None = None,
) -> ParseSummary:
    """Parse FAA DOF state files from a directory with best-effort error handling."""
    if not input_dir.exists():
        raise ValueError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise ValueError(f"Input path is not a directory: {input_dir}")

    file_paths = list_dof_state_files(input_dir)
    if not file_paths:
        raise ValueError(
            f"No FAA DOF state files found in {input_dir} (expected names like 49-UT.Dat)."
        )

    summary = ParseSummary()
    for file_path in file_paths:
        file_summary = parse_dof_file(
            input_path=file_path,
            state_filter=state_filter,
            error_stream=error_stream,
            record_handler=record_handler,
        )
        summary.file_count += file_summary.file_count
        summary.scanned_record_lines += file_summary.scanned_record_lines
        summary.parsed_count += file_summary.parsed_count
        summary.skipped_by_state_count += file_summary.skipped_by_state_count
        summary.error_count += file_summary.error_count
        if record_handler is None:
            summary.records.extend(file_summary.records)
    return summary
