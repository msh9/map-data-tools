# raster-tilemaker

Prepares raster map data for use by other flyer maps applications.
`raster-tilemaker` is a batch-oriented offline utility that builds tiled raster
outputs from a single GDAL VRT input (typically a virtual mosaic of
pre-processed COGs).

## Setup
```bash
poetry install
```

`raster-tilemaker` uses the GDAL Python bindings at runtime (`osgeo`).
GDAL/`osgeo` must be available in the runtime environment before running the CLI.

## Commands
```bash
poetry run raster-tilemaker build-tiles --input-vrt /path/to/mosaic.vrt
poetry run raster-tilemaker build-tiles --input-vrt /path/to/mosaic.vrt --resolution 2560 --resolution 1280
poetry run raster-tilemaker build-tiles --input-vrt /path/to/mosaic.vrt --output-kind pmtiles
poetry run raster-tilemaker build-tiles --input-vrt /path/to/mosaic.vrt --output-kind pmtiles --pmtiles-file sectionals.pmtiles
poetry run pytest
poetry run ruff check .
```

Tile resolutions default to the ADR-005 ladder (2560..20 m/px). Override with
repeatable `--resolution` flags or `--config path/to/config.json`.

## Example workflows
```bash
# Build default ZXY output (tile_output/tiles + tile_output/tile_config.json)
poetry run raster-tilemaker build-tiles --input-vrt /tmp/sectionals.vrt

# Build PMTiles output (tile_output/tiles.pmtiles + tile_output/tiles-config.json)
poetry run raster-tilemaker build-tiles \
  --input-vrt /tmp/sectionals.vrt \
  --output-kind pmtiles

# Build PMTiles with custom filename and output directory
poetry run raster-tilemaker build-tiles \
  --input-vrt /tmp/sectionals.vrt \
  --output-kind pmtiles \
  --pmtiles-file sectionals.pmtiles \
  --output-dir ./build/sectionals

# Build multi-resolution pmtiles for FAA terminal area charts
poetry run raster-tilemaker build-tiles --input-vrt ../../third-party-static-data/processed_charts/tac-conus-mosaic.clip.jxl.vrt --quality 40 --format avif --resolution 80 --resolution 40 --resolution 20 --output-kind pmtiles --pmtiles-file tac-conus.pmtiles
```

## Inputs and outputs
Input:
- `--input-vrt` (required): a single GDAL VRT path.
- VRT band contract: exactly 3-band `RGB` or 4-band `RGBA` input.

Output (`tile_output/` by default):
- `tile_config.json` + `tiles/{z}/{x}/{y}.{format}` (`--output-kind zxy`, default).
- `{pmtiles-stem}.pmtiles` + `{pmtiles-stem}-config.json` (`--output-kind pmtiles`).
- Example PMTiles pair by default: `tiles.pmtiles` + `tiles-config.json`.

ZXY tile directories use zero-based z indices aligned with the resolution list
(e.g., `tiles/0/` for 2560 m/px). PMTiles output omits fully empty tiles.
Tile origin is based on the effective VRT extent; changing the input mosaic
extent changes x/y addressing and requires full output regeneration.

Config JSON keeps schema version `1.0`; `sources` is emitted as an empty list
for the VRT-backed workflow.

Mask behavior:
- For `RGB` input, output alpha is derived from GDAL mask/nodata.
- For `RGBA` input, output alpha starts from band 4 and then applies GDAL
  mask/nodata on top.

## Module layout
- `src/raster_tilemaker/config.py`: shared constants.
- `src/raster_tilemaker/grid.py`: zoom/grid math for tile pyramids.
- `src/raster_tilemaker/render/mosaic.py`: GDAL VRT metadata + tile rendering.
- `src/raster_tilemaker/output/pmtiles.py`: PMTiles archive writer.
- `src/raster_tilemaker/tile_config.py`: tile config generation.
- `src/raster_tilemaker/pipeline.py`: orchestration for `build_mosaic_output`.
- `src/raster_tilemaker/build_tiles.py`: `build-tiles` CLI command.

## Containerization

The project is containerized with the intent of running on GCP Cloud Run. There is no particular reason preventing the containers use elsewhere though.

### Cloud run hints

The application uses GCP's beta feature to attach a 10GB ephemeral storage drive to the cloud run instances for temporary data storage and write staging. The use of the attached storage drive is configured via two environment variables,

- `CPL_TMPDIR` and `TMPDIR` which configure aspects of the underlying GDAL and PIL libraries used by raster-tilemaker.

Additionally, when configured in parallel render mode, multiple instances of the GDAL library are in use. This can cause excessive memory use by GDAL's cache. In order to control this, we set `GDAL_CACHEMAX` to a somewhat arbitrary value of 128MB when run on a 4GB GCP cloud run instance and with three render workers.

The application's behavior is otherwise controlled by container arguments passed in the conventional way.