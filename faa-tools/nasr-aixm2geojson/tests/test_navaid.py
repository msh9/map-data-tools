"""Tests for NavaidRecord data model and normalization."""

from __future__ import annotations

from nasr_aixm2geojson.navaid import NavaidRecord


def _make_record(**overrides) -> NavaidRecord:
    defaults = dict(
        navaid_type="VOR_DME",
        designator="SLC",
        name="SALT LAKE CITY",
        latitude=40.850556,
        longitude=-111.979722,
        elevation_ft=4220.0,
        frequency_mhz=116.80,
        channel="115X",
        navaid_class="H-VORW/DME",
        navaid_status="OPERATIONAL IFR",
        state_name="UTAH",
        administrative_area="UT",
        associated_city="SALT LAKE CITY",
    )
    defaults.update(overrides)
    return NavaidRecord(**defaults)


def test_navaid_record_frozen():
    record = _make_record()
    import pytest

    with pytest.raises(AttributeError):
        record.designator = "OGD"


def test_to_normalized_dict_full():
    record = _make_record()
    d = record.to_normalized_dict()

    assert d["navaid_id"] == "SLC-VOR_DME"
    assert d["navaid_type"] == "VOR_DME"
    assert d["designator"] == "SLC"
    assert d["name"] == "SALT LAKE CITY"
    assert d["location"] == {"latitude": 40.850556, "longitude": -111.979722}
    assert d["elevation"]["feet"] == 4220.0
    assert d["elevation"]["meters"] == 1286.256
    assert d["frequency"] == {"mhz": 116.80, "channel": "115X"}
    assert d["navaid_class"] == "H-VORW/DME"
    assert d["navaid_status"] == "OPERATIONAL IFR"
    assert d["state_name"] == "UTAH"
    assert d["administrative_area"] == "UT"
    assert d["associated_city"] == "SALT LAKE CITY"


def test_to_normalized_dict_ndb_no_channel():
    record = _make_record(
        navaid_type="NDB",
        frequency_mhz=403.0,
        channel=None,
    )
    d = record.to_normalized_dict()

    assert d["frequency"] == {"mhz": 403.0}
    assert "channel" not in d["frequency"]


def test_to_normalized_dict_no_frequency():
    record = _make_record(frequency_mhz=None, channel=None)
    d = record.to_normalized_dict()

    assert "frequency" not in d


def test_to_normalized_dict_no_elevation():
    record = _make_record(elevation_ft=None)
    d = record.to_normalized_dict()

    assert "elevation" not in d


def test_to_normalized_dict_optional_fields_none():
    record = _make_record(
        navaid_class=None,
        navaid_status=None,
        state_name=None,
        administrative_area=None,
        associated_city=None,
    )
    d = record.to_normalized_dict()

    assert "navaid_class" not in d
    assert "navaid_status" not in d
    assert "state_name" not in d
    assert "administrative_area" not in d
    assert "associated_city" not in d


def test_to_normalized_dict_location_not_in_properties():
    record = _make_record()
    d = record.to_normalized_dict()

    # location should be present for geojson conversion but should be
    # removed from properties by the geojson module
    assert "location" in d
    assert isinstance(d["location"], dict)


def test_elevation_meters_conversion():
    record = _make_record(elevation_ft=100.0)
    d = record.to_normalized_dict()
    assert d["elevation"]["meters"] == 30.48


def test_navaid_id_format():
    record = _make_record(designator="BER", navaid_type="TACAN")
    d = record.to_normalized_dict()
    assert d["navaid_id"] == "BER-TACAN"
