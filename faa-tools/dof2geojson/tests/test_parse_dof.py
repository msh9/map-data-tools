from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from dof2geojson.dof import (
    decode_horizontal_accuracy,
    decode_lighting,
    decode_mark_indicator,
    decode_verification_status,
    decode_vertical_accuracy,
    list_dof_state_files,
    parse_dof_directory,
    parse_dof_file,
    parse_dof_line,
)
from tilemaker_shared.geojson import (
    COORDINATE_SYSTEM_ESRI_102009,
    build_coordinate_transform,
    normalized_record_to_geojson_feature,
)


def test_parse_dof_line_extracts_required_fields(build_dof_line):
    line = build_dof_line()
    record = parse_dof_line(line, line_number=7)
    normalized = record.to_normalized_dict()

    assert normalized["obstacle_id"] == "49-123456"
    assert normalized["state_identifier"] == "UT"
    assert normalized["location"]["latitude"] == 40.50833333
    assert normalized["location"]["longitude"] == -111.75833333
    assert normalized["obstacle_type"] == "TOWER"
    assert normalized["heights"]["agl"]["feet"] == 850
    assert normalized["heights"]["agl"]["meters"] == 259.08
    assert normalized["heights"]["amsl"]["feet"] == 1320
    assert normalized["heights"]["amsl"]["meters"] == 402.336
    assert normalized["lighting"]["description"] == "Red"
    assert normalized["vertical_accuracy"]["description"] == "+/- 10 ft"
    assert normalized["vertical_accuracy"]["feet"] == 10
    assert normalized["vertical_accuracy"]["meters"] == 3.048


def test_parse_dof_line_supports_south_and_east_coordinates(build_dof_line):
    line = build_dof_line(
        lat_deg="12",
        lat_min="05",
        lat_sec="30.00",
        lat_hemi="S",
        lon_deg="045",
        lon_min="10",
        lon_sec="10.00",
        lon_hemi="E",
    )

    record = parse_dof_line(line, line_number=1)
    assert record.latitude == -12.09166667
    assert record.longitude == 45.16944444


def test_parse_dof_line_accepts_blank_accuracy_and_lighting_codes(build_dof_line):
    line = build_dof_line(
        lighting=" ",
        horizontal_accuracy=" ",
        vertical_accuracy=" ",
        mark_indicator=" ",
    )
    record = parse_dof_line(line, line_number=2)
    normalized = record.to_normalized_dict()

    assert normalized["lighting"]["description"] == "Unknown"
    assert normalized["horizontal_accuracy"]["description"] == "Unknown"
    assert normalized["vertical_accuracy"]["description"] == "Unknown"
    assert normalized["mark_indicator"]["description"] == "Unknown"


def test_parse_dof_line_allows_blank_state_for_non_us_records(build_dof_line):
    line = build_dof_line(oas_code="AG", country_identifier="AG", state_identifier="  ")

    record = parse_dof_line(line, line_number=1)
    normalized = record.to_normalized_dict()

    assert record.country_identifier == "AG"
    assert record.state_identifier is None
    assert normalized["state_identifier"] is None


def test_parse_dof_line_rejects_blank_state_for_us_records(build_dof_line):
    line = build_dof_line(country_identifier="US", state_identifier="  ")

    with pytest.raises(ValueError, match="missing state identifier for US record"):
        parse_dof_line(line, line_number=1)


def test_parse_dof_file_is_best_effort_and_reports_errors(tmp_path: Path, build_dof_line):
    good_line_1 = build_dof_line(state_identifier="UT")
    good_line_2 = build_dof_line(
        oas_code="08",
        obstacle_number="654321",
        state_identifier="CO",
        julian_date="2026039",
    )
    bad_line = build_dof_line(julian_date="20X6038")

    input_path = tmp_path / "DOF.DAT"
    input_path.write_text(
        "\n".join(
            [
                "2026-02-07",
                "HEADER LINE",
                "HEADER LINE",
                "-" * 127,
                good_line_1,
                bad_line,
                good_line_2,
            ]
        ),
        encoding="utf-8",
    )

    error_stream = io.StringIO()
    summary = parse_dof_file(input_path=input_path, error_stream=error_stream)

    assert summary.file_count == 1
    assert summary.parsed_count == 2
    assert summary.error_count == 1
    assert len(summary.records) == 2
    assert "parse error" in error_stream.getvalue()
    assert ":6:" in error_stream.getvalue()


def test_parse_dof_file_tolerates_invalid_utf8_bytes(tmp_path: Path, build_dof_line):
    line_bytes = bytearray(
        build_dof_line(country_identifier="US", state_identifier="UT").encode("utf-8")
    )
    line_bytes[18] = 0xD1

    input_path = tmp_path / "DOF.DAT"
    with input_path.open("wb") as input_file:
        input_file.write(bytes(line_bytes))
        input_file.write(b"\n")

    summary = parse_dof_file(input_path=input_path)
    assert summary.file_count == 1
    assert summary.parsed_count == 1
    assert summary.error_count == 0


