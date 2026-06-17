# TAC Mask POC TODO

## Status summary (2026-02-06)
- Shifted from corner-only output to staged mask processing with polygon/multipolygon output.
- Added side-aware extension overhang controls:
  - north/south default effectively 7
  - west/east default to `--extension-max-overhang` (24 by default)
- Added post-assembly island filtering to drop non-main components unless they
  qualify as east-edge islands (`--island-east-*` controls).
- Added oracle fixture testing against hand-edited
  `third-party-static-data/terminal-area-fly-chart-masks/Salt_Lake_City_TAC.geojson`.

## Current behavior (SLC TAC defaults)
- Output now trends toward one main polygon plus, at most, small east-edge
  islands when present.
- Top-left legend bleed remains excluded.
- Right-edge off-neatline extension signal is preserved in extension stage.

## Regression fixtures
- `tests/fixtures/slc_downsample_stage_snapshot.npz`: raw/core snapshot used to
  exercise extension selection deterministically.
- `tests/fixtures/slc_hand_oracle_mask_512.npz`: rasterized hand-edited oracle
  mask for IoU and false-positive/false-negative bounds.

## Next possible improvements
- Add optional contour simplification knob for geometry output.
- Add a second TAC oracle fixture to reduce overfitting to SLC-specific style.
- Add a dedicated edge-color class feature (magenta/cyan/black emphasis) for
  extension scoring.
