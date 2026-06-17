"""Tests for GeoJSON output and coordinate transformation utilities."""

from __future__ import annotations

from tilemaker_shared.geojson import build_esri_102009_coordinate_transform


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
