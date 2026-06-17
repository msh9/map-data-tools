# Synthetic GeoTIFF fixtures

These small GeoTIFFs mimic FAA chart characteristics for end-to-end testing.

## Contents
- `Synthetic_Chart_A.tif` + `Synthetic_Chart_A.htm`
- `Synthetic_Chart_B.tif` + `Synthetic_Chart_B.htm`

## Features
- Lambert Conformal Conic CRS (NAD83) with differing central meridians.
- Embedded GeoTIFF tags: `Series_Name`, `Publication_Date`, `Originator`.
- Sidecar HTML metadata with `dc.coverage` bounds for crop testing.
- RGB imagery with a simple gradient for non-blank tiles.

## Intended usage
- Pass the `.tif` paths to `raster-tilemaker build-tiles` in tests.
- Use `--use-coverage-bounds` to validate HTML sidecar cropping.

These fixtures are generated with rasterio and are intentionally small to keep
CI fast.
