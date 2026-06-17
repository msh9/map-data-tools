"""Tests for shared GeoJSON output and coordinate transformation utilities."""

from __future__ import annotations

import io
import json

import pytest

from tilemaker_shared.geojson import (
    COORDINATE_SYSTEM_WGS84,
    ESRI_102009_CRS_URN,
    GeoJSONFeatureCollectionWriter,
    build_coordinate_transform,
    build_esri_102009_coordinate_transform,
    normalized_record_to_geojson_feature,
)


def test_esri_102009_projection_known_point():
    """HRO VOR/DME position must project to within 1m of the authoritative GeoJSON value.

    Reference coordinates come from the ESRI:102009 GeoJSON output for HRO VOR/DME
    (Harrison, AR) as written by the nasr-aixm2geojson parser: [235804.89, -380638.79].
    WGS84 input from NASR XML: lon=-93.213272°, lat=36.318308°.
    """
    transform = build_esri_102009_coordinate_transform()
    x, y = transform(-93.213272, 36.318308)

    ref_x = 235804.89
    ref_y = -380638.79

    assert abs(x - ref_x) < 1.0, f"x error {abs(x - ref_x):.2f}m exceeds 1m tolerance"
    assert abs(y - ref_y) < 1.0, f"y error {abs(y - ref_y):.2f}m exceeds 1m tolerance"


def test_feature_collection_writer_empty():
    stream = io.StringIO()
    writer = GeoJSONFeatureCollectionWriter(stream)
    writer.close()

    result = json.loads(stream.getvalue())
    assert result["type"] == "FeatureCollection"
    assert result["features"] == []


def test_feature_collection_writer_multiple_features():
    stream = io.StringIO()
    writer = GeoJSONFeatureCollectionWriter(stream)
    writer.write_feature({"type": "Feature", "geometry": None, "properties": {"id": 1}})
    writer.write_feature({"type": "Feature", "geometry": None, "properties": {"id": 2}})
    writer.close()

    result = json.loads(stream.getvalue())
    assert len(result["features"]) == 2
    assert result["features"][0]["properties"]["id"] == 1
    assert result["features"][1]["properties"]["id"] == 2


def test_feature_collection_writer_with_crs():
    stream = io.StringIO()
    writer = GeoJSONFeatureCollectionWriter(stream, crs_name=ESRI_102009_CRS_URN)
    writer.close()

    result = json.loads(stream.getvalue())
    assert result["crs"]["type"] == "name"
    assert result["crs"]["properties"]["name"] == ESRI_102009_CRS_URN


def test_normalized_record_to_geojson_feature_wgs84():
    record: dict[str, object] = {
        "location": {"latitude": 36.318308, "longitude": -93.213272},
        "name": "HRO",
    }
    feature = normalized_record_to_geojson_feature(record)

    assert feature["type"] == "Feature"
    geometry = feature["geometry"]
    assert isinstance(geometry, dict)
    assert geometry["type"] == "Point"
    coords = geometry["coordinates"]
    assert isinstance(coords, list)
    assert len(coords) == 2
    assert abs(coords[0] - (-93.213272)) < 1e-6
    assert abs(coords[1] - 36.318308) < 1e-6
    assert feature["properties"] == {"name": "HRO"}


def test_normalized_record_to_geojson_feature_with_amsl_z():
    record: dict[str, object] = {
        "location": {"latitude": 36.0, "longitude": -93.0},
        "heights": {"amsl": {"meters": 250.0}},
    }
    feature = normalized_record_to_geojson_feature(record, include_amsl_z=True)

    coords = feature["geometry"]["coordinates"]  # type: ignore[index]
    assert isinstance(coords, list)
    assert len(coords) == 3
    assert coords[2] == 250.0


def test_build_coordinate_transform_wgs84_is_identity():
    transform = build_coordinate_transform(COORDINATE_SYSTEM_WGS84)
    x, y = transform(-93.0, 36.0)
    assert x == -93.0
    assert y == 36.0


def test_build_coordinate_transform_unknown_raises():
    with pytest.raises(ValueError, match="Unsupported coordinate system"):
        build_coordinate_transform("invalid-crs")
