# nasr-aixm2geojson

`nasr-aixm2geojson` is a utility for converting FAA NASR AIXM data to GeoJSON.

Current scope is NASR AIXM 5.1 Navigation Aid parsing into GeoJSON point features.

## Development setup

```bash
poetry install
poetry run nasr-aixm2geojson --help
poetry run pytest
poetry run ruff check .
```

## Parse NASR AIXM navaids

```bash
poetry run nasr-aixm2geojson parse-navaids \
  --input ./NAV_AIXM.xml \
  --geojson-out navaids.geojson.gz
```

For projected ESRI:102009 coordinates (for tippecanoe preprocessing):

```bash
poetry run nasr-aixm2geojson parse-navaids \
  --input ./NAV_AIXM.xml \
  --coordinate-system esri:102009 \
  --geojson-out navaids-esri102009.geojson.gz
```

Notes:
- Parsing is best-effort. Invalid elements are reported to stderr.
- Frequency and channel data are resolved from linked RadioCommunicationChannel elements.
- GeoJSON output defaults to a `FeatureCollection` of WGS84 Point features.
- `--coordinate-system esri:102009` writes projected easting/northing coordinates and includes GeoJSON `crs` metadata.
- Output is gzip-compressed by default.

## Generate PMTiles for web-tilelayer

After parsing with `--coordinate-system esri:102009`, convert the GeoJSON to PMTiles with tippecanoe:

```bash
tippecanoe \
  -o march19-navaids.pmtiles \
  -l navaids \
  -s EPSG:3857 \
  -z9 \
  navaids-march19.geojson.gz
```

Use `-z9` (not `-zg`) to ensure adequate position precision. At zoom 9 the MVT resolution
is ~78 m/pixel, giving sub-pixel accuracy for navaid point features. Using `-zg` auto-selects
max_zoom=2 (~2446 m/pixel) which causes a systematic ~7 km westward position offset due to
floor-based MVT pixel quantization.
