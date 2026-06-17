from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from dof2geojson.cli import main


def test_cli_prints_help_without_command(capsys):
    exit_code = main([])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "DOF2GeoJSON CLI" in captured.out


def test_cli_parse_dof_writes_geojson_gzip_and_reports_errors(
    tmp_path: Path, capsys, build_dof_line
):
    valid_line = build_dof_line(state_identifier="UT")
    filtered_line = build_dof_line(
        oas_code="08",
        obstacle_number="654321",
        state_identifier="CO",
        julian_date="2026039",
    )
    invalid_line = build_dof_line(julian_date="20X6038")

    input_dir = tmp_path / "Digital_Obstacle_File"
    geojson_out = tmp_path / "obstacles.geojson.gz"
    input_dir.mkdir()
    (input_dir / "49-UT.Dat").write_text(
        "\n".join([valid_line, invalid_line]),
        encoding="utf-8",
    )
    (input_dir / "08-CO.Dat").write_text(filtered_line, encoding="utf-8")

    exit_code = main(
        [
            "parse-dof",
            "--input-dir",
            str(input_dir),
            "--geojson-out",
            str(geojson_out),
            "--state",
            "UT",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Processed 2 files." in captured.out
    assert "Encountered 1 parse errors" in captured.out
    assert "(gzip)." in captured.out
    assert "parse error" in captured.err

    with gzip.open(geojson_out, mode="rt", encoding="utf-8") as feature_file:
        feature_collection = json.loads(feature_file.read())
    assert feature_collection["type"] == "FeatureCollection"
    assert "crs" not in feature_collection
    assert len(feature_collection["features"]) == 1
    feature = feature_collection["features"][0]
    assert feature["geometry"] == {
        "type": "Point",
        "coordinates": [-111.75833333, 40.50833333],
    }
    assert "location" not in feature["properties"]
    assert feature["properties"]["state_identifier"] == "UT"


def test_cli_parse_dof_requires_geojson_out(tmp_path: Path, build_dof_line):
    input_dir = tmp_path / "Digital_Obstacle_File"
    input_dir.mkdir()
    (input_dir / "49-UT.Dat").write_text(build_dof_line(state_identifier="UT"), encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        main(["parse-dof", "--input-dir", str(input_dir)])
    assert exc_info.value.code != 0


def test_cli_parse_dof_with_sample_fixture_data(
    tmp_path: Path,
    capsys,
    dof_sample_fixture_dir: Path,
):
    geojson_out = tmp_path / "sample-obstacles.geojson.gz"
    exit_code = main(
        [
            "parse-dof",
            "--input-dir",
            str(dof_sample_fixture_dir),
            "--geojson-out",
            str(geojson_out),
            "--state",
            "UT",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Processed 4 files." in captured.out
    assert "Wrote 2 records" in captured.out
    assert "Encountered 0 parse errors" in captured.out

    with gzip.open(geojson_out, mode="rt", encoding="utf-8") as feature_file:
        feature_collection = json.loads(feature_file.read())
    assert feature_collection["type"] == "FeatureCollection"
    assert len(feature_collection["features"]) == 2
    for feature in feature_collection["features"]:
        assert feature["geometry"]["type"] == "Point"
        assert "location" not in feature["properties"]


def test_cli_parse_dof_can_emit_esri_102009_coordinates_and_crs(
    tmp_path: Path, capsys, build_dof_line
):
    input_dir = tmp_path / "Digital_Obstacle_File"
    geojson_out = tmp_path / "obstacles-esri.geojson.gz"
    input_dir.mkdir()
    (input_dir / "49-UT.Dat").write_text(build_dof_line(state_identifier="UT"), encoding="utf-8")

    exit_code = main(
        [
            "parse-dof",
            "--input-dir",
            str(input_dir),
            "--geojson-out",
            str(geojson_out),
            "--coordinate-system",
            "esri:102009",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Encountered 0 parse errors" in captured.out

    with gzip.open(geojson_out, mode="rt", encoding="utf-8") as feature_file:
        feature_collection = json.loads(feature_file.read())
    assert feature_collection["crs"]["type"] == "name"
    assert feature_collection["crs"]["properties"]["name"] == "urn:ogc:def:crs:ESRI::102009"
    feature = feature_collection["features"][0]
    coordinates = feature["geometry"]["coordinates"]
    assert len(coordinates) == 2
    assert coordinates != [-111.75833333, 40.50833333]


def test_cli_parse_dof_include_amsl_z_adds_third_coordinate(tmp_path: Path, capsys, build_dof_line):
    input_dir = tmp_path / "Digital_Obstacle_File"
    geojson_out = tmp_path / "obstacles-z.geojson.gz"
    input_dir.mkdir()
    (input_dir / "49-UT.Dat").write_text(build_dof_line(state_identifier="UT"), encoding="utf-8")

    exit_code = main(
        [
            "parse-dof",
            "--input-dir",
            str(input_dir),
            "--geojson-out",
            str(geojson_out),
            "--include-amsl-z",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Encountered 0 parse errors" in captured.out

    with gzip.open(geojson_out, mode="rt", encoding="utf-8") as feature_file:
        feature_collection = json.loads(feature_file.read())
    assert "crs" not in feature_collection
    feature = feature_collection["features"][0]
    assert feature["geometry"]["coordinates"] == [-111.75833333, 40.50833333, 402.336]
