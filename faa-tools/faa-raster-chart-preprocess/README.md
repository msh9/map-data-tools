# faa-raster-chart-preprocess

Converts FAA VFR chart GeoTIFFs into Cloud Optimized GeoTIFFs (COGs) and assembles per-region VRT mosaics for the `raster-tilemaker` pipeline.

Provides two subcommands:

- `preprocess`: create processed chart COG outputs from FAA raw GeoTIFFs
- `build-region-mosaics`: build per-region VRT mosaics from processed outputs

## Development setup

```bash
poetry install
poetry run pytest
poetry run ruff check .
```

## Chart types and input structure

Raw chart processing reads from `third-party-static-data/raw_charts`.

Supported chart types:

- `sectional`: `* SEC.tif` files in folders that do not end with `_TAC`
- `tac`: `* TAC*.tif` files in folders ending with `_TAC`
- `fly`: `* FLY.tif` files in folders ending with `_TAC`

For each processed chart source TIFF, `preprocess` writes two outputs:

- full/unclipped COG with WEBP lossy compression at quality 40
- clipped COG using coverage masks and one of two modes:
  - `zstd` (default): ZSTD + predictor 2 + level 20 + 512x512 blocks
  - `jxl-lossless`: JXL lossless + effort 7 + 512x512 blocks

Mask directories (relative to `shared-configuration/`):

- sectional uses `sectional-chart-masks/`
- TAC and FLY use `terminal-area-fly-chart-masks/`

Processing uses GDAL raster pipeline `tee`, where the full WEBP output is written as a side pipeline and the main flow continues to clip + write the clipped output.

Threading is controlled by `--threads`. This value is applied to:

- reproject stage via `reproject --num-threads=<threads>`
- COG output writes via `--co NUM_THREADS=<threads>`

If a chart folder contains multiple TIFF files, each TIFF is processed independently. Output filenames include additional type markers for TAC/FLY:

- TAC outputs include `.tac.` before `.webp.cog.tif` / `.clip.<mode>.cog.tif`
- FLY outputs include `.fly.` before `.webp.cog.tif` / `.clip.<mode>.cog.tif`

## Special-case skips

The following chart TIFFs are intentionally skipped:

- `Honolulu Inset SEC.tif` (sectional)
- `Anchorage Graphic.tif` (TAC package artifact)
- `Caribbean Planning Chart.tif` (TAC package artifact)
- `New York TAC VFR Planning Charts.tif` (TAC package artifact)

These are companion planning/graphic artifacts, not TAC/FLY map layers for this pipeline.

## Example usage

### `preprocess`

Process one chart folder:

```bash
poetry run faa-raster-chart-preprocess \
  preprocess \
  --chart Denver
```

Process one TAC package, TAC + FLY:

```bash
poetry run faa-raster-chart-preprocess \
  preprocess \
  --chart Salt_Lake_City_TAC \
  --chart-type tac \
  --chart-type fly
```

Process all available charts (all chart types):

```bash
poetry run faa-raster-chart-preprocess \
  preprocess \
  --all-charts
```

When `--all-charts` is used, continue-on-error is enabled automatically so one failing chart does not stop processing of remaining sources.

Use a custom output root:

```bash
poetry run faa-raster-chart-preprocess \
  preprocess \
  --chart Denver_TAC \
  --output-root /tmp/processed_charts
```

Enable verbose stage logging:

```bash
poetry run faa-raster-chart-preprocess \
  preprocess \
  --chart Denver \
  --verbose
```

Use JXL lossless for clipped outputs:

```bash
poetry run faa-raster-chart-preprocess \
  preprocess \
  --all-charts \
  --threads 8 \
  --clipped-output-mode jxl-lossless
```

Note: for backward compatibility, invoking the CLI without an explicit subcommand still routes to `preprocess`.

### `build-region-mosaics`

Build sectional region mosaics from `processed_charts`:

```bash
poetry run faa-raster-chart-preprocess \
  build-region-mosaics \
  --chart-type sectional
```

Build TAC region mosaics:

```bash
poetry run faa-raster-chart-preprocess \
  build-region-mosaics \
  --chart-type tac \
  --file-match-token .clip.
```

Build FLY region mosaics (dry-run):

```bash
poetry run faa-raster-chart-preprocess \
  build-region-mosaics \
  --chart-type fly \
  --dry-run
```

Mosaic output naming:

- sectional: `sectional-<region>-mosaic.clip.jxl.vrt`
- tac: `tac-<region>-mosaic.clip.jxl.vrt`
- fly: `fly-<region>-mosaic.clip.jxl.vrt`
