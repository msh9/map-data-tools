# raster-tilemaker specification 

This document describes the raster-tilemaker pipeline for Milestone 2. It follows the
ADRs in `../../adr/`, especially CRS, raster tiling, and zooming.

## Goals (M2)
- Generate a 512x512 AVIF or WebP tile pyramid (quality ~30) from a single GDAL
  VRT input.
- Emit a simple tile configuration JSON describing projection,
  supported resolutions, and extents.
- Accept explicit resolution ladders via CLI or JSON config and default to
  ADR-005 resolutions.

## Inputs
- Exactly one GDAL VRT input on disk, provided via `--input-vrt`.
- The VRT is expected to reference pre-processed COGs prepared upstream.
- The application carries through the VRT projection and does not reproject to a
  fixed CRS.
- Supported raster shapes: 1 band (`Gray`), 2 bands (`LA`), 3 bands (`RGB`),
  or 4 bands (`RGBA`). For 1-2 band input, PNG format is recommended to
  preserve data fidelity for non-photographic content.

## Outputs
- A single output directory containing:
  - `tile_config.json`
  - `tiles/{z}/{x}/{y}.{format}` (`--output-kind zxy`, default), or
  - `tiles.pmtiles` (`--output-kind pmtiles`)

The output root is configurable (default: `tile_output/` in this repo).

## Tile config fields
- `schemaVersion`: "1.0"
- `crs.type`: "wkt"
- `crs.value`: WKT from the input VRT projection
- `tile.tileSizePx`: 512
- `tile.format`: "avif", "webp", or "png" (default: "webp")
- `tile.origin`: [minX, maxY] from the VRT bounds
- `tile.resolutions`: list of supported resolutions, coarse to fine
- `extent.crsUnits`: aggregate [minX, minY, maxX, maxY]
- `extent.wgs84`: [minLon, minLat, maxLon, maxLat]
- `sources[]`: empty list in the VRT-backed workflow

## Resolution handling
- Default resolutions follow ADR-005: 2560, 1280, 640, 320, 160, 80, 40, 20.
- If `--config` is provided, read `resolutions` from the JSON file.
- If `--resolution` flags are provided, use those values.
- Resolution lists must be positive and listed from coarse to fine.
- Resolutions must be part of the ADR-005 ladder (otherwise error).

## Tiling algorithm
- Use the effective aggregate tiled-data origin from ADR-002:
  `origin = (minX, maxY)`.
- For each resolution in order, compute the tile index range that intersects
  the aggregate bounds and render only those tiles.
- Tile directories use zero-based z indices aligned with the resolutions list
  (coarsest resolution -> `z=0`, finest -> `z=N-1`).
- PMTiles output may apply a zoom offset to satisfy PMTiles tile-id bounds while
  preserving local x/y addresses. Local-to-PMTiles zoom mapping is emitted in
  PMTiles metadata for debugging.
- For each tile x,y compute bounds:
  - `minX = originX + x * tileSpan`
  - `maxX = minX + tileSpan`
  - `maxY = originY - y * tileSpan`
  - `minY = maxY - tileSpan`
- Read and resample directly from the input VRT into a 512x512 tile image.
- Resampling uses GDAL warp `cubic`.
- For `Gray` input, output is LA; alpha derived from GDAL mask/nodata.
- For `LA` input, output is LA; source alpha with GDAL mask/nodata on top.
- For `RGB` input, output is RGBA; alpha derived from GDAL mask/nodata.
- For `RGBA` input, output is RGBA; source alpha with GDAL mask/nodata on top.
- In `pmtiles` mode, fully empty/no-data tiles are omitted from the archive.
- Because origin depends on input VRT extent, changing the mosaic extent changes
  tile x/y addresses. Full output regeneration is required when input extent changes.

## CLI
- `poetry run raster-tilemaker build-tiles --input-vrt path/to/mosaic.vrt`
- Optional: `--format avif|webp|png` (default: webp)
- Optional: `--config path/to/config.json` (file must exist)
- Optional: repeatable `--resolution 2560` (ignored when `--config` is provided)
- Optional: `--output-kind zxy|pmtiles` (default: `zxy`)
- Optional: `--pmtiles-file tiles.pmtiles` (used with `--output-kind pmtiles`)

## Non-goals
- Building source COGs or building the VRT input (handled upstream).
- Any functionality listed as non-goals in upstream project specifications.
