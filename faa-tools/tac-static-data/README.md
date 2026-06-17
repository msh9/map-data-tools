# !!!Note well this utility is in flux and not in use, TAC masks are hand generated -- 2026-02-10!!! #

# TAC Static Data Utility (POC)

This utility generates:
- a heuristic **binary chart mask PNG** for a TAC GeoTIFF, and
- a heuristic **coverage GeoJSON** (`Polygon` or `MultiPolygon`) derived from
  the mask.

The current approach is intentionally rough-cut and is designed to produce
auto-generated geometries that are close enough for transparent-background
rendering and subsequent manual cleanup.

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install numpy rasterio pillow
```

## Generate a debug mask
```bash
python generate_tac_mask_debug.py \
  --input ../../tilemaker/raster-tilemaker/data/raw/Salt_Lake_City_TAC/Salt\ Lake\ City\ TAC.tif \
  --output /tmp/salt-lake-city-tac-mask.png \
  --full-mask-output /tmp/salt-lake-city-tac-mask.png \
  --corners-json /tmp/salt-lake-city-tac-corners.json \
  --geojson-output /tmp/salt-lake-city-tac-coverage.geojson \
  --debug-prefix /tmp/salt-lake-city-tac-debug
```

## Processing flow and heuristics

The script processes a chart in these stages:

1. Downsample and normalize bands
- The input is downsampled to `--max-size` (default `512`) using nearest-neighbor.
- For paletted GeoTIFFs (common for TACs), the palette is used for color-aware comparisons.

2. Seed a candidate background mask from border colors
- The most common edge value (or RGB tuple) is chosen as the background seed.
- `--tolerance` controls how loosely pixels can match that seed.
- Default `--tolerance 0` is conservative for paletted TACs to reduce false background matches.

3. Expand background hints using dark-neatline rows/columns
- Dark pixels (`RGB sum <= --ink-threshold`) are counted per row/column.
- If a row/column exceeds `--neatline-coverage`, all rows/columns outside those bounds are marked background.
- This helps edge flood-fill avoid stopping at non-map annotations near borders.

4. Flood-fill background from image edges
- Connected background pixels reachable from the outer border are treated as outside.
- The inverse of outside pixels is the raw chart candidate mask.

5. Build a conservative core component
- The raw mask is eroded `--core-erode-iterations` times, largest component selected, then dilated back.
- This suppresses thin bridges from map body to corner legend artifacts.

6. Add extension components near the core
- Components in `raw - core` are scored and optionally kept as extensions.
- A component is kept only if it passes all gating checks:
  - Area >= `--extension-min-area`
  - Area <= `core_area * --extension-max-area-ratio`
  - If dense (`fill_ratio > --extension-max-fill-ratio`), it must be thin
    (`min bbox dimension <= --extension-max-thickness`)
  - It must be attachable to core within `--extension-gap` pixels
  - It must not protrude beyond core bounds by more than the configured
    overhang limits (`--extension-max-overhang-*`)
- This aims to keep off-neatline map callouts/labels while rejecting large
  detached legend blocks.

7. Final cleanup and geometry conversion
- Optional closing (`--close-iterations`, default `0`) is applied last.
- Small final components are pruned using `--extension-min-area`.
- Non-main islands are then filtered; only east-edge islands that satisfy
  `--island-east-*` thresholds are preserved.
- The final raster mask is polygonized with `rasterio.features.shapes` and transformed to WGS84.
- Output geometry may be `Polygon` or `MultiPolygon`.

## Defaults tuned for SLC TAC rough-cut

Important defaults:
- `--tolerance 0`
- `--close-iterations 0`
- `--extension-gap 6`
- `--extension-max-overhang 24`
- `--extension-max-overhang-north 7` (effective default when not provided)
- `--extension-max-overhang-south 7` (effective default when not provided)
- `--island-east-band-width 64`
- `--island-east-min-area 8`
- `--island-east-min-span 2`

These defaults bias toward:
- avoiding top-left legend bleed-in (like the terrain legend area), and
- allowing modest off-neatline protrusions to be captured as additional polygons.

## Debug artifacts

When `--debug-prefix /tmp/foo` is provided, the utility writes:
- `/tmp/foo-background.png`
- `/tmp/foo-raw.png`
- `/tmp/foo-core.png`
- `/tmp/foo-extensions.png`
- `/tmp/foo-final.png`
- `/tmp/foo-components.json`

`components.json` includes per-component area, bbox, fill ratio, overhang, and
keep/reject reason for tuning heuristics.

## Typical tuning sequence

1. If corner legends leak into mask:
- keep `--close-iterations 0`
- reduce `--extension-gap`
- reduce `--extension-max-overhang-north` / `--extension-max-overhang-south`
- increase `--extension-min-area`
- tighten `--island-east-*` if east-side noise is also present

2. If off-neatline callouts are missing:
- increase `--extension-gap` slightly
- increase `--extension-max-overhang-east`
- reduce `--extension-min-area`
- loosen `--island-east-*` thresholds as needed

3. If dense non-map blobs are included:
- lower `--extension-max-fill-ratio`
- lower `--extension-max-thickness`

## Run tests
```bash
python -m unittest discover -s tests -p "test_*.py"
```

The suite includes a fixture-backed regression test using
`tests/fixtures/slc_downsample_stage_snapshot.npz` plus
`tests/fixtures/slc_hand_oracle_mask_512.npz` derived from
`third-party-static-data/terminal-area-fly-chart-masks/Salt_Lake_City_TAC.geojson`. It guards:
- top-left legend artifact remains excluded from the final mask, and
- a small right-edge off-neatline extension remains included,
- IoU against the hand-edited oracle mask stays above threshold, and
- non-main output component count remains bounded.
