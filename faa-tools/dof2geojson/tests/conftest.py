from __future__ import annotations

from pathlib import Path

import pytest


def _build_dof_line(
    *,
    oas_code: str = "49",
    obstacle_number: str = "123456",
    verification_status: str = "O",
    country_identifier: str = "US",
    state_identifier: str = "UT",
    city_name: str = "SALT LAKE CITY",
    lat_deg: str = "40",
    lat_min: str = "30",
    lat_sec: str = "30.00",
    lat_hemi: str = "N",
    lon_deg: str = "111",
    lon_min: str = "45",
    lon_sec: str = "30.00",
    lon_hemi: str = "W",
    obstacle_type: str = "TOWER",
    quantity: str = "2",
    agl_height: str = "00850",
    amsl_height: str = "01320",
    lighting: str = "R",
    horizontal_accuracy: str = "2",
    vertical_accuracy: str = "B",
    mark_indicator: str = "P",
    faa_study_number: str = "2025STUDY0001",
    action: str = "A",
    julian_date: str = "2026038",
) -> str:
    line = [" "] * 127

    def put(start: int, end: int, value: str) -> None:
        width = end - start + 1
        padded = value.ljust(width)
        line[start - 1 : end] = list(padded[:width])

    put(1, 2, oas_code)
    put(3, 3, "-")
    put(4, 9, obstacle_number)
    put(11, 11, verification_status)
    put(13, 14, country_identifier)
    put(16, 17, state_identifier)
    put(19, 34, city_name)
    put(36, 37, lat_deg)
    put(39, 40, lat_min)
    put(42, 46, lat_sec)
    put(47, 47, lat_hemi)
    put(49, 51, lon_deg)
    put(53, 54, lon_min)
    put(56, 60, lon_sec)
    put(61, 61, lon_hemi)
    put(63, 80, obstacle_type)
    put(82, 82, quantity)
    put(84, 88, agl_height)
    put(90, 94, amsl_height)
    put(96, 96, lighting)
    put(98, 98, horizontal_accuracy)
    put(100, 100, vertical_accuracy)
    put(102, 102, mark_indicator)
    put(104, 117, faa_study_number)
    put(119, 119, action)
    put(121, 127, julian_date)
    return "".join(line)


@pytest.fixture
def build_dof_line():
    return _build_dof_line


@pytest.fixture
def dof_sample_fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures" / "digital_obstacle_file_sample"
