"""Tests for AIXM XML parsing."""

from __future__ import annotations

import io

from nasr_aixm2geojson.aixm import (
    _extract_rcc_id_from_href,
    _parse_gml_pos,
    parse_aixm_file,
)
from nasr_aixm2geojson.navaid import NavaidRecord

from xml_builders import build_aixm_navaid_xml, build_full_aixm_xml


def test_parse_gml_pos_lon_lat():
    lon, lat = _parse_gml_pos("-111.979722 40.850556")
    assert lon == -111.979722
    assert lat == 40.850556


def test_parse_gml_pos_positive_values():
    lon, lat = _parse_gml_pos("10.5 20.3")
    assert lon == 10.5
    assert lat == 20.3


def test_parse_gml_pos_whitespace():
    lon, lat = _parse_gml_pos("  -111.979722  40.850556  ")
    assert lon == -111.979722
    assert lat == 40.850556


def test_parse_gml_pos_insufficient_parts():
    import pytest

    with pytest.raises(ValueError, match="at least 2 coordinates"):
        _parse_gml_pos("42.0")


def test_extract_rcc_id_from_href():
    href = (
        "#/faa:SubscriberFile/faa:Member/aixm:RadioCommunicationChannel%5B@gml:id='RCC_0000001'%5D"
    )
    assert _extract_rcc_id_from_href(href) == "RCC_0000001"


def test_extract_rcc_id_non_rcc_href():
    href = "#/faa:SubscriberFile/faa:Member/aixm:VOR%5B@gml:id='VOR_0000001'%5D"
    assert _extract_rcc_id_from_href(href) is None


def test_extract_rcc_id_malformed_href():
    href = "#/faa:SubscriberFile/faa:Member/aixm:RadioCommunicationChannel"
    assert _extract_rcc_id_from_href(href) is None


def test_parse_aixm_file_basic(tmp_aixm_file):
    xml = build_full_aixm_xml()
    path = tmp_aixm_file(xml)

    records: list[NavaidRecord] = []
    summary, effective_date = parse_aixm_file(
        input_path=path,
        record_handler=records.append,
    )

    assert summary.navaid_count == 1
    assert summary.error_count == 0
    assert effective_date == "2025-11-27T00:00:00.000-05:00"
    assert len(records) == 1

    record = records[0]
    assert record.navaid_type == "VOR_DME"
    assert record.designator == "SLC"
    assert record.name == "SALT LAKE CITY"
    assert record.longitude == -111.979722
    assert record.latitude == 40.850556
    assert record.elevation_ft == 4220.0
    assert record.frequency_mhz == 116.80
    assert record.channel == "115X"
    assert record.navaid_class == "H-VORW/DME"
    assert record.navaid_status == "OPERATIONAL IFR"
    assert record.state_name == "UTAH"
    assert record.administrative_area == "UT"
    assert record.associated_city == "SALT LAKE CITY"


def test_parse_aixm_file_ndb_no_channel(tmp_aixm_file):
    xml = build_full_aixm_xml(
        navaid_kwargs=dict(
            navaid_type="NDB",
            designator="AMF",
            name="AMBLER",
            lon="-157.860150",
            lat="67.105242",
            elevation_ft="258.4",
            navaid_class="HW",
            state_name="ALASKA",
            admin_area="AK",
            city_name="AMBLER",
        ),
        rcc_kwargs=dict(frequency_mhz="403", channel=""),
    )
    path = tmp_aixm_file(xml)

    records: list[NavaidRecord] = []
    summary, _ = parse_aixm_file(input_path=path, record_handler=records.append)

    assert summary.navaid_count == 1
    assert len(records) == 1
    record = records[0]
    assert record.navaid_type == "NDB"
    assert record.frequency_mhz == 403.0
    assert record.channel is None


def test_parse_aixm_file_tacan(tmp_aixm_file):
    xml = build_full_aixm_xml(
        navaid_kwargs=dict(
            navaid_type="TACAN",
            designator="BER",
            name="ADAK",
            lon="-176.674111",
            lat="51.871231",
            elevation_ft="408.0",
            navaid_class="H-TACAN",
            state_name="ALASKA",
            admin_area="AK",
            city_name="ADAK ISLAND",
        ),
        rcc_kwargs=dict(frequency_mhz="113.00", channel="77X"),
    )
    path = tmp_aixm_file(xml)

    records: list[NavaidRecord] = []
    summary, _ = parse_aixm_file(input_path=path, record_handler=records.append)

    assert summary.navaid_count == 1
    record = records[0]
    assert record.navaid_type == "TACAN"
    assert record.designator == "BER"
    assert record.frequency_mhz == 113.0
    assert record.channel == "77X"


def test_parse_aixm_file_no_rcc_match(tmp_aixm_file):
    """Navaid referencing a non-existent RCC should still parse with None freq."""
    xml = build_aixm_navaid_xml(rcc_refs=["RCC_NONEXISTENT"])
    path = tmp_aixm_file(xml)

    records: list[NavaidRecord] = []
    summary, _ = parse_aixm_file(input_path=path, record_handler=records.append)

    assert summary.navaid_count == 1
    record = records[0]
    assert record.frequency_mhz is None
    assert record.channel is None


def test_parse_aixm_file_skips_unknown_type(tmp_aixm_file):
    xml = build_aixm_navaid_xml(navaid_type="UNKNOWN_TYPE")
    path = tmp_aixm_file(xml)

    records: list[NavaidRecord] = []
    summary, _ = parse_aixm_file(input_path=path, record_handler=records.append)

    assert summary.navaid_count == 0
    assert len(records) == 0


def test_parse_aixm_file_no_handler(tmp_aixm_file):
    xml = build_full_aixm_xml()
    path = tmp_aixm_file(xml)

    summary, effective_date = parse_aixm_file(input_path=path)

    assert summary.navaid_count == 1
    assert summary.rcc_count == 1
    assert effective_date is not None


def test_parse_aixm_file_error_reporting(tmp_aixm_file):
    """Malformed XML within a member should be reported, not crash."""
    # Build XML with a navaid missing the designator (required field)
    xml = build_aixm_navaid_xml(designator="SLC")
    # Corrupt a required element to test error tolerance
    xml = xml.replace("<aixm:designator>SLC</aixm:designator>", "")
    path = tmp_aixm_file(xml)

    errors = io.StringIO()
    records: list[NavaidRecord] = []
    summary, _ = parse_aixm_file(
        input_path=path, error_stream=errors, record_handler=records.append
    )

    # Missing designator means the navaid is skipped (returns None), not counted as error
    assert summary.navaid_count == 0
    assert len(records) == 0


def test_parse_aixm_effective_date(tmp_aixm_file):
    xml = build_full_aixm_xml(navaid_kwargs=dict(valid_from="2026-01-22T00:00:00.000-05:00"))
    path = tmp_aixm_file(xml)

    _, effective_date = parse_aixm_file(input_path=path)
    assert effective_date == "2026-01-22T00:00:00.000-05:00"
