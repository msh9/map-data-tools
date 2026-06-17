from __future__ import annotations

import json
from pathlib import Path

from raster_tilemaker.coverage.common import (
    CoverageFeature,
    CoverageIndex,
    normalize_chart_name,
    _validate_geometry,
)

TacCoverageFeature = CoverageFeature
TacCoverageIndex = CoverageIndex


def _combine_tac_geometries(geometries: list[dict[str, object]]) -> dict[str, object]:
    if len(geometries) == 1:
        return geometries[0]

    multipolygon_coords: list[object] = []
    for geometry in geometries:
        geometry_type = geometry.get("type")
        if geometry_type == "Polygon":
            multipolygon_coords.append(geometry["coordinates"])
        elif geometry_type == "MultiPolygon":
            multipolygon_coords.extend(geometry["coordinates"])  # type: ignore[arg-type]
        else:  # pragma: no cover - guarded by _validate_geometry
            raise ValueError(f"Unsupported TAC geometry type: {geometry_type!r}")

    return {"type": "MultiPolygon", "coordinates": multipolygon_coords}


def load_tac_coverage_index(path: Path) -> TacCoverageIndex:
    if not path.is_dir():
        raise ValueError(f"TAC coverage path must be a directory: {path}")

    by_chart_name: dict[str, CoverageFeature] = {}
    for geojson_path in sorted(path.glob("*.geojson")):
        payload = json.loads(geojson_path.read_text(encoding="utf-8"))
        if payload.get("type") != "FeatureCollection":
            raise ValueError(
                f"TAC coverage file must be a GeoJSON FeatureCollection: {geojson_path}"
            )
        features = payload.get("features")
        if not isinstance(features, list) or not features:
            raise ValueError(
                "TAC coverage FeatureCollection must include at least one feature: "
                f"{geojson_path}"
            )

        geometries: list[dict[str, object]] = []
        for feature in features:
            if not isinstance(feature, dict):
                raise ValueError(f"TAC coverage feature must be an object: {geojson_path}")
            geometries.append(_validate_geometry(feature.get("geometry")))

        chart_name = geojson_path.stem
        key = normalize_chart_name(chart_name)
        by_chart_name[key] = CoverageFeature(
            chart=chart_name,
            geometry=_combine_tac_geometries(geometries),
            source_fields={"source_file": geojson_path.name},
        )

    return CoverageIndex(by_chart_name=by_chart_name)
