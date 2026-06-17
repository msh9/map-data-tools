"""Integration tests for the nasr-aixm2geojson CLI."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from nasr_aixm2geojson.cli import main as cli_main

from xml_builders import build_full_aixm_xml, extract_members


def test_cli_parse_navaids_produces_geojson(tmp_path: Path):
    xml = build_full_aixm_xml()
    input_file = tmp_path / "NAV_AIXM.xml"
    input_file.write_text(xml, encoding="utf-8")
    output_file = tmp_path / "navaids.geojson.gz"

    result = cli_main(
        ["parse-navaids", "--input", str(input_file), "--geojson-out", str(output_file)]
    )
    assert result == 0
    assert output_file.exists()

    with gzip.open(output_file, "rt", encoding="utf-8") as f:
        data = json.load(f)

    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1

    feature = data["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Point"

    coords = feature["geometry"]["coordinates"]
    assert len(coords) == 2
    assert coords[0] == -111.979722  # longitude
    assert coords[1] == 40.850556  # latitude

    props = feature["properties"]
    assert props["navaid_type"] == "VOR_DME"
    assert props["designator"] == "SLC"
    assert props["name"] == "SALT LAKE CITY"
    assert props["frequency"]["mhz"] == 116.80
    assert props["frequency"]["channel"] == "115X"


def test_cli_parse_navaids_esri_102009(tmp_path: Path):
    xml = build_full_aixm_xml()
    input_file = tmp_path / "NAV_AIXM.xml"
    input_file.write_text(xml, encoding="utf-8")
    output_file = tmp_path / "navaids.geojson.gz"

    result = cli_main(
        [
            "parse-navaids",
            "--input",
            str(input_file),
            "--geojson-out",
            str(output_file),
            "--coordinate-system",
            "esri:102009",
        ]
    )
    assert result == 0

    with gzip.open(output_file, "rt", encoding="utf-8") as f:
        data = json.load(f)

    assert "crs" in data
    assert data["crs"]["properties"]["name"] == "urn:ogc:def:crs:ESRI::102009"

    coords = data["features"][0]["geometry"]["coordinates"]
    # Projected coordinates should be meters, not degrees
    assert abs(coords[0]) > 1000
    assert abs(coords[1]) > 1000


def test_cli_parse_navaids_requires_geojson_out(tmp_path: Path):
    import pytest

    xml = build_full_aixm_xml()
    input_file = tmp_path / "NAV_AIXM.xml"
    input_file.write_text(xml, encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        cli_main(["parse-navaids", "--input", str(input_file)])
    assert exc_info.value.code != 0


def test_cli_parse_navaids_missing_input(tmp_path: Path):
    output_file = tmp_path / "navaids.geojson.gz"
    result = cli_main(
        ["parse-navaids", "--input", str(tmp_path / "nonexistent.xml"), "--geojson-out", str(output_file)]
    )
    assert result == 1


def test_cli_no_command(capsys):
    result = cli_main([])
    assert result == 1


def test_cli_parse_navaids_wgs84_no_crs(tmp_path: Path):
    xml = build_full_aixm_xml()
    input_file = tmp_path / "NAV_AIXM.xml"
    input_file.write_text(xml, encoding="utf-8")
    output_file = tmp_path / "navaids.geojson.gz"

    cli_main(["parse-navaids", "--input", str(input_file), "--geojson-out", str(output_file)])

    with gzip.open(output_file, "rt", encoding="utf-8") as f:
        data = json.load(f)

    assert "crs" not in data


def test_cli_parse_navaids_multiple_navaids(tmp_path: Path):
    """Test with two navaids sharing an RCC."""
    xml = build_full_aixm_xml(
        navaid_kwargs=dict(designator="SLC", name="SALT LAKE CITY"),
    )
    # Add a second navaid member before the closing tag
    second_navaid_xml = build_full_aixm_xml(
        navaid_kwargs=dict(
            navaid_id="NAVAID_0000002",
            designator="OGD",
            name="OGDEN",
            lon="-111.975",
            lat="41.196",
            elevation_ft="4400.0",
            rcc_refs=["RCC_0000002"],
        ),
        rcc_kwargs=dict(rcc_id="RCC_0000002", frequency_mhz="115.70", channel="104X"),
    )
    # Merge two files: take members from second file and insert into first
    second_members = extract_members(second_navaid_xml)
    combined = xml.replace(
        "</faa:SubscriberFile>",
        "\n".join(second_members) + "\n</faa:SubscriberFile>",
    )
    input_file = tmp_path / "NAV_AIXM.xml"
    input_file.write_text(combined, encoding="utf-8")
    output_file = tmp_path / "navaids.geojson.gz"

    result = cli_main(
        ["parse-navaids", "--input", str(input_file), "--geojson-out", str(output_file)]
    )
    assert result == 0

    with gzip.open(output_file, "rt", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data["features"]) == 2
    designators = {f["properties"]["designator"] for f in data["features"]}
    assert designators == {"SLC", "OGD"}
