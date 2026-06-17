# Synthetic output fixtures

This folder contains pre-generated raster-tilemaker outputs for end-to-end tests.
They are generated from the synthetic GeoTIFFs in ../source and include only
minimal tiles needed for verification.

## Contents
- tile_config.json
- tiles/0/0/0.webp
- tiles/1/1/1.webp

## Regeneration
Run from the raster-tilemaker repo root:
  /home/michael/projects/flyer-maps/tilemaker/raster-tilemaker/.venv/bin/poetry run \
    raster-tilemaker build-tiles \
    --chart tests/fixtures/e2e/source/Synthetic_Chart_A.tif \
    --chart tests/fixtures/e2e/source/Synthetic_Chart_B.tif \
    --output-dir /tmp/tilemaker-e2e-output \
    --use-coverage-bounds

Then copy the files listed above into this folder.
