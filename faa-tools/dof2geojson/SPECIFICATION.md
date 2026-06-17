# dof2geojson specification (M2)

This document describes the initial dof2geojson functionality for Milestone 2.

## Goals (M2)
- Parse FAA Digital Obstacle File (DOF) fixed-width records from FAA-provided files.
- Extract the obstacle fields needed by downstream consumers:
  - WGS84 location (latitude/longitude)
  - obstacle type
  - AGL and AMSL heights
  - lighting type
  - vertical accuracy
- Emit GeoJSON point features for downstream map clients.
- Support best-effort parsing: report per-line parse errors and continue.

## Inputs
- Directory of FAA archive state files (for example `08-CO.Dat`, `49-UT.Dat`).
- Optional single-file input for local/testing workflows.
- Optional state filters using repeated `--state` arguments.

## Output
- GeoJSON `FeatureCollection` file with one Point feature per valid obstacle.
- Output is gzip-compressed by default.
- Per-line parse errors written to stderr with file path and line number.
- Coordinate output modes:
  - Default `wgs84`: `[longitude, latitude]`.
  - Optional `esri:102009`: `[easting, northing]` and collection-level
    `crs.properties.name = urn:ogc:def:crs:ESRI::102009`.
- Optional z coordinate:
  - `--include-amsl-z` appends `heights.amsl.meters` as third element:
    `[x, y, amsl_meters]`.

## CLI
- `poetry run dof2geojson parse-dof --input-dir /path/to/Digital_Obstacle_File --geojson-out obstacles.geojson.gz`
- Optional single-file mode:
  - `poetry run dof2geojson parse-dof --input /path/to/DOF.DAT --geojson-out obstacles.geojson.gz`
- Optional state filtering:
  - `--state UT --state CO --state NV --state ID`
- Optional coordinate system:
  - `--coordinate-system wgs84|esri:102009` (default `wgs84`)
- Optional AMSL z coordinate:
  - `--include-amsl-z`

## Non-goals (this phase)
- Automatic FAA download and refresh workflows.
- Strict RFC7946-only output when using `esri:102009` mode. The utility intentionally emits
  `crs` metadata for downstream processing where all parties agree on CRS usage.
