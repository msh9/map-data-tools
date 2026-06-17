# faa-vfr-fetch

`faa-vfr-fetch` downloads FAA VFR chart GeoTIFF packages and extracts them into
`tilemaker/raster-tilemaker/data/raw/`-style folders.

Current scope:
- Sectional chart packages (`sectional-files/*.zip`)
- Terminal Area Chart packages (`tac-files/*_TAC.zip`)
- Preserve all extracted files, including TAC companion FLY files

## Development setup

```bash
poetry install
poetry run faa-vfr-fetch --help
poetry run pytest
poetry run ruff check .
```

## Fetch latest published sectional + TAC packages

```bash
poetry run faa-vfr-fetch fetch \
  --cycle auto \
  --chart-type sectional \
  --chart-type tac \
  --output-dir ../../../tilemaker/raster-tilemaker/data/raw
```

## Notes

- `--cycle auto` discovers the most recent published FAA cycle by probing
  `https://aeronav.faa.gov/visual/<cycle>/All_Files/Sectional.zip` and
  `.../Terminal.zip`.
- Default behavior skips existing non-empty zip archives. Use `--force` to
  redownload.
- By default archives are extracted in place. Use `--no-extract` to keep only zip files.
- Each run writes a manifest file:
  `faa-vfr-fetch-manifest-<cycle>.json` in the output directory.