def test_parse_dof_file_filters_by_state(tmp_path: Path, build_dof_line):
    ut_line = build_dof_line(state_identifier="UT")
    co_line = build_dof_line(oas_code="08", obstacle_number="000002", state_identifier="CO")

    input_path = tmp_path / "DOF.DAT"
    input_path.write_text("\n".join([ut_line, co_line]), encoding="utf-8")

    summary = parse_dof_file(input_path=input_path, state_filter={"UT"})
    assert summary.file_count == 1
    assert summary.parsed_count == 1
    assert summary.skipped_by_state_count == 1
    assert summary.records[0].state_identifier == "UT"


def test_parse_dof_file_filters_non_us_records_by_country_with_blank_state(
    tmp_path: Path, build_dof_line
):
    input_path = tmp_path / "DOF.DAT"
    input_path.write_text(
        build_dof_line(oas_code="AG", country_identifier="AG", state_identifier="  "),
        encoding="utf-8",
    )

    summary = parse_dof_file(input_path=input_path, state_filter={"AG"})
    assert summary.file_count == 1
    assert summary.parsed_count == 1
    assert summary.error_count == 0
    assert summary.records[0].country_identifier == "AG"
    assert summary.records[0].state_identifier is None


def test_decode_tables_cover_required_popup_fields():
    assert decode_lighting("R") == "Red"
    assert decode_vertical_accuracy("B") == ("+/- 10 ft", 10)
    assert decode_horizontal_accuracy("2") == ("+/- 50 ft", 50)
    assert decode_verification_status("O") == "Verified"
    assert decode_mark_indicator("P") == "Orange or Orange and White Paint"


def test_normalized_record_to_geojson_feature_uses_point_and_excludes_location(build_dof_line):
    record = parse_dof_line(build_dof_line(), line_number=2)
    normalized = record.to_normalized_dict()

    feature = normalized_record_to_geojson_feature(normalized)
    assert feature["type"] == "Feature"
    assert feature["geometry"] == {
        "type": "Point",
        "coordinates": [-111.75833333, 40.50833333],
    }
    assert "location" not in feature["properties"]
    assert feature["properties"]["state_identifier"] == "UT"


def test_normalized_record_to_geojson_feature_can_include_amsl_z(build_dof_line):
    record = parse_dof_line(build_dof_line(), line_number=3)
    normalized = record.to_normalized_dict()

    feature = normalized_record_to_geojson_feature(normalized, include_amsl_z=True)
    assert feature["geometry"]["coordinates"] == [-111.75833333, 40.50833333, 402.336]


def test_normalized_record_to_geojson_feature_can_project_to_esri_102009(build_dof_line):
    record = parse_dof_line(build_dof_line(), line_number=4)
    normalized = record.to_normalized_dict()
    transform = build_coordinate_transform(COORDINATE_SYSTEM_ESRI_102009)

    feature = normalized_record_to_geojson_feature(
        normalized,
        coordinate_transform=transform,
    )

    coordinates = feature["geometry"]["coordinates"]
    assert len(coordinates) == 2
    assert round(coordinates[0], 6) == -1247788.196368
    assert round(coordinates[1], 6) == 166073.217645


def test_list_dof_state_files_only_returns_state_data_files(tmp_path: Path):
    input_dir = tmp_path / "Digital_Obstacle_File"
    input_dir.mkdir()
    (input_dir / "49-UT.Dat").write_text("x", encoding="utf-8")
    (input_dir / "08-CO.dat").write_text("x", encoding="utf-8")
    (input_dir / "README.txt").write_text("x", encoding="utf-8")
    (input_dir / "do_not_use.DAT").write_text("x", encoding="utf-8")

    files = list_dof_state_files(input_dir)
    assert [path.name for path in files] == ["08-CO.dat", "49-UT.Dat"]


def test_parse_dof_directory_aggregates_file_summaries(tmp_path: Path, build_dof_line):
    input_dir = tmp_path / "Digital_Obstacle_File"
    input_dir.mkdir()
    (input_dir / "49-UT.Dat").write_text(
        "\n".join([build_dof_line(state_identifier="UT"), build_dof_line(julian_date="20X6038")]),
        encoding="utf-8",
    )
    (input_dir / "08-CO.Dat").write_text(
        build_dof_line(state_identifier="CO", oas_code="08", obstacle_number="654321"),
        encoding="utf-8",
    )

    summary = parse_dof_directory(input_dir=input_dir, state_filter={"UT"})
    assert summary.file_count == 2
    assert summary.parsed_count == 1
    assert summary.skipped_by_state_count == 1
    assert summary.error_count == 1


def test_parse_dof_directory_parses_sample_fixture_records(
    dof_sample_fixture_dir: Path,
):
    summary = parse_dof_directory(input_dir=dof_sample_fixture_dir)
    assert summary.file_count == 4
    assert summary.parsed_count == 10
    assert summary.error_count == 0
    assert summary.skipped_by_state_count == 0


def test_sample_fixture_manifest_matches_fixture_directory(dof_sample_fixture_dir: Path):
    manifest_path = dof_sample_fixture_dir / "sample_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["sample_size"] == 10
    assert manifest["seed"] == 1

    total_lines = 0
    for file_path in dof_sample_fixture_dir.glob("*.Dat"):
        with file_path.open("r", encoding="utf-8") as fixture_file:
            total_lines += sum(1 for line in fixture_file if line.strip())

    assert total_lines == manifest["sample_size"]
