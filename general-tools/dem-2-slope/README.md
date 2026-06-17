# dem-2-slope

Converts USGS 3DEP 1-arc-second DEM GeoTIFFs into slope-shaded COGs for consumption by the `raster-tilemaker` pipeline.

## Development setup

```bash
poetry install
poetry run pytest
poetry run ruff check .
```

## Usage

```
poetry run dem-2-slope --url-list <path> --slope-threshold <degrees> --clip-regions <geojson> --output-dir <dir> [--vrt-name <filename>] [--smooth-kernel <N>] [--stream] [--verbose]
```

### Arguments

| Argument | Required | Description |
|---|---|---|
| `--url-list` | Yes | Text file with one DEM URL (or local file path) per line |
| `--slope-threshold` | Yes | Slope threshold in degrees; slopes below this become transparent |
| `--clip-regions` | Yes | Path to mountainous regions GeoJSON for clipping |
| `--output-dir` | Yes | Output directory for processed COGs and final VRT |
| `--vrt-name` | No | Filename for the output VRT mosaic (default: `slope-mosaic.vrt`) |
| `--smooth-kernel` | No | Size of the NxN moving average smoothing kernel. At ~30m/pixel, 8 covers ~240m. Omit for no smoothing. |
| `--stream` | No | Stream tiles from S3 via `/vsicurl/` and keep intermediates in RAM (`/vsimem/`). Avoids downloading raw tiles to disk. |
| `--verbose` | No | Enable verbose logging |

### Example

```bash
poetry run dem-2-slope \
  --url-list ../../shared-configuration/usgs-national-map-file-lists/usgs-1-arc-second-dem-generated-mountainous-regions.txt \
  --slope-threshold 15.0 \
  --clip-regions ../../shared-configuration/mountain-regions-masks/mountainous-regions.geojson \
  --output-dir ./processed_slope
```

## Pipeline

For each DEM tile the utility:

1. Downloads the tile (or reads from a local path). With `--stream`, tiles are read directly from S3 via GDAL `/vsicurl/` without downloading.
2. Computes slope in degrees using GDAL DEMProcessing
3. Optionally smooths the slope with an NxN moving average (`--smooth-kernel`)
4. Applies the threshold — slopes below the threshold become transparent
5. Builds 2-band LA (luminance + alpha)
6. Clips to the mountainous regions polygon and reprojects to ESRI:102009
7. Writes a ZSTD-compressed COG
8. Deletes the raw DEM to conserve disk space (skipped in stream mode)

When `--stream` is used, intermediate files are kept in GDAL's `/vsimem/` in-memory filesystem rather than on disk. Only the final COG output is written to disk.

After all tiles are processed, a VRT mosaic is built over the COGs (named `slope-mosaic.vrt` by default, overridable via `--vrt-name`). This VRT feeds into the existing `raster-tilemaker` pipeline.

## Notes

- The slope threshold is specified in degrees (0–90).
- Output COGs are 2-band LA (luminance + alpha) uint8.
- Pixel values represent slope angles in degrees (0–90). Values are **not** normalized to 0–255 — downstream consumers should treat the dataset as having degree units with values concentrated below 30°.
