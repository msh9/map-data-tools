from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

Geometry = dict[str, object]


def normalize_chart_name(name: str) -> str:
    normalized = " ".join(name.replace("_", " ").replace("-", " ").split())
    lowered = normalized.lower()
    if lowered.endswith(" sec"):
        normalized = normalized[:-4]
    elif lowered.endswith(" sectional"):
        normalized = normalized[: -len(" sectional")]
    return "".join(ch for ch in normalized.lower() if ch.isalnum())


def _validate_geometry(geometry: object) -> Geometry:
    if not isinstance(geometry, dict):
        raise ValueError("Coverage feature geometry must be an object.")

    geometry_type = geometry.get("type")
    if geometry_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(
            f"Unsupported coverage geometry type: {geometry_type!r}. "
            "Only Polygon and MultiPolygon are supported."
        )
    if "coordinates" not in geometry:
        raise ValueError("Coverage geometry is missing coordinates.")
    return geometry


@dataclass(frozen=True)
class CoverageFeature:
    chart: str
    geometry: Geometry
    source_fields: dict[str, str]


@dataclass(frozen=True)
class CoverageIndex:
    by_chart_name: dict[str, CoverageFeature]

    def get(self, chart_name: str) -> CoverageFeature | None:
        return self.by_chart_name.get(normalize_chart_name(chart_name))


def load_coverage_index(path: Path) -> CoverageIndex:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError("Coverage file must be a GeoJSON FeatureCollection.")

    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("Coverage FeatureCollection is missing features list.")

    by_chart_name: dict[str, CoverageFeature] = {}
    for feature in features:
        if not isinstance(feature, dict):
            raise ValueError("Coverage feature must be an object.")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("Coverage feature properties must be an object.")

        chart = properties.get("chart")
        if not isinstance(chart, str) or not chart.strip():
            raise ValueError("Coverage feature is missing properties.chart.")
        chart = chart.strip()

        geometry = _validate_geometry(feature.get("geometry"))
        source_fields = properties.get("source_fields")
        if not isinstance(source_fields, dict):
            source_fields = {}

        key = normalize_chart_name(chart)
        by_chart_name[key] = CoverageFeature(
            chart=chart,
            geometry=geometry,
            source_fields={str(k): str(v) for k, v in source_fields.items()},
        )

    return CoverageIndex(by_chart_name=by_chart_name)
