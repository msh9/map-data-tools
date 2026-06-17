# faa-vfr-fetch specification

## Goals
- Programmatically fetch current FAA VFR chart packages for:
  - Sectional charts
  - Terminal Area Charts (TAC)
- Extract packages into folder layout compatible with
  `tilemaker/raster-tilemaker/data/raw/`.
- Keep extracted FLY files from TAC archives for downstream use.
- Record provenance metadata for each run.

## Inputs
- FAA visual chart publication endpoints at `https://aeronav.faa.gov/visual/`.
- Optional explicit cycle (`MM-DD-YYYY`) or automatic cycle discovery.
- Output directory (defaults to `tilemaker/raster-tilemaker/data/raw`).

## Behavior
- Auto-cycle mode:
  - Enumerate cycle directories from `/visual/`.
  - Select newest cycle where both:
    - `/All_Files/Sectional.zip`
    - `/All_Files/Terminal.zip`
    are available.
- Package discovery:
  - Sectional: `/sectional-files/`
  - TAC: `/tac-files/`
- Layout:
  - For each zip, write to `<output>/<zip_stem>/<zip_name>`.
  - Extract zip contents into the same `<output>/<zip_stem>/` directory.

## Output
- Downloaded zip archives and extracted files in raw data layout.
- Manifest JSON file `faa-vfr-fetch-manifest-<cycle>.json` containing:
  - cycle and chart types
  - package URL and local zip path
  - status (downloaded/skipped-existing/dry-run)
  - size and selected HTTP metadata

## Non-goals
- Automatic scheduled refresh.
- Deleting non-current charts.
- Any downstream chart processing/tiling.
