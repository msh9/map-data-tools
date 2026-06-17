# dof2geojson

`dof2geojson` is a utility application for converting FAA DOF records to GeoJSON.

Current scope is FAA Digital Obstacle File (DOF) parsing into GeoJSON point features.

## Development setup

```bash
poetry install
poetry run dof2geojson --help
poetry run pytest
poetry run ruff check .
```

NB the follow examples assume a downloaded and extract digital obstacle archive in the 'dof-extract' directory.

## Parse FAA DOF input

```bash
poetry run dof2geojson parse-dof \
  --input-dir ./dof-extract/ \
  --state UT --state CO --state NV --state ID \
  --geojson-out obstacle-records.geojson.gz
```

Single-file mode is also supported:

```bash
poetry run dof2geojson parse-dof \
  --input ./dof-extract/DOF.DAT \
  --geojson-out obstacle-records.geojson.gz
```

For projected ESRI:102009 coordinates (for tippecanoe preprocessing):

```bash
poetry run dof2geojson parse-dof \
  --input-dir ./dof-extract/ \
  --state UT --state CO --state NV --state ID \
  --coordinate-system esri:102009 \
  --geojson-out obstacle-records-esri102009.geojson.gz
```

To append AMSL meters as a z coordinate:

```bash
poetry run dof2geojson parse-dof \
  --input-dir ./dof-extract/ \
  --include-amsl-z \
  --geojson-out obstacle-records-3d.geojson.gz
```

Notes:
- Parsing is best-effort. Invalid record lines are reported to stderr with line numbers.
- In single-file `DOF.DAT` mode, non-US records with a blank state field are accepted.
- US records still require a populated 2-character state identifier.
- Input text decoding is tolerant (`utf-8` with replacement for invalid bytes) so malformed
  bytes do not terminate parsing.
- GeoJSON output defaults to a `FeatureCollection` of WGS84 Point features.
- `--coordinate-system esri:102009` writes projected easting/northing coordinates and includes
  GeoJSON `crs` metadata: `urn:ogc:def:crs:ESRI::102009`.
- Output is gzip-compressed by default.
- If `--geojson-out` is omitted, output defaults to `obstacles.geojson.gz`.
- `--include-amsl-z` appends `heights.amsl.meters` as the third coordinate element.
