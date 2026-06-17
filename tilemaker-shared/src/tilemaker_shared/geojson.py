"""GeoJSON output and coordinate transformation utilities."""

from __future__ import annotations

import json
import math
from typing import Callable, TextIO

COORDINATE_SYSTEM_WGS84 = "wgs84"
COORDINATE_SYSTEM_ESRI_102009 = "esri:102009"
ESRI_102009_CRS_URN = "urn:ogc:def:crs:ESRI::102009"
NAD83_GRS80_MAJOR_AXIS_METERS = 6378137.0
NAD83_GRS80_INV_FLATTENING = 298.257222101
ESRI_102009_STANDARD_PARALLEL_1_DEGREES = 20.0
ESRI_102009_STANDARD_PARALLEL_2_DEGREES = 60.0
ESRI_102009_LATITUDE_OF_ORIGIN_DEGREES = 40.0
ESRI_102009_CENTRAL_MERIDIAN_DEGREES = -96.0


class GeoJSONFeatureCollectionWriter:
    """Incrementally write a GeoJSON FeatureCollection to a stream."""

    def __init__(self, stream: TextIO, crs_name: str | None = None) -> None:
        self._stream = stream
        self._feature_count = 0
        if crs_name is None:
            self._stream.write('{"type":"FeatureCollection","features":[')
            return

        crs = {"type": "name", "properties": {"name": crs_name}}
        self._stream.write('{"type":"FeatureCollection","crs":')
        self._stream.write(json.dumps(crs, sort_keys=True))
        self._stream.write(',"features":[')

    def write_feature(self, feature: dict[str, object]) -> None:
        if self._feature_count > 0:
            self._stream.write(",")
        self._stream.write(json.dumps(feature, sort_keys=True))
        self._feature_count += 1

    def close(self) -> None:
        self._stream.write("]}\n")


def normalized_record_to_geojson_feature(
    normalized_record: dict[str, object],
    coordinate_transform: Callable[[float, float], tuple[float, float]] | None = None,
    include_amsl_z: bool = False,
) -> dict[str, object]:
    """Convert a normalized record into a GeoJSON Point feature."""
    location = normalized_record.get("location")
    if not isinstance(location, dict):
        raise ValueError("normalized record is missing location object")

    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if not isinstance(latitude, (float, int)) or not isinstance(longitude, (float, int)):
        raise ValueError("normalized record location must include numeric latitude/longitude")

    transform = coordinate_transform or identity_coordinate_transform
    x, y = transform(float(longitude), float(latitude))
    coordinates: list[float] = [x, y]
    if include_amsl_z:
        coordinates.append(extract_amsl_meters(normalized_record))

    properties = {key: value for key, value in normalized_record.items() if key != "location"}
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": coordinates,
        },
        "properties": properties,
    }


def feature_collection_crs_name(coordinate_system: str) -> str | None:
    if coordinate_system == COORDINATE_SYSTEM_ESRI_102009:
        return ESRI_102009_CRS_URN
    return None


def extract_amsl_meters(normalized_record: dict[str, object]) -> float:
    heights = normalized_record.get("heights")
    if not isinstance(heights, dict):
        raise ValueError("normalized record is missing heights object")

    amsl = heights.get("amsl")
    if not isinstance(amsl, dict):
        raise ValueError("normalized record is missing heights.amsl object")

    meters = amsl.get("meters")
    if not isinstance(meters, (float, int)):
        raise ValueError("normalized record heights.amsl.meters must be numeric")
    return float(meters)


def build_coordinate_transform(
    coordinate_system: str,
) -> Callable[[float, float], tuple[float, float]]:
    if coordinate_system == COORDINATE_SYSTEM_WGS84:
        return identity_coordinate_transform

    if coordinate_system == COORDINATE_SYSTEM_ESRI_102009:
        return build_esri_102009_coordinate_transform()

    raise ValueError(f"Unsupported coordinate system: {coordinate_system}")


def identity_coordinate_transform(lon: float, lat: float) -> tuple[float, float]:
    return float(lon), float(lat)


def build_esri_102009_coordinate_transform() -> Callable[[float, float], tuple[float, float]]:
    major_axis = NAD83_GRS80_MAJOR_AXIS_METERS
    flattening = 1.0 / NAD83_GRS80_INV_FLATTENING
    eccentricity = math.sqrt((2.0 * flattening) - (flattening * flattening))

    phi_1 = math.radians(ESRI_102009_STANDARD_PARALLEL_1_DEGREES)
    phi_2 = math.radians(ESRI_102009_STANDARD_PARALLEL_2_DEGREES)
    phi_0 = math.radians(ESRI_102009_LATITUDE_OF_ORIGIN_DEGREES)
    lambda_0 = math.radians(ESRI_102009_CENTRAL_MERIDIAN_DEGREES)

    def m(phi: float) -> float:
        return math.cos(phi) / math.sqrt(1.0 - (eccentricity * math.sin(phi)) ** 2)

    def t(phi: float) -> float:
        eccentricity_sin_phi = eccentricity * math.sin(phi)
        ratio = (1.0 - eccentricity_sin_phi) / (1.0 + eccentricity_sin_phi)
        return math.tan((math.pi / 4.0) - (phi / 2.0)) / (ratio ** (eccentricity / 2.0))

    m_1 = m(phi_1)
    m_2 = m(phi_2)
    t_1 = t(phi_1)
    t_2 = t(phi_2)
    t_0 = t(phi_0)
    n = (math.log(m_1) - math.log(m_2)) / (math.log(t_1) - math.log(t_2))
    f = m_1 / (n * (t_1**n))
    rho_0 = major_axis * f * (t_0**n)

    def project(lon: float, lat: float) -> tuple[float, float]:
        phi = math.radians(lat)
        lambda_value = math.radians(lon)
        rho = major_axis * f * (t(phi) ** n)
        theta = n * (lambda_value - lambda_0)
        x = rho * math.sin(theta)
        y = rho_0 - (rho * math.cos(theta))
        return float(x), float(y)

    return project
