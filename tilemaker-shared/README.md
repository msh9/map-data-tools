# tilemaker-shared

Shared GeoJSON output and coordinate transformation utilities used by `dof2geojson` and `nasr-aixm2geojson`. Not intended for standalone use — consumed as a Poetry path dependency.

## Public API

All public symbols are in `tilemaker_shared.geojson`:

- `GeoJSONFeatureCollectionWriter` — streaming GeoJSON `FeatureCollection` writer; call `write_feature()` for each feature and `close()` to finalise the JSON.
- `normalized_record_to_geojson_feature(record, *, coordinate_transform, include_amsl_z)` — converts a normalized record dict (with a `location` sub-dict) into a GeoJSON `Feature`.
- `build_coordinate_transform(coordinate_system)` — returns a callable `(lon, lat) -> (x, y)` for the given system string (`"wgs84"` or `"esri:102009"`).
- `build_esri_102009_coordinate_transform()` — Lambert Conformal Conic projection matching ESRI:102009; implemented in pure Python (no GDAL required).
- `identity_coordinate_transform()` — pass-through transform for WGS84 output.
- `feature_collection_crs_name(coordinate_system)` — returns the GeoJSON `crs.properties.name` string for a coordinate system, or `None` for WGS84.
- `extract_amsl_meters(normalized)` — extracts `heights.amsl.meters` from a normalized dict.
- Constants: `COORDINATE_SYSTEM_WGS84`, `COORDINATE_SYSTEM_ESRI_102009`, `ESRI_102009_CRS_URN`, and the six ESRI:102009 Lambert projection parameters.

## Development setup

```bash
poetry install
poetry run pytest
poetry run ruff check src/ tests/
```

Tests do not require GDAL or network access.
